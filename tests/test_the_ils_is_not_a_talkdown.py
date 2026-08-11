"""The ILS arrival: vector, clear, then get off the air.

    "ive never flown an ILS with marshall yet - just the ASR and Visual"

Which is why none of this was pinned, and why the whole procedure was silently
dead: `profile.vectored` is False for an ILS -- correctly, because it asks who
owns navigation ALL THE WAY DOWN, and on an ILS that is the pilot -- and both
the guidance context and the radar monitor were gated on it. An ILS recovery
therefore got no vectors, no descent, no clearance and no geometry at all. The
controller had to improvise the entire arrival from nothing.

The two procedures divide the work in opposite places and that is the whole
content of this file:

    ASR    the controller IS the approach aid. He owns it to the runway --
           a range every mile, a heading, an altitude, all the way to the MAP.
    ILS    the controller owns the INTERCEPT only. He vectors, he clears, and
           at established he stops: the pilot has a localiser and a glidepath
           and is flying both, and every further word is chatter over a busy
           man -- or worse, an altitude off a table disagreeing with his
           glideslope, once a mile, all the way down.

See docs/ISSUES.md #117 and `asr_context` / the ASR monitor in agent_atc.py.
"""

import unittest

from marshall.atc import agent_atc, asr, talkdown
from marshall.atc.geometry import Position
from marshall.core import route as R
from marshall.core.approach import may_vector


class TestMayVector(unittest.TestCase):
    """One question, asked one way. It was asked three and they disagreed."""

    def test_the_ils_controller_vectors(self):
        # He does not talk the pilot down, but he absolutely gives headings --
        # that is the half of the approach he owns.
        self.assertTrue(may_vector(R.KOBULETI_ILS))

    def test_the_surveillance_approach_vectors(self):
        self.assertTrue(may_vector(R.BATUMI_ASR))

    def test_the_beacon_letdown_never_does(self):
        # The homing adapter points the nose at the beacon: a heading destroys
        # the only course reference he has. The capability says so outright and
        # it wins over anything the procedure implies.
        self.assertFalse(may_vector(R.BATUMI_APPROACH))

    def test_vectored_is_a_different_question_and_stays_one(self):
        # `vectored` asks who navigates to the runway; `may_vector` asks whether
        # a heading may be issued at all. Both are false for the letdown and
        # they differ on the ILS, which is exactly the case that was broken.
        self.assertFalse(R.KOBULETI_ILS.vectored)
        self.assertTrue(may_vector(R.KOBULETI_ILS))


def _inbound(profile, range_nm, xtk_nm=0.0, alt_ft=3000, heading=None):
    """A contact on the inbound radial, offset `xtk_nm` right of course."""
    import math
    crs = profile.final_crs_true
    # Positive cross-track is right of course as he flies it in -- see
    # geometry.cross_track, which this inverts.
    off = math.degrees(math.asin(max(-1.0, min(1.0, -xtk_nm / range_nm))))
    return Position(range_nm=range_nm,
                    radial_deg=((crs + 180) % 360 + off) % 360,
                    alt_ft=alt_ft,
                    heading_deg=crs if heading is None else heading,
                    speed_kt=200.0)


