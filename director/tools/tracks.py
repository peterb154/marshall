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

_MS_TO_KT = 1.94384
_MAGVAR = 6.0   # Caucasus magnetic variation (E); pilots fly magnetic headings
# Named fixes we can vector to, as lat/lon.
#
# Batumi is built in because it is the field. Everything else -- the sortie
# steerpoints, the target, the approach fixes -- is PUSHED here at bridge
# startup by whoever owns route.py, because route.py is the single source of
# truth for where a fix is and this container cannot import it.
#
# The projection is not ours and must not be: Caucasus is a transverse Mercator
# and a flat-earth offset from the field is out by seven miles at the target
# area, which was measured rather than assumed. The bridge asks the SIM to
# convert, so the numbers here are the sim's own.
#
# Until that push arrives the table holds only the field, and `vector` says so
# rather than guessing -- which is the correct failure. A pilot asking for the
# range to his ingress point got "negative DME to ingress, you'll have to call
# it off your own nav", and that was honest.
_FIXES = {"batumi": (BATUMI_LAT, BATUMI_LON), "the field": (BATUMI_LAT, BATUMI_LON),
          "the beacon": (BATUMI_LAT, BATUMI_LON), "home": (BATUMI_LAT, BATUMI_LON)}


def _ensure_fix_table() -> None:
    with get_pool().connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS fixes ("
                     "name text PRIMARY KEY, lat double precision NOT NULL, "
                     "lon double precision NOT NULL, pushed_at timestamptz "
                     "DEFAULT now())")


def set_fixes(fixes: dict) -> int:
    """Load named fixes pushed from route.py, via the sim's own projection.

    Additive and idempotent: the built-in field entries stay, and a re-push
    (every bridge restart) overwrites what it knew before.

    PERSISTED, and that is the point. Held only in memory, the table survives
    exactly as long as this process -- so a director restart with the bridge
    still up would leave the controller silently back to knowing only the
    field, answering "no fix for that" for the rest of the night with nothing
    to say why. A restart is the routine event here; the table has to outlive
    it.
    """
    clean = {}
    for name, ll in (fixes or {}).items():
        key = str(name).strip().lower()
        if key and ll and len(ll) == 2:
            clean[key] = (float(ll[0]), float(ll[1]))
    if clean:
        _ensure_fix_table()
        with get_pool().connection() as conn:
            for key, (la, lo) in clean.items():
                conn.execute(
                    "INSERT INTO fixes (name, lat, lon) VALUES (%s, %s, %s) "
                    "ON CONFLICT (name) DO UPDATE SET lat = EXCLUDED.lat, "
                    "lon = EXCLUDED.lon, pushed_at = now()", (key, la, lo))
    _FIXES.update(clean)
    log.info("fix table now holds %d names", len(_FIXES))
    return len(_FIXES)


def _load_fixes() -> None:
    """Pull the pushed fixes back after a restart. Once, lazily."""
    global _fixes_loaded
    if _fixes_loaded:
        return
    _fixes_loaded = True
    try:
        _ensure_fix_table()
        with get_pool().connection() as conn:
            for name, la, lo in conn.execute(
                    "SELECT name, lat, lon FROM fixes").fetchall():
                _FIXES.setdefault(name, (la, lo))
    except Exception as e:
        log.warning("could not reload the fix table: %s", e)


def known_fixes() -> dict:
    _load_fixes()
    return {k: list(v) for k, v in sorted(_FIXES.items())}

from dcs.common.v0 import common_pb2
from dcs.mission.v0 import mission_pb2, mission_pb2_grpc

log = logging.getLogger(__name__)

