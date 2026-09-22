# Media PiP Well Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The media well scales to the image's aspect ratio, and a browser's PiP video window is reparented into it when one appears.

**Architecture:** Part 1 makes the well's height follow the displayed image (`side = min(well_w, well_w·ih/iw)`), with the well's arithmetic factored into one function read by both `_relayout` and `natural_height` so the two stop drifting. Part 2 adds a `PipMonitor` that finds a browser's PiP toplevel by geometry + `_NET_WM_PID` every 1500 ms (the `TrayWidget` find-loop pattern), and `MediaWidget` embeds that window in the well with `QWindow.fromWinId` + `QWidget.createWindowContainer` (the `photon_tray.py` pattern), pinning the child to the well rect and following it on configure events.

**Tech Stack:** Python 3.14, PyQt6, python-xlib 0.33 (already a hard dependency of the panel via `bin/photon_tray.py`), X11 under FVWM. No new packages.

## Global Constraints

- Working directory for every command: `/home/deer/dotfiles/.fvwm`.
- Only `bin/photon_media.py` is modified. `bin/shelf-panel`, `bin/photon_tray.py`, `config`, `bin/panel.items` are **not touched** — the panel already routes `MediaWidget.natural_height(w)` (`shelf-panel:343`) and connects `natural_height_changed` (`shelf-panel:301`).
- No new runtime dependency. Xlib import: `from Xlib import X, display, error as xerror` — the same line `photon_tray.py` uses.
- Lint gate: `ruff` is `/usr/bin/ruff` (there is no `python3 -m ruff` on this box) with default rules, no config file. `bin/photon_media.py` has **5 pre-existing diagnostics (4× UP031, 1× I001)** as of commit `HEAD` before this work; zero *new* ones may be added, and nothing may be auto-fixed.
- Check scripts go in `/tmp`, run with `QT_QPA_PLATFORM=offscreen`, and are deleted when they pass.
- Style: 2-space-indented `#  ...` comments in file-idiom, `%` formatting (new lines use f-strings: the gate allows no new UP031), no emojis, no docstrings beyond the class header this file uses.
- Commit after every task: `feat(media): ...` (docs task: `docs(media): ...`).
- Spec: `docs/plans/2026-09-22-media-pip-well.md`. If the live smoke (Task 4) fails its hard items, revert both Part 2 commits and ship Part 1 only — the spec's fallback decision.

---

### Task 1: The well follows the image's aspect ratio (Part 1)

**Files:**
- Modify: `bin/photon_media.py` — `MediaWidget.__init__` (the `self._has_art` line), `_relayout`, `natural_height`, `_on_cover`, `resizeEvent`. New methods `_layout`, `_well_side`, `_refresh_well` inserted where `_relayout` lives.
- Test: `/tmp/pipwell-check.py` (throwaway, deleted at the end).

**Interfaces:**
- Consumes: existing `CoverArt.pixmap` (`QPixmap` or `None`), the `natural_height_changed` signal, `photon.*` painters, `NATURAL_H`, `FIELD_H`, `BTN_H`, `BTN_GAP`, `GAP`, `THUMB_H`, `GROOVE_DROP` (all module constants).
- Produces (Task 3 builds on these exact names):
  - `MediaWidget._layout(self, w, side) -> dict` with keys `pad, r_art, art_div_y, r_title, r_buttons, div_y, r_speaker, r_groove, thumb_top, r_ticks_y, r_output, content_bottom`.
  - `MediaWidget._well_side(self, w) -> int | None` (well side for the *current* source; `None` = no well).
  - `MediaWidget._refresh_well() -> None` (recompute side, relayout, emit `natural_height_changed` once when the side changes, resize standalone window).
  - `MediaWidget._side` (int or `None`, the side the last emit was for) and `MediaWidget._pip_container` (`QWidget` or `None` — attribute only in this task; Task 3 gives it a purpose).
