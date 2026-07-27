"""Audit the plate's plan view without a human looking at it.

Design-agnostic: it does not know where the hold or the beacon should be, only
that nothing may run off the canvas or print on top of another label. The
geometry itself I now verify by rendering to PNG (render.sh) and looking, which
catches the things a bounds check never will -- a hold drawn over land, an arrow
pointing the wrong way.

    uv run python check_plate.py
"""

import re
import sys

from marshall.kneeboard import plate as P

svg = P.plan_view()
problems: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + msg)
    if not ok:
        problems.append(msg)


print(f"plan view {P.W} x {P.H}\n")

# Labels: estimate each one's box and flag anything off-canvas or overlapping.
rows = []
for m in re.finditer(
        r'<text class="m" x="([-\d.]+)" y="([-\d.]+)"[^>]*?'
        r'(?:font-size="(\d+)")?[^>]*?>(.*?)</text>', svg, re.S):
    x, y = float(m.group(1)), float(m.group(2))
    fs = int(m.group(3) or 10)
    txt = " ".join(m.group(4).split())
    visible = re.sub(r"&\w+;", "*", txt)          # entities are one glyph
    w = len(visible) * fs * 0.6
    anchor = "start"
    tag = svg[m.start():m.end()]
    if 'text-anchor="middle"' in tag:
        anchor, x = "middle", x - w / 2
    elif 'text-anchor="end"' in tag:
        anchor, x = "end", x - w
    rows.append((x, y, w, fs, txt))

print("labels")
for x, y, w, fs, txt in rows:
    check(x >= 0 and x + w <= P.W and fs <= y <= P.H,
          f"{txt[:32]!r} within canvas (x {x:.0f}..{x + w:.0f})")

overlaps = []
for i, a in enumerate(rows):
    for b in rows[i + 1:]:
        if abs(a[1] - b[1]) < max(a[3], b[3]) * 0.9 \
                and a[0] < b[0] + b[2] and b[0] < a[0] + a[2]:
            overlaps.append((a[4][:20], b[4][:20]))
print("\ncollisions")
check(not overlaps, f"no overlapping labels{'' if not overlaps else f' -- {overlaps}'}")

# The one geometric invariant worth asserting: the beacon and the inbound course
# start are both on the canvas, and the fix is up-and-left of the field (inbound
# on 130 must come from the north-west).
print("\ngeometry")
app = P.pt(P.FINAL_CRS - 180, 15.0)
check(app[0] < P.CX and app[1] < P.CY,
      f"final approach begins NW of the field ({app[0]:.0f},{app[1]:.0f})")
check(0 <= P.CX <= P.W and 0 <= P.CY <= P.H, "beacon on canvas")

print()
if problems:
    print(f"{len(problems)} problem(s)")
    sys.exit(1)
print("plan view passes bounds + collision check "
      "(look at the render for geometry)")
