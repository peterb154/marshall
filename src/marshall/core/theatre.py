"""Which world this controller is working in.

    "Tell me what you mean that the bridge runs Caucasus profile."

ONE LINE, and everything downstream flowed from it:

    profile = load_and_push_plate(R.BATUMI_ASR)

That object is not just an approach. Its geometry, minima and vectoring cells
are the arrival, and until #162 it carried the station list as well -- so the
approach decided which frequencies the ear opens and `station_on` resolved a
channel to a controller through it. The seats are the THEATRE's now, and
`station_for` / `station_on` below are where they are asked for. Beside it the
ATIS served `R.FIELDS` and the bootstrap wrote a Kobuleti-to-Batumi flight plan.

So on the Nevada mission the bridge was DEAF and, worse, occasionally wrong:

    a pilot on Nellis Clearance 120.900    nobody is listening on it
    a pilot on 121.800                     reaches KOBULETI Ground, because
                                           that is the one frequency the two
                                           theatres happen to share
    the ATIS                               Batumi and Kobuleti weather, on
                                           127.100 and 127.400

The middle one is the dangerous shape this project keeps meeting: not silence,
but a real controller at a real field answering confidently for the wrong
airport -- on the wrong map, this time.

A THEATRE IS THE SELECTION, made once, AND IT SELECTS A WORLD RATHER THAN AN
ARRIVAL. `marshall-atc` takes its fields, its stations, its published
procedures and its bootstrap plan from here; the kneeboard builds its Card from
here. Two mechanisms for "which world" is how the radio and the chart come to
disagree, which is the one thing this project exists to prevent.

It used to take an APPROACH from here too, and that is the line at the top of
this docstring. A map offers procedures; a clearance issues one. There is no
such thing as the theatre's approach and there is no longer anywhere to put
one -- see `Theatre.approaches`, which is plural and has no singular beside
it. [#162]

CHOSEN BY ENVIRONMENT AND NOT INFERRED. Reading the loaded mission sounds better
and is worse: the bridge and the kneeboard both start before anybody has told
the sim anything, and a component that guesses wrong is a controller working the
wrong map while sounding entirely normal.
"""

from __future__ import annotations

import os
from functools import lru_cache as _lru_cache
from dataclasses import dataclass, field

from marshall.core import stations as _stations


@dataclass(frozen=True)
class Theatre:
    """Everything that changes when the map does, and nothing that does not."""

    name: str
    terrain: str                      # the pydcs terrain, for the builders
    fields: tuple = ()
    stations: tuple = ()
    departure: str = ""
    arrival: str = ""
    # WHETHER THIS FACILITY HAS RADAR. See `catalogue.Identity.radar`: it is a
    # property of the ATC unit and was being read off a procedure. [#162]
    radar: bool = True
    # WHAT THIS MAP OFFERS, plural, and there is deliberately no singular
    # beside it. `approach` and `approach_key` were here -- the one arrival the
    # radio was started on -- and every range a Center quoted, every plate the
    # agent was given and every un-cleared aeroplane's numbers came off
    # whichever one that happened to be.
    #
    #     "I don't understand what this whole business about a theater default
    #      approach is. There should be no such thing"
    #
    # There is not. A field OFFERS these and Approach issues ONE of them to ONE
    # aeroplane, which `flights.cleared_approach` records and `hydrate` brings
    # back across a restart. A caller who wants a procedure and has no
    # aeroplane to ask about is asking a question with no answer -- and the
    # answer it used to get was a real approach to a real runway, which is why
    # nothing looked wrong until somebody flew it. [#162]
    approaches: tuple = ()
    wind_from_deg: float = 0.0
    wind_mph: float = 0.0
    # The filed plan the bridge seeds. Named here rather than in the bridge so
    # a migration and the bootstrap cannot disagree -- see migrations/017 and
    # 020. It no longer carries an approach: a filed route says where you are
    # going, not which procedure you will be given when you get there.
    bootstrap_plan: str = ""
    # EVERY FIX THIS MAP PUBLISHES, and the numbered route down it.
    #
    # The bridge used to build this by reading `core.route`'s module globals --
    # `{f.name: f for f in vars(R).values() if isinstance(f, R.Fix)}` -- which is
    # the Caucasus catalogue whatever map is loaded. So on Nevada it published
    # KOBULETI, BATUMI, INGRESS and the rest, and did NOT publish NELLIS. The
    # filed Nevada plan is `NELLIS, TONOPAH` and clearance delivery resolves
    # every route name against the published table, so a clean Nevada start
    # rejects the plan for a fix that exists in the source and never reached the
    # sim. An old row in the database would hide it, which is exactly the
    # accidental success a second theatre is meant to expose.
    #
    # `waypoints` are the NUMBERED ones -- "distance to waypoint three" is how a
    # pilot asks. Empty is honest: a theatre with no strike route has no
    # steerpoints, and inventing them from another map's is how this started.
    fixes: tuple = ()
    waypoints: tuple = ()          # ((1, Fix), (2, Fix), ...)
    # WHAT SHOOTS, if anything. A 1944 Caucasus sortie transits past defended
    # aerodromes and the controller has to be able to talk about them; a
    # peacetime training flight over Nevada does not. Empty is the normal case
    # and the plate says nothing rather than inventing a war.
    defended: tuple = ()
    # THE LEGS, solved, for the plate's route paragraph. Empty where a theatre
    # has no filed strike route -- which is most of them.
    legs: tuple = ()
    extra: dict = field(default_factory=dict)

    def field_named(self, name: str):
        return next((f for f in self.fields
                     if f.name.lower() == (name or "").lower()), None)