- **Reproduces today exactly in the square case** — this plan keeps the measured reference values: at widget width 152 with square art, `r_art == QRect(4, 4, 144, 144)`, `art_div_y == 151`, `r_title.y() == 156`, `natural_height(152) == 252`.

- [ ] **Step 1: Write the failing check**

Create `/tmp/pipwell-check.py`:

```python
import sys
import time

sys.path.insert(0, "bin")
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage, qRgb
from PyQt6.QtWidgets import QApplication
from photon_media import MediaWidget

app = QApplication([])
w = MediaWidget()
#  The check runs against the live session bus: cut the MPRIS wiring so the
#  art state below is the only thing that can move the well.
w.mpris.changed.disconnect(w._on_mpris)
n = {"h": 0}
w.natural_height_changed.connect(lambda: n.update(h=n["h"] + 1))
#  A hidden top-level never delivers geometry events on the offscreen
#  platform; swallowed widgets are mapped, so map this one too.
w.show()
app.processEvents()

def set_art(pw, ph):
    img = QImage(pw, ph, QImage.Format.Format_RGB32)
    img.fill(qRgb(200, 30, 30))
    p = "/tmp/pipwell-art-%dx%d.png" % (pw, ph)
    assert img.save(p)
    w.cover.set_track("svc", "t", "file://" + p)
    end = time.monotonic() + 5
    while time.monotonic() < end and w.cover.pixmap is None:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

w.resize(152, 100)
assert w.r_art is None, w.r_art
assert w.natural_height(152) == 100

# Square art: pixel-identical to today's reference layout.
set_art(256, 256)
w.resize(152, 100)
assert w.r_art == QRect(4, 4, 144, 144), w.r_art
assert w.art_div_y == 151
assert w.r_title.y() == 156
assert w.natural_height(152) == 252 and w.natural_height(150) == 250

# 16:9: the well is short and the rows ride up.
h0 = n["h"]
set_art(320, 180)
w.resize(152, 100)
assert w.r_art == QRect(4, 4, 144, 81), w.r_art
assert w.art_div_y == 88
assert w.r_title.y() == 93
assert w.natural_height(152) == 189
assert n["h"] == h0 + 1, n["h"]   # exactly one natural_height_changed on the swap

# Portrait: capped at the square, as today.
set_art(120, 180)
w.resize(152, 100)
assert w.r_art == QRect(4, 4, 144, 144), w.r_art
assert w.natural_height(152) == 252

# Width change in the 16:9 state: the well tracks it.
set_art(320, 180)
w.resize(130, 177)
assert w.r_art == QRect(4, 4, 122, 69), w.r_art
assert w.natural_height(130) == 177
assert all(r.right() <= 130 and r.bottom() <= 177
           for r in (w.r_art, w.r_title) + tuple(w.r_buttons)
           + (w.r_speaker, w.r_groove, w.r_output))

# Art gone: back to no well.
w.cover.set_track("svc", "t", "")
app.processEvents()
assert w.r_art is None and w.natural_height(152) == 100

print("pipwell OK")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python3 /tmp/pipwell-check.py`
Expected: `AssertionError: None` at the square-section `r_art` assert —
today's layout only re-runs on a resizeEvent, and in the standalone
check no resize happens after the cover arrives (in the real panel the
natural-height flip resizes the swallowed child, masking this) — the
square values asserted there are today's behavior and must survive
byte-identically. Note: `natural_height(self, w)` already exists (the
width-aware shelf work); this task reworks its body, not its signature.

- [ ] **Step 3: Implement**

`__init__`, after the existing
`self._has_art = False    # presence of a loaded pixmap, the only flip that relays`
line — that line's comment changes, since side flips relayout too:

```python
        self._has_art = False    # the well is up; a flip or a side change relays
        self._side = None        # the side the last natural_height_changed was for
        self._pip_container = None   # the embedded PiP window (Task 3)
```

Replace `_relayout` in full, carrying the existing FvwmButtons inset
comment to the top of the new method, and add `_layout` directly above it:

