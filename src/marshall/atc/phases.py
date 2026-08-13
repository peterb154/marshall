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
                      holding" is possible and "landed while still on the ramp"
                      is not, and nobody has to remember which

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
    # AND `landed` FOLLOWS THIS, AND EVERY OTHER AIRBORNE PHASE. It used to
    # follow `approach` alone, so the sim stating the one fact nobody argues
    # with lost to the table: a departure that comes straight back, a straight-in
    # nobody formally cleared, a pilot who breaks off a hold and lands were each
    # refused and kept their phase. `derive`'s own reasoning opens with "DOWN IS
    # THE ONE FACT NOBODY ARGUES WITH" and `may_follow` argued with it.
    #
    # Touching down is an OBSERVATION, not a procedural transition, and an
    # observation cannot be illegal. What stays refused is `landed` out of a
    # GROUND phase -- which is the case `follows` was written to protect, and
    # the reason a parked aeroplane that has never flown is not "landed".
    #
    # It is spelled out per phase rather than special-cased inside `may_follow`,
    # because this table is meant to be READ: a reader asking what may follow an
    # arrival should see the answer here and not in a predicate two hundred
    # lines down. `test_phases_derive` sweeps `has_flown` against these tuples
    # so the two cannot drift when a phase is added. [#151]
    Phase("departure", owner="departure", aims_at="course",
          follows=("enroute", "arrival", "landed"),
          note="Rolling and climbing out on the runway heading, then turned "
               "on course. The same intercept geometry as an approach, flown "
               "the other way."),

    Phase("enroute", owner="center", aims_at="point",
          follows=("tasked", "arrival", "rtb", "holding", "landed"),
          note="The long middle. Direct to a fix or to the destination -- "
               "the geometry's simplest case, a point to fly at."),

    Phase("tasked", owner="overlord", aims_at="point",
          follows=("on_station", "rtb", "enroute", "landed"),
          note="Given a job rather than a heading: an area, and something in "
               "it. Overlord's business."),

    Phase("on_station", owner="overlord", aims_at="orbit",
          follows=("tasked", "rtb", "landed"),
          note="Working the area. An orbit is a point with a radius, which the "
               "geometry already knows how to fly."),

    Phase("rtb", owner="center", aims_at="point",
          follows=("arrival", "enroute", "landed"),
          note="Going home. Enroute again, with the destination as the point."),

    # THE SAME GEOMETRY AS THE APPROACH, and saying otherwise was a lie by
    # omission. `asr.guide` has flown this phase since it was written -- the
    # "vectoring, twenty three miles, turn right heading two three zero" calls
    # are it, and they happen long before anybody is cleared. Declaring the
    # handler here is what lets the dispatcher fly the arrival without the
    # arrival's guidance being smuggled in as the approach's.
    Phase("arrival", owner="approach", aims_at="course",
          follows=("holding", "approach", "landed"),
          note="Descending and being vectored into position. Same geometry as "
               "the approach, flown before the clearance rather than after.",
          handler="marshall.atc.asr:guide"),

    Phase("holding", owner="approach", aims_at="orbit",
          follows=("approach", "landed"),
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
          follows=("holding", "approach", "enroute", "landed"),
          note="Went around. The PUBLISHED missed approach, not a vector -- "
               "the plate's track is the one certified to clear the ground, "
               "and vectoring instead flew an aeroplane into the Caucasus.",
          handler="marshall.atc.asr:guide"),

    Phase("landed", owner="tower", aims_at="none", follows=("taxi_in",),
          note="Down and still on the runway, which is Tower's. The roll is "
               "over; he has not left the strip yet."),

    # TAXIING IN, AND IT IS NOT THE SAME PHASE AS TAXIING OUT.
    #
    #     PILOT: Taxi to parking my discretion, sockeye.
    #     ATC:   Sockeye, contact Batumi Tower one one eight decimal six.
    #     PILOT: Batumi Ground, don't you own parking instructions?
    #
    # `landed` is TOWER's, correctly -- he is on the runway. Nothing moved him
    # off it, so Ground looked at a landed aeroplane, read Tower's phase, and
    # handed him BACK. A rung that hands backwards puts a pilot on a frequency
    # whose controller has already finished with him, which is how a man ends up
    # talking to nobody at the end of a flight.
    #
    # `taxi` could not be reused: it means "to the holding point AND NO FURTHER",
    # it leads to a runway, and `holding_short` follows it. This one leads to a
    # stand and NOTHING follows it. Two journeys across the same tarmac in
    # opposite directions, and giving them one name is what made the ladder
    # circular. [#100]
    Phase("taxi_in", owner="ground", aims_at="none", follows=(),
          note="Off the runway, to a stand. THE END OF THE LADDER -- Ground is "
               "the last controller of the sortie and parking is his. There is "
               "nothing after him and nobody to hand back to."),
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

