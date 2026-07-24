"""Single source of truth for the 362nd blind-flying mission.

Both the mission and the kneeboard are generated from this file. That is the
whole point: if the beacon positions live in the .miz builder and the charts are
drawn somewhere else, moving a beacon two miles silently makes the plate lie to
the flight. Here they cannot disagree.

Coordinates are DCS terrain metres, Caucasus: x increases north, z increases
east. Speeds are MPH because the P-51's airspeed indicator is.
"""

import math
from dataclasses import dataclass, field

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
             "Field elevation 32 ft. Runway 13/31.")

FIXES = [KOBULETI, INITIAL, BATUMI]

# The route, in order. INITIAL to BATUMI is deliberately runway heading, so
# rolling out of the turn inbound puts you on the approach course already.
LEGS = [(KOBULETI, INITIAL), (INITIAL, BATUMI)]


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
    "Batumi", -355811, 617386, 32, 130,
    msa={"NW": 1000, "NE": 8400, "SE": 11700, "SW": 7500},
    note="Highest terrain 10,623 ft at 23 nm SE. Missed approach turns LEFT.")


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
    stack_ft: list[int]             # holding stack, bottom first
    outer_hold: Fix                 # escape-valve fix for repeated misses

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
    speed_kt: int = 240             # pattern speed (4 nm/min)
    descent_fpm: int = 500          # never steeper than this

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
    stack_ft=[4000, 5000, 6000, 7000],
    outer_hold=KOBULETI,
    final_crs=124,
    hold_turns="RIGHT",
    field_elev_ft=37,
    runway="12",
    platform_ft=2000,
    ceiling_ft=400,
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
