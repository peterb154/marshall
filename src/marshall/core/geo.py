"""Range and bearing. One implementation, and the FRAME is always named.

    "GIS vector functions -- those need to be shared. There is no reason an ASR
     approach module is doing any of that math."

WHY THIS FILE EXISTS. "Bearing between two points" was implemented SIX times:

    picture.range_radial        geodesic -- correct
    agent_atc._range_radial     geodesic -- byte-for-byte the same function
    route.bearing_distance      flat metres off the sim grid, labelled TRUE
    geometry.bearing_between    flat east/north approximation
    asr.py:426, :449            more flat atan2, inside the approach logic
    PostGIS ST_Azimuth          in the feed

Two of those were the same code in two modules, and the copy in `agent_atc`
said in its own docstring that a THIRD one was wrong. Somebody found the
correct implementation, knew another copy was broken, and made a second copy
instead of one home.

THE FRAMES ARE THE WHOLE PROBLEM, and they are why this is worth a module
rather than a utility function. There are two right answers to "which way does
Batumi's runway point" and they differ by six degrees:

    305.6   the DCS GRID frame -- the F10 ruler, the aircraft compass, and
            `Airbase.getRunways().course`
    311.3   TRUE -- the geodesic bearing between the two thresholds

DCS's x/z grid is a transverse Mercator and its north is not true north. The
angle between them is the grid convergence, 5.74 degrees at Batumi. Our radials
come from lat/lon and are TRUE; the sim's own numbers are GRID; and a function
called `bearing_distance` that returns one while promising the other is how the
paper nav log came to be 5.74 degrees out on every leg -- 2.39 nm of cross-track
over a 23.9 nm leg, on a chart a pilot flies. It is the opening finding of the
29 July audit and it has been open since.

So no function here returns "a bearing". They return a TRUE bearing or a GRID
bearing, they say which in the name, and converting between them takes an
explicit convergence. A caller who does not know which frame he is in gets a
name that will not let him pretend otherwise.
"""

from __future__ import annotations

import math

# Mean Earth radius (IUGG), and the nautical mile. Constants, like gravity --
# see STRUCTURE.md on what stays in code and what becomes a row.
EARTH_R_M = 6371008.8
NM_M = 1852.0


def range_bearing_true(origin: tuple[float, float], lat: float,
                       lon: float) -> tuple[float, float]:
    """Great-circle range in nautical miles and TRUE bearing, from an origin.

    Geodesic, not a flat-earth offset. Caucasus is a transverse Mercator, and
    the flat version was measured 1.2 nm out at the coast and 7.6 nm out at the
    target area -- so this is not pedantry about the third decimal, it is miles.
    """
    la1, lo1 = math.radians(origin[0]), math.radians(origin[1])
    la2, lo2 = math.radians(lat), math.radians(lon)
    dlo = lo2 - lo1
    cosd = (math.sin(la1) * math.sin(la2)
            + math.cos(la1) * math.cos(la2) * math.cos(dlo))
    nm = math.acos(min(1.0, max(-1.0, cosd))) * EARTH_R_M / NM_M
    brg = math.degrees(math.atan2(
        math.sin(dlo) * math.cos(la2),
        math.cos(la1) * math.sin(la2)
        - math.sin(la1) * math.cos(la2) * math.cos(dlo))) % 360.0
    return nm, brg


def range_bearing_grid(ax: float, az: float, bx: float,
                       az2: float) -> tuple[float, float]:
    """Range in nautical miles and GRID bearing, from sim x/z metres.

    The sim's own frame, and honest about it. This is the right answer when the
    number is going to be compared against something else the sim said -- a
    runway course from `getRunways`, an F10 ruler measurement, the heading on
    the pilot's compass. It is the WRONG answer for anything that will meet a
    radial computed from latitude and longitude, which is everything on the
    radar side.

    Convert with `grid_to_true` and an explicit convergence. Do not eyeball it:
    six degrees looks like a rounding error and is two miles.
    """
    dx, dz = bx - ax, az2 - az
    return math.hypot(dx, dz) / NM_M, math.degrees(math.atan2(dz, dx)) % 360.0


def grid_to_true(grid_deg: float, convergence_deg: float) -> float:
    """A DCS grid bearing into a true one.

    Convergence is the angle between grid north and true north, positive east.
    At Batumi it is 5.74 degrees: a runway on grid 305.6 is true 311.3.

    IT IS NOT A CONSTANT OF THE MAP. It varies with longitude across a
    transverse Mercator, so it belongs to the FIELD -- measured, per
    `SCHEMA.md`, as the difference between a runway's grid course and the
    geodesic bearing between its thresholds. The hand-entered 5.74 in
    `route.py` is Batumi's, and using it forty miles east is a smaller version
    of the same mistake.
    """
    return (grid_deg + convergence_deg) % 360.0


def true_to_grid(true_deg: float, convergence_deg: float) -> float:
    """The inverse. Named rather than left as `- convergence` at call sites,
    because a sign error here is invisible and costs a sortie."""
    return (true_deg - convergence_deg) % 360.0


def magnetic(true_deg: float, variation_deg: float) -> float:
    """True to magnetic. Pilots fly magnetic; radar computes true.

    A THIRD frame, and the reason every one of these takes its offset as an
    argument rather than reading a module constant: at some point this system
    works two maps at once, and a Caucasus variation applied to a Nevada
    heading is a bug nobody would see in a code review.
    """
    return (true_deg - variation_deg) % 360.0


def project_true(origin: tuple[float, float], bearing_true_deg: float,
                 nm: float) -> tuple[float, float]:
    """The point `nm` away from an origin along a TRUE bearing.

    The inverse of `range_bearing_true`, on the same sphere, so a round trip
    returns where it started -- which the flat-earth version did not, and that
    was how the seven-mile error at the target area was found.
    """
    la1, lo1 = math.radians(origin[0]), math.radians(origin[1])
    d = (nm * NM_M) / EARTH_R_M
    brg = math.radians(bearing_true_deg)
    la2 = math.asin(math.sin(la1) * math.cos(d)
                    + math.cos(la1) * math.sin(d) * math.cos(brg))
    lo2 = lo1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def crosstrack_nm(course_deg: float, bearing_to_deg: float,
                  range_nm: float) -> float:
    """How far off the centreline, positive RIGHT of course.

    Both angles must be in the SAME frame; this cannot check that for you,
    which is exactly why the frame is in the name of everything that produces
    one. Mixing a true radial with a grid course here is the six-degree error
    with the numbers already in hand.
    """
    return range_nm * math.sin(math.radians(bearing_to_deg - course_deg))
