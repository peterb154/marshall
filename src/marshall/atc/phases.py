"""The phases of a sortie, and one handler for all of them.

Every phase asks the geometry the same question -- given where he is and where
he should be going, what heading, what altitude, what speed -- so there is one
geometry engine and one dispatcher, not an engine per phase. What each phase
contributes is three things and only three:

    who owns him      which controller is working him, so a handoff is a
                      consequence of a phase change rather than a special case
    what he aims at   the target the geometry is pointed at. A final approach
                      course, an airway leg, an orbit, a runway centreline --
                      the same maths against a different line
    what may follow   the legal next phases, so "cleared for the approach while
                      holding" is possible and "landed while enroute" is not,
                      and nobody has to remember which

The table below is deliberately COMPLETE while the code behind it is not. A
pilot should eventually be able to fly a whole sortie under ATC -- clearance,
taxi, departure, tasking, recovery -- and naming all of it now is what stops a
component inventing a state that nothing else knows about, which is how three
different ideas of "what is happening" got loose in the first place. Phases
with `handler=None` are declared and unimplemented, which is an honest thing to
be and is visible from here rather than discovered in flight.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    """One phase of a sortie. Data, so a new one is an entry and not a class."""

    name: str
    owner: str                      # sector role that works him here
    aims_at: str                    # 'none' | 'point' | 'course' | 'orbit'
    follows: tuple[str, ...] = ()   # phases that may legally come next
    note: str = ""                  # what the controller's job is, in a line
    handler: str = ""               # the module function that flies it, if any


# The order is the order a sortie happens in, which is the order to read it.
PHASES: dict[str, Phase] = {p.name: p for p in (
    # There are two ways into the system and this is the other one. A pilot may
    # simply call up, with no plan filed and nothing known about him -- which is
    # how every sortie has begun so far. Declaring it keeps it an honest state
    # rather than a gap: he exists, he is on the radio, and we have not yet
    # learned what he wants.
    Phase("unknown", owner="", aims_at="none",
          follows=("enroute", "clearance", "taxi", "arrival", "holding",
                   "approach"),
          note="Heard on the radio and nothing more. Ask his intentions; never "
               "assume them."),

    Phase("filed", owner="", aims_at="none",
          follows=("clearance", "taxi", "enroute"),
          note="A plan exists and there is no aeroplane yet. Nobody works him."),

    Phase("clearance", owner="delivery", aims_at="none",
          follows=("taxi", "filed"),
          note="The IFR clearance, read back on the ramp. The one place "
               "'readback correct' belongs -- airborne, a correct readback is "
               "answered with silence."),

    Phase("taxi", owner="ground", aims_at="none", follows=("holding_short",),
          note="To the holding point AND NO FURTHER. Ground movement, no "
               "geometry. He is cleared to the runway, not onto it."),

    # GROUND DOES NOT CLEAR ANYBODY FOR TAKE-OFF, and this phase is where that
    # becomes structural rather than a rule somebody has to remember:
    #
    #     "Ground should clear to the runway only, telling them to hold short
    #      of the runway. Once they check in and report holding short they
    #      should be handed off to tower. Ground should not clear for takeoff.
    #      That's tower."
    #
    # `taxi` used to run straight to `departure`, so the model said Ground
    # handed a jet to the radar controller and the runway had no owner at all
    # in between. Splitting the holding point out gives Tower something to own:
    # the aeroplane is stopped, on the ground, and the next word he hears is a
    # take-off clearance from the man who owns the runway.
    Phase("holding_short", owner="tower", aims_at="none",
          follows=("departure", "taxi"),
          note="Stopped at the holding point, on Tower's frequency, waiting "
               "for the runway. Ground's work is done; nobody is cleared onto "
               "the runway by anyone but Tower."),

    # `arrival` follows this directly, and not only through `enroute`. The
    # sortie this system actually flies is Kobuleti to Batumi -- twenty four
    # miles -- and on a hop that short there may be no enroute segment at all:
    # Departure hands him straight to Approach. Requiring `enroute` in between
    # meant the transition was refused as illegal and he stayed "departing"
    # while being vectored onto a final.
    Phase("departure", owner="departure", aims_at="course",
          follows=("enroute", "arrival"),
          note="Rolling and climbing out on the runway heading, then turned "
               "on course. The same intercept geometry as an approach, flown "
               "the other way."),

    Phase("enroute", owner="center", aims_at="point",
          follows=("tasked", "arrival", "rtb", "holding"),
          note="The long middle. Direct to a fix or to the destination -- "
               "the geometry's simplest case, a point to fly at."),

    Phase("tasked", owner="overlord", aims_at="point",
          follows=("on_station", "rtb", "enroute"),
          note="Given a job rather than a heading: an area, and something in "
               "it. Overlord's business."),

    Phase("on_station", owner="overlord", aims_at="orbit",
          follows=("tasked", "rtb"),
          note="Working the area. An orbit is a point with a radius, which the "
               "geometry already knows how to fly."),

    Phase("rtb", owner="center", aims_at="point", follows=("arrival", "enroute"),
          note="Going home. Enroute again, with the destination as the point."),

    # THE SAME GEOMETRY AS THE APPROACH, and saying otherwise was a lie by
    # omission. `asr.guide` has flown this phase since it was written -- the
    # "vectoring, twenty three miles, turn right heading two three zero" calls
    # are it, and they happen long before anybody is cleared. Declaring the
    # handler here is what lets the dispatcher fly the arrival without the
    # arrival's guidance being smuggled in as the approach's.
    Phase("arrival", owner="approach", aims_at="course",
          follows=("holding", "approach"),
          note="Descending and being vectored into position. Same geometry as "
               "the approach, flown before the clearance rather than after.",
          handler="marshall.atc.asr:guide"),

    Phase("holding", owner="approach", aims_at="orbit", follows=("approach",),
          note="Waiting his turn, in clear air, at a level of his own. The "
               "hold is a chance to regroup, not something to sweat -- what "
               "has to be right is the sequencing out of it."),

    Phase("approach", owner="approach", aims_at="course",
          follows=("missed", "landed"),
          note="Vectored onto the final approach course and, on a radar "
               "approach, talked down it. The hardest phase and the one that "
               "is finished.",
          handler="marshall.atc.asr:guide"),

    Phase("missed", owner="approach", aims_at="course",
          follows=("holding", "approach", "enroute"),
          note="Went around. The PUBLISHED missed approach, not a vector -- "
               "the plate's track is the one certified to clear the ground, "
               "and vectoring instead flew an aeroplane into the Caucasus.",
          handler="marshall.atc.asr:guide"),

    Phase("landed", owner="tower", aims_at="none", follows=("taxi",),
          note="Down. Off the frequency and out of the sequence."),
)}

# The states the approach half of the system can currently fly. Everything else
# in PHASES is declared and waiting, which is deliberate -- see the docstring.
FLOWN = tuple(p.name for p in PHASES.values() if p.handler)


def get(name: str) -> Phase | None:
    return PHASES.get((name or "").lower())


def may_follow(current: str, nxt: str) -> bool:
    """Is this transition legal?

    Worth asking rather than assuming: three components used to each hold their
    own idea of what was happening, and an aircraft established on final was
    filed as a fresh arrival because nothing said that could not happen.
    """
    p = get(current)
    return bool(p) and nxt.lower() in p.follows


def owner_of(name: str) -> str:
    """Which controller works him in this phase.

    This is what makes a handoff a consequence rather than a special case: the
    phase changes, the owner changes with it, and the aircraft is told to
    contact somebody new because the table says so.
    """
    p = get(name)
    return p.owner if p else ""


def guide(phase: str, pos, profile):
    """Fly whichever phase he is in, or None if we do not fly it yet.

    One dispatcher. The approach phases go to the proven geometry; the rest
    return None, which reads as "no guidance for this phase" and is honest --
    an unimplemented phase should be silent rather than improvising.
    """
    p = get(phase)
    if p is None or not p.handler:
        return None
    module, fn = p.handler.split(":")
    import importlib
    return getattr(importlib.import_module(module), fn)(pos, profile)


# WHERE HE IS IN THE SORTIE, DERIVED FROM FACTS ------------------------------
#
# The table above has been complete and correct since it was written, and it was
# read by two modules: the comms kneeboard page and `handoff.py`. Not the
# controller, not the geometry, not the reply composition. Fifteen phases are
# declared and FIVE are ever set -- clearance, taxi, holding_short, departure --
# every one of them by a ground intent. Nothing has ever set enroute, arrival,
# holding, approach, missed or landed, so once an aeroplane rotates its phase
# freezes on "departure" for the rest of the flight.
#
# Everything else therefore guesses, and the guesses disagree. On 9 August the
# approach geometry was asked about an F-16 one mile off Kobuleti at 950 feet
# and 403 knots, climbing away on runway heading, and answered:
#
#     "he has gone around, one miles. Missed approach: fly heading 330,
#      climb 3000."
#
# It was not wrong about the arithmetic. It was answering a question about an
# approach for an aeroplane that was departing, because nothing told it which
# phase he was in -- and `guide` above, the dispatcher written to prevent
# exactly that, has never been called by anything.
#
# So this is the missing half: one place that says what is happening, from
# facts rather than from what anybody said.

# Phases that mean he is on the ground and being worked by the aerodrome. Which
# one he is in is driven by the CONVERSATION -- a clearance, a taxi request, a
# report of holding short -- because none of them has geometry to read.
ON_THE_GROUND = ("clearance", "taxi", "holding_short", "landed")


def derive(current: str, *, on_ground: bool | None = None,
           separation: str = "", was_airborne: bool = False,
           worked_by: str = "") -> str:
    """The phase he is in NOW, from what is known rather than what was said.

    `separation` is the arrival engine's own enum -- HOLDING, CLEARED, MISSED,
    LANDED -- which is authoritative for the half of the sortie it models,
    because it is what issued the clearances. `on_ground` is the sim's, which is
    authoritative for the other half. Where neither knows, the current phase
    stands: a deriver that invents a transition on missing information is worse
    than one that waits.

    NOTHING IS SKIPPED SILENTLY. A transition the table calls illegal is
    refused and the current phase kept, because "cleared for the approach while
    holding" is legal and "landed while enroute" is not, and the one place that
    knows is this table.
    """
    want = _wanted(current, on_ground, (separation or "").lower(), was_airborne,
                   (worked_by or "").lower())
    if not want or want == (current or ""):
        return current or want
    if not current or current == "unknown":
        return want                     # nothing to transition FROM
    return want if may_follow(current, want) else current


def _wanted(current: str, on_ground: bool | None, sep: str,
            was_airborne: bool, worked_by: str) -> str:
    """The phase the facts point at, before the legality check."""
    # DOWN IS THE ONE FACT NOBODY ARGUES WITH. The sim says so outright, and it
    # settles both ends of the sortie: an aeroplane that has flown and is now
    # stopped has landed, and one that has not flown yet is still on the ramp.
    if on_ground is True:
        if was_airborne or sep == "landed":
            return "landed"
        return current if current in ON_THE_GROUND else "taxi"
    if sep == "landed":
        return "landed"
    if on_ground is False and current in ("clearance", "taxi", "holding_short"):
        # He has left the ground. Whatever the conversation last established,
        # he is departing now.
        return "departure"
    # THE ARRIVAL ENGINE OWNS THE ARRIVAL. These are not guesses about geometry;
    # they are the states in which a clearance has actually been issued.
    if sep == "missed":
        return "missed"
    if sep == "cleared":
        return "approach"
    if sep == "holding":
        return "holding"
    # WHO IS WORKING HIM IS ALSO A FACT. A pilot handed to Approach is arriving,
    # whether or not anybody has cleared him yet -- that is what the handoff
    # MEANT. Without this an aeroplane being vectored towards the final sits in
    # "departure" until the clearance, and gets no guidance for the half of the
    # arrival that most needs it.
    #
    # Only into `arrival`, and only from airborne phases. Deriving every phase
    # from its owner would invert the table -- `handoff.due` reads the phase to
    # decide the controller -- and two rules pointing at each other is how the
    # three disagreeing ideas of "what is happening" got loose to begin with.
    if worked_by == "approach" and current in ("departure", "enroute", "rtb", ""):
        return "arrival"
    return current


def flies_geometry(phase: str) -> bool:
    """Does this phase have guidance to fly at all?

    The question `settle` should have been asking. `aims_at="none"` is a phase
    with nothing to point the geometry at -- every ground phase, and `landed`.
    """
    p = get(phase)
    return bool(p) and p.aims_at != "none" and bool(p.handler)
