"""Where he is along a route, and what to tell him next. PURE GEOMETRY.

    "I want to be able to have atc vector us along a flight plan. Give us a
     heading, alt and distance, tell us when we pass a steerpoint and give us
     new heading alt and distance and alert us when we're off course"

No radio, no board, no database and no opinion about who is talking. It takes
the legs and a position and answers three questions -- which leg, how is he
doing on it, and has he passed the end of it -- so that all of them are
testable without a sortie, and so the sweep can fly a synthetic aeroplane down
a route and count what a controller would have said.

THE HEADINGS OUT OF HERE ARE TRUE. Converting to magnetic is the speaking
boundary's job and belongs in ONE place, because three separate renderers in
this codebase already forget to do it and the frame is not in the type. What is
different about these is that they are FLOWN: a radial spoken six degrees off
is a wrong number on a page, a heading spoken six degrees off is a wrong
aeroplane. See `Guidance.heading` in `atc/geometry.py`, which is magnetic and
says so in its own comment.

IT IS BUILT ON `geo.crosstrack_nm` AND `geo.alongtrack_nm` rather than on new
trigonometry. Those are the same decomposition of the same triangle that the
approach talkdown uses, and `core/geo.py` exists because "bearing between two
points" once had five implementations, four live and one wrong.
"""
from __future__ import annotations

from dataclasses import dataclass

from marshall.core import geo


# HOW CLOSE COUNTS AS PASSING IT. A pilot leads the turn -- he does not fly to
# the fix and pivot -- so a mile and a half short, already turning, is past it
# by any reading a controller would use. Wide enough to catch the lead turn,
# tight enough that it cannot fire on the way TO a fix that is still miles off.
CAPTURE_NM = 1.5


@dataclass(frozen=True)
class Leg:
    """One fix on the route, and the level it is flown at."""
    fix: str
    lat: float
    lon: float
    alt_ft: int = 0


@dataclass(frozen=True)
class Along:
    """Where he is, and what he is owed.

    `index` is the leg he is ON -- the one ENDING at `fix`. `passed` says he has
    crossed the perpendicular through that fix on this poll, which is the moment
    to call it and move him on.
    """
    index: int
    fix: str
    heading_true: float
    distance_nm: float
    alt_ft: int
    xtk_nm: float                # + right of course as he flies it
    along_nm: float              # down the leg from its start fix
    leg_nm: float
    passed: bool = False

    @property
    def to_go_nm(self) -> float:
        """Distance remaining ALONG the leg, never negative."""
        return max(0.0, self.leg_nm - self.along_nm)


def guide(legs, lat: float, lon: float, index: int = 0,
          start=None) -> Along | None:
    """His guidance on the leg he is on. None when the route is finished.

    `index` is the LATCH, held by the caller and never decreasing -- a wobble at
    a fix must not un-pass it and send him back to a point he is behind. This
    function will report `passed`; advancing is the caller's to record, because
    the latch has to be durable and geometry has no memory.

    `start` is where the FIRST leg begins -- his position when following was
    granted, or the field he departed. Without it the first leg has no origin
    to measure along, and a route's fixes are its ENDS: `legs[0]` is somewhere
    to go, not somewhere he has been.
    """
    legs = list(legs or [])
    if index >= len(legs):
        return None
    a = (legs[index - 1] if index > 0 else start)
    b = legs[index]
    if a is None:
        # NO ORIGIN FOR THIS LEG, so there is no course to be off. He still gets
        # a bearing and a range to the fix, which is the whole of "direct BAR"
        # and is honest about the rest: no cross-track, and no passage, because
        # both need a line and there is not one.
        nm, brg = geo.range_bearing_true((lat, lon), b.lat, b.lon)
        return Along(index, b.fix, brg, nm, b.alt_ft, 0.0, 0.0, nm)
    leg_nm, course = geo.range_bearing_true((a.lat, a.lon), b.lat, b.lon)
    from_a_nm, from_a_brg = geo.range_bearing_true((a.lat, a.lon), lat, lon)
    along = geo.alongtrack_nm(course, from_a_brg, from_a_nm)
    xtk = geo.crosstrack_nm(course, from_a_brg, from_a_nm)
    # THE HEADING IS TO THE FIX, not down the leg. Down the leg is where he
    # should have been; to the fix is where he is going from where he actually
    # is, and a man three miles off course who flies the leg's course stays
    # three miles off course for ever.
    nm, brg = geo.range_bearing_true((lat, lon), b.lat, b.lon)
    # PASSAGE IS THE PERPENDICULAR **OR** THE CAPTURE RADIUS, and it took the
    # sweep to find that one of them alone is not enough.
    #
    # The perpendicular is the robust half and was the whole of it: a fast jet
    # cutting the corner may never come inside any radius worth picking, so a
    # distance threshold on its own misses him. But a pilot who LEADS the turn
    # -- which is what pilots do -- turns a mile short and flies away, and never
    # crosses the perpendicular at all. `tools/route_sweep.py` scored three
    # fixes flown past with no call, from an aeroplane doing nothing unusual.
    #
    # So both. The perpendicular catches the overshoot and the wide pass; the
    # radius catches the lead turn. Neither is a substitute for the other, which
    # is why the sweep counts `missed` and treats any as a bug.
    return Along(index, b.fix, brg, nm, b.alt_ft, xtk, along, leg_nm,
                 passed=(along >= leg_nm or nm <= CAPTURE_NM))


def next_index(now: Along | None, index: int) -> int:
    """The latch's new value. Never decreases, advances only on passage."""
    if now is None or not now.passed:
        return index
    return index + 1


def off_course(now: Along | None, alerting: bool, alert_nm: float = 2.0,
               clear_nm: float = 1.0, settle_nm: float = 5.0) -> bool:
    """Should he be TOLD he is off course? Hysteresis, and a turn guard.

    `alerting` is whether he is already being told, so the band works: it takes
    `alert_nm` to start and coming inside `clear_nm` to stop. Without that he is
    nagged on the boundary -- measured on the approach sweep, where rounding
    without hysteresis took dithering from 0 to 7 and turns from 581 to 1614.

    AND SILENT THROUGH THE TURN, which is the one that decides whether this
    reads as a controller or a nag. At 400 knots and 30 degrees of bank the
    radius is about 4 nm, so a ninety-degree turn at a fix swings four miles
    wide of the new leg before it settles and a 2 nm alert would fire on EVERY
    turn. `settle_nm` is measured down the leg rather than in seconds because
    the swing scales with speed and a clock does not.

    It says nothing about whether he is under a vector of ours -- that is not
    geometry and the caller knows it. `asr.guide` said "you are left of course"
    to an aeroplane climbing away on 330 having just been told to fly 330.
    """
    if now is None or now.leg_nm <= 0:
        return False
    if now.along_nm < settle_nm:
        return False
    off = abs(now.xtk_nm)
    return off >= alert_nm if not alerting else off > clear_nm
