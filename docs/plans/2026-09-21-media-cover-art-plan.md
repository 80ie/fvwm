# Media Cover Art — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the current track's cover art in the sidebar's Media group as a
square, World-View-framed well above the existing controls.

**Architecture:** `Mpris` (already signal-driven) carries two new metadata
fields; a new `CoverArt` class in the same file fetches the named image
request/response through `QNetworkAccessManager` (one path for `file://`,
bare paths and `http(s)`, an 8 s abort guard per request, an 8-entry LRU);
`MediaWidget` gains the well rect, a width-aware `natural_height(w)` and a
`natural_height_changed` signal; `shelf-panel` routes it through its existing
WorldView branch. The reference QNX shelf has no art — everything shared
with it (title, transport, volume) stays byte-identical.

**Tech Stack:** Python 3.13, PyQt6 (`QtNetwork` for the fetch), existing
`bin/photon.py` painters (the `trough` bevel frames the well).

Spec: `docs/plans/2026-09-21-media-cover-art.md` — it is approved; its
geometry and failure semantics are binding.

## Global Constraints

- **No test framework in this repo** (AGENTS.md: "There is no build or test
  system"). Each task's test cycle is: `python3 -m py_compile` +
  `python3 -m ruff check`, a **throwaway** offscreen verification script
  (deleted after passing, never committed), and where marked, a live
  `FvwmCommand Restart` check. **No permanent test files are added.**
- **No new files, no daemon, no polling.** All new code lands in
  `bin/photon_media.py` (plus the one-line `bin/shelf-panel` change and docs).
  The only new timers are per-request abort guards.
- **Colours:** only existing `photon` constants — the well frame is
  `photon.trough` (`DARK` #4b4b4b outline, `TROUGH_SH` #8d8d8d inner shadow
  top/left, `TROUGH` #bcbcbc channel); the widget face is `photon.FACE`.
- **Geometry (binding, from the spec):** with body width `w`,
  `r_art = QRect(4, 4, w-8, w-8)`; the etched divider sits at
  `r_art.bottom() + 1 + GAP` (GAP = 3, the file's usual rule); the title
  field top is `divider + 2 + GAP` (i.e. `4 + w`); body height is
  `NATURAL_H + w` (100 + w) with art,
  `NATURAL_H` (100) without; the pixmap is centred in
  `r_art.adjusted(4, 4, -4, -4)`, `KeepAspectRatio` + `SmoothTransformation`.
- **Race rule:** every in-flight request is tagged with the
  `(service, trackid, url)` state it was made under; a reply whose tag no
  longer matches is dropped. A *failed* fetch keeps the last good pixmap;
  the well clears only when the source says absent (no player, no `artUrl`,
  or an unresolvable scheme).
- **Style:** match the file's existing conventions — 4-space indent,
  `#  ` two-space-continuation comments that read like notes to the next
  maintainer, one-line section headers like `#  ---- Cover art ---`.
- **Verify with ruff and compile on every task:**
  `python3 -m py_compile bin/photon_media.py bin/shelf-panel && python3 -m ruff check bin/photon_media.py bin/shelf-panel`

---

### Task 1: MPRIS metadata — `art_url` and `trackid`

**Files:**
- Modify: `bin/photon_media.py` — `Mpris.__init__` (the `self.title = ""`
  block, ~line 95), `Mpris._clear` (~line 152), `Mpris._apply` (~line 160).

**Interfaces:**
- Consumes: nothing new (all `Mpris` internals).
- Produces: `Mpris.art_url: str` and `Mpris.trackid: str` — always present
  attributes (possibly `""`), set on every `_apply` of a `Metadata` dict and
  cleared by `_clear`. Task 3 reads them via
  `self.mpris.art_url` / `self.mpris.trackid`.

- [ ] **Step 1: Add the two fields to `Mpris.__init__`**

In `bin/photon_media.py`, in `Mpris.__init__`, the block currently reads:

```python
        self.title = ""
        self.status = "Stopped"
```

Change it to:

```python
        self.title = ""
        #  mpris:artUrl: the track's cover, published as a fetchable
        #  file:// or http(s) URI, or absent.  mpris:trackid tags the track
        #  so a slow art reply knows when it has gone stale.
        self.art_url = ""
        self.trackid = ""
        self.status = "Stopped"
```

- [ ] **Step 2: Clear them in `Mpris._clear`**

`_clear` currently reads:

```python
    def _clear(self):
        self.owner = None
        self.title = ""
        self.status = "Stopped"
```

Change to:

```python
    def _clear(self):
        self.owner = None
        self.title = ""
        self.art_url = ""
        self.trackid = ""
        self.status = "Stopped"
```

- [ ] **Step 3: Fill them in `Mpris._apply`**

`_apply` currently starts:

```python
    def _apply(self, props):
        if "Metadata" in props:
            self.title = self._format(props.get("Metadata"))
```

Change to:

```python
    def _apply(self, props):
        if "Metadata" in props:
            meta = props.get("Metadata")
            self.title = self._format(meta)
            if isinstance(meta, dict):
                #  Players deliver the whole Metadata dict when the track
                #  changes, so both keys land in the same PropertiesChanged.
                self.art_url = str(meta.get("mpris:artUrl") or "")
                self.trackid = str(meta.get("mpris:trackid") or "")
```

- [ ] **Step 4: Verify compile and ruff**

Run: `python3 -m py_compile bin/photon_media.py && python3 -m ruff check bin/photon_media.py`
Expected: both clean.

- [ ] **Step 5: Verify the values arrive from the live bus (throwaway)**

Have a track playing with art (e.g. strawberry on a local file with cover).
Run:

```bash
QT_QPA_PLATFORM=offscreen python3 - <<'EOF'
import sys; sys.path.insert(0, "bin")
from PyQt6.QtWidgets import QApplication
from photon_media import Mpris
app = QApplication([])
m = Mpris()
print("service:", m.service)
print("trackid:", m.trackid)
print("art_url:", m.art_url)
EOF
```

Expected: `service:` a `org.mpris.MediaPlayer2.*` name, `trackid:`
non-empty, `art_url:` a `file:///…` (strawberry/kdeconnect) or `https://…`
(spotify) URI. If nothing is playing, start a track and re-run — an empty
`art_url` with no player is the *other* correct state, but this check must
see a real URI at least once.

- [ ] **Step 6: Commit**

```bash
git add bin/photon_media.py
git commit -m "feat(media): carry mpris:artUrl and mpris:trackid in Mpris"
```

---

### Task 2: `CoverArt` — the fetcher

**Files:**
- Modify: `bin/photon_media.py` — the `PyQt6` import block (~line 38), the
  "Nothing here polls" docstring paragraph (~line 15), and a new class
  inserted between the `Sink` class and the `#  ---- The widget ---`
  section (~line 415).

**Interfaces:**
- Consumes: Task 1's `Mpris.art_url` / `Mpris.trackid` (only via the
  `set_track` call in Task 3 — nothing here imports them).
- Produces: `class CoverArt(QObject)` with
  `changed = pyqtSignal()`,
  `def set_track(self, service, trackid, art_url)`,
  `@property pixmap` (a `QPixmap` or `None`), and class constants
  `MAX_PIXELS = 1024`, `CACHE = 8`, `TIMEOUT_MS = 8000`. Task 3
  instantiates it as `self.cover = CoverArt(self)` and connects
  `changed`.

- [ ] **Step 1: Extend the imports**

The import block currently reads:

```python
from PyQt6.QtCore import (QObject, QProcess, QRect, QSignalBlocker, QSize, Qt,
                          QTimer, pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QFontMetrics, QPainter, QPalette, QPolygon
```

Change to (new line first — alphabetical with the module list):

```python
from PyQt6.QtCore import (QObject, QProcess, QRect, QSignalBlocker, QSize, Qt,
                          QTimer, QUrl, pyqtSignal, pyqtSlot)
from PyQt6.QtGui import (QFontMetrics, QImageReader, QPainter, QPalette,
                         QPolygon, QPixmap)
from PyQt6.QtNetwork import QNetworkAccessManager
```

- [ ] **Step 2: Insert the `CoverArt` class**

After the end of `Sink` (its last method is `set_default_output`), before
the `#  ---- The widget ----------------` section header, insert:

```python
#  ---- Cover art ----------------------------------------------------------

class CoverArt(QObject):
    """The current track's artwork, fetched on demand and held briefly.

    Request/response rather than a poll: a fetch starts when MPRIS names a
    new track and ends when its image lands or its guard timer expires.
    file://, bare paths and http(s) all go through one
    QNetworkAccessManager call; anything else (mpris-proxy's coverart://)
    is treated as no art.  A failed fetch keeps the last good pixmap up --
    the well would flash if every broken link blanked it -- and a reply
    that arrives after the track has moved on is dropped by its
    (service, trackid, url) tag.
    """

    changed = pyqtSignal()

    MAX_PIXELS = 1024    # decode cap: a 4000px cover must not balloon the panel
    CACHE = 8            # LRU entries, url -> pixmap
    TIMEOUT_MS = 8000    # per-request abort guard

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nav = QNetworkAccessManager(self)
        self._nav.finished.connect(self._on_reply)
        self._state = None     # the (service, trackid, url) currently served
        self._pixmap = None    # what the well currently shows
        self._cache = {}       # url -> QPixmap, oldest first
        self._timers = {}      # reply -> abort guard
        self._tags = {}        # reply -> the state it was made under

    @property
    def pixmap(self):
        return self._pixmap

    def set_track(self, service, trackid, art_url):
        """MPRIS just named a track (or nothing).  Fetch, swap, or clear."""
        url = str(art_url or "")
        if service and url and "://" not in url and not url.startswith("/"):
            url = os.path.abspath(url)
        if service and url and "://" not in url:
            url = QUrl.fromLocalFile(url).toString()
        state = (service, str(trackid or ""), url)
        if state == self._state:
            return
        self._state = state
        if not url:
            #  No player, no artUrl: the source says the art is gone.
            self._show(None)
            return
        if url in self._cache:
            self._cache[url] = self._cache.pop(url)   # most-recent last
            self._show(self._cache[url])
            return
        if QUrl(url).scheme() not in ("file", "http", "https"):
            #  Opaque schemes: there is no standard client-side resolver.
            self._show(None)
            return
        self._start(url)

    def _start(self, url):
        reply = self._nav.get(QUrl(url))
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(self.TIMEOUT_MS)
        timer.timeout.connect(lambda: reply.abort())
        self._timers[reply] = timer
        self._tags[reply] = self._state

    def _on_reply(self, reply):
        timer = self._timers.pop(reply, None)
        if timer is not None:
            timer.stop()
        tag = self._tags.pop(reply, None)
        if tag != self._state:
            #  The track moved on while this was in flight.
            reply.deleteLater()
            return
        data = bytes(reply.readAll())
        reply.deleteLater()
        if not data:
            #  Timeout or empty body: the last good art stays up.
            return
        reader = QImageReader(data)
        reader.setMaximumSize(self.MAX_PIXELS, self.MAX_PIXELS)
        image = reader.read()
        if image.isNull():
            #  Decoding failed the same way: keep what is up.
            return
        url = tag[2]
        self._cache[url] = QPixmap.fromImage(image)
        while len(self._cache) > self.CACHE:
            self._cache.pop(next(iter(self._cache)))
        self._show(self._cache[url])

    def _show(self, pixmap):
        if pixmap is not self._pixmap:
            self._pixmap = pixmap
            self.changed.emit()
```

- [ ] **Step 3: Fix the module docstring's timer claim**

The docstring paragraph currently reads:

```
Nothing here polls.  Track and playback state arrive as D-Bus
PropertiesChanged signals, and the sink volume arrives on `pactl subscribe`.
The only timer in the file drives the marquee, and it stops when the title
fits.  That is what removes the once-a-second white flash: there is no
once-a-second anything left.
```

Change to:

```
Nothing here polls.  Track and playback state arrive as D-Bus
PropertiesChanged signals, the sink volume arrives on `pactl subscribe`,
and cover art is fetched when a new track names one -- a request that ends
with its image or its timeout, never with the next tick.  The timers in the
file: the marquee (which stops when the title fits) and one abort guard per
in-flight art fetch.  That is what removes the once-a-second white flash:
there is no once-a-second anything left.
```

- [ ] **Step 4: Verify compile and ruff**

Run: `python3 -m py_compile bin/photon_media.py && python3 -m ruff check bin/photon_media.py`
Expected: both clean.

- [ ] **Step 5: Verify fetch, cache, clear and failure semantics (throwaway)**

Create `/tmp/coverart-check.py`:

```python
import sys, time
sys.path.insert(0, "bin")
from PyQt6.QtGui import QImage, qRgb
from PyQt6.QtWidgets import QApplication
from photon_media import CoverArt

app = QApplication([])
c = CoverArt()

red = "/tmp/coverart-red.png"
img = QImage(256, 256, QImage.Format.Format_RGB32)
img.fill(qRgb(200, 30, 30))
assert img.save(red)

def spin(cond, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()

# 1. local file:// arrives
c.set_track("svc", "t1", "file://" + red)
assert spin(lambda: c.pixmap is not None, 5), "local fetch never landed"
assert (c.pixmap.width(), c.pixmap.height()) == (256, 256)

# 2. unresolvable scheme clears the well
c.set_track("svc", "t2", "coverart:///t2")
app.processEvents()
assert c.pixmap is None, "opaque scheme did not clear"

# 3. cached re-hit swaps back with no new fetch
c.set_track("svc", "t3", red)   # bare path, same file
assert spin(lambda: c.pixmap is not None, 5), "cache hit failed"

# 4. a failed fetch keeps the last good art up
c.TIMEOUT_MS = 300              # class attr, per-instance override
before = c.pixmap
c.set_track("svc", "t4", "file:///tmp/no-such-cover-art-x7y8z.png")
spin(lambda: not c._timers and not c._tags, 2)  # request resolved one way
assert c.pixmap is before, "failed fetch disturbed the well"

print("coverart OK")
```

Run: `QT_QPA_PLATFORM=offscreen python3 /tmp/coverart-check.py`
Expected: `coverart OK`. Then delete the script: `rm /tmp/coverart-check.py`

- [ ] **Step 6: Commit**

```bash
git add bin/photon_media.py
git commit -m "feat(media): CoverArt, request/response art fetch with LRU and abort guard"
```

---

### Task 3: The well in `MediaWidget`

**Files:**
- Modify: `bin/photon_media.py` — `MediaWidget.__init__` (after the
  `sink.outputs_changed.connect` line), `_relayout`, `_on_mpris`,
  `paintEvent`, and two new sections after the "painting" ones.

**Interfaces:**
- Consumes: Task 2's `CoverArt` (`set_track`, `pixmap`, `changed`), Task 1's
  `Mpris.art_url` / `Mpris.trackid`, existing `photon.trough(p, r)` and
  `photon.divider(p, y, x0, x1)` (unchanged), file constant
  `NATURAL_H = 100`, `GAP = 3`, `FIELD_H = 19`, `pad = 4` inside
  `_relayout`.
- Produces: `MediaWidget.natural_height_changed = pyqtSignal()` and
  `def natural_height(self, w) -> int` (`NATURAL_H + w` when a pixmap is up,
  else `NATURAL_H`); instance attributes `self.r_art` (a `QRect` or `None`),
  `self.art_div_y` (int or `None`), `self._has_art` (bool), `self.cover`
  (a `CoverArt`). Task 4 relies on the signal name and the one-arg
  `natural_height`.

- [ ] **Step 1: Instantiate the cover and the flip state in `__init__`**

In `MediaWidget.__init__`, the lines currently read:

```python
        self.sink = Sink(self)
        self.sink.changed.connect(self._on_sink)
        self.sink.outputs_changed.connect(self._on_outputs)
```

Add after them:

```python
        self.cover = CoverArt(self)
        self.cover.changed.connect(self._on_cover)
        self._has_art = False    # presence of a loaded pixmap, the only flip that relays
```

- [ ] **Step 2: The width-aware natural height and the panel signal**

After the `sizeHint` method in `MediaWidget`, insert:

```python
    natural_height_changed = pyqtSignal()

    def natural_height(self, w):
        #  The well pushes the rows below it down by the body's width, so
        #  art adds exactly w to the 100px body.
        return NATURAL_H + w if self._has_art else NATURAL_H
```

- [ ] **Step 3: Lay the well into `_relayout`**

At the top of `_relayout`, the lines currently read:

```python
    def _relayout(self):
        w = self.width()
        #  FvwmButtons' module-wide `Padding 4 0` does not reach a swallowed
        #  window -- it resizes the child to the whole cell -- so the inset
        #  that keeps this row in line with the meters above it has to come
        #  from here.  The reference's field is inset 3px from its group's
        #  content edge; 4 matches what the rest of the dock does.
        pad = 4

        self.r_title = QRect(pad, pad, w - 2 * pad, FIELD_H)

        by = self.r_title.bottom() + 1 + GAP
```

Replace from the blank line before `self.r_title =` down to the `by =`
line with:

```python
        if self._has_art:
            #  The square well, the etched rule, then the title in its usual
            #  place below.  (w-8) + 3 + 2 + 3 = w: everything below shifts
            #  down by the body's width, which is the whole of the cost.
            self.r_art = QRect(pad, pad, w - 2 * pad, w - 2 * pad)
            self.art_div_y = self.r_art.bottom() + 1 + GAP
            self.r_title = QRect(pad, self.art_div_y + 2 + GAP,
                                 w - 2 * pad, FIELD_H)
        else:
            self.r_art = None
            self.art_div_y = None
            self.r_title = QRect(pad, pad, w - 2 * pad, FIELD_H)

        by = self.r_title.bottom() + 1 + GAP
```

(Rest of `_relayout` — buttons, `div_y`, volume, output — unchanged.)

- [ ] **Step 4: Forward MPRIS state to the cover**

`_on_mpris` currently reads:

```python
    def _on_mpris(self):
        self._measure_title()
        self.update()
```

Change to:

```python
    def _on_mpris(self):
        self.cover.set_track(self.mpris.service, self.mpris.trackid,
                             self.mpris.art_url)
        self._measure_title()
        self.update()
```

- [ ] **Step 5: The flip handler and the painter**

After `_paint_title`, insert:

```python
    def _on_cover(self):
        has = self.cover.pixmap is not None
        if has != self._has_art:
            #  Only a presence flip moves the layout; a track-to-track swap
            #  repaints the same rect and costs no panel relayout.
            self._has_art = has
            self.natural_height_changed.emit()
        self.update()
        if self.parent() is None:
            #  Standalone window: nothing else grows or shrinks it.
            self.resize(self.width(), self.natural_height(self.width()))

    def _paint_art(self, p):
        photon.trough(p, self.r_art)
        r = self.r_art.adjusted(4, 4, -4, -4)
        art = self.cover.pixmap.scaled(
            r.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        x = r.left() + (r.width() - art.width()) // 2
        y = r.top() + (r.height() - art.height()) // 2
        p.drawPixmap(x, y, art)
```

- [ ] **Step 6: Paint the well and its divider**

`paintEvent` currently reads:

```python
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)
        self._paint_title(p)
        self._paint_transport(p)
        photon.divider(p, self.div_y, 2, self.width() - 3)
        self._paint_volume(p)
```

Change to:

```python
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)
        if self.r_art is not None:
            self._paint_art(p)
            photon.divider(p, self.art_div_y, 2, self.width() - 3)
        self._paint_title(p)
        self._paint_transport(p)
        photon.divider(p, self.div_y, 2, self.width() - 3)
        self._paint_volume(p)
```

- [ ] **Step 7: Verify compile and ruff**

Run: `python3 -m py_compile bin/photon_media.py && python3 -m ruff check bin/photon_media.py`
Expected: both clean.

- [ ] **Step 8: Verify geometry and pixels (throwaway)**

Create `/tmp/coverwell-check.py`:

```python
import sys
sys.path.insert(0, "bin")
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage, qRgb
from PyQt6.QtWidgets import QApplication
import photon
from photon_media import MediaWidget

app = QApplication([])
w = MediaWidget()

#  The check runs against a live session bus: drop the MPRIS wiring so the
#  state below is the only thing that can move the well.
w.mpris.changed.disconnect(w._on_mpris)

# Baseline: no art, no well.
w.resize(152, 100)
assert w.r_art is None
assert w.natural_height(152) == 100

# Art arrives through the public path.
red = "/tmp/coverwell-red.png"
img = QImage(256, 256, QImage.Format.Format_RGB32)
img.fill(qRgb(200, 30, 30))
assert img.save(red)
w.cover.set_track("svc", "t1", "file://" + red)

import time
end = time.monotonic() + 5
while time.monotonic() < end and not w._has_art:
    app.processEvents()
    time.sleep(0.01)
assert w._has_art, "well never came up"

# Geometry at the default inner width.
w.resize(152, w.natural_height(152))
assert w.natural_height(152) == 252
assert w.natural_height(150) == 250
assert w.natural_height(100) == 200
assert w.r_art == QRect(4, 4, 144, 144)
assert w.art_div_y == 151            # r_art.bottom() (147) + 1 + GAP (3)
assert w.r_title.y() == 156          # divider (151) + 2 + GAP
assert w.height() == 252

# Pixels: frame dark outline, grey inner shadow, art, face at the edge.
q = w.grab().toImage()
dark = qRgb(photon.DARK.red(), photon.DARK.green(), photon.DARK.blue())
tsh = qRgb(photon.TROUGH_SH.red(), photon.TROUGH_SH.green(),
           photon.TROUGH_SH.blue())
face = qRgb(photon.FACE.red(), photon.FACE.green(), photon.FACE.blue())
assert q.pixel(4, 4) == dark, "well outline missing"
assert q.pixel(5, 5) == tsh, "inner shadow missing"
assert q.pixel(10, 10) == qRgb(200, 30, 30), "art not drawn"
assert q.pixel(147, 147) == face, "trough leaked into the face"

# Absence again: source says gone.
w.cover.set_track("svc", "t2", "")
app.processEvents()
assert not w._has_art and w.natural_height(152) == 100

print("coverwell OK")
```

Run: `QT_QPA_PLATFORM=offscreen python3 /tmp/coverwell-check.py`
Expected: `coverwell OK`. Then: `rm /tmp/coverwell-check.py /tmp/coverwell-red.png`

- [ ] **Step 9: Standalone smoke run**

Run `python3 bin/photon_media.py` with a track playing (strawberry or
spotify). Expected: the window grows to a square well of the current art
above the title/transport/volume; stop all players and the well disappears
and the window shrinks back. Kill the process when done.

- [ ] **Step 10: Commit**

```bash
git add bin/photon_media.py
git commit -m "feat(media): cover-art well in the Media group"
```

---

### Task 4: `shelf-panel` routes the media height

**Files:**
- Modify: `bin/shelf-panel` — `Panel._natural_height` only (~line 368).
  Both widget classes are already imported (lines 46 and 48).

**Interfaces:**
- Consumes: Task 3's `MediaWidget.natural_height(w)` and
  `MediaWidget.natural_height_changed`. The panel's existing
  `hasattr(g.body_widget, "natural_height_changed")` connect in
  `Panel.__init__` picks the signal up automatically — do **not** add a
  second connection.
- Produces: the panel sizing the Media group to `100 + w` when art is up.

- [ ] **Step 1: Extend the width-aware branch**

`_natural_height` currently reads:

```python
    def _natural_height(self, widget, w):
        if isinstance(widget, WorldView):
            return widget.natural_height(w)
        if hasattr(widget, "natural_height"):
            return widget.natural_height()
        return widget.sizeHint().height()
```

Change the `isinstance` line to:

```python
        if isinstance(widget, (WorldView, MediaWidget)):
            return widget.natural_height(w)
```

(`MediaWidget.natural_height` now takes one argument, so it must match
*before* the argumentless `hasattr` fallback reaches it — it does: this
branch runs first and both names are already in the file's imports.)

- [ ] **Step 2: Verify compile and ruff**

Run: `python3 -m py_compile bin/shelf-panel && python3 -m ruff check bin/shelf-panel`
Expected: both clean.

- [ ] **Step 3: Live panel check (spec verification items 3 and 4)**

With a track playing: run `FvwmCommand Restart`. Expected:

- the Media group shows the square, dark-framed well above the title
  field, transport row and volume, with the etched rule between well and
  title;
- the frame reads like the World View's trough beside it: dark outline,
  grey channel, art not touching the border;
- `Super+[` / `Super+]` width steps re-layout the well with art visible;
- collapsing and re-expanding the Media group works;
- stop all players: the group drops back to its 100px body;
- no regressions: marquee scrolls, transport clicks, volume drag, output
  combobox.

- [ ] **Step 4: Commit**

```bash
git add bin/shelf-panel
git commit -m "feat(shelf): size the Media group for the art well"
```

---

### Task 5: Documentation

**Files:**
- Modify: `CLAUDE.md` — the `bin/photon_media.py` table row (~line 74) and
  the "Almost nothing polls" paragraph (~lines 87-91).
- Modify: `PANEL-DESIGN.md` — new addendum section at the end of the file.
- Modify: `docs/plans/2026-09-21-media-cover-art.md` — the spec header's
  workflow line (second block-quote line).

**Interfaces:** none.

- [ ] **Step 1: `CLAUDE.md` table row**

Current:

```
| `bin/photon_media.py` | MPRIS transport, marquee title, volume slider |
```

Change to:

```
| `bin/photon_media.py` | MPRIS transport, marquee title, cover art, volume slider |
```

- [ ] **Step 2: `CLAUDE.md` poll paragraph**

Current:

```
Almost nothing polls. Media takes D-Bus `PropertiesChanged` (matched on the
sender's *unique* bus name, never the well-known `org.mpris.MediaPlayer2.*`
one) and a long-lived `pactl subscribe`; the pager takes root-window
```

Change to:

```
Almost nothing polls. Media takes D-Bus `PropertiesChanged` (matched on the
sender's *unique* bus name, never the well-known `org.mpris.MediaPlayer2.*`
one), a long-lived `pactl subscribe`, and it fetches cover art when a track
names one -- a request that ends with its image or its timeout; the pager
takes root-window
```

(the rest of the paragraph is unchanged).

- [ ] **Step 3: `PANEL-DESIGN.md` addendum**

Append to the end of the file, after the `## Open questions` list:

```markdown

## Cover art in the Media group (2026-09-21, a deliberate departure)

The reference's CD Player has no art -- title field, four buttons, volume.
The shelf's Media group shows it now. Measured 2026-09-21 on the live
bus: strawberry and the kdeconnect proxy publish `file://` covers,
spotify publishes `https://`, firefox publishes none. Fetching is
request/response through `QNetworkAccessManager` (the only new timer is
the eight-second per-request abort guard), decodes are capped at 1024px,
and the well exists only while a real image has loaded, so a group
without art is the 100px body as before. The frame reuses photon's
meter-trough bevel -- the dark `#4b4b4b` outline and `#bcbcbc` channel,
the same border language as the reference's World View. Design:
`docs/plans/2026-09-21-media-cover-art.md`; plan:
`docs/plans/2026-09-21-media-cover-art-plan.md`.
```

- [ ] **Step 4: Point the spec at the plan**

In `docs/plans/2026-09-21-media-cover-art.md`, the header reads:

```
> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement
> this plan task-by-task. (Plan sections land after review.)
```

Change the parenthetical to:

```
> this plan task-by-task. (Plan: `docs/plans/2026-09-21-media-cover-art-plan.md`.)
```

- [ ] **Step 5: Verify the doc changes read back correctly**

Run: `git diff CLAUDE.md PANEL-DESIGN.md docs/plans/2026-09-21-media-cover-art.md`
Expected: exactly the four edits above, no drift.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md PANEL-DESIGN.md docs/plans/2026-09-21-media-cover-art.md
git commit -m "docs: cover-art addendum to the panel docs"
```
