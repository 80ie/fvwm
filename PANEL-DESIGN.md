# Panel design note: why the shelf and taskbar get a new rendering layer

Status: **decided, not yet implemented.** Written 2026-09-20, after the
`fold-in-protos` branch landed the generated shelf and taskbar.

This note records why the QNX Photon panel stops being rendered by fvwm's own
module toolkit, what replaces it, and what was measured rather than assumed.
It exists so the decision is not re-litigated from memory: several of the
constraints below contradict comments written earlier in this repo, and two of
those comments turned out to be wrong.

## The complaint

The shelf and taskbar work, but they are not the screenshot. Three specific
failures, in the order they annoy:

1. The Media widget's track title and volume readout **flash white once a
   second**.
2. The Media widget is ASCII (`<<`, `[]`, `>`, `>>`, `- 50 +`) where the
   original has glyphs, a marquee-scrolled title and a real slider.
3. The System Monitor is three flat grey bars with text labels where the
   original has colour icons and green fills in sunken troughs.

Underneath those is a fourth, structural: collapsing an accordion group kills
and restarts a module across two window aliases with a 150ms swap, and that
constraint is what forbids `Swallow` anywhere in `shelf.items`.

## What is actually wrong

The architecture is sound. FvwmButtons, conky, FvwmPerl and stalonetray are
all doing their jobs. **FvwmScript is the one component that cannot do what is
being asked of it**, and the accordion's kill-and-restart is a self-imposed
constraint that a different FvwmButtons primitive removes.

### The blink is structural, not a config bug

`ChangeTitle` (`modules/FvwmScript/Instructions.c:1213`) issues
`XClearWindow` and *then* `DrawObj` — two separate X requests, so the widget's
background is on screen for however long the server takes between them.
`ItemDraw.c:132` repeats the pattern with `XClearArea`. There is no
double-buffering anywhere in the module: `grep -rn Xdbe` across
`modules/FvwmScript/` returns nothing, and `CheckBox.c`, `HScrollBar.c`,
`TextField.c`, `Menu.c` and `VScrollBar.c` all clear before drawing the same
way. No widget type or flag avoids it.

The 2-second guard in `FvwmScript-ShelfMedia` is **not** at fault and is doing
exactly what its comment claims. `PeriodicTasks` is driven from a `select()`
loop that only runs the block when `delta >= 1000000` microseconds
(`FvwmScript.c:1139`), and `GetTime()` is whole seconds (`Instructions.c:646`),
so `(RemainderOfDiv (GetTime) 2)==0` genuinely halves an accurate one-second
tick.

Guarding `ChangeTitle` on "did the value actually change" hides most flashes.
It does not fix the one that matters — the repaint when the track *does*
change — because the clear-then-draw is the redraw model itself.

### `Icon` is broken on this build, confirmed here

`bin/fvwmscript-icontest` run against the live fvwm3 1.1.2 on this machine:

```
widget 1 (no icon, before) rendered: yes
widget 2 (HAS ICON)        rendered: no
widget 3 (no icon, after)  rendered: no
```

The syntax is correct against the grammar (`script.y:646`, `instr ICON icon`)
and `LoadIcon` uses the same `PImageLoadPixmapFromFile` path as every other
fvwm module. The failure is reproducible and silent, and it cascades: a widget
carrying an icon takes every later widget with it. This is why the transport
controls are ASCII.

### Nothing upstream is coming

The fvwm3 changelogs for 1.1.3 (2025-06-01), 1.1.4 (2025-11-08) and 1.1.5
(2026-06-27, current) contain **no** FvwmScript entries touching `Icon`,
`ItemDraw`, double-buffering or widget messages. 1.1.5's breaking change
removes FvwmConsole in favour of FvwmPrompt. That corner of fvwm is being
retired, not repaired. Waiting is not a strategy.

## Two corrections to this repo's own comments

Both of these are wrong in files currently checked in, and both cost us
something real.

