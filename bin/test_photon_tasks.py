import os
import tempfile
import types
import unittest

_TMP = tempfile.mkdtemp(prefix="photon_thumbs.")
os.environ["FVWM_USERDIR"] = _TMP
os.makedirs(os.path.join(_TMP, "images", "thumbs"), exist_ok=True)

from photon_tasks import TasksWidget, THUMB_DIR, thumbnail_heights
from PyQt6.QtGui import QImage


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


if __name__ == "__main__":
    unittest.main()
