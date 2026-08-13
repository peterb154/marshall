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

from marshall.atc import asr
from marshall.atc import geometry as G

STEP_SEC = 5.0
TURN_RATE_DEG = 3.0            # standard rate, and all a heavy fighter will give
SPEED_MPH = 200.0              # what a P-47 flies an approach at

# THE SWEEP ONLY EVER FLEW A WARBIRD. 1,296 approaches, every one of them at
# 200 mph, because that is what this field was built around -- so the base-leg
# geometry has never once been exercised at jet speed, which is exactly where
# #39 lives. A green sweep meant "correct for a P-47" and was read as "correct".
#
# TURN RATE IS NOT A CONSTANT EITHER, and pretending it is hides the whole
# problem. Standard rate is 3 degrees a second, but holding it needs bank that
# grows with speed, and past about 250 knots that bank is no longer something
# anybody flies on an approach. The usual limit is 30 degrees, which gives
#
#     rate = 1091 * tan(bank) / V     ~= 630 / V  at 30 degrees of bank
#
# 4.2 deg/s at 150 knots (so standard rate is comfortably available), 2.1 at
# 300, and 1.4 at 450 -- a turn radius near three miles, which is wider than
# the base leg it is being asked to turn inside.
MAX_BANK_DEG = 30.0


def turn_rate_deg_s(speed_kt: float) -> float:
    """The best rate this speed can actually give, in a bank a pilot will hold."""
    import math as _m
    if speed_kt <= 0:
        return TURN_RATE_DEG
    return min(TURN_RATE_DEG, 1091.0 * _m.tan(_m.radians(MAX_BANK_DEG)) / speed_kt)
MAX_MINUTES = 25.0
# An aeroplane does not change height in one radar sweep, and pretending it does
# is not a harmless simplification. It made the missed approach -- climb to
# three thousand -- complete in a single step, so the aircraft was instantly at
# the altitude that ENDS the procedure while still sitting over the field, and
# the resulting churn was scored as dithering the engine was not doing.
CLIMB_FPM = 1000.0
DESCEND_FPM = 700.0


def fly(range_nm: float, radial_deg: float, heading_deg: float, profile,
        sloppy: bool = False, seed: int = 0, deaf: bool = False,
        speed_kt: float = 0.0) -> dict:
    """One approach, from one start, until it arrives or runs out of fuel.

    `deaf` is a pilot who does not turn. Not a bad pilot -- a BUSY one: head
    down, changing a frequency, talking to somebody else, or reading a bug
    report to engineering, which is exactly what Hoover was doing at seven miles
    when the vectors reversed on him.

    It matters because every start in this sweep otherwise OBEYS. `--sloppy`
    lags and overshoots and drifts, and still complies. So the engine has only
    ever been measured against an aeroplane that does what it is told, and the
    reversal bug (#19) survived four fix attempts across two sessions without
    ever reproducing here -- because it needs the geometry to keep getting worse
    while the controller keeps talking, and an obedient aeroplane never lets it.
    """
    rnd = random.Random(seed)              # seeded: a failure must be repeatable
    kt = speed_kt or (SPEED_MPH * 0.868)
    speed_nm_s = kt / 3600.0
    rate_deg_s = turn_rate_deg_s(kt)
    pos = asr.Position(range_nm=range_nm, radial_deg=radial_deg,
                       alt_ft=profile.hold_base_ft, heading_deg=heading_deg,
                       speed_kt=kt)
    steps = int(MAX_MINUTES * 60 / STEP_SEC)
    last_turn, established_at = "", None
    turns = 0
    dither = 0
    last_turn_step = None
    # Two reversals inside this many seconds is not a manoeuvre, it is an
    # argument. A gate turn is isolated; dithering comes in bursts.
    DITHER_WINDOW = 30.0

    on_missed = False          # the caller's latch, exactly as the bridge holds it
    _last_hdg = [None]         # and the quantiser's memory, likewise
    for _ in range(steps):
        # Carry the last heading so the quantiser has the memory it needs
        # -- see `guide`. Without it a five degree bucket flips at the
        # boundary and the sweep measures the flapping, which is real.
        g = asr.guide(pos, profile, on_missed=on_missed,
                      last_heading=_last_hdg[0])
        _last_hdg[0] = g.heading
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
        #
        # The order is MAGNETIC, because that is what a controller says. The
        # aeroplane's heading here is TRUE, because that is what radar reports.
        # Converting is not a detail: skip it and the simulated pilot flies a
        # course the geometry never asked for, and the sweep grades the engine
        # against its own mistake.
        ordered_true = (g.heading + profile.magvar_deg) % 360
        err = 0.0 if deaf else G.angle_diff(ordered_true, pos.heading_deg)
        turn = max(-rate_deg_s * STEP_SEC, min(rate_deg_s * STEP_SEC, err))
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


