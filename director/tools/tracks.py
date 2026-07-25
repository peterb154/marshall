"""Live track cache — DCS-gRPC unit stream mirrored into PostGIS.

Reading radar meant fanning out several gRPC calls to the sim on every pilot
call, every hook, every scheduler tick. Instead we subscribe once to
``mission.StreamUnits`` and keep a ``tracks`` table current: upsert on a unit
update, delete on ``gone``. Radar then reads one indexed PostGIS query, and the
geo is native -- range and radial come from ``ST_Distance`` / ``ST_Azimuth``, and
"which track is near his reported position" is a spatial nearest-neighbour, which
is where correlation is heading.

Freshness is explicit: the sim PAUSES when empty, so the stream stops and rows go
stale. Every read filters on ``last_seen`` -- a stale track reads as no-contact,
never as confidently-wrong. Live gRPC (dcs.radar_live) stays as the fallback if
the cache is cold.
"""

from __future__ import annotations

import logging
import threading
import time

import grpc

try:
    from strands import tool
except ImportError:
    def tool(fn):
        return fn

from strands_pg._pool import get_pool
from tools.dcs import BATUMI_LAT, BATUMI_LON, DCS_GRPC_ADDR, _M_TO_FT

_MAGVAR = 6.0   # Caucasus magnetic variation (E); pilots fly magnetic headings
# Named fixes we can vector to, as lat/lon. Batumi is the beacon/field; more fixes
# join here once route.py's DCS metres are projected to lat/lon.
_FIXES = {"batumi": (BATUMI_LAT, BATUMI_LON), "the field": (BATUMI_LAT, BATUMI_LON),
          "the beacon": (BATUMI_LAT, BATUMI_LON), "home": (BATUMI_LAT, BATUMI_LON)}

from dcs.common.v0 import common_pb2
from dcs.mission.v0 import mission_pb2, mission_pb2_grpc

log = logging.getLogger(__name__)

FRESH_SEC = 15          # a track older than this is stale -> not shown
_ready = False
_started = False
_lock = threading.Lock()


def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    with get_pool().connection() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                name       TEXT PRIMARY KEY,
                label      TEXT,
                type       TEXT,
                coalition  INT,
                geog       geography(Point, 4326),
                alt_ft     DOUBLE PRECISION,
                heading    DOUBLE PRECISION,
                last_seen  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """)
        conn.execute("CREATE INDEX IF NOT EXISTS tracks_geog ON tracks USING GIST (geog)")
    _ready = True


def _upsert(u) -> None:
    label = u.player_name or u.callsign or u.name
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO tracks (name, label, type, coalition, geog, alt_ft, heading, last_seen)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s, %s, now())
            ON CONFLICT (name) DO UPDATE SET
                label=EXCLUDED.label, type=EXCLUDED.type, coalition=EXCLUDED.coalition,
                geog=EXCLUDED.geog, alt_ft=EXCLUDED.alt_ft, heading=EXCLUDED.heading,
                last_seen=now()
            """,
            (u.name, label, u.type, u.coalition, u.position.lon, u.position.lat,
             u.position.alt * _M_TO_FT, u.orientation.heading))


