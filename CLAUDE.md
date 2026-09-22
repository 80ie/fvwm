# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FVWM3 window manager configuration. `~/.fvwm` is a symlink to `dotfiles/.fvwm`. The main `config` uses vim fold markers (`{{{`/`}}}`) for section organization and reads the separate `colorsets` file.

## Testing Changes

There is no build or test system. To apply changes:
- `FvwmCommand Restart` — reload the entire config (restarts FVWM in place)
- `FvwmCommand <command>` — execute a single FVWM command without full restart
- `FvwmConsole` — interactive FVWM command shell for testing commands live

## Architecture

**config** — the main configuration, organized into sections:
- Environment variables & paths (terminals, dirs, layers)
- Functions (StartFunction, tiling, window ops, thumbnails)
- Menus (root Toolchest, window ops, session control, SendTo)
- Styles (global defaults + per-application overrides)
- Colorset loading
- Key & Mouse bindings (numpad tiling, page navigation, window ops)
- Module configs (FvwmEvent, FvwmPager, FvwmPerl, Thumbnail)

**colorsets** — FVWM colorsets 0-37 and the canonical QNX Photon palette. The
palette is exported as `FVWM_PHOTON_*` values inherited by the shelf; direct
component launches fall back to reading the same file.

**The shelf is one program** — `bin/shelf-panel`, a PyQt6 window down the
right edge. It draws its own frame, group headers, launcher rows, pager,
meters and media widget; reads its sections from `panel.items`; and keeps its
width and collapse state in `.panel.state`. fvwm keeps the `Style` rule, the
`EwmhBaseStruts` reservation and launching, and nothing else.

It stopped being FvwmButtons because three things were out of reach there and
all three are free here (`PANEL-DESIGN.md` has the measurements):

- **The double bevel.** The reference's left edge is two nested bevels with a
  2px face channel — `#4b4b4b #ffffff #d8d8d8 #d8d8d8 #a6a6a6 #4b4b4b
  #ffffff`. `Frame N` draws *one* bevel N wide from a colorset's hi/sh and
  cannot nest, at any N.
- **Live resizing.** FvwmButtons cannot resize its grid, so a width change
  meant regenerating and restarting the module.
- **Collapsing without a flicker.** Same reason. A module restart is
  asynchronous with no "I am mapped" signal to sequence against, so the
  `Schedule 150 KillModule` swap was a race: measured at 60fps it dropped the
  shelf to bare wallpaper on 2 toggles in 8. The same test on the panel is 0
  in 8.

`EwmhBaseStruts` **does** take effect at runtime — verified by maximising a
window across a strut change — which is what lets the shelf be resizable at
all. The panel re-issues it as you drag; `bin/shelf-panel --print-width` is
how the config gets it right again after a Restart, which re-reads the
config. The panel itself is restarted along with fvwm (`StartFunction` pkills
and relaunches it), so this only covers the moment between the config
re-read and the panel coming back up.

**Generated panel — retired.** The bottom `FvwmTaskBar` this fed is gone from
`config`; the shelf now carries everything it held (window list, tray,
clock). `bin/mk-taskbar` and `taskbar.items` are left on disk unused rather
than deleted, in case a generated cell list is useful again, but nothing
wires them in.

**Shelf components** — everything the panel draws, split so each piece stays
testable on its own. Run any of them directly and it comes up as an ordinary
window.

| file | what it is |
|---|---|
| `bin/photon.py` | the shared Photon look: palette, bevels, themed icons |
| `bin/shelf-panel` | the window: frame, headers, launchers, resize, layout |
| `bin/photon_media.py` | MPRIS transport, marquee title, cover art, volume slider |
| `bin/photon_meters.py` | CPU / memory / filesystem meters, via `psutil` |
| `bin/photon_pager.py` | World View, drawn from EWMH rather than swallowed |
| `bin/photon_tasks.py` | the window list, drawn from EWMH like the pager |
| `bin/photon_tray.py` | the system tray: stalonetray reparented in via Qt's foreign-window container — the one piece here that is swallowed rather than drawn |
| `bin/photon_clock.py` | the clock field that used to be a taskbar cell |