def sweep(profile, sloppy: bool = False,
          deaf: bool = False, speed_kt: float = 0.0) -> tuple[list[dict], int]:
    # A deaf pilot is flown from CLOSE IN as well. That is where he was when he
    # reported it -- "between the inner, near the runway, going the opposite
    # direction. This is where he gets very very confused" -- and the ordinary
    # grid has never started an approach inside eight miles.
    ranges = [3, 5, 8, 12, 16, 20, 25, 30] if deaf else [8, 12, 16, 20, 25, 30]
    radials = range(0, 360, 20)              # 18
    headings = range(0, 360, 30)             # 12
    out = []
    for rng in ranges:
        for rad in radials:
            for hdg in headings:
                r = fly(rng, rad, hdg, profile, sloppy=sloppy, deaf=deaf,
                        seed=rng * 100000 + rad * 100 + hdg, speed_kt=speed_kt)
                r["start"] = (rng, rad, hdg)
                out.append(r)
    return out, len(out)


# WHERE THE ENGINE STANDS TODAY, known bugs and all.
#
# A regression check must compare against what IS, not against perfection: three
# approaches orbit instead of arriving (#20) and that is open and understood, so
# exiting non-zero for it makes this permanently red -- and a check that always
# fails is a check nobody reads, which is worse than not having one.
#
# Beat any of these and update them in the same commit. That is the point: the
# numbers only move deliberately.
# Moved 27 July, when the final approach course stopped being magnetic in a
# true-bearing frame -- Batumi's 13 measured 126 true / 120 magnetic against a
# briefed 124 used as though it were true. A correctness fix, not a tuning one,
# so the numbers move in both directions and all of them are recorded:
#
#   clean   1293 -> 1294 arrived   1 -> 1 flips     582 -> 588 turns
#   sloppy  1296 -> 1296 arrived  26 -> 32 flips    899 -> 899 turns
#   deaf      20 -> 21 arrived    23 -> 17 flips    576 -> 586 turns
#
# Moved AGAIN the same night, when the course moved from 126 to 131 -- the
# first correction had it in the DCS grid frame rather than the true one the
# radials use. See route.py.
#
# And once more when the approach was re-anchored on the TOUCHDOWN POINT rather
# than the radar reference half a mile beyond it:
#
#   clean   1294 -> 1296 arrived    1 -> 1 flips
#   sloppy  1296 -> 1296 arrived   32 -> 38 flips
#   deaf      21 -> 22 arrived     17 -> 20 flips
#
# And again when the reposition became a PATTERN -- downwind, base, final --
# instead of a point to be chased:
#
#   clean   1296 -> 1296 arrived    1 ->  0 flips    588 ->  581 turns
#   sloppy  1296 -> 1294 arrived   38 -> 35 flips    899 -> 1535 turns
#   deaf      21 ->   22 arrived   20 -> 72 flips    586 -> 1945 turns
#
# THE TURN COUNT NOW MEASURES A DIFFERENT MANOEUVRE and the old number is not a
# fair comparison: a pattern has three deliberate turns where a straight-in has
# one, so "~1 is the gate turn" in the note above is no longer the shape of the
# thing being counted. Clean, which is the honest measure of the engine, is the
# best it has ever been on every metric.
#
# The deaf figures are a genuine regression and are recorded rather than
# smoothed: a pilot who never turns is flown through all three legs in turn and
# the engine keeps re-deciding which one he is on. It is the same weakness as
# the fast overshoot below, and it is #39's remaining work.
#
# CLEAN IS NOW PERFECT: 1296 of 1296. The last two stragglers were the orbiters
# behind the field that #20 has been about since the beginning -- they were
# chasing an entry gate computed from the wrong point. The dither counts rise
# because half a mile of geometry moved under a metronome that calls every whole
# mile; arrivals are the number that matters and they went up in all three.
#
# The deaf number is the one worth noticing: the reversals a pilot who does not
# turn provokes fell by a third, which is #19's territory. The single extra
# rapid flip in clean is not understood and is written down here rather than
# rounded away.
# HEADINGS ARE ISSUED IN FIVES NOW, and the two flyable sweeps improved while
# the deaf one got worse. Both numbers moved for the same reason and it is
# worth writing down which.
#
#     "Most times, especially en route, heading should be rounded to nearest
#      5 degrees."
#
# Rounding ALONE was a bad regression -- clean went from 0 dithering to 7 and
# from 581 turns to 1614 -- because the turn deadband was ALSO five degrees, so
# every rounding step landed exactly on the threshold and flipped the commanded
# turn. Two independently sensible numbers resonating. They live together in
# `geometry` now with a test asserting the deadband stays the wider of the two.
#
#   clean   1296 -> 1296 arrived    0 ->  0 flips    581 ->  576 turns
#   sloppy  1294 -> 1294 arrived   35 -> 35 flips
#   deaf       0 ->    0 arrived   72 -> 94 flips
#
# THE DEAF NUMBER IS MOVED DELIBERATELY, which is a thing this file otherwise
# refuses to do. A pilot who never turns is a probe of controller stability and
# not a sortie -- nobody arrives in it, by definition -- and coarser headings
# mean the engine re-decides his leg in bigger jumps. Two attempts to recover
# it failed: a wider deadband did nothing, and turn-reversal hysteresis made it
# worse and broke sloppy as well. Both reverted.
#
#     "Yelling at a non turning pilot is ok."
#
# So the trade is taken with the reason recorded: the two sweeps that describe
# aeroplanes actually flying an approach both held or improved.
# A BASELINE IS PER PROCEDURE. Comparing an ILS at Nellis -- a mile and a half
# up, in the Spring Mountains -- against a surveillance approach at Batumi on the
# coast measures nothing except that they are different approaches. The figures
# below are Batumi's ASR, which is what every recorded run has meant.
#
# An approach with no baseline REPORTS and does not judge. That is the honest
# state for one nobody has swept before: the numbers are on the screen, and
# calling them a regression against another procedure's would be noise, which is
# how a check stops being read. Record one here when it is worth defending.
BASELINE_FOR = {"batumi-asr-13": "the recorded Batumi figures"}

