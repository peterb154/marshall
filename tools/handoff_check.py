"""Does the handoff fire where it should? Checked against real tracks, no pilot.

C5 and C6 on the flight test card -- Center keeps a departing flight until it
leaves his airspace, and hands an arriving one to Approach normally -- were
marked as needing a human. They do not. The decision is a function of a
POSITION and a CONTROLLER, and both can be arranged: spawn an aircraft where the
question is interesting, bind it, say who is working it, and read the answer.

    uv run python tools/handoff_check.py

What it exercises, and why each case is here:

  inbound, far out      Center keeps him. Nothing to do yet.
  inbound, close        Center gives him to Approach -- the ordinary arrival,
                        and the case a change to the outbound rule could break.
  outbound, close       Center KEEPS him. Range alone says "inside 25 miles, so
                        Approach's problem", which is how a flight departing on
                        a CAS sortie was handed off and then never handed back.
  outbound, far         he has left, so Center is done with him.
  on a talkdown         NEVER handed over, whatever the airspace says. Tower's
                        volume has a 4,000 ft ceiling and an aircraft descending
                        the final sits inside it.

Spawns are cleaned up at the end. Nothing here writes to the live mission beyond
the aircraft it creates.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


from marshall.atc import agent_atc as A
from marshall.core import route as R

BASE = os.environ.get("MARSHALL_BASE", "http://localhost:8000")
MISSION = "handoff-check"


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def _spawn(name: str, bearing: float, rng: float, alt: int, heading: int) -> None:
    import subprocess
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "spawn.py"),
         "--name", name, "--type", "mustang", "--count", "1",
         "--alt", str(alt), "--heading", str(heading),
         "--at", "batumi", "--bearing", str(bearing), "--range", str(rng),
         "--side", "blue"],
        capture_output=True, env={**os.environ,
                                  "PYTHONPATH": str(ROOT / "src")})


# The sim numbers the units inside a spawned group, so a group called "HC-out"
# arrives in `tracks` as "HC-out-1". Binding the group name joins to nothing and
# the airspace view silently returns no row -- which reads exactly like "no
# handoff due" and would have made this whole check pass while testing nothing.
def _track(group: str) -> str:
    return f"{group}-1"


def case(name: str, track: str, callsign: str, working_with: str,
         me_role: str, fix, expect: str | None) -> bool:
    """One question, asked of the real code with a real track behind it."""
    profile = R.BATUMI_ASR
    me = profile.station_for(me_role)
    _post("/flights/bind", {"mission": MISSION, "callsign": callsign,
                            "track_name": _track(track)})
    rows = _get(f"/flights?mission={MISSION}")["flights"]
    fid = next((r["id"] for r in rows if r.get("callsign") == callsign), None)
    if fid is not None:
        _post(f"/flights/{fid}/agree", {"controller": working_with})

    got = A.leaving_my_airspace(BASE, "handoff-check", callsign, me, profile,
                                fix, mission=MISSION)
    got_name = got.name if got else None
    ok = (got_name == expect)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"        working with {working_with}, expected "
          f"{expect or 'no handoff'}, got {got_name or 'no handoff'}")
    return ok


def main() -> int:
    from marshall.atc import asr
    p = R.BATUMI_ASR
    inbound = (p.final_crs + 180) % 360

    print(f"spawning traffic for the handoff cases (mission {MISSION!r})\n")
    _spawn("HC-out", 330, 18, 8000, 330)      # departing, still close in
    _spawn("HC-in", inbound, 30, 9000, int(p.final_crs))   # arriving, far out
    _spawn("HC-gone", 300, 45, 11000, 300)    # well outside anybody's terminal
    time.sleep(14)

    def at(nm, radial, alt, hdg):
        return asr.Position(range_nm=nm, radial_deg=radial, alt_ft=alt,
                            heading_deg=hdg)

    results = [
        # A talkdown in progress outranks geography -- Tower's volume has a
        # 4,000 ft ceiling and a descending aircraft is inside it.
        case("talkdown inside the final is never handed over", "HC-in",
             "Pony 1-1", "batumi-approach", "approach",
             at(8, inbound, 2500, p.final_crs), None),
        case("outbound and still inside: Center keeps him", "HC-out",
             "Pony 2-1", "georgia-center", "center",
             at(18, 330, 8000, 330), None),
        case("arriving: route.py's own rules still own it", "HC-in",
             "Pony 3-1", "georgia-center", "center",
             at(30, inbound, 9000, p.final_crs), None),
        # THE POSITIVE CASE. Without one, a function that always answered "no
        # handoff" would pass every test above -- which is most of what a
        # handoff check is for.
        case("flown out of Approach's airspace: hand him back to Center",
             "HC-gone", "Pony 4-1", "batumi-approach", "approach",
             at(45, 300, 11000, 300), "Georgia Center"),
    ]
    print()
    ok = all(results)
    print("all cases behaved" if ok else "SOME CASES FAILED")

    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{BASE}/flights?mission={MISSION}", method="DELETE"), timeout=10)
    except Exception:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