```python
    #  Every rect below the width, in one place: _relayout and
    #  natural_height both read this, so with a variable side there is no
    #  second copy of the arithmetic to drift.
    def _layout(self, w, side):
        pad = 4
        if side is None:
            r_art, art_div_y = None, None
            r_title = QRect(pad, pad, w - 2 * pad, FIELD_H)
        else:
            r_art = QRect(pad, pad, w - 2 * pad, side)
            art_div_y = r_art.bottom() + 1 + GAP
            r_title = QRect(pad, art_div_y + 2 + GAP, w - 2 * pad, FIELD_H)
        by = r_title.bottom() + 1 + GAP
        row_w = max(4, w - 2 * pad - 3 * BTN_GAP)
        button_w, extra = divmod(row_w, 4)
        r_buttons, bx = [], pad
        for i in range(4):
            bw = button_w + (1 if i < extra else 0)
            r_buttons.append(QRect(bx, by, bw, BTN_H))
            bx += bw + BTN_GAP
        div_y = by + BTN_H + GAP
        thumb_top = div_y + 2 + GAP
        return {"pad": pad, "r_art": r_art, "art_div_y": art_div_y,
                "r_title": r_title, "r_buttons": r_buttons, "div_y": div_y,
                "r_speaker": QRect(6, thumb_top + 1, 16, 16),
                "r_groove": QRect(32, thumb_top + GROOVE_DROP,
                                  max(20, w - 28 - 32), 5),
                "thumb_top": thumb_top, "r_ticks_y": thumb_top + THUMB_H - 1,
                "r_output": QRect(pad, thumb_top + THUMB_H + 4,
                                  max(20, w - 2 * pad), FIELD_H),
                "content_bottom": thumb_top + THUMB_H + 4 + FIELD_H}

    def _well_side(self, w):
        """The well's side for the current source, or None: full width,
        shortened by the image's own ratio, capped at the square."""
        pm = self.cover.pixmap
        if pm is None or pm.isNull():
            return None
        well_w = w - 8
        return min(well_w, round(well_w * pm.height() / pm.width()))

    def _relayout(self):
        w = self.width()
        #  FvwmButtons' module-wide `Padding 4 0` does not reach the
        #  swallowed window -- the child is resized to the whole cell -- so
        #  the inset that aligns this row with the meters above must come
        #  from here.
        L = self._layout(w, self._well_side(w))
        self.r_art = L["r_art"]
        self.art_div_y = L["art_div_y"]
        self.r_title = L["r_title"]
        self.r_buttons = L["r_buttons"]
        self.div_y = L["div_y"]
        self.r_speaker = L["r_speaker"]
        self.r_groove = L["r_groove"]
        self.r_thumb_top = L["thumb_top"]
        self.r_ticks_y = L["r_ticks_y"]
        self.r_output = L["r_output"]
        self.output.setGeometry(self.r_output)
        self._measure_title()

    def _refresh_well(self):
        side = self._well_side(self.width())
        if side == self._side:
            self.update()      # track-to-track swap: repaint the same rect
            return
        self._side = side
        self._has_art = side is not None
        self._relayout()
        self.natural_height_changed.emit()
        self.update()
        if self.parent() is None:
            #  Standalone window: nothing else grows or shrinks it.
            self.resize(self.width(), self.natural_height(self.width()))
```

Replace `natural_height`:

```python
    def natural_height(self, w):
        side = self._well_side(w)
        if side is None:
            return NATURAL_H
        #  +4: the slack the no-well state leaves below the volume row
        #  (content bottom is side+104; the square case lands exactly on
        #  the old NATURAL_H + w).
        return self._layout(w, side)["content_bottom"] + 4
```

Replace `_on_cover`:

```python
    def _on_cover(self):
        self._refresh_well()
```

Extend `resizeEvent` (one added line):

```python
    def resizeEvent(self, event):
        self._relayout()
        side = self._well_side(self.width())
        if side != self._side:
            self._side = side
            self.natural_height_changed.emit()
```

