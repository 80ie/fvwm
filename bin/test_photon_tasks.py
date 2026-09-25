import unittest

from photon_tasks import thumbnail_heights
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


if __name__ == "__main__":
    unittest.main()
