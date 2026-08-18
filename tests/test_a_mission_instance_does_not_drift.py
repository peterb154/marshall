"""The bucket a sortie's rows live in must not move while the sortie runs.

Every flight, contact and assigned plan is scoped to a `mission` key. It was
DERIVED on each process start:

    started = int(wall_clock_now - timer.getTime())

`timer.getTime()` is DCS MODEL time. It stops while the mission is paused and
wall clock does not, so the difference grows by every pause the server takes.
Measured 18 August on a mission up 6.7 days:

    rows on the board were written under   ...@1786509383
    a process starting now computed        ...@1786509377

Six seconds apart. `board.find(mission=...)` matched nothing, so the rows were
not deleted but UNREACHABLE -- which is worse, because the table reads as empty
rather than as wrong. A pilot was refused his clearance with "nobody is listed
under that callsign" while his own row sat in `flights` under a key nobody
would compute again.

AGAINST THE REAL DATABASE, and it SKIPS LOUDLY rather than stubbing one.

    "i dont care about how fast the test run when its clear they arent
     protecting us from mis-alignment!"

That is the lesson of the same sortie and it applies to this file first. 2,463
tests passed while the in-memory board and `flights` disagreed about whether an
aeroplane existed -- they were fast because they exercised the cache, and they
exercised the cache instead of the system, so no number of them could have seen
it. A stubbed pool here would reproduce that exactly: it would test that this
module can call functions, which is not the thing that broke.  [#187]
"""

from __future__ import annotations

import unittest

from marshall.atc import missions


class _NeedsTheStore(unittest.TestCase):
    """Every case here talks to Postgres or announces that it did not."""

    NAME = "unit-test-mission-instance"

    def setUp(self):
        from marshall.core.db import pool
        try:
            with pool().connection() as c:
                c.execute("SELECT 1 FROM mission_instances LIMIT 1")
        except Exception as e:
            self.skipTest(
                f"no database, so mission scoping is UNGUARDED — the bug this "
                f"file exists for is invisible without one: {e}")
        self._wipe()
        self.addCleanup(self._wipe)

    def _wipe(self):
        from marshall.core.db import pool
        with pool().connection() as c:
            c.execute("DELETE FROM mission_instances WHERE name = %s",
                      (self.NAME,))


class APauseDoesNotMintANewBucket(_NeedsTheStore):
    """The bug, as it actually happened."""

    def test_the_same_mission_keeps_its_key_across_a_pause(self):
        first = missions.resolve(self.NAME, 576267.3)
        # Six seconds of pause: wall clock moved and model time did not, which
        # is precisely what shifted the derived start by six.
        later = missions.resolve(self.NAME, 576267.3)
        self.assertEqual(first, later)

    def test_and_across_hours_of_running(self):
        """Elapsed climbing is the ordinary case and must change nothing."""
        first = missions.resolve(self.NAME, 100.0)
        for elapsed in (500.0, 5_000.0, 576_267.3):
            with self.subTest(elapsed=elapsed):
                self.assertEqual(missions.resolve(self.NAME, elapsed), first)

    def test_the_key_still_names_the_mission(self):
        got = missions.resolve(self.NAME, 100.0)
        self.assertTrue(got.startswith(f"{self.NAME}@"))


class ButAGenuineReloadIsADifferentWorld(_NeedsTheStore):
    """The asymmetry the design rests on: a pause moves the derived start and
    can never move elapsed backwards. A reload resets elapsed to nearly zero.
    """

    def test_model_time_going_backwards_mints_a_new_instance(self):
        first = missions.resolve(self.NAME, 50_000.0)
        after = missions.resolve(self.NAME, 12.0)      # the sim loaded again
        self.assertNotEqual(first, after)

    def test_and_the_old_instance_is_not_destroyed(self):
        """A previous world's rows are not stale data to be tidied. They are
        simply never found -- and must still be there to be found if somebody
        asks with the right key."""
        from marshall.core.db import pool
        first = missions.resolve(self.NAME, 50_000.0)
        missions.resolve(self.NAME, 12.0)
        with pool().connection() as c:
            got = c.execute(
                "SELECT count(*) FROM mission_instances WHERE instance = %s",
                (first,)).fetchone()[0]
        self.assertEqual(got, 1)

    def test_jitter_is_not_a_reload(self):
        """gRPC round-trips and the sim's tick make two readings disagree by a
        fraction. A reload drops elapsed by hours, so the two cases are orders
        of magnitude apart and the slack cannot swallow a real one."""
        first = missions.resolve(self.NAME, 50_000.0)
        self.assertEqual(missions.resolve(self.NAME, 49_999.4), first)


if __name__ == "__main__":
    unittest.main()
