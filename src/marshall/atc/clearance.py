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

from marshall.atc import plans as P
from datetime import UTC

log = logging.getLogger(__name__)

try:
    from strands import tool
except ImportError:                     # importable without strands (tests)
    def tool(fn):
        return fn


def _pool():
    from marshall.core.db import pool as get_pool
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
# `legs` is the level per leg, which is what a flight plan actually carries --
# `cruise_ft` is the highest of them, and the level a pilot MAINTAINS off the
# ramp is the first. See migration 030 and `request_clearance`.
# WHAT A PLAN ROW IS, after migration 031. `route`, `destination` and
# `cruise_ft` come back from `filing.derived` -- computed from the legs rather
# than stored beside them -- and `origin` and `approach` are the CLEARANCE'S,
# which is why `assigned_plans` has its own columns for them.
_TEMPLATE_COLS = ("name", "label", "legs", "task")


def filed() -> list[dict]:
    """Every plan on file THAT DEPARTS THIS WORLD. Anonymous, not unfiltered.

    Deliberately anonymous: any pilot may request any plan, and taking somebody
    else's is a normal thing here and an impossible one in the civil world.

    IT USED TO BE UNFILTERED TOO, and that stopped being right when a second map
    arrived. Measured on the first Nevada run, to an aeroplane sitting at Nellis:

        "Sockeye, Clearance, I have three plans on file -- Domino, transit and
         radar recovery; Redflag, local transit and instrument recovery; ..."

    Domino departs KOBULETI. It is a real plan, correctly filed, three thousand
    miles away on a map that is not loaded -- and offering it made the pilot
    choose between his own sortie and one he cannot fly. That is #89 exactly
    ("a plan that is not from your field is not yours"), one level up: not the
    wrong field, the wrong WORLD.

    THE PUBLISHED FIX TABLE IS THE WORLD. `push_fixes` writes this theatre's
    catalogue at every voice-process start and now replaces rather than merges, so a
    plan whose origin is not a published fix is not somewhere this controller
    can see. No new configuration, no theatre flag in the language brain, and it
    cannot drift from what `marshall-atc` actually published.

    A plan with no origin is kept. That is a filing gap rather than another
    map's sortie, and the filing checks already report it.
    """
    with _pool().connection() as c:
        rows = c.execute(
            f"SELECT {', '.join(_TEMPLATE_COLS)} FROM flight_plans "
            f"ORDER BY label NULLS LAST, name").fetchall()
    from marshall.atc.filing import derived
    plans = [derived(dict(zip(_TEMPLATE_COLS, r))) for r in rows]
    here = set(_known_fixes())
    if not here:
        return plans           # nothing published yet: filter nothing
    return [p for p in plans
            if not p.get("origin")
            or str(p["origin"]).strip().lower() in here]


