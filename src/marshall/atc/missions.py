"""Which sortie is this? Decided once, then looked up.

Every flight, contact and assigned plan is scoped to a `mission` key so that
yesterday's sortie cannot answer today's question. That key used to be DERIVED
on each process start:

    started = int(wall_clock_now - timer.getTime())

`timer.getTime()` is DCS MODEL time. It does not advance while the mission is
paused and wall clock does, so the difference is not a constant -- it grows by
every pause the server takes. The key MOVED over the life of one mission, and
every process starting after a pause computed a different one.

Measured 18 August, on a mission that had been up 6.7 days:

    rows on the board were written under   ...@1786509383
    a process starting now computed        ...@1786509377

Six seconds apart, so `board.find(mission=...)` matched nothing. The rows were
not deleted, they were unreachable -- which is worse, because the table looks
EMPTY rather than wrong. A pilot on the radio was refused his clearance with
"nobody is listed under that callsign" while his own row sat in `flights` under
a key nobody would ever compute again.

    "We agreed weeks ago that a flight plan does not need to have a
     pilot/aircraft on it ... Why would the agent respond like this?"

It was never about the plan. The plan was found; the AEROPLANE was in another
bucket.

SO THE KEY IS WRITTEN DOWN THE FIRST TIME A MISSION IS SEEN and read back
afterwards. A derived value that drifts cannot be made to stop drifting by
rounding it -- that widens the window in which two processes agree and calls it
a fix, which is the same trade this project made with `_squash` and then
deleted.

A GENUINE RELOAD IS STILL A DIFFERENT WORLD, and is detected by the one signal
that cannot be faked: model time RESTARTS. `timer.getTime()` is monotonic
within a mission, so elapsed going BACKWARDS means the sim loaded something
new. Pauses move the derived start; they never move elapsed backwards. That
asymmetry is the whole design.  [#187]
"""

from __future__ import annotations

import logging
import time

from marshall.core.db import pool as get_pool

log = logging.getLogger(__name__)

# How far model time may go backwards before it counts as a reload rather than
# as noise. gRPC round-trips and the sim's own tick mean two readings a second
# apart can disagree by a fraction; a real reload drops elapsed by hours.
#
# NOT A TOLERANCE ON THE KEY -- that is what was wrong before. This is a
# tolerance on detecting a RESET, where the two cases differ by orders of
# magnitude rather than by seconds, so no plausible jitter reaches it.
RELOAD_SLACK_SEC = 60.0


def resolve(name: str, elapsed: float) -> str:
    """The instance key for this mission, minting one only if it is new.

    `name` is the mission's own name from the sim; `elapsed` is
    `timer.getTime()`. Raises nothing the caller has to handle -- a store that
    cannot be reached is the caller's problem to degrade over, and it is the
    one case where guessing is worse than saying so.
    """
    with get_pool().connection() as c:
        row = c.execute(
            "SELECT instance, last_elapsed FROM mission_instances "
            "WHERE name = %s ORDER BY last_elapsed DESC LIMIT 1",
            (name,)).fetchone()
        if row is not None:
            instance, last = row[0], float(row[1])
            # MONOTONIC MEANS SAME MISSION. Elapsed may only go up while one
            # mission runs, so anything at or above what we last saw is this
            # same world however long it has been paused.
            if elapsed >= last - RELOAD_SLACK_SEC:
                c.execute(
                    "UPDATE mission_instances SET last_elapsed = GREATEST("
                    "last_elapsed, %s), last_seen = now() WHERE instance = %s",
                    (elapsed, instance))
                return instance
            log.info("model time went backwards (%.0f -> %.0f): the sim has "
                     "loaded a new mission", last, elapsed)
        # NEW WORLD. The derived start is used ONCE, here, and then never
        # recomputed -- which is the entire point. It is still the best label
        # available: two instances of one mission file are told apart by when
        # they began.
        started = int(time.time() - elapsed)
        instance = f"{name}@{started}"
        c.execute(
            "INSERT INTO mission_instances (name, instance, started, "
            "last_elapsed) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (instance) DO UPDATE SET last_elapsed = GREATEST("
            "mission_instances.last_elapsed, EXCLUDED.last_elapsed), "
            "last_seen = now()",
            (name, instance, started, elapsed))
        return instance
