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

# Mirrors migrations/012, 017 and 019. Kept here so the sweep runs with no database, no
# container and no network -- the point of a tier-1 check is that there is
# nothing to bring up first. `--live` reads the real rows instead, which is how
# you catch this copy drifting from what is actually on file.
FILED = [
    {"name": "362nd-batumi-asr", "label": "Samovar", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 11000,
     "route": "BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI",
     "task": "CAS over Tsutsnvati"},
    {"name": "362nd-batumi-ndb", "label": "Kettle", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 11000,
     "route": "BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI",
     "task": "CAS over Tsutsnvati, beacon letdown on return"},
    {"name": "362nd-ingress-weather", "label": "Lantern", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 5000,
     "route": "BATUMI, FEET WET, INGRESS, FEET WET, BATUMI",
     "task": "Weather reconnaissance out to Ingress"},
    {"name": "362nd-coast-patrol", "label": "Marlin", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 3000,
     "route": "BATUMI, FEET WET, KOBULETI, BATUMI",
     "task": "Night patrol of the coastline"},
    {"name": "362nd-kobuleti-escort", "label": "Anvil", "callsign": None,
     "origin": "Batumi", "destination": "Batumi", "cruise_ft": 4000,
     "route": "BATUMI, KOBULETI, BATUMI",
     "task": "Escort a transport as far as Kobuleti"},
    # THE ONE THAT DOES NOT DEPART BATUMI, and the reason the two cases below
    # matter more than they look. It shares the word "Kobuleti" with Anvil, and
    # a pilot standing on the Kobuleti ramp says that word in his callsign line
    # every single transmission -- so the request that must resolve to this plan
    # arrives pre-loaded with a token that scores for a different one.
    {"name": "362nd-kobuleti-batumi", "label": "Domino", "callsign": None,
     "origin": "Kobuleti", "destination": "Batumi", "cruise_ft": 5000,
     "route": "KOBULETI, INITIAL, BATUMI",
     "task": "Transit and radar recovery"},
]

# (what he says, what should happen, why this phrasing is in the list)
CASES = [
    # -- named outright. The escape hatch, and it has to be exact-proof.
    ("Batumi Ground, Hoover one one, request clearance, Marlin",
     "362nd-coast-patrol", "the label, said plainly"),
    ("Hoover one one, IFR clearance on file, Lantern, ready to copy",
     "362nd-ingress-weather", "the label buried in the middle of a request"),

    # -- by the task, which is how a pilot thinks about it.
    ("Hoover one one, request clearance for the weather run out to Ingress",
     "362nd-ingress-weather", "the task in his own words"),
    ("Hoover one one, ready to copy, we're escorting a transport up to Kobuleti",
     "362nd-kobuleti-escort", "the task, paraphrased"),
    ("Hoover one one, clearance for the night patrol",
     "362nd-coast-patrol", "half the task, and only one plan has it"),

    # -- "CAS over Tsutsnvati" names TWO plans, so the controller must ASK. This
    #    is the case a best-score-wins resolver gets confidently and silently
    #    wrong: the two differ only in the approach flown at the end.
    ("Hoover one one, request clearance for the CAS over Tsutsnvati",
     "ASK", "a task that fits two plans"),
    ("Hoover one one, clearance for the Tsutsnvati mission",
     "ASK", "a place that fits two plans"),
    ("Hoover one one, request clearance, the one with the beacon letdown",
     "362nd-batumi-ndb", "the words that tell the two apart"),

    # -- THE KOBULETI DEPARTURE, the sortie actually being flown and the first
    #    row on the board that does not start at Batumi.
    #
    #    It went unfiled until the evening it was needed: every plan departed
    #    Batumi, so a pilot on the Kobuleti ramp asking for his clearance was
    #    told, in perfect phraseology, that there was nothing on file for him.
    #    Nothing errors -- it is the first transmission of the night, and it
    #    sounds exactly like having mistyped your own callsign.
    ("Kobuleti Clearance, Viper one one, request clearance, Domino",
     "362nd-kobuleti-batumi", "the Kobuleti departure, named"),

    #    ORIGIN IS A REAL DISCRIMINATOR NOW and was not before -- one row, one
    #    origin that is not Batumi. Note the field he is standing on is in his
    #    callsign line on every transmission, so this must work with "Kobuleti"
    #    appearing for reasons that have nothing to do with the plan.
    ("Viper one one, ready to copy, the transit out of Kobuleti",
     "362nd-kobuleti-batumi", "the origin alone, which only one plan has"),

    #    AND ONE THAT ASKS, which looks like a weakness and is the safe answer.
    #    Naming both endpoints scores Anvil nearly as well as Domino, because
    #    Anvil's JOB is going to Kobuleti -- its task says so, legitimately, and
    #    the task is the heaviest field there is. Telling them apart needs the
    #    direction of "FROM Kobuleti TO Batumi", which nothing here parses.
    #
    #    Recorded as ASK rather than tuned away. Moving the origin weight until
    #    this one case flips is fitting the scorer to the sweep, and the cost of
    #    being wrong is a clearance onto somebody else's sortie; the cost of
    #    asking is the pilot saying one more word.
    ("Viper one one, clearance for the transit from Kobuleti to Batumi",
     "ASK", "both endpoints -- Anvil's task legitimately owns Kobuleti too"),

    # -- the civil form, which separates nothing here: everything comes home to
    #    Batumi, so a destination match must not be enough on its own.
    ("Hoover one one, IFR to Batumi, ready to copy",
     "ASK", "destination alone, which every plan shares"),

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
