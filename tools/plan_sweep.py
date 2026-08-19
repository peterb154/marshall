"""Does the CONTROLLER find the plan a pilot actually asked for?

FP-1 on the card -- #1 -- and it is a bench rather than a flight test because
the thing under test is comprehension, not a manoeuvre. Reading fifty phrasings
at a controller over the radio would cost an evening; here it costs a minute,
and the evening can be spent on something only an aeroplane can tell us.

    uv run python tools/plan_sweep.py            # scores the model

IT USED TO SCORE A REGEX AND NOW IT SCORES THE MODEL, which is the whole of
#183. `plans.pick` gave 100 points for naming a plan, 10 a word for the task, 6
for a route point and 1 for the destination, and this file measured those
weights. The weights are gone: the controller reads the pilot's words with
every filed label in his prompt and decides, and the engine validates the label
he names. So the question this file asks is unchanged and the thing it asks has
moved.

    "lets not implement stopgaps"

WHY IT LEFT tools/check.py. It costs model calls and a network, which a tier-1
check may not. `check.py` now reports it as unguarded by name rather than
quietly not running it -- the same treatment as the other live checks, and for
the same reason: a check that silently does not run reads exactly like one that
passed.

Three outcomes are all correct, and telling them apart is the whole job:

  MATCH      exactly one plan fits. He is cleared.
  ASK        more than one fits. The controller ASKS, and must not choose --
             the same rule as a formation he cannot tell apart.
  NONE       nothing on file fits. He says so rather than clearing him on the
             nearest thing, which would be an aeroplane routed somewhere nobody
             asked to go.

The failure this guards is the quiet one. A controller who always names his
best guess never asks a question and looks perfect in a demo, because every
request produces a clearance -- including the requests that were ambiguous,
where the clearance is for somebody else's sortie.

A SCORE, NOT A PASS. Like `classify_bench.py`, this measures a model and models
vary; the baseline is what it scored last, beaten and moved in the same commit.
`asr_sweep`'s rule -- a check that is always red is a check nobody reads.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from marshall.atc import plans as P

# Mirrors migrations/012, 017 and 019. Kept here so the sweep runs with no database, no
# container and no network -- the point of a tier-1 check is that there is
# nothing to bring up first. `--live` reads the real rows instead, which is how
# you catch this copy drifting from what is actually on file.
FILED = [
    {"name": "362nd-batumi-asr", "label": "Samovar", "callsign": None,
     "origin": "Batumi", "destination": "Batumi",
     "route": "BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI",
     "task": "CAS over Tsutsnvati"},
    {"name": "362nd-batumi-ndb", "label": "Kettle", "callsign": None,
     "origin": "Batumi", "destination": "Batumi",
     "route": "BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI",
     "task": "CAS over Tsutsnvati, beacon letdown on return"},
    {"name": "362nd-ingress-weather", "label": "Lantern", "callsign": None,
     "origin": "Batumi", "destination": "Batumi",
     "route": "BATUMI, FEET WET, INGRESS, FEET WET, BATUMI",
     "task": "Weather reconnaissance out to Ingress"},
    {"name": "362nd-coast-patrol", "label": "Marlin", "callsign": None,
     "origin": "Batumi", "destination": "Batumi",
     "route": "BATUMI, FEET WET, KOBULETI, BATUMI",
     "task": "Night patrol of the coastline"},
    {"name": "362nd-kobuleti-escort", "label": "Anvil", "callsign": None,
     "origin": "Batumi", "destination": "Batumi",
     "route": "BATUMI, KOBULETI, BATUMI",
     "task": "Escort a transport as far as Kobuleti"},
    # THE ONE THAT DOES NOT DEPART BATUMI, and the reason the two cases below
    # matter more than they look. It shares the word "Kobuleti" with Anvil, and
    # a pilot standing on the Kobuleti ramp says that word in his callsign line
    # every single transmission -- so the request that must resolve to this plan
    # arrives pre-loaded with a token that scores for a different one.
    {"name": "362nd-kobuleti-batumi", "label": "Domino", "callsign": None,
     "origin": "Kobuleti", "destination": "Batumi",
     "route": "KOBULETI, INITIAL, BATUMI",
     "task": "Transit and radar recovery"},
]

# WHAT IT SCORED WHEN THE MODEL TOOK OVER, 18 August, all-Sonnet. Two cases
# fail and both are the controller naming Domino where the case wants a
# question:
#
#   "IFR to Batumi, ready to copy"                a real miss. Every plan ends
#                                                 at Batumi, so this genuinely
#                                                 discriminates nothing and the
#                                                 answer is a question
#   "the transit from Kobuleti to Batumi"         ARGUABLE, and left failing on
#                                                 purpose. The case wants ASK
#                                                 because the old scorer could
#                                                 not tell Domino from Anvil,
#                                                 whose task also names
#                                                 Kobuleti -- but Domino IS the
#                                                 Kobuleti-to-Batumi transit and
#                                                 a controller reading the board
#                                                 would say so
#
# The second is a case that encoded a limitation of the thing being replaced.
# Left in and left red rather than quietly reclassified: moving the goalposts
# to make a new number look better is how a baseline stops meaning anything.
BASELINE = 14

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
    #    ...AND THE SAME REQUEST WITH THE STATION NAMED, which is how a pilot
    #    actually opens a transmission and which used to change the answer.
    #    Addressing a controller gave every plan at his field a standing four
    #    points, so on a board trimmed to one plan the man who asked for Vaziani
    #    was read back a clearance to Batumi. The address is context; it breaks
    #    ties between plans his words already point at and can never be the
    #    match on its own.
    ("Kobuleti Clearance, Viper one one, request clearance to Vaziani",
     "NONE", "somewhere nobody filed for, with the station addressed"),
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


SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {"type": "string",
                 "description": "the LABEL of the plan he means -- 'Domino', "
                                "'Marlin'. Empty if you cannot tell or if "
                                "nothing on file fits."},
        "ask": {"type": "boolean",
                "description": "true if more than one filed plan fits and you "
                               "must ask him which"},
        "none": {"type": "boolean",
                 "description": "true if nothing on file fits what he asked "
                                "for"},
    },
    "required": ["plan", "ask", "none"],
}


def contract() -> str:
    """The REAL tool description, read off the source.

    Copying the wording into this file would let the two drift, and the drift
    would be invisible: the bench would go on scoring a contract the controller
    is no longer given. It is the prompt under test, so it is read from where
    the controller actually gets it.
    """
    src = (ROOT / "src" / "marshall" / "atc" / "clearance.py").read_text()
    at = src.index("def request_clearance(callsign: str, plan: str)")
    doc = src[src.index('"""', at) + 3:]
    return doc[:doc.index('"""')]