# WHICH RECOVERY AT BATUMI. Three procedures are published to the same runway
# and the bridge runs ONE arrival profile at a time, so the choice has to be
# made somewhere -- and explicit beats baked in, which is the lesson
# `NEVADA_SORTIES` below already carries.
#
#     asr    the surveillance approach. The controller IS the approach aid and
#            reads a range every mile. Fifty-odd sorties have flown it.
#     ils    the same AIP plate flown as what it is: vectors to intercept, a
#            clearance, and then silence. AD 2.UGSB-IAC-12-ILSz.
#     ndb    the 1944 beacon letdown, for the period flavour.
#
# ALL THREE ARE PUBLISHED AND NONE IS SELECTED HERE. This block used to end
# `MARSHALL_APPROACH=batumi-ils`, with the ASR as the default "because it is
# what has actually been flown". Two mechanisms have now been deleted off the
# same line, and they failed the same way:
#
#     CAUCASUS_RECOVERIES = {"batumi-asr": "BATUMI_ASR", ...}   -> #137
#     MARSHALL_APPROACH / default_approach                      -> #162
#
# The first mapped a key to the NAME OF A PYTHON CONSTANT, so a theatre file
# could publish a procedure nothing was able to select. The second let the
# shell a process was started from decide which arrival every aeroplane on the
# frequency was worked against. The keys are the file's, the choice is a
# clearance's, and this module makes neither.


# HOW CLOSE A POINT HAS TO BE TO COUNT AS THE AERODROME'S OWN. Two miles is
# well outside any runway -- Batumi's is a mile and an eighth end to end -- and
# well inside the eighteen that separate the TPH VORTAC from Tonopah airfield,
# which is the case this exists to refuse. It is a sanity check and not a
# tolerance: nothing is corrected by it, a candidate either is the aerodrome
# reference point or is some other place wearing the aerodrome's name.
ON_THE_FIELD_NM = 2.0


def _nm(x1: float, z1: float, x2: float, z2: float) -> float:
    """Grid metres apart, in nautical miles. Flat, because two points a mile
    apart on one aerodrome do not need a geodesic."""
    return ((x1 - x2) ** 2 + (z1 - z2) ** 2) ** 0.5 / 1852.0


def published_approaches(fields=(), theatre: str = "") -> dict:
    """The map's procedures, keyed, with the theatre's data composed back in.

    THIS IS WHERE THE TWO THINGS ARE PUT BACK TOGETHER, in one place and
    visibly. `ApproachProfile` carries `msa_sectors` and `mva_cells` as well as
    the procedure, so a profile is still the theatre's reference data welded to
    one arrival -- the unfinished half of #2, and the reason the bridge cannot
    hold the first without defaulting the second.

    THE STATION TABLE IS NO LONGER WELDED ON. It used to be, and it was the
    worst of the welds: a procedure at Batumi carried Kobuleti's ground seats,
    so every caller who wanted a controller went through an arrival. The seats
    are the theatre's and are read from `station_for` / `station_on`; what
    survives here is one bit -- `theatre_stations` -- saying whether a
    procedure's controllers are the ladder at all or the beacons the pilot
    homes. See #162, and #152 on that bit. The minimum altitudes still come
    from the aerodrome the procedure names, so there is one copy and an
    approach cannot come to disagree with the field it serves.
    """
    from marshall.core import catalogue
    from marshall.core import route as R

    at = {f.name: f for f in published_fixes(theatre)}
    by_field = {f.name: f for f in fields}

    def own_point(a):
        """The one point this procedure uses that the catalogue does not hold.

        BUILT ONCE PER APPROACH, so a point named in two roles -- Kobuleti's ILS
        holds at its own IAF -- is one object and not two that happen to agree.
        `route.__getattr__` makes the same argument for the cached loaders, and
        several tests assert identity rather than equality because that is the
        cheapest way to say "the same place, not a copy".

        The NAME is the role's. `iaf = "INITIAL"` says it once, so there is no
        second spelling to drift, and an approach that carries geometry for one
        point may not name two -- the second would silently get the first's
        coordinates under its own name, which is this project's favourite
        failure shape: a real-looking number belonging somewhere else.
        """
        want = [n for n in (a.navaid, a.outer_hold, a.arrival_fix, a.iaf)
                if n and n not in at]
        if not want:
            return None
        if len(set(want)) > 1:
            raise ValueError(
                f"approach {a.key!r} names {len(set(want))} fixes this theatre "
                f"does not publish ({', '.join(sorted(set(want)))}) and carries "
                f"geometry for one. See docs/CONFIG.md")
        if a.own_point is None:
            # LOUD. A procedure naming a fix that is neither published nor
            # carried is a procedure nobody can fly, and the failure must not be
            # a None that turns into a plausible number three layers away.
            raise ValueError(
                f"approach {a.key!r} names fix {want[0]!r}, which this theatre "
                f"does not publish and the procedure does not carry -- add it "
                f"to the theatre file with its source, give the approach an "
                f"[approach.own_point], or correct the name. See docs/CONFIG.md")
        p = a.own_point
        # `sector` is who owns the FREQUENCY, and `station()` reads it to decide
        # who talks to him while he is homing this point. The procedure's own
        # controller, because a point that is not published belongs to nobody
        # else -- and it is the procedure that put him on this needle.
        return R.Fix(want[0], p.ident, p.x, p.z, p.mhz or None,
                     sector=a.controller, lat=p.lat, lon=p.lon)

    def datum(a, f):
        """WHERE THIS APPROACH IS. The aerodrome, as a point, and nothing else.

        An approach always has a field and it is the datum for every range, IAF
        offset and plate -- which is what `beacon` was doing under a name that
        made three of this map's four procedures claim a navaid they do not
        have (#163).

        THE POINT COMES FROM THE PUBLISHED FIX WHERE THE MAP HAS ONE, because
        that fix IS the aerodrome reference point and is what the rest of the
        system already measures against: `field_origin` resolves an aerodrome
        by looking its NAME up in the projected fix table, so taking the datum
        from anywhere else would give one controller a different Batumi from
        the next. It is copied rather than shared, and stripped of its ident,
        frequency and sector on the way -- a datum is a place, and the one
        thing the fix rows carry that does not belong to a place is the beacon
        costume this issue is about.

        A FIX OF THE SAME NAME IS NOT AUTOMATICALLY THE AERODROME, and Nevada
        is the proof: `TONOPAH` is the TPH VORTAC, an enroute station carrying
        the town's name eighteen miles from Tonopah airfield, and reading it as
        the field's datum is how `tonopah-ils` came to measure its whole
        approach from a point in the desert (#141 found the distance and read
        it as a wrong coordinate; it is this conflation wearing one). So the
        candidate has to BE at the aerodrome, and where it is not, the
        aerodrome's own row answers -- it is never wrong about where it is.
        """
        got = at.get((a.field or "").upper())
        if got is not None and _nm(got.x, got.z, f.x, f.z) <= ON_THE_FIELD_NM:
            return R.Fix(got.name, "", got.x, got.z, None,
                         note=got.note, navaid_kind="", lat=got.lat, lon=got.lon)
        return R.Fix(f.name, "", f.x, f.z, None,
                     note=f.note, navaid_kind="", lat=f.lat, lon=f.lon)

    out = {}
    for a in catalogue.approaches(theatre):
        knobs = a.model_dump(exclude={"key", "field", "atc", "navaid",
                                      "outer_hold", "arrival_fix", "iaf",
                                      "theatre_stations", "own_point",
                                      "published_minima"})
        # AN UNUSED ROLE IS NOT AN UNRESOLVABLE NAME, and conflating the two is
        # what broke the first two attempts at #145. An approach that names no
        # `arrival_fix` has no enroute homing fix -- `briefing.py` guards on
        # exactly that -- while an approach that names one the catalogue does
        # not hold has its own. The empty string is the first case and must stay
        # None; falling back on it handed the radar ASR the letdown's IAF and
        # sent a departing aircraft an arrival briefing.
        mine = own_point(a)
        def role(want, _mine=mine):
            return (at.get(want) or _mine) if want else None
        f = by_field.get(a.field)
        if f is None:
            # LOUD. A procedure with no aerodrome has no datum, and every range
            # it speaks would be measured from nothing -- which is not a thing
            # that can be discovered later from a plausible number.
            raise ValueError(
                f"approach {a.key!r} names field {a.field!r}, which this "
                f"theatre does not have. Every approach arrives at an "
                f"aerodrome and it is the datum for everything positional. "
                f"See docs/CONFIG.md")
        mins = a.published_minima
        out[a.key] = R.ApproachProfile(
            aerodrome=datum(a, f), navaid=role(a.navaid),
            outer_hold=role(a.outer_hold),
            arrival_fix=role(a.arrival_fix), iaf=role(a.iaf),
            atc=R.AtcCapability(**a.atc.model_dump(exclude_none=True)),
            theatre_stations=a.theatre_stations,
            msa_sectors=[tuple(s) for s in (f.msa_sectors if mins else [])],
            mva_cells=[tuple(c) for c in (f.mva_cells if mins else [])],
            **knobs)
    return out


