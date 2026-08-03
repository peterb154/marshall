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

# The phase-agnostic half now lives in geometry.py, because it is the same
# question whether the target is a final approach course, an airway or a run-in
# to a target -- and two copies of cross-track would drift apart. Re-exported
# rather than hidden: this module's callers ask it for Position and angle_diff
# and should keep being able to.
from marshall.atc.geometry import (            # noqa: F401
    DEG_PER_NM, Guidance, INTERCEPT_ANGLE, LOOKAHEAD_MIN_NM, LOOKAHEAD_NM,
    MAX_INTERCEPT, ON_COURSE_DEG, ON_COURSE_FLOOR_NM, Position, TURN_IN_NM,
    along_track, angle_diff, cross_track, intercept_heading,
    lookahead_nm, on_course_tolerance, turn_direction, _en,
)


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
    # The published table is the ILS GLIDEPATH, and it belongs to the ILS. A
    # surveillance approach has no glidepath: the pilot descends at a rate of
    # his choosing and levels at minimums to look for the runway. Flying the
    # glidepath numbers on a radar approach asks for 940 fpm at 200 mph, which
    # is the dive again, and it aims at a decision height the procedure is not
    # precise enough to use. So the table is read only where the aircraft is
    # actually being given a glidepath; otherwise the descent is spread across
    # the whole run from the final approach point to the missed approach point,
    # which is both gentler and what a non-precision approach IS.
    table = (getattr(profile, "descent_table", None)
             if getattr(profile, "kind", "") in ("ils", "precision") else None)
    if table:
        want = _from_table(range_nm, sorted(table))
    else:
        to_go = max(0.0, range_nm - profile.map_nm)
        want = profile.mda_ft + to_go * descent_gradient(profile)
    return max(profile.mda_ft, min(profile.platform_ft,
                                   int(round(want / 100) * 100)))


def descend_to(range_nm: float, profile) -> int:
    """The altitude to ISSUE at this range -- the one he should be at NEXT mile.

        "at 4 miles out he should say 4 miles out, on course, descend to 1200.
         This is an anticipatory call so I can be there on time rather than a
         reactive call."

    Which is how a talkdown is actually flown. "Three miles, altitude should be
    twelve hundred" tells a pilot where he ought to ALREADY be: by the time he
    has heard it, started down and got there, he is a mile further in and low.
    An instruction has to arrive before the point it applies to, or the pilot is
    permanently chasing the profile from above -- which is what he was doing.

    So the call at four miles carries the three-mile altitude, and he has a mile
    in which to fly it.

    Floored at the missed approach point: the last call does not invent a step
    below minimums.
    """
    return advisory_altitude(max(profile.map_nm, range_nm - 1.0), profile)


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
    # WHEN to start down is its own problem -- see descent.py. The old answer
    # here was a fixed feet-per-mile gradient, which is only right at one
    # groundspeed: it started a fast aeroplane down far too early and a slow one
    # too late. "Still taking me down to 2000 well before the initial fix."
    #
    # The point he has to be at platform by is the INITIAL FIX, not the runway.
    from marshall.atc import descent as D

    to_go = max(0.0, pos.range_nm - profile.final_intercept_nm)
    d = D.plan(pos.alt_ft or profile.platform_ft, profile.platform_ft,
               to_go, getattr(pos, "speed_kt", 0.0))
    # Rounded to five hundred: a controller assigns "four thousand five
    # hundred", never "four thousand five hundred and forty-four".
    want = _round_to(d.assign_ft, 500)
    here = _round_to(pos.alt_ft, 500) if pos.alt_ft else 0
    # NEVER ABOVE WHERE HE ALREADY IS -- this is a descent, and an aeroplane
    # that is low is not asked to climb back onto a profile. MSA still wins,
    # because it is a floor and not a preference.
    #
    # THE WHIPPING IS NOT FIXED HERE, and an attempt to fix it here was a
    # safety regression: applying `here` after the MSA clamp assigns a level
    # BELOW the minimum vectoring altitude for an aeroplane that is already
    # low, which is the one thing this line exists to prevent. A test caught
    # it -- 5,000 against an 8,000 MVA.
    #
    # The cause is real: recomputed every sweep against a descending
    # aeroplane, this produces a new level a few hundred feet lower each time.
    # But it is a fact about the PLAN changing continuously, and the fix is
    # hysteresis on what gets ISSUED -- see `phrasebook.LastSaid`, which is
    # where the memory of what he was last told already lives.
    return max(msa, min(want, here) if here else want)


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

