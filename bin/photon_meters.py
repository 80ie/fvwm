#!/usr/bin/env python3
"""System Monitor meters for the QNX Photon shelf.

A component of bin/shelf-panel, and a window of its own when run directly.
Like the Media widget it owns no geometry beyond a size hint and never talks
to fvwm.

conky was doing its job; what it cannot do is draw what the reference has.
`${cpubar}` paints a bar's outline and its fill in one colour, so a per-bar
sunken trough is out of reach, and the reference's fill is itself bevelled in
its own hue inside that trough.  Getting there through conky means drawing
every pixel in a Lua/cairo hook, which is bin/photon.py written a second time
in a second language, free to drift from the first.  So this is Qt, and the
look comes from the same module the Media widget uses.

Three rows, as in the reference: CPU, memory, filesystems.  The filesystem row
carries *two* thin bars rather than one tall one, which is the shape neither
FvwmButtons nor a conky template expresses without regenerating itself.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtCore import QRect, QSize, QTimer
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

import psutil

import photon

#  Two seconds, as conky used.  A meter is the one thing here that genuinely
#  has to sample -- there is no "the CPU changed" signal to subscribe to --
#  but sampling is not the same as repainting: paintEvent only runs when a
#  bar's pixel width actually moves.
INTERVAL_MS = 750 

#  Measured off ~/Desktop/qnx621-1-1.png at x=1000, rows 475..533.
BAR_H = 16            # CPU and MEM: outline, 14 rows of interior, outline
THIN_H = 7            # each of the filesystem row's two bars
GAP = 4               # between rows
THIN_GAP = 1          # between the two thin bars
ICON = 16

#  The reference shows a tan CPU bar and a green memory bar and its
#  filesystem bars happen to be empty, so there is no measured colour for
#  them.  The pager's khaki is the nearest thing in the sampled palette; it
#  is a choice, not a measurement, and it is the one colour on this widget
#  that the screenshot cannot settle.
FILL_DISK = photon.FILL_DISK


def filesystems():
    """The two biggest real filesystems, by total size.

    Two because the reference's disk row has two bars.  Real because a
    machine has a dozen pseudo mounts and none of them mean anything on a
    meter.
    """
    seen, out = set(), []
    for part in psutil.disk_partitions(all=False):
        if not part.device.startswith("/dev/"):
            continue
        if part.mountpoint in seen:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        seen.add(part.mountpoint)
        out.append((part.mountpoint, usage.total))
    out.sort(key=lambda mp_total: mp_total[1], reverse=True)
    return [mp for mp, _ in out[:2]]


class MetersWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, photon.FACE)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self.mounts = filesystems()
        self.cpu = 0.0
        self.mem = 0.0
        self.disks = [0.0] * len(self.mounts)
        self._widths = None       # last painted fill widths, to skip repaints

        #  Primes psutil's CPU counter: the first call always reads 0.
        psutil.cpu_percent(interval=None)

        self.resize(photon.SHELF_INNER, self.natural_height())
        self.setMinimumSize(110, 40)
        self._relayout()

        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self._sample)
        self._timer.start()
        self._sample()

    def sizeHint(self):
        return QSize(photon.SHELF_INNER, self.natural_height())

    def natural_height(self):
        rows = GAP + BAR_H + GAP + BAR_H + GAP
        rows += len(self.mounts) * THIN_H
        rows += max(0, len(self.mounts) - 1) * THIN_GAP
        return rows + GAP

    #  -- geometry --

    def _relayout(self):
        w = self.width()
        pad = 4
        self.r_icons = []
        self.r_bars = []

        bar_x = pad + ICON + 4
        bar_w = max(20, w - bar_x - pad - 1)

        y = GAP
        for name in ("cpu", "mem"):
            self.r_icons.append(QRect(pad, y + (BAR_H - ICON) // 2, ICON, ICON))
            self.r_bars.append([QRect(bar_x, y, bar_w, BAR_H)])
            y += BAR_H + GAP

        #  One icon for the filesystem row, however many bars it has.
        block = len(self.mounts) * THIN_H + max(0, len(self.mounts) - 1) * THIN_GAP
        self.r_icons.append(QRect(pad, y + (block - ICON) // 2, ICON, ICON))
        thin = []
        for i in range(len(self.mounts)):
            thin.append(QRect(bar_x, y + i * (THIN_H + THIN_GAP), bar_w, THIN_H))
        self.r_bars.append(thin)

    def resizeEvent(self, event):
        self._relayout()

    #  -- data --

    def _sample(self):
        self.cpu = psutil.cpu_percent(interval=None)
        self.mem = psutil.virtual_memory().percent
        disks = []
        for mp in self.mounts:
            try:
                disks.append(psutil.disk_usage(mp).percent)
            except OSError:
                disks.append(0.0)
        self.disks = disks

        #  Repaint only when a bar would actually land on a different pixel.
        #  A meter that redraws itself every two seconds regardless is the
        #  habit that made the old widget flicker, even where the toolkit
        #  underneath it is honest about double buffering.
        widths = self._fill_widths()
        if widths != self._widths:
            self._widths = widths
            self.update()

    def _values(self):
        return [[self.cpu], [self.mem], list(self.disks)]

    def _fill_widths(self):
        out = []
        for row, values in zip(self.r_bars, self._values()):
            for r, value in zip(row, values):
                out.append(self._fill_w(r, value))
        return out

    @staticmethod
    def _fill_w(r, value):
        #  The fill lives inside the outline, so the interior is 2px narrower.
        return int(round((r.width() - 2) * max(0.0, min(100.0, value)) / 100.0))

    #  -- painting --

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), photon.FACE)

        names = ("audio-card", "media-flash-memory-stick", "drive-harddisk")
        colours = (photon.FILL_CPU, photon.FILL_MEM, FILL_DISK)

        for icon_r, row, name, colour, values in zip(
                self.r_icons, self.r_bars, names, colours, self._values()):
            #  Haiku's nearest equivalents to Photon's chip, memory module
            #  and disk.  No Photon icon set exists for any toolkit, and
            #  these are the closest installed set in the same flat idiom.
            photon.draw_icon(p, name, icon_r)
            for r, value in zip(row, values):
                photon.trough(p, r)
                width = self._fill_w(r, value)
                if width > 0:
                    photon.bar_fill(p, QRect(r.left() + 1, r.top() + 1,
                                             width, r.height() - 3), colour)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ShelfMeters")
    app.setDesktopFileName("ShelfMeters")
    w = MetersWidget()
    if "--print-height" in sys.argv:
        #  What the SysMon row in shelfdock.items should reserve.  The number
        #  depends on how many filesystems this machine has, so ask rather
        #  than assume when the spec and the widget disagree.
        print(w.natural_height())
        return
    w.setWindowTitle("ShelfMeters")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