BASELINE = {
    "clean":  {"arrived": 1296, "dither": 0, "turns": 576},
    "sloppy": {"arrived": 1294, "dither": 35, "turns": 1535},
    # --deaf: a pilot who never turns, so ARRIVING IS NOT THE MEASURE -- he is
    # not flying the approach and 20 of 1728 reaching the missed approach point
    # is him drifting over it, not the engine working. What is measured here is
    # whether the CONTROLLER argues with itself when the geometry refuses to
    # improve: reversals and direction changes. That is #19, and it is invisible
    # to an obedient aeroplane.
    "deaf":   {"arrived": 0, "dither": 94, "turns": 1945},
    # SPEED. The sweep only ever flew a warbird -- 1,296 approaches, all of
    # them at 200 mph -- so a green run meant "correct for a P-47" and was read
    # as "correct". These fly the identical grid at jet speeds, with the turn
    # rate a 30-degree bank actually gives at each one.
    #
    # 300 is clean, which says the pattern holds for anything that flies a
    # normal approach. 450 is NOT, and the shape of the failure is the point:
    # almost everybody still arrives, but the controller argues with itself 181
    # times getting them there. A 5.1 nm turn radius cannot turn inside a base
    # leg built around 3, so the engine orders a turn, the aeroplane cannot
    # make it, and the engine orders the opposite -- which is exactly what a
    # pilot reports as "he switched between left and right on final".
    #
    # Recorded as a KNOWN-OPEN number rather than a target, in the same spirit
    # as the deaf figures: this is #39, and the fix is to scale the intercept
    # with groundspeed. Beat it and move it in the same commit.
    "fast300": {"arrived": 1296, "dither": 0, "turns": 765},
    "fast450": {"arrived": 1290, "dither": 181, "turns": 3976},
}
# Turns wander a little with the seeded drift; dithering and arrivals must not.
TURN_SLACK = 0.05


# THE AERODROME, not the beacon. A procedure is named `<field>-<kind>` --
# "batumi-asr-13", "nellis-ils-21" -- and both helpers below read `beacon` for the
# field's name because that is where it lived until #163 split the slot. The
# read went to a property, then to a renamed attribute, and `getattr` answered
# "" both times: every key came out `"-asr"`, nothing matched, and the sweep
# reported NO APPROACHES ON THE MAP.
#
# It did not fail. It printed "no approach called 'batumi-asr'" and returned 2,
# which `tools/check.py` renders as SKIP -- so the one instrument that measures
# the GEOMETRY of an approach has been standing down since the split, saying so
# on every run, in the line everybody reads as "needs the sim". That is the
# whole argument for `check.py` naming what a skip leaves unguarded.
def _field_of(p) -> str:
    """The aerodrome this procedure arrives at, lower-cased, or ''."""
    return (getattr(getattr(p, "aerodrome", None), "name", "") or "").lower()


