import os
import tempfile
import types
import unittest

_TMP = tempfile.mkdtemp(prefix="photon_thumbs.")
os.environ["FVWM_USERDIR"] = _TMP
os.makedirs(os.path.join(_TMP, "images", "thumbs"), exist_ok=True)

from photon_tasks import (
    TasksWidget,
    THUMB_DIR,
    _Task,
    order_tasks,
    strip_height,
    thumbnail_heights,
    tile_cols,
    tile_rect,
)
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

import photon

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


class ThumbnailLayoutTest(unittest.TestCase):
    def test_equal_height_crops_shrink_together_then_collapse(self):
        landscape = QImage(200, 100, QImage.Format.Format_RGB32)
        portrait = QImage(100, 200, QImage.Format.Format_RGB32)
        images = [landscape, None, portrait]
        self.assertEqual(thumbnail_heights(images, 320), [154, 0, 154])
        self.assertEqual(thumbnail_heights(images, 208), [104, 0, 104])
        self.assertEqual(thumbnail_heights(images, 164), [82, 0, 82])
        self.assertEqual(thumbnail_heights(images, 162), [0, 0, 0])


class ThumbnailTornReadTest(unittest.TestCase):
    """The capture writes the PNG in place, so a watcher event can arrive
    mid-write; a torn decode must hold the last good image (regression:
    a blanked preview until the next unrelated file change)."""

    def setUp(self):
        self.path = os.path.join(THUMB_DIR, "0x1.png")
        self.me = types.SimpleNamespace(_thumbs={})

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _write(self, size):
        img = QImage(size, size, QImage.Format.Format_RGB32)
        img.fill(0xff404040)
        self.assertTrue(img.save(self.path, "PNG"))

    def test_torn_read_holds_last_good_image(self):
        self._write(2)
        good = TasksWidget._thumbnail(self.me, 1)
        self.assertFalse(good.isNull())

        with open(self.path, "rb") as f:
            full = f.read()
        with open(self.path, "wb") as f:
            f.write(full[:16])

        torn = TasksWidget._thumbnail(self.me, 1)
        self.assertFalse(torn.isNull())
        self.assertEqual(torn.width(), good.width())

        self._write(3)
        fresh = TasksWidget._thumbnail(self.me, 1)
        self.assertFalse(fresh.isNull())
        self.assertEqual(fresh.width(), 3)

    def test_missing_file_is_blank(self):
        self._write(2)
        self.assertFalse(TasksWidget._thumbnail(self.me, 1).isNull())
        os.unlink(self.path)
        self.assertTrue(TasksWidget._thumbnail(self.me, 1).isNull())


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


class PinnedModelTest(unittest.TestCase):
    def test_pinned_first_in_client_order_then_minimized_last(self):
        found = [task(1, iconified=True), task(2, pinned=True),
                 task(3), task(4, pinned=True, iconified=True)]
        self.assertEqual([t.wid for t in order_tasks(found)], [2, 4, 3, 1])

    def test_minimizing_a_tile_does_not_move_it(self):
        found = [task(1, pinned=True, iconified=True), task(2, pinned=True)]
        self.assertEqual([t.wid for t in order_tasks(found)], [1, 2])

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


class TileLayoutTest(unittest.TestCase):
    def setUp(self):
        self.w = FakeTasks()
        self.w.resize(210, 600)

    def tearDown(self):
        for wid in (1, 2):
            path = os.path.join(THUMB_DIR, f"0x{wid:x}.png")
            if os.path.exists(path):
                os.unlink(path)

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
        face = QRect(5, 5, 24, 24)  # the icon box, clear of row text
        darkest = min(img.pixelColor(x, y).lightness()
                      for x in range(face.left(), face.right())
                      for y in range(face.top(), face.bottom()))
        self.assertLess(darkest, photon.FACE.lightness() - 60)


if __name__ == "__main__":
    unittest.main()
