"""Single source of truth for the 362nd blind-flying mission.

Both the mission and the kneeboard are generated from this file. That is the
whole point: if the beacon positions live in the .miz builder and the charts are
drawn somewhere else, moving a beacon two miles silently makes the plate lie to
the flight. Here they cannot disagree.

Coordinates are DCS terrain metres, Caucasus: x increases north, z increases
east. Speeds are MPH because the P-51's airspeed indicator is.
"""

import math

from marshall.core import geo as _geo
from dataclasses import asdict, dataclass, field, fields

NM = 1852.0
MPH_PER_KT = 1.15078

# Caucasus magnetic variation, degrees EAST. The compass reads magnetic; every
# heading the pilot actually flies has to be corrected. "East is least" -- east
# variation is subtracted from true.
MAGVAR = 6.0

# Briefed conditions. Wind is the direction it blows FROM.
CRUISE_TAS_MPH = 220.0
CRUISE_ALT_FT = 5000
# FIVE KNOTS FROM THE SOUTH, and much gentler than what came before.
#
# It was 20 mph from 270 -- a stiff, near-direct crosswind on runway 13, which
# is a fine thing to fly against once the procedure works and a poor thing to
# debug an approach in. Every heading correction the controller gave had a wind
# component buried in it, so "he put me left of course" and "I drifted left of
# course" looked identical from both ends.
#
#     "wind should be much much less aggressive. Let's just go with 5 kn from
#      the south"
#
# Changed HERE and nowhere else on purpose: the nav log's timed legs, the
# plate, the mission file and the controller's landing clearance all read this
# one number, so they cannot disagree about it.
WIND_FROM_DEG = 180.0
WIND_MPH = 5.0 * 1.15078          # five knots, in the mph this file works in

# Altimeter setting. Briefed, written into the mission, and passed on radar
# contact -- a pilot who never gets one is flying on whatever was in the
# Kollsman window when he spawned, and every advisory altitude the controller
# reads him is measured against a different datum than the one he is holding.
# DCS stores it in millimetres of mercury; aircrew are given inches, and the
# two must come from one number or they drift.
QNH_MMHG = 760.0
QNH_INHG = QNH_MMHG / 25.4          # sea level: the altimeter reads elevation
                                    # on the ground

# Near sea level the atmosphere loses about this much pressure per foot of
# climb. Enough to convert a field's elevation into the pressure difference
# between QNH and QFE, which is all this is used for.
INHG_PER_FT = 0.00108


def qfe_inhg(field_elev_ft: float, qnh_inhg: float = 0.0) -> float:
    """Field-level pressure: set this and the altimeter reads ZERO on the deck."""
    return (qnh_inhg or QNH_INHG) - field_elev_ft * INHG_PER_FT


def altimeter_spoken(inhg: float = 0.0) -> str:
    """The setting as a controller says it: "two niner niner two"."""
    digits = f"{(inhg or QNH_INHG):.2f}".replace(".", "")
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "niner"}
    return " ".join(words[d] for d in digits)

# The inbound flight this mission expects, for the generated plate (Whisper prime
# + a hint to the controller). Any pilot may call in with their own callsign; the
# controller correlates by position, not by expecting this one. build.py names the
# flight group from the leading word.
FLIGHT_CALLSIGN = "Pony 1-1"

# Every flight name that can appear on this mission's ramp. Knowable in advance,
# which matters: the transcriber is primed with the callsigns it has HEARD, so
# without this the first call a pilot makes -- the one that establishes who he
# is -- is the one call with no priming behind it. A garbled first callsign does
# not merely mis-transcribe a word; it invents an aeroplane and gives it a place
# in the holding stack.
#
# The mission builder takes its flight names from here, so the ramp and the
# transcriber cannot disagree about who is flying.
SQUADRON_CALLSIGNS = ("Pony", "Hammer", "Spit", "Whistler")
# How many aircraft that flight brings. A formation is worked as ONE entity
# until it reaches the holding fix, then broken up into individually-sequenced
# singles -- so this number decides how many levels the stack has to give away.
FLIGHT_SIZE = 4


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


def ias_mph(tas_mph: float, alt_ft: float) -> int:
    """Indicated airspeed for a true airspeed at a height.

    What the pilot flies is the needle, and the needle reads less than the
    truth as the air thins -- about two per cent per thousand feet, which is
    the rule of thumb every pilot carries and is close enough well below the
    tropopause. Down at five hundred feet over the water they are the same
    number; coming home at eleven thousand they are thirty apart, and a nav log
    quoting only true airspeed asks the pilot to do that sum himself while
    flying an aeroplane.
    """
    return int(round(tas_mph / (1.0 + 0.02 * (alt_ft / 1000.0))))


def leg_altitude(i: int) -> int:
    """Planned altitude for leg i (0-based), or cruise if the route is shorter."""
    if 0 <= i < len(SORTIE_ALT_FT):
        return SORTIE_ALT_FT[i]
    return CRUISE_ALT_FT


def steerpoint(fix) -> int:
    """Which numbered point on today's route this is, or 0 if it is not on it.

    Numbers because a radio is a bad place for proper nouns. "Steerpoint two"
    survives Whisper, an accent and a bad channel; "FEET WET" comes out as
    "feet wet" if you are lucky and "fee twet" if you are not, and TSUTSNVATI
    has no chance at all. The names stay for the chart, where a pilot is
    reading rather than listening -- both, and each where it works.
    """
    for i, f in enumerate(SORTIE):
        if f is fix or f.name == fix.name:
            return i + 1
    return 0


def sortie_points() -> list[tuple[int, "Fix"]]:
    """(number, fix) down the route, which is how it should be read out."""
    return list(enumerate(SORTIE, start=1))

# The route, in order. INITIAL to BATUMI is deliberately runway heading, so
# rolling out of the turn inbound puts you on the approach course already.
LEGS = [(KOBULETI, INITIAL), (INITIAL, BATUMI)]


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


@dataclass
class Station:
    """A controller: a name, a frequency, and the phase of flight he owns.

    Distinct from a Fix on purpose. A Fix is a place; a Station is a person on a
    radio. They were the same thing while the approach was a beacon letdown --
    the controller had to sit on the beacon you were homing, because the ARA-8
    tunes and homes on one frequency at a time. Under radar the pilot navigates
    by nothing at all, so a frequency is free to be just a frequency, and the
    controllers can be split the way real ones are: Center, Approach, Tower.
    """
    name: str
    freq_mhz: float
    role: str = ""              # his PRIMARY job, and what he is called
    # Everything else he also works. A field this size does not staff a seat per
    # phase of flight: one man has ground and tower, another has departure and
    # approach, and that is how it is done for real. It matters because a
    # departing aircraft and an arriving one then share a controller and a
    # frequency, which is where sequencing gets interesting -- he is fitting
    # departures into the airspace he is recovering through.
    #
    # Empty means "just the primary role", so the simple case stays simple.
    also: tuple = ()
    # The Polly voice this controller speaks with. On the STATION rather than
    # passed to the bridge, because a voice handed in separately drifts from the
    # identity it belongs to -- you end up with Tower's manner in Center's voice
    # and no single place that says which is which. Changing sector should sound
    # like meeting a different person, which is the point of splitting them.
    voice: str = "Matthew"