class TestTheInterceptCarriesTheClearance(unittest.TestCase):
    """The last vector is a different transmission from the ones before it."""

    P = R.KOBULETI_ILS

    def test_a_repositioning_turn_is_not_the_intercept(self):
        # Well outside the final segment and being taken across it. Clearing
        # him here would have him descend on a heading that is not yet the
        # centreline.
        pos = _inbound(self.P, 30.0, xtk_nm=12.0, alt_ft=6000,
                       heading=(self.P.final_crs_true + 150) % 360)
        g = asr.guide(pos, self.P)
        self.assertFalse(talkdown.is_the_intercept(g, self.P))

    def test_turning_onto_the_localiser_is(self):
        # A mile off the course at seventeen, cutting in. This is where the
        # geometry actually turns him onto the localiser -- it was written as
        # 12 nm and 2.5 off, which the engine flies DOWNWIND, so the fixture
        # was asserting about a repositioning leg.
        pos = _inbound(self.P, 17.0, xtk_nm=1.0, alt_ft=4800)
        g = asr.guide(pos, self.P)
        self.assertTrue(talkdown.is_the_intercept(g, self.P))

    def test_the_clearance_says_until_established(self):
        pos = _inbound(self.P, 17.0, xtk_nm=1.0, alt_ft=4800)
        g = asr.guide(pos, self.P)
        said = talkdown.approach_clearance(g, self.P)
        self.assertIn("until established", said)
        self.assertIn("cleared ILS runway", said)
        self.assertIn("approach", said)

    def test_the_altitude_is_said_once(self):
        # "turn right zero one zero, maintain three thousand, maintain three
        # thousand until established" is what the obvious version transmits.
        pos = _inbound(self.P, 17.0, xtk_nm=1.0, alt_ft=4800)
        g = asr.guide(pos, self.P)
        clr = talkdown.approach_clearance(g, self.P)
        said = talkdown.vector_call(agent_atc.Bridge(), "Pony 1-1", g, pos, clr)
        self.assertEqual(said.count("maintain"), 1, said)

    def test_a_plain_vector_is_unchanged(self):
        # No clearance, no tail: every ASR vector ever issued still reads the
        # same, which is what the 1007 subtests in the sweep are pinned to.
        pos = _inbound(self.P, 30.0, xtk_nm=12.0, alt_ft=6000,
                       heading=(self.P.final_crs_true + 150) % 360)
        g = asr.guide(pos, self.P)
        said = talkdown.vector_call(agent_atc.Bridge(), "Pony 1-1", g, pos)
        self.assertNotIn("cleared", said)
        self.assertTrue(said.endswith("."), said)


class TestEstablishedIsWhereHeStops(unittest.TestCase):
    """On the needles, the controller's job is a handoff and then silence."""

    def scope(self, profile, nm, alt=2000, tag="Pony one one"):
        radial = (profile.final_crs_true + 180) % 360
        return (f"Enfield11 [{tag}] (F-16C_50): {nm} nm on the {radial:.0f} "
                f"radial, {alt:,} ft, heading {profile.final_crs_true:.0f}")

    def test_the_guidance_context_goes_quiet(self):
        pos = _inbound(R.KOBULETI_ILS, 6.0, alt_ft=2000)
        self.assertTrue(asr.guide(pos, R.KOBULETI_ILS).established)
        # It is prose for the agent, so this asserts on what it is TOLD rather
        # than on a phrase: say nothing about range, heading, altitude or the
        # glidepath -- which we cannot see -- and hand him to Tower.
        out = agent_atc.asr_context(
            R.KOBULETI_ILS, self.scope(R.KOBULETI_ILS, 6.0), "Pony 1-1")
        self.assertIn("SAY NOTHING", out)
        self.assertIn("Tower", out)

    def test_the_guidance_context_vectors_before_that(self):
        # The bug in one assertion: this returned "" for the whole approach.
        out = agent_atc.asr_context(
            R.KOBULETI_ILS, self.scope(R.KOBULETI_ILS, 25.0, alt=8000),
            "Pony 1-1")
        self.assertNotEqual(out, "")
        self.assertIn("ILS", out)

    def test_the_asr_still_talks_him_all_the_way_down(self):
        # The contrast that makes the ILS silence meaningful. On a surveillance
        # approach the controller IS the approach aid, so established is where
        # the mile calls START, not where they stop.
        pos = _inbound(R.BATUMI_ASR, 6.0, alt_ft=2000)
        g = asr.guide(pos, R.BATUMI_ASR)
        self.assertTrue(g.established)
        said = talkdown.asr_call(agent_atc.Bridge(), "Pony 1-1", g, pos,
                                 R.BATUMI_ASR)
        self.assertIn("miles from the runway", said)


if __name__ == "__main__":
    unittest.main()