_ASSIGNED_COLS = ("id", "flight_id", "template", "label", "origin",
                  "destination", "route", "task", "approach",
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
                 route, task, approach, squawk)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (flight_id) DO UPDATE SET
                template=EXCLUDED.template, label=EXCLUDED.label,
                origin=EXCLUDED.origin, destination=EXCLUDED.destination,
                route=EXCLUDED.route,
                task=EXCLUDED.task, approach=EXCLUDED.approach,
                squawk=EXCLUDED.squawk,
                assigned_at=now(), acked_at=NULL
            """,
            (mission, flight_id, row.get("name"), row.get("label"),
             row.get("origin"), row.get("destination"),
             route or row.get("route"),
             row.get("task"), row.get("approach"),
             # THE SQUAWK, RECORDED RATHER THAN RECOMPUTED. It is derived from
             # the flight id, so it was reproducible -- and being reproducible
             # is not the same as being on the strip. A read-back can only be
             # judged against the clearance that was issued, and this was the
             # one element of it nothing kept. See migration 023.
             _squawk_for(flight_id)))
    # And onto the flight's own row, because that is what everything else reads
    # -- the state view, the plate, anything asking "where is he going". Written
    # in the same call as the copy so the two cannot drift; the copy keeps the
    # provenance and the read-back, the flight row keeps what was agreed.
    from marshall.atc import board as F
    F.agree(flight_id, flight_plan=row.get("name"),
            flight_plan_label=row.get("label"),
            destination=row.get("destination"),
            route=route or row.get("route"),
            clearance_ack=None)
    # acked_at is cleared on an amendment on purpose. A read-back covers the
    # clearance he was given, and he has not read back the new one yet.
    return assigned(flight_id) or {}


def _squawk_for(flight_id: int) -> str:
    """The squawk this flight was given. Derived, so it never disagrees with
    the words that were spoken -- `plans` composes the clearance from the same
    function."""
    try:
        from marshall.atc.plans import squawk_for
        return squawk_for(flight_id)
    except Exception:                       # never lose a clearance to this
        return ""


def ack(flight_id: int) -> dict:
    """He read it back. Filed, given and AGREED are three different things and
    the gap between the last two is a controller's business."""
    with _pool().connection() as c:
        c.execute("UPDATE assigned_plans SET acked_at=now() WHERE flight_id=%s",
                  (flight_id,))
    from datetime import datetime

    from marshall.atc import board as F
    # A timestamp, not a flag: WHEN he agreed is the useful part, and the column
    # has been a timestamptz since the flights table was written.
    F.agree(flight_id, clearance_ack=datetime.now(UTC))
    return assigned(flight_id) or {}


# --- the numbers the clearance needs, from what is published ----------------

def departure_freq(field: str = "") -> float:
    """Whom he calls after he rolls, off the SECTORS this voice process published.

    IT USED TO READ THE ACTIVE FLIGHT PLAN'S APPROACH BLOB and take the first
    departure station in it. Two faults in one line.

    The first is that `flight_plans.active` is not a fact about a flight plan --
    it is `marshall-atc`'s note-to-self about which arrival it is running -- and
    reading world state off it is what made a finished route undeletable:

        "i dont understand this active business. sounds like mis-alignment
         between you and me"

    The second is that "the first departure station" is FIELD-BLIND. A profile
    carries the whole theatre's stations, so with Kobuleti and Batumi both
    listed, whichever came first won -- and a pilot cleared out of one field
    could be given the other's departure frequency. Real number, wrong airport;
    the shape this project keeps finding, and the fourth place it has appeared.

    `sectors` is pushed by `marshall-atc` from the theatre (migration 027) and
    carries the field on every row, so the question can be asked properly:
    whose departure frequency, at WHICH aerodrome. Approach and Departure are
    one seat on one frequency -- see `Station.also` -- so the approach sector IS
    the answer.
    """
    if not field:
        return 0.0
    with _pool().connection() as c:
        r = c.execute(
            "SELECT freq_mhz FROM sectors "
            " WHERE lower(field) = lower(%s) AND role IN ('departure','approach')"
            " ORDER BY CASE role WHEN 'departure' THEN 0 ELSE 1 END LIMIT 1",
            (field,)).fetchone()
    return float(r[0]) if r and r[0] else 0.0


def aircraft_type(flight: dict) -> str | None:
    """What he is flying, from the sim's own track. Nobody has to declare it,
    and a pilot cannot get it wrong."""
    name = flight.get("track_name")
    if not name:
        return None
    with _pool().connection() as c:
        r = c.execute("SELECT type FROM tracks WHERE name=%s", (name,)).fetchone()
    return r[0] if r else None


# --- did the record back what he said? --------------------------------------

# THE ASSERTIONS A PILOT CANNOT ARGUE WITH, and the state each one claims.
# Deliberately short: every phrase here has to be one a controller says ONLY
# when the fact is true, or the check becomes noise and gets switched off.
_CLAIMS = (
    ("cleared to", "issued"),
    ("readback correct", "acknowledged"),
    ("read back correct", "acknowledged"),
    ("readback is correct", "acknowledged"),
)


