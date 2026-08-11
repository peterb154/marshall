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
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

BASE = "http://localhost:8000"

# THE PARSER LIVES IN `core.dtc`, not here. The kneeboard's filing page reads
# the same cartridges in a browser, and a wire format owned by one caller is a
# format the other copies -- which is how two readers come to disagree about
# what a pilot filed.
from marshall.core.dtc import (
    decode, named_steerpoints, plan_from, waypoints)


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
