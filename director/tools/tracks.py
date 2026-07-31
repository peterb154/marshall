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

import json
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

# HOW LONG A POSITION IS WORTH QUOTING. Not how long a unit EXISTS -- those are
# different questions and conflating them is what this constant used to do.
#
# `StreamUnits` is a CHANGE feed: the proto says a unit is published when it is
# "new or its position or attitude changed", and `max_backoff` exists expressly
# to "postpone polling units that haven't moved recently". So a parked aeroplane
# stops being reported, and asking "was this row written in the last 15 seconds"
# to decide whether the aircraft is THERE answered a question the data cannot
# answer. A pilot sitting in a cold jet vanished off the scope 15 seconds after
# he spawned -- which is the founding case this whole system is for.
#
# Existence is `gone`, and the world resetting is `mission_start`/`mission_end`.
# Both are explicit, both come from the sim, and neither needs a clock. See
# `clear_all` and the loader in the dcs-dedicated-server project this is ported
# from, which has carried the same three rules for years with no timeout at all.
STALE_POS_SEC = 15
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
        # THE CATEGORY THE STREAMER ALREADY KNOWS. It subscribes per category --
        # AIRPLANE, HELICOPTER, GROUND, SHIP -- and then threw it away, so
        # nothing downstream could tell a T-55 from an F-16. That is audit
        # finding #45: `count_contacts` counts tanks as traffic, so a lone
        # pilot engages the separation engine and pays 2.2 s of Sonnet on every
        # transmission. It is also why the diagnostics page could not leave
        # armour out of "nobody is working this".
        conn.execute("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS category TEXT")
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
        # IS IT FLYING? The sim's OWN answer, from `Unit.inAir()`.
        #
        # This replaces a reconstruction of the same fact from land/takeoff
        # EVENTS, which was wrong in three ways at once: empty for anything
        # that spawned parked (no event ever fired), lost entirely on a director
        # restart (it lived in a dict in memory), and silently incomplete
        # whenever the event stream dropped. DCS owns this state; keeping a
        # second copy of it derived from a lossy log was never going to agree.
        #
        # NULL means nobody has asked yet, which is a third answer and not the
        # same as "airborne".
        conn.execute("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS in_air BOOLEAN")
    _ready = True


def _upsert(u, category: str = "") -> None:
    label = u.player_name or u.callsign or u.name
    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO tracks (name, label, type, coalition, geog, alt_ft, heading, speed_kt, player, category, last_seen)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s, %s, %s, %s, %s, now())
            ON CONFLICT (name) DO UPDATE SET
                label=EXCLUDED.label, type=EXCLUDED.type, coalition=EXCLUDED.coalition,
                geog=EXCLUDED.geog, alt_ft=EXCLUDED.alt_ft, heading=EXCLUDED.heading,
                speed_kt=EXCLUDED.speed_kt, player=EXCLUDED.player,
                category=EXCLUDED.category,
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
             u.player_name or "", category))


