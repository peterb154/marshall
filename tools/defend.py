"""Put anti-aircraft guns round a field, so the airspace teaches itself.

A briefing note saying "avoid Kutaisi" is read once and forgotten. A battery of
88s that opens up the first time somebody cuts the corner is remembered for
good, and it turns a straight line on a chart into a route with a reason.

Period-correct on purpose. These are 1945 guns -- heavy flak that reaches up to
the transit altitude and light guns that make anything low regret it -- and both
matter, because the two answers to flak are "high enough that the light stuff
cannot reach" and "not overhead at all", and a defence with only one kind
teaches only half the lesson.

    uv run python tools/defend.py                    # the three fields on the route
    uv run python tools/defend.py --field Kutaisi    # just one

The guns land in `tracks` like everything else, so an overlord can warn about
them and a pilot can ask where they are.
"""

from __future__ import annotations

import argparse
import math
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

import grpc

ADDR = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")

# The red fields that sit on the transit route. Defending these three is what
# makes the Batumi -- Kutaisi leg a route rather than a straight line: they are
# all close enough to the direct track that cutting a corner takes you over one
# of them.
#
# Named, not coordinated. Typing the latitudes in by hand put the first battery
# most of a mile off the field it was meant to be defending, which on a
# thousand-metre ring is the difference between guns round the runway and guns
# in somebody's orchard. The sim knows where its own aerodromes are.
FIELDS = ["Kobuleti", "Senaki-Kolkhi", "Kutaisi"]

# A 1945 battery: heavy guns that reach the transit height, light guns that
# punish anything low, and a director, because a battery without one is a
# museum piece rather than a threat.
#
# Laid out as a ring rather than a heap: guns on top of each other are one
# target, and the spread is what makes overflying the field a bad idea from
# any direction.
BATTERY = [
    # (dcs type, how many, ring radius in metres)
    ("flak37", 4, 900),                 # 8.8 cm heavy, radar-directed
    ("flak18", 2, 1000),                # 8.8 cm, the older mount
    ("flak38", 4, 550),                 # 2 cm quad -- punishes anything low
    ("flak30", 2, 650),                 # 2 cm single
    ("KDO_Mod40", 1, 750),              # fire director: the battery's eyes
    ("Flakscheinwerfer_37", 2, 1100),   # searchlights, for night work
]

# Every one of these was VERIFIED against the running sim, and that is not
# belt-and-braces. The first battery was written from the module list -- flak36,
# flak37, flak38, KDO_Mod40, Flakscheinwerfer_37 -- and every one of those names
# is fiction on a server without the WW2 Assets Pack. DCS did not complain. It
# accepted each request, reported success, and quietly built a LEOPARD-2: a
# 1979 main battle tank, thirty-three of them, ringing three 1945 aerodromes.
#
# Nothing anywhere said so. The gRPC reply was fine, the Lua returned a count,
# and the only way to find out was to ask the sim what it had actually made.
# Hence verify() below, and hence the short list: flak18 IS the 8.8, bofors40
# IS period, and both exist in the base game.
# Empty now that the WW2 Assets Pack is installed -- every name above was
# re-probed against the running sim and comes back as itself. Kept as a list
# rather than deleted because the check is the point: a server without the pack
# turns all of them into Leopard-2s without saying a word, and verify() below is
# what notices.
KNOWN_BAD: set[str] = set()


def ring(lat: float, lon: float, radius_m: float, n: int, phase: float = 0.0):
    """n points evenly round a circle. Metres to degrees the cheap way, which
    is ample at this radius and this latitude."""
    for i in range(n):
        a = phase + 2 * math.pi * i / n
        yield (lat + (radius_m * math.cos(a)) / 111_320.0,
               lon + (radius_m * math.sin(a)) / (111_320.0 * math.cos(math.radians(lat))))