**`HScrollBar` works. The slider was always reachable.** The header comment in
`FvwmScript-ShelfMedia` says it "does not emit SingleClic when moved, and
numeric case labels (`1 :`) do not parse, so no message is left to catch," and
that is why the volume control is a `-`/`+` pair. In fact
`EvtMouseHScrollBar` calls `SendMsg(xobj, SingleClic)` on every value change
during a drag (`HScrollBar.c:171`). The trap is that `SingleClic` is
`#define SingleClic -1` (`Widgets/Tools.h:30`) — it is *not* message id `1`, so
a `1 :` case label can never match anything a scrollbar sends. Verified here
with a test script using a `SingleClic :` label and an xdotool-driven drag: the
thumb tracked to 100 and the handler fired.

This does not change the decision — an FvwmScript slider would still flash and
still have no icons — but the comment should be corrected rather than left to
mislead the next reader.

**`FvwmButtons` has a `Panel` primitive we never tried.** `bin/mk-shelf`'s
kill-and-regenerate is correct *as designed*: `SendToModule ChangeButton`
reaches Title, ActiveTitle, PressTitle, Colorset and Icon and nothing else —
no size, no visibility — and `Container` is a layout-time construct, so there
is genuinely no way to hide or resize a button at runtime. But a `Panel`
button swallows a persistent separate window and slides it in and out with
animation (`FvwmButtons.html`, "CREATING PANELS"). Because nothing is
destroyed on toggle, the `UseOld` stranding problem that forbids `Swallow` in
`shelf.items` does not arise at all.

The stranding analysis in `shelf.items` is itself correct: `UseOld` matches on
window name/class against whatever is on the display and has no concept of
which alias currently owns a reparented child. The workaround is right for the
design; the design had an alternative.

## What the reference actually demands

Measured from `~/Desktop/qnx621-1-1.png` (1024x768, shelf occupies x=890..1024,
so its 134px inner width is close enough to our 152 that pixel sizes transfer
nearly 1:1).

**The colours in `config` are already right** — colorsets 30-37 sample
`#d9d9d9`, `#a7a7a7`, `#ffffff` and `#c3c7b1` accurately. The problem is form,
not palette, with one important exception.

**Photon uses two bevel vocabularies and we encode one.** Raised chrome gets
the soft `#a7a7a7` shadow we have. Sunken troughs and data fields get a **hard
`#4b4b4b` outline**. QNX's own PhAB widget reference corroborates this: Photon
widgets carry both `Pt_ARG_DARK_BEVEL_COLOR` (outer edge) and
`Pt_ARG_DARK_FILL_COLOR` (inner transition), a two-tone bevel-to-fill, not a
highlight/shadow pair. Colorset 33 ("sunken well") uses `sh #a7a7a7`, which is
why the meters, the clock field and the pager all read as mushy.

Colours measured that we do not currently have:

| Element | Colour |
|---|---|
| Sunken trough / data field outline | `#4b4b4b` |
| Meter trough, unfilled | `#bcbcbc` |
| CPU meter fill | `#d6cdba` |
| MEM meter fill | `#b5c4b0` |
| Title field interior (CD Player) | `#f4f4f4` |
| Slider groove | `#8c8c8c` |
| Header toggle cell face | `#c7c7c7` (header face is `#dbdbdb`) |
| Header toggle glyph | `#606060` |
| Widget-section face | `#d8d8d8` |
| Pager mini window | `#bec1c3` |
| Pager focused window | `#b4b4ff` |

Geometry, x measured from the shelf's inner left edge:

- **Accordion rows**: 25px pitch (23px face + 2px gap). Matches `shelf.items`.
- **Group header**: ~20px, with the `-`/`+` in a *separate cell* at x=6..20 in
  a distinct shade, divided from the label. We draw a plain hyphen inline.
- **Meter row**: ~19px pitch. Icon at x=6..25 (20px square, colour, raised),
  bar from x=30 to the right margin, 12-13px tall. The DSK row carries **two**
  thin bars (~4-6px each) in one row — a variable number of bars per row,
  which FvwmButtons cannot express without regeneration.
