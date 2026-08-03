"""The transmit pool: concurrency where it is real, waiting where it must be.

    "Maybe we can have a pool of clients... maybe we can get away with 10
     shared."

Measured before it was built, because the idea rests on it: 100 clients open in
0.4 s, and 10 transmitting at once took 9.8 s wall for 9.4 s of audio, against
98 s serialised. Ten is generous for one to ten pilots and survives fifty.

The tests below use fake clients. What is being checked is not SRS -- that was
measured against the real server -- but the POLICY: which things wait for each
other, and which do not.
"""

import threading
import time
import unittest
import unittest.mock as mock

from marshall.radio import pool as P


class FakeClient:
    live = []

    def __init__(self, *a, **k):
        self.name = k.get("name", "")
        self.guid = f"guid-{len(FakeClient.live)}"
        self.sent = []
        FakeClient.live.append(self)

    def connect(self, radios):
        return self

    def transmit(self, frames, freqs, modulation, settle=0.4):
        self.sent.append((time.monotonic(), tuple(freqs), settle))
        time.sleep(0.05)          # stand in for paced audio

    def close(self):
        pass


def a_pool(size=3):
    FakeClient.live = []
    with mock.patch.object(P, "SRSClient", FakeClient):
        return P.TransmitPool("host", size=size, log=lambda *_a: None)


class TestItOpensWhatItPromised(unittest.TestCase):

    def test_a_pool_of_n_holds_n_clients(self):
        p = a_pool(4)
        self.assertEqual(len(FakeClient.live), 4)
        self.assertEqual(p.stats()["idle"], 4)

    def test_the_names_are_just_numbers(self):
        """They are interchangeable and the SRS name carries no meaning --
        a controller says who he is in the first three words."""
        a_pool(3)
        self.assertEqual([c.name for c in FakeClient.live],
                         ["Marshall-1", "Marshall-2", "Marshall-3"])


class TestWeDoNotHearOurselves(unittest.TestCase):
    """The problem the pool introduces, and the one thing that must go with it.

    With ONE client this could not happen -- SRS does not echo a client to
    itself. With a pool the listener and the transmitters are different
    clients, so every word we say comes back and looks exactly like a pilot.
    The controller then stands off for his own voice for a second and a half
    after every transmission: the metronome skips, back-to-back calls jitter,
    and nothing in any log explains it.

    Proved by accident while measuring the settle -- a separate listener heard
    all 87 frames of the transmitter beside it.
    """

    def test_the_pool_can_name_every_voice_it_speaks_with(self):
        p = a_pool(3)
        self.assertEqual(len(p.guids), 3)

    def test_the_packet_loop_drops_our_own_and_keeps_a_pilots(self):
        """Read as source, because the decision lives inside a UDP loop that
        cannot be driven without sockets -- and the whole failure is that the
        loop stamps a timestamp it should not have."""
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1]
               / "src/marshall/radio/client.py").read_text()
        body = src[src.index("_guid = data[-GUID_LEN:]"):]
        body = body[:body.index("self.last_rx = time.monotonic()")]
        self.assertIn("if _guid in self.ignore_guids:", body)
        self.assertIn("continue", body,
                      "our own voice reaches the timestamp anyway")


