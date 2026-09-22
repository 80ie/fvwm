# Media cover art — design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement
> this plan task-by-task. (Plan sections land after review.)

Status: design for review, 2026-09-21.  User amendments folded in: square
width-relative well (no hardcoded 150), World-View-style framing.

## Goal

Show the current track's cover art in the Media group of the sidebar, as a
square well framed like the reference's World View -- a dark bevelled border
and a grey channel around the image -- the visual centerpiece of the widget,
with the title field, transport buttons and volume sub-section below it.

The reference QNX shelf has **no** cover art (PANEL-DESIGN.md measured the CD
Player as title field + four buttons + volume, only). This feature is a
deliberate departure, not a restoration; everything the widget has in common
with the reference must stay as-is.

## Live evidence, why fetching is `file://` and `http(s)` only

`mpris:artUrl` was probed on the live session bus on 2026-09-21:

| Player | artUrl |
|---|---|
| strawberry | `file:///tmp/strawberry-cover-*.jpg` |
| kdeconnect (phone proxy) | `file:///home/deer/.cache/kdeconnect.daemon/kdeconnect/albumart/*.jpg` |
| spotify | `https://i.scdn.co/image/...` |
| firefox | no `artUrl` key |
| (any mpv via `mpv-mpris` style, e.g. mpd stacks) | `file://` temp file, per mpv-mpris's documented behaviour |

The opaque `coverart://` scheme used by `mpris-proxy` (installed here, not
running) has no standard client-side resolution in MPRIS 2.x; players are
expected to publish fetchable URIs. Decision: treat every scheme other than
`file`, `http`, `https` (and bare local paths) as *no art*. If mpris-proxy is
ever a regular player here, the gap will show as an absent well and the fix is
one scheme branch.

## Decisions

1. **Layout:** large square well, controls below (chosen over a thin top strip
   and over art-beside-controls).
2. **Square, width-relative:** the well is `W−8` by `W−8`, where `W` is the
   body's width. Not a hardcoded 150.
3. **Only when an actual image has loaded:** the well exists iff a fetch
   succeeded. No placeholder face, no loading state; the group collapses to
   its current 100px body otherwise (user chose space savings over a stable
   group height).
4. **Inline in `photon_media.py`:** no new file, no daemon (the pactl-
   subscription pattern was considered and rejected — it would duplicate
   player tracking and add a per-fvwm-Restart orphan process).
5. **No polling:** fetching is request/response, started by MPRIS state. The
   panel's "nothing polls" property holds.
6. **World-View framing:** the well is framed like the reference's World
   View (user request, 2026-09-21): a hard `#4b4b4b`-outlined trough with a
   `#8d8d8d` inner shadow along its top and left over a `#bcbcbc` channel --
   photon's meter-trough bevel, darker than the soft chrome or the `#f4f4f4`
   data-field well -- with the art ~4px inside the frame.

## Architecture

```
Mpris (exists)  ── PropertiesChanged/NameOwnerChanged ──►  art_url, trackid
      │
      ▼  _on_mpris forwards (service, trackid, art_url) on every change
CoverArt (new, same file)
      │  QNetworkAccessManager get (file/http/https only),
      │  8 s QTimer abort per request, decode capped at 1024px,
      │  LRU of 8 pixmaps keyed by URL
      ▼  changed()
MediaWidget (exists)
      │  repaints the well; flips body between the current
      │  NATURAL_H=100 layout and the art layout
      ▼  natural_height_changed()  (new signal on the widget)
shelf-panel (exists) — one line: pass the width through for it, as it
                       already does for WorldView
```

- `Mpris` gains `art_url` and `trackid`, set in `_apply()` under the same
  "only if the key is present" guards as `title`, cleared in `_clear()`.
- `CoverArt(QObject)`: `set_track(service, trackid, art_url)`; `changed`
  signal; `pixmap` property.
- `MediaWidget` gets the new well rect and `natural_height_changed` signal.
  `shelf-panel` already connects `natural_height_changed` on any body widget
  that has one (done for the tray) — the only panel change is the width-aware
  natural height, see *Geometry*.

## Geometry

`W` = body width = panel width − `FRAME_W` (7, right-docked) − `PAD_R` (3).

No art: layout byte-identical to today (`NATURAL_H = 100`).

With art:

```
r_art   = QRect(4, 4, W-8, W-8)          # the square well
divider = r_art.bottom() + GAP           # etched 2px, same rule as div_y
          everything below shifts by ART_BLOCK = (W-8) + 3 + 2 + 3 = W
r_title = (4, 4 + W, W-8, 19)            # interiors unchanged
buttons, div_y, volume, output           # unchanged, shifted by W
body height = 100 + W
```

