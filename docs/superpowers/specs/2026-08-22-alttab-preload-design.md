# fvwm-alttab preload daemon — design

Date: 2026-08-22
Status: approved for planning

## Problem

`bin/fvwm-alttab` is spawned fresh on every Alt+Tab. Measured on this machine,
~75ms elapses before the picker is on screen, and ~57ms of that is a fixed
startup cost paid before any useful work happens:

| phase | cost |
|---|---|
| perl interpreter start + module compile | ~20 ms |
| `use Gtk3 -init` (GI typelib load, X connect) | ~57 ms |
| `get_windows()` over the MFL socket | ~0.6 ms |
| `install_css` + `build_ui` | ~3 ms |
| `show_all` + `present` | ~15 ms |

The window enumeration and UI build are already negligible. Only the
interpreter and toolkit startup are worth attacking, and they can only be
attacked by not paying them per invocation.

## Goal

Keep a picker process resident so Alt+Tab reveals an already-built window.
Target ~30ms from keypress to visible, down from ~75ms.

Non-goal: changing how the picker looks or behaves once visible.

## Findings that shaped the design

All four were measured during design, not assumed.

1. **A preloaded window is as grabbable as a fresh one.** A throwaway spike
   revealed a realized-but-hidden GTK window 20 times per run, across three
   runs and two cadences (350ms visible / 250ms gap, and 120ms / 60ms):
   **60/60 reveals took focus and the keyboard grab**, averaging ~10ms to
   focus — matching or slightly beating a freshly created window (~12ms).
   This was the assumption that could have invalidated the whole design.

2. **Perl signal handlers run promptly inside `Gtk3->main`.** `Glib::Unix` is
   not available in this Glib (1.3294), so `signal_add` is out. Plain `%SIG`
   was measured at **0.1ms average / 0.2ms worst over 6/6 signals**, even with
   nothing else driving the loop — the signal's EINTR gives Perl its opcode
   boundary. No self-pipe, FIFO, or heartbeat timer is needed.

3. **`All (CurrentPage, !Iconic, AcceptsFocus)` returns correct MRU order.**
   Index 0 is the focused window, index 1 the previously focused one. Verified
   by focusing each of three windows in turn and re-querying. The daemon
   therefore does **not** need to maintain its own MRU stack, and
   `FVWM::Tracker::WindowList` is unnecessary.

4. **`SendToModule` is fork-free but has no liveness test.** FVWM offers no
   conditional for "is this module running", so a module-based design cannot
   fall back when the module is dead. This is what selected the daemon shape
   over making the picker an FVWM module.

5. **`FVWM_USERDIR` and `XDG_RUNTIME_DIR` both reach `Exec`'d children**
   (`/home/deer/.fvwm` and `/run/user/1000`), verified by printing them from a
   shell spawned via `Exec`. The trigger script depends on both.

## Architecture

Three files.

### `bin/fvwm-alttab` — gains `--daemon`

One file, two lifecycles. The one-shot path is left **behaviourally
unchanged**, because it is the fallback. UI construction, thumbnail loading,
key handling and commit logic are shared; splitting into two files would
duplicate ~200 lines and guarantee drift.

Daemon startup:

1. `acquire_lock` on `$RUN_DIR/fvwm-alttab-daemon.pid` — exit silently if a
   daemon already holds it, which makes relaunch idempotent.
2. Connect the MFL socket, send `set echo`.
3. Build the window shell and `$win->realize` — creates the X window without
   mapping it. This is the cost being amortised.
4. Install `$SIG{USR1}` (forward) and `$SIG{USR2}` (reverse).
5. `Gtk3->main`.

### `bin/alttab-trigger` — new, ~10 lines of `sh`

```sh
#!/bin/sh
PIDF="${XDG_RUNTIME_DIR:-/tmp}/fvwm-alttab-daemon.pid"
SIG=USR1; [ "$1" = "--reverse" ] && SIG=USR2
# read and kill are shell builtins: no extra fork, and a dead daemon costs nothing
if read -r pid < "$PIDF" 2>/dev/null && kill -"$SIG" "$pid" 2>/dev/null; then
    exit 0
fi
"$FVWM_USERDIR/bin/fvwm-alttab" --daemon &     # warm one for next time
exec "$FVWM_USERDIR/bin/fvwm-alttab" "$@"      # ...but switch NOW
```

The fallback is structural rather than bolted on: a failed signal costs two
builtins and falls straight through to the path that works today. Alt+Tab can
never silently do nothing — the failure mode this session found three separate
instances of.

The respawn is backgrounded so it cannot delay the switcher the user asked
for. If the daemon is permanently broken, each Alt+Tab costs one extra doomed
fork and the user gets today's behaviour: degraded, never broken.

