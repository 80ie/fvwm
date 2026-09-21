# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FVWM3 window manager configuration. `~/.fvwm` is a symlink to `dotfiles/.fvwm`. The main config is a single monolithic file (`config`) with vim fold markers (`{{{`/`}}}`) for section organization.

## Testing Changes

There is no build or test system. To apply changes:
- `FvwmCommand Restart` — reload the entire config (restarts FVWM in place)
- `FvwmCommand <command>` — execute a single FVWM command without full restart
- `FvwmConsole` — interactive FVWM command shell for testing commands live

## Architecture

**config** — the single source of truth (~1200 lines), organized into sections:
- Environment variables & paths (terminals, dirs, layers)
- Functions (StartFunction, tiling, window ops, thumbnails)
- Menus (root Toolchest, window ops, session control, SendTo)
- Styles (global defaults + per-application overrides)
- Colorsets (warm brown/rust 0-21, QNX Photon greys 30-37)
- Key & Mouse bindings (numpad tiling, page navigation, window ops)
- Module configs (FvwmEvent, FvwmPager, FvwmPerl, Thumbnail)

**Generated panels** — the QNX Photon shelf and taskbar. FvwmButtons has no
flexible sizing and cannot hide a button or resize its grid at runtime, so
their cell lists are generated from spec files rather than written by hand:

| generator | spec | window |
|---|---|---|
| `bin/mk-shelf` | `shelf.items` | `ShelfMenu` — collapsible launcher accordion, right edge |
| `bin/mk-shelf --static` | `shelfdock.items` | `ShelfDock` — pager, meters, media; holds every Swallow |
| `bin/mk-taskbar` | `taskbar.items` | `FvwmTaskBar` — Launch, window list, tray, VOL, clock |

Adding a row means adding a spec line; widths/heights are solved by the
generator, which hands leftover pixels to a `flex` cell. **Never put a Swallow
in `shelf.items`** — `ShelfMenu` swaps between two aliases on every toggle, and
the outgoing instance still holds a swallowed window when the incoming one
looks for it, so `UseOld` spawns a stranded duplicate. Swallowed things go in
`shelfdock.items`, which is `--static` and kills before it starts.

**bin/shelf-media** — MPRIS transport and sink volume for the shelf's Media
widget, via `gdbus` and `wpctl` (no playerctl dependency). **conkyrc-shelf** —
the System Monitor meters, swallowed into the dock.

**bin/fvwmscript-icontest** — regression check: FvwmScript's `Icon` property is
broken in fvwm3 1.1.2, and a widget carrying one fails to draw *and takes every
later widget with it*. Re-run after an fvwm upgrade. FvwmScript also has no
hover event and its `HScrollBar` emits no message when moved, which is why the
shelf is FvwmButtons and the media widget uses `-`/`+` rather than a slider.

**lib/Thumbnail** — custom Perl module using Image::Magick for window thumbnail generation (200x180px, cached in `.thumbs/` with 100s expiry). Loaded via `ModulePath` and recycled every 300s.

**FvwmScript-\*** — small UI dialogs (Confirm{Quit,Reboot,Shutdown}) plus
`ShelfMedia`, the dock's media widget. `FvwmScript-DateTime` is no longer used
by the taskbar (its clock is a native FvwmButtons cell updated via
`SendToModule ChangeButton`) but is kept.

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
- Colorsets 0-21 are the warm brown/rust set; 30-37 are the Photon greys and are
  referred to by the `cs_*` InfoStore keys, never by number
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