def published_fields(theatre: str = "") -> tuple:
    """The map's aerodromes, from the configuration file.

    Converted to `Field_` here so everything downstream -- `station_for`,
    `runway_in_use`, the MSA/MVA lookups, the charts -- keeps working against
    the type it already knows. The file is the source; `Field_` is the shape
    the rest of the system speaks.
    """
    from marshall.core import catalogue
    from marshall.core import route as R
    return tuple(
        R.Field_(f.name, f.x, f.z, f.elevation_ft, f.runway,
                 ends=tuple(f.ends), atis_mhz=f.atis_mhz,
                 atis_uhf_mhz=f.atis_uhf_mhz, lat=f.lat, lon=f.lon,
                 magvar_deg=f.magvar_deg,
                 grid_convergence_deg=f.grid_convergence_deg,
                 msa_sectors=[tuple(s) for s in f.msa_sectors],
                 mva_cells=[tuple(c) for c in f.mva_cells],
                 note=f.note)
        for f in catalogue.aerodromes(theatre))


def published_stations(theatre: str = "") -> tuple:
    """The map's controllers, in the order the file lists them.

    ORDER IS THE LADDER, so it is preserved rather than sorted: `channels_for`
    takes the first four presets and `"ABCD"[i]` indexes the buttons, and both
    were correct only while there were exactly four.
    """
    from marshall.core import catalogue
    from marshall.core import route as R
    return tuple(
        R.Station(s.name, s.freq_mhz, s.role, also=tuple(s.also),
                  voice=s.voice, channels=tuple(s.channels),
                  field=s.field, preset=s.preset, manner=s.manner)
        for s in catalogue.controllers(theatre))


def _map_name(theatre: str = "") -> str:
    """The map we are configured for, resolved to a real one."""
    name = (theatre or os.environ.get("MARSHALL_THEATRE")
            or "caucasus").strip().lower()
    return name if name in THEATRES else "caucasus"


# RESOLVE THE NAME BEFORE THE CACHE, not inside it. `lru_cache` keys on the
# ARGUMENT, so `stations_now("")` and `stations_now("caucasus")` were two
# entries holding two sets of equal-but-distinct objects -- and
# `R.KOB_CLEARANCE is R.STATIONS[0]` went false, which several tests
# assert precisely because identity is the cheapest way to say "the same
# controller, not a copy that happens to match".
@_lru_cache(maxsize=4)
def _stations_cached(name: str) -> tuple:
    # THE FALLBACK THAT WAS HERE IS GONE, and its going is the point of #137's
    # second half. It read a map's seats out of `THEATRES[name]().stations`
    # when the file published none, because Nevada's controllers were nine
    # `Station` objects in `core/nevada.py` and this became the one place a
    # station is looked up -- so without it a map that publishes no
    # `[[station]]` rows went silently stationless. Nevada's rows exist now, so
    # nothing reaches it; and leaving it would be worse than dead code, because
    # `nevada()` reads `stations_now` itself and the fallback would recurse.
    return published_stations(name)


@_lru_cache(maxsize=4)
def _fields_cached(name: str) -> tuple:
    return published_fields(name)


@_lru_cache(maxsize=4)
def _approaches_cached(name: str) -> dict:
    return published_approaches(_fields_cached(name), name)


