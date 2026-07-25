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

from dataclasses import dataclass, field


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

    Phase("clearance", owner="ground", aims_at="none",
          follows=("taxi", "filed"),
          note="The IFR clearance, read back on the ramp. The one place "
               "'readback correct' belongs -- airborne, a correct readback is "
               "answered with silence."),

    Phase("taxi", owner="ground", aims_at="none", follows=("departure",),
          note="To the holding point. Ground movement, no geometry."),

    Phase("departure", owner="tower", aims_at="course", follows=("enroute",),
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

    Phase("arrival", owner="approach", aims_at="point",
          follows=("holding", "approach"),
          note="Descending and being set up. Aimed at the gate that puts him "
               "in position for the approach."),

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
