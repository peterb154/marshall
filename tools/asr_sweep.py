"""Fly a thousand-odd approaches through the engine and report what happened.

The geometry is the part that cannot be tested by talking to it. A vectoring
rule that looks right in one position is wrong in another, and the failure is
never a crash -- it is an aeroplane that arrives late, or turns the wrong way
once, or converges beautifully from the north and orbits forever from the
south-east. Reading the code does not find that. Flying it from every direction
does.

    uv run python tools/asr_sweep.py            # the sweep, one line of verdict
    uv run python tools/asr_sweep.py --verbose  # every start that failed

The aeroplane is a point that turns at three degrees a second. By default it
holds the heading it is given, which is generous -- no overshoot, no wind, no
lag -- so anything it cannot fly, a real one certainly cannot.

    --sloppy    a pilot who lags, overshoots and drifts

That flag is not decoration. A perfect pilot only ever visits positions the
ENGINE chose, so the engine cannot be caught disagreeing with itself about a
position it did not expect -- and every reversal a real pilot has reported came
from exactly there. Run both: the clean sweep proves the geometry converges, the
sloppy one proves it does not argue with itself on the way.

What it measures, and why each one:

  arrived        reached the missed approach point. Anything less is an
                 aircraft the controller lost.
  established    range at which it settled on the final approach course. The
                 approach is meant to be flown established; arriving at the
                 point having just rolled out is arriving unstabilised.
  dithering      reversals that arrive in QUICK SUCCESSION -- the instruction
                 flipping left/right/left inside half a minute. This is what a
                 pilot hears as two controllers arguing, and it is the number
                 that matters.

  turns          every direction change, dithering included. Read it for
                 context, never as a score: about one per approach is the
                 aircraft reaching the entry gate and rolling onto the 45,
                 which is the manoeuvre working. Ninety per cent of this
                 count was that single correct turn, and judging two attempted
                 fixes by it produced two confident wrong answers.

Run it before and after ANY change to asr.py or geometry.py, and compare all
three. A change that improves one and quietly wrecks another has happened, more
than once, in this file's history.
"""

from __future__ import annotations

import argparse
import math
import random
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
# An aeroplane does not change height in one radar sweep, and pretending it does
# is not a harmless simplification. It made the missed approach -- climb to
# three thousand -- complete in a single step, so the aircraft was instantly at
# the altitude that ENDS the procedure while still sitting over the field, and
# the resulting churn was scored as dithering the engine was not doing.
CLIMB_FPM = 1000.0
DESCEND_FPM = 700.0


