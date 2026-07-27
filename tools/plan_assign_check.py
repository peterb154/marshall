"""Two flights, two plans, at the same time -- and neither treads on the other.

FP-1 on the card (#1). The sweep next door asks whether the controller finds the
RIGHT plan; this asks whether giving one out is safe when more than one aeroplane
is doing it, which is the whole reason plans became templates.

    uv run python tools/plan_assign_check.py        # a running director

What it drives, in order, against a scratch mission so nothing touches tonight's
board:

  1. two flights hold DIFFERENT plans at once
  2. the same template goes to two flights at once
  3. amending one flight's routing leaves the other alone -- AND leaves the
     filed template alone, which is the point of copying rather than pointing
  4. assignment stamps the flight's own row, because that is what everything
     else reads
  5. a read-back is recorded, and an amendment un-records it: he agreed to the
     clearance he was given, not to the one that replaced it
  6. a flight with NO plan still behaves, since that is still the normal case

Every check reads the state back over HTTP rather than trusting the write, and
the scratch mission is deleted at the end whether or not anything failed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
MISSION = "planassigncheck"


def _json(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def bind(callsign: str) -> int:
    return _json("POST", "/flights/bind",
                 {"mission": MISSION, "callsign": callsign})["id"]


def assign(fid: int, **body) -> dict:
    return _json("POST", f"/flights/{fid}/assign-plan", {"mission": MISSION, **body})


def flights() -> dict[str, dict]:
    got = _json("GET", f"/flights?mission={MISSION}")["flights"]
    return {f["callsign"]: f for f in got}


def main() -> int:
    ok = True

    def check(good: bool, what: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {what}")
        if detail:
            print(f"        {detail}")

    try:
        plans = _json("GET", "/plans")["plans"]
    except (urllib.error.URLError, OSError) as e:
        print(f"no director on {BASE}: {e}")
        return 2
    if len(plans) < 2:
        print(f"need at least two filed plans, found {len(plans)}")
        return 2
    a, b = plans[0], plans[1]

    try:
        lead, wing = bind("Hoover 1-1"), bind("Hoover 1-2")

        print("two flights, two different plans")
        assign(lead, plan=a["name"])
        assign(wing, plan=b["name"])
        rows = flights()
        check(rows["Hoover 1-1"]["flight_plan"] == a["name"]
              and rows["Hoover 1-2"]["flight_plan"] == b["name"],
              "each flight holds its own",
              f"{rows['Hoover 1-1']['flight_plan']} / "
              f"{rows['Hoover 1-2']['flight_plan']}")
        check(rows["Hoover 1-1"]["route"] == a["route"],
              "the flight's own row is stamped, not just the copy",
              rows["Hoover 1-1"]["route"] or "(empty)")

        print("\nthe same template, twice at once")
        assign(wing, plan=a["name"])
        rows = flights()
        check(rows["Hoover 1-1"]["flight_plan"] == rows["Hoover 1-2"]["flight_plan"]
              == a["name"], "one plan flown by two aeroplanes")

        print("\namending one of them")
        amended = "BATUMI, FEET WET, BATUMI"
        assign(wing, plan=a["name"], route=amended)
        rows = flights()
        check(rows["Hoover 1-2"]["route"] == amended,
              "the amendment took", rows["Hoover 1-2"]["route"])
        check(rows["Hoover 1-1"]["route"] == a["route"],
              "the OTHER aeroplane is untouched", rows["Hoover 1-1"]["route"])
        filed_now = {p["name"]: p for p in _json("GET", "/plans")["plans"]}
        check(filed_now[a["name"]]["route"] == a["route"],
              "and so is what was FILED -- next week's plan is not tonight's",
              filed_now[a["name"]]["route"])

        print("\nread-backs")
        _json("POST", f"/flights/{lead}/clearance-ack")
        check(bool(flights()["Hoover 1-1"]["clearance_ack"]),
              "a read-back is recorded")
        _json("POST", f"/flights/{lead}/clearance-ack")
        assign(lead, plan=b["name"])
        check(not flights()["Hoover 1-1"]["clearance_ack"],
              "an amendment un-records it -- he agreed to the OLD clearance")

        print("\nnothing on file")
        alone = bind("Viper 2-1")
        rows = flights()
        check(rows["Viper 2-1"]["flight_plan"] in (None, ""),
              "a flight with no plan is still a normal flight")
        # The callsign goes with the request on purpose: without knowing who is
        # calling, his own name is a word that matches no plan and the resolver
        # cannot tell "somewhere nobody filed for" from "he named nothing".
        got = assign(alone, callsign="Viper 2-1",
                     said="request clearance to Vaziani")
        check(bool(got.get("none")),
              "and asking for one nobody filed is refused, not guessed",
              json.dumps(got)[:80])
    finally:
        try:
            _json("DELETE", f"/flights?mission={MISSION}")
        except (urllib.error.URLError, OSError):
            print("  !! could not clean up the scratch mission")

    print("\nall cases behaved" if ok else "\nSOME CASES FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