def board(filed: list[dict]) -> str:
    """What the controller can see. `filed_plans` puts the labels in his
    prompt; the task is what a pilot describes instead of naming one."""
    return "\n".join(
        f"  {p['label']} — {p.get('task') or '?'} "
        f"({p.get('origin') or '?'} to {p.get('destination') or '?'})"
        for p in filed)


def decide(said: str, filed: list[dict]) -> dict:
    from marshall.atc.bedrock_intent import bedrock_llm
    system = (
        "You are a clearance delivery controller. A pilot has just spoken to "
        "you. Decide which filed flight plan he means.\n\n"
        "These are the plans on file:\n" + board(filed) + "\n\n"
        "The tool you would call is described to you like this:\n\n"
        + contract())
    return bedrock_llm(said, system, SCHEMA)


def outcome(hit: dict) -> str:
    """The model's answer, in the sweep's three-way vocabulary."""
    if hit.get("ask"):
        return "ASK"
    if hit.get("none") or not (hit.get("plan") or "").strip():
        return "NONE"
    return (hit.get("plan") or "").strip()


def unrunnable(want: str, filed: list[dict]) -> str:
    """Why this case cannot be asked of THIS board, or "" if it can.

    THE FIXTURE ALWAYS EXPRESSES EVERY CASE -- it was written to. A live board
    is whatever somebody filed, and it can be trimmed to one plan for a night's
    flying, at which point most of this sweep is asking a question the data
    cannot answer.

    A case that cannot be asked must SAY SO. Running it anyway gives a FAIL that
    means "the board changed", which is not a finding and which teaches everyone
    to ignore a red sweep -- and skipping it silently is worse, because the run
    then reports success for work it did not do.
    """
    if want == "ASK" and len(filed) < 2:
        return f"needs two plans that could both fit; the board has {len(filed)}"
    if want.startswith("362nd-") and not any(p.get("name") == want
                                             for p in filed):
        return f"{want} is not on this board"
    return ""


def main(argv: list[str]) -> int:
    live = "--live" in argv
    filed = live_plans() if live else FILED
    print(f"{len(filed)} plan(s) on file\n")

    ok, skipped, passed, failed = True, [], 0, []
    for said, want, why in CASES:
        gap = unrunnable(want, filed) if live else ""
        if gap:
            skipped.append((why, gap))
            print(f"  SKIP  {why}")
            print(f'        "{said}"')
            print(f"        {gap}")
            continue
        hit = decide(said, filed)
        got = outcome(hit)
        # CASES NAME A PLAN BY ITS KEY and a controller answers with a LABEL,
        # because the key is a slug nobody says out loud. Compared through the
        # board so the cases stay readable as what is actually filed.
        want_label = next((p["label"] for p in filed
                           if p.get("name") == want), want)
        good = P._key(got) == P._key(want_label)
        passed += 1 if good else 0
        if not good:
            failed.append(why)
        print(f"  {'PASS' if good else 'FAIL'}  {why}")
        print(f'        "{said}"')
        if not good:
            print(f"        wanted {want_label}, got {got}")

    # And the clearance itself, read out once so a human can hear whether it
    # scans. Nothing here asserts on the wording -- that is what the unit tests
    # are for -- but a CRAFT clearance that reads badly out loud is a bug you
    # only find by looking at it.
    plan = next((p for p in filed if p.get("task")), filed[0] if filed else None)
    if plan:
        print("\nthe clearance, as it would be spoken:")
        print("  " + P.clearance(plan, flight_id=7, departure_freq=124.0,
                                 initial_ft=(plan.get("legs") or [{}])[0].get("alt_ft") or 0))

    if skipped:
        # Named, every time. "Skipped is reported, never silent" -- a check that
        # quietly did not run reads exactly like one that passed.
        print(f"\n{len(skipped)} case(s) this board cannot express:")
        for why, gap in skipped:
            print(f"  - {why}: {gap}")
        print("  The FIXTURE still exercises all of them; run without --live.")
    # A BASELINE, NOT A PASS MARK. This scores a model and models vary; a
    # check that is always red is a check nobody reads. Beat it and move it in
    # the same commit.
    print(f"\n{passed}/{len(CASES) - len(skipped)} — baseline {BASELINE}")
    for why in failed:
        print(f"  still failing: {why}")
    if passed < BASELINE:
        print("REGRESSION against the recorded baseline")
        return 1
    if passed > BASELINE:
        print(f"BETTER than the baseline — raise BASELINE to {passed} "
              f"in this commit")
    return 0 if ok or passed >= BASELINE else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
