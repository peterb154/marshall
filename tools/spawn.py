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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


import grpc

from marshall import config as _config
from marshall.feed.stubs import bind as _bind

_bind()


# WHERE THE SIM IS, from the one place that knows -- env, else
# `services/.env`, which is the file compose reads and no shell does.
# Rolling a local default here is how this tool ended up talking to
# localhost while the sim ran on another machine. See `dcs.grpc_addr`.
ADDR = _config.DCS_GRPC_ADDR
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

# Airborne. Separate table because they spawn by a different route entirely --
# see spawn_air.
AIR_TYPES = {
    "bandit": "Bf-109K-4",
    "fw190": "FW-190D9",
    "he111": "He-111H-6",
    "ju88": "Ju-88A4",
    "mustang": "P-51D-30-NA",
    "spitfire": "SpitfireLFMkIX",
    "jug": "P-47D-30",
    # MODERN, and their absence was not harmless. An unknown name falls through
    # to the GROUND table and then to the raw string, so `--type viper` did not
    # fail -- it quietly spawned a Leopard-2 and called it an aeroplane. A
    # rehearsal that needs a jet on the scope got a tank, and nothing said so.
    "viper": "F-16C_50",
    "hornet": "FA-18C_hornet",
    "warthog": "A-10C_2",
    "eagle": "F-15C",
}

# DCS country names, as the mission scripting API spells them. Air goes through
# Lua where countries are named rather than numbered, which is the one place
# this is easier than the gRPC path.
LUA_COUNTRY = {"red": "RUSSIA", "blue": "USA"}

# Batumi's aerodrome reference point, so a bearing and range can be resolved
# against something. Any fix in route.py works too.
def _anchors() -> dict:
    """Every aerodrome the loaded theatre has, by name.

    READ FROM THE FIELD TABLE rather than typed here. This was two hardcoded
    Caucasus pairs, so a spawn on Nevada resolved a Nellis request to a Georgian
    coastline -- and `core/fields.py` has carried the published position of every
    field since `theatre.verify` needed one to check the map against the sim.
    Two tables of the same fact is how they come to disagree; there is one.
    """
    from marshall.core import theatre as _theatre
    got = {f.name.upper(): (f.lat, f.lon)
           for f in _theatre.current().fields if f.lat or f.lon}
    return got or {"BATUMI": (41.6103, 41.5997)}


_ANCHORS = _anchors()


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


def surface_at(ch, lat: float, lon: float) -> tuple[str, float]:
    """What is under that spot, and how high, asked of the sim itself.

    Worth asking BEFORE spawning, because a spawn over water succeeds. A tank
    dropped into the Black Sea appears at minus one metre and is a perfectly
    valid track that a mission commander will confidently task a flight
    against. "Anywhere" has to mean anywhere sensible, and the only thing that
    knows which is sensible is the terrain.
    """
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    lua = f"""
    local p = coord.LLtoLO({lat}, {lon})
    local t = land.getSurfaceType({{x = p.x, y = p.z}})
    local h = land.getHeight({{x = p.x, y = p.z}})
    local names = {{[1]="land", [2]="shallow water", [3]="water",
                   [4]="road", [5]="runway"}}
    return (names[t] or "unknown") .. ":" .. math.floor(h)
    """
    try:
        raw = str(custom_pb2_grpc.CustomServiceStub(ch).Eval(
            custom_pb2.EvalRequest(lua=lua), timeout=15).json).strip('"')
        kind, _, height = raw.partition(":")
        return kind, float(height or 0)
    except Exception:
        return "unknown", 0.0


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