FRESH_SEC = 15          # a track older than this is stale -> not shown
_ready = False
_fixes_loaded = False
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
                speed_kt   DOUBLE PRECISION,
                last_seen  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """)
        conn.execute("CREATE INDEX IF NOT EXISTS tracks_geog ON tracks USING GIST (geog)")
        # IS THERE A HUMAN IN IT? Added separately because the table predates
        # the question, and CREATE TABLE IF NOT EXISTS will not widen a table
        # that already exists -- the column would silently never appear on the
        # only database that matters, the live one.
        #
        # The player's name rather than a boolean, because the name is the
        # evidence: SRS names a client after the human and DCS names the player
        # the same way, so this is the field an unknown radio is matched
        # against. A flag would answer "is this a person" and lose "which
        # person", which is the half that identifies anybody.
        conn.execute("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS player TEXT")
    _ready = True


def _upsert(u) -> None:
    label = u.player_name or u.callsign or u.name
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO tracks (name, label, type, coalition, geog, alt_ft, heading, speed_kt, player, last_seen)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s, %s, %s, %s, now())
            ON CONFLICT (name) DO UPDATE SET
                label=EXCLUDED.label, type=EXCLUDED.type, coalition=EXCLUDED.coalition,
                geog=EXCLUDED.geog, alt_ft=EXCLUDED.alt_ft, heading=EXCLUDED.heading,
                speed_kt=EXCLUDED.speed_kt, player=EXCLUDED.player,
                last_seen=now()
            """,
            (u.name, label, u.type, u.coalition, u.position.lon, u.position.lat,
             u.position.alt * _M_TO_FT, u.orientation.heading,
             # GROUNDSPEED, in knots. The sim gives metres per second; the
             # descent planner needs to know how long a mile takes, because a
             # 500 fpm descent covers a very different distance at 150 knots
             # than at 300.
             u.velocity.speed * _MS_TO_KT,
             # Empty for AI. That emptiness is the whole human/AI
             # distinction, and it costs nothing to carry.
             u.player_name or ""))


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
        # Ground and ships too, not just aircraft. This is a combat sim and the
        # world was aeroplanes only, so an overlord could task a flight against
        # armour that existed in the sim and nowhere the ATC side could see it.
        # With them in the cache, "is the target still alive" is a lookup: the
        # row stops being there, and that IS the answer -- nobody has to model
        # destruction.
        for cat in (common_pb2.GROUP_CATEGORY_AIRPLANE,
                    common_pb2.GROUP_CATEGORY_HELICOPTER,
                    common_pb2.GROUP_CATEGORY_GROUND,
                    common_pb2.GROUP_CATEGORY_SHIP):
            threading.Thread(target=_stream_category, args=(cat, stop),
                             daemon=True).start()
        _started = True
        log.info("track streamer started")