def _delete(name: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM tracks WHERE name=%s", (name,))


def _stream_category(category: int, stop: threading.Event) -> None:
    """Follow one category's unit stream, reconnecting with backoff."""
    backoff = 1.0
    while not stop.is_set():
        try:
            ch = grpc.insecure_channel(DCS_GRPC_ADDR)
            stub = mission_pb2_grpc.MissionServiceStub(ch)
            req = mission_pb2.StreamUnitsRequest(poll_rate=1, max_backoff=5,
                                                 category=category)
            for resp in stub.StreamUnits(req):
                if stop.is_set():
                    break
                backoff = 1.0
                if resp.HasField("unit"):
                    _upsert(resp.unit)
                elif resp.HasField("gone"):
                    _delete(resp.gone.name)
        except grpc.RpcError as e:
            log.warning("StreamUnits(%s) dropped: %s; retry in %.0fs",
                        category, str(e)[:60], backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 15)


def start_streamer() -> None:
    """Start the position stream in the background (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _ensure_table()
        stop = threading.Event()
        for cat in (common_pb2.GROUP_CATEGORY_AIRPLANE,
                    common_pb2.GROUP_CATEGORY_HELICOPTER):
            threading.Thread(target=_stream_category, args=(cat, stop),
                             daemon=True).start()
        _started = True
        log.info("track streamer started")


def _resolve(name: str) -> tuple[float, float] | None:
    """A target name -> (lat, lon): a named fix, else a fresh radar track (matched
    on its scope label or unit name)."""
    key = (name or "").strip().lower()
    if key in _FIXES:
        return _FIXES[key]
    try:
        with get_pool().connection() as conn:
            r = conn.execute(
                "SELECT ST_Y(geog::geometry), ST_X(geog::geometry) FROM tracks "
                "WHERE (lower(label) = %s OR lower(name) = %s) "
                "AND last_seen > now() - make_interval(secs => %s) LIMIT 1",
                (key, key, FRESH_SEC)).fetchone()
        return (r[0], r[1]) if r else None
    except Exception as e:
        log.warning("_resolve(%s) failed: %s", name, e)
        return None


@tool
def vector(from_contact: str, to: str) -> str:
    """Compute a radar vector -- the magnetic heading and distance from one aircraft
    to a target -- deterministically off the live track cache. `from_contact` is the
    requesting aircraft's radar label (e.g. 'Enfield11'); `to` is a fix name
    ('Batumi', 'the field') OR another aircraft's radar label (for a join-up).
    Returns 'heading XXX, N miles'. Use it when a pilot asks for vectors, a heading,
    or a distance -- the geometry is exact here, never estimated."""
    a, b = _resolve(from_contact), _resolve(to)
    if not a:
        return f"No radar contact on '{from_contact}' -- can't vector from it."
    if not b:
        return f"No radar contact on '{to}' -- can't vector to it."
    with get_pool().connection() as conn:
        brg, nm = conn.execute(
            "SELECT degrees(ST_Azimuth("
            "  ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,"
            "  ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)),"
            " ST_Distance("
            "  ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,"
            "  ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) / 1852.0",
            (a[1], a[0], b[1], b[0], a[1], a[0], b[1], b[0])).fetchone()
    return f"{to}: heading {(brg - _MAGVAR) % 360:03.0f}, {nm:.0f} miles"


def radar_cached(bindings: dict | None = None) -> list[str] | None:
    """Radar lines from the PostGIS cache (fresh tracks only), or None if the
    cache can't be read so the caller falls back to a live gRPC scan."""
    bindings = bindings or {}
    try:
        _ensure_table()
        with get_pool().connection() as conn:
            rows = conn.execute(
                """
                WITH bcn AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS g)
                SELECT t.label, t.type, t.alt_ft, t.heading,
                       ST_Distance(t.geog, bcn.g) / 1852.0 AS nm,
                       degrees(ST_Azimuth(bcn.g, t.geog)) AS radial
                FROM tracks t, bcn
                WHERE t.last_seen > now() - make_interval(secs => %s)
                ORDER BY nm
                """,
                (BATUMI_LON, BATUMI_LAT, FRESH_SEC)).fetchall()
    except Exception as e:
        log.warning("radar_cached failed: %s", e)
        return None
    lines = []
    for label, typ, alt_ft, heading, nm, radial in rows:
        tag = f" [{bindings[label]}]" if label in bindings else ""
        lines.append(
            f"{label}{tag} ({typ}): {nm:.1f} nm on the {radial:03.0f} radial, "
            f"{alt_ft:,.0f} ft, heading {heading:03.0f}")
    return lines
