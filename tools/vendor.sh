#!/usr/bin/env bash
# Fetch the third-party assets the document pages serve from disk.
#
# Only mermaid, and only because the kneeboard is a LAN thing: OpenKneeboard's
# embedded Chromium cannot be assumed to reach a CDN, and a diagram that
# silently fails to draw looks exactly like a diagram nobody wrote. The pages
# fall back to the CDN and say so in the corner when this has not been run.
#
# Lands in build/vendor/, which is gitignored -- 3.4 MB of minified JavaScript
# has no business in a repo whose whole point is that the ATC brain is readable.
#
#     tools/vendor.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build/vendor"
MERMAID_VERSION="11"
URL="https://cdn.jsdelivr.net/npm/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js"

mkdir -p "$DIR"
echo "fetching mermaid ${MERMAID_VERSION} -> ${DIR}/mermaid.min.js"
curl -sSLf --max-time 120 -o "${DIR}/mermaid.min.js.part" "$URL"

# Refuse a truncated or error-page download rather than serving one: a 4 KB
# "not found" page named mermaid.min.js breaks every diagram with no clue why.
size=$(wc -c < "${DIR}/mermaid.min.js.part")
if [ "$size" -lt 500000 ]; then
    rm -f "${DIR}/mermaid.min.js.part"
    echo "!! got ${size} bytes, which is not mermaid. Left the old copy alone." >&2
    exit 1
fi
mv "${DIR}/mermaid.min.js.part" "${DIR}/mermaid.min.js"
echo "ok, $(( size / 1024 )) KB"