# Phases that mean he is on the ground and being worked by the aerodrome, in
# ladder order. Which one he is in is driven by the CONVERSATION -- a clearance,
# a taxi request, a report of holding short -- because none of them has geometry
# to read. `_wanted` seeds a fresh aeroplane at the first of them and leaves the
# rest to what is said.
ON_THE_GROUND = ("clearance", "taxi", "holding_short", "landed",
                 "taxi_in")

# ...AND THE PHASES THAT MEAN NOTHING HAS HAPPENED YET. `unknown` is a man on
# the radio and nothing more; `filed` is a plan with no aeroplane under it.
# Neither says he is on an aerodrome and neither says he has flown, so they are
# their own answer rather than the absence of one.
NOT_YET = ("", "unknown", "filed")


def has_flown(phase: str) -> bool:
    """Has he left the ground on this sortie? THE PHASE SAYS SO.

    WHY THIS IS A FUNCTION AND NOT A COUNTER. `derive` takes `was_airborne`
    because "he is stopped on the aerodrome" means LANDED for an aeroplane that
    has flown and "still on the ramp" for one that has not -- the same fact,
    two opposite phases. The bridge answered it with `bool(ac.approaches)`,
    which counts GO-AROUNDS: `Controller._do_missed` is the only thing that
    increments it. So every pilot who flew an approach and landed off it --
    which is every normal sortie -- was reported as never having been airborne,
    and a landing that the separation engine had not already called was derived
    as "he is where he was".

    The consequence is the ground half of the sortie. `sortie_phase` never
    reached `landed`, so `handoff.due` had no phase to hand him to Tower or
    Ground with (#77), and `intents` reads the same field to tell "taxi to
    parking" from "ready to taxi" (#100) -- so the last request of a flight was
    answered as though it were the first.

    Nobody had to guess: the phase he is in IS the record of where he has been.
    `departure`, `enroute`, `arrival`, `approach`, `missed` are airborne phases
    by construction, and a counter of one particular way of having been airborne
    is a side-effect standing in for the fact.
    """
    p = (phase or "").lower()
    return p not in NOT_YET and p not in ON_THE_GROUND


def derive(current: str, *, on_ground: bool | None = None,
           separation: str = "", was_airborne: bool = False,
           worked_by: str = "", refused=None) -> str:
    """The phase he is in NOW, from what is known rather than what was said.

    `separation` is the arrival engine's own enum -- HOLDING, CLEARED, MISSED,
    LANDED -- which is authoritative for the half of the sortie it models,
    because it is what issued the clearances. `on_ground` is the sim's, which is
    authoritative for the other half. Where neither knows, the current phase
    stands: a deriver that invents a transition on missing information is worse
    than one that waits.

    `was_airborne` IS EXTRA EVIDENCE, NOT THE EVIDENCE. Whether he has flown is
    read off `current` by `has_flown`, because the phase is what holds it; a
    caller that knows better may still say so, and may only add. It was being
    answered with a count of go-arounds -- see `has_flown` for what that cost.

    NOTHING IS SKIPPED SILENTLY. A transition the table calls illegal is
    refused and the current phase kept, because "cleared for the approach while
    holding" is legal and "landed while still on the ramp" is not, and the one
    place that knows is this table.

    AND AN OBSERVATION IS NOT A TRANSITION. `landed` follows every airborne
    phase, because the sim saying the wheels are down is a fact and not a
    proposal -- see the table. A phase machine that refuses an observed fact is
    asserting something it cannot know. [#151]

    `refused(current, wanted)` is called when that happens, so the refusal
    appears in the log instead of only its consequences. A phase that will not
    move is indistinguishable from a phase nothing is trying to move, and the
    difference is the whole diagnosis.
    """
    want = _wanted(current, on_ground, (separation or "").lower(), was_airborne,
                   (worked_by or "").lower())
    if not want or want == (current or ""):
        return current or want
    if not current or current == "unknown":
        return want                     # nothing to transition FROM
    if may_follow(current, want):
        return want
    # REFUSED, AND SAYING SO IS THE POINT. A transition the table calls illegal
    # is correctly refused -- but refusing SILENTLY is how a phase gets welded
    # in place. One bad input once, and the aeroplane stays in that phase for
    # the rest of the sortie with nothing anywhere saying why.
    #
    # That is not hypothetical. On 10 August an aircraft sat in `departure` from
    # rotation to thirteen miles on the approach -- through Center, through the
    # hand-off to Batumi Approach, through "I'll take the surveillance approach"
    # -- and the only trace was the CONSEQUENCE, twenty times over:
    #
    #     .. ASR guidance suppressed: he is in the departure phase
    #
    # which says what happened and nothing about why. The refusal that caused it
    # left no record at all. Same rule as `check.py`: skipped is reported, never
    # silent.
    if refused is not None:
        refused(current, want)
    return current


