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

# One rule for closing the centreline, at every distance: turn toward it by an
# angle proportional to how far off it you are, capped at ninety degrees --
# straight at it. Fifteen degrees per mile puts a half-mile error at a gentle
# eight, two miles at thirty, and six miles or more at the cap.
#
# The cap matters more than the gain. It used to be thirty degrees, which cannot
# close a large offset at all, so a separate "no room to intercept" case flew the
# aircraft PARALLEL to the course to buy distance -- and parallel never reduces
# an offset. A pilot seventeen miles off the centreline was sent north-west at a
# constant seventeen miles off, out to sea, until he abandoned the approach.
# There is no case where turning away from the centreline is the answer; there is
# only turning toward it harder.
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

    Two segments, per the plate, and the level one matters. From the IF to the
    FAP he stays at 2,000: that is the intermediate segment, and it is what
    makes the approach flyable -- a single gradient from the gate has him
    descending the entire way in, arriving low and level miles out. Only at the
    FAP does the three-degree path begin.

    Checked against the AIP's own table (1,355 / 708 / 387 ft at 4 / 2 / 1 nm);
    this lands within about fifty feet the whole way down.
    """
    fap = getattr(profile, "fap_nm", 0) or profile.final_intercept_nm
    if range_nm >= fap:
        return profile.platform_ft                    # level intermediate
    thr = getattr(profile, "field_thr_elev_ft", 0) or profile.field_elev_ft
    want = thr + round(range_nm * FT_PER_NM)
    return max(profile.mda_ft, min(profile.platform_ft,
                                   int(round(want / 100) * 100)))


def _round_to(ft: float, step: int) -> int:
    return int(round(ft / step) * step)


def safe_alt(pos: Position, profile) -> int:
    """What to assign him while he is being vectored.

    Three things bound it, and the lowest legal answer is rarely the right one:

    **Terrain.** Platform is only safe over low ground. At Batumi that is the
    sea to the north-west; the other three quadrants hold between seven and
    eleven thousand feet of Caucasus, and geometry alone will cheerfully turn an
    aircraft over a mountain at two thousand.

    **The profile.** He should reach platform AS he reaches the turn-on point,
    not twelve miles before it. Sending him to platform the moment he checks in
    has him droning along low and slow for ten minutes -- "no sense descending
    so early", and quite right.

    **Where he already is.** If he is below the profile there is no point
    telling him to climb back onto it; keep him where he is if that is safe.
    """
    msa = (profile.min_safe_ft(pos.radial_deg)
           if hasattr(profile, "min_safe_ft") else profile.platform_ft)
    to_go = max(0.0, pos.range_nm - profile.final_intercept_nm)
    # Rounded to five hundred: a controller assigns "four thousand five
    # hundred", never "four thousand five hundred and forty-four".
    on_profile = _round_to(profile.platform_ft + to_go * FT_PER_NM, 500)
    here = _round_to(pos.alt_ft, 500) if pos.alt_ft else 0
    return max(msa, min(on_profile, here) if here else on_profile)


def iaf_nm(profile) -> float:
    """How far out the initial approach fix sits, along the centreline."""
    iaf = getattr(profile, "iaf", None)
    if iaf is None:
        return profile.final_intercept_nm + 4.0
    import math as _m
    dx, dz = iaf.x - profile.beacon.x, iaf.z - profile.beacon.z
    return _m.hypot(dx, dz) / 1852.0


def guide(pos: Position, profile) -> Guidance:
    """One radar look -> the next instruction.

    The procedure a controller actually flies, and the reason it is staged this
    way rather than computed as one heading: every leg has a different JOB.

      final      established on the course -- keep it, and come down
      intercept  45 degrees onto the course, turned TURN_IN_NM off it
      base       perpendicular, closing the centreline
      outbound   not enough centreline left to work with; go and get some

    All of the positioning happens OUTSIDE the initial approach fix, so that by
    the IAF he is established, on course and at the IAF altitude. The fix is a
    gate he passes through, not a point to be chased -- three sorties were lost
    to vectoring that aimed at an invented point which moved, and variously
    turned him away from the field, orbited, and flew him out to sea.
    """
    xtk = cross_track(pos, profile.final_crs)
    tol = on_course_tolerance(pos.range_nm)
    deviation = ("on course" if abs(xtk) <= tol
                 else "right of course" if xtk > 0 else "left of course")
    inbound_radial = (profile.final_crs + 180) % 360
    outbound = inbound_radial
    along = along_track(pos, profile.final_crs)
    gate = iaf_nm(profile)

    def out(phase, heading, alt):
        h = round(heading) % 360
        return Guidance(phase, h, alt, pos.range_nm, xtk, deviation,
                        turn_direction(pos.heading_deg, h))

    if pos.range_nm <= profile.map_nm:
        return out("map", intercept_heading(profile.final_crs, xtk),
                   profile.mda_ft)

    # Established: on the course AND pointing down it. The heading check is not
    # pedantry -- a go-around tracking outbound sits on the centreline with a
    # small cross-track, and was called established and told to descend to
    # minimums while flying away from the field.
    tracking_in = abs(angle_diff(pos.heading_deg, profile.final_crs)) <= 45
    if abs(xtk) <= max(tol, TURN_IN_NM / 4) and tracking_in:
        inside = pos.range_nm <= profile.final_intercept_nm
        alt = (advisory_altitude(pos.range_nm, profile) if inside
               else safe_alt(pos, profile))
        return out("final" if inside else "vector",
                   intercept_heading(profile.final_crs, xtk), alt)

    # Inside the gate but not established: there is no approach left to fly from
    # here, so route him to the initial approach fix and start again from there.
    # DIRECT TO THE FIX, not on a computed reciprocal: "fly outbound, angled
    # toward the centreline" is a heuristic, and from due east it points
    # straight across the airfield -- the simulation flew a man over the runway
    # and called it a missed approach. A real fix fifteen miles out is a real
    # place to send him, and the track to it clears the field on its own.
    if along < gate:
        return out("to the fix",
                   bearing_between(pos.range_nm, pos.radial_deg,
                                   gate, inbound_radial),
                   safe_alt(pos, profile))

    # Outside the gate: close the centreline square, then turn 45 onto it.
    if abs(xtk) > TURN_IN_NM:
        return out("base", profile.final_crs - 90 * (1 if xtk > 0 else -1),
                   safe_alt(pos, profile))
    return out("intercept",
               profile.final_crs - INTERCEPT_ANGLE * (1 if xtk > 0 else -1),
               profile.iaf_alt_ft if getattr(profile, "iaf_alt_ft", 0)
               else profile.platform_ft)


def spoken_range(nm: float) -> str:
    """Range calls are whole miles on final -- 'six miles from the runway'."""
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "one zero", "one one", "one two"]
    n = int(round(nm))
    return words[n] if n < len(words) else str(n)
