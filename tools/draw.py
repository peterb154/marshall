"""Draw the route on the F10 map of a RUNNING mission. No reload.

The mission builder can bake drawings into the .miz, but every change then
costs a rebuild, a deploy and a server restart -- three minutes, and everybody
gets dropped. The mission scripting API draws on the live map instead:
lineToAll, circleToAll and markToAll put marks up immediately and take them
down the same way.

So the route can be argued about while people are sitting on the ramp, which is
exactly when it gets argued about. Tonight it went from "straight over Kutaisi"
to "out to sea and round the top" in three iterations, and baking each one in
would have cost ten minutes of downtime.

    uv run python tools/draw.py            # route, target, threat rings
    uv run python tools/draw.py --clear    # take it all down

Marks are numbered from a fixed base so a redraw replaces rather than stacks --
otherwise the map silently accumulates every version of the plan.
"""

from __future__ import annotations

import argparse
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "director" / "_grpc"))

if "dcs" not in sys.modules:                     # see asr_autopilot.py
    _pkg = types.ModuleType("dcs")
    _pkg.__path__ = [str(ROOT / "director" / "_grpc" / "dcs")]
    sys.modules["dcs"] = _pkg

import grpc                                                     # noqa: E402

from marshall.core import route as R                            # noqa: E402

ADDR = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")

# A fixed range of mark ids that belong to us. Everything in it is removed
# before anything is drawn, so a redraw replaces the plan rather than layering
# a second copy over the first.
BASE_ID = 4000
MAX_IDS = 120

BLUE = "{0, 0.35, 0.9, 0.9}"          # our route
RED = "{0.85, 0.15, 0.1, 0.95}"       # things that shoot
RED_FILL = "{0.85, 0.15, 0.1, 0.12}"
CLEAR = "{0, 0, 0, 0}"


def _eval(ch, lua: str) -> str:
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    return str(custom_pb2_grpc.CustomServiceStub(ch).Eval(
        custom_pb2.EvalRequest(lua=lua), timeout=60).json).strip('"')


def erase(ch) -> str:
    """Remove our marks. Safe to call when there are none."""
    return _eval(ch, f"""
    for id = {BASE_ID}, {BASE_ID + MAX_IDS} do
      trigger.action.removeMark(id)
    end
    return "cleared"
    """)


def draw(ch) -> str:
    """Route, target and threat rings, drawn for the blue coalition only.

    Coalition-scoped on purpose: the red side has no business reading our plan,
    and on a map where every field but one is hostile that is not a detail.
    """
    lines, mid = [], BASE_ID

    # The route, leg by leg. One line per leg rather than a polyline, because a
    # leg is the unit a pilot thinks in and can be talked about on its own.
    for a, b in zip(R.SORTIE, R.SORTIE[1:]):
        lines.append(
            f'trigger.action.lineToAll(2, {mid}, '
            f'{{x = {a.x}, y = 0, z = {a.z}}}, {{x = {b.x}, y = 0, z = {b.z}}}, '
            f'{BLUE}, 1, true, "")')
        mid += 1

    # Waypoint labels: NUMBER first, because the number is what gets said on
    # the radio and the name is what gets read on the chart.
    for n, fix in R.sortie_points():
        if n == len(R.SORTIE):          # the last point is home again
            continue
        lines.append(
            f'trigger.action.markToCoalition({mid}, "{n}. {fix.name}", '
            f'{{x = {fix.x}, y = 0, z = {fix.z}}}, 2, true, "")')
        mid += 1

    # The target: a circle you can fly to, not a coordinate you have to find.
    t = R.TARGET_AREA
    lines.append(
        f'trigger.action.circleToAll(2, {mid}, '
        f'{{x = {t.x}, y = 0, z = {t.z}}}, {5 * 1852}, {RED}, {RED_FILL}, 1, '
        f'true, "")')
    mid += 1

    # And what shoots. The radius is the guns' REACH -- what a pilot needs to
    # see is where it becomes unwise, not where the barrels are.
    for name, x, z, reach_nm in R.DEFENDED:
        lines.append(
            f'trigger.action.circleToAll(2, {mid}, {{x = {x}, y = 0, z = {z}}}, '
            f'{int(reach_nm * 1852)}, {RED}, {RED_FILL}, 2, true, "")')
        mid += 1
        lines.append(
            f'trigger.action.markToCoalition({mid}, "{name.upper()} - AAA", '
            f'{{x = {x}, y = 0, z = {z}}}, 2, true, "")')
        mid += 1

    body = "\n".join(lines)
    return _eval(ch, f'{body}\nreturn "{mid - BASE_ID}"')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clear", action="store_true", help="erase and stop")
    args = ap.parse_args()

    with grpc.insecure_channel(ADDR) as ch:
        erase(ch)
        if args.clear:
            print("map cleared")
            return 0
        n = draw(ch)
        print(f"drew {n} marks on the F10 map (blue coalition only)")
        for a, b in zip(R.SORTIE, R.SORTIE[1:]):
            print(f"   {a.name:11s} -> {b.name}")
        print(f"   target ring 5 nm, threat rings on "
              f"{', '.join(d[0] for d in R.DEFENDED)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