class TestDifferentFrequenciesDoNotWait(unittest.TestCase):
    """The entire point. Two controllers at two aerodromes talk at once."""

    def test_two_channels_overlap_in_time(self):
        p = a_pool(3)
        done = []

        def send(hz):
            t0 = time.monotonic()
            p.transmit([b"x"], hz)
            done.append((hz, t0, time.monotonic()))

        ts = [threading.Thread(target=send, args=(h,))
              for h in (124_425_000, 133_000_000)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        (_, a0, a1), (_, b0, b1) = done
        self.assertLess(max(a0, b0), min(a1, b1),
                        "the two transmissions did not overlap at all")


class TestTheSAMEFrequencyDoesWait(unittest.TestCase):
    """Removing the global lock must not let two voices onto one channel.

    That is not concurrency, it is a blocked transmission -- which on a real
    radio is exactly what two people keying at once sounds like.
    """

    def test_one_channel_is_serialised(self):
        """Timed at the CLIENT, not at the call.

        A first version stamped the clock before `transmit` and both threads
        recorded it before either had the channel lock -- so it proved they
        were called at the same time, which was never in question.
        """
        p = a_pool(3)
        ts = [threading.Thread(target=p.transmit, args=([b"x"], 124_425_000))
              for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        starts = sorted(t for c in FakeClient.live for t, _f, _s in c.sent)
        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1] - starts[0], 0.04,
                                "two transmissions overlapped on one frequency")

    def test_a_facility_with_several_frequencies_locks_all_of_them(self):
        """`channels_of` sends one call on 124.425 AND 124.000. A second
        transmission touching either must wait for both."""
        p = a_pool(3)
        ts = [threading.Thread(target=p.transmit, args=([b"x"], f))
              for f in ([124_425_000, 124_000_000], [124_000_000])]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        starts = sorted(t for c in FakeClient.live for t, _f, _s in c.sent)
        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1] - starts[0], 0.04,
                                "overlapped on a shared channel")

    def test_overlapping_channel_sets_cannot_deadlock(self):
        """Locks are taken in sorted order for exactly this. Two transmissions
        wanting {A,B} and {B,A} in opposite orders would hold one each and wait
        forever."""
        p = a_pool(4)
        pairs = [[118_600_000, 118_000_000], [118_000_000, 118_600_000]] * 3
        ts = [threading.Thread(target=p.transmit, args=([b"x"], f)) for f in pairs]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=5)
        self.assertFalse([t for t in ts if t.is_alive()], "deadlocked")


class TestAWarmClientSkipsTheSettle(unittest.TestCase):
    """What makes a pool worth more than creating a client per transmission.

    Measured against the real SRS server with a listener counting frames:

        warm client,  settle 0    87/87, four times out of four
        fresh client, settle 0    87, 86, 87, 87 -- clips, one run in four

    Forty milliseconds is the first syllable of a callsign, and an intermittent
    clip is worse than a reliable one because nobody can reproduce it. So the
    first transmission on a client pays the settle and the rest do not, which
    is 0.4 s off every reply after the first.
    """

    def test_the_first_transmission_settles_and_the_next_does_not(self):
        p = a_pool(1)
        p.transmit([b"x"], 124_425_000)
        p.transmit([b"x"], 124_425_000)
        settles = [s for c in FakeClient.live for _t, _f, s in c.sent]
        self.assertEqual(settles, [0.4, 0.0])

    def test_every_client_settles_once(self):
        """A pool of three used three times must settle three times -- one per
        client, not one per pool."""
        p = a_pool(3)
        ts = [threading.Thread(target=p.transmit,
                               args=([b"x"], 120_000_000 + i * 1_000_000))
              for i in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        settles = [s for c in FakeClient.live for _t, _f, s in c.sent]
        self.assertEqual(sorted(settles), [0.4, 0.4, 0.4])


class TestExhaustionWaitsAndSaysSo(unittest.TestCase):

    def test_more_callers_than_clients_all_get_through(self):
        """Waiting, never dropping. Silence on the air is read as a controller
        who has stopped listening, which is the worst failure here."""
        p = a_pool(2)
        ts = [threading.Thread(target=p.transmit,
                               args=([b"x"], 120_000_000 + i * 1_000_000))
              for i in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=5)
        self.assertEqual(sum(len(c.sent) for c in FakeClient.live), 6)

    def test_a_saturated_pool_is_not_silent_about_it(self):
        said = []
        FakeClient.live = []
        with mock.patch.object(P, "SRSClient", FakeClient), \
             mock.patch.object(P, "SLOW_WARN_SEC", 0.0):
            p = P.TransmitPool("host", size=1, log=said.append)
            p.transmit([b"x"], 124_425_000)
        self.assertTrue(any("radio pool" in s for s in said),
                        "saturation was silent, which makes it a sizing bug "
                        "nobody can find")

    def test_a_client_is_returned_even_when_the_transmission_raises(self):
        """A leaked client is a pool that shrinks until it deadlocks, and the
        symptom would be a controller going quiet an hour into a sortie."""
        p = a_pool(2)
        for c in FakeClient.live:          # whichever gets picked must fail
            c.transmit = mock.Mock(side_effect=OSError("radio down"))
        with self.assertRaises(OSError):
            p.transmit([b"x"], 124_425_000)
        self.assertEqual(p.stats()["idle"], 2, "a client leaked")
        # And the channel is free again -- a held lock would be a frequency
        # that has gone permanently silent.
        self.assertFalse(p._lock_for(124_425_000).locked())


if __name__ == "__main__":
    unittest.main()
