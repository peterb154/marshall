"""One transmission, several frequencies. What makes a mixed-era field possible.

    "The reason ours round is that the WW2 airplanes can't tune to those finer
     frequencies... I wonder if SRS lets us duplex a channel, so we can use both
     124.425 for modern and 124.00 for a SCR-522 radio seamlessly."

It does, and it always did. The SRS voice packet carries a VARIABLE-LENGTH
frequency list -- `_voice_packet` has packed one for as long as it has existed
-- and `transmit` simply wrapped a single value in it.

VERIFIED AGAINST A LIVE SERVER, which is the only way this could be known: a
warbird listening on 124.000, a modern jet on 124.425, and one transmission
naming both. Each heard it once. Not a relay and not two calls a beat apart --
one packet, one voice, two radios, and neither pilot can tell there was a second
frequency.

WHY IT MATTERS. The SCR-522 in a P-51 tunes four crystal channels and cannot
reach 124.425. The published AIP plate for Batumi says APP 124.425 because that
is the real frequency. Without duplex a controller must choose which aircraft to
be audible to, and the 1944 Mustang and the F-16 are on different fields.

These tests are the cheap half -- that the packet is built correctly for one
frequency and for several. The expensive half is the live check above, which
needs a server and lives in the rehearsal tools.
"""

import struct
import unittest

from marshall.radio.client import AM, SRSClient


class _Bare(SRSClient):
    """A client that never touches a socket. `_voice_packet` is pure."""

    def __init__(self):
        self.guid = "x" * 22
        self.unit_id = 1
        self.packet_id = 0


def freqs_in(packet: bytes) -> list[float]:
    """Read the frequency list back out of a voice packet.

    The header is three little-endian shorts -- total, audio length, frequency
    segment length -- and each frequency is a double plus two bytes.
    """
    _total, audio_len, freq_len = struct.unpack("<HHH", packet[:6])
    seg = packet[6 + audio_len:6 + audio_len + freq_len]
    return [struct.unpack("<dBB", seg[i:i + 10])[0]
            for i in range(0, len(seg), 10)]


class TestOneFrequency(unittest.TestCase):
    def test_a_single_value_still_works(self):
        """Every existing caller passes a float and must keep working."""
        p = _Bare()._voice_packet(b"audio", [(124.0e6, AM, 0)])
        self.assertEqual(freqs_in(p), [124.0e6])


class TestSeveralFrequencies(unittest.TestCase):
    """The WW2 channel and the published one, in one packet."""

    WW2, MODERN = 124.000e6, 124.425e6

    def test_both_are_carried(self):
        p = _Bare()._voice_packet(b"audio", [(self.WW2, AM, 0),
                                             (self.MODERN, AM, 0)])
        self.assertEqual(freqs_in(p), [self.WW2, self.MODERN])

    def test_the_segment_grows_by_exactly_one_entry(self):
        """Ten bytes per frequency: a double and two flag bytes. If this ever
        changes, the packet is malformed and the server drops it silently --
        which sounds exactly like a controller nobody can hear."""
        one = _Bare()._voice_packet(b"audio", [(self.WW2, AM, 0)])
        two = _Bare()._voice_packet(b"audio", [(self.WW2, AM, 0),
                                               (self.MODERN, AM, 0)])
        self.assertEqual(len(two) - len(one), 10)

    def test_the_declared_length_matches_what_was_written(self):
        """The header declares the segment length and the server trusts it."""
        p = _Bare()._voice_packet(b"audio", [(self.WW2, AM, 0),
                                             (self.MODERN, AM, 0)])
        _total, audio_len, freq_len = struct.unpack("<HHH", p[:6])
        self.assertEqual(freq_len, 20)
        self.assertEqual(audio_len, len(b"audio"))


if __name__ == "__main__":
    unittest.main()


class TestAFacilityOwnsItsFrequencies(unittest.TestCase):
    """One controller, several channels, and a pilot on any of them reaches him.

        "The SCR-522 only has 4 presets, no changing them in cockpit - so a
         mission designer has to choose what freqs a P-51 will get."

    Which is why this is a property of the FACILITY rather than of a
    transmission. A pilot cannot retune, so the controller has to be where the
    aeroplane already is -- and the published frequency stays published, because
    it is what the plate prints and what a modern radio dials.

    The consequence for warbird fields -- that Tower ends up covering ground and
    approach because there are only four presets to spend -- is a behaviour on
    top of this, not a change to it. `Station.also` already models a man wearing
    several hats.
    """

    def setUp(self):
        from marshall.core import route as R
        self.p = R.BATUMI_ASR

    def test_the_published_frequency_is_the_primary(self):
        """AIP Georgia AD 2.UGSB-IAC-12-ILSy: APP 124.425, TWR 118.600. The
        scanned plate on the kneeboard prints these, so they are what a pilot
        reads and expects to dial."""
        self.assertEqual(self.p.station_for("approach").freq_mhz, 124.425)
        self.assertEqual(self.p.station_for("tower").freq_mhz, 118.600)

    def test_the_tunable_channel_is_carried_beside_it(self):
        self.assertIn(124.000, self.p.station_for("approach").freqs)
        self.assertIn(118.000, self.p.station_for("tower").freqs)

    def test_either_one_reaches_the_same_controller(self):
        """The whole point. A warbird on the rounded channel and a jet on the
        published one are talking to the same man, and `station_on` has to agree
        or one of them is answered by nobody."""
        for mhz in (124.425, 124.000):
            with self.subTest(mhz=mhz):
                self.assertEqual(self.p.station_on(mhz).name, "Batumi Approach")
        for mhz in (118.600, 118.000):
            with self.subTest(mhz=mhz):
                self.assertEqual(self.p.station_on(mhz).name, "Batumi Tower")

    def test_a_frequency_nobody_owns_still_reaches_nobody(self):
        """Widening the match must not make every frequency somebody's."""
        self.assertIsNone(self.p.station_on(121.500))
