"""DCS-gRPC tools for the mission director — live world queries and control.

Live state (unit positions, spawning, mission control) comes from DCS-gRPC on the
sim server. Static map data (airports, navaids, beacons) belongs in PostGIS and is
served by separate tools; this module is the *live* half.

The gRPC stubs are generated from the DCS-gRPC protos and vendored under `_grpc/`
(added to sys.path in app.py). `DCS_GRPC_ADDR` defaults to the LAN sim server.
"""

from __future__ import annotations


from marshall.core import geo as _geo
import logging
import os

import grpc

try:
    from strands import tool
except ImportError:                     # allow import on a host without strands
    def tool(fn):
        return fn

from dcs.coalition.v0 import coalition_pb2, coalition_pb2_grpc
from dcs.common.v0 import common_pb2
from dcs.group.v0 import group_pb2, group_pb2_grpc
from dcs.hook.v0 import hook_pb2, hook_pb2_grpc

# Your DCS server's gRPC endpoint. LAN-only, never public -- and this repo is,
# so the address belongs in the environment (see director/.env), not here.
log = logging.getLogger(__name__)

DCS_GRPC_ADDR = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
_TIMEOUT = 8.0


def _channel() -> grpc.Channel:
    return grpc.insecure_channel(DCS_GRPC_ADDR)


@tool
def get_current_mission() -> str:
    """Return the name and .miz filename of the mission currently loaded on the
    DCS server. Use this to confirm which scenario is running."""
    with _channel() as ch:
        hook = hook_pb2_grpc.HookServiceStub(ch)
        name = hook.GetMissionName(hook_pb2.GetMissionNameRequest(), timeout=_TIMEOUT).name
        path = hook.GetMissionFilename(hook_pb2.GetMissionFilenameRequest(), timeout=_TIMEOUT).name
        return f"Current mission: {name}  (file: {path.replace(chr(92), '/').split('/')[-1]})"


@tool
def load_mission(file_name: str) -> str:
    """Hot-load a mission on the DCS server, live, with no server restart. Takes
    the FULL server-side path to the .miz. Players drop to the load screen and the
    new mission comes up."""
    with _channel() as ch:
        hook = hook_pb2_grpc.HookServiceStub(ch)
        hook.LoadMission(hook_pb2.LoadMissionRequest(file_name=file_name), timeout=_TIMEOUT)
        return f"Loading mission: {file_name}"


@tool
def get_player_units() -> str:
    """List the human-piloted aircraft currently on the server, with type,
    position (lat/lon), altitude, and heading. This is the god's-eye view of who
    is flying and where."""
    lines: list[str] = []
    with _channel() as ch:
        coal = coalition_pb2_grpc.CoalitionServiceStub(ch)
        for side in (common_pb2.COALITION_BLUE, common_pb2.COALITION_RED):
            try:
                resp = coal.GetPlayerUnits(
                    coalition_pb2.GetPlayerUnitsRequest(coalition=side), timeout=_TIMEOUT)
            except grpc.RpcError:
                continue
            for u in resp.units:
                who = u.player_name or u.callsign or u.name
                lines.append(
                    f"{who} ({u.type}) — {u.position.lat:.4f}, {u.position.lon:.4f}, "
                    f"{u.position.alt:.0f} m, heading {u.orientation.heading:.0f}")
    return "\n".join(lines) if lines else "No player-controlled units on the server right now."


# --- radar: player positions as a controller reads them ---------------------
# Raw lat/lon means nothing on a radio. A controller thinks in bearing and range
# off a fix -- here the Batumi beacon / field (UGSB) -- plus altitude and the
# direction the aircraft is actually pointing.
BATUMI_LAT, BATUMI_LON = 41.6103, 41.5997     # UGSB ARP, co-located with the OS beacon
_NM = 3440.065                                 # earth radius in nautical miles
_M_TO_FT = 3.28084


def _bearing_range(lat: float, lon: float) -> tuple[float, float]:
    """Bearing (deg TRUE -- the radial the aircraft sits on) and range in nm
    from the Batumi beacon to a point.

    THE SEVENTH IMPLEMENTATION OF THIS IS GONE. It was a haversine with its own
    earth-radius constant (3440.065 nm, against `core.geo`'s 6371008.8 m -- the
    same figure, arrived at separately), living here because until the compose
    file mounted `marshall` into this container the director COULD NOT IMPORT
    the shared one. Duplicating was not a shortcut, it was the only option.

    Order is swapped rather than passed through: `core.geo` returns
    (range, bearing) because every caller wants the distance first, and this
    one's callers want it the other way round. One transposition here beats a
    second function everywhere.
    """
    nm, brg = _geo.range_bearing_true((BATUMI_LAT, BATUMI_LON), lat, lon)
    return brg, nm


