#!/usr/bin/env python3
"""The shelf's window list, drawn rather than swallowed.

This used to be `FvwmIconMan` (`config`'s `TaskBarIcons`, `*TaskBarIcons:
Resolution page`) reparented into a taskbar cell.  Two things that cost:

  - `Resolution page` means "current page only", which the module works out
    itself from the desk it is told about.  This widget already has to watch
    `_NET_CLIENT_LIST` and `_NET_ACTIVE_WINDOW` for the pager's mini-windows
    (photon_pager.py), so there was nothing left for a second module to do
    that a page-rect intersection test here does not do more cheaply.
  - A swallowed IconMan needs a fresh `ButtonGeometry` on every panel resize,
    the same module-restart problem the pager and the frame bevel solved by
    not being modules any more.

This is a *list in a well*, not a column of push buttons.  The button
vocabulary was tried first, mapping `config`'s old `*TaskBarIcons:` faces
(`PlainButton up`, `IconAndSelectButton down`) onto `photon.button`, and it
reads badly: that painter's #ebebeb-to-#b0b0b0 gradient is measured off a
16px CD transport key, and stretched down a 23px row the length of the
shelf it turns every entry into a lozenge.  So the section is one
`photon.sunken` well and the rows are flat inside it, with the focused
window marked by a #4b4b4b outline -- the same idiom photon_pager.py uses
for the current page, and for the same reason: an outline says "this one"
without changing the surface it sits on.

Event-driven like the pager: `PropertyChangeMask` on the root for the client
list and active window, plus `PropertyChangeMask | StructureNotifyMask` on
every listed client so a title edit, a state change or a page move repaints
without polling.  Drained off Xlib's own connection through a
`QSocketNotifier` so it shares the Qt event loop. Saved thumbnail files are
checked once a second only while minimized windows are present.
"""

import os
import sys
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import QRect, QSize, QSocketNotifier, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QImage, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from Xlib import X, display, protocol, error as xerror

import photon

#  ICCCM 4.1.4: a client (here, us) asks the window manager to withdraw or
#  iconify a top-level window by sending it this state, not by touching the
#  window directly.
ICONIC_STATE = 3

_ROOT_ATOMS = ("_NET_CLIENT_LIST", "_NET_CLIENT_LIST_STACKING",
               "_NET_ACTIVE_WINDOW", "_NET_DESKTOP_VIEWPORT")
_EXTRA_ATOMS = ("_NET_WM_STATE", "_NET_WM_STATE_SKIP_TASKBAR",
                "_NET_WM_STATE_HIDDEN", "_NET_WM_STATE_MAXIMIZED_VERT",
                "_NET_WM_STATE_MAXIMIZED_HORZ", "_NET_WM_NAME",
                "_NET_WM_ICON", "_NET_CLOSE_WINDOW", "UTF8_STRING",
                "WM_CHANGE_STATE")

WELL_PAD = 2      # what photon.sunken_interior eats off each edge
MIN_THUMB_H = 64
MAX_THUMB_H = 136
THUMB_DIR = os.path.join(os.environ.get("FVWM_USERDIR", os.path.expanduser("~/.fvwm")),
                         "images", "thumbs")

_Task = namedtuple("_Task", "wid win title focused iconified maximized icon cls")


