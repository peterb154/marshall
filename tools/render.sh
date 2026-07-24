#!/usr/bin/env bash
# Screenshot a kneeboard page with headless Windows Edge, so the layout can be
# inspected without a human copy/pasting.  Runs from WSL, drives the Windows
# browser, reads the PNG back.
#
#   ./render.sh navlog.html            # kneeboard-shaped (768x1024)
#   ./render.sh plate-batumi.html 800 1400
#
# Output: shots/<name>.png next to this script.

set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
file="${1:?usage: render.sh <html-file> [width] [height]}"
w="${2:-768}"
h="${3:-1024}"

mkdir -p "$here/shots"
name="$(basename "$file" .html)"
out="$here/shots/$name.png"

# Edge needs a Windows path. Resolve the file's location on the C:/D: drive.
winpath="$(wslpath -w "$here/$file")"
winout="$(wslpath -w "$out")"

edge="/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

# --headless=new gives a real screenshot; force the window size so the shot is
# the kneeboard's aspect, not the desktop's.
"$edge" \
  --headless=new \
  --disable-gpu \
  --hide-scrollbars \
  --force-device-scale-factor=1 \
  --window-size="${w},${h}" \
  --screenshot="$winout" \
  "file:///${winpath//\\//}" \
  >/dev/null 2>&1 || true

# Edge writes asynchronously; wait briefly for the file.
for _ in $(seq 1 20); do
  [ -s "$out" ] && break
  sleep 0.3
done

if [ -s "$out" ]; then
  echo "$out ($(stat -c%s "$out") bytes, ${w}x${h})"
else
  echo "FAILED: no screenshot written" >&2
  exit 1
fi
