"""Which filed plan does he mean? THE CONTROLLER DECIDES; this validates.

It used to decide, with a hand-weighted point system over the transcript --
100 for naming the label, 10 a word for the task, 6 for a route point, 1 for
the destination -- and the whole of that is gone.

WHY IT WENT. The scorer was a worse language model sitting in front of a good
one. The controller calls `request_clearance` having already read the pilot's
words, with every filed label in front of him and the conversation behind him;
he passed the raw transcript in, and a matcher with none of that context
decided. On 18 August it decided wrong:

    PILOT  Roger Sock, I would like Batumi Test, IFR to Batumi.
    ATC    two plans fit that -- say which: transit and recovery filed as
           Batumi Test, or transit and recovery filed as Domino.

He named it. The 100 points for naming a plan outright could not fire, because
the test was `label in said` and a label is TYPED (`BatumiTest`) while a
request is SPOKEN ("Batumi Test"). Only `destination` scored, which both plans
shared, so they tied and the controller was handed a question to ask whose
answer was already in the transmission.

    "lets not implement stopgaps"

Matching letters instead of characters would have fixed that sentence and left
the design: five weights nobody can tune, a noise list, an address parser, and
a stop-word set, all reimplementing comprehension. The fix is to stop.

WHAT SEPARATES PLANS IS STILL WHAT A PILOT WOULD SAY. Every sortie leaves
Batumi and comes home to Batumi, so the civil key -- callsign plus destination
-- separates nothing:

    Samovar  to Batumi   CAS over Tsutsnvati
    Kettle   to Batumi   CAS over Tsutsnvati, beacon letdown on return
    Lantern  to Batumi   Weather reconnaissance out to Ingress
    Marlin   to Batumi   Night patrol of the coastline
    Anvil    to Batumi   Escort a transport as far as Kobuleti

"The weather run out to Ingress" names one of those five and nothing else,
without anybody being taught a syntax. That was always a comprehension problem
and it is now answered by the half that comprehends.

**AMBIGUITY IS STILL ANSWERED BY ASKING**, and that rule did not move -- only
who applies it. Samovar and Kettle are the same sortie flown two ways, and a
controller who cannot tell says so. He can see both labels; he asks.

WHAT IS LEFT HERE IS THE PART A MODEL MAY NOT DO. `named` is an exact lookup,
so the plan an aeroplane is ISSUED is decided by a key and not by a judgment --
which is what makes an assignment auditable, and is the same line #177 drew for
approaches. A label that is not on the board is refused and the refusal says
what IS filed, because the one thing worse than the wrong plan is a menu the
pilot has to guess from.  [#183]
"""

from __future__ import annotations

import re

def named(label: str, plans: list[dict]) -> dict | None:
    """The filed plan the controller named, or None if it is not on the board.

    AN EXACT LOOKUP, and that is the point of it. Which plan an aeroplane is
    issued decides what it is cleared for, so it is settled by a key rather
    than by a judgment -- the judgment happened upstairs, where the words are.

    Case and separators are ignored on both sides because a label is TYPED and
    a controller reads it back out of his own transmission: `BatumiTest`,
    `Batumi Test` and `batumi-test` are one plan. That is normalisation of a
    known identifier, not matching -- there is no scoring here and no
    second-best. Two plans whose labels normalise the same cannot both be
    filed; `filing._LABEL_OK` and the uniqueness check own that.
    """
    want = _key(label)
    if not want:
        return None
    for p in plans:
        if _key(p.get("label")) == want:
            return p
    return None


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def whats_filed(plans: list[dict]) -> str:
    """What IS on the board, for a refusal.

    A refusal that only says "no" makes a pilot guess, and he will guess at the
    thing he already said. Naming the board turns one wasted transmission into
    a choice he can answer -- which is the whole of #126's complaint, one noun
    over: he was told his flight was missing when his PLAN was on file the
    whole time, and went hunting where nothing was wrong.
    """
    live = [p.get("label") for p in plans if p.get("label")]
    if not live:
        return "Nothing is on file at all."
    if len(live) == 1:
        return f"The only plan on file is {live[0]}."
    return (f"On file: {', '.join(live[:-1])} and {live[-1]}.")


RESERVED_SQUAWKS = {"7500", "7600", "7700", "7000", "1200", "0000", "7777"}


def squawk_for(seed: int) -> str:
    """A plausible discrete code, stable for a given flight.

    Octal, so no digit above 7 -- a squawk with an 8 in it is the sort of detail
    that is invisible until somebody who knows notices, and this is a project
    where somebody who knows is the tester.

    Deterministic on purpose: asking for the clearance twice must not produce a
    different code, or a pilot reading back what he wrote down is wrong through
    no fault of his own.
    """
    # Spread the seed across the range before converting. Straight modulo gave
    # flight 1 the code 0001 and flight 2 the code 0002, which is deterministic,
    # legal, and looks exactly like something a computer made up.
    n = (abs(int(seed)) * 2654435761 + 1013904223) % 4096
    for _ in range(4096):
        code = f"{n // 512 % 8}{n // 64 % 8}{n // 8 % 8}{n % 8}"
        if code not in RESERVED_SQUAWKS:
            return code
        n = (n + 1) % 4096
    return "4271"


