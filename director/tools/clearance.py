"""Giving a filed plan to a flight, and saying it out loud.

`plans.py` is the judgement with no database in it -- which plan does he mean,
and what are the words. This is the part that touches Postgres and the radio:
read the templates, copy one onto a flight, and hand the controller a clearance
he is to READ rather than compose.

That split is the same one the whole project runs on. The agent owns language;
it does not own the numbers. A squawk, a cruise altitude and a departure
frequency are facts about what was filed, and a controller who improvises them
has cleared somebody to an altitude nobody wrote down. So the tool returns the
finished sentence and the brief says to voice it -- exactly as the deterministic
controller's altitudes are voiced, and for the same reason.

The other half is that assignment is a COPY. `flight_plans` holds what was
filed; `assigned_plans` holds what this aeroplane was given. Amending one
flight's routing must never edit the plan somebody else is flying, or next
week's. See migrations/009.
"""

from __future__ import annotations

import logging
import re

from tools import plans as P
from datetime import UTC

log = logging.getLogger(__name__)

try:
    from strands import tool
except ImportError:                     # importable without strands (tests)
    def tool(fn):
        return fn


def _pool():
    from strands_pg._pool import get_pool
    return get_pool()


# --- what is on file --------------------------------------------------------

# NO CALLSIGN. The column still exists on `flight_plans` -- two of the six rows
# carry one, left over from when a plan was seeded beside the aeroplane meant to
# fly it -- but a plan on file belongs to NOBODY until a clearance is issued, and
# that is the moment it is copied into `assigned_plans` against a flight_id.
#
# It is read out here rather than filtered later so it cannot come back by
# accident: a template callsign is a THIRD source of names, beside a pilot's own
# handle and a flight somebody created, and it is the same kind as the "Falcon"
# that cost a sortie -- a word that exists because a builder typed it, attached
# to no person and no flight. `Pony 1-1` on a template is a mission-editor unit
# name, and matching a live pilot to it hands him a plan he never asked for on
# the strength of a coincidence.
_TEMPLATE_COLS = ("name", "label", "origin", "destination",
                  "route", "cruise_ft", "task", "approach")


def filed() -> list[dict]:
    """Every plan on file. They belong to nobody until one is issued.

    Deliberately unfiltered and deliberately anonymous. Any pilot may request
    any plan -- taking somebody else's is a normal thing here and an impossible
    one in the civil world.
    """
    with _pool().connection() as c:
        rows = c.execute(
            f"SELECT {', '.join(_TEMPLATE_COLS)} FROM flight_plans "
            f"ORDER BY label NULLS LAST, name").fetchall()
    return [dict(zip(_TEMPLATE_COLS, r)) for r in rows]


_ASSIGNED_COLS = ("id", "flight_id", "template", "label", "origin",
                  "destination", "route", "cruise_ft", "task", "approach",
                  "acked_at")


def assigned(flight_id: int) -> dict | None:
    with _pool().connection() as c:
        r = c.execute(
            f"SELECT {', '.join(_ASSIGNED_COLS)} FROM assigned_plans "
            f"WHERE flight_id=%s", (flight_id,)).fetchone()
    return dict(zip(_ASSIGNED_COLS, r)) if r else None


