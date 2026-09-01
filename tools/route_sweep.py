"""Fly synthetic aeroplanes down a route and count what a controller would say.

    "I want to be able to have atc vector us along a flight plan"

THE THRESHOLDS IN `core/following.py` ARE GUESSES UNTIL THIS MEASURES THEM.
Two nautical miles to alert, one to clear, five down the leg before judging a
turn -- all chosen from arithmetic (a 400-knot aeroplane at 30 degrees of bank
turns in about 4 nm) and none from a flight. This is the instrument that turns
them into numbers, the same way `tools/asr_sweep.py` did for the approach,
where rounding without hysteresis was measured at 0 dithering events against 7
and 581 turns against 1614.

WHAT IT COUNTS, and why each one is a failure if it grows:

    calls       how much he is told in a sortie. The whole feature is gated
                behind a request because "in a combat sim, we might not want
                the nag", so this is the number that says whether it nags
    missed      fixes flown past with no passage call. Any is a bug: passage
                is the perpendicular, and a pilot who is not told has to guess
                whether we are still with him
    turn calls  off-course alerts issued within a turn. Should be ZERO -- a
                ninety-degree turn swings four miles wide and an alert there
                is the controller nagging about a manoeuvre he asked for
    flapping    off-course alerts issued and cancelled inside a mile of track.
                That is the hysteresis band failing

    uv run python tools/route_sweep.py
    uv run python tools/route_sweep.py --alert 3 --clear 1.5
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marshall.core import following as F

# Kobuleti out to BAR and back into Batumi -- the theatre's own numbers, so a
# leg length and an angle between legs are the real ones rather than a pair of
# tidy numbers that happen to make the arithmetic work.
# How an aeroplane actually flies a route, and both numbers matter to what
# this measures. Fifteen degrees per mile is a 400-knot jet at 30 degrees of
# bank -- a 4 nm radius -- and a mile and a half is where he starts the turn.
TURN_DEG_PER_NM = 15.0
LEAD_NM = 1.5

START = F.Leg("KOBULETI", 41.9299, 41.8633, 59)
ROUTE = [F.Leg("BAR", 42.1858, 42.0941, 10000),
         F.Leg("BATUMI", 41.6094, 41.5999, 33)]


def fly(route, start, wander_nm: float, step_nm: float = 1.0):
    """A pilot flying the route, wandering off it by up to `wander_nm`.

    NOT A PERFECT AUTOPILOT, which is the point: an aeroplane that tracks the
    centreline exactly would score zero on everything and prove nothing. He
    aims at the next fix, overshoots the turn like a real one, and drifts.
    """
    lat, lon = start.lat, start.lon
    i, t = 0, 0.0
    _, flying = _rb(lat, lon, route[0].lat, route[0].lon)
    while i < len(route):
        b = route[i]
        nm, brg = _rb(lat, lon, b.lat, b.lon)
        if nm < LEAD_NM:
            # HE LEADS THE TURN, which is what pilots do and what a
            # perpendicular-only passage test missed entirely.
            i += 1
            continue
        # The wander is a slow sine so it crosses the band rather than jittering
        # across it -- jitter would flatter the hysteresis by never dwelling.
        off = wander_nm * math.sin(t / 6.0)
        want = brg + math.degrees(math.atan2(off, max(nm, 1.0)))
        # AND HE TURNS AT A RATE, rather than snapping onto the new heading.
        # Without this the sweep was VACUOUS for the turn guard and the
        # hysteresis band: an aeroplane that changes direction instantly never
        # swings wide of the next leg, so `settle_nm` could be set to zero and
        # nothing moved. At 400 knots and 30 degrees of bank the radius is
        # about 4 nm, which is roughly fifteen degrees per mile flown.
        d = ((want - flying + 180) % 360) - 180
        flying = (flying + max(-TURN_DEG_PER_NM, min(TURN_DEG_PER_NM, d))) % 360
        lat, lon = _project(lat, lon, flying, step_nm)
        t += 1.0
        yield lat, lon
        if t > 400:
            return


def _rb(lat1, lon1, lat2, lon2):
    from marshall.core import geo
    return geo.range_bearing_true((lat1, lon1), lat2, lon2)


def _project(lat, lon, brg, nm):
    from marshall.core import geo
    return geo.project_true((lat, lon), brg, nm)


def sweep(alert_nm: float, clear_nm: float, settle_nm: float) -> dict:
    out = {"calls": 0, "passages": 0, "missed": 0, "turn_calls": 0,
           "flapping": 0, "polls": 0}
    for wander in (0.0, 1.0, 2.5, 4.0):
        idx, alerting, since_change = 0, False, 99.0
        seen_pass = set()
        for lat, lon in fly(ROUTE, START, wander):
            out["polls"] += 1
            g = F.guide(ROUTE, lat, lon, idx, start=START)
            if g is None:
                break
            if g.passed:
                out["calls"] += 1
                out["passages"] += 1
                seen_pass.add(g.fix)
                idx = F.next_index(g, idx)
                alerting, since_change = False, 0.0
                continue
            want = F.off_course(g, alerting, alert_nm, clear_nm, settle_nm)
            if want != alerting:
                if want:
                    out["calls"] += 1
                    if g.along_nm < settle_nm:
                        out["turn_calls"] += 1
                    if since_change < 1.0:
                        out["flapping"] += 1
                alerting, since_change = want, 0.0
            since_change += 1.0
        out["missed"] += len([b for b in ROUTE if b.fix not in seen_pass
                              and b is not ROUTE[-1]])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", type=float, default=2.0)
    ap.add_argument("--clear", type=float, default=1.0)
    ap.add_argument("--settle", type=float, default=5.0)
    a = ap.parse_args()
    got = sweep(a.alert, a.clear, a.settle)
    # DOES THE GUARD MATTER? A zero that proves nothing must not read like a
    # zero that does. Each guard is switched OFF and the sweep re-run: if the
    # count does not move, this harness is not exercising it and the pass is
    # vacuous. `tools/check.py` reports a skip for the same reason -- "a check
    # that quietly does not run reads exactly like one that passed".
    no_turn = sweep(a.alert, a.clear, 0.0)
    no_hyst = sweep(a.alert, a.alert, a.settle)
    print(f"  route sweep  alert {a.alert} / clear {a.clear} / settle {a.settle}")
    print(f"    polls        {got['polls']}")
    print(f"    calls        {got['calls']}  ({got['calls'] / 4:.1f} per sortie)")
    print(f"    passages     {got['passages']}")
    print(f"    missed       {got['missed']}   <- any is a bug")
    print(f"    turn calls   {got['turn_calls']}   <- should be zero"
          + _vacuous(got["turn_calls"], no_turn["turn_calls"], "settle"))
    print(f"    flapping     {got['flapping']}   <- hysteresis failing"
          + _vacuous(got["flapping"], no_hyst["flapping"], "clear"))
    bad = got["missed"] or got["turn_calls"] or got["flapping"]
    return 1 if bad else 0


def _vacuous(got: int, without: int, knob: str) -> str:
    """Say when a zero is not evidence. The guard was turned off and nothing
    changed, so this run did not test it."""
    if got == 0 and without == 0:
        return f"  (NOT EXERCISED -- 0 with `{knob}` off too)"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
