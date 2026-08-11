"""The DKS data cartridge, as data.

    "why wouldnt we file the flight plan to match the DTC data exactly?"
    "and then ATC should be fully aware of what I am doing at what altitude"

Marshall's filed plan said KOBULETI, INITIAL, BATUMI at five thousand while the
cartridge in the jet said seven miles east, nine north, thirteen west over the
water, at ten. Clearance would have read back a route he was not flying at an
altitude he was not holding.

THE FORMAT is four bytes of little-endian uncompressed length, then a gzip
stream, then JSON. Waypoints carry degrees-and-decimal-minutes strings and a
per-waypoint elevation; `Radios` carries the preset ladder; `Misc` carries the
ILS, TACAN and bingo; `KneeboardNotes` is free text. Nothing here is guessed --
it was read off live exports.

IT LIVES IN `core` BECAUSE TWO THINGS READ IT: `tools/dtc.py` at a keyboard and
the kneeboard's filing page in a browser. A parser owned by one caller is a
parser the other copies, and a second copy of a wire format is how two readers
come to disagree about what a pilot filed.

Nothing here talks to the network or decides anything. What may be FILED is the
director's rule (`tools/filing.py`) and is asked, never duplicated.
"""

from __future__ import annotations

import base64
import gzip
import json
import re

# Degrees and decimal minutes, as DKS writes them: a hemisphere letter, a degree
# sign, then minutes. The trailing mark is a typographic apostrophe rather than a
# prime, which is why nothing here matches on it -- a cartridge that has been
# through a clipboard is not guaranteed to keep it.
_LL = re.compile(r"([NSEW])\s*(\d+)[\u00b0\s]+([\d.]+)")


def decode(text: str) -> dict:
    """The cartridge, as data. Raises with a readable reason if it is not one."""
    raw = base64.b64decode("".join(text.split()))
    if len(raw) < 8:
        raise ValueError("too short to be a cartridge")
    # The first four bytes are the uncompressed length. Not needed to decode --
    # gzip carries its own -- but checked, because a mismatch means the string
    # was truncated in transit and the JSON would fail later and less clearly.
    want = int.from_bytes(raw[:4], "little")
    body = gzip.decompress(raw[4:])
    if len(body) != want:
        raise ValueError(f"cartridge says {want} bytes, decoded {len(body)}")
    return json.loads(body)


def latlon(s: str) -> float:
    """A DKS position string to decimal degrees.

    Degrees and decimal MINUTES, not seconds: "N 41 deg 57.496" is 41.958267,
    and reading those minutes as seconds would put it half a mile out.
    """
    m = _LL.search(s or "")
    if not m:
        raise ValueError(f"cannot read a position from {s!r}")
    hemi, deg, mins = m.group(1), float(m.group(2)), float(m.group(3))
    v = deg + mins / 60.0
    return -v if hemi in ("S", "W") else v


def waypoints(d: dict) -> list[dict]:
    """Sequence, name, position and altitude, in the order he will fly them."""
    out = []
    for w in ((d.get("Waypoints") or {}).get("Waypoints") or []):
        out.append({"seq": int(w.get("Sequence") or 0),
                    "name": (w.get("Name") or "").strip(),
                    "lat": latlon(w.get("Latitude", "")),
                    "lon": latlon(w.get("Longitude", "")),
                    "alt_ft": int(w.get("Elevation") or 0)})
    return sorted(out, key=lambda w: w["seq"])


def route_through(wps: list[dict], nm: float = 5.0) -> list[str]:
    """The PUBLISHED fixes this route actually passes near, and nothing else.

        "in civil avation, we dont make up our own random fixes in a flight
         plan though.. That's probably a difference here."

    Right, and it is the second time this project reached for a made-up name --
    CHAKVI on the plate, then STPT1/2/3 here. The defence the second time was
    that the pilot can see his own steerpoints in the cockpit, and it does not
    hold: a filed route is a SHARED PUBLISHED reference and his cartridge is
    published to nobody. Filing a fix only one party can resolve is worse than
    filing none, because it reads as agreement.

    What a radar controller needs is the destination, the altitude, and a return
    on the scope; the turning points between are the pilot's business. That is
    the military model and it is what this is. So the route names the published
    fixes it genuinely passes through and says nothing about the rest.
    """
    from marshall.core import geo
    from marshall.core import theatre as _t
    th = _t.current()
    fields = {f.name.upper() for f in th.fields}
    out: list[str] = []
    for w in wps:
        best, best_nm = "", nm
        for f in getattr(th, "fixes", ()) or ():
            name = (getattr(f, "name", "") or "").upper()
            lat, lon = getattr(f, "lat", None), getattr(f, "lon", None)
            if not name or lat is None or lon is None:
                continue
            d, _ = geo.range_bearing_true((w["lat"], w["lon"]), lat, lon)
            if d < best_nm:
                best, best_nm = name, d
        if best and best not in out and best not in fields:
            out.append(best)
    return out