# ONE OBJECT PER FIX, for the same reason the seats and the fields get one:
# `NEVADA_ROUTE = [LSV, TPH, LSV]` was one `Fix` appearing twice, and the
# numbered route and the published table were the same objects. Rebuilt per
# call they are two copies that happen to agree, which is how they come to
# differ -- so the conversion is cached on the resolved map name like the rest.
def sortie_route(theatre: str = "") -> tuple:
    """The mission's numbered steerpoints, from the file. `((1, Fix), ...)`.

    NAMES RESOLVE AGAINST THE MISSION'S OWN POINTS FIRST AND THE PUBLISHED
    CATALOGUE SECOND, which is what lets a private route use a public
    aerodrome without copying it: BATUMI opens and closes the 1944 strike and
    is one row in `[[fix]]`, visited twice.

    Private first rather than public first, deliberately. A mission that
    defines a point of its own under a published name means it, and silently
    handing it the map's version instead would move a turning point without
    saying so -- the mirror of #143, where our INITIAL collided with a real
    cartridge's. A collision is the mission's to resolve and this is not the
    layer that can.

    Empty where the file declares no `[sortie]`, which is Nevada: a map may
    publish a catalogue and fly nothing private. [#137]
    """
    from marshall.core import catalogue
    from marshall.core.fixes import Fix
    name = _map_name(theatre)
    s = catalogue.sortie(name)
    if s is None or not s.route:
        return ()
    mine = {p.name.upper(): Fix(p.name, "", p.x, p.z, None, note=p.note or "",
                                navaid_kind="", lat=p.lat, lon=p.lon)
            for p in s.point}
    public = {f.name.upper(): f for f in _fixes_cached(name)}
    out = []
    for n, want in enumerate(s.route, start=1):
        f = mine.get(want.upper()) or public.get(want.upper())
        if f is None:
            # NAMED, NOT SKIPPED. A route point nothing defines would otherwise
            # renumber every steerpoint after it, so "waypoint four" would mean
            # a different place than the chart says -- silently.
            raise KeyError(
                f"{name}: [sortie].route names {want!r}, which is neither a "
                f"[[sortie.point]] nor a published [[fix]]")
        out.append((n, f))
    return tuple(out)


def _sortie_wp(theatre: str = "") -> tuple:
    """`sortie_route`, and empty rather than fatal when the file is wrong.

    A malformed `[sortie]` must not stop a bridge coming up: the strike route
    is one mission's chart and the ladder, the approaches and the whole ground
    half do not touch it. Named on the way past, because a route that silently
    vanished would read as a map that has no mission.
    """
    try:
        return sortie_route(theatre)
    except (KeyError, ValueError) as exc:
        print(f"!! {_map_name(theatre)}: no sortie route -- {exc}", flush=True)
        return ()


def _sortie_legs(theatre: str = "") -> tuple:
    """Consecutive pairs down the route, which is what a planner walks."""
    pts = [f for _, f in _sortie_wp(theatre)]
    return tuple(zip(pts, pts[1:]))


def procedure_point(want: str, theatre: str = ""):
    """A point an APPROACH declares, by name. `None` when nothing does.

    The third source, after the published catalogue and the mission's own.
    `catalogue.OwnPoint` is "a point a procedure USES and nobody PUBLISHES" --
    INITIAL is the standing example, moved onto its approaches by #143 when a
    real DKS cartridge turned up carrying a steerpoint of the same name
    thirteen miles away and every import warned about a collision with our
    fiction.

    ONE POINT MAY BE DECLARED BY SEVERAL PROCEDURES. Three approaches name
    INITIAL as their `iaf` and it is the same place each time, so the first
    match wins and the others are not consulted -- which is right while they
    agree and would be wrong the moment they did not. They cannot: each is
    written under the approach that uses it, and a procedure that wanted a
    different point of the same name would be declaring a different point, not
    disagreeing about this one.
    """
    key = (want or "").upper()
    for pro in approaches_now(theatre).values():
        for attr in ("iaf", "outer_hold", "arrival_fix", "navaid"):
            got = getattr(pro, attr, None)
            if got is not None and getattr(got, "name", "").upper() == key:
                return got
    return None


def sortie_point(want: str, theatre: str = ""):
    """One of the mission's own points by name, or None.

    DECLARED, NOT NECESSARILY FLOWN, and that distinction is the whole reason
    this is not just a search of `sortie_route`. REHEARSAL is a `[[sortie.point]]`
    that appears nowhere in `route`: it is where the test flights spawn
    airborne, which is a place the mission owns and never navigates to. A
    lookup that walked the route returned None for it and the mission builder
    lost its air-start.

    Falls through to the published catalogue, so a caller asking for a name the
    mission borrows -- BATUMI opens and closes the strike -- gets the map's row
    rather than nothing.
    """
    from marshall.core import catalogue
    from marshall.core.fixes import Fix
    name = _map_name(theatre)
    s = catalogue.sortie(name)
    key = (want or "").upper()
    for pt in (s.point if s is not None else ()):
        if pt.name.upper() == key:
            return Fix(pt.name, "", pt.x, pt.z, None, note=pt.note or "",
                       navaid_kind="", lat=pt.lat, lon=pt.lon)
    return next((f for f in _fixes_cached(name) if f.name.upper() == key), None)


def sortie_defended(theatre: str = "") -> tuple:
    """What the route is planned around: `(name, x, z, reach_nm)` per battery."""
    from marshall.core import catalogue
    s = catalogue.sortie(_map_name(theatre))
    if s is None:
        return ()
    return tuple((d.name, d.x, d.z, d.reach_nm) for d in s.defended)


def sortie_alt_ft(theatre: str = "") -> tuple:
    """Planned altitude per LEG -- one shorter than the route."""
    from marshall.core import catalogue
    s = catalogue.sortie(_map_name(theatre))
    return tuple(s.alt_ft) if s is not None else ()


@_lru_cache(maxsize=4)
def _fixes_cached(name: str) -> tuple:
    return published_fixes(name)


def stations_now(theatre: str = "") -> tuple:
    """The configured map's controllers -- ONE object per seat."""
    return _stations_cached(_map_name(theatre))


def fields_now(theatre: str = "") -> tuple:
    """The configured map's aerodromes -- ONE object per field."""
    return _fields_cached(_map_name(theatre))