- **CD title field**: 16px interior, sunken, near-white, marquee-scrolled (the
  reference frame caught it mid-wrap: `er ... CD Playe`).
- **Transport**: 4 buttons, ~22px wide on a 23px pitch, ~20px tall, glyphs in
  black.
- **Volume**: speaker icon at x=6..23, groove x=32..124 in `#8c8c8c` with tick
  marks below, ~8px raised thumb. This is a *separate sub-section* of the CD
  Player group, divided by a rule — groups have internal dividers.
- **World View**: 3x3, ~28px cells, white 1px grid, current page outlined in
  **black**, in a sunken trough.

That last one is its own small wall: `FvwmPager` styles the active page by
background colour and has no border option, which is why `config` settles for a
lighter khaki instead of the reference's outline.

## Options considered

**A — Surgical native fix.** conky's Lua/cairo hook for real troughs; fix the
slider case label; `Panel` for the accordion; add a `#4b4b4b` well colorset.
Cheap, and the config stays the single source of truth. Rejected as
*sufficient*, kept as *partly worth doing*: it cannot deliver icons (Icon is
broken), flicker-free text, marquee or hover, because those are all FvwmScript.

**B — Keep fvwm chrome, write the widgets.** One small program per broken
widget, swallowed into `shelfdock.items` exactly as conky already is. The dock
is `--static`, so its swallows are stable by construction.

**C — One panel process.** A single program draws shelf and taskbar; the pager
is drawn from EWMH rather than swallowed; the window list comes from FvwmMFL's
event socket; fvwm keeps `EwmhBaseStruts` and a `Style` rule. Removes
`mk-shelf`, `mk-taskbar`, the spec files, the alias swap and every `Swallow`.

**Rejected outright: adopting a third-party panel.** No candidate clears the
bar. The ones with real theming cannot embed foreign windows
(`xfce4-panel`'s embed plugin is out-of-Debian and unmaintained; lxqt-panel has
none); the one with real custom-widget power (eww) has no tray, no window list,
no pager, and foreign-window embedding is an open unimplemented issue. polybar
has no vertical mode at all (requested 2016, still open). yabar, cairo-dock,
docky and AWN are dead. No maintained QNX Photon skin exists for any toolkit —
the bevels are hand-built whatever we choose.

## Decision

**Do B now. Treat C as the deliberate end state.**

Every widget written for B is a drop-in component of C, so none of it is
throwaway. B fixes the things that are ugly; C fixes the things that are
fragile; doing B first means the media player and meters look right long before
the architecture migration has to be finished, and the migration stays
optional.

The move that matters is the same in both: **stop asking fvwm's module toolkit
to render, and let fvwm do what it is good at** — window management, struts,
layers, launching.

### Toolkit

PyQt6, because it is already installed and needs nothing new:

| Piece | Status |
|---|---|
| `python3-pyqt6` 6.9.0 | installed, with **QtDBus** |
| `python-xlib` 0.33 | installed |
| `dbus-python`, `psutil` 7.0.0 | installed |
| C/C++ compiler | **absent** — Qt6/C++ would need `build-essential` first |

Qt6 dropped the Motif/CDE styles entirely, so bevels are drawn in
`paintEvent()` rather than fought through `QStyle`. For a small fixed
vocabulary — button face, sunken well, trough, raised thumb — that is the
easier path anyway, and it is the only one that gives exact 1px strokes.

### What stops polling

The blink's real cause is the poll, and both polls have event-driven
replacements:

- **MPRIS**: subscribe to `org.freedesktop.DBus.Properties.PropertiesChanged`
  with `arg0='org.mpris.MediaPlayer2.Player'` for `Metadata` and
  `PlaybackStatus`. Note the spec explicitly excludes `Position` from change
  notification — track it locally between `Seeked` signals.
