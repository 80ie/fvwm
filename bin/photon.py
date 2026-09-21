"""The QNX Photon look, as a handful of painters.

Shared by every widget that gets swallowed into the shelf's dock, so that the
bevels agree with each other and with the fvwm colorsets rather than drifting
apart.  Nothing in here knows about fvwm, MPRIS or PipeWire: data in, pixels
out, which is the property that lets these widgets be reused unchanged if the
panel ever becomes one process (see PANEL-DESIGN.md, option C).

Two things are deliberate:

  - Bevels are drawn here rather than through QStyle or a stylesheet.  Qt6
    dropped the Motif/CDE styles, and QSS is documented to be imprecise about
    exact strokes; every line Photon draws is exactly one pixel, so we draw
    them ourselves.
  - There are *two* bevel vocabularies, not one.  Raised chrome gets the soft
    #a7a7a7 shadow.  Sunken troughs and data fields get a hard #4b4b4b
    outline.  Using the soft one for both is what makes a Photon imitation
    read as mushy, and it is the single most visible error in the FvwmScript
    widgets these replace.
"""

import os

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient,
                         QPainter, QPixmap)

from photon_palette import load_palette

_PALETTE = load_palette()


def colour(name):
    return QColor(_PALETTE[name])


FACE         = colour("FACE")
FACE_HI      = colour("FACE_HI")
HEADER       = colour("HEADER")
GUTTER       = colour("GUTTER")
FRAME_MID    = colour("FRAME_MID")
WELL         = colour("WELL")
FACE_ALT     = colour("FACE_ALT")
BTN_HI       = colour("BTN_HI")
BTN_LO       = colour("BTN_LO")
WELL_SH      = colour("WELL_SH")
WELL_LIP     = colour("WELL_LIP")
HI           = colour("HI")
SH           = colour("SH")
DARK         = colour("DARK")
HEADER_CELL  = colour("HEADER_CELL")
HEADER_GLYPH = colour("HEADER_GLYPH")
FIELD        = colour("FIELD")
TROUGH       = colour("TROUGH")
TROUGH_SH    = colour("TROUGH_SH")
GROOVE       = colour("GROOVE")
GROOVE_MID   = colour("GROOVE_MID")
GROOVE_HI    = colour("GROOVE_HI")
GROOVE_LIP   = colour("GROOVE_LIP")
THUMB_HI     = colour("THUMB_HI")
THUMB_LO     = colour("THUMB_LO")
TICK_HI      = colour("TICK_HI")
TICK_LO      = colour("TICK_LO")
FILL_CPU     = colour("FILL_CPU")
FILL_MEM     = colour("FILL_MEM")
FILL_DISK    = colour("FILL_DISK")
INK          = colour("INK")
INK_OFF      = colour("INK_OFF")
PAGER_SECTION = colour("PAGER_SECTION")
PAGER_DESK    = colour("PAGER_DESK")
PAGER_DESK_HI = colour("PAGER_DESK_HI")
PAGER_WIN     = colour("PAGER_WIN")
PAGER_WIN_EDGE = colour("PAGER_WIN_EDGE")
PAGER_FOCUS    = colour("PAGER_FOCUS")
PAGER_FOCUS_EDGE = colour("PAGER_FOCUS_EDGE")
PAGER_GRID       = colour("PAGER_GRID")

#  The shelf's usable width inside its own frame.  A starting value only: the
#  panel is resizable now, so nothing should assume it.
SHELF_INNER = 152

#  Geometry the reference fixes, and the panel reads rather than invents.
FRAME_W = 7           # the shelf's left edge, the double bevel below
HEADER_H = 20         # a group header, its divider included
TOGGLE_W = 15         # the -/+ cell at the head of a group header
ROW_H = 25            # a launcher row, its divider included
GUTTER_W = 28         # the icon column of a launcher row


def font(size=8, bold=False):
    """A shelf-sized font.  Point sizes, because the display is 96dpi and
    Photon's labels are small enough that hinting at fixed pixel sizes costs
    more than it buys."""
    f = QFont("Sans", size)
    f.setBold(bold)
    return f


def elide(text, fnt, width):
    fm = QFontMetrics(fnt)
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, width)


#  ---- Bevels ---------------------------------------------------------------
#
#  Every one of these takes the rect it should *occupy*, inclusive of its own
#  bevel, so callers can lay out in whole rectangles without bookkeeping.