def named_steerpoints(wps: list[dict]) -> dict:
    """His own turning points, by the names HE gave them -- name -> (lat, lon).

        "I have the ability give a description to every steerpoint. What if ATC
         uses this to reference in space that I pick."

    The distinction that took two mistakes to find is SHARED versus PUBLISHED,
    not published versus invented. DIOMI is published: it is on every pilot's
    plate, for ever. FOO is not published and is still perfectly shared -- he
    typed it, it is on his HSI, and the cartridge carried it here. A controller
    saying "report passing BAR" names a place they can both resolve, which is
    the entire job a fix name does.

    What it is NOT is durable, and it belongs to ONE aeroplane: his steerpoint
    two and a wingman's are different places. So these die with the sortie --
    the bridge's own catalogue push at start-up replaces the fix table and takes
    them off it, which is the lifecycle working rather than a bug.

    Anything DKS left unnamed stays out. "STPT" is not a name he chose, it is
    the absence of one, and filing it would be back to inventing.
    """
    from marshall.core import theatre as _t
    fields = {f.name.upper() for f in _t.current().fields}
    out = {}
    for w in wps:
        n = (w["name"] or "").strip().upper()
        if not n or n in ("STPT", "WP") or n in fields:
            continue
        out[n] = [w["lat"], w["lon"]]
    return out


def nearest_field(lat: float, lon: float, within_nm: float = 25.0) -> str:
    """The aerodrome this position belongs to, or "".

    A CARTRIDGE HAS NO ORIGIN. The jet's route starts at steerpoint one, which
    is already airborne and some miles out -- so where he took off from is not
    in the file, and the first version simply used the theatre's `departure`.
    That is a hard-coded string per theatre, correct for the sortie somebody had
    in mind when they wrote it and wrong for any other.

    Geometry does not need telling. Steerpoint one sits seven miles off
    Kobuleti; the last waypoint IS Batumi. Both ends fall out of where the route
    actually is, so a cartridge flown out of Kutaisi files Kutaisi without
    anybody editing a default.
    """
    from marshall.core import geo
    from marshall.core import theatre as _t
    best, best_nm = "", within_nm
    for f in _t.current().fields:
        if f.lat is None or f.lon is None:
            continue
        d, _ = geo.range_bearing_true((lat, lon), f.lat, f.lon)
        if d < best_nm:
            best, best_nm = f.name, d
    return best


def plan_from(d: dict, name: str, approach: str = "", label: str = "",
              origin: str = "", steerpoints: bool = False) -> dict:
    """The cartridge as a filed plan: where he is going, and how high.

    THE CRUISE IS THE HIGHEST ENROUTE LEG, not the first. `flight_plans` holds
    one altitude and the cartridge holds one per waypoint, so something has to
    give -- and the number that matters is the one a controller must not be
    surprised by. Filing the first leg's five thousand while the pilot climbs to
    ten is precisely the disagreement this exists to end.

    Both ENDS are derived from the route rather than from the theatre's
    defaults -- see `nearest_field`. `origin` is still an argument because a
    ferry that starts somewhere the route does not pass over is a real thing and
    the caller may know better; it is an override, not a default.
    """
    wps = waypoints(d)
    if not wps:
        raise ValueError("no waypoints in the cartridge")
    from marshall.core import theatre as _t
    fields = {f.name.upper() for f in _t.current().fields}
    first, last = wps[0], wps[-1]
    # The destination is the last waypoint that IS an aerodrome; failing that,
    # the aerodrome the last waypoint is nearest to -- a route that ends on a
    # downwind still ends at that field.
    dest = next((w["name"] for w in reversed(wps)
                 if w["name"].upper() in fields), "") \
        or nearest_field(last["lat"], last["lon"])
    start = origin or nearest_field(first["lat"], first["lon"]) or dest
    enroute = [w for w in wps if w["name"].upper() not in fields
               and w["name"].upper() != (dest or "").upper()]
    cruise = max([w["alt_ft"] for w in enroute] or [w["alt_ft"] for w in wps])
    # HIS NAMES, or only the published ones. See `named_steerpoints` on why both
    # are defensible and why they are not the same kind of thing.
    via = ([w["name"].strip().upper() for w in enroute
            if (w["name"] or "").strip().upper() not in ("", "STPT", "WP")]
           if steerpoints else route_through(enroute))
    route = [start.upper(), *via, (dest or start).upper()]
    return {"name": name, "label": label,
            "origin": start.title(), "destination": (dest or start).title(),
            "route": ", ".join(route), "cruise_ft": int(cruise),
            "task": "training", "approach": approach}