The emit on a resize-driven side change is the spec's "content change
(cover flip, PiP flip, resize) recomputes; if it changed, emit" — the
panel's relayout is idempotent in the width it just handed over, so a
panel resize settles in one extra round trip.

`paintEvent`, `_paint_art` and the input handlers are unchanged.

- [ ] **Step 4: Run the check to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python3 /tmp/pipwell-check.py`
Expected: `pipwell OK`

- [ ] **Step 5: Compile and lint gates**

Run: `python3 -m py_compile bin/photon_media.py && ruff check --statistics bin/photon_media.py`
Expected: no output from `py_compile`; `ruff` reports the same 5
pre-existing diagnostics (4× UP031, 1× I001) — none new, none removed
(nothing may be fixed: fixing would reflow lines the next task quotes).

- [ ] **Step 6: Commit**

```bash
git add bin/photon_media.py
git commit -m "feat(media): well follows the image's aspect ratio"
```

---

### Task 2: `PipMonitor` — find the browser's PiP window (Part 2, detection)

Per the spec's test decision, Part 2 is verified **live only** (Task 4):
a fake PiP window exercises different code paths than the real one, and a
broken smoke would ship a fake result to a decision no decision exists
about. This task is implement + compile/lint + commit; the first real
run of the detector is the smoke.

**Files:**
- Modify: `bin/photon_media.py` — module imports (one line) and a new
  `PipMonitor` class section after `CoverArt` (before `#  ---- The widget`).

**Interfaces:**
- Consumes: Xlib (`from Xlib import X, display, error as xerror`),
  `QTimer`, `QObject`, `pyqtSignal` — all already imported or trivially
  added; `photon` is not needed in this task.
- Produces (Task 3 builds on these exact names):
  - `PipMonitor(QObject)` — attributes `dpy` (Xlib `Display` or `None`),
    `window_id` (int or `None`), `width`, `height` (int), `_win` (Xlib
    window resource or `None`), `_dead` (set of int), `_x_notifier`
    (`QSocketNotifier` or `None`), `_timer`; signal `changed`; methods
    `give_up(xid)`, `_poll()`, `_set(found)`, `_wm_pid(win)`, `_comm(pid)`.
  - Constants on the class: `INTERVAL_MS = 1500`, `W_MIN/W_MAX`,
    `H_MIN/H_MAX`, `R_MIN/R_MAX`, `BROWSERS`.

- [ ] **Step 1: Implement**
Add to the module imports (next to `import photon`):

```python
from Xlib import X, display, error as xerror
```

Insert after the `CoverArt` class, before the `#  ---- The widget`
section:

