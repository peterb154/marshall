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


def upsert_flight_plan(name: str, callsign: str, approach: str,
                       weather: str = "", active: bool = False) -> None:
    _ensure()
    with get_pool().connection() as c:
        if active:
            c.execute("UPDATE flight_plans SET active=false")   # one active at a time
        c.execute(
            "INSERT INTO flight_plans (name, callsign, approach, weather, active) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (name) DO UPDATE SET "
            "callsign=EXCLUDED.callsign, approach=EXCLUDED.approach, "
            "weather=EXCLUDED.weather, active=EXCLUDED.active",
            (name, callsign, approach, weather, active))


def list_flight_plans() -> list[dict]:
    _ensure()
    with get_pool().connection() as c:
        rows = c.execute("SELECT name, callsign FROM flight_plans "
                         "ORDER BY name").fetchall()
    # NO `approach` AND NO `active`. A plan does not name an arrival -- which
    # one you fly is a fact about your clearance (#2) -- and `active` was how
    # `marshall-atc` used to read its own procedure out of a plan row, which is
    # #131. Both columns are gone; see migration 031.
    return [{"name": n, "callsign": cs} for n, cs in rows]


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
