# Persistent per-class tiling floats

## Goal

Windows floated via a menu entry are excluded from automatic tiling
per-application (WM_CLASS), persisted in `~/.fvwm/.tile-floats` (one class
per line).  This survives: fvwm restart, window close+reopen, new
instances, desktops.  Toggling membership for an application via
**Win+Shift+Space remains session-only** (`TileToggleFloating`, unchanged).

## Why per-class

FVWM State bits (11 tiled / 12 floating / 13 master) are runtime-only:
gone on `fvwm3 -c Restart` or when the window is recreated.  There is no
fvwm option that persists State across restarts or pre-sets it on
existing windows.  WM_CLASS is the only identity that survives.

## Verified mechanics (as-is)

- All fvwm-side tiling queries match `!State 12`; State-12 floats already
  persist in-session (verified in TileAdmit, TileEnsureMaster,
  TileArrange, TileDisable, TileFloat, TileJoin).
- FvwmRearrange has NO state filter; floated/master/fullscreen windows
  are protected during the module call by the temporary StickyAcrossPages
  mark in `TileArrange` (sticky is ignored by FvwmRearrange by default),
  unmarked right after.  No change needed there.
- FvwmEvent window handlers run in the window context with PassID ($0 =
  window id); there are no per-window env vars from FvwmEvent.  fvwm has
  no way to read a window's WM_CLASS inside a function -> an external
  helper does it (Xlib, already used in bin/).
- PipeRead executes each output line as an fvwm command in the current
  context; user function names are valid fvwm commands, so the helper can
  emit `TileFloatClassOn` / `TileFloatClassOff`.
- The menu button top-left of the titlebar (frame-corner button 1,
  binding line `Mouse 1 1 A Menu MenuWindowOps Delete`) runs in the
  window context of the clicked frame.

## Files

### 1. `bin/tile-floats` (new, python3, Xlib)

State file: `$FVWM_USERDIR/.tile-floats` (default `~/.fvwm`), one
WM_CLASS per line, `#` comments allowed.  Atomic write via tmp+rename.

Subcommands:

| cmd            | reads | emits (fvwm commands)                                        |
|----------------|-------|--------------------------------------------------------------|
| `list`         | file  | `SetEnv TILE_FLOATS "Class1 Class2 …"` (always one line)     |
| `admit <id>`   | Xlib  | `WindowId <id> State 12 True` iff its class is listed        |
| `toggle`       | Xlib  | `TileFloatClassOn` or `TileFloatClassOff`                    |

- `toggle` resolves the class of the window **under the pointer**
  (deepest root child, climb parents until one has WM_CLASS), fallback to
  input-focus owner, so no window-id plumbing is needed from the menu.
- X errors -> no output, exit 0 (PipeRead-safe no-op).
- `admit` must never fail the admit path: any exception = emit nothing.

### 2. `config`

- **Top** (next to the `SetEnv TILING_0-0-0 on` block, line ~28):
  `PipeRead "$[FVWM_USERDIR]/bin/tile-floats list" quiet`
  Runs at config load, before `StartFunction`'s `Module FvwmEvent`, so
  the env is populated before the add_window storm.  After `Restart`,
  FvwmEvent re-fires add_window for existing windows -> all their listed
  classes auto-float again.
- **`TileAdmit`**: insert BEFORE the tiling-on test:
  `+ I PipeRead "$[FVWM_USERDIR]/bin/tile-floats admit $0" quiet`
  Emitted `WindowId $0 State 12 True` makes the next line's KeepRc
  matcher (`!State 12`) NoMatch -> `Break`.  No TileArrange triggered.
  (Runs even when the page's tiling is off so the float mark is present
  if tiling is later enabled for that window.)
- **New functions** (place next to `TileFloat`/`TileJoin`):
  ```
  DestroyFunc TileFloatClassToggle
  AddToFunc TileFloatClassToggle
  + I PipeRead "$[FVWM_USERDIR]/bin/tile-floats toggle"

  DestroyFunc TileFloatClassOn
  AddToFunc TileFloatClassOn
  + I TileFloat
  + I PipeRead "$[FVWM_USERDIR]/bin/tile-floats list"

  DestroyFunc TileFloatClassOff
  AddToFunc TileFloatClassOff
  + I TileJoin
  + I PipeRead "$[FVWM_USERDIR]/bin/tile-floats list"
  ```
  `toggle` edits the file first, then emits the direction function, so by
  the time the final `PipeRead … list` re-syncs the env, file and env
  agree.
- **`MenuWindowOps`** (after "Toggle Title"):
  `+ "" Nop` + `+ "Persistent float" TileFloatClassToggle`

## Semantics

| action                          | live state | file (persistent) |
|---------------------------------|-----------|-------------------|
| Win+Shift+Space (tile toggle)   | float/unfloat (session) | untouched |
| menu "Persistent float"         | float/unfloat        | class added/removed |
| new window of listed class      | opens floated        | — |
| fvwm restart                    | listed classes re-float on add_window | — |

## Verification (needs user's `fvwm3 -c 'Restart'`)

1. `bin/tile-floats list` with no state file -> `SetEnv TILE_FLOATS ""`.
2. Menu "Persistent float" on window X -> X floats, `.tile-floats` gains
   X's class, `fvwm3 -c 'Test …'` env shows it.
3. Close X, open same app -> auto-floats.
4. Win+Shift+Space on another window -> floats, file unchanged.
5. `fvwm3 -c Restart` -> app from step 3 still auto-floats.

## Risks

- `toggle` uses the pointer: a click on a frame's corner has the pointer
  over that frame; a degenerate over-root pointer falls back to the
  focused window.  Worst case = toggling the wrong class = one menu click
  to fix, state is editable in the file.
- Class granularity: all windows of the class float.  By design.
- `PipeRead` blocks fvwm briefly (Xlib startup) per window add and per
  menu use; same cost class as the existing `TileMasterWider` PipeRead.