_AIR = (common_pb2.GROUP_CATEGORY_AIRPLANE, common_pb2.GROUP_CATEGORY_HELICOPTER)
_SIDES = (common_pb2.COALITION_BLUE, common_pb2.COALITION_RED,
          common_pb2.COALITION_NEUTRAL)


def _scan_air(ch) -> dict:
    """Every airborne unit the sim will show us, keyed by name so a contact is
    listed once. Player units alone (GetPlayerUnits) miss AI traffic; walking the
    air groups (GetGroups -> GetUnits) picks up AI and the player both. We keep
    the player call as a belt-and-suspenders source for a lone client."""
    coal = coalition_pb2_grpc.CoalitionServiceStub(ch)
    grp = group_pb2_grpc.GroupServiceStub(ch)
    units: dict = {}
    for side in _SIDES:
        for cat in _AIR:
            try:
                groups = coal.GetGroups(
                    coalition_pb2.GetGroupsRequest(coalition=side, category=cat),
                    timeout=_TIMEOUT).groups
            except grpc.RpcError:
                continue
            for g in groups:
                try:
                    for u in grp.GetUnits(group_pb2.GetUnitsRequest(
                            group_name=g.name, active=True), timeout=_TIMEOUT).units:
                        units[u.name] = u
                except grpc.RpcError:
                    continue
    for side in (common_pb2.COALITION_BLUE, common_pb2.COALITION_RED):
        try:
            for u in coal.GetPlayerUnits(
                    coalition_pb2.GetPlayerUnitsRequest(coalition=side),
                    timeout=_TIMEOUT).units:
                units.setdefault(u.name, u)
        except grpc.RpcError:
            continue
    return units


def radar_live(bindings: dict | None = None) -> list[str]:
    """One line per contact straight from the sim over gRPC -- the always-current
    fallback when the PostGIS cache is cold."""
    bindings = bindings or {}
    lines: list[str] = []
    with _channel() as ch:
        for u in _scan_air(ch).values():
            who = u.player_name or u.callsign or u.name
            tag = f" [{bindings[who]}]" if who in bindings else ""
            brg, rng = _bearing_range(u.position.lat, u.position.lon)
            lines.append(
                f"{who}{tag} ({u.type}): {rng:.1f} nm on the {brg:03.0f} radial, "
                f"{u.position.alt * _M_TO_FT:,.0f} ft, heading {u.orientation.heading:03.0f}")
    return lines


def contacts_live(bindings: dict | None = None) -> list[dict]:
    """The same scan as `radar_live`, as data.

    THE LAST PLACE PROSE WAS THE ONLY SOURCE. `contacts()` reads the PostGIS
    cache; when that cache is cold `radar_picture` falls back to this gRPC scan
    and used to return a STRING and nothing else -- so the one moment the
    consumers were forced back onto their regexes was a moment they were also
    getting a degraded picture. Now the fallback degrades in the data too, which
    is honest and parseable.

    DEGRADED, and the caller can see how: a live scan knows position, type and
    player, and does NOT know the sim's ground/landed events, group category, or
    who is flying formation on whom. Those come out empty rather than guessed --
    an aeroplane wrongly marked as not-in-formation is a controller told four
    contacts exist where there is one.
    """
    bindings = bindings or {}
    out: list[dict] = []
    with _channel() as ch:
        for u in _scan_air(ch).values():
            who = u.player_name or u.callsign or u.name
            out.append({
                "name": u.name, "label": who,
                "callsign": bindings.get(who, ""),
                "type": u.type, "category": "", "manned": bool(u.player_name),
                "player": u.player_name or "", "on_ground": False,
                "lat": u.position.lat, "lon": u.position.lon,
                "alt_ft": u.position.alt * _M_TO_FT,
                "heading": u.orientation.heading, "speed_kt": 0.0,
                "coalition": getattr(u, "coalition", 0), "formation": "",
            })
    return out


def radar_picture(bindings: dict | None = None) -> str:
    """The scope, one line per contact: range and radial off Batumi, altitude, and
    heading, tagged with any radar-identified callsign. Reads the warm PostGIS
    track cache (tools.tracks) first and falls back to a live gRPC scan when the
    cache is cold. 'no contacts' when the sky is empty."""
    try:
        from marshall.feed.tracks import radar_cached
        lines = radar_cached(bindings)
    except Exception:
        lines = None
    if lines is None:
        lines = radar_live(bindings)
    return " | ".join(lines) if lines else "no contacts"


