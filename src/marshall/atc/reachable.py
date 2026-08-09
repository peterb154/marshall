"""Which pilot actions exist in THIS procedure, at this point in the sortie.

    "why would one of the brains (the one doing the wrong thing) be invoked at
     all when that phase of flight isn't happening. I feel like there is a
     fundamental flaw in the state machinery"

THERE WAS, AND THIS IS IT. The router was a flat `match intent.kind` -- a label
from a classifier, straight to a controller method, with nothing in between. The
engine's state was consulted only INSIDE the method, after it had already been
chosen and was committed to answering.

WHAT THAT COST, live on 9 August. A pilot on a RADAR approach read back a
heading twelve times:

    "Left one four zero, two thousand five hundred, sockeye"

The classifier's own instruction for `report_beacon` reads "ANY position,
altitude or progress report ... if he is telling you where he is or what he is
doing, it is this one", so a heading-and-altitude read-back matched it. The
method means "reported over the approach beacon", saw him cleared, started the
station-passage clock, and said:

    "roger, station passage two plus three two, report field in sight or
     missed approach"

Twelve times, on a procedure that HAS NO BEACON, to a pilot with no receiver for
one. Nothing asked whether the action was possible, because nothing could.

THE RULE, and it is one rule rather than a table of special cases:

    an action is reachable when the procedure contains it
    and the aeroplane is somewhere it could be performed

A beacon report is station passage. That exists on a letdown the PILOT
navigates. On a vectored procedure the controller has him on radar and reads him
his ranges -- there is no station to pass, and his altitude is on the scope
already, continuously and correctly, which is the second half of the same
finding: the deterministic engine should be driven by FACTS, not by sentences.
Radar gives it facts. A classifier gives it a guess about words.

WHY THE TALKDOWN HAS ALWAYS WORKED is the same rule read forwards. It is pure
geometry on a four-second clock and it never asks what anybody said, so it
cannot be told the wrong thing by a mis-heard sentence. This module is an
attempt to give the rest of the engine that same property.

**Unreachable is not an error.** It means the engine has nothing to do with this
transmission -- which is the ordinary case for a read-back, and the agent
answers it perfectly well with "roger". Saying "say again" would be worse than
the bug.
"""

from __future__ import annotations

from marshall.atc.intents import IntentKind as K

# THINGS A PILOT CAN ONLY DO IN THE AIR. Asked on the ramp they are noise, and
# the noise is not hypothetical: a jet parked at 65 ft and 0 knots reads to the
# approach geometry as an aircraft through the missed approach point.
AIRBORNE_ONLY = frozenset({
    K.REPORT_BEACON, K.REPORT_MISSED, K.REQUEST_APPROACH, K.REQUEST_VISUAL,
})

# ...AND THINGS HE CAN ONLY DO ON THE GROUND. These four move `sortie_phase`
# and nothing else, so firing one airborne would hand him to a ground
# controller in the middle of an approach.
GROUND_ONLY = frozenset({
    K.REQUEST_CLEARANCE, K.REQUEST_TAXI, K.REPORT_HOLDING_SHORT,
    K.REQUEST_TAKEOFF,
})


def has_station_passage(profile) -> bool:
    """Does this procedure have a station for the pilot to report passing?

    Two ways to be yes, and the second is the one that matters:

      * it is a beacon letdown, where station passage IS the procedure; or
      * the controller has NO RADAR, so a position report is the only way he
        finds out where anybody is. A blind controller needs to be told; a
        radar controller is already looking at it.

    So this is not "is it an NDB approach" dressed up. A radar-equipped
    controller working a beacon letdown still wants the report, because the
    pilot is flying the procedure off his own clock and the controller is
    backing him up -- and a non-radar controller working anything at all cannot
    do without it.
    """
    if (getattr(profile, "kind", "") or "").lower() == "ndb":
        return True
    atc = getattr(profile, "atc", None)
    return not getattr(atc, "radar", True)


def reachable(kind, profile, *, on_ground: bool | None = None) -> bool:
    """May this action be dispatched right now?

    `on_ground` is None when nothing knows -- no radar contact, no sim event --
    and None never blocks. A guard that fires on missing information is a guard
    that silences a controller the first time the scope drops, which is the one
    moment a pilot most needs him.
    """
    if kind is K.UNKNOWN:
        return False
    if on_ground is True and kind in AIRBORNE_ONLY:
        return False
    if on_ground is False and kind in GROUND_ONLY:
        return False
    # Written as a chain of refusals rather than one boolean, because each
    # line is a separate rule with its own reason and `why_not` has to be able
    # to say which one fired.
    return not (kind is K.REPORT_BEACON and not has_station_passage(profile))


def why_not(kind, profile, *, on_ground: bool | None = None) -> str:
    """A line for the log. Silence about a suppression is how the last one
    survived twelve repetitions in a single sortie."""
    if reachable(kind, profile, on_ground=on_ground):
        return ""
    if kind is K.UNKNOWN:
        return ""
    if on_ground is True and kind in AIRBORNE_ONLY:
        return f"{kind.value} is not something he can do on the ground"
    if on_ground is False and kind in GROUND_ONLY:
        return f"{kind.value} is not something he can do airborne"
    if kind is K.REPORT_BEACON:
        return (f"{kind.value} has no meaning on a "
                f"{getattr(profile, 'kind', '?')} approach with radar — "
                f"there is no station to pass and the scope has his position")
    return f"{kind.value} is not reachable here"