def assign(flight_id: int, plan: dict, *, mission: str = "default",
           route: str | None = None) -> dict:
    """Copy a filed plan onto a flight. Repeating this AMENDS rather than adds.

    One live plan per flight is a unique index, not a convention: two live plans
    for one aeroplane is precisely the ambiguity the table exists to remove, and
    an amendment that accumulated would leave a controller reading whichever row
    came back first.
    """
    row = dict(plan)
    with _pool().connection() as c:
        c.execute(
            """
            INSERT INTO assigned_plans
                (mission, flight_id, template, label, origin, destination,
                 route, cruise_ft, task, approach)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (flight_id) DO UPDATE SET
                template=EXCLUDED.template, label=EXCLUDED.label,
                origin=EXCLUDED.origin, destination=EXCLUDED.destination,
                route=EXCLUDED.route, cruise_ft=EXCLUDED.cruise_ft,
                task=EXCLUDED.task, approach=EXCLUDED.approach,
                assigned_at=now(), acked_at=NULL
            """,
            (mission, flight_id, row.get("name"), row.get("label"),
             row.get("origin"), row.get("destination"),
             route or row.get("route"), row.get("cruise_ft"),
             row.get("task"), row.get("approach")))
    # And onto the flight's own row, because that is what everything else reads
    # -- the state view, the plate, anything asking "where is he going". Written
    # in the same call as the copy so the two cannot drift; the copy keeps the
    # provenance and the read-back, the flight row keeps what was agreed.
    from tools import flights as F
    F.agree(flight_id, flight_plan=row.get("name"),
            destination=row.get("destination"),
            route=route or row.get("route"), cruise_ft=row.get("cruise_ft"),
            clearance_ack=None)
    # acked_at is cleared on an amendment on purpose. A read-back covers the
    # clearance he was given, and he has not read back the new one yet.
    return assigned(flight_id) or {}


def ack(flight_id: int) -> dict:
    """He read it back. Filed, given and AGREED are three different things and
    the gap between the last two is a controller's business."""
    with _pool().connection() as c:
        c.execute("UPDATE assigned_plans SET acked_at=now() WHERE flight_id=%s",
                  (flight_id,))
    from datetime import datetime

    from tools import flights as F
    # A timestamp, not a flag: WHEN he agreed is the useful part, and the column
    # has been a timestamptz since the flights table was written.
    F.agree(flight_id, clearance_ack=datetime.now(UTC))
    return assigned(flight_id) or {}


# --- the numbers the clearance needs, from what is published ----------------

def _stations() -> list[dict]:
    from tools.approaches import active_flight_plan
    fp = active_flight_plan() or {}
    return ((fp.get("approach") or {}).get("data") or {}).get("stations") or []


def departure_freq() -> float:
    """Whom he calls after he rolls, read off the published stations rather than
    remembered here. One field's Approach also works Departure; picking it out
    of the profile means a mission that splits them does not need this file
    changed."""
    for s in _stations():
        roles = [s.get("role") or "", *(s.get("also") or ())]
        if "departure" in roles:
            return float(s.get("freq_mhz") or 0)
    for s in _stations():
        if (s.get("role") or "") == "approach":
            return float(s.get("freq_mhz") or 0)
    return 0.0


def aircraft_type(flight: dict) -> str | None:
    """What he is flying, from the sim's own track. Nobody has to declare it,
    and a pilot cannot get it wrong."""
    name = flight.get("track_name")
    if not name:
        return None
    with _pool().connection() as c:
        r = c.execute("SELECT type FROM tracks WHERE name=%s", (name,)).fetchone()
    return r[0] if r else None


# --- the tool the controller actually calls ---------------------------------

def resolve(said: str, callsign: str | None = None) -> dict:
    """Which filed plan he means. Pure lookup + `plans.pick`, no side effects."""
    return P.pick(said, filed(), callsign=callsign)


_SPOKEN_DIGIT = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                 "five": "5", "six": "6", "seven": "7", "eight": "8",
                 "nine": "9", "niner": "9"}


def canonical_callsign(said: str) -> str:
    """"Pony one one" -> "Pony 1-1". The board's key, from the spoken form.

    The agent says callsigns the way a controller says them, because that is what
    it is for -- and the flights table is keyed on the canonical form. A tool
    that took only the canonical form would be answered "no flight on the board"
    for an aeroplane sitting on the frequency, which is exactly what the first
    dry run of clearance delivery did.

    Deliberately a second, smaller copy of what `atc/callsign.py` does, for the
    same reason `PHASES` is duplicated here: the director must not have to import
    the ATC package, which lives in a different deployable.
    """
    words = re.findall(r"[A-Za-z]+|\d", said or "")
    name, digits = "", []
    for w in words:
        if w.isdigit():
            digits.append(w)
        elif w.lower() in _SPOKEN_DIGIT:
            digits.append(_SPOKEN_DIGIT[w.lower()])
        elif w.lower() == "flight":
            break            # "Pony one flight" names the formation, not a ship
        elif not name:
            name = w.capitalize()
    if not name:
        return (said or "").strip()
    if not digits:
        return name
    if len(digits) == 1:
        return f"{name} {digits[0]}"
    return f"{name} {digits[0]}-{digits[-1]}"