def raised(p: QPainter, r: QRect, face=None):
    """Raised chrome: a button, a thumb, a section face.  Soft shadow."""
    if face is not None:
        p.fillRect(r, face)
    right, bottom = r.right(), r.bottom()
    p.setPen(HI)
    p.drawLine(r.left(), r.top(), right, r.top())
    p.drawLine(r.left(), r.top(), r.left(), bottom)
    p.setPen(SH)
    p.drawLine(r.left(), bottom, right, bottom)
    p.drawLine(right, r.top(), right, bottom)


def sunken(p: QPainter, r: QRect, fill=None):
    """A well: data field, meter trough.

    The hard one, measured off the reference's CD title field at x=900,
    y=560..579.  A full #4b4b4b outline; a #c0c0c0 inner shadow along the top
    and left, which is the two-tone bevel-to-fill Photon's PhAB reference
    calls DARK_BEVEL into DARK_FILL; the interior; and a #dddddd lip along
    the *outer* bottom and right, so the last row and column of `r` are the
    lip rather than the field.

    The soft highlight/shadow pair cannot fake this, which is the single most
    visible error in the FvwmScript widgets these replace.
    """
    outline = QRect(r.left(), r.top(), r.width() - 1, r.height() - 1)
    if fill is not None:
        p.fillRect(outline.adjusted(1, 1, 0, 0), fill)
    p.setPen(DARK)
    p.drawRect(outline)
    p.setPen(WELL_SH)
    p.drawLine(outline.left() + 1, outline.top() + 1,
               outline.right() - 1, outline.top() + 1)
    p.drawLine(outline.left() + 1, outline.top() + 1,
               outline.left() + 1, outline.bottom() - 1)
    p.setPen(WELL_LIP)
    p.drawLine(r.left() + 1, r.bottom(), r.right(), r.bottom())
    p.drawLine(r.right(), r.top() + 1, r.right(), r.bottom())


def button(p: QPainter, r: QRect, down=False):
    """A Photon push button.

    Not the soft bevel either.  Measured at x=920, y=582..596: a hard
    #4b4b4b outline, a white inner top and left, a #b0b0b0 inner bottom and
    right, and a face that is a vertical #ebebeb to #b0b0b0 gradient rather
    than a flat fill.  The slider thumb is the same construction, which is
    why both live here rather than in the widget that draws them.

    Held down, the light comes from the other side.
    """
    inner = r.adjusted(1, 1, -1, -1)
    g = QLinearGradient(0, inner.top(), 0, inner.bottom())
    g.setColorAt(0.0, BTN_LO if down else BTN_HI)
    g.setColorAt(1.0, BTN_HI if down else BTN_LO)
    p.fillRect(inner, g)
    p.setPen(DARK)
    p.drawRect(QRect(r.left(), r.top(), r.width() - 1, r.height() - 1))
    p.setPen(BTN_LO if down else HI)
    p.drawLine(inner.left(), inner.top(), inner.right(), inner.top())
    p.drawLine(inner.left(), inner.top(), inner.left(), inner.bottom())
    p.setPen(HI if down else BTN_LO)
    p.drawLine(inner.left(), inner.bottom(), inner.right(), inner.bottom())
    p.drawLine(inner.right(), inner.top(), inner.right(), inner.bottom())


def shade(colour: QColor, delta: int) -> QColor:
    """A colour lightened or darkened by `delta` on every channel.

    Photon bevels a coloured block by shifting the fill rather than by
    blending toward white and black, and the shift is exactly 40: the
    reference's CPU fill #d6cdba carries #fef5e2 above it and #aea592 below,
    and its MEM fill #b5c4b0 carries #ddecd8 and #8d9c88.  Same rule, two
    hues, so it is the rule and not a pair of measurements.
    """
    return QColor(max(0, min(255, colour.red() + delta)),
                  max(0, min(255, colour.green() + delta)),
                  max(0, min(255, colour.blue() + delta)))


def trough(p: QPainter, r: QRect):
    """A meter's trough: #4b4b4b outline, #8d8d8d inner shadow along the top
    and left, #bcbcbc interior.  Measured at x=1000, rows 499..514."""
    outline = QRect(r.left(), r.top(), r.width() - 1, r.height() - 1)
    p.fillRect(outline.adjusted(1, 1, 0, 0), TROUGH)
    p.setPen(DARK)
    p.drawRect(outline)
    p.setPen(TROUGH_SH)
    p.drawLine(outline.left() + 1, outline.top() + 1,
               outline.right() - 1, outline.top() + 1)
    p.drawLine(outline.left() + 1, outline.top() + 1,
               outline.left() + 1, outline.bottom() - 1)


