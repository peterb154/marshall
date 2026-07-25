"""The geometry. One engine, and it does not know what phase it is serving.

Everything that has worked in this project is here, and that is not a
coincidence: the parts owned by geometry have been right, and the parts owned
by per-component state have produced every bug worth remembering. So this
module answers exactly one question, for anybody who asks it --

    given where he is and where he should be going:
    what heading, what altitude, what speed?

-- and that question is the same one whether he is on a final approach course,
tracking an airway, running in to a target, flying a departure leg or holding.
A departure engine and an approach engine would be two copies of cross-track,
intercept angle, turn lead and wind absorption, and they would drift apart. We
know they would, because the beacon procedure's words leaked into the radar
procedure four separate times in one evening and reached a pilot's ears.

What varies by phase is WHERE HE SHOULD BE GOING, and that is the caller's
business, not this module's.

Wind never appears here. Under radar the controller watches the ground track
and adjusts the heading, so the drift is absorbed by the loop rather than
computed -- which is how a real surveillance approach works, and why nobody in
the aeroplane has to know the wind exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# One rule for closing the centreline, at every distance: steer at a point on
# the course a fixed distance ahead, and let the geometry set the angle. Being
# a mile off with two miles to run is a big correction; being a mile off with
# twenty to run is a small one. That is pure pursuit, and it is used here for a
# specific property -- the offset decays exponentially with a length scale of
# the lookahead, so the last tenth of a mile closes as briskly as the first.
#
# The predecessor was proportional to the offset alone, and its tail was the
# problem: fifteen degrees per mile means a half-mile error is corrected at
# seven degrees, which needs four miles of run to fix. In simulation an
# aircraft turned in at fifteen miles was not established until six -- at the
# final approach point, where he should already have been stable and starting
# down. Nothing in it was wrong at any single radar look, which is exactly why
# it survived so long.
#
# The lookahead shrinks as he closes, because a quarter-mile off at eighteen
# miles is nothing and a quarter-mile off at one is a go-around. It is floored
# at the standard-rate turn radius: aiming closer than the aircraft can turn is
# how a pursuit law starts to hunt.
LOOKAHEAD_NM = 2.0
LOOKAHEAD_MIN_NM = 1.0
# The old proportional gain, kept because the outbound-leg tests and the
# spoken-correction sizing are calibrated against it.
DEG_PER_NM = 15.0
MAX_INTERCEPT = 90
# "On course" is an ANGLE, not a distance. A fixed 0.3 nm looks reasonable at
# six miles and is nonsense at one: a pilot a quarter-mile south of the runway on
# short final was being told he was lined up, because a quarter mile still fitted
# inside the tolerance. Judged as an angle off the centreline it tightens on its
# own -- about 950 ft at six miles, about 160 ft at one.
ON_COURSE_DEG = 1.5
ON_COURSE_FLOOR_NM = 0.02   # radar noise; below this nobody can fly the difference


def on_course_tolerance(range_nm: float) -> float:
    """How far off the centreline still counts as on course, at this range."""
    return max(ON_COURSE_FLOOR_NM,
               range_nm * math.tan(math.radians(ON_COURSE_DEG)))

# Wind is absorbed by watching the ground track rather than by computing it, so
# corrections are re-issued as he drifts. This is how a real ASR works: the
# controller does not know the wind either, he just keeps him on the line.


# The angle at which a vector cuts across to the final approach course. Thirty
# degrees is the usual figure: shallow enough to roll out cleanly, steep enough
# not to spend ten miles converging. It also sets how much centreline an
# intercept COSTS -- xtk / tan(30) -- which is what decides whether he can be
# turned in at all or has to go downwind first.
# The procedure, as a controller flies it. Positioning happens OUTSIDE the
# initial approach fix, so that by the IAF he is established, on course and at
# the IAF altitude -- the fix is a gate, not a target to be chased.
#
#   outbound   too close in, or badly placed: gain room along the centreline
#   base       perpendicular to the course, closing on it
#   intercept  45 degrees, turned when TURN_IN_NM from the centreline
#   final      established; course keeping, descent, mile calls
#
# 45 rather than 30: a standard-rate turn takes 15 seconds through 45 degrees
# and the roll-out has to be gentle enough to blend on rather than snap on.
INTERCEPT_ANGLE = 45.0

# How far off the centreline to turn off base onto the intercept. At 240 mph the
# standard-rate radius is 1.11 nm, and the two turns -- base to 45, then 45 to
# the course -- eat 0.78 and 0.32 nm of lateral distance between them. Turning in
# at one mile therefore overshoots; two gives room to roll out on the course
# instead of through it.
TURN_IN_NM = 2.0


def angle_diff(a: float, b: float) -> float:
    """Signed smallest angle from b to a, in (-180, 180]."""
    return (a - b + 180) % 360 - 180


def _en(nm: float, bearing_deg: float) -> tuple[float, float]:
    """Polar (range, bearing from the field) -> (east, north) in miles."""
    r = math.radians(bearing_deg)
    return nm * math.sin(r), nm * math.cos(r)


def bearing_between(from_nm: float, from_radial: float,
                    to_nm: float, to_radial: float) -> float:
    """Bearing to fly from one point to another, both given off the field."""
    fe, fn = _en(from_nm, from_radial)
    te, tn = _en(to_nm, to_radial)
    return math.degrees(math.atan2(te - fe, tn - fn)) % 360


def turn_direction(from_heading: float, to_heading: float) -> str:
    """Which way round. 'left' or 'right', always the short way.

    Worth computing rather than leaving to the model: a controller who turns a
    man the long way round is not merely inelegant, he adds a minute of flying
    and takes him further from the field. It was noticed in the air the first
    time it happened.
    """
    delta = angle_diff(to_heading, from_heading)
    if abs(delta) < 5:
        return ""               # already pointing there; "turn" would be noise
    return "left" if delta < 0 else "right"


@dataclass
class Position:
    """Where radar says he is, relative to the field."""
    range_nm: float
    radial_deg: float           # bearing FROM the field TO the aircraft
    alt_ft: int
    heading_deg: float = 0.0


@dataclass
class Guidance:
    """What the controller should do about it. Pure geometry, no phrasing."""
    phase: str                  # "vector" | "final" | "map"
    heading: int                # the heading to assign
    altitude_ft: int | None     # the altitude to assign, or None to leave him
    range_nm: float             # range to the field, for the range call
    xtk_nm: float               # cross-track: +right of course, -left of course
    deviation: str              # "on course" | "left/right of course" | "" when
                                # the course is not what he is flying
    turn: str = ""              # "left" | "right", the short way round
    speed_kt: float = 0.0       # the speed this leg should be flown at

    @property
    def off_course(self) -> bool:
        """Off the final approach course -- and only meaningful if he is ON it.

        An empty deviation means the question does not apply: he is being
        repositioned, or flying the missed approach, and "you are left of
        course" describes a course he is not trying to fly. It was said to an
        aircraft outbound on its missed approach, which had just been told to
        fly 330 and was doing exactly that.
        """
        return bool(self.deviation) and self.deviation != "on course"

    @property
    def established(self) -> bool:
        """On the final approach course and being talked down, not vectored."""
        return self.phase in ("final", "map")


def cross_track(pos: Position, final_crs: float) -> float:
    """Signed distance off the final approach course, in nautical miles.

    Positive means RIGHT of course as the pilot flies it inbound. Derived from
    the range/radial radar already reports rather than from a second coordinate
    system, so there is nothing here to disagree with the scope.
    """
    # Established inbound on `final_crs`, he sits on the reciprocal radial.
    inbound_radial = (final_crs + 180) % 360
    off = angle_diff(pos.radial_deg, inbound_radial)
    # A positive (clockwise) offset from the inbound radial puts him LEFT of the
    # course he is flying, hence the negation.
    return -pos.range_nm * math.sin(math.radians(off))


def lookahead_nm(along_nm: float) -> float:
    """How far down the course to aim, from where he is now."""
    return min(LOOKAHEAD_NM, max(LOOKAHEAD_MIN_NM, along_nm / 2.0))


def intercept_heading(final_crs: float, xtk_nm: float,
                      along_nm: float | None = None) -> int:
    """Heading that closes the centreline without overshooting it.

    Aim at a point `lookahead` miles further down the course than he is; the
    angle to it IS the correction. Callers that have no along-track distance to
    hand get the full lookahead, which is the right answer everywhere except
    short final.
    """
    look = lookahead_nm(along_nm if along_nm is not None else LOOKAHEAD_NM * 2)
    correction = math.degrees(math.atan2(-xtk_nm, look))
    correction = max(-MAX_INTERCEPT, min(MAX_INTERCEPT, correction))
    return round((final_crs + correction) % 360)


def along_track(pos: Position, final_crs: float) -> float:
    """How far he still has to run along the course, in miles.

    Positive means the field is ahead of him down the centreline; negative means
    he is past it. Measured along the course rather than as slant range, because
    the question that matters for an intercept is how much RUNWAY of centreline
    is left, not how far away the field is.
    """
    inbound_radial = (final_crs + 180) % 360
    ae, an = _en(pos.range_nm, pos.radial_deg)
    ie, i_n = _en(1.0, inbound_radial)      # unit vector out along the centreline
    return ae * ie + an * i_n


