"""Which side of the final approach course is he ACTUALLY on?

#35, and the reason it needs a tool rather than a pilot's opinion: asked which
side of the centreline he was on, Hoover could only answer by looking out of the
window, backed by a directional gyro that drifts and a wet compass that read
sixteen degrees off the map. Neither instrument can settle an argument about a
quarter of a mile.

Radar can. This samples the track and prints, every few seconds, the ONE thing
under test:

    range, and which side of the course he is on, computed from position alone

Run it beside the bridge log while he flies an approach. Every time the
controller says "two miles left of course", this says what was true at that
moment, and the two either agree or they do not.

    uv run python tools/course_check.py                 # follow whoever is up
    uv run python tools/course_check.py --callsign "Hammer 1-3"

Position only, deliberately. His HEADING is not part of the question and is the
one number his instruments disagree about -- the side of a line you are standing
on does not depend on which way you are facing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc import asr
from marshall.atc.geometry import Position
from marshall.core import route as R

SQL = """
SELECT t.label, t.name,
       ST_Distance(f.g, t.geog)/1852.0,
       degrees(ST_Azimuth(f.g, t.geog)),
       t.alt_ft, t.heading
  FROM tracks t,
       (SELECT ST_MakePoint(lon, lat)::geography AS g FROM fixes WHERE name='batumi') f
 WHERE t.last_seen > now() - interval '30 seconds'
   AND t.type NOT LIKE 'AAA%' AND t.alt_ft IS NOT NULL
 ORDER BY ST_Distance(f.g, t.geog)
"""


def sample(callsign: str | None) -> list[tuple]:
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "strands",
         "-d", "strands", "-tAF", "|", "-c", SQL],
        cwd=ROOT / "services", capture_output=True, text=True)
    rows = []
    for line in out.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 6:
            continue
        label, name, nm, rad, alt, hdg = parts[:6]
        if callsign and callsign.lower() not in (name.lower(), label.lower()):
            continue
        try:
            rows.append((name or label, float(nm), float(rad), float(alt),
                         float(hdg or 0)))
        except ValueError:
            continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--callsign", default=None)
    ap.add_argument("--every", type=float, default=5.0)
    args = ap.parse_args()

    p = R.BATUMI_ASR
    print(f"final approach course {p.final_crs}M / {p.final_crs_true:.0f}T at "
          f"{p.aerodrome.name}\n")
    print(f"{'aircraft':12} {'rng':>6} {'radial':>7} {'alt':>6} "
          f"{'xtk':>7}  TRUTH{'':14} what he should be told")
    last = ""
    while True:
        for name, nm, rad, alt, hdg in sample(args.callsign):
            g = asr.guide(Position(nm, rad, int(alt), hdg), p)
            # The side, from POSITION alone -- no heading, no instruments.
            side = ("on course" if abs(g.xtk_nm) <= 0.3
                    else "RIGHT of course" if g.xtk_nm > 0 else "LEFT of course")
            line = (f"{name:12} {nm:6.1f} {rad:7.1f} {alt:6.0f} "
                    f"{g.xtk_nm:+7.2f}  {side:19} "
                    f"{g.deviation or '(not inbound)'}")
            if line[:40] != last[:40]:
                print(line, flush=True)
            last = line
        time.sleep(args.every)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped")
