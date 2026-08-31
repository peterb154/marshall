"""Where the runways are, so "is anybody on it" is an OBSERVATION.

    "since the sim exposes runway geometry - we ought to have a deterministic
     check to see if anyone is on the runway"

WHY THIS LOOKED UNBUILDABLE FOR MONTHS, and the note that made it so. Two
docstrings in this repo said an aerodrome row "carries a position and a landing
heading and no runway length or thresholds, so there is no polygon to test a
point against". That is true of PYDCS. It is not true of the SIM: DCS's
`Airbase:getRunways()` returns position, course, length and width, over the same
gRPC the bridge already uses for units and the mission clock. The note was
correct about the source somebody happened to check and became a reason not to
look anywhere else.

Occupancy was therefore INFERRED from what people said -- a rung, a report --
and every incursion so far has been that inference being wrong. An observation
cannot be argued with, and it covers the two cases a report never will:

    AI aircraft      never say "clear of the active", so every AI landing held
                     the strip until a five-minute timeout assumed it clear
    a forgetful man  the pilot who taxis off and says nothing

THE COURSE CONVENTION IS THE NEGATIVE OF THE MAGNETIC HEADING, in radians, and
it is worth writing down because getting it wrong yields a plausible rectangle
at the wrong ANGLE rather than an error -- and six degrees of rotation walks the
ends of a 2 km strip a hundred metres sideways, clear of a rectangle sixty
metres wide. Taking `+course` gives 54 and 110 degrees, which match nothing on
either aerodrome.

    Batumi   "31"  course 0.9501 rad -> 305.6, and 125.6 the other way
    Kobuleti "25"  course 1.9194 rad -> 250.0, and  70.0 the other way

Those are the published MAGNETIC courses -- `final_crs` is 125 and 70. I first
recorded them as true, which they are not.

THE POLYGON IS CHECKED AGAINST SURVEYED DATA THIS PROJECT ALREADY HAD, because
a rectangle of the right size at the wrong angle passes every test that only
measures it. Its long axis, in true degrees on the sphere, against
`ApproachProfile.final_crs_true`:

    Batumi     polygon 131.4    surveyed 131.0
    Kobuleti   polygon  75.9    surveyed  75.9

`heading_true` on this record is therefore derived from the CORNERS and not
from `course`. The corners are what the sim projected; everything else is our
arithmetic about them.

NO POSTGIS, AND `core/geo.py` SAYS WHY: it earns its place when the database
must FIND or ORDER rows spatially, not as a calculator when both points are
already in Python. There are two polygons and a handful of tracks, all of them
already here. The corners arrive as latitude and longitude because the SIM
converts them -- `coord.LOtoLL` -- and a flat-earth conversion of our own is
7.6 nm out at 50 nm on this map.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Runway:
    """One strip, as the four corners the sim gave us.

    `corners` are (lon, lat) in order around the rectangle. Stored as given
    rather than as a centre and a bearing: the sim did the projection, and
    re-deriving corners from a centre would put our own flat-earth arithmetic
    back in the middle of the one calculation this exists to make exact.
    """
    field_name: str
    name: str
    length_m: float
    width_m: float
    heading_true: float
    corners: tuple = field(default_factory=tuple)

    def holds(self, lat: float, lon: float, margin_m: float = 0.0) -> bool:
        """Is this point on the strip?

        `margin_m` widens the rectangle. It defaults to nothing and exists for
        one honest reason: a wingtip is not a point, and an aeroplane whose
        reported position is a metre off the edge is still on the runway. The
        caller decides, because the right margin for "may I take off" is not
        the right one for "has he vacated".
        """
        if len(self.corners) != 4:
            return False
        pts = self._grown(margin_m) if margin_m else self.corners
        return _inside(lon, lat, pts)

    def _grown(self, margin_m: float) -> tuple:
        cx = sum(p[0] for p in self.corners) / 4.0
        cy = sum(p[1] for p in self.corners) / 4.0
        out = []
        for lon, lat in self.corners:
            # Metres per degree, at this latitude. Only used to push a corner
            # outwards by a few metres, so the small-angle approximation is
            # doing no work the exactness above is meant to protect.
            mlat = 111_320.0
            mlon = 111_320.0 * max(math.cos(math.radians(lat)), 1e-6)
            dx, dy = (lon - cx) * mlon, (lat - cy) * mlat
            d = math.hypot(dx, dy) or 1.0
            out.append((lon + (dx / d) * margin_m / mlon,
                        lat + (dy / d) * margin_m / mlat))
        return tuple(out)


def _inside(x: float, y: float, poly) -> bool:
    """Point in polygon, by ray casting. Four corners, so nothing cleverer is
    earned -- and a rectangle from the sim is convex and well behaved."""
    hit = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xx = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x < xx:
                hit = not hit
    return hit


def who_is_on(runway: Runway, contacts, margin_m: float = 10.0) -> list[str]:
    """Which contacts are physically on this strip. Labels, in no order.

    ON THE GROUND ONLY, and that is the whole of the airborne case: an
    aeroplane crossing the threshold at fifty feet is over the runway and not
    on it, and counting him would refuse a take-off to everybody underneath an
    approach. `in_air` is the sim's own flag and carries a third state -- NULL,
    "nobody has asked" -- which is NOT evidence he is down. See `feed.tracks`.
    """
    out = []
    for c in contacts or []:
        if c.get("in_air") is not False:
            continue
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        if runway.holds(float(lat), float(lon), margin_m):
            out.append(c.get("label") or c.get("name") or "")
    return [w for w in out if w]