def _wanted(current: str, on_ground: bool | None, sep: str,
            was_airborne: bool, worked_by: str) -> str:
    """The phase the facts point at, before the legality check."""
    # DOWN IS THE ONE FACT NOBODY ARGUES WITH. The sim says so outright, and it
    # settles both ends of the sortie: an aeroplane that has flown and is now
    # stopped has landed, and one that has not flown yet is still on the ramp.
    if on_ground is True:
        # HAS HE FLOWN? READ IT OFF THE PHASE, do not take a caller's word for
        # it and do not accept a counter of go-arounds in its place. See
        # `has_flown`: `was_airborne` stays because a caller may know something
        # the phase does not (a flight row that outlived a bridge restart), but
        # it may only ADD evidence, never withhold it.
        if was_airborne or has_flown(current) or sep == "landed":
            return "landed"
        # WHICH GROUND RUNG HE IS ON IS NOT A GEOMETRIC FACT, and this line
        # used to invent one. A parked aeroplane with no phase yet was derived
        # as `taxi` -- so the sortie began on Ground's rung, the clearance rung
        # was skipped entirely, and `clearance_read_back` moving him to `taxi`
        # moved him nowhere. That is why a correct read-back never handed
        # anybody to Ground: there was no transition to hand over, because he
        # had been Ground's since the moment he appeared on radar.
        #
        # Clearance, taxi and holding short are the same range, the same
        # direction and the same zero knots -- see `handoff.State`, which says
        # so about the rules and was right about the deriver too. Radar cannot
        # tell them apart and must not pretend to. What separates them is what
        # was SAID, and every one of those transitions has an intent behind it.
        #
        # So: seed a fresh aeroplane at the FIRST rung and never overrule the
        # conversation afterwards. `on_ground is False` above still catches him
        # leaving the ground, which is the one ground transition radar can see.
        return current or ON_THE_GROUND[0]
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
    # AND THE SAME FACT ONE RUNG EARLIER, which was missing. `enroute` was
    # declared, owned by Center, and named as a successor by four other phases
    # -- and NOTHING RETURNED IT. Swept from `departure` the reachable set was
    # {arrival, departure}, so an aeroplane crossed the theatre with the board
    # still saying `departure` the whole way.
    #
    # It took the task half with it: `tasked` and `on_station` follow only from
    # `enroute`, so a strike, a CAS check-in and a tanker join were unreachable
    # by construction however they read on the page. [#168]
    #
    # It hid because handoffs key on the controller's ROLE and not on the
    # phase, so the ladder ran correctly while the phase was wrong -- and being
    # handed to Center is exactly what "he is enroute" MEANS, which is the
    # argument the arrival rule above makes for Approach.
    #
    # Safe against the inversion that comment warns of, for the same reason:
    # `enroute` aims at a point rather than "none", so `handoff.due`'s
    # phase-ownership branch never fires for it and the rules table goes on
    # deciding by role. Not from `rtb`, which Center also owns -- a man coming
    # home is not re-derived into the outbound leg.
    if worked_by == "center" and current in ("departure", ""):
        return "enroute"
    return current


def flies_geometry(phase: str) -> bool:
    """Does this phase have guidance to fly at all?

    The question `settle` should have been asking. `aims_at="none"` is a phase
    with nothing to point the geometry at -- every ground phase, and `landed`.
    """
    p = get(phase)
    return bool(p) and p.aims_at != "none" and bool(p.handler)
