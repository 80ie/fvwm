#!/usr/bin/env python3
"""Native FvwmPager embedded in the QNX Photon shelf.

FvwmPager supplies the useful behaviour here: button 1 changes page and
button 2 drags miniature windows. It calculates its page grid at startup, so
the shelf changes width in discrete steps and starts a fresh pager each time.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import QProcess, QSize, QTimer
from PyQt6.QtGui import QPalette, QWindow
from PyQt6.QtWidgets import QApplication, QWidget

from Xlib import X, display, error as xerror

import photon


class WorldView(QWidget):
    """Find and reparent the shelf-specific FvwmPager instance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.PAGER_DESK)
        self.setPalette(pal)

        try:
            self.dpy = display.Display()
        except Exception:
            self.dpy = None
        self.container = None
        self._size = None
        self._find_tries = 0

        self._launch_timer = QTimer(self)
        self._launch_timer.setSingleShot(True)
        self._launch_timer.timeout.connect(self._launch)
        self._find_timer = QTimer(self)
        self._find_timer.setInterval(200)
        self._find_timer.timeout.connect(self._poll_find)

    def natural_height(self, width=None):
        width = self.width() if width is None else width
        screen = QApplication.primaryScreen()
        geometry = screen.geometry() if screen is not None else None
        screen_w = geometry.width() if geometry is not None else 1920
        screen_h = geometry.height() if geometry is not None else 1080
        return max(1, round(width * screen_h / screen_w))

    def sizeHint(self):
        return QSize(photon.SHELF_INNER,
                     self.natural_height(photon.SHELF_INNER))

    def showEvent(self, event):
        super().showEvent(event)
        self._queue_launch()

    def resizeEvent(self, event):
        if self.container is not None:
            self.container.setGeometry(self.rect())
        self._queue_launch()

    def _queue_launch(self):
        if self.isVisible() and self.width() > 0 and self.height() > 0:
            self._launch_timer.start(50)

    def _launch(self):
        size = (self.width(), self.height())
        if size == self._size and self.container is not None:
            return
        self._size = size
        self._find_timer.stop()
        self._drop_container()
        QProcess.startDetached("FvwmCommand", [
            "ShelfPagerLaunch %d %d" % size,
        ])
        self._find_tries = 0
        self._find_timer.start()

    def _poll_find(self):
        self._find_tries += 1
        pager = self._find_pager()
        if pager is not None:
            self._find_timer.stop()
            self._embed(pager)
        elif self._find_tries >= 25:
            self._find_timer.stop()

    def _find_pager(self):
        if self.dpy is None:
            return None
        try:
            root = self.dpy.screen().root
            atom = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = root.get_full_property(atom, X.AnyPropertyType)
            for wid in (prop.value if prop else []):
                win = self.dpy.create_resource_object("window", wid)
                title = win.get_wm_name() or ""
                classes = win.get_wm_class() or ()
                if title == "ShelfPager" or "ShelfPager" in classes:
                    return win
        except xerror.XError:
            return None
        return None

    def _embed(self, pager):
        self._drop_container()
        window = QWindow.fromWinId(pager.id)
        self.container = QWidget.createWindowContainer(window, self)
        self.container.setGeometry(self.rect())
        self.container.show()
        QTimer.singleShot(0, self._show_container)

    def _show_container(self):
        if self.container is not None and self.isVisible():
            self.container.show()
            self.container.raise_()

    def _drop_container(self):
        if self.container is not None:
            self.container.hide()
            self.container.deleteLater()
            self.container = None

    def closeEvent(self, event):
        self._find_timer.stop()
        self._drop_container()
        QProcess.startDetached("FvwmCommand", ["KillModule FvwmPager ShelfPager"])
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WorldView")
    w = WorldView()
    w.resize(photon.SHELF_INNER, w.natural_height(photon.SHELF_INNER))
    w.setWindowTitle("WorldView")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
