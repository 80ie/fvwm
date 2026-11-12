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

The only automated checks are `cd bin && QT_QPA_PLATFORM=offscreen python3 -m
unittest test_photon_tasks` and `bin/tray-randr-test`. `FvwmCommand` follows
`$FVWMMFL_SOCKET`, not `$DISPLAY`, so a scratch Xvfb rig reaches the live fvwm
(and `pkill` ignores `$DISPLAY`) unless it runs in a PID namespace as
`bin/tray-randr-test` does (`unshare -Urpf --mount-proc`).

## Architecture

**config** — the main configuration, organized into sections:
- Environment variables & paths (terminals, dirs, layers)
- Functions (StartFunction, tiling, window ops, thumbnails)
- Menus (root Toolchest, window ops, session control, SendTo)
- Styles (global defaults + per-application overrides)
- Colorset loading
- Module configs (FvwmEvent, ShelfPager, FvwmPerl, Thumbnail)

**bindings** — every `Key`/`Mouse` binding (numpad tiling, page navigation,
window ops), pulled in by `Read bindings`. `bin/fvwm-keys` serves a local web
page to browse and edit it and re-applies the file live.

**colorsets** — FVWM colorsets 0-37 and the canonical QNX Photon palette. The
palette is exported as `FVWM_PHOTON_*` values inherited by the shelf; direct
component launches fall back to reading the same file.

**The shelf is one program** — `bin/shelf-panel`, a PyQt6 window down either
screen edge (`ShelfToLeft`/`ShelfToRight`). It draws its own frame, group headers, launcher rows, pager,
meters and media widget; reads its sections from `panel.items`; and keeps its
side, width, visibility and collapse state in `.panel.state`. fvwm keeps the `Style` rule
(layer 5), the `EwmhBaseStruts` reservation and launching, and nothing else.

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
clock). `taskbar.items`, the cell list `bin/mk-taskbar` used to render, is
left on disk unused; nothing wires it in.

**Shelf components** — everything the panel draws, split so each piece stays
testable on its own. Run any of them directly and it comes up as an ordinary
window.

| file | what it is |
|---|---|
| `bin/photon.py` | the shared Photon look: palette, bevels, themed icons |
| `bin/photon_palette.py` | loads and validates the `FVWM_PHOTON_*` palette from `colorsets` |
| `bin/shelf-panel` | the window: frame, headers, launchers, resize, layout |
| `bin/photon_media.py` | MPRIS transport, marquee title, cover art, volume slider |
| `bin/photon_meters.py` | CPU / memory / filesystem meters, via `psutil` |
| `bin/photon_pager.py` | World View: the `ShelfPager` FvwmPager module, reparented in via Qt's foreign-window container and relaunched (`ShelfPagerLaunch`) at each width step |
| `bin/photon_tasks.py` | the window list, drawn from EWMH; sticky windows as an icon strip at the top; shows `lib/Thumbnail` previews for minimized windows |
| `bin/photon_tray.py` | the system tray: stalonetray reparented in via Qt's foreign-window container |
| `bin/photon_clock.py` | the clock field that used to be a taskbar cell |

The pager and the tray are the two pieces that are swallowed rather than drawn.
FvwmPager's highlight window has no border option and no way to get one that
stays even-width and unclipped; an `SGradient` ring in `HilightColorset` was
tried and dropped, so the current page is marked by fill colour alone.

Three bevel vocabularies, one function each in `photon.py`: soft-bevelled
chrome (`raised`), hard-outlined sunken wells (`sunken`, `trough`, `groove`),
and hard-outlined gradient-faced controls (`button`, `thumb`). Do not reach
for the soft one on a control; that is the mistake the FvwmScript version
made. Every painter's docstring names the pixel it was measured from.

Almost nothing polls. Media takes D-Bus `PropertiesChanged` (matched on the
sender's *unique* bus name, never the well-known `org.mpris.MediaPlayer2.*`
one), a long-lived `pactl subscribe`, and it fetches cover art when a track
names one -- a request that ends with its image or its timeout; the window
list takes root-window `PropertyNotify` through a `QSocketNotifier` on Xlib's
own connection. Only the meters sample, because a CPU has no change signal,
and they repaint only when a bar lands on a different pixel.

