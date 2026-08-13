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
`outbound_beyond` and `inbound_within` are separate conditions, and each reads
the trend as well as the distance.

The module said that from the beginning and one of its own conditions did not
obey it: `airborne_beyond` checked the range and not the trend, and got away
with it because the only rule using it was tower -> departure, where an arrival
is rarely still on Tower's frequency. It is `outbound_beyond` now. A principle
stated in a docstring is not enforced by the docstring.

THERE IS ONE TABLE, and there used to be two. `route.handoff_from` answered
this same question for the receive path while these rules answered it for the
proactive monitor, and they were not duplicates -- they were complementary
halves, each missing what the other had. Which rules applied therefore depended
on whether the pilot happened to key the mic. A live sortie was held by Center
at 44 nm with nothing able to move him on, because the only rule that could was
in the half the monitor does not read; he declared an emergency to get out of
it. `handoff_from` is deleted. [#51]

A CONDITION MAY CONSULT THE PROCEDURE, not just the geometry -- it is handed
the profile and its own rule. That is what lets "a talkdown makes landing the
trigger rather than a distance" live here rather than as an `if` at one call
site, which is how the split started.

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

from marshall.atc import phases as _phases
from marshall.core import airspace as _airspace
from marshall.core import route as _route

# How far out he must be before Tower is finished with him, and how close before
# Approach gives him back. Defaults, in nautical miles.
#
# THESE BELONG TO THE FIELD, not to this module -- Kobuleti may want eight and a
# fighter base may want fifteen. They are arguments with defaults until the
# airfield table exists (see SCHEMA.md), and the day it does they become a
# column and this comment becomes wrong, which is the point of writing it here.
DEPARTURE_NM = 5.0
ARRIVAL_NM = 5.0
# Where Center gives him to Approach. Bigger than the others by an order of
# magnitude because it is a different kind of boundary: the others are circuit
# distances and this is the edge of the terminal area.
#
# It lived on the profile as `approach_hands_over_nm` and was read by a SECOND
# handoff mechanism -- see the module docstring on why there is only one now.
#
# AND IT IS THE SAME NUMBER AS THE EDGE OF APPROACH'S VOLUME, so it is imported
# rather than restated. They are two statements of one boundary -- this one in
# procedure, that one in geography -- and holding them separately is one edit
# away from a ladder that hands a man over at twenty-five miles into airspace
# that stops at twenty. Procedure may read geography; the reverse would put a
# rule table underneath a map. See LAYERS.md and `core.airspace.TERMINAL_NM`.
CENTER_NM = _airspace.TERMINAL_NM


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
    Rule("tower", "departure", "outbound_beyond", DEPARTURE_NM),
    # ENROUTE TO TERMINAL. Center gives him up at the edge of the area.
    #
    # THIS ROW IS THE BUG. It existed only in `route.handoff_from`, which is
    # consulted when the pilot TRANSMITS -- so the proactive monitor, which is
    # what hands everybody else over unprompted, could never move anyone off
    # Center at all. A live sortie sat at 44 nm being told to continue holding,
    # nineteen miles outside the airspace Approach would have taken him in,
    # with no mechanism in the system that could have helped him. He declared
    # an emergency. [#51]
    Rule("center", "approach", "inbound_within", CENTER_NM),
    # AND THE MIRROR OF IT, which only became visible once the ladder could be
    # read end to end in one place. Nothing handed a DEPARTURE to Center, so a
    # jet leaving Kobuleti stayed with Kobuleti Departure to the far side of
    # the map while the comms card told him preset 4 was for the enroute leg.
    # The same fault as the missing Center row and in the same table -- found
    # by printing the ladder rather than by anybody flying it.
    Rule("departure", "center", "outbound_beyond", CENTER_NM),
    # Inbound. Approach hands him over when the runway is his problem.
    Rule("approach", "tower", "inbound_within", ARRIVAL_NM),
    # On the ground under a radar controller at all is a mistake to correct --
    # he has landed and nobody noticed, or he never left. Either way Tower.
    Rule("approach", "tower", "on_ground"),
    Rule("departure", "tower", "on_ground"),
    # THE GROUND TRANSITIONS ARE NOT ROWS, and that is the design rather than
    # an omission. These two used to be listed here as deliberately-absent:
    #
    #   clearance -> ground   when the clearance has been read back
    #   ground    -> tower    when he is holding short
    #
    # Neither is a distance. Two aircraft parked side by side, one waiting for
    # a clearance and one waiting for the runway, are the same range and the
    # same direction and belong to different controllers -- so writing them as
    # geometry would be inventing a measurement that does not exist.
    #
    # They are handled by PHASE OWNERSHIP in `due` instead: a phase with no
    # geometry is owned outright by the controller the phase table names, and
    # moving into it IS the handoff. That is what `phases.py` said this design
    # was for. It also means the next ground procedure -- pushback, de-icing,
    # progressive taxi -- needs a phase and no row at all.
)


def _outbound_beyond(st, nm: float | None, profile=None, rule=None) -> bool:
    """Far out AND going further. The trend, for the same reason as arrivals.

    THIS USED TO BE `airborne_beyond` AND IGNORED THE DIRECTION, which broke
    the rule this module's own docstring opens with: five miles outbound
    climbing and five miles inbound descending are the same range and opposite
    situations.

    It survived because the only rule using it was tower -> departure, and an
    arrival is rarely still on Tower's frequency at six miles. Adding
    departure -> center made it reachable immediately: an aeroplane twenty-five
    miles out INBOUND, being worked by Approach -- who also wears the departure
    hat -- matched "airborne beyond twenty-five" and was handed to Center, away
    from the field he was arriving at.

    Caught by a test that had been passing for weeks, on a rule I had just
    added. The condition was wrong the whole time; nothing had asked it the
    question from the other side.
    """
    return bool(not st.on_ground and not st.inbound and st.range_nm is not None
                and nm is not None and st.range_nm >= nm)