def unbacked_claims(mission: str, callsign: str, said: str) -> list[str]:
    """Which clearance facts a transmission ASSERTED that the record denies.

    THE INVERSE OF `decision.verify`, and the direction nothing checked.
    `verify` asks which of the engine's facts did not survive being spoken --
    the drop. This asks the opposite: what did he say that nothing issued?

    18 August. The engine issued no clearance for the whole sortie, and the
    controller said:

        15:13:52  Sockeye, Kobuleti Clearance, cleared to Batumi, as filed,
                  maintain five thousand, expect one zero thousand, departure
                  frequency one two three decimal three, squawk ...
        15:14:33  Sockeye, readback correct, contact Kobuleti Ground ...

    `assigned_plans` held no row. Ground taxied him, Tower launched him, and he
    flew to another aerodrome on a clearance that existed only in the air --
    and every rung believed it, because nothing anywhere asked whether it was
    real.

    IT RECORDS; IT DOES NOT EDIT. Deleting the clause would be a regex guard on
    a model's words, which is #179 and which this project has agreed is a
    bandaid over a prompt fault. The prompt fault here is fixed -- the rules
    now say a refusal is not a clearance -- and this exists so that the NEXT
    time it happens it is loud on the first transmission instead of costing a
    day of reading transcripts.

    ANSWERED FROM THE DATABASE rather than from anything the turn is carrying,
    because what is being questioned IS what the turn believes. A missing
    flight row or an unreachable store returns nothing: an unanswerable
    question is not evidence of a lie, and a check that cries wolf when
    Postgres hiccups is a check somebody turns off.
    """
    lowered = (said or "").lower()
    wanted = {state for phrase, state in _CLAIMS if phrase in lowered}
    if not wanted:
        return []
    try:
        from marshall.atc import board as F
        f = None
        for cs in (canonical_callsign(callsign), callsign):
            f = F.find(mission, callsign=cs)
            if f:
                break
        if not f:
            return []
        got = assigned(f["id"])
    except Exception as e:
        log.warning("could not check what was claimed: %s", e)
        return []
    bad = []
    if "issued" in wanted and not got:
        bad.append("said CLEARED TO with no clearance issued")
    if "acknowledged" in wanted and not (got or {}).get("acked_at"):
        bad.append("said READBACK CORRECT with nothing acknowledged")
    return bad


# --- the tool the controller actually calls ---------------------------------

def resolve(label: str) -> dict | None:
    """The filed plan by that name, or None. Pure lookup, no side effects.

    It took the whole transcript and scored it. The controller decides now --
    see the note at the top of `plans.py` -- so this is a key lookup and the
    only thing it can get wrong is a name nobody filed.  [#183]
    """
    return P.named(label, filed())


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
    same reason `PHASES` is duplicated here: the language brain's HTTP door must not have to import
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


def found_but_not_him(callsign: str, plan: dict, board: list[str]) -> str:
    """The plan is here; the aeroplane is not. Two facts, and both get said.

    THE REFUSAL THAT DID NOT EXIST. There were two answers at clearance
    delivery -- "you are not on the board" and "nothing is on file" -- and the
    real state was neither. A plan named `Domino` sat on file while nothing on
    the board answered to `Sockeye`, and whichever of the two sentences came
    out was a true statement about one noun and a lie by implication about the
    other.

    Naming the plan is the point. A pilot who hears "I have Domino, filed
    Kobuleti to Batumi, but nothing on the board under Sockeye" knows in one
    breath that his filing is fine and his IDENTITY is the problem, which is
    the one thing he can fix from the cockpit. "I have no flight of that name"
    sent him to re-read his flight plan three times instead.

    It is still a refusal. `assign` writes a clearance against a flight row, so
    there is nothing to issue it to -- and a sentence must not create the
    aeroplane, which is the door #133 and FEET WET were about.
    """
    where = " to ".join(x for x in (plan.get("origin"), plan.get("destination"))
                        if x)
    named = plan.get("label") or plan.get("name") or "a plan"
    board_text = ", ".join(board) if board else "nobody -- the board is empty"
    return (f"THE PLAN IS ON FILE AND HE IS NOT ON THE BOARD. Both halves must "
            f"reach him or he will fix the wrong one.\n"
            f"On file: {named}" + (f", {where}" if where else "") + ".\n"
            f"On the board: {board_text}.\n"
            f"Tell him you HAVE the plan and name it, so he stops hunting for "
            f"it -- do NOT say it is missing, unavailable or not on file. Then "
            f"tell him you have nothing under {callsign}, say who you do have, "
            f"and ask him to say his callsign again. A callsign here is a "
            f"pilot's own name on the radio or a flight somebody created; it "
            f"is never a name chosen in the air, so this is an identity "
            f"problem and not a filing one.")


