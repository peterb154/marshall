"""The aerodromes: where they are, which way the runway points, which end is live.

A field is the thing a Station belongs to and an ApproachProfile lands at, and
it owns the facts that must not be duplicated: elevation, the runway pair, the
ATIS frequency, and its own MSA and MVA tables. `runway_in_use` is here rather
than in the controller because the taxi clearance, the take-off clearance, the
ATIS and the chart must all name the same end -- and they will only do that if
they read it from one place.

WHY `Field_` HAS A TRAILING UNDERSCORE: `dataclasses.field` is imported
throughout `core` and a class called `Field` shadows it in exactly the way that
produces a baffling error three modules away.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from marshall.core.airspace import MSA_SECTORS, MVA_CELLS, msa_for, mva_for
from marshall.core.units import WIND_FROM_DEG

@dataclass
class Field_:
    name: str
    x: float
    z: float
    elevation_ft: int
    runway: int             # landing heading, magnetic
    # THE DESIGNATORS THE MISSION USES, for (runway, its reciprocal).
    #
    #     "Mission defined runway btw, irl plates and dcs might disagree by a
    #      digit or two based on changing mag dev over time."
    #
    # Which is exactly what happens here, and it is why this cannot be derived
    # from `runway` by rounding. Batumi's landing heading is 124 magnetic, which
    # rounds to 12 -- and DCS does call it 12 -- while the current AIP plate
    # says 13/31, because magnetic drift renamed it and the paint caught up.
    # Kobuleti is the same story: 064 magnetic, published 07/25.
    #
    # Rounding the heading gave "runway 12" and "runway 06", which are the
    # numbers on nobody's chart. So the DESIGNATOR is data and the HEADING is
    # geometry, and `runway_in_use` picks an end with the second and names it
    # with the first.
    ends: tuple[int, int] = (0, 0)
    # THE ATIS FREQUENCY, and it belongs to the AERODROME rather than to a
    # controller. An ATIS is not a person on a radio -- it is a recording the
    # field puts on the air -- so it is not a `Station` and nothing monitors it
    # for incoming calls. Zero means this field does not broadcast, which is
    # the normal case for most aerodromes and is handled rather than assumed.
    #
    # ASSIGNED, not published: neither chart we hold gives one. 127.100 and
    # 127.400 are clear of every controller frequency in the theatre and of the
    # beacon channels, which is the only real constraint.
    atis_mhz: float = 0.0
    msa_sectors: list = field(default_factory=list)   # published, the pilot's
    mva_cells: list = field(default_factory=list)     # surveyed, the controller's
    note: str = ""

    def runway_in_use(self, wind_from_deg: float | None = None) -> int:
        """The into-wind end, as a two-digit designator. 07, 13, 25, 31.

        COMPUTED, because it is not a property of the aerodrome:

            "'Runway in use' should probably be computed -- based on weather
             (which is measured from the sim)."

        `runway` is one end's magnetic heading; the other is its reciprocal, and
        which of the two is "in use" is a fact about the WEATHER. Hardcoding it
        meant the departure field's controller had nothing to derive it from and
        guessed -- live, Kobuleti Ground cleared an aircraft to taxi to runway
        25 with the wind at 090, which is the downwind end of his own runway.
        Plausible, wrong, and it would have been flown.

        Ties go to the published end, so a dead calm is stable rather than
        flipping on rounding.
        """
        if wind_from_deg is None:
            wind_from_deg = WIND_FROM_DEG
        into = self.runway
        best_off = abs((wind_from_deg - into + 180) % 360 - 180)
        recip = (self.runway + 180) % 360
        # Strict, so a dead calm keeps the published end rather than flipping.
        if abs((wind_from_deg - recip + 180) % 360 - 180) < best_off - 0.001:
            return self.ends[1]
        return self.ends[0]

    def msa_for(self, bearing_deg: float) -> int:
        """Published MSA -- briefed, charted, and not for vectoring."""
        return msa_for(bearing_deg, self.msa_sectors or None)

    def mva_for(self, bearing_deg: float, range_nm: float | None = None) -> int:
        """The lowest a controller may assign an aircraft here."""
        return mva_for(bearing_deg, range_nm, self.mva_cells or None)


BATUMI_FIELD = Field_(
    "Batumi", -355811, 617386, 32, 124, ends=(13, 31), atis_mhz=127.100,
    msa_sectors=list(MSA_SECTORS),
    mva_cells=list(MVA_CELLS),
    note="Highest terrain 10,623 ft at 23 nm SE. Missed approach turns LEFT.")

# KOBULETI (UG5X). The departure field, and the second aerodrome this system has
# ever had -- which is what turned `station_for` from a list walk into something
# that has to know which airport you mean.
#
# Position and elevation are the sim's own (ARP x/z, 59 ft, agreeing with the
# published chart to the foot). Runway 07 is the into-wind end with the easterly
# we fly, and 064 is its MAGNETIC heading off the chart, which is the frame
# `Field_.runway` is in -- see `BATUMI_FIELD` at 124 for the same thing at the
# other end of the route.
#
# SURVEYED, because an approach is flown here now.
#
# This carried no MSA and no MVA, with a comment saying that was a real gap and
# that the day somebody flew an approach here it should stop them trusting a
# vectoring altitude. That day is this one, so the terrain was asked instead:
# every 5 degrees, every half mile, out to 25 nm, highest ground plus a
# thousand feet rounded up.
#
# THE COARSE SCAN WAS NOT SAFE. A first pass at 10 degrees and 1 nm found
# 8,135 ft; at 5 and a half it found 8,556, and on the western side 2,731
# became 3,760. A peak between two samples is a peak nobody sees, and the
# difference here is a thousand feet of clearance that did not exist.
#
# The shape is Batumi's, one range further north: sea and coastal plain from
# the south-west round through north, and the Lesser Caucasus from 090 to 190
# with 8,556 ft inside 25 miles.
KOBULETI_MSA = [
    (90.0, 190.0, 9600),        # the mountains
    (190.0, 90.0, 4800),        # sea, coast, and the low ground north
]
# The controller's, which are lower than the published MSA because they are
# surveyed per cell rather than per sector. Vectoring west of the field is
# cheap; vectoring east of it is not.
KOBULETI_MVA = [
    (190.0, 90.0, 5.0, 1700),
    (190.0, 90.0, 10.0, 2500),
    (190.0, 90.0, 15.0, 3000),
    (190.0, 90.0, 25.0, 4800),
    (90.0, 190.0, 5.0, 1600),
    (90.0, 190.0, 10.0, 5400),
    (90.0, 190.0, 15.0, 8600),
    (90.0, 190.0, 25.0, 9600),
]

KOBULETI_FIELD = Field_(
    "Kobuleti", -317605, 636704, 59, 64, ends=(7, 25), atis_mhz=127.400,
    msa_sectors=list(KOBULETI_MSA), mva_cells=list(KOBULETI_MVA),
    note="Field elevation 59 ft. Runway 07/25, 2400 m. TACAN 67X KBL, "
         "ILS 111.50 on 07. GCA field: PAR and SRA published.")

# EVERY AERODROME IN THE THEATRE, so `field_named` has something to search and
# a third field is one entry rather than one more place to remember.
FIELDS = (BATUMI_FIELD, KOBULETI_FIELD)


#
#     "Let's move our parked f16s to kobeleti. Let's create a flight plan to fly
#      from kob to batumi."
#
# Two names, written once, because a surprising number of things need to know
# which end of the route a field is on and every one of them was about to
# hardcode it: the mission builder decides which ramp the jets sit on, the comms
# card decides whether a field's controllers are used outbound or inbound, and
# the nav log times the legs between them.
#
# THE SAME SEAT MEANS DIFFERENT THINGS AT THE TWO ENDS, which is the part that
# is easy to miss. Kobuleti Ground is where you start up; Batumi Ground is where
# you taxi in. Kobuleti Departure sends you out; Batumi Approach brings you
# home. A card that describes a station by what the SEAT covers rather than by
# where it sits on this route tells the pilot that his departure controller
# handles recoveries -- true of the man, useless on the day.
DEPARTURE_FIELD = "Kobuleti"
ARRIVAL_FIELD = "Batumi"


def field_named(name: str):
    """The aerodrome a Station belongs to, by name.

    `Station.field` is a string because a Station is data and pointing it at a
    `Field_` would make the two definitions circular. So this is the join, and
    it is here rather than at the call sites: a ground instruction and a
    take-off clearance must read the same runway, and they will only do that if
    they read it from the same place.
    """
    for f in FIELDS:
        if f.name == name:
            return f
    return None