- **Volume**: `pipewire-pulse` registers `org.pulseaudio.Server` on the session
  bus but implements **none** of the PulseAudio D-Bus extension —
  introspecting `/org/pulseaudio/core1` returns an empty node. The working path
  is libpulse's native `pa_context_subscribe()`, or `pulsectl` from Python.
  `pactl subscribe` confirms the mechanism is live here.

## Verified, so it is not re-litigated

Everything below was checked against source or run on this machine, not taken
from documentation prose.

- **Qt can host foreign X11 windows.** A real `FvwmPager` module was reparented
  into a PyQt6 `createWindowContainer` and rendered live inside it
  (`Map State: IsViewable`, position tracking the container). Also confirmed
  with `xclock`. Caveat: without an XEmbed handshake, focus/activation are lost
  and the child's own resize requests are not honoured (container drives child,
  not the reverse) — acceptable for a pager or meter strip, which need clicks
  and repaints, not keyboard focus. **Click-through to an embedded pager is
  untested**; it is moot under C, where the pager is drawn rather than swallowed.
- **`_NET_DESKTOP_VIEWPORT` is bidirectional in fvwm3.** It is broadcast from
  `virtual_scr.Vx/Vy` (`ewmh.c:592`) *and* accepted as an incoming
  ClientMessage that calls `MoveViewport()` (`ewmh_events.c:115`). A panel can
  both read and set the page without shelling out to `FvwmCommand`. This is
  what makes drawing the World View natively viable, and makes swallowing
  `FvwmPager` optional rather than required.
- **`_NET_WM_STRUT_PARTIAL` is not implemented in fvwm3 1.1.2.**
  `ewmh_WMStrut()` (`ewmh_events.c:1554`) reads only the legacy four-value
  `_NET_WM_STRUT`, and `ewmh.c`'s own header TODO lists PARTIAL as outstanding.
  A live test here set both properties on a dock window and `_NET_WORKAREA` did
  not change; that test was not clean on property-vs-map ordering, so treat the
  legacy path as *unconfirmed* rather than broken. **It is moot either way**:
  `config:536` already reserves the edge with `EwmhBaseStruts 0 160 0 30`, which
  works unchanged for any panel program. It would only matter for a panel that
  resizes itself at runtime.
- **conky can draw the troughs.** `conky -v` here reports Lua bindings for
  Cairo, Imlib2 and RSVG, and XDBE. `lua_draw_hook_post` gets the full Cairo C
  API, so a per-bar sunken bevel plus a colour fill is roughly 60-100 lines of
  Lua over a `{icon, value, y}` table, reading values through
  `conky_parse("${cpu}")` rather than polling separately.
- **FvwmPerl is genuinely event-driven.** `FVWM::Tracker::Scheduler` implements
  timers by having fvwm send `Schedule <ms> SendToModule ...` back to the
  module, so the timer lives in fvwm's event loop, not a Perl `select()`.
  Handlers must return fast — fvwm kills a module after `ModuleTimeout` — so
  anything slow needs `detach()`.
- **FvwmMFL is a real event socket.** JSON over a unix socket at
  `$TMPDIR/fvwmmfl/fvwm_mfl_$DISPLAY.sock`, with subscribable `new_window`,
  `map`, `configure_window`, `destroy_window`, `new_page`, `new_desk`,
  `focus_change`, `restack` and more. Good for an external window list. It
  carries **nothing** about MPRIS or volume, so it does not help the Media
  widget.

## Open questions

- Click-through to an embedded foreign window (only matters if we swallow
  rather than draw the pager).
- Whether fullscreen windows rise above a dock-type panel's layer — no coupling
  found between `EWMH_fullscreen()` and layer assignment, so this is governed by
  our own `Style`/`Layer` rules and needs a live test.
- RandR/multi-monitor strut behaviour, untested (single head here).
- `AGENTS.md` has drifted — it still describes 18 colorsets, a 4x2 page layout
  and `FvwmScript-DateTime` as a live widget. `CLAUDE.md` is current. Worth
  reconciling, separately from this work.