# How sharply he is angled back toward the field while joining the base leg.
# Three miles beyond the line is a forty-five degree cut; on it, he flies the
# base heading. Small enough to converge, large enough not to dawdle.
BASE_INTERCEPT_NM = 3.0

# HOW WIDE THE PATTERN IS, and it is a band rather than a line.
#
#     "you could also make the IF a circle that is like 5 miles rather than a
#      point"
#
# Same insight, applied to the legs. Holding a pilot to an exact track means
# correcting him for a tenth of a mile, and a pilot who lags -- which is every
# real one -- oscillates across it: the sloppy sweep's direction changes nearly
# doubled, 899 to 1,590, without a single approach being flown better. Inside
# the band he is on the leg and is left alone.
LEG_TOLERANCE_NM = 1.5

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
    # Near the centreline is not enough on its own -- the run has to fit.
    #
    # The angle test alone says an aircraft a mile and a third off at just under
    # three miles is in position, because a mile and a third at three miles is
    # only twenty-five degrees. It is not: closing that offset costs a mile and
    # a third of centreline at forty-five degrees, and rolling out costs the
    # turn-in distance on top, which is more approach than he has left. So he
    # gets turned a hundred and thirty degrees onto a three-mile final he cannot
    # descend on or stabilise in.
    #
    # It happened to a P-47 on the go-around, at three miles, pointing away from
    # the field: "he turned me around way, way, way too soon, and that left me
    # way south of the field". He was right, and the answer is not to know he
    # went missed -- this function is stateless on purpose -- but to notice that
    # the approach does not fit in the room remaining.
    if abs(xtk) <= near and along >= abs(xtk) + TURN_IN_NM:
        return True
    return has_room(along, xtk, profile)


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


def base_leg_at(profile) -> float:
    """How far from touchdown the base leg crosses the final approach course.

    Far enough out that the turn from base onto final is an ordinary 30-45
    degree intercept with room to roll out, rather than the reversal an
    aeroplane gets when it is pointed AT a fix and arrives there facing the
    wrong way.
    """
    # The SAME distance the old fixed gate sat at, and not a foot closer. The
    # first attempt put the base at final_intercept + TURN_IN, which reads
    # sensibly and fails `has_room`: from a base leg three miles wide, the turn
    # onto final does not fit inside that, so an aeroplane flew the base almost
    # to the centreline before it was allowed to turn -- and then needed the
    # hard turn the base leg exists to avoid. 1,218 arrivals of 1,296 and 161
    # rapid reversals, against 1,296 and 1.
    return profile.final_intercept_nm + DOWNWIND_NM + TURN_IN_NM + 0.5


