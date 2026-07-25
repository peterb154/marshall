"""Put something in the world, somewhere specific. The overlord's hands.

The scenario this serves: a flight is fragged for CAS somewhere remote; behind
the scenes armour appears in a town; the flight is told to go and kill it. The
telling is the agent's job and the killing is the pilot's -- this is the quiet
part in the middle, and it has to be able to place a unit at a named place
rather than wherever the mission builder happened to put one.

Position is given the way a person would say it: a bearing and a distance from
somewhere known, or a latitude and longitude if you have one. "Twelve miles
north-east of Batumi" is how a target actually gets described, and converting
that to metres is this file's problem, not the overlord's.

    uv run python tools/spawn.py --at BATUMI --bearing 040 --range 12 --type tank
    uv run python tools/spawn.py --lat 41.7 --lon 41.9 --type tank --count 3

Whatever is spawned lands in `tracks` and is therefore visible to everything
else -- which is what makes "is the target still alive" a lookup rather than a
judgement. Nobody has to model destruction: the row stops being there.
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

import grpc                                                     # noqa: E402

from marshall.core import route as R                            # noqa: E402

ADDR = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
M_PER_NM = 1852.0

# A few things worth putting on the ground, by what you would call them rather
# than by their DCS type name. Extend as scenarios need more; the point is that
# an overlord says "armour" and not "M-1 Abrams".
TYPES = {
    "tank": "M-1 Abrams",
    "tank_red": "T-55",
    "apc": "M-113",
    "truck": "Ural-375",
    "aaa": "ZU-23 Emplacement",
    "sam": "Strela-1 9P31",
    "infantry": "Soldier M4",
    "artillery": "M-109",
}

# Batumi's aerodrome reference point, so a bearing and range can be resolved
# against something. Any fix in route.py works too.
_ANCHORS = {"BATUMI": (41.6103, 41.5997), "KOBULETI": (41.9297, 41.8697)}


def _at(name: str) -> tuple[float, float]:
    key = (name or "BATUMI").upper()
    if key in _ANCHORS:
        return _ANCHORS[key]
    raise SystemExit(f"unknown place {name!r}; known: {', '.join(_ANCHORS)}")


def project(lat: float, lon: float, bearing_deg: float, nm: float) -> tuple[float, float]:
    """Where you end up going that way for that far. Spherical, which is ample
    for a target twelve miles out."""
    d = nm * M_PER_NM / 6_371_000.0
    br, la, lo = map(math.radians, (bearing_deg, lat, lon))
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(br))
    lo2 = lo + math.atan2(math.sin(br) * math.sin(d) * math.cos(la),
                          math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def spawn(ch, name: str, unit_type: str, lat: float, lon: float,
          count: int = 1, coalition_country: int = 2, spacing_m: float = 60.0):
    """Place a group. Units are strung out rather than stacked on one point --
    a pile of tanks at identical coordinates is not a target, it is an artefact.
    """
    from dcs.coalition.v0 import coalition_pb2, coalition_pb2_grpc
    from dcs.common.v0 import common_pb2

    # Two shapes that look interchangeable and are not: a spawn takes an
    # InputPosition (what you ASK for -- lat, lon, and an altitude the sim may
    # clamp to the ground) while a report gives back a Position. And the
    # templates are NESTED inside AddGroupRequest rather than being module-level
    # messages. Both fail at call time rather than at import.
    GroundGroup = coalition_pb2.AddGroupRequest.GroundGroupTemplate
    GroundUnit = coalition_pb2.AddGroupRequest.GroundUnitTemplate

    units = []
    for i in range(count):
        units.append(GroundUnit(
            name=f"{name}-{i + 1}",
            type=unit_type,
            position=common_pb2.InputPosition(lat=lat, lon=lon + i * spacing_m / 82_000.0),
            heading=0,      # integer degrees, not a float
        ))
    req = coalition_pb2.AddGroupRequest(
        country=coalition_country,
        group_category=common_pb2.GroupCategory.GROUP_CATEGORY_GROUND,
        ground_template=GroundGroup(
            name=name,
            position=common_pb2.InputPosition(lat=lat, lon=lon),
            units=units,
            task="Ground Nothing",
        ),
    )
    return coalition_pb2_grpc.CoalitionServiceStub(ch).AddGroup(req, timeout=15)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="", help="group name; defaults to the type")
    ap.add_argument("--type", default="tank", help=f"one of: {', '.join(TYPES)}")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--at", default="BATUMI", help="anchor for --bearing/--range")
    ap.add_argument("--bearing", type=float)
    ap.add_argument("--range", type=float, dest="range_nm", help="nautical miles")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    # Say which SIDE, not which country id. The ids are not what you would
    # guess -- 21 comes out blue while 1, 2 and 20 come out red, and 0 and 18
    # are rejected outright with a bare "Stream removed" that says nothing
    # about the country being the problem. Probed against this build rather
    # than taken from a table, because a target that spawns on the wrong side
    # is a target the flight is not allowed to shoot.
    ap.add_argument("--side", choices=("red", "blue"), default="red",
                    help="whose armour this is (default red: something to kill)")
    ap.add_argument("--country", type=int, default=0,
                    help="override the country id if you know what you want")
    args = ap.parse_args()

    if args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
        where = f"{lat:.4f}, {lon:.4f}"
    elif args.bearing is not None and args.range_nm is not None:
        a_lat, a_lon = _at(args.at)
        lat, lon = project(a_lat, a_lon, args.bearing, args.range_nm)
        where = f"{args.range_nm:.0f} nm on the {args.bearing:03.0f} from {args.at.upper()}"
    else:
        raise SystemExit("give either --lat/--lon or --bearing/--range")

    COUNTRY = {"red": 1, "blue": 21}
    country = args.country or COUNTRY[args.side]
    unit_type = TYPES.get(args.type, args.type)
    name = args.name or f"{args.type}-{int(abs(lat * 1000)) % 1000}"
    print(f"spawning {args.count} x {unit_type} as '{name}' ({args.side})")
    print(f"  at {where}  ->  {lat:.5f}, {lon:.5f}")

    with grpc.insecure_channel(ADDR) as ch:
        try:
            spawn(ch, name, unit_type, lat, lon, args.count, country)
        except grpc.RpcError as e:
            print(f"  FAILED: {e.details()}")
            return 1
    print("  spawned — it should appear in tracks within a sweep or two")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
