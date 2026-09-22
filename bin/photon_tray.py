#!/usr/bin/env python3
"""System tray for the QNX Photon shelf: stalonetray, embedded.

Every other widget here is drawn; this one is the sole exception, because a
tray icon is somebody else's window rendering itself over the XEmbed
protocol, not a value this process can paint from data.  Writing a native
XEmbed host was on the table and rejected -- stalonetray already speaks the
protocol correctly against every client on this machine, so the job left is
just reparenting its window into ours, the same operation fvwm's `Swallow`
used to perform for the taskbar's tray cell.  `QWindow.fromWinId` plus
`createWindowContainer` is that operation done by us instead of fvwm.

We launch and own stalonetray rather than merely finding one already running:
it holds the `_NET_SYSTEM_TRAY_S0` selection, so a second instance started
behind ours would just exit, and the panel needs to be the one deciding when
it starts and stops.  Finding its window afterward means walking
`_NET_CLIENT_LIST` for a `WM_CLASS` of "stalonetray" -- query_tree from the
root does not see it, because fvwm reparents every top-level window into its
own decoration frame first.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import QProcess, QSize, QSocketNotifier, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPalette, QWindow
from PyQt6.QtWidgets import QApplication, QWidget

from Xlib import X, display, error as xerror

import photon

USERDIR = os.environ.get("FVWM_USERDIR", os.path.expanduser("~/.fvwm"))
RC = os.path.join(USERDIR, "stalonetrayrc")

SLOT_SIZE = 26           # must agree with stalonetrayrc's slot_size
FIND_INTERVAL_MS = 200
FIND_ATTEMPTS = 25       # 5s -- stalonetray's window lands well under this
SYNC_INTERVAL_MS = 250


class TrayWidget(QWidget):

    natural_height_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.FACE)
        self.setPalette(pal)

        try:
            self.dpy = display.Display()
        except Exception:
            self.dpy = None

        self.proc = None
        self.container = None
        self.tray_xid = None
        self.tray_win = None
        self._tray_h = SLOT_SIZE       # one empty row, until told otherwise
        self._columns = 0
        self._launched = False
        self._find_tries = 0
        self._x_notifier = None

        self._find_timer = QTimer(self)
        self._find_timer.setInterval(FIND_INTERVAL_MS)
        self._find_timer.timeout.connect(self._poll_find)
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(SYNC_INTERVAL_MS)
        self._sync_timer.timeout.connect(self._sync_tray_height)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._cleanup)

    def sizeHint(self):
        return QSize(photon.SHELF_INNER, self.natural_height())

    def natural_height(self):
        return self._tray_h + 4   # the sunken well's own outline and lip

    #  -- launch --

    def resizeEvent(self, event):
        interior = photon.sunken_interior(self.rect())
        if self.container is not None:
            self.container.setGeometry(interior)
        if not self._launched and interior.width() > 0:
            self._launched = True
            self._spawn(max(1, interior.width() // SLOT_SIZE))
        elif self._launched:
            columns = max(1, interior.width() // SLOT_SIZE)
            if columns != self._columns:
                self._restart(columns)

    def _spawn(self, columns):
        """Kill any stalonetray already running -- it owns the tray
        selection, so a second one would just exit -- and launch our own, so
        the panel owns its lifetime.  Same pkill-then-exec shape as config's
        StartFunction uses for the panel itself.

        Geometry is a vertical grid sized to the width we were actually
        given, passed on the command line because stalonetrayrc's own header
        says the command line wins.  no_shrink is off (set in stalonetrayrc)
        so the tray's own window shrinks and grows with the icon count, and
        `_sync_tray_height` below follows it.
        """
        subprocess.run(["pkill", "-x", "stalonetray"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self._columns = columns
        self.proc = QProcess(self)
        self.proc.start("stalonetray", [
            "--config", RC,
            "--geometry", "%dx1" % columns,
            "--max-geometry", "%dx0" % columns,
            "--grow-gravity", "NW",
        ])

        self._find_tries = 0
        self._find_timer.start()

    def _restart(self, columns):
        self._find_timer.stop()
        self._sync_timer.stop()
        self._columns = columns
        if self.container is not None:
            self.container.hide()
            self.container.deleteLater()
            self.container = None
        self.tray_win = None
        self.tray_xid = None
        self._tray_h = SLOT_SIZE
        self.updateGeometry()
        self.natural_height_changed.emit()
        self._spawn(columns)

    #  -- finding the window --

    def _poll_find(self):
        self._find_tries += 1
        win = self._find_tray_window()
        if win is not None:
            self._find_timer.stop()
            self._embed(win)
            return
        if self._find_tries >= FIND_ATTEMPTS:
            self._find_timer.stop()

    def _find_tray_window(self):
        if self.dpy is None:
            return None
        pid = self.proc.processId() if self.proc is not None else 0
        try:
            root = self.dpy.screen().root
            atom = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = root.get_full_property(atom, X.AnyPropertyType)
            for wid in (prop.value if prop else []):
                win = self.dpy.create_resource_object("window", wid)
                cls = win.get_wm_class()
                if not cls or "stalonetray" not in cls:
                    continue
                if pid and self._wm_pid(win) not in (None, pid):
                    continue
                return win
        except xerror.XError:
            return None
        return None

    def _wm_pid(self, win):
        try:
            atom = self.dpy.intern_atom("_NET_WM_PID")
            prop = win.get_full_property(atom, X.AnyPropertyType)
            return prop.value[0] if prop else None
        except xerror.XError:
            return None

    #  -- embedding --

    def _embed(self, win):
        self.tray_win = win
        self.tray_xid = win.id
        window = QWindow.fromWinId(self.tray_xid)
        self.container = QWidget.createWindowContainer(window, self)
        self.container.setGeometry(photon.sunken_interior(self.rect()))
        self.container.show()
        QTimer.singleShot(0, self._show_container)

        try:
            win.change_attributes(event_mask=X.StructureNotifyMask)
            self.dpy.flush()
        except xerror.XError:
            pass
        self._x_notifier = QSocketNotifier(
            self.dpy.fileno(), QSocketNotifier.Type.Read, self)
        self._x_notifier.activated.connect(self._drain_x)

        self._sync_tray_height()
        self._sync_timer.start()

    def _show_container(self):
        if self.container is not None and self.isVisible():
            self.container.show()
            self.container.raise_()

    def _drain_x(self):
        try:
            for ev in photon.x_events(self.dpy):
                if (ev.type == X.ConfigureNotify
                        and getattr(ev.window, "id", None) == self.tray_xid):
                    self._sync_tray_height()
        except (xerror.ConnectionClosedError, OSError):
            self._x_notifier.setEnabled(False)
            QApplication.quit()
            return
        except Exception:
            return

    def _sync_tray_height(self):
        """Size the tray from its icon children after Qt reparents it."""
        try:
            bottom = 0
            for child in self.tray_win.query_tree().children:
                g = child.get_geometry()
                if g.x >= 0 and g.y >= 0 and g.width > 1 and g.height > 1:
                    bottom = max(bottom, g.y + g.height)
        except xerror.XError:
            return
        h = max(SLOT_SIZE,
                ((bottom + SLOT_SIZE - 1) // SLOT_SIZE) * SLOT_SIZE)
        if h != self._tray_h:
            self._tray_h = h
            self.updateGeometry()
            self.natural_height_changed.emit()

    #  -- painting --

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)
        photon.sunken(p, self.rect(), photon.WELL)

    #  -- teardown --

    def _cleanup(self):
        self._sync_timer.stop()
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.terminate()
            self.proc.waitForFinished(500)
            if self.proc.state() != QProcess.ProcessState.NotRunning:
                self.proc.kill()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ShelfTray")
    app.setDesktopFileName("ShelfTray")
    w = TrayWidget()
    w.resize(photon.SHELF_INNER, SLOT_SIZE + 4)
    w.setWindowTitle("ShelfTray")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
