# AGENTS.md

This file provides guidance to coding agents working in this repository. `CLAUDE.md` is a symlink to it.

## Overview

FVWM3 window manager configuration. `~/.fvwm` is the live config dir (git repo, origin 80ie/fvwm). The main `config` uses vim fold markers (`{{{`/`}}}`) for section organization and reads the separate `colorsets` file.

## Testing Changes

There is no build system. To apply changes:
- `FvwmCommand Restart` — reload the entire config (restarts FVWM in place)
- `FvwmCommand <command>` — execute a single FVWM command without full restart
- `FvwmConsole` — interactive FVWM command shell for testing commands live

**Test visually without touching the live session: `bin/fvwm-rig`.** It runs
the real config (minus autostart daemons) on a private Xvfb inside user, PID,
mount and net namespaces with a throwaway `$HOME`, so no live socket, bus or
process is reachable. `up [--size WxH] [--fresh]`, `restart` (re-syncs the
working tree, then `Restart`), `cmd <fvwm command>`, `shot [file.png]` (read
the PNG), `exec <cmd>` (e.g. `exec setsid -f kitty`, `exec xdotool key ...`),
`down`. Prefer it over `FvwmCommand Restart` on the live session.

The rig runs the installed panel, `~/.local/bin/jian`, copied in at each sync.
`FvwmCommand` follows `$FVWMMFL_SOCKET`, not `$DISPLAY`, so a scratch Xvfb
reaches the live fvwm (and `pkill` ignores `$DISPLAY`) unless it runs in a PID
namespace as the rig does (`unshare -Urpfn --mount-proc`).

## Architecture

**config** — the main configuration, organized into sections:
- Environment variables & paths (terminals, dirs, layers)
- Functions (StartFunction, tiling, window ops)
- Menus (root Toolchest, window ops, session control, SendTo)
- Styles (global defaults + per-application overrides)
- Colorset loading
- Module configs (FvwmEvent, FvwmPerl)

**bindings** — every `Key`/`Mouse` binding (numpad tiling, page navigation,
window ops), pulled in by `Read bindings`. `bin/fvwm-keys` serves a local web
page to browse and edit it and re-applies the file live.

**colorsets** — FVWM colorsets 0-41 and the `FVWM_PHOTON_*` palette that menus
and modules read. jian's fvwm export writes it when enabled; its template is
`~/.config/jian/exports/fvwm/template`.

**The panel is jian** — a separate C++/Qt program in `~/projects/jian`, whose
`docs/spec.md` is the reference, installed to `~/.local/bin/jian`. It
replaced `bin/shelf-panel` and `bin/palette`, which are in this repository's
history. `StartFunction` starts it at every (re)start; a second one exits, so a
`Restart` leaves the running panel alone. It is an EWMH dock and sets its own
strut, side and width (drag its inner edge; its menu docks it left or right),
kept in `~/.config/jian/config.ini`. fvwm keeps two `Style` lines: `jian` for
the panel and `JianWorldView` for the FvwmPager the panel starts, configures
over `FvwmCommand` and swallows.

**Generated panel — retired.** The bottom `FvwmTaskBar` this fed is gone from
`config`; the panel now carries everything it held (window list, tray,
clock). `taskbar.items`, the cell list `bin/mk-taskbar` used to render, is
left on disk unused; nothing wires it in.

**Other `bin/` tools** — `fvwm-keys` (see **bindings**) and `tile-floats`
(the persistent per-WM_CLASS tiling float list in `.tile-floats`;
`TILE-FLOATS.md` has the design).

**bin/fvwmscript-icontest** — regression check: FvwmScript's `Icon` property is
broken in fvwm3 1.1.2, and a widget carrying one fails to draw *and takes every
later widget with it*. Re-run after an fvwm upgrade. FvwmScript also has no
hover event. Its `HScrollBar` *does* emit on drag — the trap is that
`SingleClic` is `#define -1`, so a `1 :` case label never matches.
`PANEL-DESIGN.md` has the detail.

**FvwmScript-\*** — small UI dialogs (Confirm{Quit,Reboot,Shutdown}).
`FvwmScript-DateTime` is no longer used for the clock (the panel draws it)
but is kept.

**scripts/** — shell scripts: `onLock.sh` (xsecurelock), `onSuspend.sh`, `onReboot.sh`, `onShutdown.sh`.

## Key Conventions

- Functions follow Destroy-then-Add pattern: `DestroyFunc Name` / `AddToFunc Name`
- Module configs follow: `DestroyModuleConfig Mod:*` / `*Mod: Option Value`
- Window styles use FVWM3 syntax: `Style "pattern" opts...`
- Desktop layout is 3x3 pages on one desk with 5 layers (1/2/4/6/11); the panel, a dock, sits at 6
- Default terminal: kitty (`$[infostore.terminal]`)
- Paths use `$[FVWM_USERDIR]` env var pointing to `~/.fvwm`
- A `*Module: option` config line does **not** expand `$[...]`; anything needing
  a computed value (Geometry, ButtonGeometry) goes through `PipeRead "echo ..."`
- `InfoStoreAdd` on an existing key replaces it, so re-reads recompute cleanly
- Colorsets 5-14 (menus, modules) and 30-33 (the old shelf chrome) are the
  Photon set; 20-21 and 36-37 belonged to the retired ShelfPager and 16-19 are
  unused legacy. jian sets 300-303 for its pager at runtime. Window decor (40, 41, 15) is rendered too; `config` can pin
  it back with `Colorset` lines after the `Read colorsets` (the last one wins).
  Menus use the default style (`MenuStyle *`); a named style does nothing
  without a `ChangeMenuStyle <style> <menu>` naming menus.
- Fonts: one `font` InfoStore key in `config` (Linux Libertine semibold 10). `DefaultFont`,
  `Style * Font` and the `*FvwmIdent`/`*FvwmScript` module lines take
  `$[infostore.font]`; FvwmScript-* files set no `Font`.
- Colors for fvwm, Qt, KDE and GTK come from jian's palette through its export
  targets in `~/.config/jian/exports/`, each enabled on the settings window's
  Exports page. The old wallust schemes are presets in `~/.config/jian/palettes/`.
- Icons are 16x16 PNGs in `icons/`; backgrounds in `images/bg/`
- Sounds (MP3) in `sounds/` triggered by FvwmEvent modules

## Documentation Reference

All FVWM documentation is in `docs/`. **Always consult these files before answering configuration questions.**

### Man Pages (`docs/Man/`)

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

### Wiki (`docs/Wiki/`)

Practical how-tos with config examples. Each entry is `<dir>/index.md` (a few, such as `Config/Functions` and `Modules/SendToFvwm`, are `index.html`).

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