def bar_fill(p: QPainter, r: QRect, colour: QColor):
    """The filled part of a meter, drawn *inside* a trough.

    Not a flat block: the reference's fill is bevelled in its own hue, a
    lighter row and column above and left and a darker one below and right.
    `r` is the whole filled area including that bevel.
    """
    if r.width() <= 0 or r.height() <= 0:
        return
    p.fillRect(r, colour)
    p.setPen(shade(colour, 40))
    p.drawLine(r.left(), r.top(), r.right(), r.top())
    p.drawLine(r.left(), r.top(), r.left(), r.bottom())
    p.setPen(shade(colour, -40))
    p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
    p.drawLine(r.right(), r.top(), r.right(), r.bottom())


def frame(p: QPainter, r: QRect, edge="left"):
    """The shelf's inner edge: two nested bevels, seven pixels wide.

    Sampled at x=889..895 and identical at every height checked (y=2, 8, 16,
    18, 19, 22, 40, 45, 300, 520, 590, 700):

        #4b4b4b  outer dark      #a6a6a6  inner shadow
        #ffffff  outer light     #4b4b4b  inner dark
        #d8d8d8  channel         #ffffff  inner light
        #d8d8d8  channel

    FvwmButtons' `Frame N` draws *one* bevel N pixels wide out of a
    colorset's hi/sh and cannot nest, which is why this could not be had
    while the shelf was a module.  The reference carries it on the left; a
    left-docked shelf mirrors it onto the right.
    """
    rows = (DARK, HI, FACE_ALT, FACE_ALT, FRAME_MID, DARK, HI)
    if edge == "right":
        rows = reversed(rows)
    for i, colour in enumerate(rows):
        p.setPen(colour)
        p.drawLine(r.left() + i, r.top(), r.left() + i, r.bottom())


def toggle_glyph(p: QPainter, r: QRect, collapsed):
    """The `-` or `+` in a group header's own cell.

    Both are 6x2 bars: the minus alone, the plus crossed with a 2x6.  Read
    straight off the reference at x=896..911, rows 1..17 (Applications,
    expanded) and 220..236 (Utilities, collapsed).
    """
    cx, cy = r.center().x(), r.center().y()
    p.fillRect(QRect(cx - 2, cy, 6, 2), HEADER_GLYPH)
    if collapsed:
        p.fillRect(QRect(cx, cy - 2, 2, 6), HEADER_GLYPH)


def group_header(p: QPainter, r: QRect, label, collapsed, fnt):
    """A collapsible group's header: its own `#c7c7c7` toggle cell, the label
    on a `#dbdbdb` face, and an etched divider along the bottom.

    The toggle living in a *separate cell* rather than as a hyphen inline is
    the visible difference the FvwmButtons version could not express -- a
    Title cell is one colorset all the way across.
    """
    cell = QRect(r.left(), r.top(), TOGGLE_W, r.height() - 2)
    face = QRect(r.left() + TOGGLE_W, r.top(),
                 r.width() - TOGGLE_W, r.height() - 2)
    p.fillRect(cell, HEADER_CELL)
    p.fillRect(face, HEADER)
    toggle_glyph(p, cell, collapsed)

    p.setFont(fnt)
    p.setPen(INK)
    fm = QFontMetrics(fnt)
    baseline = face.top() + (face.height() + fm.capHeight()) // 2
    p.drawText(face.left() + 5, baseline,
               elide(label, fnt, face.width() - 8))

    divider(p, r.bottom() - 1, r.left(), r.right())


def divider(p: QPainter, y, x0, x1):
    """The rule Photon puts between a group's sub-sections.  Two lines, etched
    rather than raised."""
    p.setPen(SH)
    p.drawLine(x0, y, x1, y)
    p.setPen(HI)
    p.drawLine(x0, y + 1, x1, y + 1)


def groove(p: QPainter, r: QRect):
    """A slider's groove.

    Not a flat trough.  Sampled down a column of the reference at x=940 the
    five rows are #cccccc #acacac #8c8c8c #4b4b4b #ebebeb: a fill that darkens
    downward into the hard bevel, with a white lip under it.  That is the
    Pt_ARG_DARK_FILL_COLOR to Pt_ARG_DARK_BEVEL_COLOR transition, and drawing
    it as a plain sunken rect is what makes an imitation look flat.
    """
    rows = [GROOVE_HI, GROOVE_MID, GROOVE, DARK, GROOVE_LIP]
    for i, colour in enumerate(rows):
        y = r.top() + i
        if y > r.bottom():
            break
        p.setPen(colour)
        p.drawLine(r.left(), y, r.right(), y)


