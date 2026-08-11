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


def waypoints(d: dict, route_only: bool = True) -> list[dict]:
    """Sequence, name, position and altitude, in the order he will fly them.

    THE ROUTE STOPS AT THE FIRST GAP, and everything past it is not navigation.

        "DTC cartridges have a bunch of steerpoints used for targeting and
         drawing boxes that are not navigation. I would start from steerpoint 1
         and ignore anything after a break."

    A Viper's cartridge carries far more than a route: target points, mark
    points, the corners of a threat box, lines drawn on the HSD. They live at
    higher steerpoint numbers with a gap in front of them -- 1..5 then 81..89 --
    and the gap is the whole signal.

    A live one proved the point better than targeting data would have: 81 to 89
    were ARCOE, RONKY, WISTO, OLNIE, KRYSS, SHEET, ROTSE, JELIR, CADOS,
    descending fifteen thousand to nothing. A published STAR, every fix real and
    on the chart -- and still not this flight's route. Filed, it would have had
    a controller expecting him to fly an arrival he had merely loaded.

    `route_only=False` returns the lot, for anybody who wants to LOOK at a
    cartridge rather than fly it.
    """
    out = []
    for w in ((d.get("Waypoints") or {}).get("Waypoints") or []):
        out.append({"seq": int(w.get("Sequence") or 0),
                    "name": (w.get("Name") or "").strip(),
                    "lat": latlon(w.get("Latitude", "")),
                    "lon": latlon(w.get("Longitude", "")),
                    "alt_ft": int(w.get("Elevation") or 0)})
    out.sort(key=lambda w: w["seq"])
    if not route_only:
        return out
    route, want = [], 1
    for w in out:
        if w["seq"] < want:          # a duplicate or a zero -- not the route
            continue
        if w["seq"] != want:         # the gap. Everything past it is not the route.
            break
        route.append(w)
        want += 1
    return route


def ladder(d: dict) -> list[str]:
    """The aerodromes this sortie touches, in the order he will call them.

        "is the origin (Nellis) not in the DTC anywhere?"

    It is, and better than in the waypoints: the RADIO PRESETS name it. A comms
    ladder always opens at the departure field -- you cannot taxi anywhere else
    -- and closes at the arrival field's Tower or Ground:

        Kobuleti Clearance, Kobuleti Ground, Kobuleti Tower, Kobuleti Departure,
        Georgia Center, Batumi Approach, Batumi Tower, Batumi Ground

    Kobuleti to Batumi, said in order, with no geometry and no theatre. Nellis's
    ladder never leaves Nellis, which is exactly what a there-and-back is.

    Preferred over `nearest_field` because it needs neither `MARSHALL_THEATRE`
    nor a field table -- a Nevada cartridge read by a process that believes it is
    on the Caucasus resolved to nothing at all, origin and destination empty and
    a route of ", ".

    The station word is dropped and the rest is the field. Anything with no
    station word (a Center, a bullseye, a tanker) is not an aerodrome and is
    skipped, which is what keeps GEORGIA CENTER out of the middle of the route.
    """
    seats = ("clearance", "clnc", "delivery", "ground", "gnd", "tower", "twr",
             "departure", "dep", "approach", "app", "arrival", "atis",
             "director", "radar")
    out: list[str] = []
    for r in (d.get("Radios") or {}).values():
        for p in (r.get("Presets") or []):
            words = (p.get("Name") or "").replace("/", " ").split()
            if len(words) < 2:
                continue
            if words[-1].lower() not in seats:
                continue
            # A CENTER IS NOT AN AERODROME, and the SEAT word already says so:
            # "Georgia Center" and "Nellis Control" end in words no aerodrome
            # seat uses, so neither reaches here. Excluding them by FIELD name
            # instead -- which the first version did, to keep Georgia out of the
            # middle of a route -- also excluded Nellis, whose ladder is
            # entirely Nellis, leaving that cartridge with no ends at all.
            field = " ".join(words[:-1]).strip().title()
            if field and (not out or out[-1] != field):
                out.append(field)
    # Runs of one field collapse; the ORDER is what carries the meaning.
    seen: list[str] = []
    for f in out:
        if f not in seen:
            seen.append(f)
    return seen


