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
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


import grpc

from marshall import config as _config
from marshall.feed.stubs import bind as _bind

_bind()

from marshall.core import route as R

# WHERE THE SIM IS, from the one place that knows -- env, else
# `services/.env`, which is the file compose reads and no shell does.
# Rolling a local default here is how this tool ended up talking to
# localhost while the sim ran on another machine. See `dcs.grpc_addr`.
ADDR = _config.DCS_GRPC_ADDR

# Mark ids, and the rule that governs them: DCS NEVER LETS ONE BE REUSED.
#
# Create a mark, remove it, create it again with the same id and the second one
# silently does not exist. No error, no warning; the call is accepted and
# nothing appears. It cost an evening: the route drew perfectly the first time,
# vanished on every redraw after, and each redraw cheerfully reported success.
# It was diagnosed by putting up two marks at once -- a used id and a fresh one
# -- and watching only the fresh one arrive.
#
# So each draw takes a NEW block of ids and remembers it, and the next draw
# erases the block before it. The state lives in a file because the tool is one
# process per invocation and the sim will not tell us which ids were ours.
BASE_ID = 4000
BLOCK = 200
STATE = Path("/tmp/marshall-draw-marks")

BLUE = "{0, 0.35, 0.9, 0.9}"          # our route
RED = "{0.85, 0.15, 0.1, 0.95}"       # things that shoot
RED_FILL = "{0.85, 0.15, 0.1, 0.12}"
CLEAR = "{0, 0, 0, 0}"


def _eval(ch, lua: str) -> str:
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    return str(custom_pb2_grpc.CustomServiceStub(ch).Eval(
        custom_pb2.EvalRequest(lua=lua), timeout=60).json).strip('"')


def _last_base() -> int:
    try:
        return int(STATE.read_text().strip())
    except (OSError, ValueError):
        return BASE_ID


def _next_base() -> int:
    """A block of ids never used before. See the note on BASE_ID."""
    nxt = _last_base() + BLOCK
    try:
        STATE.write_text(str(nxt))
    except OSError:
        pass
    return nxt


def _erase_lua(base: int) -> str:
    return (f"for id = {base}, {base + BLOCK - 1} do "
            "trigger.action.removeMark(id) end")


def erase(ch) -> str:
    """Take down whatever we drew last."""
    _eval(ch, _erase_lua(_last_base()) + '\nreturn "cleared"')
    return "cleared"


def draw(ch, coalition: int = -1) -> str:
    """Route, target and threat rings.

    Coalition -1 is EVERYONE and is the default, which is not the tidy answer
    but is the working one: marks scoped to blue are invisible to anybody who
    has not taken a blue slot yet, including spectators and anybody still on
    the slot screen -- which is exactly when people want to look at the plan.
    Drawn blue-only they simply are not there, with nothing to say why.

    Pass 2 for blue-only on a server where the other side has real players.
    """
    # Erase the previous block, then draw into a fresh one -- ids are never
    # reused, so the new marks cannot collide with the old ones even in the
    # same frame.
    lines = [_erase_lua(_last_base())]
    mid = _next_base()

    # The route, leg by leg. One line per leg rather than a polyline, because a
    # leg is the unit a pilot thinks in and can be talked about on its own.
    for a, b in zip(R.SORTIE, R.SORTIE[1:]):
        lines.append(
            f'trigger.action.lineToAll({coalition}, {mid}, '
            f'{{x = {a.x}, y = 0, z = {a.z}}}, {{x = {b.x}, y = 0, z = {b.z}}}, '
            f'{BLUE}, 1, true, "")')
        mid += 1

    # Waypoint labels: NUMBER first, because the number is what gets said on
    # the radio and the name is what gets read on the chart.
    for n, fix in R.sortie_points():
        if n == len(R.SORTIE):          # the last point is home again
            continue
        lines.append(
            f'trigger.action.markToAll({mid}, "{n}. {fix.name}", '
            f'{{x = {fix.x}, y = 0, z = {fix.z}}}, true, "")')
        mid += 1

    # The target: a circle you can fly to, not a coordinate you have to find.
    t = R.TARGET_AREA
    lines.append(
        f'trigger.action.circleToAll({coalition}, {mid}, '
        f'{{x = {t.x}, y = 0, z = {t.z}}}, {5 * 1852}, {RED}, {RED_FILL}, 1, '
        f'true, "")')
    mid += 1

    # And what shoots. The radius is the guns' REACH -- what a pilot needs to
    # see is where it becomes unwise, not where the barrels are.
    for name, x, z, reach_nm in R.DEFENDED:
        lines.append(
            f'trigger.action.circleToAll({coalition}, {mid}, {{x = {x}, y = 0, z = {z}}}, '
            f'{int(reach_nm * 1852)}, {RED}, {RED_FILL}, 2, true, "")')
        mid += 1
        lines.append(
            f'trigger.action.markToAll({mid}, "{name.upper()} - AAA", '
            f'{{x = {x}, y = 0, z = {z}}}, true, "")')
        mid += 1

    body = "\n".join(lines)
    _eval(ch, f'{body}\nreturn "sent"')
    # Count in a SEPARATE call: marks created in a chunk are not visible to
    # getMarkPanels until the next frame, so counting inline reports the old
    # total and looks like a failure even when it worked.
    time.sleep(1.5)
    return _eval(ch, "return tostring(#world.getMarkPanels())")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clear", action="store_true", help="erase and stop")
    ap.add_argument("--blue-only", action="store_true",
                    help="scope to the blue coalition (invisible to spectators)")
    args = ap.parse_args()

    with grpc.insecure_channel(ADDR) as ch:
        if args.clear:
            erase(ch)
            print("map cleared")
            return 0
        n = draw(ch, 2 if args.blue_only else -1)
        who = "blue only" if args.blue_only else "everyone, spectators included"
        print(f"{n} marks now on the F10 map ({who}) — counted by the sim")
        for a, b in zip(R.SORTIE, R.SORTIE[1:]):
            print(f"   {a.name:11s} -> {b.name}")
        print(f"   target ring 5 nm, threat rings on "
              f"{', '.join(d[0] for d in R.DEFENDED)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
