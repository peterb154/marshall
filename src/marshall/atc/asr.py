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


def angle_diff(a: float, b: float) -> float:
    """Signed smallest angle from b to a, in (-180, 180]."""
    return (a - b + 180) % 360 - 180


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
    phase: str                  # "vector" | "final" | "map" | "beyond"
    heading: int                # the heading to assign
    altitude_ft: int | None     # the altitude to assign, or None to leave him
    range_nm: float             # range to the field, for the range call
    xtk_nm: float               # cross-track: +right of course, -left of course
    deviation: str              # "on course" | "left of course" | "right of course"

    @property
    def off_course(self) -> bool:
        return self.deviation != "on course"


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

    `profile` is a route.ApproachProfile: final_crs, mda_ft, platform_ft and the
    field elevation come from the same object the chart and the mission read, so
    a vectored approach cannot brief different numbers from a flown one.
    """
    xtk = cross_track(pos, profile.final_crs)
    if abs(xtk) <= ON_COURSE_NM:
        deviation = "on course"
    else:
        deviation = "right of course" if xtk > 0 else "left of course"

    heading = intercept_heading(profile.final_crs, xtk)
    inbound = angle_diff(pos.radial_deg, (profile.final_crs + 180) % 360)

    # Past the field, or so far off the inbound sector that he is not on this
    # approach at all -- the controller has to re-position him, not correct him.
    if pos.range_nm <= profile.map_nm:
        return Guidance("map", heading, profile.mda_ft, pos.range_nm, xtk, deviation)
    if abs(inbound) > 90:
        return Guidance("beyond", heading, None, pos.range_nm, xtk, deviation)

    # Inside the intercept range and roughly lined up: this is the final, and he
    # comes down to minimums. Outside it he is being vectored at platform.
    on_final = (pos.range_nm <= profile.final_intercept_nm
                and abs(inbound) <= 30)
    if on_final:
        return Guidance("final", heading, profile.mda_ft, pos.range_nm, xtk,
                        deviation)
    return Guidance("vector", heading, profile.platform_ft, pos.range_nm, xtk,
                    deviation)


def spoken_range(nm: float) -> str:
    """Range calls are whole miles on final -- 'six miles from the runway'."""
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "one zero"]
    n = int(round(nm))
    return words[n] if n < len(words) else str(n)
