"""How low a controller may put you, and how low the chart says you may go.

TWO DIFFERENT NUMBERS, and confusing them is the fault this module exists to
prevent. The MSA is published, sector-wide and conservative -- it is what a
pilot reads off a plate when he has lost the picture. The MVA is surveyed, cell
by cell, and it is what a controller may assign when he is watching you on
radar and knows exactly where you are.

Honouring the MSA on a vector holds an aeroplane thousands of feet above a
platform it is about to land on; assigning an MVA to a pilot flying his own
letdown puts him below the only figure he has. So both live here, both are
named for what they are, and `Field_` exposes them separately.
"""

from __future__ import annotations



# The AIP publishes minimum safe altitude as TWO sectors around the LU NDB, not
# four quadrants: 7,000 ft from 217 degrees round through north to 038, and
# 13,600 ft from 038 round through south to 217. Published and conservative, and
# two sectors removes a whole class of bug -- a 45-degree error in a four-
# quadrant lookup once put 330 (the sea, the one place it is safe to be low)
# into the mountain sector.
# Two different minimum altitudes, and conflating them grounds the approach.
#
# **MSA** is published, on the plate, and is the PILOT's number: the lowest he
# may descend to inside 25 nm if he loses everything. Batumi's is 7,000 to the
# north through west and 13,600 the rest of the way round. It is deliberately
# blunt -- one figure for a whole sector of a 25-mile circle, sized by the
# highest thing in it.
#
# **MVA** is the CONTROLLER's number: the lowest he may ASSIGN while vectoring.
# It is lower, because he knows exactly where the aircraft is and only has to
# clear the ground actually underneath it. Vectoring to the published MSA
# instead reads as safety and is not: Batumi's final is flown over open water
# where the MSA is still 7,000, so honouring it holds the aircraft four
# thousand feet above the platform until it is over the threshold. An earlier
# build did exactly that and assigned 11,700 to an aeroplane at 250 feet.
#
# Sectors are (from_bearing, to_bearing, altitude), clockwise, and may wrap.
MSA_SECTORS = [(217.0, 38.0, 7000), (38.0, 217.0, 13600)]

# Minimum vectoring altitudes, surveyed out of the sim itself by
# tools/survey_terrain.py -- `land.getHeight` over a polar grid, then the
# highest ground in each cell plus a thousand feet of clearance, rounded up.
#
# Cells, not quadrants, and the difference is not academic. The predecessor was
# four 90-degree buckets each holding the highest ground within 25 nm, which
# says 9,500 ft for everything north-east of Batumi -- including the coastal
# plain four miles out, where the survey says thirty-six feet. Flown live that
# rule climbed an aircraft repositioning at four miles to 9,500 and then, one
# bucket boundary later, told it to descend to 2,000: seven thousand feet of
# climb for nothing. The same coarseness off the departure end, where the
# buckets said 13,000, had already flown an aeroplane into the Caucasus.
#
# (bearing_from, bearing_to, out_to_nm, altitude_ft). Rings as well as spokes,
# which is the shape a real MVA chart has and for exactly this reason.
MVA_CELLS = [
    (  0.0,  30.0,   5.0,   1500),
    (  0.0,  30.0,  10.0,   1000),
    (  0.0,  30.0,  15.0,   1500),
    (  0.0,  30.0,  25.0,   1500),
    ( 30.0,  60.0,   5.0,   1500),
    ( 30.0,  60.0,  10.0,   3000),
    ( 30.0,  60.0,  15.0,   5500),
    ( 30.0,  60.0,  25.0,   8000),
    ( 60.0,  90.0,   5.0,   3000),
    ( 60.0,  90.0,  10.0,   5500),
    ( 60.0,  90.0,  15.0,   6000),
    ( 60.0,  90.0,  25.0,   9000),
    ( 90.0, 120.0,   5.0,   3000),
    ( 90.0, 120.0,  10.0,   5000),
    ( 90.0, 120.0,  15.0,   6500),
    ( 90.0, 120.0,  25.0,  11000),
    (120.0, 150.0,   5.0,   3000),
    (120.0, 150.0,  10.0,   5000),
    (120.0, 150.0,  15.0,   8000),
    (120.0, 150.0,  25.0,  12000),
    (150.0, 180.0,   5.0,   4000),
    (150.0, 180.0,  10.0,   6000),
    (150.0, 180.0,  15.0,   5500),
    (150.0, 180.0,  25.0,   9500),
    (180.0, 210.0,   5.0,   3000),
    (180.0, 210.0,  10.0,   4000),
    (180.0, 210.0,  15.0,   6000),
    (180.0, 210.0,  25.0,   9000),
    (210.0, 240.0,   5.0,   1500),
    (210.0, 240.0,  10.0,   1000),
    (210.0, 240.0,  15.0,   1000),
    (210.0, 240.0,  25.0,   3500),
    (240.0, 270.0,   5.0,   1500),
    (240.0, 270.0,  10.0,   1000),
    (240.0, 270.0,  15.0,   1000),
    (240.0, 270.0,  25.0,   1000),
    (270.0, 300.0,   5.0,   1500),
    (270.0, 300.0,  10.0,   1000),
    (270.0, 300.0,  15.0,   1000),
    (270.0, 300.0,  25.0,   1000),
    (300.0, 330.0,   5.0,   1500),
    (300.0, 330.0,  10.0,   1000),
    (300.0, 330.0,  15.0,   1000),
    (300.0, 330.0,  25.0,   1000),
    (330.0, 360.0,   5.0,   1500),
    (330.0, 360.0,  10.0,   1000),
    (330.0, 360.0,  15.0,   1000),
    (330.0, 360.0,  25.0,   1000),
]


def alt_for(bearing_deg: float, sectors) -> int:
    """Look a bearing up in a sector table. Sectors may wrap through north."""
    b = bearing_deg % 360
    for lo, hi, alt in sectors:
        inside = (lo <= b < hi) if lo < hi else (b >= lo or b < hi)
        if inside:
            return alt
    return max(a for _, _, a in sectors)


def msa_for(bearing_deg: float, sectors=None) -> int:
    """Published minimum sector altitude -- what the PILOT is briefed."""
    return alt_for(bearing_deg, sectors or MSA_SECTORS)


def mva_for(bearing_deg: float, range_nm: float | None = None, cells=None) -> int:
    """Minimum vectoring altitude -- the lowest a CONTROLLER may assign.

    Looked up by bearing AND range, because terrain has both. With no range
    given, answer for the outermost ring, which is the conservative reading and
    the only safe default when the caller does not know where the aircraft is.

    This is the altitude for where he is NOW. A vector whose track crosses
    higher ground on the way is not caught here; at Batumi every repositioning
    track runs out to the north-west over open water, so the case does not
    arise, but it is a real limit and not a solved problem.
    """
    cells = cells or MVA_CELLS
    b = bearing_deg % 360
    best = None
    for lo, hi, out_to, alt in cells:
        inside = (lo <= b < hi) if lo < hi else (b >= lo or b < hi)
        if not inside:
            continue
        if range_nm is None:
            best = max(best or 0, alt)
        elif range_nm <= out_to and (best is None or out_to < best[0]):
            best = (out_to, alt)
    if best is None:
        return max(a for *_, a in cells)
    return best if isinstance(best, int) else best[1]