@tool
def call_in_traffic(group_name: str = "Traffic") -> str:
    """Activate a late-activated AI group -- spawn traffic into the world on cue.
    The mission places dormant groups (e.g. 'Traffic', built with --traffic); this
    calls one in so it appears, flies, and shows on radar. Returns confirmation."""
    with _channel() as ch:
        group_pb2_grpc.GroupServiceStub(ch).Activate(
            group_pb2.ActivateRequest(group_name=group_name), timeout=_TIMEOUT)
    return f"Activated group '{group_name}' — it should now be airborne and on radar."


# Things an overlord can put on the ground, named the way he would say them.
# Every one verified against the running sim -- DCS silently substitutes a
# Leopard-2 for any type it does not recognise, with no error and no warning,
# so a name that has not been checked is a name that quietly spawns a modern
# main battle tank into 1945.
SPAWNABLE = {
    "armour": "T-55", "tank": "T-55", "tanks": "T-55",
    "apc": "M-113", "truck": "Ural-375", "trucks": "Ural-375",
    "infantry": "Soldier M4", "artillery": "M-109",
    "aaa": "ZU-23 Emplacement", "sam": "Strela-1 9P31",
}


@tool
def spawn_ground(what: str, bearing_deg: float, range_nm: float,
                 count: int = 4, anchor: str = "Batumi",
                 name: str = "") -> str:
    """Put enemy ground units into the world at a place you can describe.

    For an OVERLORD giving a flight something to do: armour appearing in a
    valley, a convoy on a road, guns round a position. Located the way a target
    actually gets described -- a bearing and a distance from somewhere both of
    you know -- rather than by coordinates nobody can see from a cockpit.

    what: armour, tank, apc, truck, infantry, artillery, aaa, sam
    bearing_deg / range_nm: from the anchor, magnetic-ish bearing and nautical miles
    anchor: an aerodrome name, e.g. Batumi or Kutaisi
    count: how many
    name: what to call the group, so you can refer to it later

    Refuses to put ground units in the sea. Returns what was actually created,
    read back from the sim -- not what was asked for.
    """
    dcs_type = SPAWNABLE.get(what.lower().strip())
    if not dcs_type:
        return (f"'{what}' is not something I can place. Options: "
                f"{', '.join(sorted(set(SPAWNABLE)))}.")
    count = max(1, min(int(count), 12))
    group = (name or f"{what}-{int(bearing_deg):03d}").replace('"', "")

    lua = f"""
    local ab = Airbase.getByName("{anchor}")
    if not ab then return "no airbase called {anchor}" end
    local c = ab:getPoint()
    local a = math.rad({float(bearing_deg)})
    local d = {float(range_nm)} * 1852
    local x, z = c.x + d * math.cos(a), c.z + d * math.sin(a)
    local st = land.getSurfaceType({{x = x, y = z}})
    if st == 2 or st == 3 then return "that position is water" end
    local units = {{}}
    for i = 1, {count} do
      units[i] = {{
        ["type"] = "{dcs_type}", ["unitId"] = 8600 + i, ["skill"] = "Average",
        ["x"] = x + (i - 1) * 60, ["y"] = z, ["heading"] = 0,
        ["name"] = "{group} " .. i,
      }}
    end
    coalition.addGroup(country.id.RUSSIA, Group.Category.GROUND, {{
      ["visible"] = true, ["taskSelected"] = true, ["hidden"] = false,
      ["groupId"] = 8600, ["name"] = "{group}",
      ["x"] = x, ["y"] = z, ["task"] = "Ground Nothing", ["units"] = units,
    }})
    local g = Group.getByName("{group}")
    local got = g and g:getUnit(1) and g:getUnit(1):getTypeName() or "nothing"
    local ll = ""
    local la, lo = coord.LOtoLL({{x = x, y = 0, z = z}})
    ll = string.format("%.4f %.4f", la, lo)
    return "made=" .. got .. " at " .. ll
    """
    try:
        with _channel() as ch:
            from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
            out = str(custom_pb2_grpc.CustomServiceStub(ch).Eval(
                custom_pb2.EvalRequest(lua=lua), timeout=30).json).strip('"')
    except Exception as e:                       # never break the conversation
        log.warning("spawn_ground failed: %s", e)
        return f"Could not place them: {e}"

    if out.startswith("made="):
        made = out.split("made=")[1]
        if dcs_type not in made:
            return (f"Something is wrong: asked for {dcs_type} and the sim "
                    f"produced {made}. Do not tell the pilot it is there.")
        return (f"{count} x {dcs_type} now on the ground as '{group}', "
                f"{range_nm:.0f} nm on the {bearing_deg:03.0f} from {anchor} "
                f"({made}). They are on radar and can be talked onto.")
    return f"Not placed: {out}"


@tool
def radar() -> str:
    """Your radar scope: where every aircraft is right now, as range and radial
    off the Batumi beacon plus altitude and heading. Use it to confirm a pilot's
    position report and to catch a wrong turn before he flies it."""
    return radar_picture()
