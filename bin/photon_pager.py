#!/usr/bin/env python3
"""World View: the QNX Photon shelf's page pager, drawn rather than swallowed.

A component of bin/shelf-panel, and a window of its own when run directly.

This used to be a real FvwmPager reparented into the shelf.  Two things that
buys us by being drawn instead:

  - `FvwmPager` styles the active page by *background colour* and has no
    border option, so the reference's black outline around the current page
    was not reachable and `config` settled for a lighter khaki.  Here it is
    an outline.
  - A swallowed module has to be handed a fresh Geometry every time the
    shelf's width changes, which put a module restart in the middle of a
    live resize.  Nothing to restart now.

Everything comes over EWMH, which fvwm3 implements in both directions:
`_NET_DESKTOP_VIEWPORT` is broadcast from `virtual_scr.Vx/Vy` (`ewmh.c:592`)
*and* accepted as an incoming ClientMessage that calls `MoveViewport()`
(`ewmh_events.c:115`).  So we can read the page and set it without shelling
out to FvwmCommand.

Event-driven: a PropertyNotify selection on the root window, drained through
a QSocketNotifier on Xlib's own connection, so this shares the Qt event loop
rather than polling beside it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import QRect, QSize, QSocketNotifier, Qt
from PyQt6.QtGui import QColor, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

from Xlib import X, display, protocol, error as xerror

import photon

DESK      = QColor("#c3c7b1")   # a page's background
DESK_HI   = QColor("#e1e3d8")   # ... and the current page's, lighter
WIN       = QColor("#bec1c3")   # a mini window
WIN_EDGE  = QColor("#7f8285")
FOCUS     = QColor("#b4b4ff")   # the focused window's mini
FOCUS_EDGE = QColor("#7676aa")
GRID      = QColor("#ffffff")   # the 1px rules between pages

WATCH = ("_NET_DESKTOP_VIEWPORT", "_NET_DESKTOP_GEOMETRY", "_NET_CLIENT_LIST",
         "_NET_ACTIVE_WINDOW", "_NET_CURRENT_DESKTOP")


class WorldView(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.FACE)
        self.setPalette(pal)

        self.pages = (3, 3)
        self.viewport = (0, 0)
        self.windows = []          # (QRect in desktop coords, focused)

        self.dpy = display.Display()
        self.root = self.dpy.screen().root
        self.screen_w = self.dpy.screen().width_in_pixels
        self.screen_h = self.dpy.screen().height_in_pixels
        self.atoms = {name: self.dpy.intern_atom(name) for name in WATCH}
        self.atoms["_NET_WM_STATE"] = self.dpy.intern_atom("_NET_WM_STATE")
        self.atoms["_NET_WM_STATE_SKIP_PAGER"] = self.dpy.intern_atom(
            "_NET_WM_STATE_SKIP_PAGER")
        self.atoms["_NET_WM_STATE_HIDDEN"] = self.dpy.intern_atom(
            "_NET_WM_STATE_HIDDEN")

        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.dpy.flush()
        self._notifier = QSocketNotifier(
            self.dpy.fileno(), QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._drain)

        self.refresh()

    #  -- size --

    def natural_height(self, width=None):
        """A page cell is screen-shaped, so the grid's height follows the
        width.  This is the sum the panel asks for when it lays out."""
        width = self.width() if width is None else width
        inner = max(1, width - 2)
        cols, rows = self.pages
        cell = inner / float(cols)
        return int(round(cell * rows * self.screen_h / self.screen_w)) + 2

    def sizeHint(self):
        return QSize(photon.SHELF_INNER,
                     self.natural_height(photon.SHELF_INNER))

    #  -- X --

    def _drain(self):
        wanted = set(self.atoms[n] for n in WATCH)
        dirty = False
        try:
            for _ in range(self.dpy.pending_events()):
                ev = self.dpy.next_event()
                if ev.type == X.PropertyNotify and ev.atom in wanted:
                    dirty = True
        except Exception:
            return
        if dirty:
            self.refresh()

    def _prop(self, window, name):
        try:
            atom = self.atoms.get(name) or self.dpy.intern_atom(name)
            p = window.get_full_property(atom, X.AnyPropertyType)
        except (xerror.XError, Exception):
            return None
        return list(p.value) if p else None

    def refresh(self):
        geom = self._prop(self.root, "_NET_DESKTOP_GEOMETRY")
        if geom and len(geom) >= 2 and self.screen_w and self.screen_h:
            self.pages = (max(1, geom[0] // self.screen_w),
                          max(1, geom[1] // self.screen_h))
        vp = self._prop(self.root, "_NET_DESKTOP_VIEWPORT")
        if vp and len(vp) >= 2:
            self.viewport = (vp[0], vp[1])

        active = self._prop(self.root, "_NET_ACTIVE_WINDOW")
        active = active[0] if active else 0

        found = []
        for wid in self._prop(self.root, "_NET_CLIENT_LIST") or []:
            try:
                win = self.dpy.create_resource_object("window", wid)
                state = self._prop(win, "_NET_WM_STATE") or []
                if self.atoms["_NET_WM_STATE_SKIP_PAGER"] in state:
                    continue
                if self.atoms["_NET_WM_STATE_HIDDEN"] in state:
                    continue
                g = win.get_geometry()
                #  Geometry is relative to the frame fvwm reparented it into,
                #  so ask the server where it really is.
                t = win.translate_coords(self.root, 0, 0)
            except Exception:
                continue
            found.append((QRect(-t.x, -t.y, g.width, g.height), wid == active))
        self.windows = found
        self.update()

    def _set_page(self, col, row):
        data = [col * self.screen_w, row * self.screen_h, 0, 0, 0]
        ev = protocol.event.ClientMessage(
            window=self.root,
            client_type=self.atoms["_NET_DESKTOP_VIEWPORT"],
            data=(32, data))
        self.root.send_event(
            ev, event_mask=X.SubstructureNotifyMask | X.SubstructureRedirectMask)
        self.dpy.flush()

    #  -- painting --

    def _grid(self):
        """The trough's interior and one page cell, in widget coordinates."""
        well = QRect(0, 0, self.width(), self.height())
        inner = photon.sunken_interior(well)
        cols, rows = self.pages
        return well, inner, inner.width() / float(cols), inner.height() / float(rows)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)
        well, inner, cw, ch = self._grid()
        photon.sunken(p, well, DESK)

        cols, rows = self.pages
        col = min(cols - 1, self.viewport[0] // max(1, self.screen_w))
        row = min(rows - 1, self.viewport[1] // max(1, self.screen_h))
        cur = QRect(inner.left() + int(round(col * cw)),
                    inner.top() + int(round(row * ch)),
                    int(round(cw)), int(round(ch))).intersected(inner)

        #  The reference does both: the current page is lighter *and* it is
        #  outlined.  Sampled at y=651, the rule at x=939 is white, the
        #  outline at 940 is #4b4b4b and the page behind it is #e1e3d8.
        p.fillRect(cur, DESK_HI)

        #  White 1px rules between pages, as in the reference -- the grid is
        #  drawn, not implied by gaps.
        p.setPen(GRID)
        for c in range(1, cols):
            x = inner.left() + int(round(c * cw))
            p.drawLine(x, inner.top(), x, inner.bottom())
        for r in range(1, rows):
            y = inner.top() + int(round(r * ch))
            p.drawLine(inner.left(), y, inner.right(), y)

        scale_x = inner.width() / float(max(1, cols * self.screen_w))
        scale_y = inner.height() / float(max(1, rows * self.screen_h))
        for rect, focused in self.windows:
            mini = QRect(inner.left() + int(rect.left() * scale_x),
                         inner.top() + int(rect.top() * scale_y),
                         max(2, int(rect.width() * scale_x)),
                         max(2, int(rect.height() * scale_y)))
            mini = mini.intersected(inner)
            if mini.isEmpty():
                continue
            p.fillRect(mini, FOCUS if focused else WIN)
            p.setPen(FOCUS_EDGE if focused else WIN_EDGE)
            p.drawRect(QRect(mini.left(), mini.top(),
                             mini.width() - 1, mini.height() - 1))

        #  The outline goes *inside* the white rule rather than over it,
        #  which is the order the reference reads in.  FvwmPager had no
        #  border option at all, which is why config settled for a lighter
        #  khaki alone and this is the part that could not be had before.
        p.setPen(photon.DARK)
        p.drawRect(QRect(cur.left() + 1, cur.top() + 1,
                         cur.width() - 2, cur.height() - 2))

    #  -- input --

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        _, inner, cw, ch = self._grid()
        pos = event.position().toPoint()
        if not inner.contains(pos):
            return
        col = int((pos.x() - inner.left()) / max(1.0, cw))
        row = int((pos.y() - inner.top()) / max(1.0, ch))
        cols, rows = self.pages
        self._set_page(max(0, min(cols - 1, col)), max(0, min(rows - 1, row)))


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