def field_of(station: str) -> str:
    """"Kobuleti Clearance" -> "Kobuleti". The aerodrome this seat works.

    The last word is the SEAT and the rest is the field, which is how every
    station in this system is named. Deliberately not a table lookup: the
    language brain has no theatre (see the `/atis` endpoint on why), and the one fact
    needed here is already in the string `marshall-atc` sent.
    """
    words = (station or "").split()
    return " ".join(words[:-1]).strip() if len(words) > 1 else ""


def clearance_tools(mission: str = "default", station: str = "") -> list:
    """The clearance-delivery tools, bound to a mission and to a SEAT.

    `station` is where this controller sits, and it is what makes the origin a
    fact rather than a guess.

        "I think the destination will typically be in the steerpoints but the
         departure airfield will not. Maybe that's determined from whatever
         clearance opens the plan?"

    A DTC has no origin -- steerpoint one is already airborne -- so every
    attempt to derive one has been an inference: a per-theatre constant, then
    nearest-aerodrome, then the comms ladder. A pilot calling Kobuleti Clearance
    is on Kobuleti's ramp; he cannot be anywhere else and be talking to this
    seat. See #127.
    """
    here = field_of(station)

    def _flight(callsign: str) -> dict | None:
        from marshall.atc import board as F
        for cs in (canonical_callsign(callsign), callsign):
            got = F.find(mission, callsign=cs)
            if got:
                return got
        return None

    def _board() -> list[str]:
        from marshall.atc import board as F
        try:
            return F.callsigns(mission)
        except Exception as e:                  # never lose the refusal to a query
            log.warning("could not list the board: %s", e)
            return []

    def _not_on_the_board(callsign: str) -> str:
        return not_on_the_board(callsign, _board())

    @tool
    def request_clearance(callsign: str, plan: str) -> str:
        """Give a flight its IFR clearance from a plan on file, and get back the
        exact words to say. `plan` is the LABEL of the plan you have decided he
        means -- "Domino", "BatumiTest" -- not his words.

        YOU DECIDE WHICH PLAN, because you are the one who heard him. You have
        every filed label in front of you and he has just told you what he
        wants, in his own words: "the weather run out to Ingress" is Lantern,
        "IFR to Batumi ready to copy" is whichever one that is when only one
        departs this field. An engine used to guess this from the transcript
        and it was worse at it than you are.

        IF YOU CANNOT TELL, ASK HIM -- do not call this with a guess. Two plans
        really can be alike (Samovar and Kettle are the same sortie flown two
        ways), and naming them both back to him costs one transmission where
        clearing him onto the wrong sortie costs the mission. A pilot who
        NAMED a plan has not asked you an ambiguous question; ask only when he
        genuinely has not chosen.

        A label that is not on the board is refused and you will be told what
        IS filed.

        READ THE RETURNED CLEARANCE VERBATIM AND WHOLE. Every element is there
        because a pilot writes it down: clearance limit, route, altitude,
        DEPARTURE FREQUENCY, squawk. Do not paraphrase, round, drop or reorder
        one -- a clearance is the one long transmission on this frequency, and
        the frequency is the element most often lost, which leaves him airborne
        not knowing whom to call.
        """
        # WHAT IS FILED IS LOOKED AT FIRST, and the order is the whole of #126.
        #
        # This asked `_flight(callsign)` and refused on it, so a request that
        # names a plan sitting on file was answered "I have no flight of that
        # name" without the file ever being opened. Three times in a row, to a
        # pilot whose plan was there the whole time:
        #
        #     "clearly he doesn't know how to find my flight plan"
        #
        # He was right about what he heard and wrong about the cause, which is
        # the damage a refusal about the wrong noun does: it sends him hunting
        # in a place where nothing is missing.
        #
        # `resolve` is a pure lookup over `flight_plans` with no side effects
        # and no dependence on the board, so there was never a reason for it to
        # run second -- only the habit of validating the caller first.
        board = filed()
        hit = resolve(plan)
        if hit is None:
            # HE NAMED SOMETHING NOBODY FILED, which is a different answer from
            # "nothing is on file" and the pilot can only act on the right one.
            return (f"No plan called {plan!r} is filed. {P.whats_filed(board)} "
                    f"Tell him what is on file and ask which he wants -- do "
                    f"not clear him on one he did not ask for.")

        # NOW the aeroplane, and the refusal can be honest because both halves
        # are known. A clearance is ISSUED TO an aeroplane -- `assign` needs a
        # flight row -- so this is still a refusal. It is a different one: the
        # plan is there and he is not, which is a fact about identity that he
        # can act on in one transmission.
        f = _flight(callsign)
        if not f:
            return found_but_not_him(callsign, hit, _board())

        plan = hit
        fixes = _known_fixes()
        _, missing = P.route_fixes(plan, fixes)
        if missing:
            # Refused here rather than discovered at the third leg: a route with
            # a point nobody can find is a plan that strands him halfway.
            return (f"That plan routes via {', '.join(missing)}, which is not a "
                    f"fix anybody here holds. Do not clear him on it -- tell him "
                    f"the routing is unavailable and ask him to amend.")

        # THE ORIGIN IS ESTABLISHED HERE, not copied from the template. A filed
        # plan is a route anybody may request; a clearance is issued to ONE
        # aeroplane departing ONE field, and `assigned_plans` has its own origin
        # column for exactly that. Two aircraft may fly the same plan out of
        # different fields on one night.
        got = assign(f["id"], {**plan, "origin": here or plan.get("origin")},
                     mission=mission)
        # THE FIRST LEG IS WHAT HE MAINTAINS; THE HIGHEST IS WHAT HE EXPECTS.
        #
        #     "The Clearance delivery gave me a clearance to 1,000, even though
        #      my first waypoint is 5,000."
        #
        # This passed `cruise_ft` as the initial, so the two were always equal
        # and `plans.clearance`'s "expect ... one zero minutes after departure"
        # clause -- written for exactly this -- could never fire. He was cleared
        # off the ramp to a level a later leg wanted.
        #
        # `legs` carries the profile the pilot actually filed (migration 030).
        # Falls back to the cruise for a plan filed before it, which behaves
        # exactly as it did.
        # LEGS AND NOTHING ELSE. This fell back to `cruise_ft` for a plan
        # filed before migration 030; there is no cruise altitude and the
        # column is gone (#192), so a plan with no legs has no initial level
        # and the clearance says so by omitting it.
        _legs = plan.get("legs") or []
        _initial = (_legs[0].get("alt_ft") if _legs else 0) or 0
        words = P.clearance(plan, flight_id=f["id"],
                            departure_freq=departure_freq(here),
                            initial_ft=_initial)
        # THE LEVEL HE IS NOW HELD TO, written down at the moment it is issued.
        #
        # A clearance IS an altitude assignment -- "maintain five thousand" --
        # and nothing recorded it. `cruise_ft` was standing in, which is the
        # highest level his ROUTE reaches and not the one he may fly now, and
        # #192 removed it. `assigned_ft` is the level the engine issued and the
        # only one separation reads, so this is where it starts. [#192]
        # THROUGH `board.agree`, which is the store's own words for this:
        # "Record something that was AGREED. The only way state changes ...
        # a clearance, a level, a place in the queue." Writing the UPDATE here
        # would have been one more raw statement in a domain module, and the
        # architecture check said so before this comment did.
        if _initial:
            try:
                from marshall.atc import board as _F
                _F.agree(f["id"], assigned_ft=int(_initial))
            except Exception as _e:
                log.warning("could not record the cleared level: %s", _e)
        why = ", ".join(hit.get("why") or []) or "the one on file"
        return (f"SAY THIS, verbatim and complete, after his callsign: {words}\n"
                f"(matched on {why}; plan {got.get('label') or plan.get('name')}. "
                f"Every element above is read out -- the departure frequency is "
                f"not optional.\n"
                f"HIS NEXT TRANSMISSION WILL BE THE READ-BACK, and you do not "
                f"judge it. `marshall-atc` verifies it against this clearance, "
                f"element by element, and hands you the verdict -- say "
                f"\"readback correct\" when it says so, and when it names an "
                f"element he missed, ask for THAT one again and nothing else. "
                f"Silence is not an answer here: he is on the ground with a "
                f"pencil and no way to tell whether you heard him.)")

    @tool
    def clearance_state(callsign: str) -> str:
        """Where this flight stands with its clearance: FILED, ISSUED or
        ACKNOWLEDGED. Ask before you tell a pilot anything about his clearance.

        These are three different things and saying the wrong one is not a
        wording slip. A plan on FILE is a route somebody typed; a clearance
        ISSUED is one you read to him; ACKNOWLEDGED is one he read back
        correctly. "Your read-back was correct" is the sentence that ends
        clearance delivery's business and hands him to Ground, so it may only
        be said when this tool says ACKNOWLEDGED.
        """
        f = _flight(callsign)
        if not f:
            return _not_on_the_board(callsign)
        got = assigned(f["id"])
        if not got:
            n = len(filed())
            return (f"NOT ISSUED. {callsign} has no clearance. There "
                    f"{'is' if n == 1 else 'are'} {n} plan(s) on file he could "
                    f"ask for, and a plan on file is not a clearance -- he has "
                    f"not been read anything and has agreed to nothing. Do not "
                    f"tell him he is cleared.")
        if not got.get("acked_at"):
            return (f"ISSUED, NOT ACKNOWLEDGED. {callsign} was read a clearance "
                    f"({got.get('label') or 'as filed'}) and has not read it "
                    f"back correctly yet. Do not say his read-back was correct. "
                    f"If he has just read it back, `marshall-atc` has already "
                    f"judged it and told you the verdict -- use that.")
        return (f"ACKNOWLEDGED. {callsign} was cleared on "
                f"{got.get('label') or 'the filed plan'} and read it back "
                f"correctly. He is finished with clearance delivery.")

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
               f"top of route {P.top_of_route(plan) or '?'} ft, "
               f"destination {plan.get('destination') or '?'}",
               P.help_level(nav)]
        if missing:
            out.append(f"Unresolved on his route: {', '.join(missing)}.")
        return "\n".join(out)

    return [request_clearance, clearance_state, flight_plan_help]


def _known_fixes() -> dict:
    """Where the points are. Not stored on the plan -- one source of truth for a
    position, so a plan and a chart cannot disagree about INGRESS."""
    try:
        from marshall.feed.tracks import known_fixes
        return {k.lower(): v for k, v in (known_fixes() or {}).items()}
    except Exception:                   # nothing pushed yet; a plan is still readable
        log.warning("no fixes pushed; route resolution will report everything missing")
        return {}