# From the Batumi AIP (AD 2.UGSB-IAC-12-ILSy): APP 124.425, TWR 118.600 --
# rounded to whole megahertz, because a WW2 set tunes crystal channels and
# quarter-megahertz spacing is a jet-age convention. Approach lands on 124.000,
# which is also one of the stock preset channels both WW2 airframes ship with,
# so it works even where a preset override does not apply.
#
# There is no published Center for the region, so Georgia Center keeps a stock
# channel and is the one frankly invented number here.
#
# CENTER IS NOT A FIELD'S CONTROLLER. Approach and Tower belong to an aerodrome;
# a Center owns a region and hands you between aerodromes, so there is one for
# the whole theatre rather than one per airfield.
CENTER = Station("Georgia Center", 139.000, "center", voice="Brian")
APPROACH = Station("Batumi Approach", 124.000, "approach",
                   also=("departure",), voice="Matthew")
TOWER = Station("Batumi Tower", 118.000, "tower",
                also=("ground", "delivery"), voice="Joey")

# The mission commander. Not a new kind of machine -- a controller with a wider
# scope, which is why it is a Station like the others: it has a frequency, a
# voice, and aircraft it works. What it does differently is give a flight a JOB
# rather than a heading, and it is the only one here that does not care where
# the runway is.
#
# Fourth preset deliberately. A period set has four buttons and the other three
# are spoken for, so this is the last one available -- which is also true of a
# real WW2 cockpit and is a reasonable constraint to design inside.
OVERLORD = Station("Sentry", 131.000, "overlord", voice="Kimberly")

STATIONS = [CENTER, APPROACH, TOWER, OVERLORD]


@dataclass
class Field_:
    name: str
    x: float
    z: float
    elevation_ft: int
    runway: int             # landing heading, magnetic
    msa_sectors: list = field(default_factory=list)   # published, the pilot's
    mva_cells: list = field(default_factory=list)     # surveyed, the controller's
    note: str = ""

    def msa_for(self, bearing_deg: float) -> int:
        """Published MSA -- briefed, charted, and not for vectoring."""
        return msa_for(bearing_deg, self.msa_sectors or None)

    def mva_for(self, bearing_deg: float, range_nm: float | None = None) -> int:
        """The lowest a controller may assign an aircraft here."""
        return mva_for(bearing_deg, range_nm, self.mva_cells or None)


BATUMI_FIELD = Field_(
    "Batumi", -355811, 617386, 32, 124,
    msa_sectors=list(MSA_SECTORS),
    mva_cells=list(MVA_CELLS),
    note="Highest terrain 10,623 ft at 23 nm SE. Missed approach turns LEFT.")


@dataclass
class AtcCapability:
    """What the controller can DO on a given mission -- the dial between a real,
    capable controller and a period handicap.

    Defaults describe a REAL controller: it has radar, it separates on radar, it
    talks like a modern controller. A 1944-style mission dials the handicaps in
    (radar off, no DME, blind procedural separation, period phraseology) -- the
    Batumi beacon letdown is one such configured flavour, not the baseline. The
    bridge reads this to generate the agent's prompt and to decide whether to feed
    it a radar picture at all, so "handicap the ATC for this mission" is data here,
    not a prompt rewrite.
    """
    radar: bool = True          # sees aircraft positions -> can give range/vectors
    dme: bool = False           # the PILOT's aircraft carries DME (the P-51 doesn't)
    separation: str = "radar"   # "radar" | "procedural" (blind assigned-altitude stack)
    era: str = "modern"         # phraseology flavour: "modern" | "ww2"