def not_on_the_board(callsign: str, board: list[str]) -> str:
    """The miss, said so it cannot be paraphrased into the wrong thing.

    THIS IS ABOUT HIM, NOT ABOUT HIS FLIGHT PLAN, and getting that across is the
    entire job of this string. It used to read "No flight on the board for
    Falcon 1-1. Get his callsign and check him in first" -- a true statement
    about the PILOT, which the controller relayed as "no flight plan on file for
    that callsign", a false statement about the FILE. The pilot then spent two
    minutes re-reading his callsign and hunting a plan that was on file the
    whole time, and never got his clearance at all.

    The cause underneath it is worth naming, because it is not a fault: he had
    called himself Falcon, and nothing called Falcon existed. A callsign is
    somebody's own name on the radio or a flight that was created, and the
    identity ladder is meant to refuse a word invented in the air. It did.
    Only the explanation was wrong.

    So the answer names the CLOSED SET, which is the thing the ladder gives us
    for free and nobody was spending. A controller who can say "I have Pony 1-1
    and Pony 1-2" has told him what to do next in one breath, and no controller
    who has that list in front of him reaches for the flight plan as the excuse.
    """
    board_text = ", ".join(board) if board else "nobody -- the board is empty"
    return (f"{callsign} IS NOT ON THE BOARD. This is about WHO HE IS, not "
            f"about his flight plan -- do NOT tell him a plan is missing, "
            f"unavailable or not on file, because that is a different thing "
            f"and it sends him hunting in the wrong place.\n"
            f"On the board: {board_text}.\n"
            f"A callsign here is either a pilot's own name on the radio or a "
            f"flight somebody created; it is never a name chosen in the air. "
            f"So a callsign nobody recognises means he has not checked in under "
            f"a name that exists. Tell him you have no {callsign}, say who you "
            f"do have, and ask him to say his callsign again.")


