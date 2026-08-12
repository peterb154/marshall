"""The places: beacons, turning points and the routes strung between them.

Coordinates are DCS terrain metres, Caucasus: x increases north, z increases
east. A Fix is a PLACE and nothing else -- it has no frequency it controls on
and no procedure attached, which is what separates it from a Station. They were
the same thing while the approach was a beacon letdown and the man you talked
to was the beacon you homed; two aerodromes and a modern station set is what
finally broke them apart.

Two routes live here and they are not the same journey: `SORTIE` is the strike
out to the target and back, `FIXES` is the Kobuleti-to-Batumi transit that is
actually flown. Callers want different ones -- see `steerpoint`.
"""

from __future__ import annotations

from dataclasses import dataclass

from marshall.core.units import CRUISE_ALT_FT

@dataclass
class Fix:
    name: str
    ident: str          # Morse ident, keyed by the beacon
    x: float            # metres north
    z: float            # metres east
    freq_mhz: float | None = None   # None = not a beacon, dead-reckoning only
    sector: str = ""    # the controller who owns this frequency
    note: str = ""
    # WHAT KIND OF STATION is here, if any: "ndb", "tacan", "vor", "vortac",
    # or "" for a point in space that only an inertial platform can find.
    #
    # It is not the same question as `freq_mhz`. Which aircraft can navigate to
    # a fix depends on what sort of station it is, and the answer is not a
    # ladder: the DCS F-16 carries TACAN and an inertial platform and NO ADF, so
    # it cannot home the NDB that a 1944 Mustang homes without difficulty.
    # See atc/equipment.py.
    navaid: str = "ndb"
    # THE SIM'S OWN PROJECTION, when we have it. Optional because a Fix built
    # in a test or by the mission builder has grid metres and nothing else, and
    # None means "ask the sim" exactly as before.
    #
    # Carried so that geometry can be done WITHOUT A RUNNING SIM. Until this,
    # the only thing that could turn a fix into a position was `coord.LOtoLL`
    # over gRPC at bridge start, so "does this terminal area contain its own
    # approach" (#139) was unanswerable in a test. Never computed by us --
    # Caucasus is a transverse Mercator and a flat-earth offset was 7.6 nm
    # wrong at the target area. Seeded into config/theatres/<map>.toml from the
    # sim itself; see core/catalogue.py.
    lat: float | None = None
    lon: float | None = None


# Beacon idents must NOT resemble the letters the ARA-8 keys for homing --
# U (..-), D (-..), A (.-), N (-.). An earlier build used B (-...), one dot from
# a homing D, and the two were indistinguishable in flight. M, S, G, H, O and W
# share no prefix with any of them.
KOBULETI = Fix("KOBULETI", "MG", -317962, 635633, 124.000,
               "Kobuleti Departure", "Field elevation 59 ft. Departure end.")

INITIAL = Fix("INITIAL", "SW", -337949, 596106, 128.000,
              "Batumi Approach",
              "Offshore holding fix. Open water, no terrain in any quadrant.")

BATUMI = Fix("BATUMI", "OS", -355811, 617386, 132.000,
             "Batumi Tower",
             "Field elevation 32 ft. Landing runway 12 (charted 13/31 today -- "
             "magnetic drift renamed it; we fly the period AIP designation).")

KUTAISI = Fix("KUTAISI", "KT", -284887, 683859, None,
              note="Red field. The transit turning point, not a diversion -- "
                   "Batumi is the only blue aerodrome on the map.")

# Where the work is. Not an aerodrome and not a beacon: a point on the ground
# with a name, which is what a target area actually is -- somewhere a controller
# can say out loud and a pilot can find by looking.
#
# The lakes east of Kutaisi, found by asking the terrain rather than by picking
# a coordinate off a map: a surface-type sweep east of the field turned up water
# here and nowhere else nearby, which makes it the one landmark in the valley
# that reads the same from ten thousand feet as it does on a chart.
# N42 17.314 E42 51.676, given rather than derived -- a terrain sweep found a
# lake nearby and picked the wrong one, and somebody who has flown over the
# place beats a surface-type search every time.
TARGET_AREA = Fix("TSUTSNVATI", "", -268955, 713840, None,
                  note="CAS area: the town on the western shore of the lake, "
                       "11 nm east of Kutaisi. Hostile ground. The lake is the "
                       "only water for miles, which makes it the one landmark "
                       "that reads the same at eight thousand feet as it does "
                       "on a chart -- and the town sits on its western edge, "
                       "so a target can be described by where it is rather "
                       "than by a coordinate nobody can see.")

FIXES = [KOBULETI, INITIAL, BATUMI]

# The sortie, as planned rather than as flown: out from Batumi, across to
# Kutaisi, east into the target area, and home. Everything but Batumi is
# hostile, so the route is a there-and-back with no alternate -- which is the
# point of the scenario and the reason fuel is a real number.
# Where the rehearsal flights spawn airborne. Fifteen miles south-west of
# Batumi, which is open sea and thirty-seven miles from Kobuleti -- they used to
# appear directly over the Kobuleti beacon, which was harmless right up until
# that field acquired a battery of 88s. An aeroplane that is shot down while the
# pilot is still finding the throttle is not a test of anything.
AIR_START = Fix("REHEARSAL", "", -375454, 597742, None,
                note="Air-start point for rapid testing: 15 nm south-west of "
                     "Batumi, over water, well clear of the defended fields.")