def route_through(wps: list[dict], catalogue: dict, nm: float = 5.0) -> list[str]:
    """The PUBLISHED fixes this route actually passes near, and nothing else.

        "in civil avation, we dont make up our own random fixes in a flight
         plan though.. That's probably a difference here."

    A filed route is a SHARED PUBLISHED reference. Filing a name only one party
    can resolve is worse than filing none, because it reads as agreement.

    THE CATALOGUE IS PASSED IN, and the first version read the theatre's own
    fixes instead. Those hold DCS grid metres -- `x` and `z` -- and no lat/lon at
    all, so the comparison could never match and this silently returned nothing,
    every time. A Kobuleti-Batumi cartridge came out "direct" and that read as
    "no published fix nearby" when it meant "the question could not be asked".

    `/fixes` on the director holds name -> lat/lon, projected by the sim itself
    and pushed by the bridge, and it is what `filing.check_live` validates a
    route against. One table read by both, so a route this proposes cannot be
    refused by the thing that checks it.
    """
    from marshall.core import geo
    out: list[str] = []
    for w in wps:
        best, best_nm = "", nm
        for name, ll in (catalogue or {}).items():
            if not isinstance(ll, (list, tuple)) or len(ll) != 2:
                continue
            d, _ = geo.range_bearing_true((w["lat"], w["lon"]), ll[0], ll[1])
            if d < best_nm:
                best, best_nm = name.upper(), d
        if best and best not in out:
            out.append(best)
    return out


def named_steerpoints(wps: list[dict], fields: tuple = ()) -> dict:
    """His own turning points, by the names HE gave them -- name -> (lat, lon).

        "I have the ability give a description to every steerpoint. What if ATC
         uses this to reference in space that I pick."

    SHARED is not PUBLISHED. DIOMI is published: on every pilot's plate, for
    ever. FOO is not published and is perfectly shared -- he typed it, it is on
    his HSI, and the cartridge carried it here. "Report passing BAR" names a
    place they can both resolve, which is the entire job of a fix name.

    Not durable, and belonging to ONE aeroplane: his steerpoint two and a
    wingman's are different places. These die with the sortie.

    Anything DKS left unnamed stays out -- "STPT" is the absence of a name, not a
    name, and filing it would be back to inventing.
    """
    skip = {f.upper() for f in fields}
    out = {}
    for w in wps:
        n = (w["name"] or "").strip().upper()
        if not n or n in ("STPT", "WP") or n in skip:
            continue
        out[n] = [w["lat"], w["lon"]]
    return out


def plan_from(d: dict, name: str, approach: str = "", label: str = "",
              origin: str = "", catalogue: dict | None = None,
              steerpoints: bool = False) -> dict:
    """The cartridge as a filed plan: where he is going, and how high.

    BOTH ENDS COME FROM THE COMMS LADDER (`ladder`), which names them in order
    and needs no theatre. Falling back to the waypoint that IS an aerodrome, and
    then to the origin -- a sortie that ends nowhere in particular recovers where
    it started, which is what a local sortie is.

    THE CRUISE IS THE HIGHEST ENROUTE LEG. `flight_plans` holds one altitude and
    the cartridge holds one per waypoint; the number that matters is the one a
    controller must not be surprised by. Filing the first leg's five thousand
    while the pilot climbs to ten is the disagreement this exists to end.

    THE ROUTE IS THE ENROUTE PORTION, and empty is legal -- which is what
    "direct" means. Origin and destination have columns of their own; ICAO keeps
    field 13, field 15 and field 16 apart, and repeating the aerodromes inside
    the route was duplication that `check_live`'s "at least two fixes" rule had
    come to depend on. Both are fixed together, because either alone breaks the
    other: see #127.
    """
    wps = waypoints(d)
    if not wps:
        raise ValueError("no waypoints in the cartridge")
    seats = ladder(d)
    start = origin or (seats[0] if seats else "")
    dest = (seats[-1] if seats else "") or start
    if not start or not dest:
        # No usable ladder. Fall back to a waypoint that names an aerodrome --
        # DKS writes the field's own name on it -- and then to the other end.
        fields = [w["name"] for w in wps if w["name"] and w["name"] != "STPT"
                  and w["name"].upper() == w["name"].title().upper()]
        dest = dest or (fields[-1] if fields else "")
        start = start or dest
    ends = {(start or "").upper(), (dest or "").upper()}
    enroute = [w for w in wps if w["name"].upper() not in ends]
    cruise = max([w["alt_ft"] for w in enroute] or [w["alt_ft"] for w in wps])
    via = ([w["name"].strip().upper() for w in enroute
            if (w["name"] or "").strip().upper() not in ("", "STPT", "WP")]
           if steerpoints else route_through(enroute, catalogue or {}))
    return {"name": name, "label": label,
            "origin": (start or dest).title(),
            "destination": (dest or start).title(),
            "route": ", ".join(via), "cruise_ft": int(cruise),
            "task": "training", "approach": approach,
            "enroute": via, "ladder": seats}
