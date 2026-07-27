"""Does the controller find the plan a pilot actually asked for?

FP-1 on the card -- #1 -- and the reason it is a sweep rather than a flight test
is that the thing under test is a MATCH, not a manoeuvre. Reading fifty phrasings
at a controller over the radio would cost an evening; here it costs a second, and
the evening can be spent on something only an aeroplane can tell us.

    uv run python tools/plan_sweep.py
    uv run python tools/plan_sweep.py --live      # against a running director

Three outcomes are all correct, and telling them apart is the whole job:

  MATCH      exactly one plan fits. He is cleared.
  ASK        more than one fits. The controller ASKS, and must not choose --
             the same rule as a formation he cannot tell apart.
  NONE       nothing on file fits. He says so rather than clearing him on the
             nearest thing, which would be an aeroplane routed somewhere nobody
             asked to go.

The failure this guards is the quiet one. A resolver that always picks the
best-scoring plan never asks a question and looks perfect in a demo, because
every request produces a clearance -- including the requests that were ambiguous,
where the clearance is for somebody else's sortie.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "director"))

from tools import plans as P

# Mirrors migrations/011. Kept here so the sweep runs with no database, no
# container and no network -- the point of a tier-1 check is that there is
# nothing to bring up first. `--live` reads the real rows instead, which is how
# you catch this copy drifting from what is actually on file.
FILED = [
    {"name": "362nd-batumi-asr", "label": "Samovar One", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 11000,
     "route": "BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI",
     "task": "CAS over Tsutsnvati"},
    {"name": "362nd-batumi-ndb", "label": "Samovar Two", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 11000,
     "route": "BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI",
     "task": "CAS over Tsutsnvati, beacon letdown on return"},
    {"name": "362nd-kutaisi-transit", "label": "Samovar Three", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 7000,
     "route": "BATUMI, FEET WET, KUTAISI, BATUMI",
     "task": "Transit up the coast, turning at Kutaisi"},
]

# (what he says, what should happen, why this phrasing is in the list)
CASES = [
    # -- named outright. The escape hatch, and it has to be exact-proof.
    ("Batumi Approach, Hoover one one, request clearance, Samovar Three",
     "362nd-kutaisi-transit", "the label, said plainly"),
    ("Hoover one one, IFR clearance on file, Samovar Three, ready to copy",
     "362nd-kutaisi-transit", "the label buried in the middle of a request"),

    # -- by the task, which is how a pilot thinks about it.
    ("Hoover one one, request clearance for the transit to Kutaisi",
     "362nd-kutaisi-transit", "the task in his own words"),
    ("Hoover one one, ready to copy IFR, we're going up the coast today",
     "362nd-kutaisi-transit", "the task, paraphrased"),

    # -- by a place on the route. "CAS over Tsutsnvati" names two plans, so the
    #    controller must ASK. This is the case a best-score-wins resolver gets
    #    confidently and silently wrong.
    ("Hoover one one, request clearance for the CAS over Tsutsnvati",
     "ASK", "a task that fits two plans"),
    ("Hoover one one, clearance for the Tsutsnvati mission",
     "ASK", "a place that fits two plans"),
    ("Hoover one one, request clearance, the one with the beacon letdown",
     "362nd-batumi-ndb", "the words that tell the two apart"),

    # -- the civil form, which separates nothing here: everything comes home to
    #    Batumi, so a destination match must not be enough on its own.
    ("Hoover one one, IFR to Batumi, ready to copy",
     "ASK", "destination alone, which two plans share"),

    # -- nothing on file. Saying so is the correct answer and the hard one.
    ("Hoover one one, request clearance to Vaziani",
     "NONE", "somewhere nobody filed for"),
    ("Hoover one one, request clearance for the tanker track",
     "NONE", "a task nobody filed"),

    # -- the words that are in EVERY request and must carry no signal at all. If
    #    "request clearance" scores against a task field, the first plan in the
    #    list wins every transmission.
    ("Hoover one one, request clearance", "ASK", "no discriminator at all"),
]


def live_plans(base: str = "http://localhost:8000") -> list[dict]:
    with urllib.request.urlopen(f"{base}/plans", timeout=5) as r:
        return json.load(r).get("plans") or []


def outcome(hit: dict) -> str:
    if hit.get("plan"):
        return hit["plan"]["name"]
    if hit.get("ambiguous"):
        return "ASK"
    return "NONE"


def main(argv: list[str]) -> int:
    filed = live_plans() if "--live" in argv else FILED
    print(f"{len(filed)} plan(s) on file\n")

    ok = True
    for said, want, why in CASES:
        hit = P.pick(said, filed, callsign="Hoover 1-1")
        got = outcome(hit)
        good = got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {why}")
        print(f'        "{said}"')
        if not good:
            print(f"        wanted {want}, got {got}")
        if got == "ASK":
            print(f"        -> {P.ask_which(hit['ambiguous'])}")
        elif hit.get("plan"):
            print(f"        -> matched on {', '.join(hit.get('why') or [])}")

    # And the clearance itself, read out once so a human can hear whether it
    # scans. Nothing here asserts on the wording -- that is what the unit tests
    # are for -- but a CRAFT clearance that reads badly out loud is a bug you
    # only find by looking at it.
    plan = next((p for p in filed if p.get("task")), filed[0] if filed else None)
    if plan:
        print("\nthe clearance, as it would be spoken:")
        print("  " + P.clearance(plan, flight_id=7, departure_freq=124.0,
                                 initial_ft=plan.get("cruise_ft") or 0))

    print("\nall cases behaved" if ok else "\nSOME CASES FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