def fly(range_nm: float, radial_deg: float, heading_deg: float, profile,
        sloppy: bool = False, seed: int = 0) -> dict:
    """One approach, from one start, until it arrives or runs out of fuel."""
    rnd = random.Random(seed)              # seeded: a failure must be repeatable
    speed_nm_s = SPEED_MPH / 3600.0 * 0.868      # mph -> knots -> nm/sec
    pos = asr.Position(range_nm=range_nm, radial_deg=radial_deg,
                       alt_ft=profile.hold_base_ft, heading_deg=heading_deg)
    steps = int(MAX_MINUTES * 60 / STEP_SEC)
    last_turn, established_at = "", None
    turns = 0
    dither = 0
    last_turn_step = None
    # Two reversals inside this many seconds is not a manoeuvre, it is an
    # argument. A gate turn is isolated; dithering comes in bursts.
    DITHER_WINDOW = 30.0

    on_missed = False          # the caller's latch, exactly as the bridge holds it
    for _ in range(steps):
        g = asr.guide(pos, profile, on_missed=on_missed)
        if g.phase == "missed":
            on_missed = True
        elif pos.alt_ft >= profile.missed_climb_ft:
            on_missed = False          # procedure complete; he is ours again
        if g.turn in ("left", "right"):
            if last_turn and g.turn != last_turn:
                turns += 1
                if (last_turn_step is not None
                        and (_ - last_turn_step) * STEP_SEC <= DITHER_WINDOW):
                    dither += 1
                last_turn_step = _
            last_turn = g.turn
        if established_at is None and g.phase in ("final", "map"):
            established_at = pos.range_nm
        if g.phase == "map":
            return {"arrived": True, "minutes": _ * STEP_SEC / 60,
                    "established": established_at, "turns": turns,
                    "dither": dither}

        # Turn towards the ordered heading at standard rate, then move.
        err = G.angle_diff(g.heading, pos.heading_deg)
        turn = max(-TURN_RATE_DEG * STEP_SEC, min(TURN_RATE_DEG * STEP_SEC, err))
        if sloppy:
            # What a person actually does with a heading: hears it a beat late,
            # rolls out past it, and wanders a degree or two in between. None of
            # this is large. It does not need to be -- it only has to put the
            # aeroplane somewhere the engine did not put it.
            if rnd.random() < 0.25:
                turn = 0.0                          # still reaching for the dial
            elif abs(err) > 20:
                turn *= 1.0 + rnd.uniform(0.0, 0.25)     # rolls out late
            hdg = (pos.heading_deg + turn + rnd.uniform(-2.0, 2.0)) % 360
        else:
            hdg = (pos.heading_deg + turn) % 360
        # Position in miles north/east of the field, advanced along the heading.
        north = pos.range_nm * math.cos(math.radians(pos.radial_deg))
        east = pos.range_nm * math.sin(math.radians(pos.radial_deg))
        d = speed_nm_s * STEP_SEC
        north += d * math.cos(math.radians(hdg))
        east += d * math.sin(math.radians(hdg))
        rng = math.hypot(north, east)
        want = g.altitude_ft or pos.alt_ft
        rate = CLIMB_FPM if want > pos.alt_ft else DESCEND_FPM
        step_ft = rate * (STEP_SEC / 60.0)
        alt = (min(want, pos.alt_ft + step_ft) if want > pos.alt_ft
               else max(want, pos.alt_ft - step_ft))
        pos = asr.Position(range_nm=rng,
                           radial_deg=math.degrees(math.atan2(east, north)) % 360,
                           alt_ft=alt, heading_deg=hdg)

    return {"arrived": False, "minutes": MAX_MINUTES, "established": None,
            "turns": turns, "dither": dither}


def sweep(profile, sloppy: bool = False) -> tuple[list[dict], int]:
    ranges = [8, 12, 16, 20, 25, 30]
    radials = range(0, 360, 20)              # 18
    headings = range(0, 360, 30)             # 12
    out = []
    for rng in ranges:
        for rad in radials:
            for hdg in headings:
                r = fly(rng, rad, hdg, profile, sloppy=sloppy,
                        seed=rng * 100000 + rad * 100 + hdg)
                r["start"] = (rng, rad, hdg)
                out.append(r)
    return out, len(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sloppy", action="store_true",
                    help="fly it with a pilot who lags, overshoots and drifts")
    ap.add_argument("--verbose", action="store_true",
                    help="list every start that never arrived")
    args = ap.parse_args()

    profile = R.BATUMI_ASR
    results, total = sweep(profile, sloppy=args.sloppy)
    arrived = [r for r in results if r["arrived"]]
    est = [r["established"] for r in arrived if r["established"]]
    turns = sum(r["turns"] for r in results)
    dither = sum(r["dither"] for r in results)
    dithering = [r for r in results if r["dither"] >= 2]

    print(f"{len(arrived)}/{total} arrived at the missed approach point")
    if est:
        print(f"  established   median {statistics.median(est):.1f} nm, "
              f"worst {min(est):.1f} nm")
    print(f"  DITHERING     {dither} rapid flips, on {len(dithering)} approaches")
    print(f"  turns         {turns} direction changes in all "
          f"({turns / max(1, total):.2f} per approach; ~1 is the gate turn)")
    if arrived:
        mins = [r["minutes"] for r in arrived]
        print(f"  time          median {statistics.median(mins):.1f} min, "
              f"worst {max(mins):.1f} min")

    if dithering:
        print("  the approaches that argued with themselves:")
        for r in sorted(dithering, key=lambda d: -d["dither"])[:8]:
            rng, rad, hdg = r["start"]
            print(f"     {r['dither']:3d} flips  from {rng:2d} nm on the "
                  f"{rad:03d} radial, heading {hdg:03d}")

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