def spawn_air(ch, name: str, unit_type: str, lat: float, lon: float, alt_ft: int,
              count: int = 1, side: str = "red", speed_ms: int = 150,
              heading_deg: int = 0, task: str = "CAP"):
    """Put aircraft in the air, through Lua rather than gRPC.

    Only GROUND is implemented in this DCS-gRPC build: ShipGroupTemplate,
    HelicopterGroupTemplate and PlaneGroupTemplate are all present in the
    protocol and all have zero fields, so an air spawn over gRPC silently
    builds an empty message. The mission scripting API has no such gap, and
    Eval reaches it -- the same door the terrain survey uses.

    The group table is verbose because DCS wants it that way: a route with at
    least one point, a payload, and a unit list, or the group appears and does
    nothing. Positions go in as the sim's own x/z metres, converted from
    latitude and longitude in the Lua so the caller never has to think in them.
    """
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc

    alt_m = int(alt_ft * 0.3048)
    units = ",".join(f'''[{i + 1}]={{
        ["alt"]={alt_m}, ["alt_type"]="BARO", ["speed"]={speed_ms},
        ["type"]="{unit_type}", ["unitId"]={9000 + i}, ["psi"]=0,
        ["x"]=p.x + {i * 120}, ["y"]=p.z + {i * 120},
        ["name"]="{name}-{i + 1}", ["heading"]={math.radians(heading_deg):.4f},
        ["callsign"]={i + 1}, ["onboard_num"]="{10 + i:03d}", ["skill"]="Average",
        ["payload"]={{["pylons"]={{}}, ["fuel"]=400, ["flare"]=0,
                     ["chaff"]=0, ["gun"]=100}},
    }}''' for i in range(count))

    lua = f'''
    local p = coord.LLtoLO({lat}, {lon})
    local g = {{
      ["visible"]=false, ["taskSelected"]=true, ["hidden"]=false,
      ["route"]={{["points"]={{[1]={{
          ["alt"]={alt_m}, ["type"]="Turning Point", ["action"]="Turning Point",
          ["alt_type"]="BARO", ["speed"]={speed_ms}, ["x"]=p.x, ["y"]=p.z,
          ["task"]={{["id"]="ComboTask", ["params"]={{["tasks"]={{}}}}}},
      }}}}}},
      ["groupId"]=9001, ["units"]={{{units}}},
      ["y"]=p.z, ["x"]=p.x, ["name"]="{name}", ["communication"]=true,
      ["start_time"]=0, ["task"]="{task}", ["uncontrolled"]=false,
      ["frequency"]=124,
    }}
    coalition.addGroup(country.id.{LUA_COUNTRY.get(side, "RUSSIA")},
                       Group.Category.AIRPLANE, g)
    return "spawned"
    '''
    return custom_pb2_grpc.CustomServiceStub(ch).Eval(
        custom_pb2.EvalRequest(lua=lua), timeout=25)


