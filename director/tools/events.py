"""What the sim SAYS happened, instead of what we inferred from a position.

    "for landing - isn't there a dcs event that we can use to determine if the
     pilot landed or not?"
    "Landing / takeoff event should be triggers to switch to/from tower"
    "Player leaving slot event can clear database for slot association to
     callsign"

[ARCH-3] / #41. Three inferences in one afternoon that the sim would simply
state -- is he down, is the approach over, is he still that aeroplane -- each a
threshold on a continuous quantity standing in for a discrete fact, and each
one having already needed a special case:

    LANDED      altitude under 200 ft and speed under 60 kt. A taxiing
                aeroplane read as a go-around, and a parked one was told to
                climb to three thousand.
    HANDOFF     Approach gives him up at a RANGE, which had to be special-cased
                because handing a man over mid-talkdown abandons him at the
                exact moment the procedure begins. A go-around at half a mile
                is closer than a landing at one; distance cannot express it.
    STILL HIM   a two-hour TTL on the radio binding. Far too long for a man who
                swapped aeroplanes between sorties, far too short for one on a
                long mission, and never right, because the quantity it measures
                is not the one that matters.

`mission.StreamEvents` publishes all three. Only `StreamUnits` was subscribed
to; the rest sat behind a TODO.

WHAT IS STORED, AND WHY BOTH. The append-only `events` table is the record -- a
sortie can be replayed against it afterwards, which is the whole reason the
flight recorder exists. The in-memory state is what the radar picture reads on
every render, because a picture built four times a second cannot afford a query
per contact.

AN ABSENT ANSWER IS NOT A NEGATIVE ANSWER, and this is the part that decides
whether the whole thing is safe. The sim pauses when it is empty, the stream
drops, a director restart loses everything before it. So `ground_state` returns
None for "no event has told me" and the caller keeps its old inference for that
case. A dead subscription must never read as "nobody has ever landed".
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
from tools.dcs import DCS_GRPC_ADDR

from dcs.mission.v0 import mission_pb2, mission_pb2_grpc

log = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()
_ready = False

# unit name -> True if the sim last said he was on the ground, False if
# airborne. ABSENT means nothing has been heard about him, which is a third
# answer and not a synonym for either.
_on_ground: dict[str, bool] = {}

# The events that move an aeroplane between the ground and the air.
#
# `land` ONLY, and `runway_touch` deliberately left out of it. A touch-and-go
# raises runway_touch and never lands, so acting on it would hand a man doing a
# low approach to Tower for the few seconds until `takeoff` put it right --
# which is the same "he went around and got given to Tower anyway" the range
# rule had just been fixed for. Seen in the recording: a real landing raised
# runway_touch seventeen seconds before `land`, so the two are genuinely
# different moments and only the second one means he is staying.
#
# `birth` is out for the same reason: an aircraft can be born on a ramp or in
# the air and the event does not say which. Both are still RECORDED; the
# question is only what state they are allowed to set.
DOWN = ("land",)
UP = ("takeoff", "runway_takeoff")

# Everything worth writing down. Wider than what is acted on, because the
# recording is for replaying a sortie afterwards and the cost of a row is
# nothing next to the cost of not having it.
WATCHED = DOWN + UP + (
    "birth", "crash", "ejection", "unit_lost", "pilot_dead",
    "player_enter_unit", "player_leave_unit", "engine_startup",
    "engine_shutdown", "connect", "disconnect",
)


def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    with get_pool().connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id         BIGSERIAL PRIMARY KEY,
                at         TIMESTAMPTZ NOT NULL DEFAULT now(),
                kind       TEXT NOT NULL,
                unit_name  TEXT,
                player     TEXT,
                place      TEXT
            )
            """)
        conn.execute("CREATE INDEX IF NOT EXISTS events_unit ON events (unit_name, at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS events_at ON events (at DESC)")
    _ready = True


def _record(kind: str, unit_name: str, player: str, place: str) -> None:
    try:
        _ensure_table()
        with get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO events (kind, unit_name, player, place) "
                "VALUES (%s, %s, %s, %s)", (kind, unit_name, player, place))
    except Exception as e:
        # Never let the recorder cost us the state change: the in-memory answer
        # is what the controller actually reads, and a database hiccup must not
        # take the landing with it.
        log.warning("event recorder: %s", e)


def _initiator(ev) -> tuple[str, str]:
    """The unit an event happened to, and the human in it."""
    who = getattr(ev, "initiator", None)
    unit = getattr(who, "unit", None) if who is not None else None
    if unit is None or not getattr(unit, "name", ""):
        return "", ""
    return unit.name, getattr(unit, "player_name", "") or ""