Three bevel vocabularies, one function each in `photon.py`: soft-bevelled
chrome (`raised`), hard-outlined sunken wells (`sunken`, `trough`, `groove`),
and hard-outlined gradient-faced controls (`button`, `thumb`). Do not reach
for the soft one on a control; that is the mistake the FvwmScript version
made. Every painter's docstring names the pixel it was measured from.

Almost nothing polls. Media takes D-Bus `PropertiesChanged` (matched on the
sender's *unique* bus name, never the well-known `org.mpris.MediaPlayer2.*`
one), a long-lived `pactl subscribe`, and it fetches cover art when a track
names one -- a request that ends with its image or its timeout; the pager
takes root-window
`PropertyNotify` through a `QSocketNotifier` on Xlib's own connection. Only
the meters sample, because a CPU has no change signal, and they repaint only
when a bar lands on a different pixel.

A component owns no geometry beyond a size hint and never talks to fvwm.
That is the rule that let the media and meters widgets move from being
swallowed windows to being child widgets without a line changing in either.

**bin/fvwmscript-icontest** — regression check: FvwmScript's `Icon` property is
broken in fvwm3 1.1.2, and a widget carrying one fails to draw *and takes every
later widget with it*. Re-run after an fvwm upgrade. FvwmScript also has no
hover event, which is why the shelf is FvwmButtons. (Its `HScrollBar` *does*
emit on drag — the trap is that `SingleClic` is `#define -1`, so a `1 :` case
label never matches. `PANEL-DESIGN.md` has the detail; this is the correction
to a comment that used to live in `FvwmScript-ShelfMedia`.)

**lib/Thumbnail** — custom Perl module using Image::Magick for window thumbnail generation (200x180px, cached in `.thumbs/` with 100s expiry). Loaded via `ModulePath` and recycled every 300s.

**FvwmScript-\*** — small UI dialogs (Confirm{Quit,Reboot,Shutdown}).
`FvwmScript-DateTime` is no longer used for the clock (that's now
`bin/photon_clock.py`, a Qt widget in the shelf) but is kept.

