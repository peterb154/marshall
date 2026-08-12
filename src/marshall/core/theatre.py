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
CAUCASUS_RECOVERIES = {
    "batumi-asr": "BATUMI_ASR",
    "batumi-ils": "BATUMI_ILS",
    "batumi-ndb": "BATUMI_APPROACH",
}


def published_fixes() -> tuple:
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
              note=f.note, navaid=f.navaid or "ndb", lat=f.lat, lon=f.lon)
        for f in catalogue.published_fixes())


def caucasus() -> Theatre:
    """The 362nd. Kobuleti to Batumi, radar recovery, 1944 flavour available."""
    from marshall.core import route as R
    want = os.environ.get("MARSHALL_APPROACH", "batumi-asr").strip().lower()
    if want not in CAUCASUS_RECOVERIES:
        want = "batumi-asr"
    recovery = getattr(R, CAUCASUS_RECOVERIES[want])
    return Theatre(
        name="Caucasus", terrain="Caucasus", fields=tuple(R.FIELDS),
        stations=tuple(R.STATIONS), departure=R.DEPARTURE_FIELD,
        arrival=R.ARRIVAL_FIELD, approach=recovery,
        approaches=(R.BATUMI_ASR, R.BATUMI_ILS, R.BATUMI_APPROACH,
                    R.KOBULETI_ILS),
        wind_from_deg=R.WIND_FROM_DEG, wind_mph=R.WIND_MPH,
        bootstrap_plan="362nd-kobuleti-batumi", approach_key=want,
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
        fixes=published_fixes(),
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
    """The theatre every component in this process is working."""
    want = os.environ.get("MARSHALL_THEATRE", "caucasus").strip().lower()
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