def base_leg_heading(pos: Position, profile, side: int) -> int:
    """Fly him a PATTERN instead of aiming him at a place.

        "if I'm going fast, he basically flies me around in circles. If I'm
         going slow enough, he aims me right at the IF -- even if I'm 180 out of
         phase, then turns me hard 180. It would be way better if he had a right
         base and a left base that he could put me on."

    Both of those failures are one cause: the old answer was a POINT, and an
    aircraft not in position was steered straight at it. Fast, the bearing to a
    point rotates as quickly as he turns and he chases it round the sky. Slow, he
    arrives pointing the wrong way, because arriving at a place says nothing
    about arriving on a HEADING.

    A base leg is a TRACK, and a track has a heading he can hold. It runs
    perpendicular to the final approach course, crossing it `base_leg_at` miles
    from touchdown, on the side he is already on -- so joining it is the same
    kind of problem as joining the final, and it is solved the same way, by
    intercepting a line rather than chasing a dot.

    Two cases and no memory, because the engine has none:

      beyond the base line   intercept it, converging on the base heading
      inside it              he has run out of room -- take him downwind,
                             parallel to the course and the other way, until
                             there is room again
    """
    crs = profile.final_crs_true
    along = along_track(pos, crs)
    xtk_now = cross_track(pos, crs)
    # Toward the centreline: from the right of course, that is a left turn.
    inbound_base = (crs - 90 * side) % 360
    beyond = along - base_leg_at(profile)

    if beyond < -0.5:
        # No room for a base yet: he is inside it, or behind the field. Fly the
        # DOWNWIND, which is its own line -- parallel to the course, opposite
        # direction, offset to his side -- and joined the same way the base is.
        #
        # A pure outbound heading was the first version and it is a trap: from
        # behind the field it is forty miles of straight and level before the
        # base is even reachable, and the sweep simply timed out. Angling him
        # out to the downwind offset while he goes gets him there in a leg
        # rather than a journey.
        want = DOWNWIND_NM * side
        drift = (want - xtk_now) * side          # + when he must open out
        if abs(drift) <= LEG_TOLERANCE_NM:
            return round((crs + 180) % 360)      # on the downwind: fly it
        off = abs(drift) - LEG_TOLERANCE_NM
        corr = min(math.degrees(math.atan2(off, BASE_INTERCEPT_NM)), MAX_INTERCEPT)
        corr = corr * (1 if drift > 0 else -1)
        return round((crs + 180 - corr * side) % 360)

    # Joining the base is joining a line, but NOT with `intercept_heading`:
    # that one's lookahead is scaled for short final, and handed a
    # twenty-five-mile problem it saturates -- the correction came out at
    # eighty degrees, which pointed him straight back outbound and he flew away
    # from the field until the fuel ran out. 1,197 arrivals of 1,296.
    #
    # The correction here is measured from the BASE LINE and turned toward the
    # final approach course: on the line he flies the base heading exactly, and
    # the further beyond it he is the more he is angled back in, to a limit of
    # forty-five degrees. That is an intercept, and it converges instead of
    # chasing.
    if beyond <= LEG_TOLERANCE_NM:
        return round(inbound_base)          # on the base leg: fly it
    corr = math.degrees(math.atan2(beyond - LEG_TOLERANCE_NM, BASE_INTERCEPT_NM))
    return round((inbound_base + min(corr, MAX_INTERCEPT) * side) % 360)


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
    inbound_radial = (profile.final_crs_true + 180) % 360
    # Rebuild the point in the field's polar frame, which is the only frame the
    # radar picture speaks, so nothing here needs a second coordinate system.
    ae, an = _en(along, inbound_radial)
    right = (profile.final_crs_true + 90) % 360
    ce, cn = _en(across, right)
    pe, pn = ae + ce, an + cn
    fe, fn = _en(pos.range_nm, pos.radial_deg)
    return math.degrees(math.atan2(pe - fe, pn - fn)) % 360


def at_touchdown(pos: Position, profile) -> Position:
    """The same aircraft, measured from the TOUCHDOWN POINT.

    Radar reports range and bearing from a reference the sim gives us, and at
    Batumi that is the runway centre. What an approach is flown to is the
    threshold. The two differ by half the runway, which is 0.56 nm here, and the
    difference lands squarely on the descent profile: aim at the centre and the
    pilot is half a mile of glidepath high over the threshold, every time.

    A plain translation along the course. Cross-track is untouched, because the
    touchdown point is on the centreline -- only how far he has left to run
    changes, which is the number the altitude comes from.
    """
    off = getattr(profile, "touchdown_offset_nm", 0.0)
    if not off:
        return pos
    # The touchdown point sits `off` miles UP the course from the reference.
    te, tn = _en(off, (profile.final_crs_true + 180) % 360)
    ae, an = _en(pos.range_nm, pos.radial_deg)
    de, dn = ae - te, an - tn
    return Position(math.hypot(de, dn), math.degrees(math.atan2(de, dn)) % 360,
                    pos.alt_ft, pos.heading_deg)