def spawn_parked(ch, name: str, unit_type: str, airfield: str = "Batumi",
                 count: int = 1, side: str = "blue"):
    """Put aircraft on the RAMP, cold, the way a pilot finds them.

    WHY THIS EXISTS. `spawn_air` is the only aircraft path there was, and it
    forces altitude (`alt_ft = args.alt or 8000`), so there was no way to make
    the case this whole system is built around: a man who has just taken a slot
    and not moved. Every ground behaviour -- the untracked table naming him, the
    "parked" state, checking in without a radar contact -- was untestable
    without a human in a cockpit.

    FROM PARKING AREA, not a low-altitude spawn. An aeroplane placed in the air
    at zero feet with zero speed falls over; DCS wants an airdrome ID and a
    `TakeOffParking` route point, and then it assigns a real parking spot and
    the aircraft sits there indefinitely, which is exactly the fixture wanted.

    `uncontrolled` so it stays put. Given a route and a task an AI will start
    up and taxi, and a moving aeroplane is the case that already worked.
    """
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc

    units = ",".join(f'''[{i + 1}]={{
        ["type"]="{unit_type}", ["unitId"]={9100 + i}, ["skill"]="Average",
        ["name"]="{name}-{i + 1}", ["parking_landing"]=0,
        ["payload"]={{["pylons"]={{}}, ["fuel"]=400, ["flare"]=0,
                     ["chaff"]=0, ["gun"]=100}},
    }}''' for i in range(count))

    # THE SIM'S OWN SPELLING. `Airbase.getByName` is case-sensitive and DCS
    # writes "Kobuleti", not "KOBULETI" -- and the anchor table is keyed upper,
    # so the name arrived shouting and the lookup failed. Try the caller's
    # spelling, then title case, before giving up: a fixture that cannot be
    # placed is the difference between "the rule is broken" and "there was
    # nothing to test".
    lua = f'''
    local ab = Airbase.getByName("{airfield}")
        or Airbase.getByName("{str(airfield).title()}")
        or Airbase.getByName("{str(airfield).capitalize()}")
    if ab == nil then return "no such airfield: {airfield}" end
    local p = ab:getPoint()
    local g = {{
      ["visible"]=false, ["uncontrolled"]=true, ["hidden"]=false,
      ["route"]={{["points"]={{[1]={{
          ["alt"]=p.y, ["type"]="TakeOffParking",
          ["action"]="From Parking Area", ["alt_type"]="BARO",
          ["speed"]=0, ["x"]=p.x, ["y"]=p.z,
          ["airdromeId"]=ab:getID(),
          ["task"]={{["id"]="ComboTask", ["params"]={{["tasks"]={{}}}}}},
      }}}}}},
      ["groupId"]=9101, ["units"]={{{units}}},
      ["y"]=p.z, ["x"]=p.x, ["name"]="{name}", ["communication"]=true,
      ["start_time"]=0, ["task"]="Nothing", ["frequency"]=124,
    }}
    coalition.addGroup(country.id.{LUA_COUNTRY.get(side, "USA")},
                       Group.Category.AIRPLANE, g)
    return "parked at {airfield}"
    '''
    return custom_pb2_grpc.CustomServiceStub(ch).Eval(
        custom_pb2.EvalRequest(lua=lua), timeout=25)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="", help="group name; defaults to the type")
    ap.add_argument("--type", default="tank",
                    help=f"ground: {', '.join(TYPES)} | air: {', '.join(AIR_TYPES)}")
    ap.add_argument("--alt", type=int, default=0,
                    help="feet; any value makes this an AIR spawn")
    ap.add_argument("--heading", type=int, default=0, help="air only")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--ground", metavar="AIRFIELD", nargs="?", const="Batumi",
                    help="aircraft only: park it cold on the ramp at this "
                         "airfield (default Batumi) instead of putting it in "
                         "the air. The case the ATC is actually built around.")
    ap.add_argument("--force", action="store_true",
                    help="spawn even where it makes no sense (water)")
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
    elif args.ground:
        # The airfield IS the position, and the sim picks the parking spot --
        # asking a caller for a latitude to park at would be asking him to
        # guess at something DCS knows exactly.
        #
        # ...THE AIRFIELD HE ASKED FOR, though. This read `_at("BATUMI")`
        # whatever was passed, so `--ground KOBULETI` parked an aeroplane forty
        # miles away at Batumi and announced "at KOBULETI -> 41.61030, 41.59970"
        # in the same breath. Correct by accident while there was one aerodrome;
        # wrong the moment there were two, and it prints the answer beside the
        # question it ignored.
        lat, lon = _at(args.ground)
        where = args.ground
    else:
        raise SystemExit("give either --lat/--lon or --bearing/--range")

    COUNTRY = {"red": 1, "blue": 21}
    country = args.country or COUNTRY[args.side]
    parked = bool(args.ground) and args.type in AIR_TYPES
    airborne = (args.type in AIR_TYPES or args.alt > 0) and not parked
    # AN UNKNOWN TYPE IS A MISTAKE, not a DCS type name to pass through. The
    # fall-through spawned a Leopard-2 for `--type viper` and reported success;
    # a harness then tested a controller against a tank parked on a runway.
    table = AIR_TYPES if (airborne or parked) else TYPES
    if args.type not in table and not args.force:
        raise SystemExit(
            f"unknown type {args.type!r}. Known {'aircraft' if table is AIR_TYPES else 'ground'}"
            f": {', '.join(sorted(table))}. Use --force to pass a raw DCS type.")
    unit_type = table.get(args.type, args.type)
    name = args.name or f"{args.type}-{int(abs(lat * 1000)) % 1000}"
    alt_ft = args.alt or (8000 if airborne else 0)
    print(f"spawning {args.count} x {unit_type} as '{name}' ({args.side}"
          + (f", {alt_ft:,} ft)" if airborne else ")"))
    print(f"  at {where}  ->  {lat:.5f}, {lon:.5f}")

    with grpc.insecure_channel(ADDR) as ch:
        if parked:
            print(f"  parking {args.count} x {unit_type} as '{name}' "
                  f"at {args.ground}")
            try:
                r = spawn_parked(ch, name, unit_type, args.ground,
                                 args.count, args.side)
                print(f"  {r.json}")
            except grpc.RpcError as e:
                print(f"  FAILED: {e.details()}")
                return 1
            # THE LUA'S ANSWER IS THE RESULT, not the fact that the call
            # returned. This printed "spawned -- cold on the ramp" immediately
            # after printing `no such airfield: KOBULETI`, in the same breath:
            # the RPC succeeded and the spawn did not. A tool that reports
            # success it did not have sends the next person looking for a bug in
            # the thing that was never tested.
            answer = str(getattr(r, "json", "")).strip('"')
            if "no such" in answer or "error" in answer.lower():
                print(f"  FAILED: {answer}")
                return 1
            print("  spawned — cold on the ramp, uncontrolled")
            return 0
        if not airborne:
            # Only ground units care what is underneath them.
            kind, height = surface_at(ch, lat, lon)
            print(f"  ground there: {kind}, {height:.0f} m")
            if kind in ("water", "shallow water") and not args.force:
                print("  REFUSED: that is water, and a tank in the sea is a "
                      "target an overlord will task a flight against in all "
                      "seriousness. Move it, or pass --force if you meant it.")
                return 1
        try:
            if airborne:
                spawn_air(ch, name, unit_type, lat, lon, alt_ft, args.count,
                          args.side, heading_deg=args.heading)
            else:
                spawn(ch, name, unit_type, lat, lon, args.count, country)
        except grpc.RpcError as e:
            print(f"  FAILED: {e.details()}")
            return 1
    print("  spawned — it should appear in tracks within a sweep or two")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