```python
#  ---- PiP monitor ----------------------------------------------------------

class PipMonitor(QObject):
    """A browser's PiP window, found by geometry and owner.

    There is no X event for "a PiP appeared", so this is a deliberate
    poll, the same find loop shape photon_tray uses to adopt stalonetray.
    Candidate: a managed top-level that is video-shaped and whose
    _NET_WM_PID is a browser.  fvwm reparents every top-level into its
    own frame, so _NET_CLIENT_LIST (client ids) is the enumeration, not
    a root query_tree.
    """

    INTERVAL_MS = 1500

    W_MIN, W_MAX = 160, 1000       # plausible PiP widths
    H_MIN, H_MAX = 90, 700
    R_MIN, R_MAX = 1.2, 2.6        # video-ish aspect only
    BROWSERS = ("firefox", "chromium", "chrome")

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.dpy = display.Display()
        except (xerror.DisplayConnectionError, xerror.DisplayNameError):
            self.dpy = None
        self.window_id = None
        self.width = 0
        self.height = 0
        self._win = None           # the Xlib window of the current PiP
        self._dead = set()         # ids whose embed kept failing
        self._x_notifier = None    # Task 3
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        if self.dpy is not None:
            self._timer.start()

    def give_up(self, xid):
        """The widget could not embed this window; stop re-offering it."""
        self._dead.add(xid)

    @staticmethod
    def _comm(pid):
        try:
            with open(f"/proc/{pid}/comm") as f:
                return f.read().strip()
        except OSError:
            return ""

    def _wm_pid(self, win):
        try:
            atom = self.dpy.intern_atom("_NET_WM_PID")
            prop = win.get_full_property(atom, X.AnyPropertyType)
            return prop.value[0] if prop else None
        except xerror.XError:
            return None

    def _poll(self):
        if self.dpy is None:
            return
        found = None
        try:
            root = self.dpy.screen().root
            atom = self.dpy.intern_atom("_NET_CLIENT_LIST")
            prop = root.get_full_property(atom, X.AnyPropertyType)
            wids = list(prop.value) if prop else []
        except xerror.XError:
            wids = []
        for wid in wids:
            try:
                win = self.dpy.create_resource_object("window", wid)
                g = win.get_geometry()
            except xerror.XError:
                continue
            if not (self.W_MIN <= g.width <= self.W_MAX
                    and self.H_MIN <= g.height <= self.H_MAX):
                continue
            if not (self.R_MIN <= g.width / g.height <= self.R_MAX):
                continue
            pid = self._wm_pid(win)
            if pid is None or pid in self._dead:
                continue
            if self._comm(pid) not in self.BROWSERS:
                continue
            found = (win, g)
            break
        self._set(found)

    def _set(self, found):
        xid = found[0].id if found else None
        size = (found[1].width, found[1].height) if found else (0, 0)
        if xid == self.window_id and size == (self.width, self.height):
            return
        self._dead.discard(self.window_id)   # entries drop when the id stops matching
        self._win = found[0] if found else None
        self.window_id = xid
        self.width, self.height = size
        self.changed.emit()
```

- [ ] **Step 2: Check the live browser's identity**