**scripts/** — shell scripts: `onLock.sh` (xsecurelock), `onSuspend.sh`, `onReboot.sh`, `onShutdown.sh`, `toggle_whiskermenu.sh` (xdotool-based).

## Key Conventions

- Functions follow Destroy-then-Add pattern: `DestroyFunc Name` / `AddToFunc Name`
- Module configs follow: `DestroyModuleConfig Mod:*` / `*Mod: Option Value`
- Window styles use FVWM3 syntax: `Style "pattern" opts...`
- Desktop layout is 3x3 pages on one desk with 5 layers (1/2/4/6/11)
- Default terminal: kitty (`$[infostore.terminal]`)
- Paths use `$[FVWM_USERDIR]` env var pointing to `~/.fvwm`
- A `*Module: option` config line does **not** expand `$[...]`; anything needing
  a computed value (Geometry, ButtonGeometry) goes through `PipeRead "echo ..."`
- `InfoStoreAdd` on an existing key replaces it, so re-reads recompute cleanly
- Colorsets 0-21 are the warm brown/rust set; 30-37 are the Photon greys
- Photon colors are defined only in `colorsets`, never as literal `QColor` values
- Icons are 16x16 PNGs in `icons/`; backgrounds in `images/background/`
- Sounds (MP3) in `sounds/` triggered by FvwmEvent modules

## Documentation Reference

All FVWM documentation is in `doc/`. **Always consult these files before answering configuration questions.**

### Man Pages (`doc/Man/`)

| File | Contents |
|------|----------|
| `fvwm3all.html` | Complete combined reference — search here first for any command/option |
| `fvwm3.html` | Core concepts: virtual desktop, anatomy of a window, initialization, fonts, RANDR |
| `fvwm3commands.html` | All built-in commands grouped: window movement/state, focus, key/mouse bindings, virtual desktop, functions, conditionals, modules, session, colorsets |
| `fvwm3styles.html` | Complete `Style` option reference |
| `FvwmEvent.html` | Event-driven actions (window open/close/focus hooks) |
| `FvwmPager.html` | Virtual desktop pager module |
| `FvwmPerl.html` | Perl scripting integration |
| `FvwmScript.html` | FvwmScript dialog/widget language |
| `FvwmButtons.html` | Button panel/taskbar module |
| `FvwmForm.html` | Form dialog module |
| `FvwmIconMan.html` | Icon manager module |
| `FvwmMFL.html` | Mouse/focus/layer control module |
| `FvwmRearrange.html` | Window tiling/cascading module |
| `FvwmConsole.html` | Interactive command console |
| `FvwmCommand.html` | External command injection tool |
| `FvwmIdent.html` | Window property inspector (use to find class/name for Style rules) |
| `FvwmAnimate.html` | Animated iconify/deiconify effects |
| `FvwmAuto.html` | Auto-raise/focus module |
| `FvwmBacker.html` | Per-desktop background changer |
| `FvwmPrompt.html` | Interactive prompt module |
| `fvwm-perllib.html` | Perl library for FVWM modules |
| `fvwm-menu-desktop.html` | XDG/desktop menu generator |

### Wiki (`doc/Wiki/`)

Practical how-tos with config examples. Each entry is `<dir>/index.md`.

**Config/** — syntax and how-to for each major config area:
- `Bindings/` — Key/Mouse syntax, contexts (R/W/T/F/S/I), modifiers
- `Colorsets/` — Colorset syntax and theming
- `Commands/` — Built-in command usage
- `Conditionals/` — `Test`, `TestRc`, conditional command syntax
- `Decor/` — Window decoration configuration
- `DesktopConfiguration/` — DesktopSize, desk names, pages
- `Fonts/` — Font specification syntax
- `Functions/` — AddToFunc/DestroyFunc, contexts (I/C/D/H/M); subdirs: `ComplexFunctions/`, `FunctionContext/`, `FunctionSynchronisation/`, `FunctionTips/`, `StartFunction/`
- `Menus/` — Menu definition and styles
- `Modules/` — How to configure and load modules
- `Monitors/` — Multi-monitor/RandR setup
- `MouseStroke/` — Mouse gesture bindings
- `PagesAndDesks/` — Page navigation, virtual desktops
- `Style/` — Style syntax and matching
- `StyleTips/` — Practical style patterns
- `Syntax/` — General config file syntax rules
- `VectorButtons/` — Vector-drawn title buttons

**CookBook/** — complete recipes for specific features:
`AltTab`, `DeskDecor`, `IconifyExcept`, `InitialMapCommand`, `LimitApplication`, `SaveState`, `ShowCalendar`, `ShowDesktop`, `StickyDecor`, `TitleShade`, `AdaptiveButtons`

**Tips/** — focused tips:
`AutoHidingWindows`, `BorderMaximize`, `CapsLockAsModifier`, `CenterPlacement`, `FocusStealing`, `FvwmIconMan`, `FvwmStartup`, `GradientBackgrounds`, `IconsOnDesktop`, `MouseGestures`, `RandomWallPaper`, `ResizeWindowCenter`, `ThumbnailsAsIcons`, `TogglingWindows`, `Transparency`

**Modules/** — per-module examples:
`FvwmAnimate`, `FvwmAuto`, `FvwmBacker`, `FvwmBanner`, `FvwmButtons`, `FvwmEvent`, `FvwmForm`, `FvwmIconMan`, `FvwmIdent`, `FvwmPager`, `FvwmRearrange`, `FvwmScript`, `SendToFvwm`

**Decor/** — full decoration themes to reference or adapt:
`CDE`, `Crux`, `Default`, `Mech`, `NanoGui`, `OSX`, `QNX`, `Redmond98`, `RedmondXP`, `Vectors`, `4Btm`

**Panels/** — panel/taskbar examples:
`FvwmTaskBar`, `HoverButtons`, `RightPanel`, `SensorDock`, `SimpleButtons`
