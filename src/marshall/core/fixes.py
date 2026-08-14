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
    # WHAT KIND OF TRANSMITTER THIS FIX IS, if it is one at all -- "ndb",
    # "vor", "tacan", "". Not the navaid itself: this is a fix that may
    # happen to carry a station, and the string says which sort. It was
    # `navaid`, which is the name the THING wants, and holding it here
    # blocked calling a navaid a navaid one layer up.
    navaid_kind: str = "ndb"
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


# THE PUBLISHED FIXES ARE NOT HERE EITHER, for the same reason and one level
# up. KOBULETI, BATUMI and KUTAISI were Python constants AND `[[fix]]` rows in
# `config/theatres/caucasus.toml`, holding identical coordinates -- two authors
# for one number, agreeing only because nobody had edited one without the
# other. That is the shape this project keeps finding, caught here before it
# cost anything rather than after.
#
# INITIAL was worse: a third copy. It is the initial approach fix of the 1944
# letdown, declared on the approaches that use it as an `iaf` and moved there
# by #143 precisely so it would stop being published -- and the module constant
# went on existing beside it.
#
# All four come off the loaded map through `route.__getattr__` now. The beacon
# idents keep their rule, in the file: they must NOT resemble the letters the
# ARA-8 keys for homing -- U (..-), D (-..), A (.-), N (-.). An earlier build
# used B (-...), one dot from a homing D, and the two were indistinguishable in
# flight. [#137]


# THE 1944 STRIKE'S OWN POINTS ARE NOT HERE ANY MORE, and that is the fix.
#
#     "There are fixes in core/fixes.py??? Shouldn't all fixes be data in the
#      database?"
#
# FEET WET, INGRESS, TSUTSNVATI, EGRESS and REHEARSAL were module-level `Fix`
# objects here, and the defended fields and the route and its altitudes were
# lists beside them. Being in a Python module was the only thing that made them
# "not published" -- which is not a property of a name, it is an accident of
# where somebody typed it -- and the bridge pushed the lot into the shared
# `fixes` table on every start regardless.
#
# They live in `[sortie]` in `config/theatres/<map>.toml` now, in a section of
# their own, because what is published is a fact about the MAP and what is
# there goes home with the mission that flies it. Read through
# `theatre.sortie_route`, `theatre.sortie_defended` and `theatre.sortie_alt_ft`,
# and reachable under their old names on `route` -- which is the module every
# caller already imports and is a reader over the files rather than their
# author. [#137]
#
# What is left in this file is the `Fix` TYPE and the two functions that answer
# questions ABOUT a route. Those are logic and stay in code, which is the split
# docs/CONFIG.md asks for: numbers in the data, rules in Python.


def leg_altitude(i: int) -> int:
    """Planned altitude for leg i (0-based), or cruise if the route is shorter.

    The numbers come off the loaded map; falling back to the cruise for a map
    that declares no sortie is the same answer this gave for a route shorter
    than the list, and is why Nevada needs no `[sortie]` section at all.
    """
    from marshall.core import theatre as _th
    alts = _th.sortie_alt_ft()
    if 0 <= i < len(alts):
        return alts[i]
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
    if route is None:
        from marshall.core import theatre as _th
        route = [f for _, f in _th.sortie_route()]
    for i, f in enumerate(route):
        if f is fix or f.name == fix.name:
            return i + 1
    return 0