def seats_now(procedure=None, theatre: str = "") -> tuple:
    """The controllers on the air, for a procedure the ladder actually staffs.

    THE ONE PLACE THE MODE SWITCH LIVES, and `procedure` is here for that and
    for nothing else -- it is asked one boolean about ITSELF and never yields a
    Station. A beacon letdown's controllers are not on the ladder at all: the
    ARA-8 homes whatever the set is tuned to, so the man you talk to IS the
    frequency you home, and `ApproachProfile.theatre_stations` is False.

    That used to be spelt "the profile's own station list is empty", in two
    places by #152's count and in about a dozen by consequence -- every role
    lookup through the 1944 profile answered None because the list it walked
    was that profile's. The table has moved to the map (#162) and the emptiness
    would have moved with it, so the letdown would have silently acquired eight
    modern seats. PRESERVED, NOT ENDORSED, which is the same words
    `config/theatres/caucasus.toml` uses about the flag itself. #152 is where
    it gets said properly, as a capability; this argument goes with it.

    `procedure=None` means the ladder, which is every other caller.
    """
    if procedure is not None and not getattr(procedure, "theatre_stations", True):
        return beacon_seats(procedure)
    return stations_now(theatre)


def a_procedure_into(field: str = "", theatre: str = ""):
    """One published procedure into `field`, for a TOOL that must choose one.

    THE RADIO NEVER CALLS THIS, and that is the whole reason it is named the
    way it is. `Theatre.approach` was deleted because a process cannot fly an
    approach (#162); a REHEARSAL SCRIPT is a different thing -- it is standing
    in for a pilot, and a pilot flies one. `ghost_flight` and `stack_rehearsal`
    need a procedure for the same reason a synthetic pilot needs a callsign.

    So the choice is made HERE, once, visibly, and by a function whose name is
    an indefinite article. It is not `the_approach`, there is no environment
    variable behind it, and `tests/test_the_atc_holds_no_arrival.py` asserts
    that nothing under `marshall/atc/` reaches for it. A tool that wants a
    different one names it on the command line and should PRINT which it got.

    The lowest key at the field, sorted, so two runs choose the same procedure
    and a rehearsal is reproducible. Defaults to the sortie's arrival field.
    """
    procedures = approaches_now(theatre)
    want = (field or _theatre_arrival(theatre) or "").lower()
    here = [p for _k, p in sorted(procedures.items())
            if p.aerodrome.name.lower() == want]
    if not here:
        raise LookupError(
            f"no published approach into {want!r}; this map offers "
            f"{', '.join(sorted(procedures))}")
    return here[0]


def _theatre_arrival(theatre: str = "") -> str:
    """Where the sortie recovers. `current()`, not `identity()`: Nevada's
    arrival is a fact about which of its two sorties is being flown and its
    theatre file declares none, so the catalogue answers "" there."""
    if theatre and theatre in THEATRES:
        return THEATRES[theatre]().arrival or ""
    return current().arrival or ""


def seats_on_the_air(theatre: str = "") -> tuple:
    """Every seat anybody on this map could be worked by. FREQUENCIES, not roles.

    THE EAR OPENS THIS, and it exists because there is no longer one procedure
    to ask. `_run_srs` read `stations_now() if profile.theatre_stations else ()`
    off the process-wide arrival, so which channels the radio LISTENED on were
    decided by whichever approach it was started with: started on the 1944
    letdown it opened none of the ladder, and started on anything else it could
    not hear a Mustang homing 132.0. One aeroplane's procedure cannot decide
    what the facility can hear. [#162]

    THE UNION IS SAFE HERE AND WOULD NOT BE IN THE STATION TABLE, which is why
    this is a separate function from `push_stations`. A beacon seat and a
    ladder seat can share a NAME and differ in frequency -- "Batumi Tower" is
    118.6 on the ladder and 132.0 on the letdown -- so a union has two rows for
    one role at one field, and `station_for("tower", field="Batumi")` would
    answer one of them by list order. That is the exact fault #162 and the
    two-aerodrome work both exist to kill.

    Every caller of this resolves by FREQUENCY -- `on_frequency`, the voice
    table, the channel list -- and a frequency is unique across the union. The
    by-role lookups keep the ladder alone. Where a procedure's seats differ,
    its plate says so in words: see `briefing._own_seats`.
    """
    from marshall.core.stations import Station
    out: list[Station] = list(stations_now(theatre))
    seen = {round(s.freq_mhz, 3) for s in out}
    for p in approaches_now(theatre).values():
        if getattr(p, "theatre_stations", True):
            continue
        for s in beacon_seats(p):
            if round(s.freq_mhz, 3) in seen:
                continue
            seen.add(round(s.freq_mhz, 3))
            out.append(s)
    return tuple(out)


def beacon_seats(procedure) -> tuple:
    """The controllers of a procedure that is not on the ladder: its own beacons.

        "They were the same thing while the approach was a beacon letdown --
         the controller had to sit on the beacon you were homing, because the
         ARA-8 tunes and homes on one frequency at a time."

    `Station`'s own docstring, and the reason this can be DERIVED rather than
    declared. Each fix a period procedure uses already carries the seat that
    owns its frequency -- INITIAL is Batumi Approach on 128.0, BATUMI is Batumi
    Tower on 132.0, KOBULETI is Kobuleti Departure on 124.0 -- because on that
    procedure the frequency IS the navaid.

    WHAT THIS REPLACES IS AN EMPTY TUPLE. `theatre_stations = false` meant "not
    on the modern ladder" and was read as "has no controllers", so a bridge
    started on the 1944 flavour had a man who could not name a single
    frequency: no handoff could be spoken, no departure frequency issued, and
    every refusal lost the half that tells a pilot what to do. Nobody had flown
    it, which is why nobody had noticed. [#140]

    AND IT IS NOT THE MODERN LADDER EITHER, which is the other wrong answer and
    the tempting one. Handing this profile `stations_now()` would tell a
    Mustang to contact Batumi Tower on 118.6 while his ARA-8 is homing 132.0 --
    a real controller on a frequency the aeroplane physically cannot tune. The
    period flavour lives in `AtcCapability` (no DME, procedural separation, no
    vectors); the SEATS are a fact about which radios exist.

    A role and a field come out of the name, last word first, exactly as
    `clearance.field_of` reads one: "Batumi Approach" is the approach seat at
    Batumi. That is how every station in this system is named.
    """
    from marshall.core.stations import Station
    out: dict[str, Station] = {}
    # The order is the ladder's: where he is worked first, then the field.
    for attr in ("arrival_fix", "outer_hold", "navaid", "iaf", "aerodrome"):
        f = getattr(procedure, attr, None)
        who = (getattr(f, "sector", "") or "").strip()
        hz = getattr(f, "freq_mhz", None)
        if not who or not hz:
            # A fix with no seat or no frequency is a place, not a person. The
            # aerodrome row is usually exactly that.
            continue
        if who in out:
            continue
        words = who.split()
        out[who] = Station(name=who, freq_mhz=float(hz),
                           role=words[-1].lower() if len(words) > 1 else "",
                           field=" ".join(words[:-1]) if len(words) > 1 else "",
                           preset=True)
    return tuple(out.values())