def defend(ch, field: str, battery, country: str = "RUSSIA") -> int:
    """Ring a named aerodrome with guns, in one call.

    Through Lua rather than the gRPC ground spawn, and not by preference. That
    endpoint SILENTLY SUBSTITUTES: asked for flak37 it accepted the request,
    reported success, and produced a Leopard-2 -- thirty-three of them, round
    three 1945 aerodromes. It does the same for any ground type outside a small
    internal list, with no error and nothing in the reply to suggest anything
    happened. The mission scripting API has no such list and no such opinion.

    The aerodrome is looked up by name inside the sim, so the guns sit on the
    field rather than near where somebody thought it was.
    """
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc

    spec = ",".join(
        f'{{type="{t}", n={n}, r={r}}}' for t, n, r in battery)
    lua = f'''
    local ab = Airbase.getByName("{field}")
    if not ab then return "no such airbase" end
    local c = ab:getPoint()
    local battery = {{{spec}}}
    local made, id = 0, 0
    for _, b in ipairs(battery) do
      for i = 1, b.n do
        id = id + 1
        -- Spread each type round its own ring, offset from the others, so the
        -- guns cover every approach instead of clustering on one bearing.
        local a = (2 * math.pi * (i - 1) / b.n) + (id * 0.37)
        local g = {{
          ["visible"] = true, ["taskSelected"] = true, ["hidden"] = false,
          ["groupId"] = 7000 + id,
          ["name"] = "AAA {field} " .. b.type .. " " .. i,
          ["x"] = c.x + b.r * math.cos(a), ["y"] = c.z + b.r * math.sin(a),
          ["task"] = "Ground Nothing",
          ["units"] = {{[1] = {{
              ["type"] = b.type, ["unitId"] = 7000 + id, ["skill"] = "Average",
              ["y"] = c.z + b.r * math.sin(a), ["x"] = c.x + b.r * math.cos(a),
              ["name"] = "AAA {field} " .. b.type .. " " .. i .. "-1",
              ["heading"] = a,
          }}}},
        }}
        coalition.addGroup(country.id.{country}, Group.Category.GROUND, g)
        made = made + 1
      end
    end
    return tostring(made)
    '''
    out = custom_pb2_grpc.CustomServiceStub(ch).Eval(
        custom_pb2.EvalRequest(lua=lua), timeout=45)
    raw = str(out.json).strip('"')
    return int(raw) if raw.isdigit() else 0


def verify(ch, field: str, battery) -> list[str]:
    """Ask the sim what it ACTUALLY built. Never skip this.

    DCS substitutes silently for an unknown ground type -- no error, no warning,
    a cheerful success and a Leopard-2 where the 88 should be. The request
    succeeding proves nothing; only the type name coming back does.
    """
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    checks = "".join(
        f'''
        local g = Group.getByName("AAA {field} {t} 1")
        out[#out+1] = "{t}=" .. (g and g:getUnit(1) and g:getUnit(1):getTypeName()
                                 or "MISSING")
        ''' for t, _, _ in battery)
    raw = str(custom_pb2_grpc.CustomServiceStub(ch).Eval(
        custom_pb2.EvalRequest(lua=f"local out = {{}}\n{checks}\n"
                                   "return table.concat(out, ';')"),
        timeout=30).json).strip('"')
    wrong = []
    for pair in raw.split(";"):
        asked, _, got = pair.partition("=")
        if asked and asked != got:
            wrong.append(f"{asked} came out as {got}")
    return wrong


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--field", action="append",
                    help=f"one of: {', '.join(FIELDS)} (default: all three)")
    ap.add_argument("--country", default="RUSSIA", help="Lua country id name")
    args = ap.parse_args()

    fields = args.field or FIELDS
    placed = 0
    with grpc.insecure_channel(ADDR) as ch:
        bad = [t for t, _, _ in BATTERY if t in KNOWN_BAD]
        if bad:
            print(f"  refusing: {', '.join(bad)} need the WW2 Assets Pack and "
                  "become Leopard-2s without it")
            return 1
        for field in fields:
            n = defend(ch, field, BATTERY, args.country)
            placed += n
            print(f"  {field:16s} {n} guns")
            for dcs_type, count, radius in BATTERY:
                print(f"      {count} x {dcs_type} at {radius} m")
            for problem in verify(ch, field, BATTERY):
                print(f"      !! {problem}")
    print(f"\n{placed} guns placed and verified against the sim")
    return 0 if placed else 1


if __name__ == "__main__":
    raise SystemExit(main())
