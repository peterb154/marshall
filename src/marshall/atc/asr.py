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
    deviation: str              # "on course" | "left of course" | "right of course"
    turn: str = ""              # "left" | "right", the short way round
    speed_kt: float = 0.0       # the speed this leg should be flown at

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


# Nominal descent gradient for the advisory altitudes, in feet per mile. Three
# degrees is the standard approach slope; 318 ft/nm is its gradient.
FT_PER_NM = 318.0


def descent_gradient(profile) -> float:
    """Feet per mile from the final approach point down to minimums.

    DERIVED, not assumed. The plate's three degrees is the ILS glidepath and it
    is aimed at the threshold; a surveillance approach has no glidepath and does
    not go to the threshold -- it descends to minimums and levels there to look
    for the runway. So the gradient that matters is the one joining two
    published points, the fix altitude at the final approach point and the
    minimum descent altitude at the missed approach point, and at Batumi that is
    about 2.3 degrees rather than 3.

    It also has to be derived rather than fixed if this is to work at another
    field, where the fixes sit at different distances and the answer is a
    different number.
    """
    run = max(0.1, profile.fap_nm - profile.map_nm)
    return (profile.platform_ft - profile.mda_ft) / run


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
    table = getattr(profile, "descent_table", None)
    if table:
        want = _from_table(range_nm, sorted(table))
    else:
        to_go = max(0.0, range_nm - profile.map_nm)
        want = profile.mda_ft + to_go * descent_gradient(profile)
    return max(profile.mda_ft, min(profile.platform_ft,
                                   int(round(want / 100) * 100)))


