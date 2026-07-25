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
INTERCEPT_ANGLE = 30.0


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


# Nominal descent gradient for the advisory altitudes, in feet per mile. Three
# degrees is the standard approach slope; 318 ft/nm is its gradient.
FT_PER_NM = 318.0


def advisory_altitude(range_nm: float, profile) -> int:
    """The height he SHOULD be at, this far out.

    An ASR has no glidepath, so this is advice rather than guidance -- but
    "descend and maintain three hundred" at eight miles is a seventeen-hundred
    foot drop given as one instruction, and a pilot flying it arrives low and
    level miles out. Real controllers read a recommended altitude with each mile
    call. Never below minimums, and never above the altitude he was vectored at.
    """
    want = profile.field_elev_ft + round(range_nm * FT_PER_NM)
    return max(profile.mda_ft, min(profile.platform_ft, int(round(want / 100) * 100)))


def guide(pos: Position, profile) -> Guidance:
    """One radar look -> the next instruction.

    Four states, and the whole difficulty is telling them apart:

    **final**    -- on the course, pointing down it: keep the course, descend.
    **vector**   -- off it with room to converge: cut across at INTERCEPT_ANGLE.
    **downwind** -- off it WITHOUT room: parallel the course outbound until
                    there is some.
    **map**      -- over the missed approach point.

    Two things this has been got wrong on real sorties, both worth keeping in
    view. Treating "more than ninety degrees off the inbound radial" as having
    flown PAST the field: a man due north of a field is ninety-odd degrees off
    the inbound radial and has passed nothing, and that reading flew a pilot
    straight at the field and then told him he had overshot. And vectoring at a
    fixed JOIN POINT: the bearing to a point swings harder the closer you get
    and reverses once you pass it, so the pilot S-turned across the centreline
    and was turned back through it again. A controller converges at an angle; he
    does not chase a spot on the map.
    """
    xtk = cross_track(pos, profile.final_crs)
    tol = on_course_tolerance(pos.range_nm)
    deviation = ("on course" if abs(xtk) <= tol
                 else "right of course" if xtk > 0 else "left of course")
    inbound_radial = (profile.final_crs + 180) % 360
    off_radial = abs(angle_diff(pos.radial_deg, inbound_radial))

    if pos.range_nm <= profile.map_nm:
        h = intercept_heading(profile.final_crs, xtk)
        return Guidance("map", h, profile.mda_ft, pos.range_nm, xtk, deviation,
                        turn_direction(pos.heading_deg, h))

    # Established: on the centreline AND pointing down it. The heading check is
    # not pedantry -- a go-around tracking OUTBOUND sits on the centreline with a
    # small cross-track and was called established, then told to descend to
    # minimums while flying away from the field.
    tracking_in = abs(angle_diff(pos.heading_deg, profile.final_crs)) <= 45
    on_centreline = off_radial <= 30 and abs(xtk) <= profile.final_intercept_nm / 4
    if on_centreline and tracking_in:
        h = intercept_heading(profile.final_crs, xtk)
        inside = pos.range_nm <= profile.final_intercept_nm
        alt = (advisory_altitude(pos.range_nm, profile) if inside
               else profile.platform_ft)
        return Guidance("final" if inside else "vector", h, alt,
                        pos.range_nm, xtk, deviation,
                        turn_direction(pos.heading_deg, h))

    # Otherwise vector him onto the course. NOT by flying at a point on it: that
    # is pure pursuit, and the bearing to a fixed point swings harder the closer
    # you get and reverses once you pass it -- which is exactly the S-turning a
    # real flight produced, crossing the centreline and being turned back
    # through it again.
    #
    # A controller converges on the extended centreline at a fixed angle and
    # rolls out. The only real decision is whether there is ROOM left to do it:
    # closing 6 miles of cross-track at 30 degrees needs about 11 miles of
    # centreline, and if he does not have that he must be taken downwind to make
    # some. Trying anyway is what produced an impossible intercept and then a
    # sequence of contradictory turns.
    # Already on the centreline but pointing across it -- a turn onto the course
    # is the whole instruction. Sending him downwind here would take a man who
    # is a mile off the line and fly him away from it.
    if on_centreline:
        h = round(profile.final_crs)
        return Guidance("vector", h, profile.platform_ft, pos.range_nm, xtk,
                        deviation, turn_direction(pos.heading_deg, h))

    ahead = along_track(pos, profile.final_crs) - profile.final_intercept_nm
    needed = abs(xtk) / math.tan(math.radians(INTERCEPT_ANGLE))
    if ahead < needed:
        # No room: parallel the course outbound, on his side, until there is.
        h = round(inbound_radial)
        return Guidance("downwind", h, profile.platform_ft, pos.range_nm, xtk,
                        deviation, turn_direction(pos.heading_deg, h))

    # Room to converge: cut across at the intercept angle, from his side.
    cut = INTERCEPT_ANGLE if xtk > 0 else -INTERCEPT_ANGLE
    h = round((profile.final_crs - cut) % 360)
    return Guidance("vector", h, profile.platform_ft, pos.range_nm, xtk,
                    deviation, turn_direction(pos.heading_deg, h))


def spoken_range(nm: float) -> str:
    """Range calls are whole miles on final -- 'six miles from the runway'."""
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "one zero"]
    n = int(round(nm))
    return words[n] if n < len(words) else str(n)