def _round_up(value: int, step: int) -> int:
    return -(-int(value) // int(step)) * int(step)


@dataclass
class ApproachProfile:
    """One field's approach, in one place.

    The controller (atc.py) is field-agnostic: it reads the beacon, the
    controller name and the altitude ladder from here and nothing else. The
    plate (build_plate.py) reads the same beacon and ladder plus the geometry
    it needs to draw. Change a stack level here and both the clearances and the
    plate's table move together, because they share this one definition.
    """
    controller: str                 # radio callsign, e.g. "Batumi Approach"
    beacon: Fix                     # the approach beacon (ident + freq)
    outer_hold: Fix                 # escape-valve fix for repeated misses

    # Where the flight is worked BEFORE it reaches the beacon. None means one
    # controller owns the whole arrival.
    #
    # This exists because of a hard constraint of the aircraft, not of ATC: a
    # WW2 set has four preset channels and the ARA-8 homes only on the frequency
    # it is tuned to. So the pilot cannot listen to a controller on one channel
    # while homing a beacon on another -- and therefore **a phase's controller
    # must live on the beacon flown in that phase**. Enroute to INITIAL he is on
    # INITIAL's frequency, so that is where Approach talks to him; the moment he
    # turns for the letdown he is homing BATUMI, so Tower owns him from there.
    # Getting this wrong is not cosmetic: it puts the controller on a channel the
    # pilot physically cannot be listening to.
    arrival_fix: Fix | None = None

    # The holding stack is GENERATED, not a fixed list. A stack is just 1,000-ft
    # increments from the base, and how many you need depends on who shows up --
    # a four-ship breaking up for individual approaches wants four levels on its
    # own. Hard-coding four made a formation break-up a capacity problem the
    # controller had to refuse, which is not a thing a real controller does; he
    # just stacks them higher. The only genuine ceiling here is OXYGEN: a P-51D
    # holding for a long recovery has no business above 10,000 ft.
    hold_base_ft: int = 4000        # bottom of the stack -- first arrival gets this
    # How thick the cloud is above the briefed base. Only needed to work out
    # where the tops are, and the tops are what decide whether a hold is
    # possible at all on a vectored approach -- see stack_ft.
    cloud_thickness_ft: int = 3000
    vmc_margin_ft: int = 1000       # clear air above the tops to hold in
    hold_step_ft: int = 1000        # vertical separation between holders
    hold_top_ft: int = 10000        # ceiling (P-51: oxygen, not airspace)

    # What this field's controller can do. Default is a real, radar-equipped
    # controller; set it per mission to handicap him (see AtcCapability).
    atc: AtcCapability = field(default_factory=AtcCapability)

    # --- surveillance-radar approach ------------------------------------
    # The controller navigates: he vectors the aircraft onto the final approach
    # course and talks it down to minimums, calling range each mile. Needs
    # nothing in the cockpit but a radio, so it works in any aeroplane -- unlike
    # the beacon letdown, which needs the ARA-8 and therefore a P-51D-30.
    kind: str = "ndb"               # "ndb" | "asr" | "ils" | "visual"

    # WHERE THE CONTROLLER STOPS. This is the only axis on which the approaches
    # we care about actually differ, and naming it is what stops the hardest one
    # becoming the shape the others have to fit.
    #
    # All three are the same job up to the intercept: sequence him, vector him
    # onto the final approach course, watch the ground track. Every bit of that
    # is geometry and none of it knows what kind of approach it serves. What
    # differs is who owns the aeroplane afterwards.
    #
    #   "talkdown"  the controller never stops -- he navigates the aircraft to
    #               the missed approach point, calling range every mile and
    #               reading advisory heights, because there is no glidepath and
    #               nothing in the cockpit to fly. This is the ASR, and it is
    #               the hardest of the three for the controller by a distance.
    #
    #   "intercept" the controller stops at the intercept. Once established the
    #               AIRCRAFT flies it -- localiser and glideslope -- and the
    #               controller's remaining job is to say so and get off the air.
    #               This is the ILS, and for the controller it is mostly
    #               sequencing. Calling ranges down an ILS is chatter over a
    #               pilot who is busy and already has better information.
    #
    #   "visual"    the controller stops when the pilot reports the field. Until
    #               then it is a vector towards a close base; after, it is the
    #               pilot's approach and the controller's spacing.
    #
    # The difference is three words, and the alternative -- an engine per
    # procedure -- is three copies of the geometry that will drift apart.
    guidance: str = "talkdown"
    # From the AIP plate. IF: established on the course, level, by 11 nm. FAP:
    # 6 nm, still 2,000 -- the descent begins HERE, not at the IF. The segment
    # between them is deliberately level, which is what makes the approach
    # flyable; a single gradient from the gate has him descending the whole way.
    final_intercept_nm: float = 11.0     # the IF -- established by here
    fap_nm: float = 6.0                  # descent begins
    map_nm: float = 0.6             # missed approach point, range from the TOUCHDOWN point
    # WHERE TOWER TAKES HIM, on any approach.
    #
    #     "Tower should handle inside a xx 2?? mile radius.. even on ASR
    #      approach."
    #
    # A number rather than a rule derived from the procedure, because it is a
    # fact about the FIELD -- whose airspace the last two miles are -- and not
    # about which aid the pilot is flying. See `hands_to_tower_nm`.
    # FIVE, not two. Two put the boundary inside the talkdown -- the controller
    # is still reading ranges every mile at two miles, so the pilot changes
    # frequency in the middle of the procedure flying his approach. Five is
    # about where real practice puts it (the final approach fix), and it leaves
    # the ASR question open rather than answering it badly:
    #
    #     "Let's do 5 nm then. We'll fix ASR approach later"
    tower_takes_nm: float = 5.0
    # How far the TOUCHDOWN POINT is from the reference the radar measures
    # against, along the approach course. Positive means the aircraft reaches
    # the touchdown point FIRST.
    #
    # It is not a nicety. The radar reference at Batumi is the runway CENTRE --
    # `Airbase:getRunways()` returns the centre and route.py's BATUMI fix is that
    # point to within a metre -- so every range call, and with it the whole
    # descent profile, was aimed half a mile beyond where the wheels go:
    #
    #     "I was always too high because he's trying to get me to zero at
    #      runway center point, not threshold."
    #
    # Half the runway length. Batumi's is 2,070 m, so 0.559 nm.
    touchdown_offset_nm: float = 0.0
    # GRID CONVERGENCE: how far the sim's idea of north is from true north here.
    #
    # DCS reports an aircraft's heading in its own x/z grid, which is a
    # transverse Mercator, while radar RADIALS come from lat/lon and are true.
    # Mixing them is what drew every centreline six degrees off. The radials
    # were fixed by putting the course in the true frame; this is the other
    # half, because a HEADING arrives in the grid frame too.
    #
    # Measured, like everything else here: the geodesic bearing between the two
    # runway thresholds is 311.30, and `getRunways().course` for the same runway
    # is 305.56.
    grid_convergence_deg: float = 0.0
    approach_hands_over_nm: float = 25.0   # Center gives him to Approach here
    # The initial approach fix: where he must be established, on course and at
    # iaf_alt_ft, before the approach proper begins. A published fix rather than
    # a computed one -- the vectoring used to aim at a "join point" it invented
    # and moved, which is how a pilot ended up being turned away from the field,
    # orbiting, and vectored out to sea on three separate sorties.
    iaf: Fix | None = None
    iaf_alt_ft: int = 2000
    field_thr_elev_ft: int = 0   # runway threshold, which is lower than the ARP

    # The real published chart this profile is transcribed from, if we have it.
    # Scanned plate under kneeboard/plates/, and the chart's own name so a
    # disagreement can be traced back to a page of a real document. Optional:
    # a field with no scan still flies, it just has no scan on the kneeboard.
    plate_png: str = ""
    chart_name: str = ""

    # Which pressure datum this field works to, and therefore what every
    # altitude in this profile MEANS.
    #
    # "QNH" is sea-level pressure: set it and the altimeter reads elevation on
    # the ground, so the numbers are altitudes above the sea. "QFE" is field
    # pressure: the altimeter reads zero on the runway, so the numbers are
    # heights above the field. Ex-Soviet fields, Batumi among them, are worked
    # to QFE.
    #
    # At a 32-foot field the two settings differ by 0.03 inches and it looks
    # like pedantry. It is not: the DATUM decides whether "two thousand" means
    # two thousand above the sea or two thousand above the runway, and at a
    # field a few thousand feet up those are different places. Getting it wrong
    # is a whole approach flown at the wrong height.
    altimeter_datum: str = "QNH"

    # The plate's own descent table: (range_nm, altitude_ft), read straight off
    # the chart. Published data beats a computed gradient -- our derivation came
    # out at 315 ft per mile against the chart's 325, which is fifty feet by
    # short final, and there is no reason to be fifty feet out from a number
    # somebody already printed. It also settles what "3 degrees" is measured
    # from, which is the sort of thing a derivation quietly gets wrong.
    #
    # A field with no table falls back to the gradient joining its published
    # fixes, so this is an improvement where we have the chart and not a
    # requirement for having one.
    descent_table: list = field(default_factory=list)
    # Minimum safe altitude per quadrant around the field. Vectoring is done at
    # platform, and platform is only safe where the ground is low -- at Batumi
    # that is the sea to the north-west and nowhere else. A controller who
    # vectors on geometry alone will happily turn an aircraft over eleven
    # thousand feet of Caucasus at two thousand, which is exactly what a pilot
    # caught in flight: "he's going to fly me into the mountains here, if I were
    # IMC right now."
    msa_sectors: list = field(default_factory=list)
    mva_cells: list = field(default_factory=list)

    def min_safe_ft(self, bearing_deg: float,
                    range_nm: float | None = None) -> int:
        """The lowest altitude that may be ASSIGNED out on this bearing.

        The MVA, not the published MSA -- see the note on the two tables above.
        Never below platform, since platform is the approach's own floor.

        A profile carries its OWN tables and falls back down a ladder rather
        than borrowing: a surveyed MVA if it has one, otherwise the published
        MSA, which is conservative but safe, otherwise platform. Defaulting to
        the module's tables instead would hand a new field Batumi's mountains,
        and a field on flat ground would be vectored eleven thousand feet up
        for terrain a hundred miles away.
        """
        if self.mva_cells:
            return max(self.platform_ft,
                       mva_for(bearing_deg, range_nm, self.mva_cells))
        if self.msa_sectors:
            return max(self.platform_ft, msa_for(bearing_deg, self.msa_sectors))
        return self.platform_ft

    def briefed_msa_ft(self, bearing_deg: float) -> int:
        """The published figure, for the plate and for what the pilot is told."""
        return msa_for(bearing_deg, self.msa_sectors) if self.msa_sectors else 0
    # The controllers who work this approach, enroute inwards. Empty falls back
    # to the beacon-derived stations the NDB letdown uses.
    stations: list[Station] = field(default_factory=list)
    # Magnetic variation at this field, degrees EAST. On the profile rather than
    # a module constant because it belongs to a PLACE: point route.py at another
    # theatre and the variation changes with it, and a controller who carries the
    # Caucasus figure to the Gulf draws every centreline wrong.
    #
    # Measured, not looked up: taxi an aeroplane onto the runway centreline,
    # stop at both ends, and take the bearing between the two fixes. Batumi's
    # 13 threshold measured 131.0 TRUE against a briefed 124 magnetic.
    magvar_deg: float = MAGVAR
    # The final approach course in TRUE, when somebody has actually MEASURED it.
    #
    # Deriving it from the briefed magnetic course plus the variation is a good
    # estimate and it is still an estimate: at Batumi it gives 130 where the
    # runway measures 131.0. One degree is 0.17 nm at ten miles, which is inside
    # the noise -- but the derivation is only as good as a variation figure
    # nobody has checked for this theatre and epoch, and this is the number every
    # cross-track in the system hangs off.
    #
    # None means "derive it". A figure here means somebody MEASURED it in the
    # sim -- and measured it well, which is a real caveat: the first attempt
    # took the bearing between two points an aeroplane stopped at, and came out
    # 5 degrees wrong because it had only covered 3,900 ft of an 8,000 ft runway
    # and 100 ft of lateral error over that baseline is 1.5 degrees. The F10
    # ruler and the aircraft's own radar heading while lined up agreed with each
    # other and not with it. Prefer those two.
    final_crs_true_measured: float | None = None

    @property
    def vectored(self) -> bool:
        """True when the CONTROLLER owns navigation.

        The two are mutually exclusive and must never be mixed: a homing adapter
        points the nose at the beacon, so a pilot handed a vector heading loses
        the only course reference he has. Either he navigates and we watch, or we
        navigate and he stops homing.
        """
        return self.kind == "asr"

    # Used only by the plate, not by ATC (it is blind and cannot see the field).
    # THE COURSE A CONTROLLER SAYS OUT LOUD, which is MAGNETIC, because that is
    # what the pilot reads off his compass and sets on his gyro.
    #
    # It is NOT the number the geometry may compute with. Radar reports position
    # and heading in TRUE, and comparing a magnetic course against a true bearing
    # draws the extended centreline in the wrong place -- by exactly the
    # variation, seven degrees here, which is 1.2 nm of cross-track at ten miles
    # and a quarter of a mile on short final. Use `final_crs_true` for anything
    # geometric. See `magvar_deg`.
    final_crs: int = 0              # inbound = runway heading, MAGNETIC
    hold_turns: str = "RIGHT"
    # The racetrack a holding aircraft flies when it has nothing to hold OVER.
    # Given as two headings because headings are the one thing every aeroplane
    # can fly, navaid or not. Aligned with the approach so that leaving the hold
    # points him roughly the right way; the inbound leg is the reciprocal.
    hold_outbound_hdg: int = 180
    # How long each leg of a timed hold takes, and which way he turns.
    #
    # An aeroplane with no navaid cannot hold OVER anything, so the hold is a
    # shape and a clock: fly this heading for this long, turn, fly the
    # reciprocal for this long, repeat. Without the clock he has a heading and
    # no idea when to turn, which is what he was being given.
    #
    # One minute is the standard leg at or below 14,000 ft, and it is the right
    # choice here for a reason beyond convention: it keeps him in a small piece
    # of sky. A two-minute leg at 200 knots is nearly seven miles of racetrack,
    # and the whole point of holding him is that the controller knows roughly
    # where he is. Put to the test pilot, who flies it: "1 min hold below 14k is
    # fine." Confirmed rather than assumed, which is the difference between a
    # default and a decision.
    #
    # Right turns, also standard, and also the safer default -- everybody in the
    # stack turning the same way keeps the pattern predictable when the only
    # thing separating them is altitude.
    hold_leg_minutes: float = 1.0
    hold_turns: str = "right"
    field_elev_ft: int = 0
    runway: str = ""

    # --- the letdown, no DME. -------------------------------------------
    # Cleared, you descend to the platform on the reversal (out over water),
    # then -- only while established on the beam (steady tone) -- down to MDA.
    # Station passage (the cone of silence over the field beacon) is the missed
    # approach point: no DME, no timing. Because the field is coastal and at sea
    # level, the altimeter reads a true height and there is nothing but water
    # under the whole approach, so MDA can sit low.
    platform_ft: int = 2000         # level here on the reversal before the beam
    # Pattern speed in MPH, because a WW2 USAAF airspeed indicator reads MPH and
    # the number the pilot flies has to be the number we brief. This was
    # `speed_kt = 240` and was divided into nautical miles as if it were knots,
    # which stretched every derived distance by 15% -- the same trap solve_route
    # already carries a comment about.
    speed_mph: int = 240
    # Approach speed. A separate number because the descent rate falls out of
    # it and nothing else, and it is bounded from BOTH ends. Too fast and the
    # path becomes a dive: 240 mph on three degrees is eleven hundred feet a
    # minute. Too slow and the aeroplane will not fly it -- a Mustang is unhappy
    # below about 130 and 150 is marginal, which is what an earlier value here
    # asked for. 200 is a speed the airframe is comfortable at, and it is also
    # about the floor for anything modern, so it generalises.
    final_speed_mph: int = 200
    descent_fpm: int = 500          # never steeper than this

    @property
    def speed_kt(self) -> float:
        """Pattern speed in knots -- i.e. nautical miles per hour, which is what
        every distance here is measured in."""
        return self.speed_mph / MPH_PER_KT

    @property
    def final_speed_kt(self) -> float:
        """Approach speed in knots, for the same reason."""
        return self.final_speed_mph / MPH_PER_KT

    def speed_kt_at(self, along_nm: float, established: bool = True) -> float:
        """The speed he should be doing this far down the approach.

        One place to ask, so the descent gradient, the mission's AI tasking and
        anything a controller says about speed cannot drift apart. The
        reduction is asked for a little before the final approach point rather
        than at it -- an aeroplane does not slow down instantly, and arriving at
        the point where the descent starts still doing pattern speed is how the
        descent becomes a dive.
        """
        # The reduction belongs at the INTERMEDIATE FIX, not at the point where
        # the descent starts. Two reasons, and the second is the one the sim
        # showed. Comfort first: a pilot who arrives at the final approach point
        # still doing pattern speed has to dive to stay on the path, and 240 mph
        # on a three degree gradient is eleven hundred feet a minute. But also,
        # decelerating and descending at once is asking for both at the expense
        # of each -- flown live, an aircraft told to slow two miles before the
        # point managed 478 fpm of the 690 the path wanted, and arrived six
        # hundred feet high. Slowing at the fix buys five level miles to settle,
        # so the descent starts from a stable aeroplane already at approach
        # speed and only has to do one thing.
        #
        # Inbound and actually ON the approach: along-track alone is not enough,
        # since an aircraft abeam the field four miles off the centreline has a
        # small along-track and is nowhere near final. Negative means past the
        # field, same answer.
        if established and 0 < along_nm <= self.final_intercept_nm:
            return self.final_speed_kt
        return self.speed_kt

    # MDA is not chosen freely: it must sit just below the briefed cloud base so
    # that levelling at minimums actually reveals the runway. Ceiling and MDA
    # move together -- the mission generator reads the same ceiling for weather.
    ceiling_ft: int = 400           # briefed cloud base for this mission
    breakout_ft: int = 100          # MDA this far below the ceiling
    # Never lower than the field plus this, whatever the weather says. The
    # figure is a property of the APPROACH TYPE, not of the field: how low you
    # may go depends on how precisely the procedure knows where you are.
    #
    # An ILS knows within feet and gets a decision height around 200. A
    # surveillance radar approach knows where you are to the width of a radar
    # return and has no vertical guidance at all -- the controller reads
    # advisory heights off a table and the pilot descends at his own rate -- so
    # its minima are far higher, five hundred feet at the very least and often
    # closer to a thousand.
    #
    # This mattered: the Batumi profile was transcribed from an ILS plate and
    # inherited its minima, so a radar approach was being flown to 300 feet.
    # That is below the chart's own obstacle clearance altitude of 687, on a
    # procedure with none of the ILS's precision.
    min_hat_ft: int = 150

    # Missed approach (Batumi real AIP: straight to 800', LEFT to 330', 3000').
    missed_straight_ft: int = 800
    missed_turn: str = "LEFT"
    missed_hdg: int = 330
    missed_climb_ft: int = 3000     # below the stack; ATC re-sequences from here

    @property
    def final_crs_true(self) -> float:
        """The final approach course as RADAR sees it.

        Everything geometric -- cross-track, along-track, intercept headings,
        "is he flying the approach" -- happens in true, because that is the
        frame the sim reports positions and headings in. Only the spoken number
        is magnetic.
        """
        if self.final_crs_true_measured is not None:
            return self.final_crs_true_measured % 360
        return (self.final_crs + self.magvar_deg) % 360

    @property
    def mda_ft(self) -> int:
        """Lowest he may go before the runway has to be in sight.

        The weather can only ever raise it. Briefing a low cloud base does not
        buy a lower minimum -- it just means he is more likely to go missed,
        which is the point of a hard mission.
        """
        return max(self.field_elev_ft + self.min_hat_ft,
                   self.ceiling_ft - self.breakout_ft)

    @property
    def missed_ft(self) -> int:     # what ATC assigns a go-around
        return self.missed_climb_ft

    @property
    def inbound_descent_nm(self) -> float:
        """Track needed to lose platform->MDA at the descent limit. The inbound
        beam must be at least this long or you cannot be down by station
        passage -- which is the plate's constraint on the racetrack size."""
        minutes = (self.platform_ft - self.mda_ft) / self.descent_fpm
        return self.speed_kt / 60 * minutes

    @property
    def final_approach_sec(self) -> float:
        """Seconds from established inbound on the beam to station passage -- the
        missed approach point. DCS produces no usable cone of silence, so the MAP
        is flown on a WATCH from beacon-inbound: the pilot times it (this goes on
        the plate) and ATC times the same number to call the missed as backup.
        One value, both readers, so the watch and the controller never disagree."""
        return self.inbound_descent_nm / self.speed_kt * 3600

    def station(self, enroute: bool = False, banished: bool = False) -> tuple[str, float]:
        """(controller name, frequency) for a phase of the arrival.

        Under radar this is an ordinary sector split -- Center has him enroute,
        Approach works him inbound, Tower takes the landing -- because a vectored
        pilot navigates by nothing and a frequency is free to be just a
        frequency.

        On a beacon letdown it is not free. The ARA-8 homes on whatever the set
        is tuned to, so the controller has to sit on the beacon being flown in
        that phase, and the "station" is derived from the fix instead.
        """
        if self.stations:
            # By ROLE, not by position in the list. Picking the last one was
            # fine while the list ended at Tower, and quietly wrong the moment a
            # mission commander was appended -- it would have sent a pilot to
            # land on the overlord's frequency. A list order is not a fact about
            # who works an arrival.
            if enroute or banished:
                s = self.station_for("center") or self.stations[0]
            else:
                s = (self.station_for("tower") or self.station_for("approach")
                     or self.stations[0])
            return s.name, s.freq_mhz
        if banished:
            fix = self.outer_hold
        elif enroute and self.arrival_fix is not None:
            fix = self.arrival_fix
        else:
            fix = self.beacon
        return (fix.sector or self.controller,
                fix.freq_mhz if fix.freq_mhz else 0.0)

    def station_for(self, role: str) -> Station | None:
        """Who works this phase of flight.

        Primary role first, then anyone who also covers it -- so asking for
        "departure" finds Approach at a field where the two share a seat, and
        would find a dedicated Departure controller at one where they do not,
        without either caller knowing which kind of field it is.
        """
        for s in self.stations:
            if s.role == role:
                return s
        for s in self.stations:
            if role in getattr(s, "also", ()):
                return s
        return None

    def station_on(self, freq_mhz: float) -> Station | None:
        """Who the controller IS on this frequency.

        The bridge listens on every channel at once, which is a convenience of
        the implementation and not something the pilot should ever be able to
        hear. Without this the same voice answers as "Batumi Approach" on
        Center's frequency, and the sector split is decoration.
        """
        for s in self.stations:
            if abs(s.freq_mhz - freq_mhz) < 0.001:
                return s
        return None

    def handoff_from(self, freq_mhz: float, range_nm: float) -> Station | None:
        """The next controller, when this one is done with him.

        Range-based because that is what a radar handoff actually keys on: a
        Center works the enroute leg and gives him to Approach when he is close
        enough to be worked into the pattern; Approach turns him over to Tower
        once he is on final and the landing is the only thing left.
        """
        here = self.station_on(freq_mhz)
        if here is None:
            return None
        if here.role == "center" and range_nm <= self.approach_hands_over_nm:
            return self.station_for("approach")
        if here.role == "approach" and range_nm <= self.hands_to_tower_nm:
            return self.station_for("tower")
        return None

    @property
    def hands_to_tower_nm(self) -> float:
        """Where Approach gives him up -- and on a talkdown, that is not the
        intercept.

        On an ILS the aeroplane has its own approach aid, so once established
        there is nothing left for Approach to do and Tower takes him. On a
        talkdown the controller IS the approach aid: he reads the range every
        mile and corrects the heading to the missed approach point. Handing off
        at the intercept therefore abandons the pilot at the exact moment the
        procedure begins.

        It did, live, at ten miles in cloud -- "contact Batumi Tower now" while
        the same controller was still transmitting a mile-by-mile talkdown, so
        the pilot was told to leave the frequency that was flying his approach.

        Real practice keeps him: the final controller obtains the landing
        clearance from Tower and relays it, and the pilot never changes
        frequency inside the final. So a talkdown holds him well down the
        approach rather than releasing him at the intercept.

        AND IT IS ONE NUMBER NOW, on every approach:

            "Don't treat the ASR different for handoffs at this time. Just make
             2 mile radius the tower airspace"

        Which removes the branch rather than adding to it. This property used to
        return the missed approach point on a talkdown and the intercept
        otherwise -- two very different distances (0.6 nm and 11 nm) derived
        from which AID the pilot happened to be flying. Both were wrong in
        opposite directions: at 11 nm he was told to leave the frequency that
        was talking him down, and at 0.6 nm Tower was landing an aeroplane it
        had never spoken to.

        Whose airspace the last two miles are is a fact about the FIELD. It does
        not change because the pilot has an ILS, or because the controller is
        reading him ranges. So: a radius, and everything inside it is Tower's.
        """
        return self.tower_takes_nm

    @property
    def tops_ft(self) -> int:
        """Cloud tops, above which an aircraft can see and be seen."""
        return self.ceiling_ft + self.cloud_thickness_ft

    @property
    def hold_in_clear_air(self) -> bool:
        """Is the bottom of the stack above the weather?

        It is, by construction, on a vectored approach -- stack_ft raises the
        base above the tops so that "hold present position" is a thing a pilot
        can actually do. Which makes this the normal case rather than a lucky
        one, and that changes how a formation holds: if they can see each other
        there is no reason to separate them vertically, so a flight holds as ONE
        aeroplane at ONE level, in trail. Altitude separates FLIGHTS from each
        other; it does not separate a flight from itself.

        Climbing to find clear air is cheap and every aircraft can do it -- an
        F-16 holds at eighteen or twenty thousand without thinking about it, and
        a Mustang will climb too. The hold is a chance to regroup before the
        approach, not something to sweat.
        """
        return bool(self.stack_ft) and self.stack_ft[0] > self.tops_ft

    @property
    def stack_ft(self) -> list[int]:
        """The holding levels, bottom first. Derived, so there is no list to keep
        in step with the base/step/ceiling -- and no stored copy in the DB that
        could drift from them."""
        # On a VECTORED approach the stack must sit ABOVE THE CLOUD TOPS, and
        # that is not a nicety. The beacon letdown held aircraft over a fix, and
        # the fix was what kept them apart -- everyone flying the same published
        # pattern, separated by a level each. Take the beacon away, as a radar
        # approach does, and there is no pattern and nothing for an aeroplane
        # with no receiver to hold over. What is left is "hold present position",
        # which is only a real instruction if the pilot can SEE: in cloud he has
        # nothing to hold relative to and will drift out of his own airspace.
        #
        # So the bottom of the stack is raised to clear air. The levels still
        # provide the separation; the visibility is what makes each level
        # holdable.
        base = self.hold_base_ft
        if getattr(self, "vectored", False) or self.kind == "asr":
            base = max(base, _round_up(self.tops_ft + self.vmc_margin_ft,
                                       self.hold_step_ft))
        return list(range(base, self.hold_top_ft + 1,
                          self.hold_step_ft))

    @property
    def top_ft(self) -> int:
        return self.stack_ft[-1]

    @property
    def bottom_ft(self) -> int:
        return self.stack_ft[0]


# Batumi. ATC needs only controller / beacon / stack / missed / outer_hold;
# the rest is for the plate. Outer hold is Kobuleti -- the departure beacon,
# on land up the coast, whose job is done by the time the flight is on approach,
# so a repeatedly-missing aircraft can be banished there without a spare channel.
# Values anchored to the real Batumi (UGSB) ILS RWY 12 plate: inbound 124,
# missed straight to 800' then LEFT to 330' climbing 3000', reversal to 2000'
# over the water. We fly the same geometry with a scripted VHF homing beacon
# (the real LU is a 430 kHz LF NDB the ARA-8 cannot steer on) and station
# passage in lieu of the DME the P-51 does not carry.
BATUMI_APPROACH = ApproachProfile(
    controller="Batumi Approach",
    beacon=BATUMI,
    outer_hold=KOBULETI,
    # Enroute he homes INITIAL (128), so Batumi Approach works him there; the
    # letdown itself is flown homing BATUMI (132), which is Tower's frequency.
    arrival_fix=INITIAL,
    hold_base_ft=4000,
    final_crs=124,
    hold_turns="RIGHT",
    # Read the field's own elevation rather than restating it. These two were 37
    # and 32, and field_elev_ft is what sets MDA (min_hat_ft above the field), so
    # the disagreement moved the minimums the pilot breaks out at.
    field_elev_ft=BATUMI_FIELD.elevation_ft,
    runway="12",
    platform_ft=2000,
    ceiling_ft=400,
    # Radar ON (you wanted eyes), but the P-51 carries no DME and this is a 1944
    # beacon letdown -- so the controller reads range off his own scope, separates
    # procedurally on the single beacon, and talks period. Flip radar off here and
    # it becomes the fully-blind classic.
    atc=AtcCapability(radar=True, dme=False, separation="procedural", era="ww2"),
)


# Batumi, worked as a SURVEILLANCE RADAR approach -- the default now.
#
# The controller does the navigating: he vectors the aircraft onto the final
# approach course and talks it down, calling range each mile. Two things the
# beacon letdown could not do fall out of that for free.
#
# It works in ANY aeroplane. The beacon approach needs the AN/ARA-8 homing
# adapter, which exists on the P-51D-30 and nothing else, so the whole procedure
# was the property of one airframe. An ASR needs a radio and nothing else, so a
# Spitfire, a 109 or a Jug can fly it and the approach belongs to the FIELD.
#
# And it works in wind. Homing points the nose at the beacon, so tracking a
# straight line means crabbing -- and crabbing destroys the only course
# reference the pilot has. Flight testing hit this twice. Under radar the
# controller watches the ground track, absorbs the drift into the heading he
# assigns, and nobody in the aeroplane needs to know the wind exists.
#
# Runway note: DCS names this runway 13/31 (heading 310 true = 304 magnetic, so
# 124 magnetic inbound). We brief the course, not the name, and 124 is the same
# number the old AIP-anchored letdown used.
BATUMI_ASR = ApproachProfile(
    controller=APPROACH.name,
    beacon=BATUMI,                  # still the radar reference point, not a nav aid
    outer_hold=KOBULETI,
    kind="asr",
    guidance="talkdown",            # no glidepath: he is talked to the MAP
    stations=list(STATIONS),
    hold_base_ft=4000,
    final_crs=125,
    # 131.3, AND THE FRAME IS THE WHOLE POINT.
    #
    # DCS's x/z grid is a transverse Mercator and its north is not true north:
    # at Batumi the convergence is 5.74 degrees. So there are two right answers
    # to "which way does this runway point", and they differ by six degrees:
    #
    #   305.6  the F10 ruler, the aircraft compass, and `getRunways().course`
    #          -- all in the DCS GRID frame
    #   311.3  the geodesic bearing between the two thresholds, computed from
    #          lat/lon -- TRUE
    #
    # Our radials come from `ST_Azimuth` on lat/lon, so they are TRUE. The
    # course must be in the same frame or the centreline is drawn six degrees
    # off, which is what it was: on final Hoover reported himself right of
    # course twice while the controller said left, and at 131.3 he was 683 ft
    # and 729 ft RIGHT -- exactly as he called it.
    #
    # The first measurement of the night, a bearing between two points an
    # aeroplane stopped at, gave 311.02. It was taken in the right frame and
    # was correct to a third of a degree, and I threw it away in favour of two
    # readings taken in the wrong one. If a number disagrees with the geometry
    # you are debugging, check the FRAME before you check the number.
    # 131 rather than 131.3: every heading is issued in whole degrees, so a
    # course carrying a fraction leaves a permanent error the aeroplane can
    # never null out, and it comes back as chatter -- 16 rapid reversals across
    # the sweep at 131.3, 2 at 131, for a third of a degree.
    final_crs_true_measured=131.0,
    # Half of Batumi's 2,070 m runway: the 13 threshold, from the centre.
    touchdown_offset_nm=0.559,
    grid_convergence_deg=5.74,
    field_elev_ft=BATUMI_FIELD.elevation_ft,
    runway="13",
    platform_ft=2000,
    ceiling_ft=400,
    # A radar approach, not the ILS the plate is drawn for, and its minima are
    # bounded from two directions.
    #
    # From below by the chart: 687 ft is the obstacle clearance altitude for a
    # 2.5% missed approach climb -- the lowest you may be and still clear the
    # ground if you go around from there. It is a floor, not a decision height,
    # and an MDA beneath it is not a minimum at all.
    #
    # From above by the procedure: a surveillance approach knows where you are
    # to the width of a radar return and gives no vertical guidance, so it is
    # flown to far higher minima than the ILS this chart is drawn for -- five
    # hundred feet at the very least, often nearer a thousand.
    #
    # 700 above the field satisfies both. The profile inherited the ILS plate's
    # 300 before anyone read the chart properly.
    min_hat_ft=700,
    final_intercept_nm=11.0,     # IF, per the AIP plate
    fap_nm=6.0,                  # FAP -- descent begins
    map_nm=0.6,
    msa_sectors=list(BATUMI_FIELD.msa_sectors),
    mva_cells=list(BATUMI_FIELD.mva_cells),
    # The vectoring gate. NOT the published IAF: the real plate's IAF is the LU
    # NDB *overhead the field* at 7,000, from which the pilot flies a racetrack
    # reversal outbound on 304 and comes back inbound on 124. Under radar
    # nobody flies that reversal -- the controller's whole job is to replace it,
    # putting the aircraft on the 124 inbound already established. So the gate
    # we vector to is a point on that inbound course, 15.0 nm out on the 304
    # radial: four miles beyond the published IF, over open water, which is the
    # roll-out room a standard-rate turn needs to be steady by the IF.
    iaf=INITIAL,
    iaf_alt_ft=2000,
    plate_png="ugsb-ils-12.png",
    altimeter_datum="QFE",       # ex-Soviet field
    # AD 2.UGSB-IAC-12-ILSy, the ILU DME column of the descent table.
    descent_table=[(6.0, 2010), (5.0, 1682), (4.0, 1355),
                   (3.0, 1031), (2.0, 708), (1.0, 387)],
    chart_name="AD 2.UGSB-IAC-12-ILSy, AIRAC AMDT 02/2023",
    field_thr_elev_ft=17,        # threshold elevation, per the plate
    # Radar-equipped and radar-separated: the handicaps that defined the beacon
    # letdown do not apply to a procedure the controller flies for you.
    atc=AtcCapability(radar=True, dme=False, separation="radar", era="ww2"),
)


# --- geometry ---------------------------------------------------------------

# The angle between DCS grid north and true north at this field. Batumi's, and
# it is not a constant of the map -- it varies with longitude across a
# transverse Mercator, so it belongs to the FIELD (see SCHEMA.md: measured, as
# the difference between a runway's grid course and the geodesic bearing
# between its thresholds). Here as a default until the airfield table exists.
GRID_CONVERGENCE_DEG = 5.74


def bearing_distance(a: Fix | Field_, b: Fix | Field_,
                     convergence_deg: float = GRID_CONVERGENCE_DEG,
                     ) -> tuple[float, float]:
    """TRUE course in degrees and distance in nautical miles, a to b.

    IT WAS RETURNING A GRID COURSE AND CALLING IT TRUE, which is the opening
    finding of the 29 July audit and has been open since: the paper nav log was
    5.74 degrees out on EVERY leg, 2.39 nm of cross-track over a 23.9 nm leg, on
    a chart a pilot flies.

    `Fix.x/z` are the sim's grid metres, and DCS's grid north is not true north.
    So `atan2(dz, dx)` is a GRID bearing -- correct in the frame the F10 ruler
    and the aircraft compass use, and six degrees wrong in the frame the radar
    side computes in, because our radials come from lat/lon via `ST_Azimuth`.

    Both halves now come from `core.geo`, where the frame is in the name and a
    conversion has to be asked for explicitly. There is no longer a second
    answer for this to be out BY.
    """
    nm, grid = _geo.range_bearing_grid(a.x, a.z, b.x, b.z)
    return _geo.grid_to_true(grid, convergence_deg), nm


def wind_triangle(course_true: float, tas: float = CRUISE_TAS_MPH,
                  wind_from: float = WIND_FROM_DEG,
                  wind_speed: float = WIND_MPH) -> tuple[float, float, float]:
    """Returns (wind correction angle, true heading, groundspeed).

    WCA is positive to the right. Raises if the wind exceeds TAS across track,
    which would mean the course simply cannot be held.
    """
    delta = math.radians(wind_from - course_true)
    crosswind = wind_speed * math.sin(delta)
    headwind = wind_speed * math.cos(delta)
    ratio = crosswind / tas
    if abs(ratio) >= 1:
        raise ValueError(f"wind exceeds TAS across course {course_true:.0f}")
    wca = math.degrees(math.asin(ratio))
    gs = tas * math.cos(math.radians(wca)) - headwind
    return wca, (course_true + wca) % 360, gs


def magnetic(true_deg: float) -> float:
    """Pilots fly magnetic. One implementation, in `core.geo`."""
    return _geo.magnetic(true_deg, MAGVAR)


# --- serialization: an ApproachProfile <-> a plain dict (for the DB) ----------
# An approach is static reference data; storing it means round-tripping the
# profile (and its nested Fix / AtcCapability) through JSON. Properties like
# mda_ft recompute from the fields, so only the fields are serialized.

def profile_to_dict(p: ApproachProfile) -> dict:
    return asdict(p)


def profile_from_dict(d: dict) -> ApproachProfile:
    """Rebuild a profile from a stored record, tolerating older shapes.

    Approaches are persisted, so a row written by a previous version outlives the
    code that wrote it. Unknown keys are dropped rather than raising -- a stale
    row should cost you a field, not the whole approach (and the fallback for a
    failed load is the route.py constant, which would silently ignore whatever
    the mission actually briefed).
    """
    d = dict(d)
    # Every nested Fix has to be rebuilt, not just the two obvious ones -- a dict
    # left in arrival_fix survives every check and only fails at the moment the
    # controller asks which frequency to talk on, which is mid-approach.
    for key in ("beacon", "outer_hold", "arrival_fix"):
        if isinstance(d.get(key), dict):
            d[key] = Fix(**d[key])
    # Same trap one level down: a list of dicts passes every check and fails at
    # the moment somebody asks a Station for its name -- which, for a stored
    # profile, is while the bridge is starting up in front of a waiting pilot.
    d["stations"] = [s if isinstance(s, Station) else Station(**s)
                     for s in (d.get("stations") or [])]
    d["atc"] = AtcCapability(**d.get("atc", {}))

    # stack_ft used to be a stored list; it is now derived from base/step/ceiling.
    # Recover the base from a legacy row so an old record still holds at the right
    # bottom level instead of silently jumping to the default.
    legacy_stack = d.pop("stack_ft", None)
    if legacy_stack and "hold_base_ft" not in d:
        d["hold_base_ft"] = min(legacy_stack)
        d["hold_step_ft"] = (sorted(legacy_stack)[1] - sorted(legacy_stack)[0]
                             if len(legacy_stack) > 1 else 1000)

    known = {f.name for f in fields(ApproachProfile)}
    return ApproachProfile(**{k: v for k, v in d.items() if k in known})


@dataclass
class LegSolution:
    frm: Fix
    to: Fix
    course_true: float
    course_mag: float
    wca: float
    heading_true: float
    heading_mag: float
    distance_nm: float
    groundspeed_mph: float
    minutes: float

    @property
    def time_str(self) -> str:
        m = int(self.minutes)
        return f"{m}:{round((self.minutes - m) * 60):02d}"


def solve_route(tas: float = CRUISE_TAS_MPH, wind_from: float = WIND_FROM_DEG,
                wind_speed: float = WIND_MPH, legs=None) -> list[LegSolution]:
    """Wind-corrected headings and timings for a route.

    Defaults to the approach's own legs so nothing that already called this
    changes, but takes any list of (from, to) pairs -- which is what lets the
    nav log carry an actual sortie rather than the letdown it grew out of.
    """
    out = []
    for frm, to in (legs if legs is not None else LEGS):
        course, dist = bearing_distance(frm, to)
        wca, hdg, gs = wind_triangle(course, tas, wind_from, wind_speed)
        # Distance is nautical, speed is statute per hour -- convert or every
        # leg time comes out 15% short.
        minutes = (dist * MPH_PER_KT) / gs * 60
        out.append(LegSolution(frm, to, course, magnetic(course), wca, hdg,
                               magnetic(hdg), dist, gs, minutes))
    return out


if __name__ == "__main__":
    print(f"wind {WIND_FROM_DEG:.0f}/{WIND_MPH:.0f}  TAS {CRUISE_TAS_MPH:.0f} mph  "
          f"var {MAGVAR:.0f}E\n")
    print(f"{'leg':22} {'crs':>4} {'hdg(M)':>7} {'dist':>6} {'gs':>5} {'time':>6}")
    total = 0.0
    for s in solve_route():
        total += s.minutes
        print(f"{s.frm.name + ' -> ' + s.to.name:22} {s.course_true:4.0f} "
              f"{s.heading_mag:7.0f} {s.distance_nm:6.1f} {s.groundspeed_mph:5.0f} "
              f"{s.time_str:>6}")
    print(f"{'TOTAL':22} {'':4} {'':7} "
          f"{sum(s.distance_nm for s in solve_route()):6.1f} {'':5} "
          f"{int(total)}:{round((total % 1) * 60):02d}")
