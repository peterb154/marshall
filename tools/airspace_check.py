"""Two terminal areas overlap now, and the nearer field must win.

#139 removed the midpoint split. It existed so two aerodromes could not claim
the same sky, and what it produced was absurd: Kobuleti and Batumi are 22.6 nm
apart, so both terminal areas were eleven-mile circles -- while Batumi's ILS
holds at KOBULETI, twenty-two miles out. The procedure began at double the
radius of the airspace that owned it, so "he is outside my airspace" fired on a
man flying the approach exactly as published.

Areas are derived from the procedures they serve now and they overlap. That
reintroduces a hazard the old test named in so many words:

    "which is what happened on the first attempt at this, when both were given
     the full terminal range and an aeroplane on Kobuleti's ramp resolved to
     Batumi Approach."

THE REMEDY IS IN SQL, so the check has to be. Migration 034 orders the
containing sectors by rank and then by the nearer centre, and no unit test can
see that: `flight_airspace` is a view, the rule is an ORDER BY, and asserting
it by reading the migration text proves the file says something rather than
that the database does it.

    uv run python tools/airspace_check.py

Needs the compose stack up. Exits non-zero when an aeroplane standing at one
aerodrome is judged to be somebody else's.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MISSION = "airspacecheck"


def psql(sql: str) -> str:
    """Straight at the database, because there is no door for this.

    The tracks table has no HTTP endpoint -- the feed writes it directly, being
    the only thing that ever should -- and `marshall.core.db` wants a DSN a
    host process is not given. `docker compose exec` is what the operator
    already uses and needs no new configuration and no new route into the
    director for the sake of a check.
    """
    got = subprocess.run(
        ["docker", "compose", "exec", "-T", "db",
         "psql", "-U", "strands", "-d", "strands", "-Atc", sql],
        cwd=str(ROOT / "services"), capture_output=True, text=True)
    if got.returncode:
        raise RuntimeError((got.stderr or got.stdout).strip()[:400])
    return got.stdout.strip()


def place(callsign: str, lat: float, lon: float, alt_ft: float) -> None:
    """One aeroplane, standing still, exactly where we say."""
    psql(f"""
        INSERT INTO tracks (name, label, type, coalition, geog, alt_ft,
                            heading, last_seen, speed_kt, player, category,
                            in_air)
        VALUES ('{callsign}', '{callsign}', 'F-16C_50', 2,
                ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography,
                {alt_ft}, 0, now(), 0, '{callsign}', 'airplane', true)
        ON CONFLICT (name) DO UPDATE SET
            geog = EXCLUDED.geog, alt_ft = EXCLUDED.alt_ft,
            last_seen = EXCLUDED.last_seen;
        DELETE FROM flights
              WHERE mission = '{MISSION}' AND callsign = '{callsign}';
        INSERT INTO flights (mission, callsign, track_name)
        VALUES ('{MISSION}', '{callsign}', '{callsign}');""")
    # DELETE THEN INSERT, RATHER THAN `ON CONFLICT DO NOTHING`.
    #
    # That is how this check failed on its own first run. An earlier attempt
    # bound the flight over HTTP and never wrote a track, so a `flights` row
    # existed carrying no usable `track_name` -- and `DO NOTHING` left it
    # exactly as it was. The view LEFT JOINs the track, found none, and
    # `ST_Intersects` on a NULL geography is not true, so the aeroplane fell
    # through to the unbounded Center. Reported as "overhead Batumi ->
    # georgia-center", which reads precisely like the airspace bug this check
    # exists to find.
    #
    # A stale row does not hide a failure here, it CAUSES one -- the same
    # sentence `feed.tracks.set_fixes` already carries about its own table.


def owner(callsign: str) -> str:
    return psql(
        f"SELECT COALESCE(should_be_with, '') FROM flight_airspace "
        f"WHERE mission = '{MISSION}' AND callsign = '{callsign}' LIMIT 1")


def push(rows: list[dict]) -> None:
    """The volumes this code derives, so the check cannot pass against the
    geometry a previous bridge happened to leave behind."""
    psql("DELETE FROM sectors WHERE name LIKE '%-approach' "
         "OR name LIKE '%-tower'")
    for r in rows:
        if r["radius_nm"] is None:
            continue
        psql(f"""
            INSERT INTO sectors (name, label, role, field, freq_mhz, rank,
                                 floor_ft, ceiling_ft, volume)
            VALUES ('{r["name"]}', '{r["label"]}', '{r["role"]}',
                    '{r["field"]}', {r["freq_mhz"] or 0}, {r["rank"]},
                    {r["floor_ft"] if r["floor_ft"] is not None else "NULL"},
                    {r["ceiling_ft"] if r["ceiling_ft"] is not None else "NULL"},
                    ST_Buffer(ST_SetSRID(ST_MakePoint({r["lon"]}, {r["lat"]}),
                                         4326)::geography,
                              {r["radius_nm"]} * 1852))
            ON CONFLICT (name) DO UPDATE SET volume = EXCLUDED.volume,
                rank = EXCLUDED.rank, ceiling_ft = EXCLUDED.ceiling_ft;""")


def clean() -> None:
    psql(f"DELETE FROM flights WHERE mission = '{MISSION}'; "
         f"DELETE FROM tracks WHERE name LIKE 'Overhead-%' "
         f"OR name LIKE 'Hold-%';")


def main() -> int:
    from marshall.core import airspace as A
    from marshall.core import geo
    from marshall.core import theatre as T

    fields = list(T.fields_now())
    if len(fields) < 2:
        print(f"{T._map_name()}: one aerodrome, so nothing can overlap -- "
              f"this check has nothing to say here")
        return 0

    # PUSHED FROM WHAT THE CODE DERIVES, not read from whatever a bridge left
    # behind. A stale `sectors` table would make this check pass against the
    # geometry of an earlier run, which is the failure it exists to catch.
    rows = A.sectors_for(fields, list(T.stations_now()))
    try:
        push(rows)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"the database is not reachable: {e}\n"
              f"  Needs `cd director && docker compose up -d`.", file=sys.stderr)
        return 1

    for f in fields:
        others = [o for o in fields if o is not f]
        print(f"  {f.name:10} area {A.terminal_reach_nm(f, others):5.1f} nm")

    bad = []

    # 1. AT THE FIELD ITSELF. Above the circuit ceiling, so Tower's volume is
    #    out of it and the two TERMINAL areas are the only candidates -- which
    #    is the tie the rank cannot break and the whole point of the check.
    for f in fields:
        cs = f"Overhead-{f.name}"
        place(cs, f.lat, f.lon, 8000.0)
        got = owner(cs)
        want = f"{f.name.lower()}-approach"
        print(f"  overhead {f.name:10} -> {got or '(nobody)'}")
        if got != want:
            bad.append(f"overhead {f.name}: {got or 'nobody'}, not {want}")

    # 2. AT THE FURTHEST FIX OF EACH APPROACH. The place the old geometry put
    #    outside its own terminal area, and the reason #139 exists.
    for key, p in T.approaches_now().items():
        fld = next((x for x in fields if x.name.lower()
                    == getattr(p.aerodrome, "name", "").lower()), None)
        fix = getattr(p, "outer_hold", None) or getattr(p, "iaf", None)
        if fld is None or fix is None or getattr(fix, "lat", None) is None:
            continue
        nm, _ = geo.range_bearing_true((fld.lat, fld.lon), fix.lat, fix.lon)
        cs = f"Hold-{key}"
        place(cs, fix.lat, fix.lon, 8000.0)
        got = owner(cs)
        want = f"{fld.name.lower()}-approach"
        print(f"  {key:18} hold {fix.name:9} {nm:5.1f} nm -> "
              f"{got or '(nobody)'}")
        # NEARER FIELD WINS, and at another aerodrome's overhead that is the
        # OTHER field -- correctly. Batumi's ILS holds at KOBULETI, which is
        # Kobuleti's overhead: the man is in both areas and the nearer one has
        # him, which is what a radar room does. So this is only a failure when
        # NOBODY holds him, or when a Center does.
        if not got or got.endswith("center"):
            bad.append(f"{key} at {fix.name} ({nm:.1f} nm): {got or 'nobody'}")
        elif got != want:
            print("       .. the nearer field has him, which is correct")

    print()
    if bad:
        print("AIRSPACE DOES NOT RESOLVE")
        for b in bad:
            print(f"  {b}")
        print("  Two overlapping terminal areas are ordered by rank and then "
              "by the\n  nearer centre -- see migration 034. An aeroplane that "
              "falls through to\n  a Center at its own field's overhead means "
              "the volumes were not pushed,\n  or the view is the pre-034 one.")
        return 1
    print("airspace resolves: every field owns its own overhead, and every "
          "approach's\nfurthest fix is held by a terminal area rather than "
          "falling through to Center")
    return 0


def run() -> int:
    try:
        return main()
    finally:
        # ALWAYS, even on a failure. Rows left behind would be picked up by the
        # next bridge's board as ghost aircraft parked over two aerodromes.
        try:
            clean()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(run())
