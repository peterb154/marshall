"""Single source of truth for the 362nd blind-flying mission.

Both the mission and the kneeboard are generated from this file. That is the
whole point: if the beacon positions live in the .miz builder and the charts are
drawn somewhere else, moving a beacon two miles silently makes the plate lie to
the flight. Here they cannot disagree.

Coordinates are DCS terrain metres, Caucasus: x increases north, z increases
east. Speeds are MPH because the P-51's airspeed indicator is.
"""

import math
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
WIND_FROM_DEG = 270.0
WIND_MPH = 20.0

# The inbound flight this mission expects, for the generated plate (Whisper prime
# + a hint to the controller). Any pilot may call in with their own callsign; the
# controller correlates by position, not by expecting this one. build.py names the
# flight group from the leading word.
FLIGHT_CALLSIGN = "Pony 1-1"
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

FIXES = [KOBULETI, INITIAL, BATUMI]

# The route, in order. INITIAL to BATUMI is deliberately runway heading, so
# rolling out of the turn inbound puts you on the approach course already.
LEGS = [(KOBULETI, INITIAL), (INITIAL, BATUMI)]


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
    role: str = ""              # "center" | "approach" | "tower"
    # The Polly voice this controller speaks with. On the STATION rather than
    # passed to the bridge, because a voice handed in separately drifts from the
    # identity it belongs to -- you end up with Tower's manner in Center's voice
    # and no single place that says which is which. Changing sector should sound
    # like meeting a different person, which is the point of splitting them.
    voice: str = "Matthew"


# Batumi's VHF-high is 131.000 in DCS -- the frequency the in-game field ATC
# actually uses, so Tower gets it. Center and Approach take free slots in the
# SCR-522's 100-156 AM band: every Caucasus airfield occupies 121-141 at 1 MHz
# spacing, and 121.500 is guard, so the clear air is below 121.
#
# CENTER IS NOT A FIELD'S CONTROLLER. Approach and Tower belong to an aerodrome;
# a Center owns a region and hands you between aerodromes, so there is one of
# them for the whole theatre rather than one per airfield. Every field's profile
# points at this same station -- which is also what makes an enroute handoff
# mean something later: leaving Batumi's airspace gives you back to the same man
# who will pass you to Kobuleti.
CENTER = Station("Georgia Center", 119.000, "center", voice="Brian")
APPROACH = Station("Batumi Approach", 120.000, "approach", voice="Matthew")
TOWER = Station("Batumi Tower", 131.000, "tower", voice="Joey")

STATIONS = [CENTER, APPROACH, TOWER]


@dataclass
class Field_:
    name: str
    x: float
    z: float
    elevation_ft: int
    runway: int             # landing heading, magnetic
    msa: dict[str, int] = field(default_factory=dict)
    note: str = ""


# MSAs measured by the terrain survey, 2026-07-24: highest ground per quadrant
# within 25 nm, plus 1000 ft. The NW quadrant is open sea, which is why the
# entire procedure lives there.
BATUMI_FIELD = Field_(
    "Batumi", -355811, 617386, 32, 124,
    msa={"NW": 1000, "NE": 8400, "SE": 11700, "SW": 7500},
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
    kind: str = "ndb"               # "ndb" (pilot navigates) | "asr" (ATC does)
    final_intercept_nm: float = 8.0  # rolled out on final by here
    map_nm: float = 0.6             # missed approach point, range from the field
    approach_hands_over_nm: float = 20.0   # Center gives him to Approach here
    # The controllers who work this approach, enroute inwards. Empty falls back
    # to the beacon-derived stations the NDB letdown uses.
    stations: list[Station] = field(default_factory=list)

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
    final_crs: int = 0              # inbound = runway heading
    hold_turns: str = "RIGHT"
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
    descent_fpm: int = 500          # never steeper than this

    @property
    def speed_kt(self) -> float:
        """Pattern speed in knots -- i.e. nautical miles per hour, which is what
        every distance here is measured in."""
        return self.speed_mph / MPH_PER_KT

    # MDA is not chosen freely: it must sit just below the briefed cloud base so
    # that levelling at minimums actually reveals the runway. Ceiling and MDA
    # move together -- the mission generator reads the same ceiling for weather.
    ceiling_ft: int = 400           # briefed cloud base for this mission
    breakout_ft: int = 100          # MDA this far below the ceiling
    min_hat_ft: int = 150           # but never lower than field + this

    # Missed approach (Batumi real AIP: straight to 800', LEFT to 330', 3000').
    missed_straight_ft: int = 800
    missed_turn: str = "LEFT"
    missed_hdg: int = 330
    missed_climb_ft: int = 3000     # below the stack; ATC re-sequences from here

    @property
    def mda_ft(self) -> int:
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
            first, last = self.stations[0], self.stations[-1]
            s = first if (enroute or banished) else last
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
        for s in self.stations:
            if s.role == role:
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
        if here.role == "approach" and range_nm <= self.final_intercept_nm:
            return self.station_for("tower")
        return None

    @property
    def stack_ft(self) -> list[int]:
        """The holding levels, bottom first. Derived, so there is no list to keep
        in step with the base/step/ceiling -- and no stored copy in the DB that
        could drift from them."""
        return list(range(self.hold_base_ft, self.hold_top_ft + 1,
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
    stations=list(STATIONS),
    hold_base_ft=4000,
    final_crs=124,
    field_elev_ft=BATUMI_FIELD.elevation_ft,
    runway="13",
    platform_ft=2000,
    ceiling_ft=400,
    final_intercept_nm=8.0,
    map_nm=0.6,
    # Radar-equipped and radar-separated: the handicaps that defined the beacon
    # letdown do not apply to a procedure the controller flies for you.
    atc=AtcCapability(radar=True, dme=False, separation="radar", era="ww2"),
)


# --- geometry ---------------------------------------------------------------

def bearing_distance(a: Fix | Field_, b: Fix | Field_) -> tuple[float, float]:
    """True course in degrees and distance in nautical miles, a to b."""
    dx, dz = b.x - a.x, b.z - a.z
    course = math.degrees(math.atan2(dz, dx)) % 360
    return course, math.hypot(dx, dz) / NM


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
    return (true_deg - MAGVAR) % 360


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
                wind_speed: float = WIND_MPH) -> list[LegSolution]:
    out = []
    for frm, to in LEGS:
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