def _delete(name: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM tracks WHERE name=%s", (name,))


# What a mission reset destroys, and what it must not.
#
#     "If the mission restarts the board should be wiped. Everything --
#      everything starts over. It's a different universe."
#
# LIVE STATE goes: the scope, the board, the identity graph, and everything the
# controller was in the middle of saying. None of it describes the new world and
# all of it looks authoritative -- eight live-looking board rows survived from
# missions that had ended days earlier, one of them holding an aeroplane at six
# thousand feet.
#
# CONFIGURATION STAYS: prompts, approaches, flight_plans, fixes, sectors,
# controllers. Those describe the FIELD, not the sortie, and a controller who
# forgot the letdown on mission change would be useless.
#
# `events` STAYS TOO, and it is the one judgement call here. It is the flight
# recorder -- a log of what happened, not state that can be wrong -- and wiping
# it would mean no debrief and no comparison between sorties. It is also what
# proved `runway_touch` has never once fired on this server. A log accumulates;
# a world resets.
_WIPE_ON_RESET = ("tracks", "flights", "contacts", "bullseye",
                  "session_messages", "session_agents", "memories")


def clear_all(why: str = "") -> dict[str, int]:
    """The world reset. Everything live belonged to the old one.

    Called on `mission_start` and `mission_end`, which is the whole of the
    original design: a unit exists until the sim says `gone`, and every unit
    stops existing when the mission does. No clock is involved anywhere.

    THE ROWS THIS WOULD HAVE PREVENTED are worth naming, because they were on
    the board while this was being written: four T-55s of "Samovar Armour",
    stationary at two thousand feet, ELEVEN HOURS old, from a mission that had
    not been loaded since. They are the "cluster of aircraft on the F10 map on
    a server he was alone on" that `whats_out_there.py` was written to chase,
    and the only thing keeping them off the scope was the staleness filter --
    which is to say the bug that hid them was also the bug that hid the pilot.

    THE CONVERSATION GOES WITH IT, and clearing the tables alone would not do
    it: `app._atc_agents` holds live Agent objects with the conversation in
    process memory, so a controller would go on referring to an approach flown
    in a world that no longer exists. Same shape as every other bug this week --
    a copy in memory outliving the thing it copied.
    """
    freed: dict[str, int] = {}
    with get_pool().connection() as conn:
        for table in _WIPE_ON_RESET:
            try:
                freed[table] = conn.execute(f"DELETE FROM {table}").rowcount
            except Exception as e:
                # One missing table must not abandon the rest of the reset.
                conn.rollback()
                log.warning("could not clear %s: %s", table, str(e)[:80])
    try:
        from app import forget_sessions
        freed["agents"] = forget_sessions()
    except Exception as e:
        log.warning("could not drop the live agents: %s", str(e)[:80])
    log.info("world reset (%s): %s", why or "mission change",
             ", ".join(f"{k}={v}" for k, v in freed.items() if v))
    return freed


def reconcile(names: set[str]) -> int:
    """Delete rows for units the sim no longer has. The safety net.

    `gone` is the primary and this is the backstop, because `gone` can only
    arrive if somebody is listening: the streams reconnect with backoff, and a
    unit that despawns during the gap is never reported gone by anyone. The
    same is true across a director restart.

    A RECONCILER, NOT A REBUILD. It never clears and repopulates -- that would
    open a window, however brief, where the scope reads empty, and an empty
    scope is not a neutral state here. Identity corroborates against it,
    `release_stale` accounts for board entries with it, and a blink would look
    exactly like every aircraft leaving at once. So it only ever removes what
    the sim has positively stopped reporting.

    Given an EMPTY set it does nothing at all. "The sim told us about nobody"
    and "we failed to ask" are indistinguishable at this layer, and deleting
    the world on a failed scan is precisely the mistake this is guarding.
    """
    if not names:
        return 0
    with get_pool().connection() as conn:
        n = conn.execute("DELETE FROM tracks WHERE NOT (name = ANY(%s))",
                         (list(names),)).rowcount
    if n:
        log.info("reconcile: %d row(s) the sim no longer has", n)
    return n


# The sim's category numbers, as the words everything downstream uses.
_CATEGORY = {
    common_pb2.GROUP_CATEGORY_AIRPLANE: "airplane",
    common_pb2.GROUP_CATEGORY_HELICOPTER: "helicopter",
    common_pb2.GROUP_CATEGORY_GROUND: "ground",
    common_pb2.GROUP_CATEGORY_SHIP: "ship",
}


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
                    _upsert(resp.unit, _CATEGORY.get(category, ""))
                elif resp.HasField("gone"):
                    _delete(resp.gone.name)
        except grpc.RpcError as e:
            log.warning("StreamUnits(%s) dropped: %s; retry in %.0fs",
                        category, str(e)[:60], backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 15)


# How often the sweep runs. A BACKSTOP CADENCE, because it is a backstop again:
# `land` and `takeoff` events carry the moment an aeroplane changes state, and
# `gone` carries the moment one ceases to exist. Both are exact and immediate.
#
# What is left for the sweep is everything no event will ever mention -- the jet
# that spawned on a ramp and has simply always been there, and whatever changed
# while nobody was connected to hear about it. Neither is urgent; both are
# permanent until something looks.
#
# It briefly ran at 5s, when it was the only source of ground state. That was
# the right cadence for the wrong design.
SWEEP_SEC = 30


# The mission clock the last sweep saw. It only ever goes up inside one world.
_world: float | None = None


def _world_changed(clock: float | None) -> bool:
    """Is a different mission loaded than the one we last looked at?

    ASKED, NOT LISTENED FOR, and that is the whole point of this function.
    `mission_start` and `mission_end` exist in the proto and the obvious design
    is to act on them -- but LOADING A MISSION TEARS DOWN THE EVENT STREAM THAT
    WOULD REPORT IT. Measured on 31 July: a `LoadMission` produced

        02:55:01 WARNING StreamEvents dropped: ... retry in 1s

    and no mission event ever arrived, because the sim's event plumbing goes
    away with the mission it belonged to and comes back after the new one has
    already started. The notification is destroyed by the thing it notifies you
    of. No amount of correct handling fixes that.

    Comparing observed state has no such hole: the answer is true whenever we
    ask, whether or not anybody was connected when it changed. The event
    handler stays as a fast path for the cases it does fire, and this is what
    makes the reset actually reliable.

    THE START TIME AS WELL AS THE NAME, because reloading the SAME file is a new
    world too -- which is precisely the test that exposed all this.
    """
    global _world
    if clock is None:
        return False
    was, _world = _world, clock
    # The FIRST look is not a change. The director restarting is not a new
    # world, and wiping the board every time this process came up would be a
    # nastier version of the bug being fixed.
    if was is None:
        return False
    # THE MISSION CLOCK RAN BACKWARDS, which only one thing can mean. It counts
    # seconds since the mission began, so it rises monotonically for the life of
    # a world and starts again from near zero in the next one.
    #
    # WHY NOT THE MISSION FILENAME: reloading the same file is a new world and
    # the name is identical. Nor the scenario START time -- that is a property
    # of the .miz, not of this run, so it is also identical. Both were tried on
    # 31 July and both silently detected nothing, which is the worst kind of
    # check: it runs, it passes, and the board keeps yesterday's aeroplanes.
    #
    # AND NOT A MISSION-ENV RPC EITHER. `GetScenarioCurrentTime` says the same
    # thing and cannot be reached when it matters: a hot-loaded mission starts
    # PAUSED, and every mission-environment call deadline-exceeds while it is.
    # This rides on the sweep's existing Eval, so it costs no extra call and is
    # simply absent -- `None`, not a false answer -- whenever the sim is not
    # running to be asked.
    if clock >= was:
        return False
    log.info("mission clock went backwards (%.0fs -> %.0fs): a new world", was, clock)
    return True


def _sweep(stop: threading.Event) -> None:
    """Ask the sim what exists and what is flying. The only source of both.

    ONE QUESTION, ASKED OF THE THING THAT KNOWS. `inAir()` is DCS's own state,
    so nothing here infers, remembers or reconstructs -- which is what the
    land/takeoff event map was doing, and it disagreed with the sim for every
    aeroplane that spawned parked.
    """
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc

    lua = """
    local out = {"CLOCK\t" .. tostring(timer.getTime())}
    for _, side in pairs(coalition.side) do
      for _, cat in pairs({Group.Category.AIRPLANE, Group.Category.HELICOPTER,
                           Group.Category.GROUND, Group.Category.SHIP}) do
        for _, g in pairs(coalition.getGroups(side, cat) or {}) do
          for _, u in pairs(g:getUnits() or {}) do
            out[#out+1] = u:getName() .. "\\t" .. tostring(u:inAir())
          end
        end
      end
    end
    return table.concat(out, "\\n")
    """
    while not stop.wait(SWEEP_SEC):
        try:
            with grpc.insecure_channel(DCS_GRPC_ADDR) as ch:
                r = custom_pb2_grpc.CustomServiceStub(ch).Eval(
                    custom_pb2.EvalRequest(lua=lua), timeout=20)
            flying, clock = {}, None
            for line in json.loads(r.json).split("\n"):
                if not line:
                    continue
                name, _, val = line.partition("\t")
                if name == "CLOCK":
                    clock = float(val)
                    continue
                flying[name] = (val == "true")
            # BEFORE ANYTHING ELSE IS BELIEVED. If this is a different world,
            # the units just read belong to it and everything held belongs to
            # the last one -- so the wipe has to happen before the upsert, or
            # the reconcile below would delete the new world's aircraft as
            # "units the sim no longer has".
            if _world_changed(clock):
                clear_all("the mission restarted")
            if flying:
                _note_in_air(flying)
            reconcile(set(flying))
        except Exception as e:
            # A failed sweep must never delete anything -- see `reconcile`.
            log.warning("sweep failed: %s", str(e)[:80])


def set_in_air(unit_name: str, in_air: bool) -> None:
    """One unit's ground state, from the EVENT that changed it.

    The event is the moment; the sweep is the truth. They write the same column
    on purpose -- there is one answer to "is it flying" and it lives in one
    place -- but they arrive by different routes because they are good at
    different things.

    `land` and `takeoff` are exact and instant, and instant matters: touching
    down is what ends an approach and hands a man to Tower, so learning it a
    poll late means a poll of vectoring an aeroplane that is already rolling
    out. The sweep cannot be that prompt without asking the sim constantly.

    But the sweep is the only one that is ever RIGHT about an aeroplane nothing
    happened to. A jet that spawned on the ramp never landed, so no `land` ever
    fires and no amount of listening will produce one -- which is exactly how
    the old in-memory version came to insist a parked Mustang was airborne.
    """
    with get_pool().connection() as conn:
        conn.execute("UPDATE tracks SET in_air = %s WHERE name = %s",
                     (bool(in_air), unit_name))


def _note_in_air(flying: dict[str, bool]) -> None:
    """Write the sim's ground state onto the rows it belongs to.

    Only for units already in the cache: the stream owns what EXISTS, this owns
    one column of it. Creating a row here would make two writers of the same
    table disagree about who is in it.
    """
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE tracks SET in_air = v.air FROM (SELECT unnest(%s::text[]) "
            "AS name, unnest(%s::bool[]) AS air) v WHERE tracks.name = v.name",
            (list(flying), list(flying.values())))


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
        # AND THE SAFETY NET. `gone` is the primary; this catches the units
        # whose `gone` arrived while nobody was connected.
        threading.Thread(target=_sweep, args=(stop,), daemon=True).start()
        _started = True
        log.info("track streamer started (sweep every %ds)", SWEEP_SEC)


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
                "WHERE (lower(label) = %s OR lower(name) = %s) LIMIT 1",
                (key, key)).fetchone()
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
                       COALESCE(t.player, '') AS player,
                       COALESCE(t.category, '') AS category,
                       ST_Y(t.geog::geometry) AS lat,
                       ST_X(t.geog::geometry) AS lon,
                       t.coalition,
                       t.in_air
                FROM tracks t, bcn
                ORDER BY nm
                """,
                (BATUMI_LON, BATUMI_LAT)).fetchall()
    except Exception as e:
        log.warning("radar_cached failed: %s", e)
        return None
    return _render(rows, bindings)


# WHERE EVERYTHING ACTUALLY IS, with no opinion about who is asking.
#
#     "you have range 0.4nm.. from what? I assume Batumi. But why? When we have
#      50 controllers on the system - Batumi is just one fix"
#
# Right. `nm` and `radial` above are measured from a MODULE CONSTANT -- Batumi's
# ARP -- so every consumer on the map reads ranges from one aerodrome, and the
# rows even come back sorted by distance from it. A controller at Kobuleti would
# get his traffic in somebody else's order before he read a line.
#
# Range-from-a-field is a RENDERING, and there are at least three of them: from
# the controller's own field for a talkdown, from BULLSEYE for anything shared
# between controllers, and BRAA between two aircraft. All three fall out of an
# absolute position; bake any one of them in and the other two need a parser and
# a fudge. So this returns latitude and longitude and lets the consumer decide.
#
# The formation grouping stays, because it is a fact about the world (are these
# aeroplanes flying together?) rather than a presentation of it -- but it is
# expressed as a FIELD naming the lead, not by deleting the wingmen. Every
# aircraft keeps its own position, which is [#47] acceptance 3.
def contacts(bindings: dict | None = None) -> list[dict] | None:
    """Every fresh track, as data. None if the cache cannot be read."""
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
                       COALESCE(t.player, '') AS player,
                       COALESCE(t.category, '') AS category,
                       ST_Y(t.geog::geometry) AS lat,
                       ST_X(t.geog::geometry) AS lon,
                       t.coalition,
                       t.in_air
                FROM tracks t, bcn
                ORDER BY nm
                """, (BATUMI_LON, BATUMI_LAT)).fetchall()
    except Exception as e:
        log.warning("contacts failed: %s", e)
        return None
    # DOWN, PER THE SIM. `in_air` comes straight from `Unit.inAir()` in the
    # sweep. This used to read a set rebuilt from land/takeoff events, which is
    # the same fact reconstructed from a lossy log -- blank for anything that
    # spawned parked, gone after a director restart. NULL here means the sweep
    # has not run yet, and that is not the same as "airborne".
    down = {r[1] for r in rows if r[13] is False}
    naming = _unique_labels(rows)
    out = []
    for group in _clusters(rows):
        lead = group[0][1]
        for r in group:
            label, name, typ, alt_ft, heading, speed_kt = r[0], r[1], r[2], r[3], r[4], r[5]
            out.append({
                "name": name,
                "label": naming.get(name, label),
                "type": typ or "",
                "category": (r[9] or ""),
                "manned": bool(r[8]),
                "player": r[8] or "",
                "on_ground": name in down,
                "lat": r[10], "lon": r[11],
                "alt_ft": alt_ft, "heading": heading, "speed_kt": speed_kt,
                "coalition": r[12],
                # The callsign something has already correlated to this track,
                # which is what the prose prints in [brackets]. Corroboration,
                # never the primary key -- see atc/identity.py -- but identity
                # needs it and it must not be recovered by re-reading the prose.
                "callsign": bindings.get(naming.get(name, label), ""),
                # The lead's unit name, on every member INCLUDING the lead, so
                # "is this a formation" is one comparison and "who is it led by"
                # needs no second pass. "" would have meant two questions.
                "formation": lead if len(group) > 1 else "",
            })
    return out


