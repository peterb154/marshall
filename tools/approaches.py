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

from strands_pg._pool import get_pool

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
        rows = c.execute("SELECT name, callsign, approach, active FROM flight_plans "
                         "ORDER BY name").fetchall()
    return [{"name": n, "callsign": cs, "approach": a, "active": act}
            for n, cs, a, act in rows]


def active_flight_plan() -> dict | None:
    """The loaded flight plan joined with its approach — what the plate reads."""
    _ensure()
    with get_pool().connection() as c:
        r = c.execute(
            "SELECT f.name, f.callsign, f.weather, a.name, a.field, a.data "
            "FROM flight_plans f JOIN approaches a ON a.name=f.approach "
            "WHERE f.active LIMIT 1").fetchone()
    if not r:
        return None
    return {"name": r[0], "callsign": r[1], "weather": r[2],
            "approach": {"name": r[3], "field": r[4], "data": r[5]}}