def _resolve(name: str) -> tuple[float, float] | None:
    """A target name -> (lat, lon): a named fix, else a fresh radar track (matched
    on its scope label or unit name)."""
    key = (name or "").strip().lower()
    _load_fixes()
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
                SELECT t.label, t.name, t.type, t.alt_ft, t.heading, t.speed_kt,
                       ST_Distance(t.geog, bcn.g) / 1852.0 AS nm,
                       degrees(ST_Azimuth(bcn.g, t.geog)) AS radial,
                       COALESCE(t.player, '') AS player
                FROM tracks t, bcn
                WHERE t.last_seen > now() - make_interval(secs => %s)
                ORDER BY nm
                """,
                (BATUMI_LON, BATUMI_LAT, FRESH_SEC)).fetchall()
    except Exception as e:
        log.warning("radar_cached failed: %s", e)
        return None
    return _render(rows, bindings)


# A formation is tight: line abreast or trail, inside a couple of miles and a
# few hundred feet, all pointing the same way. Loose enough to survive AI
# station-keeping wobble, tight enough that two aircraft genuinely working the
# approach separately never merge.
#
# FORM_FT must stay well UNDER the holding stack's step (1,000 ft), or the
# detector eats the stack: four aircraft correctly separated by 1,000 ft over
# the same beacon would read as a formation, and the controller would be told
# that four aeroplanes he has just separated are one contact.
FORM_NM = 2.0
FORM_FT = 500
FORM_HDG = 40


def _clusters(rows: list) -> list[list]:
    """Group contacts that are flying as a formation.

    Four aeroplanes in close formation are four blips a mile apart at the same
    altitude on the same heading, and presenting them as four independent
    contacts is actively harmful: the controller's own rule is that an ambiguous
    match must not be identified, so a four-ship could never be radar identified
    at all -- the more aircraft in the formation, the less he can see it. A real
    controller reads that picture as ONE thing.
    """
    import math

    def xy(nm, radial):
        r = math.radians(radial)
        return nm * math.sin(r), nm * math.cos(r)

    def near(a, b) -> bool:
        # BY POSITION, NOT BY UNPACKING. This read
        #     _, _, a_alt, a_hdg, a_nm, a_radial = a
        # which demands a row of exactly six, and the row has grown twice --
        # groundspeed for the descent planner, then the player's name for
        # identity. Each time it became a ValueError that fires ONLY when two
        # contacts are compared, so a single ship never reaches it and every
        # test with one aeroplane passes. The first two aircraft on the scope
        # would have lost the whole radar picture, on the night a second pilot
        # was invited.
        #
        # The clustering wants five numbers and does not care what else the row
        # carries, so it takes the five it wants.
        a_alt, a_hdg, a_nm, a_radial = a[3], a[4], a[6], a[7]
        b_alt, b_hdg, b_nm, b_radial = b[3], b[4], b[6], b[7]
        ax, ay = xy(a_nm, a_radial)
        bx, by = xy(b_nm, b_radial)
        return (math.hypot(ax - bx, ay - by) <= FORM_NM
                and abs(a_alt - b_alt) < FORM_FT
                and abs((a_hdg - b_hdg + 180) % 360 - 180) <= FORM_HDG)

    groups: list[list] = []
    for row in rows:
        # Chain against ANY member, not just the leader: a four-ship in trail is
        # strung out over more than the pairwise threshold end to end, so
        # comparing everyone to the lead alone drops the tail of the formation.
        for g in groups:
            if any(near(row, other) for other in g):
                g.append(row)
                break
        else:
            groups.append([row])
    return groups


def in_formation(label: str) -> bool:
    """Is this track flying tight enough on another to be one contact?

    Asked before binding a FLIGHT name to a track. "Pony 1" is one aeroplane
    when it is alone and a formation when it is not, and the difference is not
    in the callsign -- it is out of the window.
    """
    try:
        _ensure_table()
        with get_pool().connection() as conn:
            rows = conn.execute(
                """
                WITH bcn AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS g)
                SELECT t.label, t.name, t.type, t.alt_ft, t.heading, t.speed_kt,
                       ST_Distance(t.geog, bcn.g) / 1852.0,
                       degrees(ST_Azimuth(bcn.g, t.geog)),
                       COALESCE(t.player, '')
                FROM tracks t, bcn
                WHERE t.last_seen > now() - make_interval(secs => %s)
                """, (BATUMI_LON, BATUMI_LAT, FRESH_SEC)).fetchall()
        # THE SAME COLUMNS, IN THE SAME ORDER, AS THE PICTURE QUERY. They had
        # drifted apart -- this one had no groundspeed -- so the two callers
        # handed _clusters rows of different widths and whichever convention it
        # used was wrong for one of them. One clusterer wants one row shape.
        #
        # Postgres hands back Decimal for the numerics and the clustering does
        # float arithmetic on them; mixing the two raises rather than coercing.
        rows = [(r[0], r[1], r[2], float(r[3] or 0), float(r[4] or 0),
                 float(r[5] or 0), float(r[6] or 0), float(r[7] or 0), r[8])
                for r in rows]
        for group in _clusters(rows):
            if any(r[0] == label for r in group):
                return len(group) > 1
    except Exception as e:
        log.warning("in_formation(%s) failed: %s", label, e)
    return False


def _unique_labels(rows: list) -> dict:
    """A label has to name exactly ONE aeroplane.

    It did not. Every AI flight in the mission carries a DCS callsign, the
    label prefers that callsign over the unit name, and two separate groups
    both came up "Enfield11" -- so the scope showed one name at four miles and
    the same name at fifteen. Everything downstream reads that picture by name:
    the controller, the range calls, and `radar_fix`, which takes the first
    match and would have been vectoring whichever of the two it happened to
    parse first.

    Almost certainly what put "Pony one one" on an AI unit in an earlier
    recording, which looked like a correlation bug and was a naming collision.

    The unit name is the table's primary key, so it is unique by construction.
    Colliding labels fall back to it, and only the colliding ones -- a mission
    whose callsigns are distinct keeps the friendlier name.
    """
    seen: dict = {}
    for r in rows:
        seen[r[0]] = seen.get(r[0], 0) + 1
    return {r[1]: (r[0] if seen[r[0]] == 1 else r[1]) for r in rows}


def _other_ship(row: list, lead: list, naming: dict, down: set) -> str:
    """One wingman on the lead's line: name, airframe, and how far off he is.

    Compact on purpose. This is read on every transmission and the formation is
    meant to scan as ONE contact, so a wingman gets the three facts something
    downstream cannot do without and no more.
    """
    import math

    def xy(nm, radial):
        r = math.radians(radial)
        return nm * math.sin(r), nm * math.cos(r)

    name = naming.get(row[1], row[0])
    bits = [row[2] or ""]
    if len(row) > 8 and row[8]:
        bits.append("manned")
    if row[1] in down:
        bits.append("on the ground")
    ax, ay = xy(lead[6], lead[7])
    bx, by = xy(row[6], row[7])
    bits.append(f"{math.hypot(ax - bx, ay - by):.1f} nm")
    return f"{name} ({', '.join(b for b in bits if b)})"


def _render(rows: list, bindings: dict) -> list[str]:
    lines = []
    naming = _unique_labels(rows)
    # WHO THE SIM SAYS IS DOWN. Carried in the picture rather than looked up per
    # contact, because this is rendered on every transmission and the answer is
    # already in memory. Empty when the event stream has told us nothing, which
    # is a third answer -- see events.ground_state.
    try:
        from tools.events import on_the_ground
        down = on_the_ground()
    except Exception:
        down = set()
    for group in _clusters(rows):
        label, name, typ, alt_ft, heading, speed_kt, nm, radial = group[0][:8]
        label = naming.get(name, label)
        # IS THERE A HUMAN IN IT? Written into the picture because it is the
        # one fact that separates a pilot who can be talked to from an AI that
        # cannot, and because an unknown radio is identified by ELIMINATION
        # against it -- see atc/identity.py. A controller wants it anyway: he
        # works participating aircraft, not every return on the scope.
        manned = ", manned" if (len(group[0]) > 8 and group[0][8]) else ""
        # "on the ground" comes from the sim's land/takeoff events, not from a
        # guess at altitude and speed.
        if name in down:
            manned += ", on the ground"
        # Groundspeed is in the picture because the vertical engine cannot plan
        # a descent without it: 500 fpm is a very different gradient at 150
        # knots than at 300. Omitted when the sim has not given us one, rather
        # than printed as zero -- a controller who reads out a speed he does not
        # have is worse than one who says nothing.
        spd = f", {speed_kt:.0f} knots" if speed_kt else ""
        tag = f" [{bindings[label]}]" if label in bindings else ""
        if len(group) > 1:
            # EACH OTHER SHIP KEEPS WHAT IT IS AND WHERE IT IS. The collapse is
            # for the CONTROLLER, who should read a formation as one thing; it
            # was also throwing away every wingman's airframe, his manned flag
            # and his position, and three separate consumers need those.
            #
            # Identity needs the name and the manned flag, or nobody in a
            # formation can be identified at all -- and forming up is what a
            # pilot does just before asking to join a flight.
            #
            # The OFFSET is here because the join rule measures a real gap
            # against a one-mile radius, and this detector's own threshold is
            # two miles (FORM_NM). "Radar shows them as a formation" is
            # therefore NOT proof they are within a mile, and quietly treating
            # it as proof would double the join radius by accident. So the
            # number is printed and the rule keeps measuring.
            others = ", ".join(_other_ship(r, group[0], naming, down)
                               for r in group[1:])
            lines.append(
                f"{label}{tag} ({typ}{manned}) IN FORMATION with {others} — "
                f"{len(group)} ships, lead {nm:.1f} nm on the {radial:03.0f} "
                f"radial, {alt_ft:,.0f} ft, heading {heading:03.0f}{spd}")
        else:
            lines.append(
                f"{label}{tag} ({typ}{manned}): {nm:.1f} nm on the {radial:03.0f} radial, "
                f"{alt_ft:,.0f} ft, heading {heading:03.0f}{spd}")
    return lines
