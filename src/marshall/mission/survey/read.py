"""Read the terrain survey back out of dcs.log and turn it into design numbers.

Prints an ASCII relief map plus the things a procedure actually needs: the
highest ground inside each sector and ring, which is what minimum safe altitudes
are built from.
"""

import math
import re
import sys
from pathlib import Path

from marshall import config
LOG = config.DCS_LOGS / "dcs.log"
FT = 3.28084
NM = 1852.0

# re.M matters: without it "$" only anchors at the end of the whole log and no
# row ever matches.
ROW = re.compile(r"\[SURVEY\] row x=([-\d.]+) z0=([-\d.]+) dz=([\d.]+) ([\d,]+)$",
                 re.M)
BEGIN = re.compile(r"\[SURVEY\] begin centre x=([-\d.]+) z=([-\d.]+) "
                   r"radius=([\d.]+)nm step=([\d.]+)nm")

# Coarse shading; the point is to see where the ground is, not to be pretty.
def glyph(ft: float) -> str:
    for limit, ch in ((0, "."), (500, ":"), (1500, "-"), (3000, "="),
                      (5000, "*"), (8000, "#")):
        if ft <= limit:
            return ch
    return "@"


def main() -> int:
    log = (Path(sys.argv[1]) if len(sys.argv) > 1 else LOG)
    if not log.exists():
        print(f"no log at {log}")
        return 1
    text = log.read_text(encoding="utf-8", errors="ignore")

    starts = list(BEGIN.finditer(text))
    if not starts:
        print("No [SURVEY] data in the log -- has the survey mission been run?")
        return 1
    last = starts[-1]
    cx, cz, radius, step = (float(last.group(1)), float(last.group(2)),
                            float(last.group(3)), float(last.group(4)))

    rows = []
    for m in ROW.finditer(text[last.end():]):
        x, z0, dz = float(m.group(1)), float(m.group(2)), float(m.group(3))
        heights = [int(v) for v in m.group(4).split(",")]
        rows.append((x, z0, dz, heights))
    if not rows:
        print("Survey started but produced no rows.")
        return 1

    print(f"centre x={cx:.0f} z={cz:.0f}  {radius:.0f} nm radius, "
          f"{step:.1f} nm grid, {len(rows)} rows\n")

    # x increases north, so print north at the top.
    print("      " + "west".ljust(len(rows[0][3]) // 2) + "east")
    for x, _z0, _dz, heights in sorted(rows, key=lambda r: -r[0]):
        nm_ns = (x - cx) / NM
        line = "".join(glyph(h * FT) for h in heights)
        print(f"{nm_ns:+5.0f} {line}")
    print("\n  . sea/flat   : <500ft   - <1500   = <3000   * <5000   # <8000   @ higher\n")

    # Highest ground per quadrant and per ring -- the MSA inputs.
    quads = {"NE": 0.0, "SE": 0.0, "SW": 0.0, "NW": 0.0}
    rings: dict[int, float] = {}
    for x, z0, dz, heights in rows:
        for i, h in enumerate(heights):
            z = z0 + i * dz
            dn, de = (x - cx) / NM, (z - cz) / NM
            dist = math.hypot(dn, de)
            if dist > radius:
                continue
            q = ("N" if dn >= 0 else "S") + ("E" if de >= 0 else "W")
            q = {"NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW"}[q]
            quads[q] = max(quads[q], h * FT)
            ring = int(dist // 5) * 5
            rings[ring] = max(rings.get(ring, 0.0), h * FT)

    print("Highest terrain by quadrant (MSA = this + 1000 ft, rounded up):")
    for q in ("NE", "SE", "SW", "NW"):
        msa = math.ceil((quads[q] + 1000) / 100) * 100
        print(f"  {q}  {quads[q]:6.0f} ft   ->  MSA {msa:5.0f} ft")

    print("\nHighest terrain by distance ring:")
    for r in sorted(rings):
        print(f"  {r:2d}-{r+5:2d} nm  {rings[r]:6.0f} ft")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