def _spell(digits: str) -> str:
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "niner"}
    return " ".join(words.get(d, d) for d in str(digits))


def _spell_alt(ft: int) -> str:
    if not ft:
        return ""
    if ft % 1000 == 0:
        return f"{_spell(str(ft // 1000))} thousand"
    return f"{_spell(str(ft // 1000))} thousand {_spell(str((ft % 1000) // 100))} hundred"


def top_of_route(plan: dict) -> int:
    """The highest level this route asks for, from the LEGS.

    THERE IS NO CRUISE ALTITUDE IN A FLIGHT PLAN. There is a level per leg.

        "There is no cruise altitude, this has been something I've harped on
         for weeks. And it's still in the schema? There is only leg altitude."

    `cruise_ft` was `max(alt_ft)` synthesised in `filing.derived` and then
    STORED -- migration 031 removed it from `flight_plans` for being a second
    answer to a question `legs` already answers, and it survived as a column on
    `flights` and on `assigned_plans`, so a number nobody filed was written
    down twice downstream of the table it was deleted from.

    Computed here, at the one point a controller needs it: "expect one zero
    thousand" is the top of his route, and the level he MAINTAINS is `legs[0]`
    until the engine assigns him one (`flights.assigned_ft`). Those are two
    different questions and one column could never answer both -- which
    `filing.derived`'s own docstring said while emitting it anyway. [#192]
    """
    legs = [l for l in (plan.get("legs") or []) if isinstance(l, dict)]
    return max((int(l.get("alt_ft") or 0) for l in legs), default=0)


def clearance(plan: dict, *, flight_id: int, departure_freq: float,
              initial_ft: int, amended_route: str | None = None) -> str:
    """CRAFT, in the order a pilot writes it down.

        Clearance limit, Route, Altitude, Frequency, Transponder

    "As filed" is the load-bearing phrase and is only used when the route is
    genuinely the filed one. An amendment is read out in full, because a pilot
    who hears "as filed" and got something else is exactly the failure that
    phrase exists to prevent -- which also makes it checkable: the words "as
    filed" must never appear beside an amended route.
    """
    dest = plan.get("destination") or "the field"
    cruise = top_of_route(plan)
    route = amended_route or plan.get("route") or ""

    parts = [f"cleared to {dest}"]
    if amended_route:
        parts.append("routing amended, " + ", ".join(
            p.strip().title() for p in route.split(",") if p.strip()))
    else:
        parts.append("as filed")
    if initial_ft:
        parts.append(f"maintain {_spell_alt(initial_ft)}")
    if cruise and cruise != initial_ft:
        parts.append(f"expect {_spell_alt(cruise)} one zero minutes "
                     f"after departure")
    if departure_freq:
        # ONE DECIMAL PLACE LOSES A REAL FREQUENCY. `f"{124.425:.1f}"` is
        # "124.4", and Batumi Approach is on 124.425 -- so a pilot copying his
        # IFR clearance wrote down a channel nobody is listening on, in the
        # first exchange of the sortie. 118.125 came out "one one eight decimal
        # one" and 132.55 as "decimal six", which is not even the same number.
        #
        # `spell_freq` is the one renderer for this and `frequencies.py`, one
        # module over in this same package, already calls it. Two spellings of
        # one number is how they come to disagree.
        from marshall.core.say import spell_freq
        parts.append(f"departure frequency {spell_freq(float(departure_freq))}")
    parts.append(f"squawk {_spell(squawk_for(flight_id))}")
    return ", ".join(parts) + "."


# --- the route on the ground, and how much help he needs with it -------------

def route_fixes(plan: dict, fixes: dict) -> tuple[list[dict], list[str]]:
    """The plan's route as places, and anything that could not be found.

    Coordinates are NOT stored on the plan. They live in the fix table, which is
    projected by the sim from route.py -- one source of truth for where a point
    is, so a plan and a chart cannot disagree about INGRESS. A plan names fixes;
    this turns the names into positions.

    The unresolved list is returned rather than dropped. A route with a fix
    nobody can find is a plan that will strand a pilot halfway, and the
    controller should refuse it at clearance delivery rather than discover it at
    the third leg.
    """
    # A PLAN DEFINES ITS OWN PRIVATE FIXES, and they are looked up first.
    #
    #     "there are public fixes that are known to everybody because they're on
    #      a plate, and private fixes that are in a Flight plan. But ATC should
    #      be able to get and refer to my private fixes when I open a plan with
    #      those fixes and the names in there."
    #
    # `legs` carries them with their positions, so opening the plan is what
    # makes FOO resolvable -- which is exactly what "private" means. The public
    # catalogue is still the authority for everything on a plate; a plan may
    # not redefine DIOMI.
    own = {(l.get("fix") or "").lower(): l for l in (plan.get("legs") or [])
           if l.get("lat") is not None and l.get("lon") is not None}
    out, missing = [], []
    for raw in (plan.get("route") or "").split(","):
        name = raw.strip()
        if not name:
            continue
        ll = fixes.get(name.lower())
        mine = own.get(name.lower())
        # HIS OWN POSITION FIRST, and this order is the whole rule.
        #
        #     "he can only fly, 1) his steerpoints, 2) navaids he can tune"
        #
        # A DCS jet has no navigation database. If FYTTR is both a published
        # fix and a steerpoint in his cartridge, the aeroplane is going to fly
        # to HIS -- so a controller working from ours is wrong about where the
        # aircraft will be, which is worse than the disagreement it was trying
        # to avoid. This used to check the catalogue first, which is how a
        # plan's own INITIAL was silently discarded.
        if mine:
            out.append({"name": name, "lat": mine["lat"], "lon": mine["lon"],
                        "private": True})
        elif ll:
            out.append({"name": name, "lat": ll[0], "lon": ll[1]})
        else:
            missing.append(name)
    return out, missing


