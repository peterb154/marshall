#!/usr/bin/env bash
# Screenshot a kneeboard page, so a layout can be inspected without a human
# copy/pasting.  Picks a backend automatically:
#
#   * Linux (the LXC): a one-shot headless-chromium container, marshall-render,
#     built from deploy/render.Dockerfile.  No browser on the host; the ~250
#     chromium packages stay in the image.  Builds the image on first use.
#   * WSL (the gaming rig): the Windows Edge install, driven headless.
#
# Takes a local HTML file OR a served URL (the Linux backend can reach the
# kneeboard on the host via --network host):
#
#   ./render.sh navlog.html                        # local file, kneeboard-shaped
#   ./render.sh plate-batumi.html 800 1400         # ...with an explicit size
#   ./render.sh http://localhost:8362/ 800 1400    # the live served page
#
# A local file may be given relative to the caller, relative to this script, or
# absolute.  Output: shots/<name>.png next to this script.

set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
target="${1:?usage: render.sh <html-file|url> [width] [height]}"
w="${2:-768}"
h="${3:-1024}"
mkdir -p "$here/shots"

# --- resolve the target into (name, and either a URL or a real file path) ---
case "$target" in
  http://*|https://*)
    url="$target"
    base="$(basename "${target%%\?*}")"
    name="${base%.html}"; [ -n "$name" ] || name="index"
    ;;
  *)
    if [ -f "$target" ]; then
      srcfile="$(cd "$(dirname "$target")" && pwd)/$(basename "$target")"
    elif [ -f "$here/$target" ]; then
      srcfile="$here/$target"
    else
      echo "FAILED: no such file: $target" >&2; exit 1
    fi
    name="$(basename "$srcfile" .html)"
    ;;
esac

# A URL-derived name can carry ':' or '/'; keep the file portable.
name="$(printf '%s' "$name" | tr '/:' '__')"
out="$here/shots/$name.png"

# Common flags across both browsers: a real headless screenshot at the given
# window size (so the shot is the kneeboard's aspect, not the desktop's).
# --virtual-time-budget IS LOAD-BEARING for anything that fetches.
#
# `--screenshot` captures at the LOAD EVENT. The kneeboard's charts are static
# HTML and looked fine; /file builds its board from `fetch('/plans')` AFTER
# load, so the shot came back with a header, an import box, and nothing else --
# and read exactly like a broken page. It was a broken screenshot.
#
# The flag makes headless Chromium run its clock forward until the budget is
# spent or the page goes idle, so async work lands before the frame is taken.
# Two seconds is far more than a localhost fetch needs and costs nothing when
# the page has none.
common=( --headless=new --disable-gpu --hide-scrollbars
         --virtual-time-budget="${VTB:-2000}"
         --force-device-scale-factor=1 --window-size="${w},${h}" )

is_wsl() { grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; }
edge="/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

if is_wsl && [ -x "$edge" ]; then
  # --- WSL / Windows Edge backend (Edge needs Windows paths) ---
  winout="$(wslpath -w "$out")"
  if [ -n "${url:-}" ]; then
    src="$url"
  else
    winpath="$(wslpath -w "$srcfile")"
    src="file:///${winpath//\\//}"
  fi
  "$edge" "${common[@]}" --screenshot="$winout" "$src" >/dev/null 2>&1 || true
else
  # --- Linux / headless-chromium container backend ---
  docker image inspect marshall-render >/dev/null 2>&1 \
    || docker build -t marshall-render -f "$repo/deploy/render.Dockerfile" "$repo/deploy" >/dev/null
  # --no-sandbox: chromium runs as root in the container.
  # --disable-dev-shm-usage: the default /dev/shm is tiny and crashes chromium.
  cflags=( "${common[@]}" --no-sandbox --disable-dev-shm-usage )
  if [ -n "${url:-}" ]; then
    # --network host so a localhost URL reaches the kneeboard published on the host.
    docker run --rm --network host -v "$here/shots:/out" marshall-render \
      "${cflags[@]}" --screenshot="/out/$name.png" "$url" >/dev/null 2>&1 || true
  else
    # Mount the file's own directory read-only; render it as file:///work/<file>.
    src_dir="$(dirname "$srcfile")"
    docker run --rm -v "$src_dir:/work:ro" -v "$here/shots:/out" marshall-render \
      "${cflags[@]}" --screenshot="/out/$name.png" "file:///work/$(basename "$srcfile")" \
      >/dev/null 2>&1 || true
  fi
fi

# Both browsers write asynchronously; wait briefly for the file.
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