def thumb(p: QPainter, r: QRect):
    """A slider's thumb: hard outline over a vertical #f0f0f0 to #c7c7c7
    gradient.  Measured the same way as the groove; Photon's thumbs are lit
    from the top rather than bevelled on four sides."""
    g = QLinearGradient(0, r.top() + 1, 0, r.bottom() - 1)
    g.setColorAt(0.0, THUMB_HI)
    g.setColorAt(1.0, THUMB_LO)
    p.fillRect(r.adjusted(1, 1, -1, -1), g)
    p.setPen(DARK)
    p.drawRect(QRect(r.left(), r.top(), r.width() - 1, r.height() - 1))


def tick(p: QPainter, x, y):
    """One mark of a scale: two pixels wide, two tall, light then dark."""
    p.setPen(TICK_HI)
    p.drawLine(x, y, x, y + 1)
    p.setPen(TICK_LO)
    p.drawLine(x + 1, y, x + 1, y + 1)


def x_events(dpy):
    """Every event readable on `dpy` right now, drained until it is empty.

    `pending_events()` reports only what Xlib has already parsed, so one pass
    over it can leave events sitting in the buffer -- and a QSocketNotifier
    fires on *fd* readability, so nothing ever wakes us to collect them.

    fvwm updating `_NET_CLIENT_LIST_STACKING` and `_NET_ACTIVE_WINDOW` for
    the same raise arrives as one readable fd and two events.  Draining once
    took the stacking change and stranded the focus change until some
    unrelated event happened along, which left the window list believing a
    window it had just raised was not focused -- and so its click toggle
    raised again instead of minimising.  Caller iterates; this yields.
    """
    while True:
        count = dpy.pending_events()
        if not count:
            return
        for _ in range(count):
            yield dpy.next_event()


def sunken_interior(r: QRect) -> QRect:
    """The part of a sunken rect that is safe to draw into: inside the
    outline, inside the inner shadow, and clear of the outer lip."""
    return QRect(r.left() + 2, r.top() + 2, r.width() - 4, r.height() - 4)


#  ---- Icons ----------------------------------------------------------------
#
#  From the Haiku icon theme, which is the closest thing installed here to
#  Photon's own set: the same flat-with-a-soft-drop-shadow idiom at the same
#  small sizes.  Looked up by hand rather than through QIcon.fromTheme so the
#  result does not depend on which theme the session happens to have set.

_THEME_DIRS = [
    os.path.expanduser("~/.local/share/icons/Haiku"),
    os.path.expanduser("~/.icons/Haiku"),
    "/usr/share/icons/Haiku",
]
_SECTIONS = ("status", "devices", "apps", "actions", "categories", "places")
_SIZES = (16, 24, 32, 48, 64, 128)

_cache = {}


def icon(name, size):
    """`name` without extension, scaled to `size` square.  Returns None if the
    theme is missing rather than raising -- a widget with a hole in it is more
    useful than one that will not start."""
    key = (name, size)
    if key in _cache:
        return _cache[key]

    #  Prefer the smallest stocked size that is at least as big as asked for,
    #  so we scale down (which stays crisp) rather than up.
    order = [s for s in _SIZES if s >= size] + [s for s in reversed(_SIZES) if s < size]
    path = None
    for root in _THEME_DIRS:
        for s in order:
            for section in _SECTIONS:
                cand = os.path.join(root, "%dx%d" % (s, s), section, name + ".png")
                if os.path.exists(cand):
                    path = cand
                    break
            if path:
                break
        if path:
            break

    pm = None
    if path:
        pm = QPixmap(path)
        if pm.isNull():
            pm = None
        elif pm.width() != size or pm.height() != size:
            pm = pm.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    _cache[key] = pm
    return pm


def draw_icon(p: QPainter, name, r: QRect, enabled=True):
    """Centre a themed icon in `r`.  A disabled icon is drawn faint rather
    than removed, so the row does not change shape."""
    pm = icon(name, min(r.width(), r.height()))
    if pm is None:
        return False
    x = r.left() + (r.width() - pm.width()) // 2
    y = r.top() + (r.height() - pm.height()) // 2
    if not enabled:
        p.save()
        p.setOpacity(0.4)
        p.drawPixmap(x, y, pm)
        p.restore()
    else:
        p.drawPixmap(x, y, pm)
    return True