def station_for(role: str, field: str = "", theatre: str = "", procedure=None):
    """Who works this role, at this aerodrome, on this map.

    THE ONE PLACE THIS IS ANSWERED. It was `ApproachProfile.station_for`, so
    the comms ladder for every aerodrome on the map was reached through one
    arrival procedure -- Kobuleti Ground's frequency came out of Batumi's ILS,
    and a departure and a recovery forty miles apart shared a table because
    they shared a profile. A station belongs to the THEATRE. [#162]

    `field` carries the same warning it always did: a role is only unique
    within an aerodrome, and an unqualified lookup returns a real controller at
    the wrong airport. See `stations.role_at`. `procedure` is the #152 switch
    and is explained on `seats_now`.
    """
    return _stations.role_at(seats_now(procedure, theatre), role, field)


def station_on(freq_mhz: float, theatre: str = "", procedure=None):
    """Who is speaking on this frequency, on this map. See `station_for`."""
    return _stations.on_frequency(seats_now(procedure, theatre), freq_mhz)


def fixes_now(theatre: str = "") -> tuple:
    """The configured map's published fixes -- ONE object per fix."""
    return _fixes_cached(_map_name(theatre))


def approaches_now(theatre: str = "") -> dict:
    """Every procedure the configured map publishes, keyed. Cached.

    The entry point for `route.__getattr__`, so it is hit on ordinary attribute
    access and must not rebuild the theatre each time. Cached on the map name;
    `catalogue.reload()` is the way to forget, and the tests use it.
    """
    return _approaches_cached(_map_name(theatre))


@_lru_cache(maxsize=4)
def _wind_cached(name: str) -> tuple:
    th = THEATRES[name]()
    return (th.wind_from_deg, th.wind_mph)


def declared_wind(theatre: str = "") -> tuple:
    """(from degrees, mph) — the wind this MAP declares, and nobody else does.

    THE DECLARED WIND IS NOT THE WIND. It is what the mission is built with:
    `mission/build.py` writes it into the .miz weather, so it is the number the
    sim then has, and `atis/` MEASURES that at ten metres over each field and
    writes what it found to the `atis` table. Anything spoken or drawn should
    read the measurement -- `atis.store.wind` -- and fall back here only when
    nothing has observed anything, which is every component that runs with no
    sim: the kneeboard, the plate, the nav log, the mission builder itself.

    It lives on the THEATRE because a different map wants a different answer,
    which is the rule in docs/CONFIG.md. It used to be `units.WIND_FROM_DEG`, a
    module constant, at the same time as the runway in use was a measurement --
    so a landing clearance could name a wind that contradicted the ATIS that
    chose its runway (#148). There is one declared wind per map now and it is
    in `config/theatres/<map>.toml`.

    Cached on the map name like the other loaders, because `runway_in_use()`
    falls back to it and that is called per transmission.
    """
    return _wind_cached(_map_name(theatre))


def published_fixes(theatre: str = "") -> tuple:
    """The map's published fixes as `Fix` objects, from the configuration file.

    Converted here rather than returned as pydantic models so that everything
    downstream -- `push_fixes`, `field_origin`, the mission builder, the charts
    -- keeps working against the one type it already knows. The file is the
    source; `Fix` is the shape the rest of the system speaks.
    """
    from marshall.core import catalogue
    from marshall.core import route as R
    return tuple(
        # WHAT KIND OF STATION IT IS, IF ANY, AND THE FILE IS BELIEVED. This
        # read `f.navaid_kind or "ndb"`, so a fix that named no kind got a homing
        # beacon it does not have -- which is how `TONOPAH`, a VORTAC, and
        # `NELLIS`, an aerodrome reference point with no transmitter at all,
        # both came to be non-directional beacons as far as `atc/equipment.py`
        # was concerned. That table decides which airframe can navigate to
        # what: it would have offered a hold at Nellis to a Mustang on the
        # strength of an ADF needle pointing at nothing. Empty means a point in
        # space, which `equipment.can_use` already answers correctly. [#163]
        R.Fix(f.name, f.ident, f.x, f.z, f.freq_mhz or None,
              sector=f.sector, note=f.note, navaid_kind=f.navaid_kind,
              lat=f.lat, lon=f.lon)
        for f in catalogue.published_fixes(theatre))