Run: `for p in $(pidof firefox); do tr -d '\0' < /proc/$p/comm; done | sort -u`
Expected: `firefox` among the output (the main browser process; content
processes show up as `Web Content` and friends and are not the PiP
window's owner). If the main process's comm is not exactly one of
`BROWSERS` (e.g. `firefox-bin`), add the real string to `BROWSERS` before
committing — the smoke will see the same string.

- [ ] **Step 3: Compile and lint gates**

Run: `python3 -m py_compile bin/photon_media.py && ruff check --statistics bin/photon_media.py`
Expected: no new diagnostics beyond the 5 from Task 1.

- [ ] **Step 4: Commit**

```bash
git add bin/photon_media.py
git commit -m "feat(media): PipMonitor finds the browser's PiP window"
```

---

### Task 3: Embed the PiP window in the well (Part 2, embed + wiring)

**Files:**
- Modify: `bin/photon_media.py` — `MediaWidget.__init__` (monitor wiring),
  `__init__` (the `_pip_rect` attribute), `_relayout` (container block),
  `_well_side` (pip priority), `_paint_art` (skip the pixmap under a
  container), new methods `_on_pip`, `_embed_pip`, `_drop_pip`,
  `_pip_pin`, `_raise_pip`; `PipMonitor` gains `watch()` and
  `_drain_x()`. Module docstring gains the poll note.
- Test: `/tmp/pipwell-check.py` extended in place (the Task 1 script,
  kept until this task's run passes).

**Interfaces:**
- Consumes: Task 2's `PipMonitor` (`window_id`, `width`, `height`,
  `changed`, `dpy`, `_win`, `_x_notifier`, `give_up`, `_poll`, `_set`);
  Task 1's `_well_side`, `_layout`, `_refresh_well`, `_side`,
  `_pip_container`; `photon.x_events(dpy)` (the helper `photon_tray.py`
  drains with); `QWindow` (PyQt6.QtGui), `QSocketNotifier` (PyQt6.QtCore).
- Produces: `MediaWidget.pip` (the monitor instance), `MediaWidget._on_pip`,
  `MediaWidget._embed_pip`, `MediaWidget._drop_pip`,
  `MediaWidget._pip_pin`, `MediaWidget._raise_pip`,
  `MediaWidget._pip_rect` (QRect or `None`), `PipMonitor.repin` signal,
  `PipMonitor.watch()`, `PipMonitor._drain_x()`.

- [ ] **Step 1: Extend the check with the integrated state machine**

Replace the final section of `/tmp/pipwell-check.py` (everything from
`# Art gone: back to no well.` through the `print`) with. The state
coming in from the Task 1 sections: cover art = 320×180 (16:9), widget
width = 130 — the check restores the canonical width first:

```python
# Task 3: pip window in hand; drive it through the real wiring.
w.pip._timer.stop()          # do not let the live desktop steer the check

# Back to the canonical width from the Task 1 sections.
w.resize(152, 252)
app.processEvents()      # resize delivery: see the show() note in Task 1
assert w.r_art == QRect(4, 4, 144, 81)     # the 16:9 cover (Task 1)

w.pip.window_id = 0xDEAD
w.pip.width, w.pip.height = 320, 180
w._on_pip()
assert w.r_art == QRect(4, 4, 144, 81), w.r_art
assert w.natural_height(152) == 189
# (offscreen QWindow.fromWinId has no X to find: the embed is skipped
#  without raising; the real embed is proven in Task 4's smoke.)

w.resize(130, 177)
app.processEvents()
assert w.r_art == QRect(4, 4, 122, 69), w.r_art
assert w.natural_height(130) == 177

w.pip.window_id = None
w.pip.width = w.pip.height = 0
w._on_pip()
assert w.r_art == QRect(4, 4, 122, 69), w.r_art   # the cover is still 16:9
assert w.natural_height(130) == 177

# Art gone: back to no well.
w.cover.set_track("svc", "t", "")
app.processEvents()
assert w.r_art is None and w.natural_height(152) == 100

print("pipwell OK")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python3 /tmp/pipwell-check.py`
Expected: `AttributeError: 'MediaWidget' object has no attribute 'pip'`

- [ ] **Step 3: Implement**

Module imports: add `QWindow` to the `PyQt6.QtGui` import list, add
`QSocketNotifier` to the `PyQt6.QtCore` list, keep line grouping with
existing ones (`photon.py` does the same sort of multi-source QtCore
imports).

`MediaWidget.__init__`, after the cover wiring (the
`self.cover.set_track(...)` call already present, inserted immediately
before it):

```python
        self.pip = PipMonitor(self)
        self.pip.changed.connect(self._on_pip)
        self.pip.repin.connect(self._pip_pin)
        self._pip_rect = None
```

(`self._pip_container = None` already exists from Task 1.)

`_well_side` — the pip window outranks the cover pixmap (the thumbnail
is the same video, one picture per well):

```python
    def _well_side(self, w):
        """The well's side for the current source, or None: full width,
        shortened by the image's own ratio, capped at the square.  The
        PiP window outranks the cover art -- the frame outranks its own
        poster."""
        if self.pip is not None and self.pip.window_id is not None:
            src = (self.pip.width, self.pip.height)
        else:
            pm = self.cover.pixmap
            src = ((pm.width(), pm.height()) if pm is not None
                   and not pm.isNull() else None)
        if src is None:
            return None
        well_w = w - 8
        return min(well_w, round(well_w * src[1] / src[0]))
```

`_relayout` — insert the container block between
`self.output.setGeometry(self.r_output)` and `self._measure_title()`:

```python
        if self._pip_container is not None and self.r_art is not None:
            r = self.r_art.adjusted(4, 4, -4, -4)
            self._pip_container.setGeometry(r)
            if r != self._pip_rect:
                self._pip_rect = r
                self._pip_pin()
```

New widget methods (place them after `_refresh_well`):

```python
    def _on_pip(self):
        if self.pip.window_id is not None and self._pip_container is None:
            self._embed_pip()
        elif self.pip.window_id is None and self._pip_container is not None:
            self._drop_pip()
        self._refresh_well()

    def _embed_pip(self):
        win = QWindow.fromWinId(self.pip.window_id)
        if win is None:
            #  The window died between the poll and now; the next poll
            #  re-decides.
            return
        container = QWidget.createWindowContainer(win, self)
        if container is None:
            self.pip.give_up(self.pip.window_id)
            return
        self._pip_container = container
        container.show()
        self._relayout()      # positions the container and pins the child
        self.pip.watch()
        QTimer.singleShot(0, self._raise_pip)

    def _drop_pip(self):
        self._pip_container.deleteLater()
        self._pip_container = None
        self._pip_rect = None

    def _pip_pin(self):
        """The child must sit at the container's origin:
        XReparentWindow keeps absolute coordinates, so without this the
        video sits where the PiP was before."""
        mon = self.pip
        r = self._pip_rect
        if mon is None or mon.dpy is None or mon._win is None:
            return
        if r is None or r.width() < 2 or r.height() < 2:
            return
        try:
            mon._win.configure_request(x=0, y=0,
                                       width=r.width(), height=r.height())
            mon.dpy.flush()
        except xerror.XError:
            pass

    def _raise_pip(self):
        if self._pip_container is not None and self.isVisible():
            self._pip_container.show()
            self._pip_container.raise_()
```

Panel exit needs no code: when our toplevel dies the X server implicitly
reparents the orphaned child to root, the PiP re-appears floating and
playback is untouched (relied-on X behavior — Task 4, step 4 asserts it).

`_paint_art` — the trough stays (the container is inset 4px inside the
well, same as the pixmap), but the pixmap is not painted under a live
child:

```python
    def _paint_art(self, p):
        photon.trough(p, self.r_art)
        if self._pip_container is not None:
            return
        r = self.r_art.adjusted(4, 4, -4, -4)
        art = self.cover.pixmap.scaled(
            r.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        x = r.left() + (r.width() - art.width()) // 2
        y = r.top() + (r.height() - art.height()) // 2
        p.drawPixmap(x, y, art)
```

(`photon.x_events` is the helper `photon_tray.py` already drains with --
import nothing new for it.)

`PipMonitor` gains:

```python
    repin = pyqtSignal()

    def watch(self):
        """Subscribe to the current window's structure events and drain
        them on the display fd: close arrives before the 1500ms poll, and
        a move or resize by the browser is caught at once."""
        if self._win is None or self.dpy is None:
            return
        try:
            self._win.change_attributes(event_mask=X.StructureNotifyMask)
            self.dpy.flush()
        except xerror.XError:
            return
        if self._x_notifier is None:
            self._x_notifier = QSocketNotifier(self.dpy.fileno(),
                                               QSocketNotifier.Type.Read,
                                               self)
            self._x_notifier.activated.connect(self._drain_x)

    def _drain_x(self):
        try:
            for ev in photon.x_events(self.dpy):
                if getattr(ev.window, "id", None) != self.window_id:
                    continue
                if ev.type in (X.DestroyNotify, X.UnmapNotify):
                    self._set(None)
                elif ev.type == X.ConfigureNotify:
                    if (ev.width, ev.height) != (self.width, self.height):
                        self.width, self.height = ev.width, ev.height
                        self.changed.emit()
                    elif ev.x or ev.y:
                        self.repin.emit()
        except (xerror.ConnectionClosedError, OSError):
            if self._x_notifier is not None:
                self._x_notifier.setEnabled(False)
            QApplication.quit()
            return
        except Exception:
            return
```

The module docstring's "Nothing here polls." paragraph: append one
sentence —
`  (One exception: the 1.5s PiP poll, which photon_tray's find loop makes
  acceptable here; the video is nobody else's business until it floats.)`
Keep the paragraph's existing lines untouched otherwise.

- [ ] **Step 4: Run the check to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python3 /tmp/pipwell-check.py`
Expected: `pipwell OK`

- [ ] **Step 5: Compile and lint gates**

Run: `python3 -m py_compile bin/photon_media.py && ruff check --statistics bin/photon_media.py`
Expected: no new diagnostics beyond the 5 from Task 1.

- [ ] **Step 6: Commit**

```bash
git add bin/photon_media.py
git commit -m "feat(media): embed the PiP window in the media well"
```

---

### Task 4: Live PiP smoke, fallback decision, cleanup

**Files:**
- None modified (unless the fallback path fires: then both Part 2
  commits are reverted and an execution note is appended to this plan).
- Delete: `/tmp/pipwell-check.py`, `/tmp/pipwell-art-*.png`.

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: a shipped state — either both parts, or Part 1 only with the
  spec's fallback recorded.

This task needs a human at the keyboard (a real YouTube PiP).

- [ ] **Step 1: Clean up throwaways**

Run: `rm -f /tmp/pipwell-check.py /tmp/pipwell-art-*.png`

- [ ] **Step 2: Start the widget standalone**

Run: `python3 bin/photon_media.py` (left running in a terminal; it is a
plain 152×100 window).

- [ ] **Step 3: Hard item A — the video lands in the well**

In Firefox: play a YouTube video, hover it, click the Picture-in-Picture
button. Within ~2 s of the PiP appearing, verify by eye:

- [ ] The video is visible **inside the media well**, not at the PiP's
  original screen position.
- [ ] It plays smoothly (no tearing, no black box); the well is short
  (~81/144 ratio of its width, not a square) and the title/transport/
  volume rows sit below it.
- [ ] The MPRIS title still scrolls and the transport buttons still work
  (play/pause via the shelf controls the browser video, as before).

If any of these fail: **stop**. Record what was observed (one or two
lines) under a new `## Execution notes` heading in this plan
(`docs/plans/2026-09-22-media-pip-well-plan.md` — the spec's "record what
was observed in the plan's execution notes"), then revert **both** Part 2
commits (Task 3 first, then Task 2):

```bash
git log --oneline -5
git revert --no-edit <sha-of-Task-3> <sha-of-Task-2>
git add docs/plans/2026-09-22-media-pip-well-plan.md
git commit -m "docs(plan): PiP embed blocked by live behavior; Part 1 ships"
```

Then kill the widget and stop here — Part 1 ships. The smoke checklist
below does not run.

- [ ] **Step 4: Hard item B — the PiP goes back, and the panel's death
  does not kill the video**

- [ ] Close the PiP (its close button or Esc with the PiP focused).
  Expected: the well falls back to the video's thumbnail, the widget does
  not die or stutter; ~2 s of settling at most.
- [ ] Play again, PiP again (it is embedded), then kill the standalone
  widget (`SIGINT` to the terminal). Expected: the PiP re-appears
  floating at (approximately) the screen, still playing, unowned -- this
  is X's auto-reparent, no code is involved. If the PiP dies instead of
  returning: that is a spec-violating behavior -- follow Step 3's revert
  path and record it.

- [ ] **Step 5: Soft items (note-and-continue, not blockers)**

- [ ] Resize the PiP from within Firefox while it is embedded (if
  Firefox allows it): the well should follow the new size within ~2 s
  and the child re-pin.
- [ ] Leave it running for a few minutes: no CPU climb (the poll is one
  Xlib round-trip per 1.5 s) and no leaked windows
  (`xdotool search --name "" getwindowname` should not grow).

- [ ] **Step 6: Restart the real panel and re-verify**

Run: `FvwmCommand Restart` (the config re-execs `bin/shelf-panel`, which
imports the new `photon_media`). With a PiP up, the panel's Media group
shows the embedded video; without one, the well behaves as Task 1's
square/16:9/portrait. Kill the standalone widget if it is still around.

- [ ] **Step 7: Final gates and commit**

Run: `python3 -m py_compile bin/photon_media.py && ruff check --statistics bin/photon_media.py && git status --short`
Expected: clean compile, still the 5 baseline ruff diagnostics, a clean
working tree (the spec note commit from Step 3, if it ran, is in).
Nothing else to commit in the happy path -- the work landed in Tasks
1–3's commits.