def guide(pos: Position, profile, on_missed: bool = False) -> Guidance:
    """One radar look -> the next instruction.

    Three states, and which one he is in is decided by a single question --
    `has_room` -- rather than by a chain of them:

      final        established on the course inside the fix: hold it, come down
      vector/in    in position: cut across at 45 until close, then blend on
      vector/out   not in position: go to a fixed gate that puts him in position

    `on_missed` is the one fact this function cannot work out for itself, and it
    is the caller's to hold. Whether a man is flying the published missed
    approach is a fact about his HISTORY, not about where he is: the procedure
    commands a two-hundred-degree turn, and half way round it he is on nobody's
    track and pointing at nothing in particular. Every stateless test for it
    flickers, and each flicker is a reversal on the radio.

    Geometry still starts it -- the entry test below is unchanged and catches
    the pilot who goes around without saying so. The flag is only what makes him
    STAY on it, and it costs nothing when the caller has no opinion.

    Everything except the last mile happens OUTSIDE the fix, so that by the fix
    he is established, on course and at the fix altitude. The fix is a gate he
    passes through, never a point to be chased -- chasing a computed point is
    what turned a pilot away from the field, orbited another, and flew a third
    out to sea over three sorties.
    """
    # MEASURE FROM THE TOUCHDOWN POINT, not from whatever the radar reference
    # happens to be. At Batumi they are half a mile apart -- the reference is the
    # runway CENTRE -- and every range call, and therefore the entire descent
    # profile, was aimed at a point beyond the far end of the runway. A pilot
    # flying it arrives over the threshold with half a mile of descent still
    # owed to him, which is exactly what "I was always too high" means.
    #
    # One translation, here, so everything downstream -- along, cross, range,
    # the altitude table, the missed approach point -- is relative to the place
    # the wheels are meant to touch.
    pos = at_touchdown(pos, profile)

    xtk = cross_track(pos, profile.final_crs_true)
    along = along_track(pos, profile.final_crs_true)
    tol = on_course_tolerance(pos.range_nm)
    # Is he flying the approach at all? Pointing roughly down the course, on
    # the near side of the field. This is what decides whether the words "of
    # course" mean anything to him -- see below.
    inbound = (abs(angle_diff(pos.heading_deg, profile.final_crs_true)) <= 60
               and along > 0)

    def as_flown(magnetic_deg: float) -> float:
        """A PUBLISHED heading, put into the frame `out` expects.

        The plate's missed approach heading is already magnetic -- it is what
        the chart says and what the pilot sets on his gyro. Everything reaching
        `out` is true, so it has to go in as true and come back out unchanged.
        Skipping this quietly turned a published "climb on 330" into 324: a
        six-degree error in the one instruction given to a pilot who has just
        gone around and is looking for something to hold on to.
        """
        return (magnetic_deg + profile.magvar_deg) % 360

    def out(phase, heading, alt):
        # EVERYTHING ABOVE IS TRUE; EVERYTHING SPOKEN IS MAGNETIC.
        #
        # Radar reports position and heading in true, so that is the frame the
        # geometry has to work in -- and the pilot flies a compass, so that is
        # the frame the number has to be said in. One value was doing both jobs
        # and the centreline was being drawn wherever the difference put it.
        h = round(heading - profile.magvar_deg) % 360
        # Deviation is a statement ABOUT THE FINAL APPROACH COURSE, so it is
        # only said to someone flying it. Drifting off course while inbound is
        # exactly what he needs to hear; being "left of course" while
        # repositioning, or outbound on the missed approach, is not true in any
        # useful sense -- he is flying the heading he was given and is where he
        # should be. It was said to an aircraft climbing away on 330 having
        # just been told to fly 330.
        if inbound or phase in ("final", "map"):
            dev = ("on course" if abs(xtk) <= tol
                   else "right of course" if xtk > 0 else "left of course")
        else:
            dev = ""
        on_approach = phase in ("final", "map")
        speed = (profile.speed_kt_at(along, on_approach)
                 if hasattr(profile, "speed_kt_at") else 0.0)
        # WHICH WAY HE TURNS IS GEOMETRY, so it is worked out in TRUE against
        # his true heading -- not against the magnetic number we are about to
        # say. Comparing the two frames put a six degree bias on every turn
        # decision, and within six degrees of on-course that is a coin toss:
        # the sweep went from 1 rapid reversal to 139 the moment it was wrong.
        # The anticipatory altitude rides along beside the advisory one. Only
        # on the approach itself: while repositioning there is no profile to be
        # ahead of.
        nxt = (descend_to(pos.range_nm, profile)
               if phase in ("final", "map") else None)
        return Guidance(phase, h, alt, pos.range_nm, xtk, dev,
                        turn_direction(pos.heading_deg, round(heading) % 360),
                        speed, heading_true=round(heading) % 360,
                        descend_to_ft=nxt)

    # Established: on the course and pointing down it. The heading check is not
    # pedantry -- a go-around tracking outbound sits on the centreline with a
    # tiny cross-track, and was once called established and sent down to
    # minimums while flying away from the field.
    tracking_in = abs(angle_diff(pos.heading_deg, profile.final_crs_true)) <= 60
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
            return out("map", intercept_heading(profile.final_crs_true, xtk, along),
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
                   intercept_heading(profile.final_crs_true, xtk, along),
                   advisory_altitude(pos.range_nm, profile) if inside
                   else safe_alt(pos, profile))

    # ALREADY FLYING THE MISSED, and not yet finished it.
    #
    # Above the in-position question, which is the whole fix. Underneath it this
    # was unreachable on the second leg: an aeroplane climbing out on 330 sits
    # on the APPROACH side of the field with positive along-track, reads as "in
    # position", and is handed an intercept -- turning it back towards the field
    # it is climbing away from. Reported from the cockpit on the first night and
    # true until now:
    #
    #   "pny flight is outbound after the missed and the atc is saying that he
    #    is left of course (thinking he is inbound)"
    #
    # The procedure has a defined end and this is it: at the missed approach
    # altitude he is an ordinary repositioning problem again.
    if (on_missed and pos.alt_ft < profile.missed_climb_ft
            and pos.range_nm <= profile.final_intercept_nm):
        straight_ft = getattr(profile, "missed_straight_ft", 0)
        return out("missed",
                   profile.final_crs_true if pos.alt_ft < straight_ft
                   else as_flown(profile.missed_hdg),
                   profile.missed_climb_ft)

    if in_position(along, xtk, profile):
        # In position. Far off the course, cut across at a fixed 45 -- fixed,
        # because that is the angle the room was reserved at, and flying any
        # shallower spends centreline he has not got. Inside the turn-in
        # distance, blend on proportionally so he rolls out on the course
        # rather than through it.
        if abs(xtk) > TURN_IN_NM:
            heading = profile.final_crs_true - INTERCEPT_ANGLE * (1 if xtk > 0 else -1)
        else:
            heading = intercept_heading(profile.final_crs_true, xtk, along)
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
        heading = (profile.final_crs_true if pos.alt_ft < straight_ft
                   else as_flown(profile.missed_hdg))
        return out("missed", heading, profile.missed_climb_ft)

    # Not in position: fly him the pattern. A base leg is a track he can hold,
    # where the old fixed gate was a point he had to chase -- see
    # base_leg_heading.
    return out("vector", base_leg_heading(pos, profile,
                                          reposition_side(xtk, profile)),
               safe_alt(pos, profile))


