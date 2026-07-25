"""Agent-set wake-up hooks — the seam that lets a request/response agent act on a
timer it cannot hold itself.

The agent is only alive during a /chat call, so it can't wait five minutes and
then key the mic. Instead it registers a hook here ("wake me in 300s, and here's
why"); the bridge's scheduler polls for due hooks and re-invokes the agent with
that `why` as context, so it makes the call it promised. One durable poller in
the bridge, many logical hooks multiplexed on top.

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

# session_id -> list of pending hooks. Module-level so it survives across the
# per-session agent instances; lost on a director restart, which is fine for a
# volatile letdown (nobody wants a stale five-minute hook after a reboot).
_HOOKS: dict[str, list[dict]] = {}
_seq = 0


def set_hook_for(session_id: str, seconds: float, why: str) -> dict:
    global _seq
    _seq += 1
    hook = {"id": _seq, "fire_at": time.time() + max(1.0, float(seconds)),
            "seconds": int(seconds), "why": why}
    _HOOKS.setdefault(session_id, []).append(hook)
    return hook


def due_hooks(session_id: str, now: float | None = None) -> list[dict]:
    """Return hooks whose time has come and remove them (one-shot)."""
    now = now if now is not None else time.time()
    pending = _HOOKS.get(session_id, [])
    due = [h for h in pending if h["fire_at"] <= now]
    if due:
        _HOOKS[session_id] = [h for h in pending if h["fire_at"] > now]
    return due


def pending_hooks(session_id: str) -> list[dict]:
    return list(_HOOKS.get(session_id, []))


def hook_tools(session_id: str) -> list:
    """The agent's hook tools, bound to its session (like memory_tools)."""

    @tool
    def set_hook(seconds: int, why: str) -> str:
        """Schedule a wake-up. After `seconds` you will be re-invoked with `why`
        as context, so you can make a call you cannot make right now — e.g. after
        telling a pilot "expect clearance in five minutes," set a hook for 300 so
        you actually call him back. Use this instead of promising a callback you
        would otherwise never make. One-shot; set another if you need to check
        again."""
        hook = set_hook_for(session_id, seconds, why)
        return f"Hook set — I'll be woken in {hook['seconds']}s: {why}"

    return [set_hook]