# The defended fields, and how far out their heavy flak reaches. Data, because
# the controllers need it as much as the chart does: a pilot can ask Center to
# keep him clear, and Center can only do that if it knows they are there.
DEFENDED = [
    ("Kobuleti", -317962, 635633, 6.0),
    ("Senaki",   -281782, 647279, 6.0),
    ("Kutaisi",  -284887, 683859, 6.0),
]

# The sortie, routed round the guns rather than through them.
#
# The direct line to the target flies straight over Kutaisi, which is a short
# conversation with an 8.8 cm battery, and the valley is the only low ground
# going east -- all three defended fields sit in it. So the outbound leg does
# not use the valley at all: off runway 31 to the west, climb over the sea,
# turn north and run up the coast well offshore, and come at the target from
# the north where nobody is shooting. Sampled the whole way: water under the
# entire northbound leg, and 1,652 ft of ground on the run east.
#
# Home is the other way, over the high ground south-east of Kutaisi, which
# trades a climb for fifteen miles of clearance. Coming back the way we came is
# thirty miles longer and the direct line passes 4.4 nm from Kutaisi's guns --
# inside their reach.
FEET_WET = Fix("FEET WET", "", -355811, 595162, None,
               note="Off 31 to the west, over water. Climb here.")
INGRESS = Fix("INGRESS", "", -259507, 595162, None,
              note="52 nm north of Batumi, 12 nm offshore -- water the whole "
                   "way, and north of Kutaisi. Turn east for the target from "
                   "here; this is where the run in starts.")
HOMEBOUND = Fix("EGRESS", "", -318936, 712429, None,
                note="Off the target and heading home, 24 nm south-east of "
                     "Kutaisi. Over the high ground: a climb in exchange for "
                     "15 nm of clearance from every battery.")

SORTIE = [BATUMI, FEET_WET, INGRESS, TARGET_AREA, HOMEBOUND, BATUMI]
SORTIE_LEGS = list(zip(SORTIE, SORTIE[1:]))

# Altitude per leg, and the shape of the sortie is in these numbers rather than
# in the route: go out low where nobody is looking, come home high because the
# way home is over mountains.
#
# The terrain under each leg was sampled from the sim, not guessed:
#
#   1-2  BATUMI to FEET WET        32 ft   -- climbing out over the coast
#   2-3  FEET WET to NORTH          0 ft   -- open water the whole way
#   3-4  NORTH to TSUTSNVATI    1,865 ft   -- the run east
#   4-5  TSUTSNVATI to RIDGE    6,684 ft   -- climbing away from the target
#   5-6  RIDGE to BATUMI        8,832 ft   -- over the top
#
# Five hundred feet over the sea is deliberate and is the whole point of going
# that way: low enough that nobody on the coast has anything to report, and
# there is nothing out there to hit. The run east is as low as the ground
# allows. Coming home the numbers are set by the mountains and not by choice --
# eleven thousand clears the highest ridge on the line by two, which is the
# margin you want when the alternative is a hillside.
SORTIE_ALT_FT = [2000, 500, 3000, 9000, 11000]


def leg_altitude(i: int) -> int:
    """Planned altitude for leg i (0-based), or cruise if the route is shorter."""
    if 0 <= i < len(SORTIE_ALT_FT):
        return SORTIE_ALT_FT[i]
    return CRUISE_ALT_FT


def steerpoint(fix, route=None) -> int:
    """Which numbered point on today's route this is, or 0 if it is not on it.

    `route` DEFAULTS TO THE STRIKE SORTIE and not to the flown transit, which
    looks backwards and is deliberate. Two different journeys exist now --
    `SORTIE` out to the target and back, `FIXES` from Kobuleti to Batumi -- and
    the callers want different ones: the briefing and the radio talk about the
    sortie's steerpoints, the nav log times the transit's. Changing the default
    would silently renumber every steerpoint the controller says out loud, which
    is the sort of change that is only ever noticed in the air.

    Numbers because a radio is a bad place for proper nouns. "Steerpoint two"
    survives Whisper, an accent and a bad channel; "FEET WET" comes out as
    "feet wet" if you are lucky and "fee twet" if you are not, and TSUTSNVATI
    has no chance at all. The names stay for the chart, where a pilot is
    reading rather than listening -- both, and each where it works.
    """
    for i, f in enumerate(route if route is not None else SORTIE):
        if f is fix or f.name == fix.name:
            return i + 1
    return 0


def sortie_points() -> list[tuple[int, Fix]]:
    """(number, fix) down the route, which is how it should be read out."""
    return list(enumerate(SORTIE, start=1))

# The route, in order. INITIAL to BATUMI is deliberately runway heading, so
# rolling out of the turn inbound puts you on the approach course already.
LEGS = [(KOBULETI, INITIAL), (INITIAL, BATUMI)]
