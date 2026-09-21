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
        self._launched = False
        self._find_tries = 0
        self._x_notifier = None

        self._find_timer = QTimer(self)
        self._find_timer.setInterval(FIND_INTERVAL_MS)
        self._find_timer.timeout.connect(self._poll_find)

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
            self._spawn(interior.width())

    def _spawn(self, width):
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

        cols = max(1, width // SLOT_SIZE)
        self.proc = QProcess(self)
        self.proc.start("stalonetray", [
            "--config", RC,
            "--geometry", "%dx1" % cols,
            "--max-geometry", "%dx0" % cols,
            "--grow-gravity", "NW",
        ])

        self._find_tries = 0
        self._find_timer.start()

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

        try:
            win.change_attributes(event_mask=X.StructureNotifyMask)
            self.dpy.flush()
        except xerror.XError:
            pass
        self._x_notifier = QSocketNotifier(
            self.dpy.fileno(), QSocketNotifier.Type.Read, self)
        self._x_notifier.activated.connect(self._drain_x)

        self._sync_tray_height()

    def _drain_x(self):
        try:
            for _ in range(self.dpy.pending_events()):
                ev = self.dpy.next_event()
                if (ev.type == X.ConfigureNotify
                        and getattr(ev.window, "id", None) == self.tray_xid):
                    self._sync_tray_height()
        except Exception:
            return

    def _sync_tray_height(self):
        """Follow the embedded window's real height rather than reserving a
        fixed slot count -- stalonetray resizes itself as icons dock and
        undock (no_shrink is off), and the container does not resize it back
        the other way, so this is the only source of truth for how tall the
        tray actually is right now."""
        try:
            h = self.tray_win.get_geometry().height
        except xerror.XError:
            return
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
