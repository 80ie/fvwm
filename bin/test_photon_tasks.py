import importlib.util
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
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

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

    def test_height_is_whole_tile_rows_less_the_last_etch(self):
        self.assertEqual(strip_height(0, 206), 0)
        self.assertEqual(strip_height(2, 206), 30)
        self.assertEqual(strip_height(6, 206), 30)
        self.assertEqual(strip_height(7, 206), 62)
        self.assertEqual(strip_height(5, 96), 62)

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
        edges = 8 + photon.PAD_R  # two wells, and the face between them
        self.assertEqual(w.natural_height(420), 30 + 3 * 25 + edges)
        self.assertEqual(w.natural_height(100), 62 + 3 * 25 + edges)

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
        self.assertEqual(rects[2], QRect(2, 36 + photon.PAD_R, 206, 25))

    def test_strip_and_rows_are_two_wells_with_shelf_face_between(self):
        w, gap = self.w, photon.PAD_R
        w._set_tasks([task(1, pinned=True), task(2)])
        img = w.grab().toImage()
        for y in range(34, 34 + gap):
            for x in (0, 100, 209):
                self.assertEqual(img.pixelColor(x, y).rgb(), photon.FACE.rgb())
            self.assertEqual(w._row_at(QPoint(18, y)), -1)
        self.assertEqual(w._row_at(QPoint(18, 36 + gap)), 1)

    def test_one_well_when_there_is_only_one_kind(self):
        w = self.w
        w._set_tasks([task(1, pinned=True)])
        self.assertEqual(w.natural_height(210), 30 + 4)
        w._set_tasks([task(2)])
        self.assertEqual(w.natural_height(210), 25 + 4)

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

    def test_only_the_rows_between_tiles_are_etched(self):
        self.w._set_tasks([task(i, pinned=True) for i in range(7)])
        img = self.w.grab().toImage()
        at = lambda y: img.pixelColor(150, y).rgb()
        self.assertEqual((at(32), at(33)), (photon.SH.rgb(), photon.HI.rgb()))
        self.assertEqual((at(64), at(65)), (photon.WELL.rgb(), photon.WELL.rgb()))

    def test_iconless_tile_draws_an_initial(self):
        self.w._set_tasks([task(1, pinned=True, title="Zed")])
        img = self.w.grab().toImage()
        face = QRect(5, 5, 24, 24)  # the icon box, clear of row text
        darkest = min(img.pixelColor(x, y).lightness()
                      for x in range(face.left(), face.right())
                      for y in range(face.top(), face.bottom()))
        self.assertLess(darkest, photon.FACE.lightness() - 60)


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


def _load_panel():
    open(os.path.join(_TMP, "panel.items"), "w").close()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shelf-panel")
    loader = importlib.machinery.SourceFileLoader("shelf_panel", path)
    shelf = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("shelf_panel", loader))
    loader.exec_module(shelf)
    panel = shelf.Panel()
    panel._state_timer.stop()
    return shelf, panel


class PanelTooltipTest(unittest.TestCase):
    """fvwm gives the shelf NeverFocus, and Qt only shows tooltips in an
    inactive window that asks for them."""

    def test_panel_shows_tooltips_while_inactive(self):
        shelf, panel = _load_panel()
        self.assertTrue(panel.testAttribute(
            shelf.Qt.WidgetAttribute.WA_AlwaysShowToolTips))


class WellTest(unittest.TestCase):
    def test_well_outline_is_a_shadow_all_round(self):
        img = QImage(12, 12, QImage.Format.Format_RGB32)
        img.fill(0xFFFF00FF)
        p = QPainter(img)
        photon.sunken(p, QRect(0, 0, 12, 12), photon.WELL)
        p.end()
        px = lambda x, y: img.pixelColor(x, y).rgb()
        for x, y in ((6, 0), (0, 6), (10, 6), (6, 10)):
            self.assertEqual(px(x, y), photon.WELL_EDGE.rgb())
        for x, y in ((1, 1), (9, 1), (1, 9)):
            self.assertEqual(px(x, y), photon.WELL_SH.rgb())
        for x, y in ((11, 6), (6, 11)):
            self.assertEqual(px(x, y), photon.WELL_LIP.rgb())
        self.assertNotEqual(photon.WELL_EDGE.rgb(), photon.DARK.rgb())


