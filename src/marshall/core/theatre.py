"""Which world this controller is working in.

    "Tell me what you mean that the bridge runs Caucasus profile."

ONE LINE, and everything downstream flowed from it:

    profile = load_and_push_plate(R.BATUMI_ASR)

That object is not just an approach. It carries the station list, so it decides
which frequencies the ear opens; `station_on` resolves it to whoever is speaking;
its geometry, minima and vectoring cells are the arrival. Beside it the ATIS
served `R.FIELDS` and the bootstrap wrote a Kobuleti-to-Batumi flight plan.

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

A THEATRE IS THE SELECTION, made once. The bridge takes its approach, its
fields, its stations and its bootstrap plan from here; the kneeboard builds its
Card from here. Two mechanisms for "which world" is how the radio and the chart
come to disagree, which is the one thing this project exists to prevent.

CHOSEN BY ENVIRONMENT AND NOT INFERRED. Reading the loaded mission sounds better
and is worse: the bridge and the kneeboard both start before anybody has told
the sim anything, and a component that guesses wrong is a controller working the
wrong map while sounding entirely normal.
"""

from __future__ import annotations

import os
from functools import lru_cache as _lru_cache
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theatre:
    """Everything that changes when the map does, and nothing that does not."""

    name: str
    terrain: str                      # the pydcs terrain, for the builders
    fields: tuple = ()
    stations: tuple = ()
    departure: str = ""
    arrival: str = ""
    # THE APPROACH THE BRIDGE RUNS. One per theatre today, because a bridge
    # works one arrival at a time -- see `load_and_push_plate`, which pushes it
    # to the director and reads it back as the source of truth.
    approach: object = None
    approaches: tuple = ()
    wind_from_deg: float = 0.0
    wind_mph: float = 0.0
    # The filed plan the bridge seeds and reads its approach from. Named here
    # rather than in the bridge so a migration and the bootstrap cannot
    # disagree -- see migrations/017 and 020.
    bootstrap_plan: str = ""
    # The key the approach is stored under in the director's `approaches` table.
    approach_key: str = ""
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
# `MARSHALL_APPROACH=batumi-ils`. The ASR stays the default because it is what
# has actually been flown; a default nobody has heard is not a default.
# GONE, and this is what it used to be:
#
#     CAUCASUS_RECOVERIES = {"batumi-asr": "BATUMI_ASR", ...}
#
# A key mapped to the NAME OF A PYTHON CONSTANT, so the set of arrivals a map
# offered lived in this module rather than with the map. A theatre file could
# publish a procedure that nothing was able to select, and adding one meant
# editing here as well as there. The keys are the file's now. See #137.


def published_approaches(fields=(), stations=(), theatre: str = "") -> dict:
    """The map's procedures, keyed, with the theatre's data composed back in.

    THIS IS WHERE THE TWO THINGS ARE PUT BACK TOGETHER, in one place and
    visibly. `ApproachProfile` carries `stations`, `msa_sectors` and
    `mva_cells` as well as the procedure, so every profile is the theatre's
    reference data welded to one arrival -- the unfinished half of #2, and the
    reason the bridge cannot hold the first without defaulting the second.

    The FILE holds only the procedure. The stations come from the theatre's own
    list and the minimum altitudes from the aerodrome the procedure names, so
    there is one copy of each and an approach cannot come to disagree with the
    field it serves. When #2 is finished this function is where the welding
    stops.
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
        want = [n for n in (a.beacon, a.outer_hold, a.arrival_fix, a.iaf)
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

    out = {}
    for a in catalogue.approaches(theatre):
        knobs = a.model_dump(exclude={"key", "field", "atc", "beacon",
                                      "outer_hold", "arrival_fix", "iaf",
                                      "theatre_stations", "own_point"})
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
        out[a.key] = R.ApproachProfile(
            beacon=role(a.beacon), outer_hold=role(a.outer_hold),
            arrival_fix=role(a.arrival_fix), iaf=role(a.iaf),
            atc=R.AtcCapability(**a.atc.model_dump(exclude_none=True)),
            stations=list(stations) if a.theatre_stations else [],
            msa_sectors=[tuple(s) for s in (f.msa_sectors if f else [])],
            mva_cells=[tuple(c) for c in (f.mva_cells if f else [])],
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
# `R.KOB_CLEARANCE is profile.stations[0]` went false, which several tests
# assert precisely because identity is the cheapest way to say "the same
# controller, not a copy that happens to match".
@_lru_cache(maxsize=4)
def _stations_cached(name: str) -> tuple:
    return published_stations(name)


@_lru_cache(maxsize=4)
def _fields_cached(name: str) -> tuple:
    return published_fields(name)


@_lru_cache(maxsize=4)
def _approaches_cached(name: str) -> dict:
    return published_approaches(_fields_cached(name), _stations_cached(name),
                                name)


def stations_now(theatre: str = "") -> tuple:
    """The configured map's controllers -- ONE object per seat."""
    return _stations_cached(_map_name(theatre))


