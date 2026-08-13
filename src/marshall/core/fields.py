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

from marshall.core.airspace import msa_for, mva_for

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
    # THE SAME BROADCAST ON THE OTHER BOX.
    #
    #     "put atis on uhf frequencies also ... and multicast those atis
    #      messages on UHF & VHF"
    #
    # A modern jet carries two radios and a pilot is usually working the
    # controllers on one of them; making him retune the box he is talking on to
    # hear the weather is exactly the friction an ATIS exists to remove. One
    # transmission carries both -- the SRS voice packet has always held a
    # variable-length frequency list, which is the same mechanism that lets a
    # controller be audible to an SCR-522 and a modern radio at once.
    #
    # ASSIGNED, like the VHF pair beside it: no chart we hold publishes one.
    # Chosen clear of the F-16's stock UHF presets, which cluster at 250-270
    # and 305, so setting these on buttons 1 and 2 costs nothing useful.
    #
    # Zero means this field does not broadcast on UHF, and the VHF side is
    # unaffected -- a field with one is not a field with neither.
    atis_uhf_mhz: float = 0.0
    msa_sectors: list = field(default_factory=list)   # published, the pilot's
    mva_cells: list = field(default_factory=list)     # surveyed, the controller's
    # MAGNETIC VARIATION, HERE RATHER THAN AS ONE CONSTANT FOR THE WHOLE WORLD.
    #
    # `units.MAGVAR` is 6.0 -- the Caucasus -- and `geo.GRID_CONVERGENCE_DEG` is
    # 5.74, measured at Batumi, with a comment saying outright that it "belongs
    # to the FIELD" and is "here as a default until the airfield table exists".
    # The airfield table has existed since Kobuleti; the numbers never moved.
    #
    # It costs nothing while there is one map and it is wrong the moment there
    # are two: Nevada is 12 EAST. Applying 6 there puts every magnetic heading a
    # controller says six degrees out -- which no test catches, because every
    # test flies the Caucasus.
    #
    # Zero means "use the theatre default", so nothing that exists today
    # changes and a new field states its own.
    magvar_deg: float = 0.0
    # WHERE IT REALLY IS. Not used to fly anything -- the sim's own projection
    # does that -- but it is what lets a component CHECK that the theatre it was
    # told to run is the map actually loaded. See `theatre.verify`.
    lat: float = 0.0
    lon: float = 0.0
    # The angle between DCS grid north and true north AT THIS FIELD. It varies
    # with longitude across a transverse Mercator, so it is a property of the
    # place and not of the map -- see SCHEMA.md on how it is measured.
    grid_convergence_deg: float = 0.0
    note: str = ""

    def variation(self) -> float:
        """This field's magnetic variation, or the theatre's if it has none."""
        from marshall.core.units import MAGVAR
        return self.magvar_deg or MAGVAR

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

        NO WIND GIVEN MEANS THE MAP'S DECLARED ONE, which is a fallback and not
        an observation -- `atis/` measures the sim and is who should be asking
        this, with what it measured. It used to be `units.WIND_FROM_DEG`, a
        constant for the Caucasus, so a Nevada field with nobody watching the
        weather picked its end in a Georgian easterly (#148).
        """
        if wind_from_deg is None:
            from marshall.core import theatre as _th
            wind_from_deg = _th.declared_wind()[0]
        into = self.runway
        best_off = abs((wind_from_deg - into + 180) % 360 - 180)
        recip = (self.runway + 180) % 360
        # Strict, so a dead calm keeps the published end rather than flipping.
        if abs((wind_from_deg - recip + 180) % 360 - 180) < best_off - 0.001:
            return self.ends[1]
        return self.ends[0]

    def msa_for(self, bearing_deg: float) -> int | None:
        """Published MSA on this bearing -- briefed, charted, not for vectoring.

        `None` WHERE NOTHING IS PUBLISHED, and that is the whole of the fix
        here. It used to read `self.msa_sectors or None`, and the `or None`
        sent an empty grid down to `airspace.MSA_SECTORS` -- which is BATUMI's:
        7,000 and 13,600 feet, surveyed against the Lesser Caucasus. So an
        aerodrome nobody has surveyed inherited a Georgian mountain range,
        silently, and the numbers came back identical to Batumi's byte for
        byte. A field on flat ground is briefed eleven thousand feet for
        terrain a hundred miles away, and a field standing higher than
        Batumi's mountains is briefed under its own ramp.

        The correct code was twenty lines away the whole time and says why:
        `ApproachProfile.min_safe_ft` walks surveyed MVA, then published MSA,
        then platform, and its docstring reads "Defaulting to the module's
        tables instead would hand a new field Batumi's mountains". This is the
        same ladder, on the object that owns the tables.

        An absent minimum altitude is not the same fact as a low one, and a
        caller must be able to tell them apart -- which it cannot when the
        answer is a plausible integer belonging to another continent. #109:
        a picture with no origin renders nothing rather than a guess.
        """
        return msa_for(bearing_deg, self.msa_sectors) if self.msa_sectors else None

    def mva_for(self, bearing_deg: float,
                range_nm: float | None = None) -> int | None:
        """The lowest a controller may ASSIGN an aircraft here, or None.

        A LADDER, not a default -- the same one `ApproachProfile.min_safe_ft`
        walks, and for the same reason. A surveyed MVA if this field has one;
        otherwise its own published MSA, which is higher than it needs to be
        and therefore safe; otherwise nothing, because there is nothing.

        Falling back to the MSA is the field's OWN number and is the honest
        conservative answer. Falling back to `airspace.MVA_CELLS`, which is
        what this did, is another aerodrome's survey: west of an unsurveyed
        field at 4,494 ft it assigned 1,000 ft, three and a half thousand feet
        below the ground, in a transmission a pilot flies in cloud.
        """
        if self.mva_cells:
            return mva_for(bearing_deg, range_nm, self.mva_cells)
        # HIS PUBLISHED MSA, and it is named rather than silently substituted:
        # the caller gets a real minimum for THIS aerodrome, from the only
        # other table this aerodrome has.
        return self.msa_for(bearing_deg)


# THE AERODROMES THAT USED TO BE HERE ARE NOW DATA.
#
# `[[field]]` tables in `config/theatres/<map>.toml`, with their runway
# designators, ATIS frequencies, magnetic variation, MSA sectors and MVA cells.
# Adding an airfield is adding a table -- "we're going to add dozens of
# airfields" used to be a code change.
#
# What stays is `Field_` itself and the lookups over it. See docs/CONFIG.md.


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


# EVERY AERODROME IN THE THEATRE, so `field_named` has something to search and
# a third field is one entry rather than one more place to remember.


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

    AND IT JOINS THE FIXES TOO, which is why the match is case-folded. The two
    catalogues have never agreed on capitals: a fix is `BATUMI` and an
    aerodrome is `Batumi`, so an exact match answered None for the Caucasus and
    a real field for Nevada, where the Tonopah fix happens to be title-cased.
    An approach's datum is a Fix, so anything asking "which aerodrome does this
    procedure arrive at" got a different KIND of answer depending on how
    somebody typed a name into a TOML file.

    There were TWO of this function and they disagreed -- `Theatre.field_named`
    has folded case since it was written -- so which answer you got depended on
    which of two identically-named joins you happened to call. This one is the
    other one now. A name that matches nothing still returns None; the fold can
    only turn a miss into the hit it was meant to be.
    """
    # ASKS THE THEATRE, because the aerodromes are its data now and not this
    # module's. Imported here rather than at the top: `theatre` reads `Field_`
    # from this file, so a module-level import would be a cycle.
    from marshall.core import theatre as _th
    return _th.current().field_named(name)