def clearance_tools(mission: str = "default") -> list:
    """The clearance-delivery tools, bound to a mission."""

    def _flight(callsign: str) -> dict | None:
        from tools import flights as F
        for cs in (canonical_callsign(callsign), callsign):
            got = F.find(mission, callsign=cs)
            if got:
                return got
        return None

    def _not_on_the_board(callsign: str) -> str:
        from tools import flights as F
        try:
            have = F.callsigns(mission)
        except Exception as e:                  # never lose the refusal to a query
            log.warning("could not list the board: %s", e)
            have = []
        return not_on_the_board(callsign, have)

    @tool
    def request_clearance(callsign: str, said: str = "") -> str:
        """Give a flight its IFR clearance from a plan on file, and get back the
        exact words to say. Call this when a pilot asks for his clearance --
        "request clearance", "IFR to Batumi ready to copy", "clearance for the
        CAS over Tsutsnvati". `said` is his request in his own words; it is how
        the right plan is found, so pass it through unedited.

        READ THE RETURNED CLEARANCE VERBATIM AND WHOLE. Every element is there
        because a pilot writes it down: clearance limit, route, altitude,
        DEPARTURE FREQUENCY, squawk. Do not paraphrase, round, drop or reorder
        one -- a clearance is the one long transmission on this frequency, and
        the frequency is the element most often lost, which leaves him airborne
        not knowing whom to call. If more than one plan fits, you get a question
        to ask him instead; ask it exactly and do not choose for him.
        """
        f = _flight(callsign)
        if not f:
            return _not_on_the_board(callsign)

        hit = resolve(said, callsign)
        if hit.get("none"):
            return ("Nothing is on file that matches. Tell him so and ask what "
                    "he filed.")
        if hit.get("ambiguous"):
            return "SAY THIS: " + P.ask_which(hit["ambiguous"])

        plan = hit["plan"]
        fixes = _known_fixes()
        _, missing = P.route_fixes(plan, fixes)
        if missing:
            # Refused here rather than discovered at the third leg: a route with
            # a point nobody can find is a plan that strands him halfway.
            return (f"That plan routes via {', '.join(missing)}, which is not a "
                    f"fix anybody here holds. Do not clear him on it -- tell him "
                    f"the routing is unavailable and ask him to amend.")

        got = assign(f["id"], plan, mission=mission)
        words = P.clearance(plan, flight_id=f["id"],
                            departure_freq=departure_freq(),
                            initial_ft=plan.get("cruise_ft") or 0)
        why = ", ".join(hit.get("why") or []) or "the one on file"
        return (f"SAY THIS, verbatim and complete, after his callsign: {words}\n"
                f"(matched on {why}; plan {got.get('label') or plan.get('name')}. "
                f"Every element above is read out -- the departure frequency is "
                f"not optional.\n"
                f"HIS NEXT TRANSMISSION WILL BE THE READ-BACK. Answer it: call "
                f"clearance_read_back and say \"readback correct\" if he got it, "
                f"or name the element he got wrong and ask for that one again. "
                f"Silence is not an answer here -- he is on the ground with a "
                f"pencil and no way to tell whether you heard him.)")

    @tool
    def clearance_read_back(callsign: str, correct: bool = True) -> str:
        """Record that a pilot has read his clearance back. Call it with
        correct=true when he got it right, and correct=false when he did not --
        an unacknowledged clearance stays unacknowledged, which is what lets
        anybody afterwards see that he was cleared but never agreed."""
        f = _flight(callsign)
        if not f:
            return _not_on_the_board(callsign)
        if not assigned(f["id"]):
            return f"{callsign} has not been given a clearance to read back."
        if not correct:
            return ("Not recorded. Read him the parts he got wrong and take the "
                    "read-back again.")
        ack(f["id"])
        return f"Read-back correct, {callsign} is cleared as filed."

    @tool
    def flight_plan_help(callsign: str) -> str:
        """What this flight is doing, where it goes next, and HOW MUCH HELP HE
        NEEDS with it. Call it before offering navigation assistance: an
        aeroplane with an inertial platform wants the fix named and nothing else,
        and a 1944 fighter on a compass and a watch cannot get there without
        position reports and vectors."""
        f = _flight(callsign)
        if not f:
            return _not_on_the_board(callsign)
        plan = assigned(f["id"])
        if not plan:
            return f"{callsign} has no assigned flight plan."
        nav = P.nav_of(aircraft_type(f))
        legs, missing = P.route_fixes(plan, _known_fixes())
        route = " -> ".join(x["name"] for x in legs) or "(no route filed)"
        out = [f"{callsign}: {plan.get('task') or 'no task filed'}",
               f"route {route}",
               f"cruise {plan.get('cruise_ft') or '?'} ft, "
               f"destination {plan.get('destination') or '?'}",
               P.help_level(nav)]
        if missing:
            out.append(f"Unresolved on his route: {', '.join(missing)}.")
        return "\n".join(out)

    return [request_clearance, clearance_read_back, flight_plan_help]


def _known_fixes() -> dict:
    """Where the points are. Not stored on the plan -- one source of truth for a
    position, so a plan and a chart cannot disagree about INGRESS."""
    try:
        from tools.tracks import known_fixes
        return {k.lower(): v for k, v in (known_fixes() or {}).items()}
    except Exception:                   # nothing pushed yet; a plan is still readable
        log.warning("no fixes pushed; route resolution will report everything missing")
        return {}
