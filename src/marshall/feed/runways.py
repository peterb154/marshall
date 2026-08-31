"""The runways of the loaded map, asked of the sim once.

`Airbase:getRunways()` is the source, and `core.runways` says why this is worth
having at all. This module is the only thing that talks to DCS about it; the
geometry and the "is he on it" test are pure and live in core.

ASKED OF THE SIM, NOT COMPUTED FROM IT. The corners are projected to latitude
and longitude by `coord.LOtoLL` inside the mission, because a flat-earth
conversion of our own is 7.6 nm out at 50 nm on the Caucasus -- the error that
cost a day once already. What comes back is already in the frame everything
else here uses.

ONCE PER MISSION. Runways do not move, so this is fetched at bridge start and
whenever the world changes, and held. A failure is not fatal and must not be:
without polygons the controller falls back to what a pilot SAYS, which is how
it worked before this existed.
"""
from __future__ import annotations

import json
import logging

from marshall.core.runways import Runway
from marshall.feed.dcs import DCS_GRPC_ADDR

log = logging.getLogger(__name__)

# DCS: x is NORTH, z is EAST. `course` is the negative of the MAGNETIC runway
# heading in radians -- see `core.runways` for how that was pinned down and for
# what happens if it is taken as true instead.
_LUA = """
local out = {}
for _, ab in pairs(world.getAirbases() or {}) do
  local rws = ab.getRunways and ab:getRunways() or nil
  if rws then
    for _, r in pairs(rws) do
      if r.position and r.length and r.width then
        local hdg = -r.course
        local dx, dz = math.cos(hdg), math.sin(hdg)
        local px, pz = -dz, dx
        local hl, hw = r.length / 2, r.width / 2
        local cx, cz = r.position.x, r.position.z
        local pts = {}
        for _, s in pairs({{1,1},{1,-1},{-1,-1},{-1,1}}) do
          local x = cx + dx*hl*s[1] + px*hw*s[2]
          local z = cz + dz*hl*s[1] + pz*hw*s[2]
          local lat, lon = coord.LOtoLL({x = x, y = 0, z = z})
          pts[#pts+1] = string.format("%.7f %.7f", lon, lat)
        end
        out[#out+1] = string.format("%s|%s|%.1f|%.1f|%s",
          ab:getName(), tostring(r.Name), r.length, r.width,
          table.concat(pts, ";"))
      end
    end
  end
end
return table.concat(out, "\\n")
"""


def _bearing(a, b) -> float:
    import math
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = (math.cos(p1) * math.sin(p2)
         - math.sin(p1) * math.cos(p2) * math.cos(dl))
    return math.degrees(math.atan2(y, x)) % 360


def from_the_sim(timeout: float = 20.0) -> list[Runway]:
    """Every runway the loaded mission has. Empty on any failure."""
    try:
        import grpc
        from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
        with grpc.insecure_channel(DCS_GRPC_ADDR) as ch:
            reply = custom_pb2_grpc.CustomServiceStub(ch).Eval(
                custom_pb2.EvalRequest(lua=_LUA), timeout=timeout)
        raw = json.loads(reply.json) or ""
    except Exception as e:                       # broad on purpose -- see module doc
        log.warning("could not read the runways from the sim: %s", str(e)[:120])
        return []
    out: list[Runway] = []
    for line in str(raw).split("\n"):
        if not line.strip():
            continue
        try:
            fld, name, length, width, pts = line.split("|")
            corners = tuple(tuple(float(v) for v in p.split())
                            for p in pts.split(";"))
            if len(corners) != 4:
                continue
            # TRUE, AND DERIVED FROM THE CORNERS. `course` is magnetic, and the
            # corners are the only thing here the sim projected itself.
            hdg = _bearing((corners[1][1], corners[1][0]),
                           (corners[2][1], corners[2][0]))
            out.append(Runway(field_name=fld, name=name,
                              length_m=float(length), width_m=float(width),
                              heading_true=hdg, corners=corners))
        except (ValueError, IndexError) as e:
            log.warning("unreadable runway row %r: %s", line[:60], e)
    return out
