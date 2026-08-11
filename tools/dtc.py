"""Read a DKS data cartridge, and file the plan the pilot is actually flying.

    "why wouldnt we file the flight plan to match the DTC data exactly?"
    "and then ATC should be fully aware of what I am doing at what altitude"

No reason, and that is the point. Marshall's filed plan said KOBULETI, INITIAL,
BATUMI at five thousand; the cartridge in the jet said seven miles east, nine
north, thirteen west over the water, at ten. So Clearance would have read back a
route he was not flying at an altitude he was not holding, and every controller
after it would have had the wrong expectation of where he was going -- which
turns an ordinary climb into a level bust and an ordinary turn into a deviation.

WHAT IT DOES NOT DO IS NAME HIS TURNING POINTS. An earlier version filed them as
STPT1/2/3 so the route could reference them, on the argument that he can see his
own steerpoints in the cockpit -- and that is wrong for the same reason CHAKVI
was wrong:

    "in civil avation, we dont make up our own random fixes in a flight plan
     though.. That's probably a difference here."

A filed route is a SHARED PUBLISHED reference. His cartridge is published to
nobody, so a fix only one party can resolve is worse than none: it reads as
agreement. What a radar controller needs is the destination, the altitude and a
return on the scope -- see `route_through`.

THE FORMAT is four bytes of little-endian uncompressed length, then a gzip
stream, then JSON. Waypoints carry degrees-and-decimal-minutes strings and a
per-waypoint elevation; `Radios` carries the preset ladder; `Misc` carries the
ILS, TACAN and bingo. Nothing here is guessed -- it was read off a live export.

    uv run python tools/dtc.py --show < cartridge.txt
    uv run python tools/dtc.py --file 362nd-kobuleti-batumi < cartridge.txt
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

BASE = "http://localhost:8000"

# Degrees and decimal minutes, as DKS writes them: a hemisphere letter, a degree
# sign, then minutes. The trailing mark is a typographic apostrophe rather than a
# prime, which is why nothing here matches on it -- a cartridge that has been
# through a clipboard is not guaranteed to keep it.
_LL = re.compile(r"([NSEW])\s*(\d+)[°\s]+([\d.]+)")


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


def existing_label(name: str, base: str = BASE) -> str:
    """The spoken name this plan already has, if it is on the board.

    A LABEL IS NOT DERIVABLE FROM A FILE NAME and must not be invented here.
    `filing` refuses anything that is not one sayable word -- "Samovar One" and
    "Samovar Two" are how the wrong sortie gets cleared -- and a plan already on
    the board already has one a pilot has heard. Re-deriving it from
    `362nd-kobuleti-batumi` produced "362Nd Kobuleti Batumi", which is three
    words and two digits, and was correctly refused.
    """
    try:
        with urllib.request.urlopen(f"{base}/plans", timeout=10) as r:
            for p in (json.loads(r.read()).get("plans") or []):
                if (p.get("name") or "") == name:
                    return p.get("label") or ""
    except Exception:
        pass
    return ""


def named_steerpoints(wps: list[dict]) -> dict:
    """His own turning points, by the names HE gave them -- name -> (lat, lon).

        "I have the ability give a description to every steerpoint. What if ATC
         uses this to reference in space that I pick."

    The distinction that took two mistakes to find is SHARED versus PUBLISHED,
    not published versus invented. DIOMI is published: it is on every pilot's
    plate for ever. FOO is not published and is still perfectly shared -- he
    typed it, it is on his HSI, and the cartridge carried it here. A controller
    saying "report passing BAR" is naming a place they can both resolve, which
    is the entire job a fix name does.

    What it is NOT is durable. A published fix outlives the sortie; these die
    with it, and they belong to ONE aeroplane -- his steerpoint two and a
    wingman's are different places. So they are only ever pushed for a flight
    that filed them, and the bridge's own catalogue push at start-up replaces
    the table, which takes them off it. That is the lifecycle working, not a
    bug, but it does mean this tool is re-run after a restart.

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


def plan_from(d: dict, name: str, approach: str = "", label: str = "",
              origin: str = "", steerpoints: bool = False) -> dict:
    """The cartridge as a filed plan: where he is going, and how high.

    THE CRUISE IS THE HIGHEST ENROUTE LEG, not the first. `flight_plans` holds
    one altitude and the cartridge holds one per waypoint, so something has to
    give -- and the number that matters is the one a controller must not be
    surprised by. Filing the first leg's five thousand while the pilot climbs to
    ten is precisely the disagreement this tool exists to end.
    """
    wps = waypoints(d)
    if not wps:
        raise ValueError("no waypoints in the cartridge")
    from marshall.core import theatre as _t
    th = _t.current()
    fields = {f.name.upper() for f in th.fields}
    start = (origin or th.departure or "").upper()
    # The destination is the last waypoint that is an aerodrome. A cartridge
    # ending nowhere in particular recovers where it started, which is what a
    # local sortie is.
    dest = next((w["name"].upper() for w in reversed(wps)
                 if w["name"].upper() in fields), start)
    enroute = [w for w in wps if w["name"].upper() not in fields]
    cruise = max([w["alt_ft"] for w in enroute] or [w["alt_ft"] for w in wps])
    # HIS NAMES, or only the published ones. See `named_steerpoints` on why
    # both are defensible and why they are not the same kind of thing.
    via = ([w["name"].strip().upper() for w in enroute
            if (w["name"] or "").strip().upper() not in ("", "STPT", "WP")]
           if steerpoints else route_through(enroute))
    route = [start, *via, dest]
    return {"name": name,
            "label": label,
            "origin": start.title(), "destination": dest.title(),
            "route": ", ".join(route), "cruise_ft": int(cruise),
            "task": "training", "approach": approach or th.approach_key}


