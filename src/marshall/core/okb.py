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


AGENCIES = "https://www.digitalkneeboardsimulator.com/api/public/agencies"


def comms_card(design: dict, resolve=None, timeout: float = 15.0) -> list[dict]:
    """His radio card: channel, agency and frequency, in channel order.

    THE FREQUENCIES ARE NOT IN THE DESIGN. Each channel carries an agency
    REFERENCE -- `co-1-agency1-id` is set while `co-1-agency1` and `co-1-freq1`
    are both "" -- and the card is resolved at render time from the squadron's
    agency library:

        POST /api/public/agencies   {"ids": [...], "squadronId": "..."}
        -> [{"id": ..., "name": "Kobuleti ATIS", "frequency": "279.000", ...}]

    I RECORDED THAT THIS COULD NOT BE DONE, and it was a misreading. Guessing
    `/api/public/squadron/<id>/agencies` returned 404 and
    `/api/public/agencies?squadronId=` returned 405, and I read the pair as "no
    such endpoint" -- 405 is METHOD NOT ALLOWED and was the endpoint saying the
    path was right and the verb was wrong. A pilot looking at his own kneeboard
    could see the frequencies I had just called unreadable.

    WHAT IT IS FOR. This is the pilot's card as HE has it, against a theatre
    file that is ours, so the two can be compared instead of hoped about: on the
    design that prompted it every channel agreed with what we publish, which is
    a thing worth being able to say rather than assume.

    `resolve` is the seam -- tests hand back the library rather than the
    network. Without one, or when the fetch fails, the channels come back with
    whatever the design spells out, which is usually the numbers and nothing
    else. A card that cannot be read is not a card that is empty.
    """
    f = design.get("formData") or {}
    rows, ids = [], []
    n = 1
    while f.get(f"co-{n}-ch") is not None:
        rows.append({"channel": str(f.get(f"co-{n}-ch") or "").strip(),
                     "agency": (f.get(f"co-{n}-agency1") or "").strip(),
                     "freq_mhz": (f.get(f"co-{n}-freq1") or "").strip(),
                     "_id": (f.get(f"co-{n}-agency1-id") or "").strip()})
        n += 1
    ids = [r["_id"] for r in rows if r["_id"] and not r["agency"]]
    library = {}
    if ids:
        try:
            got = (resolve(ids, design.get("squadronId") or "")
                   if resolve is not None
                   else _agencies(ids, design.get("squadronId") or "", timeout))
            library = {a.get("id"): a for a in (got or []) if isinstance(a, dict)}
        except Exception:
            library = {}
    out = []
    for r in rows:
        a = library.get(r.pop("_id"), {})
        r["agency"] = r["agency"] or (a.get("name") or "")
        r["freq_mhz"] = r["freq_mhz"] or (a.get("frequency") or "")
        if r["agency"] or r["freq_mhz"]:
            out.append(r)
    return out


def _agencies(ids: list[str], squadron: str, timeout: float) -> list:
    body = json.dumps({"ids": ids, "squadronId": squadron}).encode()
    req = urllib.request.Request(
        AGENCIES, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


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


# What a kneeboard abbreviates a facility to, against the word we use. His card
# says "Kobuleti CLNC" and our station is "Kobuleti Clearance"; neither is
# wrong, and a comparison that insisted on one spelling would report every
# channel as a disagreement and teach a pilot to ignore the check.
_ROLE_WORDS = {
    "clnc": "clearance", "cd": "clearance", "del": "clearance",
    "delivery": "clearance", "gnd": "ground", "twr": "tower",
    "dep": "departure", "app": "approach", "ctr": "center", "cen": "center",
    "ctrl": "center", "atis": "atis",
}


def _role_of(agency: str) -> tuple[str, str]:
    """(field words, role) out of an agency name like "Kobuleti CLNC"."""
    words = [w for w in re.split(r"[\s/_-]+", (agency or "").strip()) if w]
    if not words:
        return "", ""
    role = _ROLE_WORDS.get(words[-1].lower(), words[-1].lower())
    return " ".join(words[:-1]).lower(), role


def check_card(card: list[dict], stations, atis: dict | None = None) -> list[str]:
    """Where the pilot's radio card and our theatre disagree. Plain sentences.

        "its a good thing though, to double check the agencies on import. PITA
         to have something wrong."

    A frequency he cannot reach us on is the worst kind of wrong, because it
    fails silently and in the air: he calls, nobody answers, and neither end
    knows which of them is on the wrong number. It is cheap to find here and
    expensive to find at four hundred knots.

    ONLY WHAT IT CAN JUDGE. A channel naming a facility this map does not have
    is reported as unknown rather than as a mismatch -- squadrons carry agencies
    for every theatre they fly, and a Nevada seat on a Caucasus card is his
    library being bigger than this sortie, not an error. Anything it cannot
    parse is left alone entirely: a check that cries wolf is a check somebody
    turns off, which is the same argument `clearance.unbacked` makes.

    `stations` and `atis` are passed in for the reason everything else here
    takes its facts as arguments -- this module knows nothing about which map
    is loaded, and a Caucasus frequency judged against Nevada's ladder would be
    wrong in a way nobody would see.
    """
    from marshall.core import names as _names
    out = []
    for row in card or []:
        agency, want = row.get("agency", ""), (row.get("freq_mhz") or "").strip()
        if not agency or not want:
            continue
        try:
            mhz = float(want)
        except ValueError:
            continue
        field, role = _role_of(agency)
        if role == "atis":
            have = [v for k, v in (atis or {}).items()
                    if _names.squash(k) == _names.squash(field) and v]
            if have and not any(abs(mhz - float(h)) < 0.0005 for h in have):
                out.append(f"ch {row.get('channel')}: his card has {agency} on "
                           f"{want}, we broadcast on "
                           f"{', '.join(f'{float(h):.3f}' for h in have)}")
            continue
        seat = next((s for s in stations
                     if (role == (getattr(s, "role", "") or "").lower()
                         or role in [str(a).lower() for a in getattr(s, "also", ())])
                     and _names.squash(getattr(s, "field", "") or "")
                     == _names.squash(field)), None)
        if seat is None:
            continue                      # not this map's -- see the docstring
        freqs = [float(f) for f in getattr(seat, "freqs", (seat.freq_mhz,))]
        if not any(abs(mhz - f) < 0.0005 for f in freqs):
            out.append(f"ch {row.get('channel')}: his card has {agency} on "
                       f"{want}, {seat.name} answers on "
                       f"{', '.join(f'{f:.3f}' for f in freqs)}")
    return out