# How far above field elevation still counts as being on it. Radar altitude is
# coarse and the aerodrome is not flat, so a landed aeroplane does not report
# exactly the field elevation -- but it is nowhere near two hundred feet up.
ON_DECK_FT = 200

# And how far from the field. Wide enough to cover the far end of a runway and
# the taxiways, narrow enough that an aircraft at two hundred feet a mile and a
# half out -- which is an aeroplane on short final, not a parked one -- is still
# being flown.
ON_DECK_NM = 1.2


def on_the_ground(pos: Position, profile) -> bool:
    """Is this aeroplane on the aerodrome rather than flying an approach?

    The approach ends when the wheels are down, and the scope is what knows: at
    the field, at field elevation. Nothing was asking, so the controller went on
    working an aircraft that was parked -- "I'm sitting on the ground at Batumi,
    and Batumi Tower thinks I'm on the missed approach".

    Deliberately a question about POSITION and not about what anyone said. A
    pilot who forgets to report down is common; an aeroplane at zero feet on the
    aerodrome that is somehow still airborne is not.
    """
    field_ft = getattr(profile, "field_elev_ft", 0)
    return (pos.range_nm <= ON_DECK_NM
            and pos.alt_ft <= field_ft + ON_DECK_FT)


def spoken_range(nm: float) -> str:
    """Range calls are whole miles on final -- 'six miles from the runway'."""
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "one zero", "one one", "one two"]
    n = int(round(nm))
    return words[n] if n < len(words) else str(n)
