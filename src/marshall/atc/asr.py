"""Surveillance-radar approach: the controller does the navigating.

An ASR is the answer to two problems the beacon letdown could not solve.

**Crosswind.** Homing a beacon points the nose AT it, so holding a straight
ground track means crabbing -- and the moment you crab, the homing needle is no
longer the course. The pilot has to choose between tracking and knowing where he
is. Under radar he does neither: he flies the heading he is given, the controller
watches the *ground track* drift and adjusts the heading, and the crab is simply
absorbed. Nobody in the aeroplane has to know the wind.

**Aircraft.** The AN/ARA-8 homing adapter exists on the P-51D-30 and nothing
else, so the beacon approach was locked to one airframe. An ASR needs no
equipment at all beyond a radio, which makes the approach a property of the
FIELD rather than of the aeroplane -- a Spitfire, a 109 or a Jug can all fly it.

The geometry here is deterministic and belongs in this half of the system: where
he is, how far off course, what heading regains it, when to descend, where the
missed approach point is. The agent voices it and decides how hard to insist; it
never computes it. Same invariant as separation -- an LLM does not do the
trigonometry that puts an aeroplane on a runway.

Everything is driven from the radar picture we already produce (range and radial
off the field), so this adds no new source of truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Course-keeping. A proportional correction: the further off the centreline, the
# larger the intercept angle, capped so the controller never turns a man onto a
# heading that loses the field. 12 degrees per mile puts a half-mile error at a
# gentle six and a two-mile error at the cap.
DEG_PER_NM = 12.0
MAX_INTERCEPT = 30
ON_COURSE_NM = 0.3          # inside this he is simply "on course"

# Wind is absorbed by watching the ground track rather than by computing it, so
# corrections are re-issued as he drifts. This is how a real ASR works: the
# controller does not know the wind either, he just keeps him on the line.


# How far outside the turn-on range the join point sits. He has to roll out on
# the centreline with room left to settle before the descent, so the vector aims
# at a point beyond the turn-on, not at the turn-on itself.
JOIN_MARGIN_NM = 4.0


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
    deviation: str              # "on course" | "left of course" | "right of course"
    turn: str = ""              # "left" | "right", the short way round

    @property
    def off_course(self) -> bool:
        return self.deviation != "on course"

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


def intercept_heading(final_crs: float, xtk_nm: float) -> int:
    """Heading that closes the centreline without overshooting it."""
    correction = max(-MAX_INTERCEPT, min(MAX_INTERCEPT, -DEG_PER_NM * xtk_nm))
    return round((final_crs + correction) % 360)


def guide(pos: Position, profile) -> Guidance:
    """One radar look -> the next instruction.

    Two regimes, and confusing them is what makes a vectored approach useless:

    **Established** -- on the final approach course, inside the turn-on range.
    Now the job is course-KEEPING, so the heading is the course plus a small
    correction, and he descends.

    **Not established** -- anywhere else, at any bearing. The job is to take him
    to the extended centreline, so the heading is the bearing to a JOIN POINT
    out along it, which for an aircraft north of a north-west-facing approach
    means turning him away from the field before turning him back in.

    An earlier version treated "more than ninety degrees off the inbound radial"
    as having flown PAST the field, which is not what it means at all -- a man
    sitting due north of the field is ninety-odd degrees off the inbound radial
    and has passed nothing. It flew a pilot straight at the field from the north
    and then told him he had overshot. Bearing is not progress.
    """
    xtk = cross_track(pos, profile.final_crs)
    deviation = ("on course" if abs(xtk) <= ON_COURSE_NM
                 else "right of course" if xtk > 0 else "left of course")
    inbound_radial = (profile.final_crs + 180) % 360
    off_radial = abs(angle_diff(pos.radial_deg, inbound_radial))

    if pos.range_nm <= profile.map_nm:
        h = intercept_heading(profile.final_crs, xtk)
        return Guidance("map", h, profile.mda_ft, pos.range_nm, xtk, deviation,
                        turn_direction(pos.heading_deg, h))

    # On the centreline and on the inbound side: keep the course. Note this does
    # NOT require him to be inside the turn-on range -- that range is where he
    # should be established BY, not a condition of being established. Treating
    # it as one sent a man already tracking the centreline at ten miles back
    # OUTBOUND to a join point at twelve, a 180 for no reason.
    on_centreline = off_radial <= 30 and abs(xtk) <= profile.final_intercept_nm / 4
    if on_centreline:
        h = intercept_heading(profile.final_crs, xtk)
        # He only comes down once he is inside the turn-on range.
        inside = pos.range_nm <= profile.final_intercept_nm
        return Guidance("final" if inside else "vector", h,
                        profile.mda_ft if inside else profile.platform_ft,
                        pos.range_nm, xtk, deviation,
                        turn_direction(pos.heading_deg, h))

    # Off the centreline: fly him to the join point out along it.
    join_nm = profile.final_intercept_nm + JOIN_MARGIN_NM
    h = round(bearing_between(pos.range_nm, pos.radial_deg,
                              join_nm, inbound_radial)) % 360
    return Guidance("vector", h, profile.platform_ft, pos.range_nm, xtk,
                    deviation, turn_direction(pos.heading_deg, h))


def spoken_range(nm: float) -> str:
    """Range calls are whole miles on final -- 'six miles from the runway'."""
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "one zero"]
    n = int(round(nm))
    return words[n] if n < len(words) else str(n)