def fields_now(theatre: str = "") -> tuple:
    """The configured map's aerodromes -- ONE object per field."""
    return _fields_cached(_map_name(theatre))


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
        R.Fix(f.name, f.ident, f.x, f.z, f.freq_mhz or None,
              sector=f.sector, note=f.note, navaid=f.navaid or "ndb",
              lat=f.lat, lon=f.lon)
        for f in catalogue.published_fixes(theatre))


def caucasus() -> Theatre:
    """The 362nd. Kobuleti to Batumi, radar recovery, 1944 flavour available."""
    from marshall.core import catalogue
    from marshall.core import route as R
    # NAMES ITS OWN MAP. These read `MARSHALL_THEATRE` underneath, so when
    # `current()` fell back to this function after a misspelt name, every
    # loader went looking for `nevda.toml` again and the fallback landed
    # nowhere. A function that IS the Caucasus theatre should not have to ask
    # which theatre it is.
    me = catalogue.identity("caucasus")
    fields, stations = fields_now("caucasus"), stations_now("caucasus")
    procedures = approaches_now("caucasus")
    # WHICH RECOVERY. `CAUCASUS_RECOVERIES` mapped a key to the NAME OF A
    # PYTHON CONSTANT, so the set of arrivals a map offered was a dict in this
    # module -- and a theatre file could add a procedure that nothing could
    # select. The keys are the file's now, and an unknown one is named rather
    # than silently swapped for the default, which is how a pilot came to fly a
    # talkdown after asking for an ILS.
    want = (os.environ.get("MARSHALL_APPROACH")
            or me.default_approach).strip().lower()
    if want not in procedures:
        print(f"  !! no approach {want!r} on this map; the theatre publishes "
              f"{', '.join(sorted(procedures))} — falling back to "
              f"{me.default_approach!r}", flush=True)
        want = me.default_approach
    recovery = procedures[want]
    return Theatre(
        name=me.name, terrain=me.terrain, fields=fields,
        stations=stations, departure=me.departure,
        arrival=me.arrival, approach=recovery,
        approaches=tuple(procedures.values()),
        wind_from_deg=me.wind_from_deg, wind_mph=me.wind_mph,
        bootstrap_plan=me.bootstrap_plan, approach_key=want,
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
        waypoints=tuple(R.sortie_points()),
        defended=tuple(R.DEFENDED), legs=tuple(R.SORTIE_LEGS))


# WHICH NEVADA SORTIE. Two are filed and they recover at different fields, so
# they cannot both be the bridge's active approach -- it runs one arrival profile
# at a time (see `load_and_push_plate`).
#
#     "a flight that departs Nellis, works the range, and returns to Nellis
#      needs that profile and its arrival state during the same sortie. It
#      cannot be selected concurrently with the Tonopah recovery."
#                                                -- CODEX_NTTR_AUDIT.md
#
# Right, and per-flight selection is the real answer (#111). Until then the
# choice is at least EXPLICIT and steerable rather than baked in: a Nellis
# there-and-back is what a range sortie actually is, so it is the default, and
# the one-way transit to Tonopah is a flag away.
#
# The default CHANGED with this. A bridge started on Nevada used to load the
# Tonopah recovery, which is the wrong end of the flight for a pilot going home.
NEVADA_SORTIES = {
    "nellis": ("nevada-nellis-nellis", "nellis-ils", "Nellis"),
    "tonopah": ("nevada-nellis-tonopah", "tonopah-ils", "Tonopah"),
}


def nevada() -> Theatre:
    """Out of Nellis and home to Nellis, or one-way to Tonopah. ILS either end."""
    from marshall.core import nevada as N
    want = os.environ.get("MARSHALL_SORTIE", "nellis").strip().lower()
    plan, key, arrival = NEVADA_SORTIES.get(want, NEVADA_SORTIES["nellis"])
    profile = N.NELLIS_ILS if arrival == "Nellis" else N.TONOPAH_ILS
    return Theatre(
        name="Nevada", terrain="Nevada", fields=tuple(N.NEVADA_FIELDS),
        stations=tuple(N.NEVADA_STATIONS), departure="Nellis",
        arrival=arrival, approach=profile,
        approaches=(N.NELLIS_ILS, N.TONOPAH_ILS),
        wind_from_deg=210.0, wind_mph=9.2,
        bootstrap_plan=plan, approach_key=key,
        # NEVADA_FIXES has existed since the map was added and nothing read it.
        fixes=tuple(N.NEVADA_FIXES),
        waypoints=tuple(enumerate(N.NEVADA_ROUTE, start=1)))


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
