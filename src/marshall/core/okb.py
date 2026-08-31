"""A DKS kneeboard design, as data. The other way to file a route.

    "when using DKS, and a jet without a DTC (i.e. F4-C) it doesnt let us
     download the dtc file, so we need another way to import easily"

A data cartridge is an F-16 thing. The Phantom has no DTC to export, so a pilot
flying one had no way to hand us his route at all -- and `core/dtc.py`, which is
the only importer, cannot help him. This is the same route arriving by a
different door.

WHY THE API AND NOT THE PAGE. The obvious reading of "parse the kneeboard page"
is to fetch the URL and read the HTML, and there is nothing in it: the site is a
Next.js application whose served markup is the words "Loading kneeboard..." and
a script tag. The steerpoints arrive afterwards, from

    GET /api/public/design/<uuid>

which the page's own bundle calls and which needs no key. Scraping the rendered
DOM would need a browser; asking the same endpoint the page asks needs `urllib`.

IT IS A BETTER SOURCE THAN THE CARTRIDGE, which is worth saying plainly because
it looks like the fallback. The DTC carries degrees-and-decimal-minutes as
strings that have to be parsed back into numbers; this carries decimal degrees.
The DTC hides target points and threat-box corners among the route and needs the
gap rule to tell them apart; this keeps `targets`, `threats` and `dmpis` in their
own arrays and leaves `waypoints` meaning the route.

WHAT IT DOES NOT CARRY is the comms ladder. A cartridge's `Radios` block names
the seats in order, and `dtc.plan_from` uses that to know where a sortie starts
and ends. A DKS design has a comms card, and on a real one it is often empty --
so `ladder` here returns what is filled in and nothing when it is not, and the
caller falls back to the aerodromes named in the route. Empty is an answer.

NOTHING HERE DECIDES ANYTHING and nothing here is theatre-aware. It reads a
design into the same shape `dtc.waypoints` produces, so everything downstream --
`route_through`, `named_steerpoints`, `plan_from_route` -- is shared rather than
written twice for a second wire format. Two importers that build a plan each
their own way is how two readers come to disagree about what a pilot filed.
"""
from __future__ import annotations

import json
import re
import urllib.request

API = "https://www.digitalkneeboardsimulator.com/api/public/design/"

# A design is identified by a UUID. A pilot will paste whatever he has: the
# whole viewer URL with its `?design=` and `&pilot=`, a share link, or the bare
# id out of one. All three are the same fact.
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def design_id(text: str) -> str:
    """The design UUID out of whatever the pilot pasted, or "".

    Deliberately not a URL parser. `?design=` is where it lives today and the
    query string has already changed shape once (`&pilot=` is newer than the
    page); a UUID in the text is the durable signal, and there is only ever one.
    """
    hit = _UUID.search(text or "")
    return hit.group(0).lower() if hit else ""