def caucasus() -> Theatre:
    """The 362nd. Kobuleti to Batumi, radar recovery, 1944 flavour available."""
    from marshall.core import catalogue
    # NAMES ITS OWN MAP. These read `MARSHALL_THEATRE` underneath, so when
    # `current()` fell back to this function after a misspelt name, every
    # loader went looking for `nevda.toml` again and the fallback landed
    # nowhere. A function that IS the Caucasus theatre should not have to ask
    # which theatre it is.
    me = catalogue.identity("caucasus")
    fields, stations = fields_now("caucasus"), stations_now("caucasus")
    # ALL OF THEM, AND NOTHING CHOSEN. This used to resolve `MARSHALL_APPROACH`
    # or `default_approach` into one `recovery` and hang it on the theatre. Two
    # things followed from that and both cost a sortie: restarting the radio
    # from the wrong shell changed the procedure under a flying aeroplane
    # (#158, `batumi-ils` became `batumi-asr` during a rehearsal), and a Center
    # measured every range from the loaded arrival's field, so the number moved
    # forty miles with no other change (#160).
    #
    # The keys are still the file's -- that half of #137 stands -- but nothing
    # in this process picks one. See `Theatre.approaches`. [#162]
    procedures = approaches_now("caucasus")
    return Theatre(
        name=me.name, terrain=me.terrain, fields=fields,
        stations=stations, departure=me.departure,
        arrival=me.arrival, radar=me.radar,
        approaches=tuple(procedures.values()),
        wind_from_deg=me.wind_from_deg, wind_mph=me.wind_mph,
        bootstrap_plan=me.bootstrap_plan,
        # THE PUBLISHED CATALOGUE, out of config/theatres/caucasus.toml.
        #
        # This used to scrape every module-level `Fix` out of `route.py`, which
        # is a fact about which Python module a name sits in and not about
        # whether anybody can look it up. So the 362nd's own turning points --
        # FEET WET, INGRESS, EGRESS, TSUTSNVATI -- were published to every
        # controller in every sortie as though they were navaids, and a pilot
        # asking for a steerpoint the controller could not resolve was offered
        # one of them. See #137.
        #
        # Still EVERY published fix and not just tonight's legs: a ferry up the
        # coast routes via KOBULETI, which no sortie leg touches, and a plan
        # naming a fix the table does not hold is refused at delivery.
        fixes=published_fixes("caucasus"),
        # ...AND THE MISSION'S OWN, out of `[sortie]` in the same file. Two
        # sections because they are two kinds of thing, which is the whole
        # point: what is published is a fact about the map, what is here goes
        # home with the sortie that flies it.
        waypoints=_sortie_wp("caucasus"),
        defended=sortie_defended("caucasus"),
        legs=_sortie_legs("caucasus"))


# WHICH NEVADA SORTIE. Two are filed and they recover at different fields, so
# where the flight is GOING is a fact about which sortie is being flown and not
# about the map.
#
#     "a flight that departs Nellis, works the range, and returns to Nellis
#      needs that profile and its arrival state during the same sortie. It
#      cannot be selected concurrently with the Tonopah recovery."
#                                                -- CODEX_NTTR_AUDIT.md
#
# THE APPROACH KEY CAME OUT OF THESE ROWS. They read
# `("nevada-nellis-nellis", "nellis-ils-21", "Nellis")`, and the middle value
# was the whole objection: the sortie chose a PROCEDURE, so every aeroplane in
# it was worked against one arrival whatever it had been cleared for. A sortie
# says where you depart and where you recover. Which approach you fly into
# Nellis is Approach's to issue and yours to accept, and Nellis publishes more
# than one. [#162]
#
# What survives is a departure, a filed plan and a destination FIELD, which are
# all facts about the mission. Per-flight selection of the procedure is #111
# and is now the only mechanism there is.
NEVADA_SORTIES = {
    "nellis": ("nevada-nellis-nellis", "Nellis"),
    "tonopah": ("nevada-nellis-tonopah", "Tonopah"),
}
# The one flown when nobody has said. A Nellis there-and-back is what a range
# sortie actually is, so it is the default and the transit is a flag away.
DEFAULT_SORTIE = "nellis"

# THE ROUTE IS THE SORTIE'S, NOT THE MAP'S, which is why it is a list of names
# here rather than a table in `nevada.toml`: a mission's turning points belong
# to the mission (docs/CONFIG.md), and publishing them is exactly what put FEET
# WET in front of every controller on the Caucasus. Names rather than
# coordinates, so the route cannot come to disagree with the catalogue it is
# drawn from. Nellis out to the VORTAC and home.
NEVADA_ROUTE = ("NELLIS", "TONOPAH", "NELLIS")


def nevada() -> Theatre:
    """Out of Nellis and home to Nellis, or one-way to Tonopah. ILS either end.

    A READER OVER `config/theatres/nevada.toml`, like `caucasus()` above. It
    used to build this object out of `core/nevada.py` -- two `Field_`s, nine
    `Station`s, two `Fix`es and two `ApproachProfile`s, all Python -- which is
    the half of #137 that stopped at the Caucasus.
    """
    from marshall.core import catalogue
    me = catalogue.identity("nevada")
    fields, stations = fields_now("nevada"), stations_now("nevada")
    procedures = approaches_now("nevada")
    # WHICH SORTIE. Two are filed, they recover at different fields, and the
    # bridge runs one arrival profile at a time -- so an unknown value is NAMED
    # rather than silently swapped for the default. It used to be
    # `NEVADA_SORTIES.get(want, NEVADA_SORTIES["nellis"])`, so `MARSHALL_SORTIE`
    # misspelt gave a bridge recovering at Nellis while its operator believed
    # he was going to Tonopah -- the same shape as the approach key, which is
    # how a pilot came to fly a talkdown after asking for an ILS.
    want = (os.environ.get("MARSHALL_SORTIE")
            or DEFAULT_SORTIE).strip().lower()
    if want not in NEVADA_SORTIES:
        print(f"  !! no sortie {want!r} on this map; Nevada files "
              f"{', '.join(sorted(NEVADA_SORTIES))} — falling back to "
              f"{DEFAULT_SORTIE!r}", flush=True)
        want = DEFAULT_SORTIE
    plan, arrival = NEVADA_SORTIES[want]
    # ONE CALL, so the numbered route and the published table hold the SAME
    # objects -- `NEVADA_ROUTE = [LSV, TPH, LSV]` was one Fix appearing twice,
    # and two copies that happen to agree is how they come to differ.
    fixes = fixes_now("nevada")
    at = {f.name: f for f in fixes}
    return Theatre(
        name=me.name, terrain=me.terrain, fields=fields, stations=stations,
        departure=me.departure, arrival=arrival,
        approaches=tuple(procedures.values()),
        wind_from_deg=me.wind_from_deg, wind_mph=me.wind_mph,
        bootstrap_plan=plan,
        fixes=fixes,
        waypoints=tuple(enumerate((at[n] for n in NEVADA_ROUTE), start=1)))


THEATRES = {"caucasus": caucasus, "nevada": nevada}


