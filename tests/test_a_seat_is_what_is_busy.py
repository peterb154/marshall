"""Which controller is busy, and which ones are not.

    "Serialisation is per FREQUENCY -- two controllers at two aerodromes talk
     at once, two transmissions on one channel wait, which is what a blocked
     transmission is."                                          -- CLAUDE.md

`radio/pool.py` has honoured that since it replaced the global transmit lock,
and `test_pool.py` is where that is proved. The DIRECTOR undid it: `_atc_busy`
was keyed on the session id, and one bridge works every frequency in the theatre
under one session. So Batumi Approach thinking for 3.3 seconds returned
`{"response": "", "busy": true}` to a pilot on the Kobuleti ramp who had asked
for taxi, and he heard nothing at all.

A dropped transmission is a controller who said nothing, and nothing downstream
can tell that from a controller who chose to say nothing. These tests are the
director's half of `TestDifferentFrequenciesDoNotWait` and
`TestTheSAMEFrequencyDoesWait`, deliberately the same shape: what is checked is
the POLICY -- which things wait for each other and which do not.

DROPPING IS NOT THE BUG and is not tested away here. `busy.py` says why: the
caller has already given up, so a queued answer replies to a transmission two
ago. What was wrong was what the lock was keyed on.
"""

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services"))

from tools.busy import SeatLocks

# Two seats at two aerodromes under ONE session id, which is what a bridge
# actually sends: `hooks` for everybody, the seat in `station`.
KOB_GROUND = ("hooks", "Kobuleti Ground", "ground", (), "sortie-1")
BAT_APPROACH = ("hooks", "Batumi Approach", "approach", ("departure",), "sortie-1")


class TestTwoSeatsDoNotWaitOnEachOther(unittest.TestCase):
    """The entire point, and the live symptom that opened this."""

    def test_kobuleti_ground_answers_while_batumi_approach_is_thinking(self):
        locks = SeatLocks()
        held = locks.lock_for(BAT_APPROACH)
        self.assertTrue(held.acquire(blocking=False),
                        "Batumi Approach could not start his own call")
        got = locks.lock_for(KOB_GROUND).acquire(blocking=False)
        held.release()
        self.assertTrue(got, "Kobuleti Ground's transmission was dropped in "
                             "silence because another aerodrome was thinking")

    def test_eight_seats_overlap_in_time(self):
        """The ladder is eight rungs across two fields. None of them queues."""
        locks = SeatLocks()
        seats = [("hooks", f"Seat {i}", "tower", (), "m") for i in range(8)]
        spans = []

        def hold(key):
            lk = locks.lock_for(key)
            if not lk.acquire(blocking=False):
                return
            t0 = time.monotonic()
            time.sleep(0.05)                  # stand in for a model call
            spans.append((t0, time.monotonic()))
            lk.release()

        ts = [threading.Thread(target=hold, args=(s,)) for s in seats]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(spans), 8, "a seat was dropped by another seat")
        self.assertLess(max(s for s, _e in spans), min(e for _s, e in spans),
                        "the eight controllers did not all overlap")

    def test_two_sorties_do_not_share_a_seat(self):
        """The mission is in the key for the same reason the station is."""
        a = ("hooks", "Batumi Tower", "tower", (), "sortie-1")
        b = ("hooks", "Batumi Tower", "tower", (), "sortie-2")
        locks = SeatLocks()
        self.assertTrue(locks.lock_for(a).acquire(blocking=False))
        self.assertTrue(locks.lock_for(b).acquire(blocking=False))


class TestTheSAMESeatDoesWait(unittest.TestCase):
    """Removing the session lock must not let two calls into one agent.

    That is not concurrency. strands raises ConcurrencyException, the endpoint
    returns 500, and one slow call poisons every transmission after it -- seen
    in a dry run as one 30-second answer followed by three 500s.
    """

    def test_a_second_call_to_one_seat_is_refused(self):
        locks = SeatLocks()
        first = locks.lock_for(BAT_APPROACH)
        self.assertTrue(first.acquire(blocking=False))
        self.assertFalse(locks.lock_for(BAT_APPROACH).acquire(blocking=False),
                         "two transmissions reached one agent at once")

    def test_it_is_the_same_lock_object_every_time(self):
        locks = SeatLocks()
        self.assertIs(locks.lock_for(KOB_GROUND), locks.lock_for(KOB_GROUND))

    def test_the_seat_is_free_again_after_the_answer(self):
        locks = SeatLocks()
        lk = locks.lock_for(KOB_GROUND)
        lk.acquire()
        lk.release()
        self.assertTrue(locks.lock_for(KOB_GROUND).acquire(blocking=False))

    def test_the_lock_is_made_once_under_a_race(self):
        """Two threads asking for a seat that does not exist yet must not get
        two locks -- which would be the bug back, invisibly."""
        locks = SeatLocks()
        seen, start = [], threading.Barrier(6)

        def ask():
            start.wait()
            seen.append(locks.lock_for(KOB_GROUND))

        ts = [threading.Thread(target=ask) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len({id(x) for x in seen}), 1,
                         "one seat ended up with two locks")


class TestTheWorldRestartTakesThemAll(unittest.TestCase):
    """`forget_sessions` drops every agent; a lock guarding one that no longer
    exists would leak an entry per seat per sortie, and hold it busy across the
    wipe."""

    def test_clear_reports_how_many_it_dropped(self):
        locks = SeatLocks()
        locks.lock_for(KOB_GROUND).acquire()
        locks.lock_for(BAT_APPROACH)
        self.assertEqual(locks.clear(), 2)
        self.assertEqual(len(locks), 0)
        self.assertTrue(locks.lock_for(KOB_GROUND).acquire(blocking=False),
                        "a seat stayed busy through a world restart")


class TheDirectorActuallyKeysItOnTheSeat(unittest.TestCase):
    """The class is only worth having if `/atc` hands it the right key.

    Read off the source: importing app.py would stand the whole director stack
    up -- strands, boto3 and a Postgres connection at import -- for one
    comparison. `test_capability.py` reads it the same way and for the same
    reason.
    """

    def setUp(self):
        self.src = (Path(__file__).resolve().parent.parent
                    / "services" / "app.py").read_text(encoding="utf-8")

    def test_the_lock_and_the_agent_cache_share_one_key(self):
        # THIS IS THE INVARIANT. A lock coarser than the thing it guards
        # silences seats that were never busy; a lock finer than it lets two
        # calls into one agent. So the two take the same tuple, computed once.
        self.assertIn("lock = _atc_busy.lock_for(_key)", self.src)
        self.assertIn("agent = _atc_agents.get(_key)", self.src)
        self.assertEqual(self.src.count("_key = (session_id, station, role, "
                                        "also, mission)"), 1,
                         "the key is built twice; they can drift apart")

    def test_the_busy_lock_is_not_keyed_on_the_session(self):
        self.assertNotIn("_atc_busy.setdefault(session_id", self.src)

    def test_the_key_is_built_before_the_lock_is_taken(self):
        self.assertLess(self.src.index("_key = (session_id, station, role"),
                        self.src.index("lock = _atc_busy.lock_for(_key)"))

    def test_a_dropped_transmission_names_the_seat(self):
        # "session hooks is busy" was true of eight controllers at two
        # aerodromes at once and said nothing about which pilot heard nothing.
        self.assertIn("station or role or session_id", self.src)

    def test_it_still_drops_rather_than_queues(self):
        self.assertIn("lock.acquire(blocking=False)", self.src)


if __name__ == "__main__":
    unittest.main()
