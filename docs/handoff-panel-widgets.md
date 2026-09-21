# Handoff: build the shelf widgets as standalone programs

Read `PANEL-DESIGN.md` at the repo root first — it has the decision, the
evidence and the measured palette. This file is the working plan for the first
phase of it: the design note says *why*, this says *what to build*. Both are
tracked. (`doc/`, singular, is the vendored upstream fvwm documentation and
stays ignored; `docs/`, plural, is ours.)

## Scope of this phase

Option B from the design note: **keep the fvwm chrome, replace the widgets that
FvwmScript and conky cannot draw.** Each widget is a standalone program
swallowed into `shelfdock.items` exactly the way conky already is. The dock is
rendered with `mk-shelf --static`, so its swallows are stable by construction —
this is the one place in the shelf where `Swallow` is safe.

Out of scope for now: the accordion, the taskbar, the pager, `mk-shelf`,
`mk-taskbar`. Those belong to Option C and are only touched if something here
forces it.

Every widget written here should be a component that Option C can host
unchanged. Practically that means: **no widget owns its own top-level window
geometry beyond a size hint, and no widget talks to fvwm directly.** Data in,
pixels out.

## Toolkit

PyQt6 6.9.0, already installed, with QtDBus. Also present: `python-xlib` 0.33,
`dbus-python`, `psutil` 7.0.0. There is **no C compiler on this box** — if
anything needs one, stop and say so rather than `apt install`ing silently.

Bevels are drawn in `paintEvent()` with `QPainter`, not `QStyle` and not QSS.
Qt6 dropped the Motif/CDE styles, and QSS is documented to be imprecise with
exact strokes. We need exact 1px lines.

## Shared foundation: build this first

A single `bin/photon.py` (or `lib/photon/`) holding the look, imported by every
widget. Getting this right once is most of the work.

### The two bevel vocabularies

This is the thing the current config gets wrong. Photon has **two**, and using
the soft one everywhere is why the meters and clock read as mushy.

```
raised chrome   → highlight #ffffff top/left,  shadow #a7a7a7 bottom/right
sunken well     → hard outline #4b4b4b, with #ffffff on the outer bottom/right
```

QNX's PhAB reference calls these `Pt_ARG_DARK_BEVEL_COLOR` (outer edge) and
`Pt_ARG_DARK_FILL_COLOR` (inner transition) — a two-tone bevel-to-fill, not a
highlight/shadow pair. Troughs and data fields get the hard one; buttons and
section faces get the soft one.

### Palette

Measured from `~/Desktop/qnx621-1-1.png`. The ones already in `config` as
colorsets 30-37 are correct and should be kept in step — do not fork the
palette, mirror it.

| Token | Value | Use |
|---|---|---|
| `face` | `#d9d9d9` | shelf and button face |
| `face_alt` | `#d8d8d8` | widget-section face |
| `hi` | `#ffffff` | raised highlight |
| `sh` | `#a7a7a7` | raised shadow (soft) |
| `dark` | `#4b4b4b` | sunken outline (hard) |
| `header` | `#dbdbdb` | group header face |
| `header_cell` | `#c7c7c7` | the `-`/`+` cell, a distinct shade |
| `header_glyph` | `#606060` | the `-`/`+` mark |
| `field` | `#f4f4f4` | data field interior |
| `trough` | `#bcbcbc` | meter trough, unfilled |
| `groove` | `#8c8c8c` | slider groove |
| `fill_cpu` | `#d6cdba` | CPU meter fill |
| `fill_mem` | `#b5c4b0` | MEM meter fill |

### Geometry

All x measured from the shelf's inner left edge. The reference shelf is 134px
inner against our 152, so sizes transfer nearly 1:1 and the extra 18px goes to
the bars and fields, not the icons.

- Accordion row pitch 25px (23px face + 2px gap) — already correct in
  `shelf.items`, listed for reference.
