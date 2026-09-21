#!/usr/bin/env python3
"""The shelf's clock: a single sunken field, flush against the bottom of the
panel.

A component of bin/shelf-panel, and a window of its own when run directly.
It replaces the FvwmTaskBar cell that config's TaskbarClockTick used to push
a string into via SendToModule/ChangeButton -- there is no taskbar left to
send to, so this widget keeps its own clock instead of waiting on fvwm for
one.

"%a-%d %I:%M%p" is TaskbarClockTick's own format, carried over unchanged:
"Fri-19 11:33PM".  The well is the same `photon.sunken`/`photon.FIELD`
construction the media widget's title field uses, at the same 4px inset --
see photon_media.py's `_relayout`, where the comment explains why 4 rather
than some other number.  No group header: `panel.items` names this section
`bare`, so the field is the whole of it.

A QTimer, but armed to the next minute boundary rather than ticking every
second and throwing most of the ticks away -- CLAUDE.md's "almost nothing
polls" applies to a display that only ever shows minutes too.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import QRect, QSize, QTimer
from PyQt6.QtGui import QFontMetrics, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

import photon

FORMAT = "%a-%d %I:%M%p"   # TaskbarClockTick's tokens: "Fri-19 11:33PM"

PAD = 4         # the inset the rest of the dock uses -- see photon_media.py
FIELD_H = 19    # a data field's height, measured for the media title field


class ClockWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.FACE)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self.font_clock = photon.font(8)
        self._text = self._now_text()

        self.resize(photon.SHELF_INNER, self.natural_height())
        self.setMinimumSize(80, self.natural_height())
        self._relayout()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._arm()

    def natural_height(self):
        return 2 * PAD + FIELD_H

    def sizeHint(self):
        return QSize(photon.SHELF_INNER, self.natural_height())

    #  -- geometry --

    def _relayout(self):
        self.r_field = QRect(PAD, PAD, max(0, self.width() - 2 * PAD), FIELD_H)

    def resizeEvent(self, event):
        self._relayout()

    #  -- clock --

    @staticmethod
    def _now_text():
        return datetime.now().strftime(FORMAT)

    def _arm(self):
        #  The delay to the next :00, not a 1000ms repeat -- so the widget
        #  wakes up exactly once a minute instead of 60 times for one change.
        now = datetime.now()
        nxt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        self._timer.start(max(0, int((nxt - now).total_seconds() * 1000)))

    def _tick(self):
        self._text = self._now_text()
        self.update(self.r_field)
        self._arm()

    #  -- painting --

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)
        photon.sunken(p, self.r_field, photon.FIELD)
        inner = photon.sunken_interior(self.r_field)
        p.setFont(self.font_clock)
        p.setPen(photon.INK)
        fm = QFontMetrics(self.font_clock)
        baseline = inner.top() + (inner.height() + fm.capHeight()) // 2
        p.drawText(inner.left() + 3, baseline,
                   photon.elide(self._text, self.font_clock, inner.width() - 6))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ShelfClock")
    app.setDesktopFileName("ShelfClock")
    w = ClockWidget()
    w.setWindowTitle("ShelfClock")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
