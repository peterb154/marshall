"""Approaches (static) + flight plans (dynamic), in Postgres.

An **approach** is a published procedure for a field — the serialized
`ApproachProfile` (beacon, ladder, headings, timing, capability), reusable across
missions. A **flight plan** is a per-sortie record: which flight, and which
approach it flies; one is `active`. The ATC plate is generated from the active
flight plan's approach, so loading a different flight plan re-aims the controller
without touching code. `route.py` seeds the first records; the DB is the source.
"""

from __future__ import annotations

import logging

from psycopg.types.json import Json

from marshall.core.db import pool as get_pool

log = logging.getLogger(__name__)
_ready = False


def _ensure() -> None:
    global _ready
    if _ready:
        return
    with get_pool().connection() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS approaches (
                name       TEXT PRIMARY KEY,
                field      TEXT,
                data       JSONB NOT NULL,          -- serialized ApproachProfile
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS flight_plans (
                name       TEXT PRIMARY KEY,
                callsign   TEXT,
                approach   TEXT REFERENCES approaches(name),
                weather    TEXT,
                active     BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """)
    _ready = True


def upsert_approach(name: str, field: str, data: dict) -> None:
    _ensure()
    with get_pool().connection() as c:
        c.execute(
            "INSERT INTO approaches (name, field, data) VALUES (%s, %s, %s) "
            "ON CONFLICT (name) DO UPDATE SET field=EXCLUDED.field, data=EXCLUDED.data",
            (name, field, Json(data)))


def replace_approaches(rows: list[dict]) -> int:
    """Publish THIS map's whole offer, and drop what is not in it.

    `set_stations`' bargain, taken verbatim: whatever the push no longer has,
    the table no longer has. `upsert_approach` alone made this table a LOG of
    every procedure any run had ever selected rather than a statement about the
    map that is loaded, and the live table proved it -- six rows spanning two
    continents, so a Caucasus controller asked what approaches were available
    would have been offered Nellis and Tonopah.

    That is the identical defect `frequencies.py` records finding in `stations`:
    *"The rows this reads accumulate across every theatre ever loaded and it
    used to take the alphabetically first, so a Nellis controller asked for
    Tonopah's tower was told there is no such position and offered Batumi and
    Kobuleti instead."* The fix there was to replace the table on every push.
    Same fix, same reason, one table over. [#176]

    A stale row here is worse than a stale station: it is a real minimum at a
    real aerodrome on the wrong continent, and a minimum is an altitude
    somebody descends to.

    Rows are `{"name", "field", "data"}`. An EMPTY list is refused rather than
    obeyed -- a push that computed nothing must not empty the table, because
    the failure that would cause (a controller who can name no approach at all)
    looks exactly like a map that publishes none.
    """
    if not rows:
        return 0
    _ensure()
    with get_pool().connection() as c, c.transaction():
        names = [r["name"] for r in rows]
        for r in rows:
            c.execute(
                "INSERT INTO approaches (name, field, data) "
                "VALUES (%s, %s, %s) ON CONFLICT (name) DO UPDATE SET "
                "field=EXCLUDED.field, data=EXCLUDED.data",
                (r["name"], r.get("field", ""), Json(r["data"])))
        c.execute("DELETE FROM approaches WHERE name <> ALL(%s)", (names,))
    return len(rows)


def get_approach(name: str) -> dict | None:
    _ensure()
    with get_pool().connection() as c:
        r = c.execute("SELECT name, field, data FROM approaches WHERE name=%s",
                      (name,)).fetchone()
    return {"name": r[0], "field": r[1], "data": r[2]} if r else None


def list_approaches() -> list[dict]:
    _ensure()
    with get_pool().connection() as c:
        rows = c.execute("SELECT name, field FROM approaches ORDER BY name").fetchall()
    return [{"name": n, "field": f} for n, f in rows]


# `upsert_flight_plan` WAS HERE AND IS DELETED. It inserted `callsign`,
# `approach`, `weather` and `active` into `flight_plans`, and three of those
# columns stopped existing when #142 split a plan from the approach somebody
# flies it on. It could not have worked:
#
#     ERROR: column "approach" of relation "flight_plans" does not exist
#
# Nothing in the repo called it -- it was reachable only over HTTP, as
# `PUT /flightplans/{name}`, which is deleted with it. Filing goes through
# `filing.file_plan` and has since #142.
#
# `list_flight_plans` below is NOT the same story and stays: it is rung 2 of the
# identity chain, `agent_atc.filed_plans` reads it every sortie, and its SELECT
# was corrected at the time.

def list_flight_plans() -> list[dict]:
    """Every filed plan, as the rest of the system speaks about one.

    NO `callsign`, AND THAT IS THE FIX. This selected `name, callsign` and
    nothing else, so the wire carried two strings of which one is NULL on every
    row -- #142 retired the idea that a plan belongs to an aeroplane, because
    which aircraft flies it is a fact about a CLEARANCE. Nothing has written
    that column since, and four separate readers went on asking for it:

        filed_plans()   built its whole set from it, so the set was empty
        Identity.plan   matched against that set, so it was never assigned
        plan_of         joined on the label the payload did not carry
        _plan_row       still joins on it

    The strip on /diag was therefore blank for every aeroplane that has ever
    been on that board, and `816c97e` fixed only the third of the four. [#167]

    `label` is what a pilot SAYS -- "request IFR clearance to Batumi, Domino
    please" -- and is what `Identity.plan` was always matching against.
    `derived` adds `route`, `destination` and `cruise_ft`, which are not
    columns (migration 031) and have exactly one author; computing them here
    means the wire and the board cannot come to disagree the way `route` and
    `legs` did on the live board before they were removed.

    NO `approach` AND NO `active` either, for the same reason as before: a plan
    does not name an arrival (#2), and `active` was how `marshall-atc` used to
    read its own procedure out of a plan row, which is #131.
    """
    from marshall.atc.filing import derived
    _ensure()
    with get_pool().connection() as c:
        rows = c.execute("SELECT name, label, legs, task, origin "
                         "FROM flight_plans ORDER BY name").fetchall()
    # `origin` SINCE #218: a plan may say where it DEPARTS from, because a DKS
    # design carries `startPoint` and a cartridge never did. Carried here so the
    # bridge sees it -- without it the column would be filed and invisible to
    # everything reading plans over the wire.
    return [derived({"name": n, "label": lb or "", "legs": lg or [],
                     "task": tk or "", "origin": og or ""})
            for n, lb, lg, tk, og in rows]


def active_flight_plan() -> dict | None:
    """Always None. THERE IS NO ACTIVE PLAN, and there should never have been.

        "i dont understand this active business. sounds like mis-alignment
         between you and me"
        "whyt would the bridge load a default approach column?? doesnt make
         sense"

    Right on both counts. This read `flight_plans` for a row with `active` set
    and joined it to the approach that row named -- two columns that are gone
    (migration 031) because neither was a fact about a flight plan. Which
    arrival is being flown is a property of a CLEARANCE (#2), and `marshall-atc`
    reading its own procedure out of a plan row is #131, which cost a sortie.

    KEPT AS A FUNCTION rather than deleted, because callers ask it a reasonable
    question and None is the honest answer: nothing is "loaded". Deleting it
    would push the same guess into whoever calls it next.
    """
    return None