A component owns no geometry beyond a size hint. The few that call back into
fvwm do it through `FvwmCommand` (the pager's launch/kill, media output
selection, the shelf's struts). That is the rule that let the media and
meters widgets move from being swallowed windows to being child widgets
without a line changing in either.

**Other `bin/` tools** — `palette` (below), `fvwm-keys` (see **bindings**),
`tile-floats` (the persistent per-WM_CLASS tiling float list in
`.tile-floats`; `TILE-FLOATS.md` has the design), `shelf-snapshot` (the real
shelf drawn offscreen to a PNG from `$FVWM_USERDIR/colorsets`, every live
source swapped for canned content) and `tray-randr-test`.

**bin/fvwmscript-icontest** — regression check: FvwmScript's `Icon` property is
broken in fvwm3 1.1.2, and a widget carrying one fails to draw *and takes every
later widget with it*. Re-run after an fvwm upgrade. FvwmScript also has no
hover event. Its `HScrollBar` *does* emit on drag — the trap is that
`SingleClic` is `#define -1`, so a `1 :` case label never matches.
`PANEL-DESIGN.md` has the detail.

**lib/Thumbnail** — custom Perl module using Image::Magick for window thumbnail generation (up to 320x240px, cached in `images/thumbs/` with 15s expiry; `StartFunction` prunes files older than 7 days). Loaded via `ModulePath` and recycled every 300s.

**FvwmScript-\*** — small UI dialogs (Confirm{Quit,Reboot,Shutdown}).
`FvwmScript-DateTime` is no longer used for the clock (that's now
`bin/photon_clock.py`, a Qt widget in the shelf) but is kept.

**scripts/** — shell scripts: `onLock.sh` (xsecurelock), `onSuspend.sh`, `onReboot.sh`, `onShutdown.sh`.

## Key Conventions

- Functions follow Destroy-then-Add pattern: `DestroyFunc Name` / `AddToFunc Name`
- Module configs follow: `DestroyModuleConfig Mod:*` / `*Mod: Option Value`
- Window styles use FVWM3 syntax: `Style "pattern" opts...`
- Desktop layout is 3x3 pages on one desk with 5 layers (1/2/4/6/11); the shelf sits at 5
- Default terminal: kitty (`$[infostore.terminal]`)
- Paths use `$[FVWM_USERDIR]` env var pointing to `~/.fvwm`
- A `*Module: option` config line does **not** expand `$[...]`; anything needing
  a computed value (Geometry, ButtonGeometry) goes through `PipeRead "echo ..."`
- `InfoStoreAdd` on an existing key replaces it, so re-reads recompute cleanly
- Colorsets 5-14 (menus, modules) and 20-21, 30-37 are the Photon set
  (menus and modules, ShelfPager page/window colours, shelf chrome); 16-19 are
  unused legacy. Window decor (40, 41, 15) is rendered too; `config` can pin
  it back with `Colorset` lines after the `Read colorsets` (the last one wins).
  Menus use the default style (`MenuStyle *`); a named style does nothing
  without a `ChangeMenuStyle <style> <menu>` naming menus.
- Photon colors are defined only in `colorsets`, never as literal `QColor` values
- Colors for every platform come from `palette/`: a wallust scheme in
  `palette/schemes/` rendered through `palette/templates/` (`roles.j2` derives
  every role). `bin/palette preview <scheme|image>` diffs; `apply` writes, backs up
  and reloads; `save <name>` stores the live palette as a scheme (`apply <name>`
  restores it) and `list` names them. `colorsets` and `stalonetrayrc` are among
  its outputs (alongside Qt, KDE, GTK 3/4 and Xresources), so edit the
  template, not them. Each `apply` leaves a backup and `restore.sh` in
  `palette/history/<timestamp>/`.
  Every render also writes `~/.cache/palette/key.html`, a visual key of each
  color, its role and where it lands; `qt.j2` slot names are its labels.
  `palette sweep <images|schemes> --vary palette=a,b --vs live` draws the shelf
  for every source and flag set into `~/.cache/palette/sweep/index.html`
  (axes are `AXIS_SPECS`, values read from the installed wallust's `run -h`,
  so it works on 3.5 and 4.x), collapsing identical palettes and never
  touching a live file, and scaling any image over 64 MP down to a cached
  copy first (wallust refuses to decode much more: "Memory limit exceeded");
  `--interactive` serves it on localhost with image drop and per-cell save, and `save <name> --from <src> -- <flags>` keeps a variant.
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