- Group header ~20px. The `-`/`+` lives in its **own cell** at x=6..20 in
  `header_cell`, divided from the label. We currently draw a bare hyphen inline;
  that is a visible difference.
- Groups have **internal dividers** — the volume row is its own sub-section of
  the CD Player group, separated by a rule.

## Task 1 — Media widget

Replaces `FvwmScript-ShelfMedia` and `bin/shelf-media`. This is first because
it is where both the blink and the ugliness live, and it is the cleanest single
swap.

### Layout, 152px wide

```
┌──────────────────────────────────────┐
│  title field, sunken, #f4f4f4        │  16px interior + bevel ≈ 20px
├──────────────────────────────────────┤
│   [<<]  [■]  [▶]  [>>]               │  4 buttons, 22px wide / 23px pitch,
│                                      │  ≈20px tall, glyphs in black
├──────────────────────────────────────┤  ← internal divider rule
│  (spk)  ├────────●──────────┤        │  groove #8c8c8c x=32..124,
│                                      │  ~8px raised thumb, ticks below
└──────────────────────────────────────┘
```

Height: budget ~80px rather than the current 70 once the divider and the
volume sub-section are in. `shelfdock.items` reserves the row height and
`mk-shelf --height auto` sizes the dock window from the rows, so growing this
costs one number in the spec and nothing else — but keep the spec number and
the widget's own size hint in step, because FvwmButtons resizes a swallowed
window to its cell and a mismatch clips rather than reflows.

### Behaviour

- **Title marquees.** The reference caught it mid-wrap (`er ... CD Playe`), so
  it is a continuous wrap-around scroll with a ` ... ` separator, not a
  ping-pong. Scroll on a `QTimer`; do not scroll when the text fits.
- **Transport glyphs are drawn, not text.** `QPainter` polygons for the
  triangles and a rect for stop. Do not use a font's glyphs — sizing and
  baseline will fight you at 20px, and this is the exact thing that made the
  current widget ASCII.
- **Volume is a real slider**, draggable, with tick marks under the groove.

### Data, event-driven — this is what kills the blink

Do **not** poll. The blink is a repaint-on-poll artifact; removing the poll
removes the class of bug, not just this instance.

- **MPRIS** over QtDBus: enumerate via `ListNames` filtered on
  `org.mpris.MediaPlayer2.`, then subscribe to
  `org.freedesktop.DBus.Properties.PropertiesChanged` on
  `/org/mpris/MediaPlayer2` with `arg0='org.mpris.MediaPlayer2.Player'`.
  `Metadata` and `PlaybackStatus` are change-notified. `Position` is
  **explicitly excluded** by the MPRIS spec — derive it locally from `Rate`
  between `Seeked` signals if a progress indicator is ever wanted.
- **Volume**: libpulse's `pa_context_subscribe()` via `pulsectl`, against
  `pipewire-pulse`. Do **not** reach for the PulseAudio D-Bus extension —
  `pipewire-pulse` registers `org.pulseaudio.Server` on the bus but implements
  none of it (`/org/pulseaudio/core1` introspects to an empty node, checked).
  Do not shell out to `wpctl` on a timer; that is the current design and it is
  the bug.
- Handle "no player" as a state, not an error string. Transport buttons should
  disable rather than vanish.

### Integration

Swallow it from the Media group in `shelfdock.items`, same shape as the conky
row:

```
80   Swallow(NoClose,UseOld) ShelfMedia \
     'Exec exec $[FVWM_USERDIR]/bin/shelf-media-widget', \
     Frame 0, Colorset $[infostore.cs_shelf]
```

Two things the swallow depends on: the window's title must be exactly
`ShelfMedia` (that is the hangon name), and it must be an ordinary
`own_window_type normal`-equivalent top level — a `Qt.WindowType.Dock` or
frameless-tool window may not be reparentable the same way. Set the title
before `show()`.

Drop `Frame -1` on the row: the widget draws its own bevels now, and an
FvwmButtons frame around them will double up.

