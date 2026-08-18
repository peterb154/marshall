"""Single source of truth for the mission: the façade over everything that is true.

Both the mission and the kneeboard are generated from here. That is the whole
point: if the beacon positions live in the .miz builder and the charts are drawn
somewhere else, moving a beacon two miles silently makes the plate lie to the
flight. Here they cannot disagree.

WHY THIS IS NOW A FAÇADE. This file was 2,057 lines holding six unrelated
subjects -- conversions, places, airspace, aerodromes, controllers, procedures --
and the size was not the problem. The problem was that adding a second aerodrome
meant editing a station four hundred lines from the field it belongs to, and
four bugs of the last run were exactly that shape.

So the subjects are separated and the name stays:

    units.py      conversions, the wind, the altimeter, the atmosphere
    airspace.py   MSA and MVA -- the published figure and the assignable one
    fixes.py      the places, and the routes strung between them
    fields.py     the aerodromes, and which end of the runway is live
    stations.py   the controllers: who is on which frequency
    approach.py   AtcCapability and ApproachProfile -- procedures as data

They depend strictly downward in that order, so there are no cycles to unpick.

`from marshall.core import route as R` still reaches all of it, and that is
deliberate rather than laziness: some three hundred call sites read `R.BATUMI_ASR`
and `R.STATIONS`, and the contract those sites rely on -- one place that cannot
disagree with itself -- is unchanged. NEW code should import the narrow module;
this re-export is what makes that a gradual choice rather than a flag day.

What genuinely still lives here is what belongs to the SORTIE rather than to any
one subject: who is flying it, the grid-to-magnetic frame the whole theatre is
measured in, and the wind-solved nav log that strings the legs together.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from marshall.core import geo as _geo

# THE RE-EXPORT. Explicit rather than `import *` so that what this file promises
# is a list somebody can read, and so ruff can tell us when a name goes stale.
from marshall.core.airspace import (  # noqa: F401
    MSA_SECTORS, MVA_CELLS, alt_for, msa_for, mva_for)
from marshall.core.approach import (  # noqa: F401
    ApproachProfile, AtcCapability, profile_from_dict, profile_to_dict)
from marshall.core.fields import (  # noqa: F401
    ARRIVAL_FIELD, DEPARTURE_FIELD, Field_, KOBULETI_MSA, KOBULETI_MVA,
    field_named)
# The sortie's own names are NOT in this list and used to be. They are the
# mission's, they live in `[sortie]` in the theatre file, and they come off the
# loaded map through `__getattr__` below exactly as the fields, the stations
# and the wind do. See #137 and `core/fixes.py`, which now holds the TYPE and
# the two functions that reason about a route, and none of the route itself.
from marshall.core.fixes import Fix, leg_altitude, steerpoint  # noqa: F401
from marshall.core.stations import (  # noqa: F401
    PRESET_LETTERS, Station, preset_label, preset_of)
from marshall.core.units import (  # noqa: F401
    CRUISE_ALT_FT, CRUISE_TAS_MPH, INHG_PER_FT, MAGVAR, MPH_PER_KT, NM,
    QNH_INHG, QNH_MMHG, altimeter_spoken, ias_mph, qfe_inhg)

# `WIND_FROM_DEG` and `WIND_MPH` are NOT in that list, and they used to be. The
# wind is not a conversion; it is a fact about the map, so it comes off the
# theatre through `__getattr__` below like the fields and the stations do. See
# `units.py`, where the constants were, and #148.


# --- who is flying it -------------------------------------------------------

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
                  wind_from: float | None = None,
                  wind_speed: float | None = None) -> tuple[float, float, float]:
    """Returns (wind correction angle, true heading, groundspeed).

    WCA is positive to the right. Raises if the wind exceeds TAS across track,
    which would mean the course simply cannot be held.

    NEITHER WIND DEFAULTS TO A CONSTANT ANY MORE. `None` means the map's
    declared wind, resolved when the sum is done rather than when this module
    was imported -- a default argument is bound at import, which on a theatre
    that is chosen by environment is a fact captured before anybody has chosen.
    """
    wind_from, wind_speed = _wind_or_declared(wind_from, wind_speed)
    delta = math.radians(wind_from - course_true)
    crosswind = wind_speed * math.sin(delta)
    headwind = wind_speed * math.cos(delta)
    ratio = crosswind / tas
    if abs(ratio) >= 1:
        raise ValueError(f"wind exceeds TAS across course {course_true:.0f}")
    wca = math.degrees(math.asin(ratio))
    gs = tas * math.cos(math.radians(wca)) - headwind
    return wca, (course_true + wca) % 360, gs


def _wind_or_declared(wind_from: float | None,
                      wind_speed: float | None) -> tuple[float, float]:
    """Whichever half the caller gave, and the map's declaration for the rest.

    ONE READER, so `solve_route` and `wind_triangle` cannot fall back to
    different winds -- which is the whole complaint of #148, one layer down.
    """
    if wind_from is not None and wind_speed is not None:
        return wind_from, wind_speed
    from marshall.core import theatre as _th
    deg, mph = _th.declared_wind()
    return (deg if wind_from is None else wind_from,
            mph if wind_speed is None else wind_speed)


def magnetic(true_deg: float) -> float:
    """Pilots fly magnetic. One implementation, in `core.geo`."""
    return _geo.magnetic(true_deg, MAGVAR)


# --- the nav log: the route solved against the wind -------------------------

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


def solve_route(tas: float = CRUISE_TAS_MPH, wind_from: float | None = None,
                wind_speed: float | None = None, legs=None) -> list[LegSolution]:
    """Wind-corrected headings and timings for a route.

    Defaults to the approach's own legs so nothing that already called this
    changes, but takes any list of (from, to) pairs -- which is what lets the
    nav log carry an actual sortie rather than the letdown it grew out of.
    """
    # RESOLVED ONCE, not per leg: the nav log is one solution against one wind,
    # and a route solved leg by leg against "whatever is declared now" would be
    # a log nobody could reproduce.
    wind_from, wind_speed = _wind_or_declared(wind_from, wind_speed)
    out = []
    for frm, to in (legs if legs is not None else __getattr__("LEGS")):
        course, dist = bearing_distance(frm, to)
        wca, hdg, gs = wind_triangle(course, tas, wind_from, wind_speed)
        # Distance is nautical, speed is statute per hour -- convert or every
        # leg time comes out 15% short.
        minutes = (dist * MPH_PER_KT) / gs * 60
        out.append(LegSolution(frm, to, course, magnetic(course), wca, hdg,
                               magnetic(hdg), dist, gs, minutes))
    return out


if __name__ == "__main__":
    _wdir, _wspd = _wind_or_declared(None, None)
    print(f"wind {_wdir:.0f}/{_wspd:.0f} (declared)  "
          f"TAS {CRUISE_TAS_MPH:.0f} mph  var {MAGVAR:.0f}E\n")
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


# --- the published catalogue, served from configuration ----------------------
#
# `BATUMI_ASR` and friends are no longer Python. They are tables in
# `config/theatres/<map>.toml` (see `core/catalogue.py` and docs/CONFIG.md), and
# this is what keeps some three hundred call sites reading `R.BATUMI_ASR`
# working while there is exactly ONE copy of the data.
#
# WHY A MODULE `__getattr__` RATHER THAN EDITING THE CALL SITES. Both would
# work, and this one leaves the seam in a single readable place instead of
# spread over forty files -- which is the same argument the re-export at the top
# of this module already makes. It also means the names resolve LAZILY: nothing
# reads a theatre file at import, so a tool that only wants `spell_alt` does not
# need a configured map to run.
#
# THE CLASSES STAY IN PYTHON. `Fix`, `Field_`, `Station` and `ApproachProfile`
# are shapes and behaviour; only the INSTANCES were data. That line is the whole
# of docs/CONFIG.md in one sentence.
_FROM_THEATRE = {
    "BATUMI_ASR": ("approach", "batumi-asr-13"),
    "BATUMI_ILS": ("approach", "batumi-ils-13"),
    "BATUMI_APPROACH": ("approach", "batumi-ndb-12"),
    "KOBULETI_ILS": ("approach", "kobuleti-ils-07"),
    # The controllers, by the names three hundred call sites already use.
    "STATIONS": ("stations", ""),
    "KOB_CLEARANCE": ("station", "Kobuleti Clearance"),
    "KOB_GROUND": ("station", "Kobuleti Ground"),
    "KOB_TOWER": ("station", "Kobuleti Tower"),
    "KOB_DEPARTURE": ("station", "Kobuleti Departure"),
    "CENTER": ("station", "Georgia Center"),
    "APPROACH": ("station", "Batumi Approach"),
    "TOWER": ("station", "Batumi Tower"),
    "GROUND": ("station", "Batumi Ground"),
    "OVERLORD": ("station", "Sentry"),
    # ...the weather the map declares. NOT the weather: see `units.py`. This is
    # what the .miz is built with and what a component with no sim falls back
    # to; anything SPOKEN asks `atis.store.wind` for what was measured (#148).
    "WIND_FROM_DEG": ("wind", "from_deg"),
    "WIND_MPH": ("wind", "mph"),
    # ...and the aerodromes.
    "PRESET_LADDER": ("ladder", ""),
    "FIELDS": ("fields", ""),
    "BATUMI_FIELD": ("field", "Batumi"),
    "KOBULETI_FIELD": ("field", "Kobuleti"),
    # ...and the MISSION the map is set up to fly. Its turning points are not
    # published fixes and never were: they belong to the sortie, and the only
    # thing that used to make that true was which Python module they sat in.
    # NO ROUTE, NO LEGS, NO ALTITUDES. `SORTIE`, `SORTIE_LEGS` and
    # `SORTIE_ALT_FT` read a mission out of the theatre file, and #188 removed
    # both the data and the fields it lived in: a map publishes places, not
    # somebody's flight plan. `DEFENDED` stays -- where the guns are is a fact
    # about the ground, true whoever is flying over it.
    "DEFENDED": ("sortie", "defended"),
    # ONE NAMED POINT LEFT, and the other four went with the route.
    #
    # `TARGET_AREA`, `FEET_WET`, `INGRESS` and `HOMEBOUND` pointed at the 1944
    # strike's turning points. They were dead the moment [sortie].route came
    # out of the theatre file -- a map does not fly a mission -- and dead
    # aliases to a mission that no longer exists are how a controller ends up
    # describing somebody else's route to a pilot holding his own. [#188]
    #
    # `AIR_START` stays because REHEARSAL is not a turning point: it is where
    # a test aeroplane is spawned, which is a fact about this map's usable
    # airspace rather than about anybody's sortie. `mission/build.py` reads it.
    "AIR_START": ("sortie_point", "REHEARSAL"),
    # ...and the PUBLISHED places, which were module constants here AND rows in
    # the theatre file, holding the same numbers and agreeing only because
    # nobody had edited one without the other.
    "KOBULETI": ("fix", "KOBULETI"),
    "BATUMI": ("fix", "BATUMI"),
    "KUTAISI": ("fix", "KUTAISI"),
    # INITIAL is NOT published and is not a `[[fix]]`. It is the initial
    # approach fix of the 1944 letdown -- a procedure this project invented, on
    # a plate it generates -- and #143 moved it onto the approaches that use
    # it, as an `iaf`, exactly so it would stop being offered to pilots flying
    # something else. The module constant beside it was a third copy.
    "INITIAL": ("procedure_point", "INITIAL"),
    # The Kobuleti-to-Batumi TRANSIT, which is a different journey from the
    # strike: `SORTIE` goes out to the target and back, this is the hop that is
    # actually flown. Still assembled here rather than declared, because a
    # second mission per map is `Sortie` becoming a list and that has not
    # happened yet -- see #137.
    "FIXES": ("transit", "fixes"),
    "LEGS": ("transit", "legs"),
}


def sortie_points() -> list[tuple[int, Fix]]:
    """(number, fix) down the mission's route, which is how it is read out.

    Was a module constant walked from `fixes.SORTIE`; now the loaded map's, so
    a second theatre gets its own numbering rather than the Caucasus strike's.
    """
    from marshall.core import theatre as _th
    return list(_th.sortie_route())


def station_for(role: str, field: str = "", theatre: str = "", procedure=None):
    """Who works this role, at this aerodrome. THE ONE PLACE IT IS ANSWERED.

    Through the façade, because that is what every caller already imports --
    `R.station_for("tower", field=...)` reads the way `profile.station_for` did
    and comes off the THEATRE, which is where a controller belongs. A role is
    unique only within an aerodrome, so the field argument is not decoration:
    omitting it returns a real controller at the wrong airport. [#162]

    `procedure` is the beacon-letdown switch and is documented on
    `theatre.seats_now`; it is asked one boolean and returns no station. [#152]
    """
    from marshall.core import theatre as _th
    return _th.station_for(role, field, theatre, procedure)


def station_on(freq_mhz: float, theatre: str = "", procedure=None):
    """Who is speaking on this frequency. See `station_for`."""
    from marshall.core import theatre as _th
    return _th.station_on(freq_mhz, theatre, procedure)


def __getattr__(name: str):
    """Resolve a published name against the configured theatre.

    Raises `AttributeError` for anything else, which is what Python expects and
    what keeps a typo an error rather than a None that becomes a plausible
    number three layers away.
    """
    want = _FROM_THEATRE.get(name)
    if want is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    kind, key = want
    from marshall.core import theatre as _th
    # ONE OBJECT PER THING, which is why these go through the cached loaders
    # rather than rebuilding. `R.KOB_CLEARANCE is R.STATIONS[0]` was true
    # when both were one module constant, and tests assert exactly that -- an
    # identity check is the cheapest way to say "the same controller, not a
    # copy that happens to match".
    if kind == "approach":
        got = _th.approaches_now().get(key)
        if got is None:
            raise AttributeError(
                f"{name} names approach {key!r}, which the configured theatre "
                f"does not publish. See docs/CONFIG.md")
        return got
    if kind == "wind":
        deg, mph = _th.declared_wind()
        return deg if key == "from_deg" else mph
    if kind == "stations":
        return list(_th.stations_now())
    if kind == "ladder":
        # THE ORDER IS THE FILE'S. Every card printed reads this, so the
        # aeroplane, the kneeboard and the controller move together or not at
        # all.
        return [s for s in _th.stations_now() if s.preset]
    if kind == "fields":
        return _th.fields_now()
    if kind == "sortie":
        route = _th.sortie_route()
        pts = [f for _, f in route]
        if key == "route":
            return pts
        if key == "legs":
            return list(zip(pts, pts[1:]))
        if key == "alt_ft":
            return list(_th.sortie_alt_ft())
        return list(_th.sortie_defended())
    if kind == "fix":
        got = next((f for f in _th.fixes_now() if f.name.upper() == key.upper()),
                   None)
        if got is None:
            raise AttributeError(
                f"{name} names fix {key!r}, which the configured theatre does "
                f"not publish. See docs/CONFIG.md")
        return got
    if kind == "procedure_point":
        got = _th.procedure_point(key)
        if got is None:
            raise AttributeError(
                f"{name} names {key!r}, which no approach on the configured "
                f"theatre declares. See docs/CONFIG.md")
        return got
    if kind == "transit":
        # KOBULETI, the initial approach fix, then BATUMI. Assembled from the
        # readers above so the transit cannot come to disagree with the
        # catalogue it is drawn from -- which is what two module constants
        # holding the same numbers already were.
        pts = [__getattr__("KOBULETI"), __getattr__("INITIAL"),
               __getattr__("BATUMI")]
        return pts if key == "fixes" else list(zip(pts, pts[1:]))
    if kind == "sortie_point":
        # NONE RATHER THAN AN ERROR, and only here. A map may fly no mission at
        # all -- Nevada declares no `[sortie]` -- and a briefing that asks for
        # the target area on such a map is asking a reasonable question with
        # the answer "there isn't one". `briefing.py` already reads it as
        # `getattr(R, "TARGET_AREA", None)`, so raising would turn a blank
        # paragraph into a dead plate.
        return _th.sortie_point(key)
    table, what = ((_th.stations_now(), "station") if kind == "station"
                   else (_th.fields_now(), "aerodrome"))
    for got in table:
        if got.name == key:
            return got
    raise AttributeError(
        f"{name} names {what} {key!r}, which the configured theatre does not "
        f"have. See docs/CONFIG.md")
