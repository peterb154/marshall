"""Standing off for a pilot on YOUR frequency, and nobody else's.

    "My guess is the real issue is controllers need to listen on a frequency to
     know when it's clear to speak. How would we manage that across n
     controllers?"

That was the real issue. One SRS client listens on every frequency in the
theatre -- twelve today -- and it kept ONE `last_rx` timestamp for all of them.
So `someone_is_talking()` meant "anybody, anywhere", and a pilot checking in
with Kobuleti Clearance held Batumi Approach silent forty miles away.

A courtesy applied to the wrong conversation, invisible with one aerodrome and
worse with every field added.
"""

import time
import unittest

from marshall.radio.client import SRSClient


def a_client():
    c = SRSClient.__new__(SRSClient)      # no socket, no server
    c.last_rx = 0.0
    c.last_rx_hz = {}
    return c


def heard(c, mhz, ago=0.0):
    """Pretend voice arrived on that frequency `ago` seconds back."""
    now = time.monotonic() - ago
    c.last_rx = now
    c.last_rx_hz[int(round(mhz * 1e6))] = now


class TestItIsPerFrequency(unittest.TestCase):

    def test_a_pilot_on_MY_channel_holds_me_off(self):
        c = a_client()
        heard(c, 124.425)
        self.assertTrue(c.someone_is_talking(freq_hz=124.425e6))

    def test_A_PILOT_ON_ANOTHER_CHANNEL_DOES_NOT(self):
        """The bug. Kobuleti Clearance is not Batumi Approach's business."""
        c = a_client()
        heard(c, 125.100)
        self.assertFalse(c.someone_is_talking(freq_hz=124.425e6),
                         "held off for a conversation at another aerodrome")

    def test_a_facilitys_other_frequency_IS_his_business(self):
        """124.425 and 124.000 are one conversation reaching two kinds of
        radio, so a warbird on the rounded channel holds the same controller
        off as a jet on the published one."""
        c = a_client()
        heard(c, 124.000)
        self.assertTrue(c.someone_is_talking(freq_hz=[124.425e6, 124.000e6]))

    def test_it_still_goes_quiet_after_a_moment(self):
        c = a_client()
        heard(c, 124.425, ago=5.0)
        self.assertFalse(c.someone_is_talking(freq_hz=124.425e6))

    def test_asking_about_nothing_in_particular_means_anywhere(self):
        """The old meaning, kept for callers that genuinely want it -- and it
        is almost never what a caller wants now, which the docstring says."""
        c = a_client()
        heard(c, 139.000)
        self.assertTrue(c.someone_is_talking())

    def test_a_channel_nobody_has_used_is_free(self):
        self.assertFalse(a_client().someone_is_talking(freq_hz=118.6e6))


class TestItScalesWithAerodromes(unittest.TestCase):
    """The question behind the question: how does this work across N fields?"""

    def test_one_listener_serves_every_frequency_independently(self):
        """Which is the answer -- the listener does not need duplicating, only
        its bookkeeping did. One client, one timestamp PER channel."""
        from marshall.core import route as R
        c = a_client()
        busy = R.APPROACH.freq_mhz
        heard(c, busy)
        others = [s for s in R.STATIONS if not s.hears(busy)]
        self.assertGreaterEqual(len(others), 6)
        for s in others:
            with self.subTest(station=s.name):
                self.assertFalse(c.someone_is_talking(freq_hz=s.freq_mhz * 1e6),
                                 f"{s.name} stood off for a call on {busy}")


if __name__ == "__main__":
    unittest.main()