def _known_profiles() -> list[str]:
    """Every approach the loaded theatre publishes, by the name a plan uses."""
    from marshall.core import theatre as _t
    out = []
    for p in getattr(_t.current(), "approaches", ()) or ():
        field, kind = _field_of(p), (getattr(p, "kind", "") or "").lower()
        if field and kind:
            out.append(f"{field}-{kind}")
    return out


def _profile_named(key: str):
    """The theatre's procedure with this key. Same resolution the bridge uses,
    so the sweep and the controller cannot disagree about what `nellis-ils` is."""
    from marshall.core import theatre as _t
    key = (key or "").strip().lower()
    for p in getattr(_t.current(), "approaches", ()) or ():
        field, kind = _field_of(p), (getattr(p, "kind", "") or "").lower()
        if key in (f"{field}-{kind}", field, kind):
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sloppy", action="store_true",
                    help="fly it with a pilot who lags, overshoots and drifts")
    ap.add_argument("--deaf", action="store_true",
                    help="fly it with a pilot who does not turn at all -- head "
                         "down, busy, or talking to somebody else")
    ap.add_argument("--verbose", action="store_true",
                    help="list every start that never arrived")
    # WHICH APPROACH IS BEING SWEPT, and it used to be one hardcoded name.
    #
    # #2 criterion 2: this sweep is the only instrument that measures the
    # GEOMETRY -- where an aeroplane establishes, how many turns it takes, how
    # often the guidance dithers -- and it could only ever measure Batumi's.
    # Every other approach in the system was therefore unmeasured, including
    # both Nevada ILSes, on a map whose terrain is a mile and a half up.
    #
    # The baseline stays Batumi's, because a baseline is per-procedure by
    # definition and comparing an ILS at Nellis against an ASR at Batumi would
    # be meaningless. Named runs report their figures and do not move it.
    ap.add_argument("--profile", default="batumi-asr-13",
                    help="which approach to fly (default: batumi-asr). "
                         "Names are the theatre's, e.g. nellis-ils")
    args = ap.parse_args()

    profile = _profile_named(args.profile)
    if profile is None:
        print(f"!! no approach called {args.profile!r}. Known here: "
              f"{', '.join(_known_profiles()) or '(none)'}", file=sys.stderr)
        return 2
    if args.profile not in BASELINE_FOR:
        print(f"flying {args.profile}, which has no recorded baseline -- the "
              f"figures are reported and nothing is judged against another "
              f"procedure's.\n")
    results, total = sweep(profile, sloppy=args.sloppy, deaf=args.deaf)
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

    mode = "deaf" if args.deaf else ("sloppy" if args.sloppy else "clean")
    base = BASELINE.get(mode) if args.profile in BASELINE_FOR else None
    if base is None:
        print(f"  baseline      none recorded for {args.profile} — figures "
              f"reported, nothing judged")
    regressed = []
    if base:
        # Arrivals are not a measure of a pilot who does not turn.
        if not args.deaf and len(arrived) < base["arrived"]:
            regressed.append(f"arrived {len(arrived)} < {base['arrived']}")
        if dither > base["dither"]:
            regressed.append(f"DITHERING {dither} > {base['dither']}")
        if turns > base["turns"] * (1 + TURN_SLACK):
            regressed.append(f"turns {turns} > {base['turns']} + slack")
        print(f"  baseline      {base['arrived']} arrived, {base['dither']} "
              f"flips, {base['turns']} turns"
              + ("  — REGRESSED: " + "; ".join(regressed) if regressed
                 else "  — no regression"))

    lost = [r for r in results if not r["arrived"]]
    if lost and not args.deaf:
        print(f"  NEVER ARRIVED {len(lost)}")
        show = lost if args.verbose else lost[:10]
        for r in show:
            rng, rad, hdg = r["start"]
            print(f"     {rng:2d} nm on the {rad:03d} radial, heading {hdg:03d}")
        if not args.verbose and len(lost) > len(show):
            print(f"     ... and {len(lost) - len(show)} more (--verbose)")
    # Known-open bugs do not fail the check; getting WORSE does.
    return 1 if regressed else 0


if __name__ == "__main__":
    raise SystemExit(main())