# What the aeroplane can do about navigation, which decides how much the
# controller needs to do FOR him.
#
#   ins   he knows where he is to the foot. Naming the fix is enough, and a
#         running commentary is noise over somebody who is already there.
#   adf   he can home a beacon. The AN/ARA-8 exists on the P-51D-30 and nothing
#         else in this hangar, which is why the beacon letdown was locked to one
#         airframe.
#   dr    a compass, a watch and a map. He needs position reports going out and
#         vectors coming back, and he is the reason the radar approach exists.
#
# Keyed on the type the SIM reports, because that is what radar already carries
# -- "362nd_sockeye [Hoover 1-1] (P-51D-30-NA)" -- so nobody has to declare it.
NAV_BY_TYPE = {
    "P-51D-30-NA": "adf",
    "P-51D": "dr",
    "P-47D-30": "dr",
    "SpitfireLF Mk IX": "dr",
    "SpitfireLFMkIX": "dr",
    "F4U-1D": "dr",
    "Bf-109K-4": "dr",
    "FW-190D9": "dr",
}


#   ""    NOBODY HAS TOLD US WHAT HE IS FLYING. Not a capability at all, and
#         that is the point of its being here: an absent airframe used to be
#         answered with `dr`, the most pessimistic of the three, so "we have not
#         identified him" was indistinguishable from "we know he is on a compass
#         and a watch". There was no output meaning "we do not know". [#153]


def nav_of(aircraft_type: str | None) -> str:
    """How he navigates, or "" when nothing has said what he is flying.

    THE TWO UNKNOWNS ARE DIFFERENT QUESTIONS and answering them the same way is
    the whole of [#153]'s third site:

        an unlisted TYPE      we know the airframe, it is not in the table.
                              Answered GENEROUSLY, and deliberately: a type
                              nobody listed is far more likely to be a jet with
                              an inertial platform than a 1944 fighter, and
                              treating an F-16 like a Mustang produces a
                              controller reading ranges to a man watching a
                              moving map -- chatter over somebody busy.
        NO TYPE AT ALL        `clearance.aircraft_type` returns None both when
                              the pilot has not been correlated to a track yet
                              and when the row is missing. That is not an
                              airframe we failed to recognise; it is an airframe
                              nobody has stated.

    The first still gets `ins`. The second gets "", and `help_level` says so in
    words rather than inventing the most pessimistic capability and handing the
    controller a flat instruction built on it.

    A CONFIDENT DENIAL IS THE FAILURE THIS PROJECT KEEPS PRODUCING, and it is
    worse from here than from most places, because the agent VOICES what
    `help_level` returns. "I do not know" and "it does not exist" are two
    different sentences and only one of them is usually true.
    """
    if not aircraft_type or not aircraft_type.strip():
        return ""
    return NAV_BY_TYPE.get(aircraft_type.strip(), "ins")


def help_level(nav: str) -> str:
    """One line the controller's prompt can act on.

    THE EMPTY KEY IS AN ANSWER NOW. It used to fall through to "", so a flight
    with no known airframe contributed no line at all -- and before that it never
    arose, because `nav_of` turned an absent airframe into `dr` and the
    controller was told flatly that a man he had not yet identified could not
    tell him where he was. What he is handed instead names the gap and says what
    to do about it, which is what a real controller does: he asks. [#153]
    """
    return {
        "ins": "He has an inertial platform and knows his position exactly. "
               "Name the fix and leave him alone; do not read him ranges.",
        "adf": "He can home a beacon but has no position fix of his own. Give "
               "him the beacon and expect a report over it.",
        "dr": "Dead reckoning only -- a compass, a watch and a map. He needs "
              "position reports outbound and vectors home, and he cannot tell "
              "you where he is more precisely than a landmark.",
        "": "Nothing has told us what he is flying -- radar has not been "
            "correlated to him yet -- so how much navigation help he needs is "
            "UNKNOWN. Do not assume either way. If it matters for what you are "
            "about to give him, ask him what he is flying.",
    }.get(nav, "")
