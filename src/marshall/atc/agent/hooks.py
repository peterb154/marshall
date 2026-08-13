"""Agent-set wake-up hooks — the seam that lets a request/response agent act on a
timer it cannot hold itself.

The agent is only alive during a /chat call, so it can't wait five minutes and
then key the mic. Instead it registers a hook here ("wake me in 300s, and here's
why"); `marshall-atc`'s scheduler polls for due hooks and re-invokes the agent with
that `why` as context, so it makes the call it promised. One durable poller in
`marshall-atc`, many logical hooks multiplexed on top.

A HOOK BELONGS TO THE CONTROLLER WHO MADE THE PROMISE, and until this it did
not. `_HOOKS` was keyed on the session id alone, and one voice process works every
frequency in the theatre under one session (`"hooks"`). So Kobuleti Ground told
Viper 1-1 "stand by, I'll call you back for taxi", the hook came back with no
seat on it, and `marshall-atc` fell back to guessing the channel from the last one
anybody spoke on -- Batumi Approach's 124.425. Batumi Approach then voiced
Kobuleti Ground's taxi callback, on the arrival frequency, to a jet still on the
ramp. A real controller, a real frequency, the wrong one: the shape this project
keeps finding.

It is the same lesson `store_id` in app.py argues at length for the transcript
and `memory_tools(namespace=store)` obeys -- a role is only unique WITHIN an
aerodrome -- and this was the one per-session binding that had not been given
the seat. Touches #25/#44 criterion 9: "a promise made on one frequency is still
kept on that frequency."

WHAT IS STILL OWED, and it is one line and it is not here. `marshall-atc` recovers
the channel with `hook_frequency(why, bridge.heard_on, bridge.last_active_hz[0])`
(`atc/agent_atc.py`), which reads the callsign out of the `why` text and falls
back to the last active channel. Every hook now comes back carrying `station`
and `role`, so `marshall-atc` can resolve the seat's own frequency and stop
guessing; until it reads them the promise is still spoken wherever the guess
lands. The language brain cannot fix that half -- it is never told which frequency a
seat sits on.

Timer-only for now. gRPC event/telemetry hooks (StreamEvents / StreamUnits) will
register on this SAME surface later — a hook just grows other kinds of `when`,
and the agent's prompt never has to learn mission-specific conditions.
"""

from __future__ import annotations

import time

try:
    from strands import tool
except ImportError:                     # importable without strands (tests)
    def tool(fn):
        return fn

# (session_id, seat) -> list of pending hooks. Module-level so it survives across
# the per-session agent instances; lost on an agent-container restart, which is fine for
# a volatile letdown (nobody wants a stale five-minute hook after a reboot).
_HOOKS: dict[tuple[str, str], list[dict]] = {}
_seq = 0


def seat_of(station: str = "", role: str = "") -> str:
    """Which controller, normalised — THE SAME RULE `app.store_id` USES.

    The station first and the role only as a fallback, because "Kobuleti Ground"
    and "Batumi Ground" are both `ground`, and keying two men at two aerodromes
    on one word is precisely the fault this is closing. An older voice process that
    sends neither gets "", i.e. the whole session, which is what it always had.
    """
    return (station or role or "").strip().lower().replace(" ", "-")


def set_hook_for(session_id: str, seconds: float, why: str,
                 station: str = "", role: str = "") -> dict:
    global _seq
    _seq += 1
    seat = seat_of(station, role)
    # THE SEAT TRAVELS ON THE HOOK, not just in the key. `marshall-atc` polls per
    # SESSION -- it has one scheduler for the whole theatre -- so a key it never
    # sees cannot tell it whose promise this is. What comes back must say.
    hook = {"id": _seq, "fire_at": time.time() + max(1.0, float(seconds)),
            "seconds": int(seconds), "why": why,
            "seat": seat, "station": station, "role": role}
    _HOOKS.setdefault((session_id, seat), []).append(hook)
    return hook


def due_hooks(session_id: str, now: float | None = None) -> list[dict]:
    """Return hooks whose time has come and remove them (one-shot).

    EVERY SEAT UNDER THIS SESSION, because `marshall-atc` has one scheduler for the
    whole theatre and that is what it asks for. Splitting the key must not lose
    a hook; what it buys is that each one comes back saying who owes it, so "all
    of them" stops meaning "anybody's".

    Sorted by when they were set, so two controllers coming due on the same tick
    are answered in the order they promised rather than in dictionary order.
    """
    now = now if now is not None else time.time()
    due = []
    for (sid, st), pending in list(_HOOKS.items()):
        if sid != session_id:
            continue
        ripe = [h for h in pending if h["fire_at"] <= now]
        if ripe:
            _HOOKS[(sid, st)] = [h for h in pending if h["fire_at"] > now]
            due.extend(ripe)
    return sorted(due, key=lambda h: h["id"])


def pending_hooks(session_id: str) -> list[dict]:
    return [h for (sid, _seat), hs in _HOOKS.items() if sid == session_id
            for h in hs]


def hook_tools(session_id: str, station: str = "", role: str = "") -> list:
    """The agent's hook tools, bound to his SEAT (like memory_tools).

    `build_agent` passes the station and the role it was handed by `marshall-atc` --
    the trusted side, resolved from the frequency before the call was made -- so
    a controller cannot register a promise in another controller's name.
    """

    @tool
    def set_hook(seconds: int, why: str) -> str:
        """Schedule a wake-up. After `seconds` you will be re-invoked with `why`
        as context, so you can make a call you cannot make right now — e.g. after
        telling a pilot "expect clearance in five minutes," set a hook for 300 so
        you actually call him back. Use this instead of promising a callback you
        would otherwise never make. One-shot; set another if you need to check
        again."""
        hook = set_hook_for(session_id, seconds, why, station, role)
        return f"Hook set — I'll be woken in {hook['seconds']}s: {why}"

    return [set_hook]