def _put(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="PUT",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true", help="print it and stop")
    ap.add_argument("--file", default="", metavar="NAME",
                    help="file it as a plan under this name")
    ap.add_argument("--approach", default="", help="the recovery to fly")
    ap.add_argument("--steerpoints", action="store_true",
                    help="file HIS named turning points and put them on the "
                         "fix table for this sortie -- shared with him, not "
                         "published to anybody else. See `named_steerpoints`")
    ap.add_argument("--label", default="",
                    help="the ONE word a pilot says to request it; kept from "
                         "the board when the plan is already filed")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("cartridge", nargs="?", default="-",
                    help="a file, or - for stdin")
    args = ap.parse_args(argv)

    text = (sys.stdin.read() if args.cartridge == "-"
            else Path(args.cartridge).read_text())
    try:
        d = decode(text)
    except Exception as e:
        print(f"!! not a cartridge: {e}", file=sys.stderr)
        return 2

    wps = waypoints(d)
    print(f"{d.get('Aircraft', '?')}, {len(wps)} waypoints")
    for w in wps:
        print(f"   {w['seq']}  {(w['name'] or 'STPT'):8} {w['lat']:9.5f} "
              f"{w['lon']:9.5f} {w['alt_ft']:>7} ft")
    m = d.get("Misc") or {}
    if m:
        print(f"   ILS {m.get('ILSFrequency')} / {m.get('ILSCourse')}"
              f"   TACAN {m.get('TACANChannel')}"
              f"{'XY'[m.get('TACANBand', 0)]}")
    for rk, r in (d.get("Radios") or {}).items():
        pres = r.get("Presets") or []
        print(f"   {rk}: " + "  ".join(f"{p['Number']}:{p['Frequency']}"
                                       for p in pres))
    if args.show or not args.file:
        return 0

    plan = plan_from(d, args.file, approach=args.approach,
                     label=args.label or existing_label(args.file, args.base),
                     steerpoints=args.steerpoints)
    if not plan["label"]:
        print(f"!! {args.file} is not on the board and has no --label. A plan "
              f"needs ONE sayable word for a pilot to request it by.",
              file=sys.stderr)
        return 2
    print(f"\nfiling {plan['name']}: {plan['route']} at {plan['cruise_ft']}, "
          f"recovering on {plan['approach']}")
    if args.steerpoints:
        # PUSHED SO THE ROUTE CAN BE VALIDATED. `filing.check_live` refuses a
        # route naming a fix the table does not hold, and it is right to -- a
        # plan validated against fixes that do not exist is a plan nobody can
        # be cleared on.
        #
        # MERGED, NOT REPLACED, and this cost a catalogue. `set_fixes` says in
        # its own docstring that THE PUSHED SET REPLACES THE TABLE -- which is
        # right for the bridge, whose push is the whole theatre, and fatal here,
        # where it is three steerpoints. It wiped all twenty-one and the very
        # next filing was refused with "no fix called KOBULETI". Read the
        # catalogue, add to it, push the union.
        sp = named_steerpoints(wps)
        if sp:
            have = {}
            try:
                with urllib.request.urlopen(f"{args.base}/fixes", timeout=10) as r:
                    have = json.loads(r.read()).get("fixes") or {}
            except Exception:
                pass
            if not have:
                print("!! the fix table is empty -- start the bridge first, it "
                      "pushes the theatre's catalogue", file=sys.stderr)
                return 2
            _put(f"{args.base}/fixes", {"fixes": {**have, **sp}})
            print(f"  his steerpoints, for this sortie: {', '.join(sp)}")
    try:
        out = _post(f"{args.base}/plans",
                    {**plan, "updating": plan["name"]})
    except urllib.error.HTTPError as e:
        print(f"!! refused: {e.read().decode()[:300]}", file=sys.stderr)
        return 1
    if not out.get("filed"):
        print(f"!! refused: {out.get('refused')}", file=sys.stderr)
        return 1
    for w in out.get("warnings") or []:
        print(f"  .. {w}")
    print(f"  filed as {out.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
