"""Who has him next, and when. Rules as data, because more controllers are coming.

    "Don't hard code these rules too much yet, because we haven't added
     clearance delivery or ground yet. Those will be different controllers with
     different handoffs."

WHAT THIS REPLACES. `handoff_on_the_event` was a hardcoded pair:

    on the ground and I am approach  -> tower
    airborne and I am tower          -> approach

Two roles, two branches. Add clearance delivery, ground, departure and center
and that is a matrix living in an if-chain, with every field wanting different
numbers -- which is the shape of a thing that should have been a table since the
second controller.

So: the RULE is code and the NUMBER is data, the same split `STRUCTURE.md`
draws for procedures. A new controller adds rows. Only a genuinely new KIND of
condition adds a predicate.

RANGE ALONE IS AMBIGUOUS, and this is why the conditions are named for the
event rather than the distance. Five miles outbound climbing and five miles
inbound descending are the same range and opposite situations; a bare
`at_5nm` rule would hand a departing aircraft straight back to Tower. So
`airborne_beyond` and `inbound_within` are separate conditions, and each reads
the trend as well as the distance.

A STATION IS WHO HAS HIM; A ROLE IS WHAT HE IS CALLED.

    "Batumi Approach and Batumi Departure would always run on the same frequency
     (even at busy airports like Nellis) and they are synonyms for each other."

So a "handoff" whose target resolves to the SAME station is not a handoff. The
man does not change, the frequency does not change, and telling a pilot to
contact the person he is already talking to is nonsense on the radio. What
changes is what that controller answers as -- Departure while you are going out,
Approach while you are coming back -- which `Station.also` already models and
nothing was reading. See `due`, which returns that case separately.
"""

from __future__ import annotations

from dataclasses import dataclass

# How far out he must be before Tower is finished with him, and how close before
# Approach gives him back. Defaults, in nautical miles.
#
# THESE BELONG TO THE FIELD, not to this module -- Kobuleti may want eight and a
# fighter base may want fifteen. They are arguments with defaults until the
# airfield table exists (see SCHEMA.md), and the day it does they become a
# column and this comment becomes wrong, which is the point of writing it here.
DEPARTURE_NM = 5.0
ARRIVAL_NM = 5.0


@dataclass(frozen=True)
class Rule:
    """One controller finishing with an aircraft, and who gets him.

    `when` names a condition rather than describing a distance, because the
    distance is the parameter and the situation is the rule.
    """
    frm: str            # the role he is with now
    to: str             # the role that should have him
    when: str           # a name from CONDITIONS below
    nm: float | None = None


# THE ORDER IS THE PRIORITY. First rule whose condition holds, wins -- so a
# specific case can be put above a general one without either knowing about the
# other.
RULES: tuple[Rule, ...] = (
    # Outbound. Tower keeps him until he is clear of the circuit.
    Rule("tower", "departure", "airborne_beyond", DEPARTURE_NM),
    # Inbound. Approach hands him over when the runway is his problem.
    Rule("approach", "tower", "inbound_within", ARRIVAL_NM),
    # On the ground under a radar controller at all is a mistake to correct --
    # he has landed and nobody noticed, or he never left. Either way Tower.
    Rule("approach", "tower", "on_ground"),
    Rule("departure", "tower", "on_ground"),
    # NOT WRITTEN YET, and deliberately absent rather than guessed:
    #   Rule("clearance", "ground", "cleared_and_ready")
    #   Rule("ground",    "tower",  "holding_short")
    # Both need a state nothing currently reports -- "he has his clearance and
    # is ready to push" is not a fact the sim gives us, and inventing a
    # condition before there is anything to satisfy it would be a rule that can
    # only ever be wrong.
)


def _airborne_beyond(st, nm: float | None) -> bool:
    return bool(not st.on_ground and st.range_nm is not None
                and nm is not None and st.range_nm >= nm)


def _inbound_within(st, nm: float | None) -> bool:
    """Close AND getting closer. The trend is what makes it an arrival.

    Without it this fires on a departure at the same range, and a climbing
    aeroplane gets handed to Tower on his way out.
    """
    return bool(not st.on_ground and st.range_nm is not None
                and nm is not None and st.range_nm <= nm and st.inbound)


def _on_ground(st, nm: float | None) -> bool:
    return bool(st.on_ground)


CONDITIONS = {
    "airborne_beyond": _airborne_beyond,
    "inbound_within": _inbound_within,
    "on_ground": _on_ground,
}


@dataclass(frozen=True)
class State:
    """What a rule is allowed to look at.

    Deliberately small. A condition that needs something not in here is a
    condition that wants a new fact published, and making that visible is worth
    more than the convenience of passing the whole world in.
    """
    on_ground: bool
    range_nm: float | None
    inbound: bool


@dataclass(frozen=True)
class Verdict:
    """What should happen, and whether the pilot hears about it."""
    station: object          # the Station that should have him
    role: str                # what that station answers as now
    same_station: bool       # True -> no frequency change, no transmission

    def __bool__(self) -> bool:
        return self.station is not None


def due(profile, me, st: State) -> Verdict | None:
    """Is a handoff due, and is it a real one?

    `me` is the station the pilot is CURRENTLY talking to -- from the frequency
    he checked in on, never from whichever channel a thread happens to transmit
    over. Reading the wrong one made every aircraft look like Approach's and the
    tower-to-departure rule could not fire for anybody.

    Returns None when nothing is due. Returns a Verdict with `same_station` set
    when the next role is covered by the man he already has: Approach and
    Departure are one person on one frequency, so that is a change of NAME and
    not of controller.
    """
    if me is None or not getattr(me, "role", ""):
        return None
    role = me.role
    for rule in RULES:
        if rule.frm != role and rule.frm not in getattr(me, "also", ()):
            continue
        cond = CONDITIONS.get(rule.when)
        if cond is None or not cond(st, rule.nm):
            continue
        nxt = profile.station_for(rule.to)
        if nxt is None:
            continue
        same = (getattr(nxt, "name", None) == getattr(me, "name", None))
        return Verdict(station=nxt, role=rule.to, same_station=same)
    return None