# `_BULLSEYE` LIVED HERE, a module dict cached for the life of the process. It
# is a table now -- see `bullseyes` and migration 016. The reasoning that
# justified the cache ("a mission change restarts this process") stopped being
# true the day the mission reset learned to wipe without a restart.


def bullseyes() -> dict:
    """The sim's own bullseye per coalition, PERSISTED rather than cached here.

        "maybe we should define a bullseye... that is a universal point that
         everyone on the map can/should share for reference"

    ASKED, NOT DEFINED. DCS already has one per coalition and every pilot's HSI
    is referenced to it, so inventing our own would give the controller a
    reference nobody in a cockpit can see. Same rule as the coordinate
    projection: the sim is the authority on its own map.

    IT USED TO BE A MODULE DICT, and the justification was:

        "Cached because it does not move within a mission, and a mission change
         restarts this process."

    True when it was written, false since the mission reset started detecting a
    world change from the clock and wiping WITHOUT restarting anything. The
    cache would have outlived the mission it described and served the previous
    map's bullseye, confidently, with nothing to say why. A cache whose
    invalidation story is "the process dies" is a bug waiting for the day the
    process stops dying.

    Now it is a table: read it, and ask the sim only when it is empty. That also
    unblocks the bridge reading the scope from `tracks` -- the /radar payload
    carried this and the table did not.
    """
    got = _bullseye_rows()
    if got:
        return got
    try:
        from dcs.coalition.v0 import coalition_pb2, coalition_pb2_grpc
        from dcs.common.v0 import common_pb2
        ch = grpc.insecure_channel(DCS_GRPC_ADDR)
        stub = coalition_pb2_grpc.CoalitionServiceStub(ch)
        rows = {}
        for name, val in (("red", common_pb2.COALITION_RED),
                          ("blue", common_pb2.COALITION_BLUE)):
            r = stub.GetBullseye(coalition_pb2.GetBullseyeRequest(coalition=val),
                                 timeout=10)
            rows[name] = {"lat": r.position.lat, "lon": r.position.lon}
        _store_bullseyes(rows)
        return rows
    except Exception as e:
        log.warning("bullseye unavailable: %s", str(e)[:80])
        return {}


