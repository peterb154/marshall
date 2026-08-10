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
    extra: dict = field(default_factory=dict)

    def field_named(self, name: str):
        return next((f for f in self.fields
                     if f.name.lower() == (name or "").lower()), None)


def caucasus() -> Theatre:
    """The 362nd. Kobuleti to Batumi, radar recovery, 1944 flavour available."""
    from marshall.core import route as R
    return Theatre(
        name="Caucasus", terrain="Caucasus", fields=tuple(R.FIELDS),
        stations=tuple(R.STATIONS), departure=R.DEPARTURE_FIELD,
        arrival=R.ARRIVAL_FIELD, approach=R.BATUMI_ASR,
        approaches=(R.BATUMI_ASR, R.BATUMI_APPROACH, R.KOBULETI_ILS),
        wind_from_deg=R.WIND_FROM_DEG, wind_mph=R.WIND_MPH,
        bootstrap_plan="362nd-kobuleti-batumi", approach_key="batumi-asr")


def nevada() -> Theatre:
    """Nellis to Tonopah, ILS at both ends, a mile and a half of terrain."""
    from marshall.core import nevada as N
    return Theatre(
        name="Nevada", terrain="Nevada", fields=tuple(N.NEVADA_FIELDS),
        stations=tuple(N.NEVADA_STATIONS), departure="Nellis",
        arrival="Tonopah", approach=N.TONOPAH_ILS,
        approaches=(N.TONOPAH_ILS, N.NELLIS_ILS),
        wind_from_deg=210.0, wind_mph=9.2,
        bootstrap_plan="nevada-nellis-tonopah", approach_key="tonopah-ils")


THEATRES = {"caucasus": caucasus, "nevada": nevada}


def current() -> Theatre:
    """The theatre every component in this process is working."""
    want = os.environ.get("MARSHALL_THEATRE", "caucasus").strip().lower()
    return THEATRES.get(want, caucasus)()


def verify(theatre: Theatre, eval_lua, timeout: float = 8.0) -> tuple[bool, str]:
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

    TWO THINGS I GOT WRONG FIRST, both worth keeping written down.

    I recorded that `coord.LOtoLL` HANGS on off-map coordinates and built the
    check around treating a timeout as proof of the wrong map. It does not hang;
    it answers instantly and wrongly, which is far more useful. The hangs were
    the sim's Eval service being unreachable at all -- `return "hello"` timed out
    the same way -- because a freshly restarted server has not run its mission
    scripting environment yet. A conclusion drawn while one component was down,
    and attributed to the component being measured.

    So a TIMEOUT IS NOT A FAILURE. It means the sim did not answer, which is a
    different thing from answering wrongly, and a controller who cannot reach the
    sim must still come up and work. Only a real answer in the wrong place is a
    refusal.

    Returns (ok, what to say). A failure is not raised: a controller who cannot
    reach the sim must still work, and this is the difference between "I cannot
    check" and "I checked and it is wrong".
    """
    f = next((x for x in theatre.fields if x.lat or x.lon), None)
    if f is None:
        return True, f"{theatre.name}: no field has a published position to check"
    lua = (f"local la, lo = coord.LOtoLL({{x={f.x}, y=0, z={f.z}}}) "
           f'return string.format("%.4f,%.4f", la, lo)')
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(eval_lua, lua)
        try:
            got = str(fut.result(timeout=timeout)).strip('"').split(",")
            lat, lon = float(got[0]), float(got[1])
        except _cf.TimeoutError:
            return True, (
                f"{theatre.name}: the sim did not answer within {timeout:.0f}s "
                f"-- running on the flag alone. A freshly restarted server has "
                f"not started its scripting environment, so this is normal "
                f"right after a deploy and is NOT evidence of the wrong map.")
        except Exception as e:
            return True, (f"{theatre.name}: could not check against the sim "
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