### `config`

```
# StartFunction
+ I Exec exec $[FVWM_USERDIR]/bin/fvwm-alttab --daemon

# bindings
Silent Key Tab A M  Exec exec $[FVWM_USERDIR]/bin/alttab-trigger
Silent Key Tab A SM Exec exec $[FVWM_USERDIR]/bin/alttab-trigger --reverse
```

### Two lockfiles, not one

A real trap: today's single lock would make the one-shot fallback exit
silently whenever the daemon held it. The daemon uses
`fvwm-alttab-daemon.pid`; the one-shot keeps `fvwm-alttab.pid` for its
existing "don't stack two pickers" purpose.

## Reveal and hide

`reveal($direction)`:

1. If already visible, **advance the selection in `$direction`** instead of
   re-revealing (i.e. behave as a Tab press would). This is the "grab failed,
   so FVWM still sees Tab" path.
2. Refresh the window list over MFL (~0.6ms). If fewer than 2 windows, return
   without showing.
3. Rebuild the thumbnail row for the current window set.
4. `$SEL_IDX = $direction > 0 ? 1 : $#windows`.
5. Reset `$KBD_GRABBED = 0`.
6. Start the 150ms Alt-poll timer.
7. `highlight()`, `show_all`, `present`.

`hide_picker()`:

1. Ungrab the keyboard.
2. `$win->hide`.
3. `$KBD_GRABBED = 0`.
4. Stop the Alt-poll timer.
5. Drop the thumbnail row's children and pixbufs.

Commit sends `WindowId <wid> AltTabFocus` followed by `mfl_sync()`, then hides
rather than exiting.

### State that must reset between reveals

This is where the bug risk concentrates. Each item below has a matching
failure mode if missed:

| state | if not reset |
|---|---|
| `$KBD_GRABBED` | `focus-in` skips the re-grab; second Alt+Tab has no keyboard |
| the actual X keyboard grab | grab leaks; other clients starve |
| Alt-poll timer | keeps polling while hidden and commits into an invisible window |
| `$SEL_IDX` | selection starts at a stale index |
| thumbnail widgets | stale images, unbounded widget growth |

## Error handling

| condition | behaviour |
|---|---|
| MFL connect fails at daemon startup | daemon exits; trigger falls back to one-shot every time (which itself degrades to `FvwmCommand`) |
| MFL EOF later (`FvwmCommand Restart` kills FvwmMFL) | daemon exits cleanly and releases its lock; StartFunction's relaunch on restart takes over |
| fewer than 2 windows on reveal | ignore the signal, stay hidden |
| keyboard grab fails on reveal | unchanged from today: the repeating Alt poll commits on release |
| signal arrives while visible | advance selection |
| daemon dead | trigger execs the one-shot and backgrounds a fresh daemon |

Exiting on MFL EOF rather than reconnecting is a deliberate simplification: FVWM
already relaunches the daemon on restart, so reconnect logic would be a second
mechanism for something the first already handles.

## Testing

Reuse the harness built during the reliability work, plus daemon-specific cases:

1. Reveal reliability — focus and grab rate over 20+ reveals (spiked: 60/60).
2. Hold Alt: picker stays open; Tab advances; release commits to the advanced
   selection. Driven with `xdotool`, **without** `--clearmodifiers`, which
   releases Alt and invalidates the test.
3. Quick tap: Alt released during startup still commits, nothing stranded.
4. `kill -9` the daemon, then Alt+Tab: still switches (fallback), and a new
   daemon appears for the next invocation.
5. `FvwmCommand Restart`: old daemon exits, new one serves, no duplicates.
6. Latency: keypress to visible, expect ~30ms.
7. Leak check over many reveals: keyboard grab released, widget count stable,
   RSS stable.

Synthetic keyboard tests exercise the fallback paths hard but do not replace
interactive verification; the Alt-held path in particular needs real use.

## Deliberately omitted (YAGNI)

- `FVWM::Tracker::WindowList` MRU maintenance — the 0.6ms query is already
  correct (finding 3).
- Pixbuf caching across reveals — saves ~1ms per thumbnail and risks showing
  stale window contents.
- Pre-warming the grid after each hide — the map dominates reveal cost, so
  this would buy a few ms for real staleness risk.
- MFL reconnect logic — superseded by exit-and-relaunch.

## Expected outcome

~75ms → ~30ms per invocation, with the reveal itself measured at ~10ms to
focus and grab. The honest framing: this is a ~45ms improvement to an
operation that already works, and it adds a resident process to the session.
It is worth less than the correctness fixes that preceded it.