def thumbnail_heights(images, available):
    """Equal-height frames; all collapse before their visible crop is a sliver."""
    count = sum(img is not None and not img.isNull() for img in images)
    if not count:
        return [0] * len(images)
    visible = min(MAX_THUMB_H, available // count - 18)
    if visible < MIN_THUMB_H:
        return [0] * len(images)
    return [visible + 18 if img is not None and not img.isNull() else 0
            for img in images]


class TasksWidget(QWidget):
    """Windows on the current page, with expandable minimized previews."""

    natural_height_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.FACE)
        self.setPalette(pal)
        self.setMouseTracking(True)

        self.font_row = photon.font(8)
        self.tasks = []
        self._hover = -1
        self._top = 0           # the topmost listed window, see mouseRelease
        #  Decoding one 128x128 _NET_WM_ICON is 16k iterations of Python, and
        #  refresh() runs on every property event a listed window emits -- a
        #  terminal rewriting its title is enough.  Measured at 10ms a refresh
        #  for five windows before this cache, 1ms after.
        self._icons = {}
        self._thumbs = {}
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(1000)
        self._thumb_timer.timeout.connect(self._poll_thumbnails)
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.setInterval(150)
        self._state_timer.timeout.connect(self.refresh)

        self.dpy = display.Display()
        self.root = self.dpy.screen().root
        self.screen_w = self.dpy.screen().width_in_pixels
        self.screen_h = self.dpy.screen().height_in_pixels
        self.atoms = {n: self.dpy.intern_atom(n)
                      for n in _ROOT_ATOMS + _EXTRA_ATOMS}

        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.dpy.flush()
        self._notifier = QSocketNotifier(
            self.dpy.fileno(), QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._drain)

        self.refresh()

    #  -- size --

    def natural_height(self):
        return len(self.tasks) * photon.ROW_H + 2 * WELL_PAD

    def sizeHint(self):
        return QSize(photon.SHELF_INNER, self.natural_height())

    def _interior(self):
        return photon.sunken_interior(self.rect())

    def _thumbnail(self, wid):
        path = os.path.join(THUMB_DIR, f"0x{wid:x}.png")
        try:
            stat = os.stat(path)
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        if wid not in self._thumbs or self._thumbs[wid][0] != stamp:
            self._thumbs[wid] = (stamp, QImage(path) if stamp else QImage())
        return self._thumbs[wid][1]

    def _poll_thumbnails(self):
        old = {wid: stamp for wid, (stamp, _) in self._thumbs.items()}
        for task in self.tasks:
            if task.iconified:
                self._thumbnail(task.wid)
        if old != {wid: stamp for wid, (stamp, _) in self._thumbs.items()}:
            self.update()

    def _rows(self):
        inner = self._interior()
        images = [self._thumbnail(t.wid) if t.iconified else None
                  for t in self.tasks]
        heights = thumbnail_heights(images,
                                    inner.height() - len(self.tasks) * photon.ROW_H)
        y = inner.top()
        rows = []
        for extra in heights:
            rows.append(QRect(inner.left(), y, inner.width(), photon.ROW_H + extra))
            y += photon.ROW_H + extra
        return rows, images

    #  -- X: reading --

    def _drain(self):
        #  Any property/structure event on a watched window is worth a
        #  refresh -- a title edit, an iconify, a page move all arrive this
        #  way, and refresh() is cheap enough not to need per-atom triage.
        dirty = False
        try:
            for ev in photon.x_events(self.dpy):
                if ev.type in (X.PropertyNotify, X.ConfigureNotify,
                               X.DestroyNotify, X.UnmapNotify, X.MapNotify):
                    dirty = True
                if ev.type in (X.UnmapNotify, X.MapNotify) or (
                        ev.type == X.PropertyNotify
                        and ev.atom == self.atoms["_NET_WM_STATE"]):
                    self._state_timer.start()
                if (ev.type == X.PropertyNotify
                        and ev.atom == self.atoms["_NET_WM_ICON"]):
                    self._icons.pop(getattr(ev.window, "id", None), None)
        except (xerror.ConnectionClosedError, OSError):
            self._notifier.setEnabled(False)
            QApplication.quit()
            return
        except Exception:
            return
        if dirty:
            self.refresh()

    def _prop(self, window, name, type=X.AnyPropertyType):
        try:
            p = window.get_full_property(self.atoms[name], type)
        except (xerror.XError, Exception):
            return None
        return list(p.value) if p else None

    def _title(self, win):
        try:
            p = win.get_full_property(self.atoms["_NET_WM_NAME"],
                                      self.atoms["UTF8_STRING"])
            if p and p.value:
                return bytes(p.value).decode("utf-8", "replace")
        except Exception:
            pass
        try:
            name = win.get_wm_name()
            if isinstance(name, bytes):
                return name.decode("utf-8", "replace")
            return name or ""
        except Exception:
            return ""

    def _icon(self, win):
        """Nearest-to-16px frame out of a possibly multi-size `_NET_WM_ICON`:
        CARDINAL `w, h, w*h ARGB pixels`, repeated.  Masked to 32 bits because
        python-xlib hands format-32 properties back as platform longs."""
        try:
            p = win.get_full_property(self.atoms["_NET_WM_ICON"],
                                      X.AnyPropertyType)
        except Exception:
            return None
        if not p or not p.value:
            return None
        values = p.value
        best = None
        i, n = 0, len(values)
        while i + 2 <= n:
            w, h = values[i], values[i + 1]
            i += 2
            if w <= 0 or h <= 0 or i + w * h > n:
                break
            if best is None or abs(w - 16) < abs(best[0] - 16):
                best = (w, h, values[i:i + w * h])
            i += w * h
        if best is None:
            return None
        w, h, pixels = best
        buf = bytearray(w * h * 4)
        for idx, argb in enumerate(pixels):
            buf[idx * 4:idx * 4 + 4] = (int(argb) & 0xffffffff).to_bytes(
                4, sys.byteorder)
        return QImage(bytes(buf), w, h, QImage.Format.Format_ARGB32).copy()

    def refresh(self):
        active = self._prop(self.root, "_NET_ACTIVE_WINDOW")
        active = active[0] if active else 0
        screen = QRect(0, 0, self.screen_w, self.screen_h)

        found = []
        for wid in self._prop(self.root, "_NET_CLIENT_LIST") or []:
            try:
                win = self.dpy.create_resource_object("window", wid)
                state = self._prop(win, "_NET_WM_STATE") or []
                if self.atoms["_NET_WM_STATE_SKIP_TASKBAR"] in state:
                    continue
                g = win.get_geometry()
                #  Geometry is relative to the frame fvwm reparented the
                #  window into; translate_coords gives the true root origin,
                #  same trick as photon_pager.py.
                t = win.translate_coords(self.root, 0, 0)
                rect = QRect(-t.x, -t.y, g.width, g.height)
                if not rect.intersects(screen):
                    continue
                win.change_attributes(
                    event_mask=X.PropertyChangeMask | X.StructureNotifyMask)
                cls = win.get_wm_class()
            except Exception:
                continue

            if wid not in self._icons:
                self._icons[wid] = self._icon(win)

            found.append(_Task(
                wid=wid, win=win, title=self._title(win),
                focused=(wid == active),
                iconified=self.atoms["_NET_WM_STATE_HIDDEN"] in state,
                maximized=(self.atoms["_NET_WM_STATE_MAXIMIZED_VERT"] in state
                           and self.atoms["_NET_WM_STATE_MAXIMIZED_HORZ"] in state),
                icon=self._icons[wid], cls=cls))

        found.sort(key=lambda task: task.iconified)
        live = {t.wid for t in found}
        self._icons = {w: i for w, i in self._icons.items() if w in live}
        self._thumbs = {w: i for w, i in self._thumbs.items() if w in live}

        #  _NET_CLIENT_LIST_STACKING is bottom-to-top, so the last entry that
        #  we actually list is the window sitting on top of the others.
        stack = self._prop(self.root, "_NET_CLIENT_LIST_STACKING") or []
        self._top = next((w for w in reversed(stack) if w in live), 0)

        self.dpy.flush()
        resized = len(found) != len(self.tasks)
        self.tasks = found
        if any(t.iconified for t in found):
            if not self._thumb_timer.isActive():
                self._thumb_timer.start()
            self._poll_thumbnails()
        else:
            self._thumb_timer.stop()
        self.update()
        if resized:
            self.natural_height_changed.emit()

    #  -- X: acting --
    #
    #  Mirrors IconManClick in `config`: a click on the focused, mapped
    #  window iconifies it; a click on anything else raises and focuses it.
    #  Both go through EWMH/ICCCM client messages to the root rather than a
    #  direct fvwm call -- a component never talks to fvwm.

    def _send(self, win, atom_name, data):
        ev = protocol.event.ClientMessage(
            window=win, client_type=self.atoms[atom_name], data=(32, data))
        self.root.send_event(
            ev, event_mask=X.SubstructureNotifyMask | X.SubstructureRedirectMask)
        self.dpy.flush()

    def _iconify(self, win):
        self._send(win, "WM_CHANGE_STATE", [ICONIC_STATE, 0, 0, 0, 0])

    def _activate(self, win):
        #  source_indication 2: a pager/taskbar-class requestor.
        self._send(win, "_NET_ACTIVE_WINDOW", [2, X.CurrentTime, 0, 0, 0])

    def _close(self, win):
        self._send(win, "_NET_CLOSE_WINDOW", [X.CurrentTime, 2, 0, 0, 0])

    def _maximize(self, task):
        self._send(task.win, "_NET_WM_STATE",
                   [0 if task.maximized else 1,
                    self.atoms["_NET_WM_STATE_MAXIMIZED_VERT"],
                    self.atoms["_NET_WM_STATE_MAXIMIZED_HORZ"], 2, 0])

    #  -- painting --

    def _row_at(self, pos):
        inner = self._interior()
        if not inner.contains(pos):
            return -1
        return next((i for i, r in enumerate(self._rows()[0]) if r.contains(pos)), -1)

    def _draw_icon(self, p, task, box):
        if task.icon is not None:
            img = task.icon
            if img.width() != box.width() or img.height() != box.height():
                img = img.scaled(box.width(), box.height(),
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            p.drawImage(box.left(), box.top(), img)
            return
        #  No _NET_WM_ICON: fall back to a theme lookup on WM_CLASS, same
        #  pattern as LauncherBody._draw_icon in shelf-panel.
        if not task.cls:
            return
        instance, klass = task.cls
        for name in (klass, klass.lower() if klass else None,
                     instance, instance.lower() if instance else None):
            if name and photon.draw_icon(p, name, box):
                return

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)
        photon.sunken(p, self.rect(), photon.WELL)
        p.setFont(self.font_row)
        fm = QFontMetrics(self.font_row)
        inner = self._interior()
        p.setClipRect(inner)

        rows, images = self._rows()
        for i, t in enumerate(self.tasks):
            r = rows[i]
            if r.top() > inner.bottom():
                break

            if i == self._hover:
                face = photon.FACE_HI
            elif t.iconified:
                face = photon.WELL
            else:
                face = photon.FACE
            p.fillRect(r, face)
            photon.divider(p, r.bottom() - 1, r.left(), r.right())

            box = QRect(r.left() + 6, r.top() + (photon.ROW_H - 16) // 2, 16, 16)
            self._draw_icon(p, t, box)

            text_x = box.right() + 7
            p.setPen(photon.INK_OFF if t.iconified else photon.INK)
            baseline = r.top() + (photon.ROW_H + fm.capHeight()) // 2
            p.drawText(text_x, baseline,
                       photon.elide(t.title or "(untitled)", self.font_row,
                                    r.right() - text_x - 4))

            if r.height() > photon.ROW_H and images[i] is not None:
                area = QRect(r.left() + 6, r.top() + photon.ROW_H + 4,
                             r.width() - 12, r.height() - photon.ROW_H - 10)
                photon.trough(p, area)
                content = area.adjusted(4, 4, -4, -4)
                img = images[i]
                scale = max(content.width() / img.width(),
                            MAX_THUMB_H / img.height())
                w, h = round(img.width() * scale), round(img.height() * scale)
                target = QRect(content.left() + (content.width() - w) // 2,
                               content.top(), w, h)
                p.save()
                p.setClipRect(content)
                p.drawImage(target, img)
                p.restore()

            #  The focused window is outlined rather than re-surfaced, so the
            #  mark survives whatever face the row already has -- iconified
            #  and focused is a real combination while a window is on its way
            #  back up.
            if t.focused:
                p.setPen(photon.DARK)
                p.drawRect(QRect(r.left(), r.top(),
                                 r.width() - 1, r.height() - 2))

    #  -- input --

    def mouseMoveEvent(self, event):
        i = self._row_at(event.position().toPoint())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, event):
        if self._hover != -1:
            self._hover = -1
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            return
        i = self._row_at(event.position().toPoint())
        if i < 0:
            return
        t = self.tasks[i]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._close(t.win)
            return
        #  Iconify only a window that is focused *and* already on top.  Focus
        #  and stacking come apart under this config's ClickToFocus -- a
        #  window can hold the focus while buried -- and keying the toggle on
        #  focus alone made a click on a buried window minimise it when what
        #  was obviously wanted was to raise it.  One click raises, the next
        #  one puts it away.
        if t.focused and not t.iconified and t.wid == self._top:
            self._iconify(t.win)
        else:
            self._activate(t.win)

    def contextMenuEvent(self, event):
        i = self._row_at(event.pos())
        if i < 0:
            return
        t = self.tasks[i]
        menu = QMenu(self)
        menu.addAction("Restore" if t.iconified else "Minimize",
                       lambda: self._activate(t.win) if t.iconified else self._iconify(t.win))
        menu.addAction("Unmaximize" if t.maximized else "Maximize",
                       lambda: self._maximize(t))
        menu.addSeparator()
        menu.addAction("Close", lambda: self._close(t.win))
        menu.exec(event.globalPos())


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tasks")
    w = TasksWidget()
    w.resize(photon.SHELF_INNER, max(photon.ROW_H, w.natural_height()))
    w.setWindowTitle("Tasks")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