class SectionBevelTest(unittest.TestCase):
    def test_bevel_flag_sizes_the_break_below_a_section(self):
        shelf, panel = _load_panel()
        spec = os.path.join(_TMP, "bevel.items")
        with open(spec, "w") as f:
            f.write("group A | nobar | bevel\nwidget clock\n"
                    "group B | nobar\nwidget clock\n"
                    "group C | nobar\nwidget clock\n")
        panel.groups = shelf.read_spec(spec)
        a, b, c = panel.groups
        self.assertEqual([g.bevel for g in panel.groups], [True, False, False])
        self.assertEqual(panel._sep_h(a), photon.BEVEL_H)
        self.assertEqual(panel._sep_h(b), shelf.SEP_H)
        self.assertEqual(panel._sep_h(c), 0)

    def test_bevel_rule_is_the_frame_profile_on_its_side(self):
        img = QImage(4, photon.BEVEL_H, QImage.Format.Format_RGB32)
        img.fill(0)
        p = QPainter(img)
        photon.bevel_rule(p, 0, 0, 3)
        p.end()
        down = [img.pixelColor(1, y).rgb() for y in range(photon.BEVEL_H)]
        self.assertEqual(down, FrameTest.columns(photon.BEVEL_H, "left"))


class _Fifty(QWidget):
    def natural_height(self):
        return 50


class SectionPadTest(unittest.TestCase):
    def _panel(self, spec):
        shelf, panel = _load_panel()
        path = os.path.join(_TMP, "pad.items")
        with open(path, "w") as f:
            f.write(spec)
        panel.groups = shelf.read_spec(path)
        for g in panel.groups:
            g.body_widget = _Fifty(panel)
        return shelf, panel

    def test_pad_flag_puts_shelf_face_above_and_below_the_body(self):
        shelf, panel = self._panel(
            "group A | nobar | pad\nwidget clock\ngroup B | nobar\nwidget clock\n")
        a, b = panel.groups
        pad = photon.PAD_R
        self.assertEqual([g.pad for g in panel.groups], [True, False])
        self.assertEqual(panel._group_height(a, 100), 2 * pad + 50 + shelf.SEP_H)
        self.assertEqual(panel._group_height(b, 100), 50)
        y = panel._place_group(a, 0, 10, 100)
        self.assertEqual(a.body, QRect(0, 10 + pad, 100 - pad, 50))
        self.assertEqual(a.sep_y, 10 + 2 * pad + 50)
        self.assertEqual(y, a.sep_y + shelf.SEP_H)

    def test_padded_flex_section_still_fills_to_the_next(self):
        shelf, panel = self._panel(
            "group A | nobar | pad\nwidget clock\nflex\n"
            "group B | nobar\nwidget clock\n")
        panel.resize(100 + photon.FRAME_W, 400)
        panel.relayout()
        a, b = panel.groups
        self.assertEqual(a.sep_y + shelf.SEP_H, b.header.top())
        self.assertGreater(a.body.height(), 50)


class FrameTest(unittest.TestCase):
    @staticmethod
    def columns(width, edge):
        img = QImage(width, 1, QImage.Format.Format_RGB32)
        img.fill(0xFFFF00FF)
        p = QPainter(img)
        photon.frame(p, QRect(0, 0, width, 1), edge)
        p.end()
        return [img.pixelColor(x, 0).rgb() for x in range(width)]

    def test_seven_is_the_reference_double_bevel(self):
        want = [c.rgb() for c in (photon.DARK, photon.HI, photon.FACE_ALT,
                                  photon.FACE_ALT, photon.FRAME_MID,
                                  photon.DARK, photon.HI)]
        self.assertEqual(self.columns(7, "left"), want)
        self.assertEqual(self.columns(7, "right"), want[::-1])

    def test_narrower_keeps_the_outer_bevel_on_the_screen_side(self):
        want = [c.rgb() for c in (photon.DARK, photon.HI, photon.FACE_ALT)]
        self.assertEqual(self.columns(3, "left"), want)
        self.assertEqual(self.columns(3, "right"), want[::-1])


if __name__ == "__main__":
    unittest.main()
