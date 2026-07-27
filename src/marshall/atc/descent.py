"""When to start down, and to what. The vertical half of an approach.

    "ATC still taking me down to 2000 well before the initial fix. It should
     time my altitude so I arrive at the IF at 2000 from wherever I was... take
     current alt, ground speed and distance from IF to calculate a 500 fpm
     descent and start down point."

    "That's probably another engine — altitude planning."

It is, and separating it is the point. `asr.py` answers WHERE he should be
pointing; this answers WHEN he should start down. They share nothing but a
Position, and every attempt to do the vertical planning inside the lateral
engine produced a fixed feet-per-mile gradient, which is only correct at one
groundspeed and is wrong for every aeroplane that is not doing exactly that.

**A rate is not a gradient.** 500 fpm is a comfortable descent in anything;
what it costs in MILES depends entirely on how fast he is going. A Mustang at
150 knots loses 500 ft in 2.5 miles. An F-16 at 300 knots needs 5. Assigning
the same feet-per-mile to both puts one of them into a dive and leaves the other
level until the last minute, which is what "taking me down well before the fix"
was: a gradient chosen for somebody else.

**Descend LATE, not early.** Given the choice, an aeroplane should stay high:
high is quiet, efficient, and leaves options. The whole job here is to compute
the last responsible moment and not a foot before it — which is the opposite of
what a fixed gradient does, since a gradient starts down the instant he is above
it.

Nothing here knows about terrain. The floor is the caller's business, because
the lowest safe altitude is a fact about the ground and this is a fact about the
aeroplane. See `asr.safe_alt`, which takes the max of the two.
"""

from __future__ import annotations

from dataclasses import dataclass

# What a transport-category descent feels like, and what a pilot asked for. Fast
# enough not to drone, gentle enough to hold a conversation and change a
# frequency in.
RATE_FPM = 500.0

# Start this far before the last responsible moment. Not padding for its own
# sake: a controller says "descend to two thousand", the pilot acknowledges,
# reaches for the throttle and trims -- and a quarter of a mile has gone by. It
# also means the arrival at the fix is level rather than still coming down,
# which is what "be there on time" means.
LEAD_NM = 0.5

# When the sim has not told us how fast he is going. Slow enough to be
# conservative: guessing LOW starts him down EARLY, which wastes fuel, and
# guessing high starts him late, which is the one that does not work.
ASSUMED_KT = 150.0


@dataclass
class Descent:
    """What to do about his altitude, and why."""
    assign_ft: int          # the altitude to give him NOW
    start_nm: float         # distance-to-go at which the descent must begin
    needed_nm: float        # miles the descent itself takes
    descending: bool        # is he past the top of descent?
    rate_fpm: float         # the rate the plan assumes


def miles_to_lose(feet: float, groundspeed_kt: float,
                  rate_fpm: float = RATE_FPM) -> float:
    """How much ground a descent of `feet` covers at this speed and rate.

    The whole calculation, and the reason it cannot be a constant:

        minutes = feet / rate
        miles   = minutes * groundspeed / 60
    """
    if feet <= 0:
        return 0.0
    gs = groundspeed_kt if groundspeed_kt and groundspeed_kt > 20 else ASSUMED_KT
    return (feet / max(1.0, rate_fpm)) * gs / 60.0


def plan(alt_ft: float, target_ft: float, to_go_nm: float,
         groundspeed_kt: float = 0.0, rate_fpm: float = RATE_FPM,
         lead_nm: float = LEAD_NM) -> Descent:
    """Keep him high until the last responsible moment, then start him down.

    `to_go_nm` is the distance to the point he must be AT `target_ft` by --
    for an approach, the initial fix, not the runway.
    """
    to_lose = max(0.0, alt_ft - target_ft)
    needed = miles_to_lose(to_lose, groundspeed_kt, rate_fpm)
    start = needed + lead_nm

    if to_lose <= 0:
        # At or below it already. Nothing to plan, and telling him to climb back
        # onto a descent profile would be absurd.
        return Descent(int(round(alt_ft)), start, needed, False, rate_fpm)

    if to_go_nm <= start:
        # Past the top of descent: give him the target and let him fly it.
        return Descent(int(target_ft), start, needed, True, rate_fpm)

    # Still high and still early. Leave him where he is.
    return Descent(int(round(alt_ft)), start, needed, False, rate_fpm)


def top_of_descent_nm(alt_ft: float, target_ft: float,
                      groundspeed_kt: float = 0.0,
                      rate_fpm: float = RATE_FPM,
                      lead_nm: float = LEAD_NM) -> float:
    """Distance-to-go at which he has to start down. For the plate and for
    anybody who wants to say "expect descent in ten miles"."""
    return miles_to_lose(max(0.0, alt_ft - target_ft),
                         groundspeed_kt, rate_fpm) + lead_nm
