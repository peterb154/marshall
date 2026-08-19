"""Where he is on HIS OWN flight plan, from radar and the legs he filed.

    "we haven't messed with the in-route routing yet much, but obviously she
     doesn't know where those waypoints are and where I'm at on my flight plan"

The engine measured one thing: range from the FIELD. The pilot navigates by
something else entirely -- his steerpoints -- and the two were never joined, so
a controller asked "what is my next steerpoint" could only answer from the
theatre file or from nothing. On 19 August, asked at Batumi after landing, it
said the first fix of the plan he had just flown.

    "I would expect that since my flight plan steerpoints have coordinates,
     the system can figure out where I am relative to my steer point and which
     leg im on"

They do, and it can. Every leg carries `lat`/`lon`, and radar carries his
position. This is the join.

HOW A FIX COUNTS AS REACHED -- the one judgement in here, and it is a hybrid
because neither half is sufficient alone:

    within RADIUS_NM        the normal case, and the one a controller can say
                            out loud: "you are inside two miles of BAR". Alone
                            it fails a fix flown wide -- he never "reaches" it,
                            and welds to that leg for the rest of the sortie
    past the perpendicular  the backstop. Once his along-track position is
                            beyond the fix he has passed it, however wide.
                            Alone it is unexplainable on the radio: "you passed
                            BAR" against nothing he can check

    "I like the hybrid approach"

STATELESS ON PURPOSE. The abeam half is a projection, not a trend, so it needs
no history and no memory of previous positions -- which means a restart, a lost
radar frame or a reconnect cannot lose his place on the route. Everything here
is a pure function of (legs, position); see docs/STATE.md on why that matters.

IT ANSWERS, IT DOES NOT DECIDE. Nothing here issues a clearance, moves a phase
or contradicts a pilot. It is a fact about geometry that the strip carries and
a controller may read out.  [#199]
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from marshall.core.geo import range_bearing_true

# HOW CLOSE COUNTS AS ARRIVING. Two miles is about eighteen seconds at 400
# knots and a minute at 120, which is the span over which a pilot would say he
# is "at" a point rather than approaching it.
#
# A NUMBER, AND ITS FAILURE MODE IS KNOWN AND COVERED. Too small and a fix
# flown wide is never reached; too large and two close fixes are reached
# together. The first is what the abeam test exists for; the second is bounded
# by legs being tens of miles apart on any plan anyone files.
REACHED_NM = 2.0

# HOW FAR OFF THE ROUTE IS "NOT ON IT". Ten miles is not an accuracy tolerance
# -- it is the line between an aeroplane flying this plan and one that has not
# started, or has left it. Inside it the nearest LEG says which leg; outside,
# only the nearest FIX means anything.
OFF_ROUTE_NM = 10.0


@dataclass(frozen=True)
class Progress:
    """Which leg he is on, and how far to the end of it."""
    leg: int                 # index of the fix he is heading TO, 0 = first
    from_fix: str            # behind him, "" before the first
    to_fix: str              # ahead of him, "" once the route is flown
    nm_to_next: float | None
    bearing_to_next: float | None
    reached: tuple[str, ...] = ()   # every fix behind him, in order

    @property
    def done(self) -> bool:
        """The whole route is behind him."""
        return not self.to_fix


def _fixes(plan: dict) -> list[tuple[str, float, float]]:
    """The legs that carry a position, in order.

    A leg with no coordinates cannot be measured against and is SKIPPED rather
    than guessed at -- but it keeps its place in the ordering, because a route
    is a sequence and renumbering it silently is how "waypoint four" comes to
    mean a different place than the chart says.
    """
    out = []
    for leg in (plan or {}).get("legs") or []:
        if not isinstance(leg, dict):
            continue
        lat, lon = leg.get("lat"), leg.get("lon")
        name = (leg.get("fix") or "").strip()
        if lat is None or lon is None or not name:
            continue
        out.append((name, float(lat), float(lon)))
    return out


def _leg_offset(pos: tuple[float, float], a: tuple[float, float, float],
                b: tuple[float, float, float]) -> tuple[float, float, float]:
    """(along-track, cross-track, leg length) in nm for the leg a -> b.

    Along-track is measured FROM `a`: negative before it, greater than the leg
    length beyond `b`.
    """
    leg_nm, leg_brg = range_bearing_true((a[1], a[2]), b[1], b[2])
    to_nm, to_brg = range_bearing_true((a[1], a[2]), pos[0], pos[1])
    d = math.radians(to_brg - leg_brg)
    return to_nm * math.cos(d), abs(to_nm * math.sin(d)), leg_nm


def _distance_to_leg(pos, a, b) -> float:
    """How far he is from the LEG, not from either end of it.

    The perpendicular where he is beside the leg, and the distance to the
    nearer end where he is off one end of it -- which is the whole point:
    a route that turns has legs pointing in every direction, and only the
    segment distance can say which one he is actually flying.
    """
    along, cross, leg_nm = _leg_offset(pos, a, b)
    if along < 0:
        return range_bearing_true((a[1], a[2]), pos[0], pos[1])[0]
    if along > leg_nm:
        return range_bearing_true((b[1], b[2]), pos[0], pos[1])[0]
    return cross


def where(plan: dict, lat: float | None, lon: float | None) -> Progress | None:
    """His position ON THE ROUTE, or None when it cannot be answered.

    None means exactly that -- no plan, no legs with coordinates, or no radar
    fix. An engine that cannot place him must say so rather than answer from
    somewhere else, which is the whole of #197.
    """
    fixes = _fixes(plan)
    if not fixes or lat is None or lon is None:
        return None
    pos = (float(lat), float(lon))

    # WHICH LEG IS HE ACTUALLY FLYING? The nearest one, by distance to the
    # SEGMENT -- not to its endpoints, and not by walking the route forward.
    #
    # TWO SIMPLER RULES WERE TRIED AND BOTH FAILED ON THE REAL PLAN, which
    # turns through nearly 180 degrees between FOO-BAR and BAR-SPAM:
    #
    #   every fix tested independently   standing ON FOO read as "past
    #                                    INITIAL, next fix BATUMI" -- the
    #                                    perpendicular through a fix four legs
    #                                    later, pointing elsewhere, was already
    #                                    behind him
    #   sequential walk, abeam by
    #   "closer to the next than
    #    to this one"                    only becomes true past the leg's
    #                                    MIDPOINT, so it lagged half a leg:
    #                                    the BAR-SPAM midpoint read as "past
    #                                    FOO, next fix BAR"
    #
    # Both were proxies for the question. The question is which leg he is on,
    # and the answer is the leg he is nearest to. [#199]
    #
    # The first version tested every fix independently and took the furthest
    # that matched. On a route that TURNS that is badly wrong: standing exactly
    # on FOO, the perpendicular through INITIAL -- four legs later and pointing
    # somewhere else entirely -- was already behind him, so the whole route
    # read as flown.
    #
    #     at FOO  ->  "past INITIAL, next fix BATUMI, 37 miles"
    #
    # An abeam test is a statement about ONE leg. It only means "he has passed
    # this fix" while he is actually on the leg that ends there, so the scan
    # has to be sequential: reached fix i only if he reached fix i-1.
    if len(fixes) == 1:
        nm, brg = range_bearing_true(pos, fixes[0][1], fixes[0][2])
        return Progress(leg=0, from_fix="", to_fix=fixes[0][0],
                        nm_to_next=nm, bearing_to_next=brg)
    best = min(range(len(fixes) - 1),
               key=lambda i: _distance_to_leg(pos, fixes[i], fixes[i + 1]))
    # ...UNLESS HE IS NOT ON THE ROUTE AT ALL. Nearest-leg assumes he is flying
    # one of them; on the ramp at Kobuleti, seventeen miles from the first fix
    # and nowhere near any leg, it picked whichever happened to be least far
    # and answered "past BAR, next fix SPAM" before he had started the engine.
    #
    # Off the route, the honest answer is the nearest FIX -- which is the first
    # one for a man about to depart, and the sensible one for a man who has
    # wandered. The corridor is wide on purpose: it is not a tolerance on
    # accuracy, it is the line between "flying this route" and "not yet".
    if _distance_to_leg(pos, fixes[best], fixes[best + 1]) > OFF_ROUTE_NM:
        near = min(range(len(fixes)),
                   key=lambda i: range_bearing_true(
                       (fixes[i][1], fixes[i][2]), *pos)[0])
        nm, brg = range_bearing_true(pos, fixes[near][1], fixes[near][2])
        return Progress(leg=near,
                        from_fix=fixes[near - 1][0] if near else "",
                        to_fix=fixes[near][0], nm_to_next=nm,
                        bearing_to_next=brg,
                        reached=tuple(x[0] for x in fixes[:near]))
    along, _cross, leg_nm = _leg_offset(pos, fixes[best], fixes[best + 1])
    # ...AND WHERE ON IT. Short of the first fix of the nearest leg he is still
    # heading TO it; past the last he has finished the route. The RADIUS is
    # what makes "at" a fix a thing a controller can say out loud -- inside it,
    # the fix is behind him and the next one is his target.
    leg = best if along < 0 else best + 1
    if leg == best and along >= -REACHED_NM and best > 0:
        leg = best            # heading to the fix that opens the nearest leg
    if along >= leg_nm - REACHED_NM and best + 2 <= len(fixes) - 1:
        leg = best + 2
    elif along >= leg_nm and best + 1 >= len(fixes) - 1:
        leg = len(fixes)
    reached = [x[0] for x in fixes[:leg]]
    if leg >= len(fixes):
        return Progress(leg=leg, from_fix=fixes[-1][0], to_fix="",
                        nm_to_next=None, bearing_to_next=None,
                        reached=tuple(reached))
    to = fixes[leg]
    nm, brg = range_bearing_true(pos, to[1], to[2])
    return Progress(leg=leg,
                    from_fix=reached[-1] if reached else "",
                    to_fix=to[0], nm_to_next=nm, bearing_to_next=brg,
                    reached=tuple(reached))


def spoken(p: Progress | None) -> str:
    """One line a controller can read out, or "" when there is nothing to say.

    Deliberately short and deliberately not a clearance. "Next is BAR, one two
    miles" is a fact he can check against his own navigation, which is what he
    asked for and what the engine could not previously answer.
    """
    if p is None:
        return ""
    if p.done:
        return f"route complete, last fix {p.from_fix}"
    if p.nm_to_next is None:
        return f"next fix {p.to_fix}"
    lead = f"past {p.from_fix}, " if p.from_fix else ""
    return (f"{lead}next fix {p.to_fix}, {p.nm_to_next:.0f} miles "
            f"on {p.bearing_to_next:03.0f}")