def _from_table(range_nm: float, table: list) -> float:
    """Read a published descent table, straight-lining between its rows.

    The table is a list of points on one straight path, so interpolating
    between them and extending past the ends with the same slope is reading it
    rather than inventing anything.
    """
    if range_nm <= table[0][0]:
        (r0, a0), (r1, a1) = table[0], table[1]
    elif range_nm >= table[-1][0]:
        (r0, a0), (r1, a1) = table[-2], table[-1]
    else:
        for i in range(len(table) - 1):
            if table[i][0] <= range_nm <= table[i + 1][0]:
                (r0, a0), (r1, a1) = table[i], table[i + 1]
                break
    slope = (a1 - a0) / (r1 - r0)
    return a0 + (range_nm - r0) * slope


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
    # Range matters as much as bearing: the mountains east of Batumi are
    # twenty miles out, and the ground four miles out on the same radial is a
    # beach. Asking by bearing alone assigns the mountain's altitude to an
    # aircraft over the beach.
    msa = (profile.min_safe_ft(pos.radial_deg, pos.range_nm)
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


# The downwind offset: how far off the centreline to run the repositioning leg.
# Three miles is a little under three standard-rate turn radii at 240 mph, which
# is what a 45-degree turn onto the intercept and a second one onto the course
# need between them without either being flown as a reversal.
DOWNWIND_NM = 3.0

# How far past the missed approach point still counts as being AT it. The point
# has no width, and an aircraft crosses it between radar looks -- most of a mile
# at approach speed on a fifteen-second sweep -- so a test for "inside" alone
# can miss it entirely and leave the approach with no terminal state, which is
# what left one simulated aircraft flying circuits over the threshold forever.
# A mile past the threshold he is over the runway; four miles past he has flown
# through and is a repositioning problem again.
MAP_OVERSHOOT_NM = 1.0


def entry_gate(profile, side: int) -> tuple[float, float]:
    """The point the aircraft is repositioned to, in (along, cross) miles.

    A fixed place on the ground, on the given side of the centreline, sitting
    just outside the intercept wedge -- so arriving there IS being in position,
    and the turn onto the 45 happens as he gets there rather than being a
    separate decision. `side` is +1 right of the inbound course, -1 left.
    """
    across = DOWNWIND_NM * side
    return (profile.final_intercept_nm + DOWNWIND_NM + TURN_IN_NM + 0.5, across)


# How close to the centreline counts as "already near enough to just steer on",
# expressed as an angle so it means the same thing at twenty miles and at three.
# Thirty degrees is the shallowest a proportional correction closes at.
STEER_ON_DEG = 30.0


def in_position(along: float, xtk: float, profile) -> bool:
    """Can the approach be flown from here, or does he have to be repositioned?

    Two ways to be in position, and both are needed. Either he is near enough
    to the centreline that ordinary course-keeping will hold him on it -- which
    has to be judged as an ANGLE, since half a mile off at thirteen miles is
    nothing and half a mile off at one is a go-around -- or he is far enough out
    to fly a full intercept, which is what `has_room` answers.

    Asking only the second question is what produced the last dither: an
    aircraft established on the centreline thirteen miles out was asked whether
    it had room to intercept, the answer went false as it flew, and it was sent
    back out to reposition from a perfect final approach.
    """
    if along <= 0:                       # past the field: nothing left to fly
        return False
    near = min(TURN_IN_NM, along * math.tan(math.radians(STEER_ON_DEG)))
    return abs(xtk) <= near or has_room(along, xtk, profile)


def has_room(along: float, xtk: float, profile) -> bool:
    """Is there enough centreline left for a full intercept from here?

    This is the whole engine, and it is one line because it has to be. Closing
    the centreline at 45 degrees trades one mile of centreline for one mile of
    offset, so an aircraft `xtk` miles off needs `xtk` miles of run, plus the
    room to roll out, plus everything inside the fix which is not his to spend.

    The property that matters is that the answer does not change while he flies
    the intercept: at 45 degrees `along` and `xtk` fall together, so `along -
    xtk` is constant and an aircraft that has room keeps having room, the whole
    way in. Four previous versions decided the question afresh on every radar
    look with a stack of conditionals, and two of those conditionals disagreed
    near the boundary -- so the aircraft was turned in, then sent back out, then
    turned in again, forever. It is not enough for the rule to be right; it has
    to be one rule.
    """
    return along >= profile.final_intercept_nm + abs(xtk) + TURN_IN_NM


def reposition_side(xtk: float, profile) -> int:
    """Which side to take him round on. +1 right of the inbound course, -1 left.

    Normally the side he is already on -- nobody is dragged across the
    centreline to join it. When he is ON the centreline and being repositioned
    (a go-around is exactly this: over the field, lined up, and with no approach
    left), the sign of a near-zero cross-track is noise, and reading it would
    flip him between two gates as he wanders across the line. So that case is
    decided by the missed approach instead, which already turns him one
    particular way for terrain reasons, and the reset stays on the side the
    procedure put him.
    """
    if abs(xtk) > TURN_IN_NM:
        return 1 if xtk > 0 else -1
    return -1 if getattr(profile, "missed_turn", "LEFT").upper() == "LEFT" else 1


def _to_point(pos: Position, profile, along: float, across: float) -> float:
    """Bearing from the aircraft to a point given in (along, cross) miles."""
    inbound_radial = (profile.final_crs + 180) % 360
    # Rebuild the point in the field's polar frame, which is the only frame the
    # radar picture speaks, so nothing here needs a second coordinate system.
    ae, an = _en(along, inbound_radial)
    right = (profile.final_crs + 90) % 360
    ce, cn = _en(across, right)
    pe, pn = ae + ce, an + cn
    fe, fn = _en(pos.range_nm, pos.radial_deg)
    return math.degrees(math.atan2(pe - fe, pn - fn)) % 360


def guide(pos: Position, profile) -> Guidance:
    """One radar look -> the next instruction.

    Three states, and which one he is in is decided by a single question --
    `has_room` -- rather than by a chain of them:

      final        established on the course inside the fix: hold it, come down
      vector/in    in position: cut across at 45 until close, then blend on
      vector/out   not in position: go to a fixed gate that puts him in position

    Everything except the last mile happens OUTSIDE the fix, so that by the fix
    he is established, on course and at the fix altitude. The fix is a gate he
    passes through, never a point to be chased -- chasing a computed point is
    what turned a pilot away from the field, orbited another, and flew a third
    out to sea over three sorties.
    """
    xtk = cross_track(pos, profile.final_crs)
    along = along_track(pos, profile.final_crs)
    tol = on_course_tolerance(pos.range_nm)
    deviation = ("on course" if abs(xtk) <= tol
                 else "right of course" if xtk > 0 else "left of course")

    def out(phase, heading, alt):
        h = round(heading) % 360
        on_approach = phase in ("final", "map")
        speed = (profile.speed_kt_at(along, on_approach)
                 if hasattr(profile, "speed_kt_at") else 0.0)
        return Guidance(phase, h, alt, pos.range_nm, xtk, deviation,
                        turn_direction(pos.heading_deg, h), speed)

    # Established: on the course and pointing down it. The heading check is not
    # pedantry -- a go-around tracking outbound sits on the centreline with a
    # tiny cross-track, and was once called established and sent down to
    # minimums while flying away from the field.
    tracking_in = abs(angle_diff(pos.heading_deg, profile.final_crs)) <= 60
    on_the_course = abs(xtk) <= max(tol, TURN_IN_NM / 4) and tracking_in
    if on_the_course and along > -MAP_OVERSHOOT_NM:
        # The missed approach point is a place on the APPROACH -- so far down
        # the final approach course, established -- and not a radius round the
        # field. Measuring it as a radius announced it to any aircraft that
        # happened to be repositioning overhead, which is most of them, since
        # the track from the far side to the entry gate goes over the top. It
        # also made the point unhittable between radar looks: at approach speed
        # a fifteen-second gap is most of a mile, so an aircraft could be
        # outside the circle on one sweep and past the field on the next.
        # Hence "at or past", not "within": an aircraft lined up and pointing
        # at the runway with the threshold behind it has finished the approach
        # whether it lands or goes around, and either way it is not still
        # being vectored onto a final it is already past.
        if -MAP_OVERSHOOT_NM <= along <= profile.map_nm:
            return out("map", intercept_heading(profile.final_crs, xtk, along),
                       profile.mda_ft)
        # Anything further through than that has flown the approach and missed
        # it, and is a repositioning problem -- so it falls out of this branch
        # entirely rather than being handed the final approach course. Handing
        # it over was a five-line convenience that told an aircraft three miles
        # past the threshold, still pointing down the runway heading, to fly
        # that heading; it did, out to sea, indefinitely.
        # Established, at whatever range. It is only "final" once inside the
        # fix; outside it he is still being vectored, just along the course --
        # which is also where the descent profile still applies rather than the
        # published one.
        inside = 0 < along <= profile.final_intercept_nm
        return out("final" if inside else "vector",
                   intercept_heading(profile.final_crs, xtk, along),
                   advisory_altitude(pos.range_nm, profile) if inside
                   else safe_alt(pos, profile))

    if in_position(along, xtk, profile):
        # In position. Far off the course, cut across at a fixed 45 -- fixed,
        # because that is the angle the room was reserved at, and flying any
        # shallower spends centreline he has not got. Inside the turn-in
        # distance, blend on proportionally so he rolls out on the course
        # rather than through it.
        if abs(xtk) > TURN_IN_NM:
            heading = profile.final_crs - INTERCEPT_ANGLE * (1 if xtk > 0 else -1)
        else:
            heading = intercept_heading(profile.final_crs, xtk, along)
        # Down the descent profile as he closes, floored by the minimum
        # vectoring altitude for the ground he is actually over -- so he
        # arrives at the fix at the fix altitude rather than being dropped to
        # it in one instruction on short final.
        return out("vector", heading, safe_alt(pos, profile))

    # Past the field and low: he has just flown the approach and missed it, and
    # what he needs is the PUBLISHED missed approach, not a vector. The
    # difference is not cosmetic. Repositioning treats him like any other
    # out-of-position aircraft and floors his altitude at the minimum vectoring
    # altitude for the ground beneath him -- which, off the departure end at
    # Batumi, is thirteen thousand feet of Caucasus. Flown live, an aircraft
    # over the threshold at six hundred feet was told to climb to thirteen
    # thousand on a heading into the mountains, and it went into them.
    #
    # The plate has the answer and we already carry it: straight ahead, and at
    # eight hundred feet turn left onto 330 climbing three thousand -- a track
    # that runs out over the water, which is exactly why it is charted that way.
    # Only once he is up at the missed approach altitude is he an ordinary
    # repositioning problem again.
    # Narrowly: just off the departure end, lined up, low. An aircraft merely on
    # the far side of the field -- arriving from the north-east, say -- has not
    # flown anything and must NOT be given the missed approach; it needs the
    # ordinary vector, and the minimum vectoring altitude for the mountains it
    # is actually over. The two cases look alike in along-track alone, which is
    # why all three conditions are here.
    if (along <= 0 and abs(xtk) <= TURN_IN_NM
            and pos.range_nm <= profile.final_intercept_nm
            and pos.alt_ft < profile.missed_climb_ft):
        straight_ft = getattr(profile, "missed_straight_ft", 0)
        heading = (profile.final_crs if pos.alt_ft < straight_ft
                   else profile.missed_hdg)
        return out("missed", heading, profile.missed_climb_ft)

    # Not in position: send him to a fixed point that puts him in position. A
    # real place on the ground, so the track to it does not move under him --
    # and it sits just outside the wedge, so arriving there and being ready to
    # turn in are the same event rather than two decisions that can disagree.
    g_along, g_across = entry_gate(profile, reposition_side(xtk, profile))
    return out("vector", _to_point(pos, profile, g_along, g_across),
               safe_alt(pos, profile))


def spoken_range(nm: float) -> str:
    """Range calls are whole miles on final -- 'six miles from the runway'."""
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "one zero", "one one", "one two"]
    n = int(round(nm))
    return words[n] if n < len(words) else str(n)