def note(kind: str, unit_name: str, player: str = "", place: str = "") -> None:
    """Apply one event. Separate from the stream so it can be tested."""
    if kind in DOWN:
        _on_ground[unit_name] = True
    elif kind in UP:
        _on_ground[unit_name] = False
    elif kind == "player_leave_unit":
        # HE HAS VACATED THE POSITION. A callsign is a position rather than a
        # person (#38), so leaving the slot is precisely when the association
        # stops being true -- and it is what the two-hour TTL was approximating.
        _on_ground.pop(unit_name, None)
        _forget_slot(unit_name)
    _record(kind, unit_name, player, place)


def _forget_slot(unit_name: str) -> None:
    """Drop what this slot was bound to, because nobody is in it now."""
    try:
        _ensure_table()
        with get_pool().connection() as conn:
            conn.execute("UPDATE flights SET track_name = NULL "
                         "WHERE track_name = %s", (unit_name,))
    except Exception as e:
        log.warning("could not clear the slot association for %s: %s",
                    unit_name, e)


def ground_state(unit_name: str) -> bool | None:
    """True on the ground, False airborne, None if the sim has not said.

    THE THIRD ANSWER IS THE IMPORTANT ONE. The stream drops when the sim
    pauses, and a director restart begins knowing nothing -- so a caller that
    read None as "airborne" would tell a parked aeroplane to fly the missed
    approach, which is the bug this replaces.
    """
    return _on_ground.get(unit_name)


def on_the_ground() -> set[str]:
    """Every unit the sim has said is down. For the radar picture."""
    return {n for n, down in _on_ground.items() if down}


def _stream(stop: threading.Event) -> None:
    backoff = 1.0
    while not stop.is_set():
        try:
            ch = grpc.insecure_channel(DCS_GRPC_ADDR)
            stub = mission_pb2_grpc.MissionServiceStub(ch)
            for resp in stub.StreamEvents(mission_pb2.StreamEventsRequest()):
                if stop.is_set():
                    break
                backoff = 1.0
                kind = resp.WhichOneof("event")
                if kind not in WATCHED:
                    continue
                ev = getattr(resp, kind)
                unit, player = _initiator(ev)
                if not unit:
                    continue
                place = getattr(getattr(ev, "place", None), "name", "") or ""
                note(kind, unit, player, place)
                log.info("event %s: %s%s", kind, unit,
                         f" ({player})" if player else "")
        except grpc.RpcError as e:
            # Expected, repeatedly: the sim pauses when empty and the stream
            # ends. Reconnect quietly rather than treating it as a failure --
            # but do NOT clear what we know, because a pause is not a takeoff.
            log.warning("StreamEvents dropped: %s; retry in %.0fs",
                        str(e)[:60], backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 15)


def start_events() -> None:
    """Start the event stream in the background (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _ensure_table()
        threading.Thread(target=_stream, args=(threading.Event(),),
                         daemon=True).start()
        _started = True
        log.info("event stream started")


@tool
def recent_events(limit: int = 20) -> str:
    """What the sim has reported lately -- landings, takeoffs, slot changes."""
    try:
        _ensure_table()
        with get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT to_char(at,'HH24:MI:SS'), kind, unit_name, "
                "COALESCE(player,''), COALESCE(place,'') FROM events "
                "ORDER BY at DESC LIMIT %s", (limit,)).fetchall()
    except Exception as e:
        return f"events unavailable: {e}"
    if not rows:
        return "no events recorded"
    return "\n".join(
        f"{t} {kind} {unit}" + (f" ({who})" if who else "")
        + (f" at {place}" if place else "")
        for t, kind, unit, who, place in rows)


def departed_since(seconds: float = 900.0) -> list[dict]:
    """Who has vacated a slot lately, and what they were flying.

    The bridge needs this because an aeroplane nobody is sitting in must leave
    the SEPARATION board, and that board lives in another process. A stale
    entry is not merely untidy: two entries make the deterministic engine
    engage, so one leftover callsign turns a single-ship approach into a
    sequencing problem between a pilot and his own former self -- holds,
    stack levels and a banishment, all issued over the top of correct vectors.
    """
    try:
        _ensure_table()
        with get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT unit_name, COALESCE(player,''), "
                "       extract(epoch FROM (now() - at)) "
                "  FROM events "
                " WHERE kind = 'player_leave_unit' "
                "   AND at > now() - make_interval(secs => %s) "
                " ORDER BY at DESC", (seconds,)).fetchall()
    except Exception as e:
        log.warning("departed_since: %s", e)
        return []
    return [{"unit": u, "player": p, "ago_sec": round(float(a), 1)}
            for u, p, a in rows]
