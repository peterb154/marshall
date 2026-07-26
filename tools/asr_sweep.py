"""Fly a thousand-odd approaches through the engine and report what happened.

The geometry is the part that cannot be tested by talking to it. A vectoring
rule that looks right in one position is wrong in another, and the failure is
never a crash -- it is an aeroplane that arrives late, or turns the wrong way
once, or converges beautifully from the north and orbits forever from the
south-east. Reading the code does not find that. Flying it from every direction
does.

    uv run python tools/asr_sweep.py            # the sweep, one line of verdict
    uv run python tools/asr_sweep.py --verbose  # every start that failed

The aeroplane is a point that turns at three degrees a second and holds the
heading it is given, which is generous -- no overshoot, no wind, no lag. That is
deliberate: anything this model cannot fly, a real one certainly cannot, so a
failure here is a real failure while a pass here is only permission to try it in
the sim (`tools/asr_autopilot.py`) and then on a person.

What it measures, and why each one:

  arrived        reached the missed approach point. Anything less is an
                 aircraft the controller lost.
  established    range at which it settled on the final approach course. The
                 approach is meant to be flown established; arriving at the
                 point having just rolled out is arriving unstabilised.
  reversals      times the instruction flipped left/right. This is the number
                 that matters most, because it is the one a pilot hears as two
                 controllers arguing, and it is what three separate "fixes"
                 made worse before the geometry was left alone.

Run it before and after ANY change to asr.py or geometry.py, and compare all
three. A change that improves one and quietly wrecks another has happened, more
than once, in this file's history.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc import asr                                  # noqa: E402
from marshall.atc import geometry as G                        # noqa: E402
from marshall.core import route as R                          # noqa: E402

STEP_SEC = 5.0
TURN_RATE_DEG = 3.0            # standard rate, and all a heavy fighter will give
SPEED_MPH = 200.0              # what a P-47 flies an approach at
MAX_MINUTES = 25.0


def fly(range_nm: float, radial_deg: float, heading_deg: float, profile) -> dict:
    """One approach, from one start, until it arrives or runs out of fuel."""
    speed_nm_s = SPEED_MPH / 3600.0 * 0.868      # mph -> knots -> nm/sec
    pos = asr.Position(range_nm=range_nm, radial_deg=radial_deg,
                       alt_ft=profile.hold_base_ft, heading_deg=heading_deg)
    steps = int(MAX_MINUTES * 60 / STEP_SEC)
    last_turn, reversals, established_at = "", 0, None

    for _ in range(steps):
        g = asr.guide(pos, profile)
        if g.turn in ("left", "right"):
            if last_turn and g.turn != last_turn:
                reversals += 1
            last_turn = g.turn
        if established_at is None and g.phase in ("final", "map"):
            established_at = pos.range_nm
        if g.phase == "map":
            return {"arrived": True, "minutes": _ * STEP_SEC / 60,
                    "established": established_at, "reversals": reversals}

        # Turn towards the ordered heading at standard rate, then move.
        err = G.angle_diff(g.heading, pos.heading_deg)
        turn = max(-TURN_RATE_DEG * STEP_SEC, min(TURN_RATE_DEG * STEP_SEC, err))
        hdg = (pos.heading_deg + turn) % 360
        # Position in miles north/east of the field, advanced along the heading.
        north = pos.range_nm * math.cos(math.radians(pos.radial_deg))
        east = pos.range_nm * math.sin(math.radians(pos.radial_deg))
        d = speed_nm_s * STEP_SEC
        north += d * math.cos(math.radians(hdg))
        east += d * math.sin(math.radians(hdg))
        rng = math.hypot(north, east)
        pos = asr.Position(range_nm=rng,
                           radial_deg=math.degrees(math.atan2(east, north)) % 360,
                           alt_ft=g.altitude_ft, heading_deg=hdg)

    return {"arrived": False, "minutes": MAX_MINUTES, "established": None,
            "reversals": reversals}


def sweep(profile) -> tuple[list[dict], int]:
    ranges = [8, 12, 16, 20, 25, 30]
    radials = range(0, 360, 20)              # 18
    headings = range(0, 360, 30)             # 12
    out = []
    for rng in ranges:
        for rad in radials:
            for hdg in headings:
                r = fly(rng, rad, hdg, profile)
                r["start"] = (rng, rad, hdg)
                out.append(r)
    return out, len(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true",
                    help="list every start that never arrived")
    args = ap.parse_args()

    profile = R.BATUMI_ASR
    results, total = sweep(profile)
    arrived = [r for r in results if r["arrived"]]
    est = [r["established"] for r in arrived if r["established"]]
    rev = sum(r["reversals"] for r in results)
    dithering = [r for r in results if r["reversals"] >= 3]

    print(f"{len(arrived)}/{total} arrived at the missed approach point")
    if est:
        print(f"  established   median {statistics.median(est):.1f} nm, "
              f"worst {min(est):.1f} nm")
    print(f"  reversals     {rev} total, {len(dithering)} approaches dithered "
          f"(3 or more)")
    if arrived:
        mins = [r["minutes"] for r in arrived]
        print(f"  time          median {statistics.median(mins):.1f} min, "
              f"worst {max(mins):.1f} min")

    lost = [r for r in results if not r["arrived"]]
    if lost:
        print(f"  NEVER ARRIVED {len(lost)}")
        show = lost if args.verbose else lost[:10]
        for r in show:
            rng, rad, hdg = r["start"]
            print(f"     {rng:2d} nm on the {rad:03d} radial, heading {hdg:03d}")
        if not args.verbose and len(lost) > len(show):
            print(f"     ... and {len(lost) - len(show)} more (--verbose)")
    return 0 if not lost else 1


if __name__ == "__main__":
    raise SystemExit(main())