| panel width | W | body with art | group (header + body + sep) |
|---|---|---|---|
| 110 (min) | 100 | 200 | 222 |
| 160 (default) | 150 | 250 | 272 |
| 420 (max) | 410 | 510 | 532 |

At max width the group claims half a 1080p screen; the Windows flex group
absorbs that, but the square-well-at-max-width consequence is noted so it is
not "discovered" later. Width steps (`Super+[` / `Super+]`) re-layout while
art is visible; the well tracks the new width and the group height follows.

`MediaWidget.natural_height(w)` returns `100 + w` with art, `100`
without. `sizeHint()` = `(SHELF_INNER, natural_height(SHELF_INNER))`, so the
standalone window sizes itself for art. In `shelf-panel._natural_height`,
the width-aware branch becomes `isinstance(widget, (WorldView, MediaWidget))`
(both already imported); the duck-typed `natural_height()` path is untouched.

Frame and paint: `photon.trough(p, r_art)` -- the bevel the World View sits
in: a hard `#4b4b4b` outline with a `#8d8d8d` shadow row and column along its
top and left, over a `#bcbcbc` channel.  The pixmap is centred 4px inside the
frame (`r_art.adjusted(4, 4, -4, -4)`), `KeepAspectRatio` +
`SmoothTransformation`.  Album art is square, so standard covers fill the
channel to near the border; anything else gets the letterbox on `#bcbcbc`.

## Fetching

- One path through `QNetworkAccessManager.get()`: `file://`, bare local
  paths, `http://`, `https://`. `QUrl(art_url).scheme()` is the gate;
  unresolvable schemes clear the art.
- 8-second per-request `QTimer` → `reply.abort()`. No retries, no disk cache.
- Decode through `QImageReader` with `setMaximumSize(1024, 1024)` before
  `QPixmap`, so a 4000px cover cannot balloon the panel.
- LRU of 8 decoded pixmaps keyed by URL: re-playing a track (same URL) swaps
  instantly with no network; the tray's `natural_height_changed` idiom and
  the file's existing "keep one current pixmap, coalesce writes" habits make
  a disk cache unneeded.
- No child processes: `Sink`'s reaping docstring exists because `pactl
  subscribe` outlives restarts; `CoverArt` has nothing to reap.

## Failure and race semantics

- Every request is tagged with the `(service, trackid)` it was made for. A
  reply arriving after the state has moved on is dropped, so a slow
  track-B image never paints under track C.
- A *failed* fetch does not clear the well: the last successfully loaded
  artwork stays up (no flash, no collapse/expand churn on a bad URL), and the
  same URL is simply re-requested if it appears again (failures are not
  cached).
- The well clears only when the *source* says absent: no selected player, no
  `artUrl` in `Metadata`, or an unresolvable scheme. Player handover to
  firefox (no art) closes it.
- Track A→B, both with art: the well never vanishes between tracks; the
  pixmap swaps in one repaint when B's image lands (A's art is held meanwhile,
  at most a second for a spotify track over a good connection; `file://` art
  lands in the same frame).
- Group collapsed: fetches continue (state lives in `Mpris`, which outlives
  the body's visibility); nothing special.

## What does not change

- Transport buttons, marquee title, volume slider, output combobox: untouched
  geometry and behaviour.
- No new polling; the only new timer is the per-request abort.
- `photon.py`: untouched (`trough` already exists). `media-album-cover`
  placeholder icon: not needed (decision 3 removed the placeholder face).

## Documentation updates

- `bin/photon_media.py` docstring: "MPRIS transport and sink volume" gains the
  art clause; "Nothing here polls" stays true and gains one sentence on the
  request/response fetching.
- `CLAUDE.md`: the `photon_media.py` table row and the "Almost nothing polls"
  paragraph each gain a line.
- `PANEL-DESIGN.md`: a short addendum — the reference has no art (deliberate
  departure), the live `file://`/`https://` probe, and the decisions list.

## Verification

No test system exists in this repo (AGENTS.md), so verification is the widget
itself:

1. `python3 -m py_compile bin/photon_media.py` and a run through
   `python3 -m ruff check bin/photon_media.py` (repo already has a
   `.ruff_cache`).
2. Standalone: `python3 bin/photon_media.py` while strawberry plays a track
   (art appears, square well), then spotify (network art within ~1 s), then
   stop all players (well gone, body back to 100px).
3. Live panel after `FvwmCommand Restart`: switch between the three live
   MPRIS players (strawberry, spotify, the art-less firefox track), step the
   shelf width with art visible, collapse and re-expand the Media group.
   Confirm the frame reads like the World View trough next to it: dark
   outline, grey channel, art not touching the border.
4. Regression by eye: marquee scrolls, transport clicks, volume drag, output
   combobox.

No permanent test files are added.