def _bullseye_rows() -> dict:
    try:
        with get_pool().connection() as conn:
            return {c: {"lat": la, "lon": lo} for c, la, lo in conn.execute(
                "SELECT coalition, lat, lon FROM bullseye").fetchall()}
    except Exception as e:
        log.warning("could not read the bullseye table: %s", str(e)[:80])
        return {}


def _store_bullseyes(rows: dict) -> None:
    """Write what the sim said. Idempotent; a re-ask overwrites."""
    try:
        with get_pool().connection() as conn:
            for name, ll in rows.items():
                conn.execute(
                    "INSERT INTO bullseye (coalition, lat, lon) "
                    "VALUES (%s, %s, %s) ON CONFLICT (coalition) DO UPDATE SET "
                    "lat = EXCLUDED.lat, lon = EXCLUDED.lon, updated_at = now()",
                    (name, ll["lat"], ll["lon"]))
        log.info("bullseye stored for %s", ", ".join(sorted(rows)))
    except Exception as e:
        log.warning("could not store the bullseye: %s", str(e)[:80])


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
                """, (BATUMI_LON, BATUMI_LAT)).fetchall()
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
    # The category, on the wingmen too. Only the lead carried it, so four tanks
    # in one group rendered as one ground unit and three aircraft -- and
    # `count_contacts` duly engaged the separation engine for a lone pilot.
    if len(row) > 9 and row[9] not in ("airplane", "helicopter", ""):
        bits.append(row[9])
    if row[1] in down:
        bits.append("on the ground")
    ax, ay = xy(lead[6], lead[7])
    bx, by = xy(row[6], row[7])
    bits.append(f"{math.hypot(ax - bx, ay - by):.1f} nm")
    return f"{name} ({', '.join(b for b in bits if b)})"


def _render(rows: list, bindings: dict) -> list[str]:
    lines = []
    naming = _unique_labels(rows)
    # WHO THE SIM SAYS IS DOWN, from `Unit.inAir()` on the row itself.
    #
    # It used to be a set rebuilt from land/takeoff EVENTS -- the same fact,
    # reconstructed from a log that never fired for an aeroplane which spawned
    # parked and was lost outright on a director restart. DCS owns this; there
    # is no reason to keep a second, worse copy of it.
    #
    # `in_air IS NULL` means the sweep has not reached this unit yet, and that
    # is a third answer: not down, not flying, not known.
    down = {r[1] for r in rows if len(r) > 13 and r[13] is False}
    for group in _clusters(rows):
        label, name, typ, alt_ft, heading, speed_kt, nm, radial = group[0][:8]
        label = naming.get(name, label)
        # IS THERE A HUMAN IN IT? Written into the picture because it is the
        # one fact that separates a pilot who can be talked to from an AI that
        # cannot, and because an unknown radio is identified by ELIMINATION
        # against it -- see atc/identity.py. A controller wants it anyway: he
        # works participating aircraft, not every return on the scope.
        manned = ", manned" if (len(group[0]) > 8 and group[0][8]) else ""
        # ANYTHING THAT IS NOT AN AEROPLANE SAYS SO. Additive, in the same
        # parenthetical the manned marker uses, so every existing parser
        # tolerates it -- `units_on` splits on the comma and takes the type.
        # Without it nothing downstream can tell a tank from a fighter.
        if len(group[0]) > 9 and group[0][9] not in ("airplane", "helicopter", ""):
            manned += f", {group[0][9]}"
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