### Acceptance

- Nothing flashes. Watch it for a full minute with a player running and a
  player absent.
- Track title scrolls smoothly and wraps.
- Slider drags, follows the sink when volume is changed elsewhere, and does not
  fight its own updates mid-drag.
- Glyphs are glyphs.
- Sunken field uses `#4b4b4b`, not `#a7a7a7`. Put it next to the screenshot.

## Task 2 — System Monitor meters

Two routes, and the design note deliberately does not pick one:

**2a. Stay with conky.** `conky -v` here confirms Lua bindings for Cairo, so
`lua_draw_hook_post` can draw per-bar sunken bevels and colour fills — roughly
60-100 lines over a `{icon, value, y}` table, reading values through
`conky_parse("${cpu}")` rather than polling separately. Keeps a working
component working.

**2b. Fold it into the Qt widget set.** `psutil` is installed; the bevel code
is already written for Task 1; and it makes the DSK row's *two* bars trivial —
the reference has a variable number of bars per row, which is exactly what
neither FvwmButtons nor a fixed conky template expresses well.

Recommendation: **try 2a first.** It is smaller, and if the trough drawing
lands cleanly the meters stop being a reason to migrate anything. Fall back to
2b if the Cairo hook fights the existing conky layout.

Either way the target is: 20px colour icon at x=6..25, bar from x=30 to the
right margin, 12-13px tall, `#bcbcbc` trough with a `#4b4b4b` outline, fills
`#d6cdba` (CPU) and `#b5c4b0` (MEM), and the DSK row carrying two thin bars.

We have no Photon icon set — the three glyphs (CPU chip, RAM sticks,
disk+folder) will need drawing or sourcing. Flag it rather than substituting
something off-palette.

## Task 3 — correct the two wrong comments

Small, and worth doing while the context is fresh. Both are checked in and both
mislead:

- `FvwmScript-ShelfMedia` header: the `HScrollBar` claim is wrong. It *does*
  emit `SingleClic` on drag; the trap is that `SingleClic` is `#define -1`, so a
  `1 :` case label never matches. Verified live. If the file is deleted in
  Task 1, fold the correction into `PANEL-DESIGN.md` only.
- `shelf.items` / `bin/mk-shelf`: the `UseOld` stranding analysis is correct,
  but it should note that `FvwmButtons`' `Panel` primitive sidesteps the whole
  kill-and-restart design, so a future reader does not conclude the swap was
  the only option.

## Testing

```
FvwmCommand Restart                          # reload everything
FvwmCommand ShelfDockRender                  # re-render just the dock
FvwmCommand 'KillModule FvwmButtons ShelfDock'
```

Run the widget standalone first — it is an ordinary window until something
swallows it. Only wire it into `shelfdock.items` once it looks right on its own.

Useful while iterating:

```
xwininfo -id $(xdotool search --name '^ShelfMedia$' | head -1) -tree
import -window root -crop 160x300+1760+780 /tmp/shelf.png
```

Note `xdotool search --class` matches the *second* WM_CLASS field (the class),
not the instance — use `--classname` for the instance, or `--name` for the
title. This cost time already.

## Known traps

- FvwmButtons resizes a swallowed window to its cell, but a widget laid out at
  fixed positions will clip rather than reflow. Keep the spec height and the
  widget's size hint in step, or make the widget genuinely resizable.
- `mk-shelf` reissues `DestroyModuleConfig` on every render, which is why
  module-wide `*Shelf:` lines live in the spec files rather than in `config`.
  Do not move them.
- Never put a `Swallow` in `shelf.items`. That constraint still stands for as
  long as the accordion swaps aliases.
- Re-rendering the dock restarts everything swallowed in it, including the
  pager and conky. `ShelfDockRender` is deliberately not called from
  `ShelfToggle`; keep it that way.
- A `*Module: option` line does not expand `$[...]`. Computed values go through
  `PipeRead "echo ..."`.
