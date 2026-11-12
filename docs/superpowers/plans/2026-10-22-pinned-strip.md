# Pinned-window strip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sticky windows leave the shelf's window list as full rows and become a strip of icon tiles at the top of the same well, with a right-click Pin/Unpin.

**Architecture:** Everything stays in `bin/photon_tasks.py`'s `TasksWidget`. A window is *pinned* when its `_NET_WM_STATE` holds `_NET_WM_STATE_STICKY`; pinned tasks sort to the front of `self.tasks`, and `_rows()` hands them tile cells instead of row rects, so painting, hover, clicks and the context menu keep working by index. Pin/Unpin is an EWMH client message, like Maximize already is.

**Tech Stack:** Python 3, PyQt6, python-xlib; tests with `unittest` under `QT_QPA_PLATFORM=offscreen`.

**Spec:** GitHub issue 80ie/fvwm#20 and option A of the design canvas https://claude.ai/artifact/UJem9EtdnPv6q3atL4DMq4 ("A: tab strip in the well"). The decisions taken in review are copied into Global Constraints below; the canvas is the visual reference.

## Global Constraints

- Membership is `_NET_WM_STATE_STICKY in _NET_WM_STATE`, nothing else. fvwm3 1.1.5 (`fvwm/ewmh_events.c`, `ewmh_WMStateSticky`) publishes it only for a window sticky across pages *and* desks, so `TileArrange`'s temporary pages-only `StickyAcrossPages` (config, `State 15`) never puts a tiled window in the strip. Do not key on `_NET_WM_DESKTOP == 0xFFFFFFFF`.
- A window counts as pinned however it got sticky: the new menu item, Super+A (`Stick Toggle`), the window-ops "Sticky" entry, or a `Style ... Sticky`.
- Pin sends `_NET_WM_STATE` with action `1` (add) and Unpin with `0` (remove), never `2` (toggle): fvwm maps toggle on a pages-only sticky window to `Stick on`, which would invert a mid-arrange Unpin.
- Geometry: a tile cell is `TILE = 32` px square, a 30x30 face plus a 2 px etch on its right (`SH` then `HI`, vertical) and a full-width `photon.divider` under each tile row. Icons are `TILE_ICON = 24` px, centred in the face (offset 3,3). Tiles wrap: `cols = max(1, interior_width // TILE)`. The strip sits inside the existing `photon.sunken` well, above the rows.
- Tile faces reuse the row vocabulary, never `photon.button`: hover `photon.FACE_HI`, minimized `photon.WELL`, otherwise `photon.FACE`; a minimized tile's icon is painted at opacity `0.6`; the focused tile gets the rows' `photon.DARK` outline.
- Pinned tasks never get a thumbnail, and their PNGs are not watched.
- Pinned tiles are in `_NET_CLIENT_LIST` order (mapping order), so nothing is persisted. Unpinned rows keep today's order, minimized last.
- Clicks on a tile behave exactly like a row: left raises, or minimizes the focused top window; middle closes; right opens the menu.
- The title of a tile appears as a Qt tooltip on hover.
- Photon colours come only from `photon.*` constants (CLAUDE.md: never literal `QColor` values).
- Comments: at most 3 lines each, sparse (user's CLAUDE.md).

## Review Focus

1. **Dragging the shelf width across a column boundary.** Five pinned windows at 420 px fit in one row and at 110 px take two; the well must grow and shrink with it, not clip the second row. Test: `test_natural_height_follows_width` (Task 2).
2. **Clicking a tile on the second strip row.** Index mapping must reach the 7th tile, not the first row or the first list row. Test: `test_row_at_reaches_second_tile_row` (Task 3).
3. **Pinning a minimized window that had a preview.** Its thumbnail frame must disappear and stop being watched; unpinning it must bring the preview back on the next refresh. Test: `test_pinned_thumbnails_are_neither_sized_nor_watched` (Task 3).
4. **A pin that changes no row count.** Pinning one of five windows keeps `len(tasks)` at 5 but changes the height; the panel must still relayout. Test: `test_pin_change_alone_emits_height_change` (Task 2).
5. **A pinned window with no `_NET_WM_ICON` and no theme icon.** A blank tile is unidentifiable; it should show the first letter of its title. Test: `test_iconless_tile_draws_an_initial` (Task 3).

---

### Task 1: Strip geometry

**Files:**
- Modify: `bin/photon_tasks.py` (module level, beside `thumbnail_heights`)
- Test: `bin/test_photon_tasks.py`

**Interfaces:**
- Produces: `TILE = 32`, `TILE_ICON = 24`; `tile_cols(width: int) -> int`; `strip_height(count: int, width: int) -> int`; `tile_rect(i: int, left: int, top: int, width: int) -> QRect` (the whole 32x32 cell, etch included).

- [ ] **Step 1: Write the failing tests**

```python
class StripGeometryTest(unittest.TestCase):
    def test_columns_fit_the_interior(self):
        self.assertEqual(tile_cols(206), 6)
        self.assertEqual(tile_cols(96), 3)
        self.assertEqual(tile_cols(10), 1)

    def test_height_is_whole_tile_rows(self):
        self.assertEqual(strip_height(0, 206), 0)
        self.assertEqual(strip_height(2, 206), 32)
        self.assertEqual(strip_height(6, 206), 32)
        self.assertEqual(strip_height(7, 206), 64)
        self.assertEqual(strip_height(5, 96), 64)

    def test_cells_wrap_left_to_right(self):
        self.assertEqual(tile_rect(0, 2, 2, 206), QRect(2, 2, 32, 32))
        self.assertEqual(tile_rect(1, 2, 2, 206), QRect(34, 2, 32, 32))
        self.assertEqual(tile_rect(6, 2, 2, 206), QRect(2, 34, 32, 32))
```

Add `tile_cols, strip_height, tile_rect` to the `photon_tasks` import and `from PyQt6.QtCore import QRect`.

- [ ] **Step 2: Run to verify failure**

Run: `cd bin && QT_QPA_PLATFORM=offscreen python3 -m unittest test_photon_tasks -v`
Expected: ImportError on `tile_cols`.

- [ ] **Step 3: Implement the three functions and two constants in `bin/photon_tasks.py`**

- [ ] **Step 4: Run to verify pass**

Same command. Expected: all tests OK.

- [ ] **Step 5: Commit**

```bash
git add bin/photon_tasks.py bin/test_photon_tasks.py
git commit -m "tasks: strip geometry for pinned tiles"
```

### Task 2: Pinned tasks in the model, and the height that follows them

**Files:**
- Modify: `bin/photon_tasks.py` (`_Task`, `_EXTRA_ATOMS`, `refresh`, `natural_height`, `sizeHint`)
- Modify: `bin/shelf-panel` (`Panel._natural_height`)
- Test: `bin/test_photon_tasks.py`

**Interfaces:**
- Consumes: `strip_height` (Task 1).
- Produces:
  - `_Task` gains a trailing field `pinned`, default `False` (`namedtuple(..., defaults=(False,))`), so `bin/shelf-snapshot`'s positional-free construction keeps working.
  - `order_tasks(tasks: list) -> list`: stable sort on `(not t.pinned, t.iconified)`.
  - `TasksWidget._set_tasks(self, found: list) -> None`: assigns `self.tasks = order_tasks(found)`, then emits `natural_height_changed` when `(len(tasks), pinned count)` differs from before. `refresh()` ends by calling it instead of its own `resized` logic.
  - `TasksWidget.natural_height(self, w=None) -> int`: `strip_height(pinned, w - 2*WELL_PAD) + unpinned*ROW_H + 2*WELL_PAD`; `w=None` means `photon.SHELF_INNER`.
  - `"_NET_WM_STATE_STICKY"` in `_EXTRA_ATOMS`; `refresh()` sets `pinned=self.atoms["_NET_WM_STATE_STICKY"] in state`.

- [ ] **Step 1: Write the failing tests**

Add a QApplication and an X-free widget to the test module:

```python
from PyQt6.QtWidgets import QApplication
_APP = QApplication.instance() or QApplication([])

def task(wid, pinned=False, iconified=False, title="t"):
    return _Task(wid=wid, win=None, title=title, focused=False,
                 iconified=iconified, maximized=False, icon=None, cls=None,
                 pinned=pinned)

class FakeTasks(TasksWidget):
    def _watch_x(self):
        self.atoms = {"_NET_WM_STATE_STICKY": 501}
        self.sent = []

    def _send(self, win, atom_name, data):
        self.sent.append((atom_name, data))
```

```python
class PinnedModelTest(unittest.TestCase):
    def test_pinned_first_in_client_order_then_minimized_last(self):
        found = [task(1, iconified=True), task(2, pinned=True),
                 task(3), task(4, pinned=True, iconified=True)]
        self.assertEqual([t.wid for t in order_tasks(found)], [2, 4, 3, 1])

    def test_natural_height_follows_width(self):
        w = FakeTasks()
        w._set_tasks([task(i, pinned=True) for i in range(5)]
                     + [task(10), task(11), task(12)])
        self.assertEqual(w.natural_height(420), 32 + 3 * 25 + 4)
        self.assertEqual(w.natural_height(100), 64 + 3 * 25 + 4)

    def test_pin_change_alone_emits_height_change(self):
        w = FakeTasks()
        w._set_tasks([task(1), task(2)])
        hits = []
        w.natural_height_changed.connect(lambda: hits.append(1))
        w._set_tasks([task(1), task(2)])
        self.assertEqual(hits, [])
        w._set_tasks([task(1, pinned=True), task(2)])
        self.assertEqual(hits, [1])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bin && QT_QPA_PLATFORM=offscreen python3 -m unittest test_photon_tasks -v`
Expected: `TypeError` on `_Task(... pinned=...)`, or ImportError on `order_tasks`.

- [ ] **Step 3: Implement the Produces list in `bin/photon_tasks.py`**

`sizeHint()` returns `QSize(photon.SHELF_INNER, self.natural_height(photon.SHELF_INNER))`; `main()` calls `natural_height()` unchanged.

- [ ] **Step 4: Pass the body width through in `bin/shelf-panel`**

`Panel._natural_height`: add `TasksWidget` to the `isinstance` tuple that calls `widget.natural_height(w)`. `bin/shelf-snapshot` swaps `shelf.TasksWidget` for its subclass before building the panel, so the check still matches there.

- [ ] **Step 5: Run to verify pass**

Same command. Expected: all tests OK. Then
`FVWM_USERDIR=$PWD QT_QPA_PLATFORM=offscreen bin/shelf-snapshot --out /tmp/claude-1000/snap.png --width 220 --height 900` exits 0.

- [ ] **Step 6: Commit**

```bash
git add bin/photon_tasks.py bin/shelf-panel bin/test_photon_tasks.py
git commit -m "tasks: sticky windows are pinned, sorted first, sized by width"
```

### Task 3: Tile layout and painting

**Files:**
- Modify: `bin/photon_tasks.py` (`_rows`, `_poll_thumbnails`, `_assert_thumb_watches`, `_icon`, `_draw_icon`, `paintEvent`, `refresh`'s icon cache)
- Modify: `bin/shelf-snapshot` (`Tasks._watch_x` sample)
- Test: `bin/test_photon_tasks.py`

**Interfaces:**
- Consumes: `TILE`, `TILE_ICON`, `tile_rect`, `strip_height` (Task 1); `_Task.pinned`, `order_tasks`, `_set_tasks` (Task 2).
- Produces:
  - `_rows()` keeps its `(rects, images)` return. `rects[i]` for a pinned task is its `tile_rect(i, inner.left(), inner.top(), inner.width())`; unpinned rows start at `inner.top() + strip_height(...)`. `images[i]` is `None` for every pinned task, and `thumbnail_heights` gets `available = inner.height() - strip - unpinned*ROW_H`.
  - `_row_at(pos)` unchanged; it finds tiles because they are in `rects`.
  - `_icon(self, win, size=16) -> QImage | None`: picks the `_NET_WM_ICON` frame nearest `size`. The icon cache is keyed by `(wid, size)`, and `refresh()` asks for `TILE_ICON` when the task is pinned.
  - `_draw_icon(self, p, task, box) -> bool`: `True` when something was drawn.
  - `_thumb_wanted(self) -> set[str]`: the PNG paths for tasks that are `iconified and not pinned`, used by both `_poll_thumbnails` and `_assert_thumb_watches`.

- [ ] **Step 1: Write the failing tests**

```python
class TileLayoutTest(unittest.TestCase):
    def setUp(self):
        self.w = FakeTasks()
        self.w.resize(210, 600)

    def test_tiles_then_rows(self):
        self.w._set_tasks([task(1, pinned=True), task(2, pinned=True), task(3)])
        rects, _ = self.w._rows()
        self.assertEqual(rects[0], QRect(2, 2, 32, 32))
        self.assertEqual(rects[1], QRect(34, 2, 32, 32))
        self.assertEqual(rects[2], QRect(2, 34, 206, 25))

    def test_row_at_reaches_second_tile_row(self):
        self.w._set_tasks([task(i, pinned=True) for i in range(7)] + [task(9)])
        self.assertEqual(self.w._row_at(QPoint(18, 50)), 6)
        self.assertEqual(self.w._row_at(QPoint(18, 80)), 7)

    def test_pinned_thumbnails_are_neither_sized_nor_watched(self):
        for wid in (1, 2):
            QImage(4, 4, QImage.Format.Format_RGB32).save(
                os.path.join(THUMB_DIR, f"0x{wid:x}.png"))
        self.w._set_tasks([task(1, pinned=True, iconified=True),
                           task(2, iconified=True)])
        rects, images = self.w._rows()
        self.assertIsNone(images[0])
        self.assertEqual(rects[0].height(), 32)
        self.assertGreater(rects[1].height(), 25)
        self.assertEqual(self.w._thumb_wanted(),
                         {os.path.join(THUMB_DIR, "0x2.png")})

    def test_iconless_tile_draws_an_initial(self):
        self.w._set_tasks([task(1, pinned=True, title="Zed")])
        img = self.w.grab().toImage()
        face = QRect(2, 2, 30, 30)
        darkest = min(img.pixelColor(x, y).lightness()
                      for x in range(face.left(), face.right())
                      for y in range(face.top(), face.bottom()))
        self.assertLess(darkest, photon.FACE.lightness() - 60)
```

Import `QPoint`, `photon`; remove the two PNGs in `tearDown`.

- [ ] **Step 2: Run to verify failure**

Run: `cd bin && QT_QPA_PLATFORM=offscreen python3 -m unittest test_photon_tasks -v`
Expected: `test_tiles_then_rows` fails on `rects[0]` (a full-width row), `_thumb_wanted` AttributeError.

- [ ] **Step 3: Implement the Produces list, then the tile branch of `paintEvent`**

For a pinned task, paint: the face (`rect.adjusted(0, 0, -2, -2)`) in the Global Constraints colour; the vertical etch at `face.right()+1` (`SH`) and `+2` (`HI`); a `photon.divider` across `inner` under the last tile of each tile row; the 24 px icon centred in the face, through `p.setOpacity(0.6)` when minimized; if `_draw_icon` returns `False`, the title's first character in `self.font_row`, `photon.INK`, centred; the `DARK` outline when focused. The unpinned branch stays as it is.

- [ ] **Step 4: Run to verify pass**

Same command. Expected: all tests OK.

- [ ] **Step 5: Show the strip in `shelf-snapshot`**

In `Tasks._watch_x`, append two pinned samples, `("Signal", "internet-chat", False, True)` and `("Spotify", "multimedia", False, False)`, with `pinned=True` (extend the tuple with a fifth element and pass it through). If a name is missing from the Haiku set the tile shows its initial, which is fine here. Render:
`FVWM_USERDIR=$PWD QT_QPA_PLATFORM=offscreen bin/shelf-snapshot --out /tmp/claude-1000/snap.png --width 220 --height 900`
Expected: two tiles above the kitty row, the Signal one on `WELL` with a dimmed icon, then the divider, then the four rows. Compare by eye against canvas artboard A.

- [ ] **Step 6: Commit**

```bash
git add bin/photon_tasks.py bin/shelf-snapshot bin/test_photon_tasks.py
git commit -m "tasks: draw pinned windows as an icon strip above the list"
```

### Task 4: Pin/Unpin and tooltips, live

**Files:**
- Modify: `bin/photon_tasks.py` (`contextMenuEvent`, new `_pin`, `_tooltip`, `event`; module docstring)
- Modify: `CLAUDE.md` (the `bin/photon_tasks.py` row of the shelf components table)
- Test: `bin/test_photon_tasks.py`

**Interfaces:**
- Consumes: `_Task.pinned` (Task 2); `_rows`, `_row_at` (Task 3).
- Produces:
  - `TasksWidget._pin(self, task) -> None`: `self._send(task.win, "_NET_WM_STATE", [0 if task.pinned else 1, self.atoms["_NET_WM_STATE_STICKY"], 0, 2, 0])`.
  - `TasksWidget._tooltip(self, pos: QPoint) -> str | None`: the title (or `"(untitled)"`) of the pinned tile under `pos`, else `None`.
  - `event()` handles `QEvent.Type.ToolTip` with `QToolTip.showText` / `hideText` from `_tooltip`, and passes everything else to `super().event`.
  - The context menu's first action is `"Unpin"` when `t.pinned`, else `"Pin"`, calling `_pin(t)`, then a separator, then the existing actions.

- [ ] **Step 1: Write the failing tests**

```python
class PinActionTest(unittest.TestCase):
    def test_pin_adds_and_unpin_removes_never_toggles(self):
        w = FakeTasks()
        w._pin(task(1))
        w._pin(task(1, pinned=True))
        self.assertEqual(w.sent, [("_NET_WM_STATE", [1, 501, 0, 2, 0]),
                                  ("_NET_WM_STATE", [0, 501, 0, 2, 0])])

    def test_tooltip_names_tiles_only(self):
        w = FakeTasks()
        w.resize(210, 600)
        w._set_tasks([task(1, pinned=True, title="Signal (31)"),
                      task(2, title="Firefox")])
        self.assertEqual(w._tooltip(QPoint(18, 18)), "Signal (31)")
        self.assertIsNone(w._tooltip(QPoint(18, 46)))
        self.assertIsNone(w._tooltip(QPoint(150, 18)))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd bin && QT_QPA_PLATFORM=offscreen python3 -m unittest test_photon_tasks -v`
Expected: AttributeError on `_pin`.

- [ ] **Step 3: Implement the Produces list**

- [ ] **Step 4: Run to verify pass**

Same command. Expected: all tests OK.

- [ ] **Step 5: Update the docs**

Module docstring: one paragraph saying that sticky windows (`_NET_WM_STATE_STICKY`, set by fvwm only for page-and-desk sticky) are drawn as a tile strip at the top of the well, and that Pin/Unpin is add/remove rather than toggle, with the reason. `CLAUDE.md` table row: "the window list, drawn from EWMH; sticky windows as an icon strip at the top; shows `lib/Thumbnail` previews for minimized windows".

- [ ] **Step 6: Live check**

Ask the user before touching the running session. Then restart only the panel:
`sh -c 'pkill -f "bin/shelf-panel$"; sleep 1; exec "$FVWM_USERDIR/bin/shelf-panel"' &`
Check by hand, each with the expected result:
1. Signal and Spotify, both sticky today, show as tiles, with no preview frames.
2. Right-click a normal row, choose Pin: it moves to the strip. Right-click the tile, choose Unpin: it returns as a row, with its preview if minimized.
3. Super+A on a focused window pins it; Super+A again unpins it.
4. Switch page (Super+1..9) and desk (Super+F1/F2): the tiles stay; rows follow the page as before.
5. Tile a page (`TileToggle`) holding an unpinned window: it never appears in the strip.
6. Drag the shelf width with 7+ pinned windows: the strip wraps and the rows below move.

- [ ] **Step 7: Commit**

```bash
git add bin/photon_tasks.py bin/test_photon_tasks.py CLAUDE.md
git commit -m "tasks: Pin/Unpin in the window menu, tooltips on tiles"
```

Close issue #20 with a comment naming the four commits, only after the user confirms the live check.