def _inbound_within(st, nm: float | None, profile=None, rule=None) -> bool:
    """Close AND getting closer. The trend is what makes it an arrival.

    Without it this fires on a departure at the same range, and a climbing
    aeroplane gets handed to Tower on his way out.

    A TALKDOWN KEEPS HIM TO THE GROUND, and that rule used to live as an `if`
    in the bridge's receive path, which meant only half the system obeyed it:

        "Real practice keeps him: the final controller obtains the landing
         clearance from Tower and relays it, and the pilot never changes
         frequency inside the final."

    On a surveillance approach the controller IS the approach aid -- he reads
    the range every mile and corrects the heading -- so handing him to Tower at
    five miles abandons the pilot at the moment the procedure starts. It did,
    live, at ten miles in cloud.

    The guard was written in the bridge because `handoff_from` had no idea
    whether the aeroplane was inbound, on the ground, or going around, and
    blocking the whole transition was the only tool available. Here there is
    `on_ground` -- so the talkdown does not suppress the handoff, it just makes
    LANDING the trigger instead of a distance, which is what it always was.
    """
    if (profile is not None
            and getattr(rule, "to", "") == "tower"
            and getattr(profile, "guidance", "") == "talkdown"
            and not st.on_ground):
        return False
    return bool(not st.on_ground and st.range_nm is not None
                and nm is not None and st.range_nm <= nm and st.inbound)


def _on_ground(st, nm: float | None, profile=None, rule=None) -> bool:
    return bool(st.on_ground)


CONDITIONS = {
    "outbound_beyond": _outbound_beyond,
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
    # WHAT HE IS DOING, which is how the ground half of the sortie is handed
    # over at all.
    #
    # Every rule above this is geometry: a range and a direction. That works in
    # the air and says nothing whatever on the ramp, where the transitions are
    # procedural -- his clearance was read back correctly, he reported holding
    # short -- and a distance cannot see any of it. Two aircraft parked side by
    # side, one waiting for a clearance and one waiting for the runway, are the
    # same range and the same direction and belong to different controllers.
    #
    # Empty means "not told", and everything falls back to the geometry, which
    # is what the airborne half has always done.
    phase: str = ""


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
    # THE PHASE OWNS HIM, WHERE THERE IS NO GEOMETRY TO ARGUE WITH.
    #
    #     "This is what makes a handoff a consequence rather than a special
    #      case: the phase changes, the owner changes with it."
    #      -- phases.py, which declared this design before anything used it
    #
    # The ground half of a sortie has no distances in it. Clearance hands to
    # Ground when the clearance is read back; Ground hands to Tower when he is
    # holding short. Neither is a range, and writing them as ranges would be
    # inventing a geometry that is not there.
    #
    # So a phase whose `aims_at` is "none" -- clearance, taxi, holding short,
    # landed -- is owned OUTRIGHT by the controller the phase table names, and
    # moving into it IS the handoff. No row is needed, and adding a ground
    # procedure later needs no row either.
    #
    # Phases that DO aim at something (enroute, arrival, approach) are left to
    # the rules below, and must be: an arrival in `holding` is owned by
    # Approach the whole time, but he is Center's until twenty-five miles, and
    # phase-ownership alone would snatch him at any distance.
    if st.phase:
        want = _phases.owner_of(st.phase)
        aims = getattr(_phases.get(st.phase), "aims_at", "")
        if want and aims == "none" and want != role \
                and want not in getattr(me, "also", ()):
            nxt = _route.station_for(want, field=getattr(me, "field", ""),
                                     procedure=profile)
            if nxt is not None:
                same = (getattr(nxt, "name", None) == getattr(me, "name", None))
                return Verdict(station=nxt, role=want, same_station=same)
    for rule in RULES:
        if rule.frm != role and rule.frm not in getattr(me, "also", ()):
            continue
        cond = CONDITIONS.get(rule.when)
        # The profile and the rule are passed so a condition can consult the
        # PROCEDURE as well as the geometry -- a talkdown makes landing the
        # trigger rather than a distance. Without them that rule has to live as
        # an `if` at one call site, which is how this ended up with two handoff
        # mechanisms that disagreed.
        if cond is None or not cond(st, rule.nm, profile, rule):
            continue
        # HIS FIELD, or the handoff crosses the theatre. A role is unique within
        # an aerodrome and not across one -- with Kobuleti and Batumi both on
        # the route there are two Towers and two Departures, and an unqualified
        # lookup returns whichever is listed first. That put a Kobuleti
        # departure on Batumi Departure's frequency, forty miles from the man
        # who actually had him, and nothing raised: both answers are a real
        # Station. See `station_for`, which is why it takes a field at all.
        nxt = _route.station_for(rule.to, field=getattr(me, "field", ""),
                                 procedure=profile)
        if nxt is None:
            continue
        same = (getattr(nxt, "name", None) == getattr(me, "name", None))
        return Verdict(station=nxt, role=rule.to, same_station=same)
    return None
