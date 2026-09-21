# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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

**colorsets** — all FVWM colorsets plus the exported QNX Photon palette used by the sidebar.

**lib/Thumbnail** — custom Perl module using Image::Magick for window thumbnail generation (200x180px, cached in `.thumbs/` with 100s expiry). Loaded via `ModulePath` and recycled every 300s.

**FvwmScript-\*** — small UI dialogs (DateTime widget, Confirm{Quit,Reboot,Shutdown}).

**scripts/** — shell scripts: `onLock.sh` (xsecurelock), `onSuspend.sh`, `onReboot.sh`, `onShutdown.sh`, `toggle_whiskermenu.sh` (xdotool-based).

## Key Conventions

- Functions follow Destroy-then-Add pattern: `DestroyFunc Name` / `AddToFunc Name`
- Module configs follow: `DestroyModuleConfig Mod:*` / `*Mod: Option Value`
- Window styles use FVWM3 syntax: `Style "pattern" opts...`
- Desktop layout is 4x2 pages with 5 layers (1/2/4/6/11)
- Default terminal: kitty (`$[infostore.terminal]`)
- Paths use `$[FVWM_USERDIR]` env var pointing to `~/.fvwm`
- Photon colors belong in `colorsets`; sidebar code reads the exported `FVWM_PHOTON_*` values
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
