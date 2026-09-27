#!/bin/sh
# Rebuild the FvwmPager background tile from the wallpaper.
#
# Colorsets 20/21 use TiledPixmap, so a tile cut to exactly one page cell
# repeats once per page. Called by bin/photon_pager.py before each pager
# launch, so shelf resizes, wallpaper changes and fvwm restarts all pick up
# a fresh tile; a no-op when the tile is already the right size.
#
# usage: mk-pager-bg.sh <wallpaper> <tile> <pages_x> <pages_y> <pager_w> <pager_h>
set -eu

src=$1 dest=$2 pages_x=$3 pages_y=$4 pager_w=$5 pager_h=$6

[ -f "$src" ] || exit 1
w=$((pager_w / pages_x))
h=$((pager_h / pages_y))
[ "$w" -gt 0 ] && [ "$h" -gt 0 ] || exit 1

if [ -f "$dest" ] && [ "$dest" -nt "$src" ] &&
   [ "$(magick identify -format '%wx%h' "$dest" 2>/dev/null)" = "${w}x${h}" ]; then
	exit 0
fi

mkdir -p "$(dirname "$dest")"
magick "$src" -resize "${w}x${h}^" -gravity center -extent "${w}x${h}" "$dest"