def current() -> Theatre:
    """The theatre every component in this process is working.

    A NAME NOBODY HAS IS SAID OUT LOUD. `THEATRES.get(want, caucasus)` silently
    swapped an unknown map for the Caucasus, so `MARSHALL_THEATRE=nevda` gave a
    bridge working Georgia while its operator believed it was in the desert --
    every frequency, fix and field real and belonging to the wrong continent.
    The same shape as the approach key: a wrong answer that looks exactly like
    a right one.
    """
    from marshall.core import catalogue
    want = os.environ.get("MARSHALL_THEATRE", "caucasus").strip().lower()
    if want not in THEATRES:
        print(f"  !! no theatre {want!r}. Configured maps: "
              f"{', '.join(catalogue.maps()) or 'none'} — falling back to "
              f"caucasus, which is probably not what you meant", flush=True)
    return THEATRES.get(want, caucasus)()


def verify(theatre: Theatre, eval_lua, timeout: float = 8.0,
           is_paused=None) -> tuple[bool, str]:
    """Is the map the sim has loaded the one we were told to work?

        "Should it get that info from the sim?"

    IN PRINCIPLE YES -- it is this project's own rule, that facts come from the
    sim and a component which guesses is wrong. In practice the obvious probes
    do not exist, and one of them is actively dangerous:

        env.mission.theatre    not exposed to the mission SCRIPTING environment;
                               it lives in the hook environment
        GetMissionName         works, and is a filename convention rather than a
                               fact about the terrain

    So the flag CHOOSES and the sim CHECKS. We convert a field this theatre
    claims to own and ask whether it lands where that field really is. A wrong
    theatre is not subtle: Batumi's metres on the Nevada map come back as
    36.29 N, 107.98 W -- instantly, and about a hundred and fifty degrees from
    where Batumi is.

    WHAT I GOT WRONG FIRST, twice, and the second correction is the useful one.

    I recorded that `coord.LOtoLL` HANGS on off-map coordinates and built the
    check around treating a timeout as proof of the wrong map. It does not hang;
    it answers instantly and wrongly, which is far more useful.

    I then explained the real hangs as "a freshly restarted server has not run
    its mission scripting environment yet". Also wrong, and vaguer than the
    truth: THE SIM WAS PAUSED. A dedicated server sets `pause_on_load`, so it
    boots paused and a client joining does not clear it -- and while it is
    paused the MISSION Lua state does not run, so `coord` never answers, while
    the HOOK Lua state answers normally and everything looks healthy. Measured
    both ways on the live server; see `feed/dcs.py`, which can now say which of
    the two it is instead of leaving a caller to guess.

    So a TIMEOUT IS NOT A FAILURE and is not evidence about the map at all. It
    is almost always a paused sim, which has a fix -- `tools/sim.py unpause` --
    rather than being something to wait out. Only a real answer in the wrong
    place is a refusal.

    `is_paused` is an optional callable answering the ONE question that explains
    almost every timeout here. Injected rather than imported, for the same reason
    `eval_lua` is: this module is `core` and the thing that knows how to ask the
    sim is `feed`, which is above it.

    Returns (ok, what to say). A failure is not raised: a controller who cannot
    reach the sim must still work, and this is the difference between "I cannot
    check" and "I checked and it is wrong".
    """
    def _why_silent() -> str:
        """Name the cause when we can, rather than shrug in prose."""
        if is_paused is None:
            return "The usual cause is a PAUSED sim."
        try:
            if is_paused():
                return ("The sim is PAUSED -- the mission scripting state does "
                        "not run while it is, so nothing here can answer. "
                        "`uv run python tools/sim.py unpause`.")
            return "The sim is running, so this is not a pause -- look at DCS-gRPC."
        except Exception:
            return "The usual cause is a PAUSED sim."
    f = next((x for x in theatre.fields if x.lat or x.lon), None)
    if f is None:
        return True, f"{theatre.name}: no field has a published position to check"
    lua = (f"local la, lo = coord.LOtoLL({{x={f.x}, y=0, z={f.z}}}) "
           f'return string.format("%.4f,%.4f", la, lo)')
    # A DAEMON THREAD, DELIBERATELY, AND NOT A ThreadPoolExecutor. The executor
    # version of this looked identical and did not honour its own timeout: the
    # `with` block's exit calls `shutdown(wait=True)`, so after `result(timeout=8)`
    # gave up it BLOCKED until the abandoned call finished anyway -- the full 25 s
    # gRPC deadline in `_eval_lua`. Against a paused sim that is a 25 s stall on
    # every bridge start, from a function whose whole contract is to give up at 8.
    #
    # Found by the tests in `tests/test_paused.py`, which passed and took two
    # minutes. A check that is right and slow is still telling you something.
    import threading
    box: dict = {}

    def _ask():
        try:
            box["got"] = eval_lua(lua)
        except BaseException as e:              # reported to the caller below
            box["err"] = e

    t = threading.Thread(target=_ask, daemon=True, name="theatre-verify")
    t.start()
    t.join(timeout)
    if t.is_alive() or ("got" not in box and "err" not in box):
        # Abandoned, not awaited. The thread is a daemon so it cannot hold the
        # process open, and its gRPC call carries its own deadline.
        return True, (
            f"{theatre.name}: the sim did not answer within {timeout:.0f}s "
            f"-- running on the flag alone. {_why_silent()} This is NOT "
            f"evidence about the map either way.")
    if "err" in box:
        return True, (f"{theatre.name}: could not check against the sim "
                      f"({type(box['err']).__name__}) -- running on the flag alone")
    try:
        got = str(box["got"]).strip('"').split(",")
        lat, lon = float(got[0]), float(got[1])
    except Exception as e:
        return True, (f"{theatre.name}: could not read the sim's answer "
                      f"({type(e).__name__}) -- running on the flag alone")
    off = ((lat - f.lat) ** 2 + (lon - f.lon) ** 2) ** 0.5
    if off < 1.0:
        return True, (f"{theatre.name}: confirmed against the sim — {f.name} "
                      f"converts to {lat:.3f}, {lon:.3f}")
    return False, (
        f"{theatre.name} is NOT the loaded map. {f.name}'s coordinates convert "
        f"to {lat:.3f}, {lon:.3f} and it should be {f.lat:.3f}, {f.lon:.3f} — "
        f"{off:.0f} degrees out. Every frequency, runway and vectoring minimum "
        f"this bridge holds belongs to another world. Start it with the right "
        f"--theatre.")
