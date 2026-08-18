"""One lock per SEAT, so a controller who is thinking cannot silence the rest.

    "Serialisation is per FREQUENCY -- two controllers at two aerodromes talk
     at once, two transmissions on one channel wait, which is what a blocked
     transmission is."                                          -- CLAUDE.md

The radio has honoured that since `radio/pool.py` replaced the global lock. The
director did not. `_atc_busy` was keyed on the session id, and ONE BRIDGE WORKS
EVERY FREQUENCY IN THE THEATRE UNDER ONE SESSION -- so while Batumi Approach
composed (a median of 3.3 s and a worst case of 13.5), Kobuleti Ground's pilot
got `{"response": "", "busy": true}` and heard nothing at all. He is on the ramp
forty miles away from the aeroplane that is holding up his taxi clearance.

A dropped transmission is a controller who said nothing, and the bridge has no
way to tell that from a controller who chose to say nothing. That is why this is
worth a module rather than a different dictionary key.

WHAT IS ACTUALLY SERIALISED, in both places, is the one thing that can only do
one job at a time. On the radio that is a frequency: one channel, one voice.
Here it is the AGENT -- strands raises ConcurrencyException when a second call
arrives while the first is still in flight, which surfaced as an HTTP 500 and
then poisoned every transmission after it. So the lock belongs on the agent's
own identity, and `app.py` hands it the very tuple the agent cache is keyed on:
`(session_id, station, role, also, mission)`. One key, one agent, one lock, and
nothing else in the theatre waits on it.

That the two are keyed alike is the whole invariant, and it is cheap to state:
a lock coarser than the thing it guards silences seats that were never busy,
and a lock finer than it lets two calls into one agent.

STILL DROPPING, NEVER QUEUEING, and that half is deliberate -- docs/GOTCHAS.md
argues it and it is not reopened here. The caller has already given up and moved
on, so a queued answer arrives after the next exchange has started and the
controller replies to a transmission two ago. The pool WAITS because a
transmission that has already been composed must reach the air; a model call
that has not started yet has nothing to deliver, and the pilot can ask again.
What changes here is what the lock is keyed on. Nothing else.
"""

from __future__ import annotations

import threading


class SeatLocks:
    """A lock per seat, made on demand -- `radio.pool.TransmitPool._lock_for`.

    A dict of locks rather than one lock, for exactly the reason 124.425 and
    133.000 do not wait for each other on the radio.
    """

    def __init__(self) -> None:
        self._locks: dict[tuple, threading.Lock] = {}
        # The dict itself is guarded. `setdefault(key, threading.Lock())` builds
        # a throwaway Lock on every call and leans on the GIL to make the swap
        # atomic; saying it costs nothing on a path that is about to talk to
        # Bedrock, and it is what the pool does one layer down.
        self._guard = threading.Lock()

    def lock_for(self, key) -> threading.Lock:
        """The lock for one seat. Never shared with another seat."""
        with self._guard:
            got = self._locks.get(key)
            if got is None:
                got = self._locks[key] = threading.Lock()
            return got

    def clear(self) -> int:
        """Drop them all. Called when the world restarts and every agent goes.

        A lock guarding an agent that no longer exists is one leaked entry per
        seat per sortie, and it would also hold a seat busy across a wipe.
        """
        with self._guard:
            n = len(self._locks)
            self._locks.clear()
        return n

    def __len__(self) -> int:
        return len(self._locks)
