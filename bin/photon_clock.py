#!/usr/bin/env python3
"""The shelf's clock: the bottom strip of the panel, edge to edge.

A component of bin/shelf-panel, and a window of its own when run directly.
It replaces the FvwmTaskBar cell that config's TaskbarClockTick used to push
a string into via SendToModule/ChangeButton -- there is no taskbar left to
send to, so this widget keeps its own clock instead of waiting on fvwm for
one.

TaskbarClockTick's date and time formats are carried over unchanged, but
placed at opposite edges of the strip: "Fri-19" and "11:33PM".

The reference does *not* put this in a sunken field, which is the mistake
worth naming because every other value on the shelf is in one.  Sampled
down the reference's bottom strip at x=150, y=292..314 is a flat run of
#d9d9d9 with the glyphs straight on it -- the shelf's own face, no bevel, no
#f4f4f4.  The only rule is the etched separator above it at y=290,291.  The
strip is enlarged beyond the reference for readability.  No group header
either; `panel.items` gives this section `nobar`.

A QTimer, but armed to the next minute boundary rather than ticking every
second and throwing most of the ticks away -- AGENTS.md's "almost nothing
polls" applies to a display that only ever shows minutes too.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import QSize, QTimer
from PyQt6.QtGui import QFontMetrics, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

import photon

DATE_FORMAT = "%a %m.%d"
TIME_FORMAT = "%I:%M%p"

CLOCK_PT = 11  # size at STRIP_H and a REF_W-wide strip; scales with width
REF_W = 200
MIN_PT = 8
STRIP_H = 30
PAD_L, PAD_R, GAP = 4, 3, 10


class ClockWidget(QWidget):
    full_width = True  # shelf-panel: no PAD_R, the face runs to the frame

    def __init__(self, parent=None):
        super().__init__(parent)

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.FACE)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self._text = self._now_text()

        self.resize(photon.SHELF_INNER, self.natural_height())
        self.setMinimumSize(80, self.natural_height())

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._arm()

    def _pt_for(self, w):
        """CLOCK_PT scaled by w against the reference width, stepped down
        until time and date fit side by side.  Scaling by the text instead
        would blow a short date format up to fill the strip."""

        def need(pt):
            fm = QFontMetrics(photon.font(pt, fnt="fixed"))
            return sum(fm.horizontalAdvance(t) for t in self._text)

        avail = w - PAD_L - PAD_R - GAP
        pt = round(CLOCK_PT * w / REF_W)
        while pt > MIN_PT and need(pt) > avail:
            pt -= 1
        return max(MIN_PT, pt)

    def natural_height(self, w=None):
        w = photon.SHELF_INNER if w is None else w
        return round(STRIP_H * self._pt_for(w) / CLOCK_PT)

    def sizeHint(self):
        return QSize(photon.SHELF_INNER, self.natural_height())

    #  -- clock --

    @staticmethod
    def _now_text():
        now = datetime.now()
        return now.strftime(DATE_FORMAT), now.strftime(TIME_FORMAT)

    def _arm(self):
        #  The delay to the next :00, not a 1000ms repeat -- so the widget
        #  wakes up exactly once a minute instead of 60 times for one change.
        now = datetime.now()
        nxt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        self._timer.start(max(0, int((nxt - now).total_seconds() * 1000)))

    def _tick(self):
        self._text = self._now_text()
        self.update()
        self._arm()

    #  -- painting --

    def paintEvent(self, event):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, photon.FACE)
        font = photon.font(self._pt_for(r.width()), fnt="fixed")
        p.setFont(font)
        p.setPen(photon.INK)
        fm = QFontMetrics(font)
        date, time = self._text
        avail = r.width() - PAD_L - PAD_R
        time = photon.elide(time, font, avail)
        date = photon.elide(date, font, avail - GAP - fm.horizontalAdvance(time))
        baseline = r.top() + (r.height() + fm.capHeight()) // 2
        p.drawText(r.left() + PAD_L, baseline, time)
        p.drawText(r.right() + 1 - PAD_R - fm.horizontalAdvance(date), baseline, date)


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