def fetch(text: str, read=None, timeout: float = 15.0) -> dict:
    """The design behind a URL or an id. Raises on anything that is not one.

    `read` is the seam: tests hand in the payload rather than the network, and
    the shape they exercise is the real one -- the fixture is a captured
    response, not an invention.
    """
    ident = design_id(text)
    if not ident:
        raise ValueError(
            "no design id in that -- paste the kneeboard URL or its id")
    if read is not None:
        raw = read(ident)
    else:
        with urllib.request.urlopen(API + ident, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    got = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(got, dict) or "formData" not in got:
        raise ValueError("that is not a DKS design")
    return got


def waypoints(design: dict, route_only: bool = True) -> list[dict]:
    """The route, in the shape `dtc.waypoints` returns it.

    THE SAME GAP RULE, and for the same reason even though this format is
    tidier. DKS keeps targets and threats in their own arrays, so the route
    should already be 1..N with nothing else in it -- but "should" is what the
    cartridge also looked like until a live one had a published STAR sitting at
    81..89. A numbering hole means the rest is not this flight's route.
    """
    out = []
    for w in (design.get("formData") or {}).get("waypoints") or []:
        try:
            lat, lon = float(w["lat"]), float(w["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"seq": int(w.get("number") or 0),
                    # `description` is the pilot's own name for the point --
                    # DEPARTURE, INGRESS, Batumi. `type` is STPT for all of
                    # them and is not a name.
                    "name": (w.get("description") or "").strip(),
                    "lat": lat, "lon": lon,
                    "alt_ft": int(float(w.get("elevation") or 0))})
    out.sort(key=lambda w: w["seq"])
    if not route_only:
        return out
    route, want = [], 1
    for w in out:
        if w["seq"] < want:
            continue
        if w["seq"] != want:
            break
        route.append(w)
        want += 1
    return route


def comms_card(design: dict) -> list[str]:
    """The comms card's agencies in channel order, or [] when it is blank.

    NAMED FOR WHAT DKS CALLS IT, and not `ladder`, which is what the cartridge
    reader calls its equivalent. Two functions with one name in two format
    readers reads as symmetry and costs more than it pays: a reader has to
    check which one is meant, and `tools/unwired.py` could no longer attribute
    a bare call to either, so `dtc.ladder` came back as reachable only from its
    own tests.

    EMPTY IS AN ANSWER AND NOT A FAILURE. The card is optional in DKS and the
    designs seen so far carry channel numbers with no agencies against them, so
    a caller must fall back to the aerodromes named in the route rather than
    treat this as an error. See `dtc.ladder`, which reads the equivalent block
    out of a cartridge and where it is usually filled in.
    """
    f = design.get("formData") or {}
    out, n = [], 1
    while f.get(f"co-{n}-ch") is not None:
        who = (f.get(f"co-{n}-agency1") or "").strip()
        if who:
            out.append(who)
        n += 1
    return out


def facts(design: dict) -> dict:
    """Everything about the sortie that is not the route.

    The home plate block is the useful half: DKS records the recovery field's
    runway, ILS, TACAN and its VHF/UHF pair as the PILOT has them, which is a
    direct read on whether his kneeboard and our controllers agree about a
    frequency. They did not on the first design seen -- his card said Batumi was
    131.00, which is the sim's simplified number, against the published 118.600
    this project uses.
    """
    f = design.get("formData") or {}
    start = f.get("startPoint") or {}
    crew = []
    n = 1
    while f.get(f"cr-{n}-cs") is not None:
        crew.append({"callsign": (f.get(f"cr-{n}-cs") or "").strip(),
                     "pilot": (f.get(f"cr-{n}-crew") or "").strip()})
        n += 1
    return {
        "name": (design.get("name") or "").strip(),
        "aircraft": (design.get("plane") or "").strip(),
        "theatre": (design.get("theater") or "").strip(),
        "flight": (design.get("flightCallsign") or "") or "",
        "crew": crew,
        "start": ({"lat": float(start["lat"]), "lon": float(start["lng"]),
                   "alt_ft": int(float(start.get("elevation") or 0))}
                  if start.get("lat") is not None else None),
        "home_plate": {
            "field": (f.get("hp-1-field") or "").strip(),
            "runway": (f.get("hp-1-rw") or "").strip(),
            "ils": (f.get("hp-1-ils") or "").strip(),
            "tacan": (f.get("hp-1-tcn") or "").strip(),
            "radios": (f.get("hp-1-vuhf") or "").strip(),
        },
    }


def origin_from_start(design: dict, catalogue: dict, nm: float = 3.0) -> str:
    """The aerodrome he is PARKED at, named by matching `startPoint`.

    WITHOUT THIS THE ROUTE NAMES ONE END. A DKS design's waypoints begin at the
    first point after take-off -- DEPARTURE, INGRESS, ... -- so the only
    aerodrome in the list is the recovery field, and `plan_from_route` falls
    back to it for BOTH ends. The first real design read this way filed as
    Batumi to Batumi for a sortie that departs Kobuleti.

    `startPoint` is the answer and the cartridge has no equivalent: a position
    with an elevation and no name, which the design carries separately from the
    route. Matching it to a published aerodrome is the same proximity question
    `route_through` asks of the waypoints, so the catalogue is the same shape --
    name -> (lat, lon) -- and passed in for the same reason. This module knows
    nothing about which map is loaded.

    Three nautical miles rather than five: this is asking "which ramp is he
    standing on", not "which fix did he pass near", and Kobuleti and Batumi are
    twenty-odd apart.
    """
    from marshall.core import geo as _geo
    start = (design.get("formData") or {}).get("startPoint") or {}
    if start.get("lat") is None:
        return ""
    here = (float(start["lat"]), float(start["lng"]))
    best, best_nm = "", nm
    for name, pos in (catalogue or {}).items():
        try:
            d_nm, _ = _geo.range_bearing_true(here, float(pos[0]), float(pos[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if d_nm <= best_nm:
            best, best_nm = name, d_nm
    return best
