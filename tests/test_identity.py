"""An aeroplane exists because something that is not a voice says it exists.

[ARCH-2] / #40. These are the rules the board's primary key now rests on, so
they are worth more than the usual care: a wrong identity is worse than no
identity, because none produces "say again" and wrong produces a clearance for
the wrong aeroplane.
"""

import unittest

from marshall.atc import identity

# A real radar picture, copied from a flight recording rather than invented.
SCOPE = ("362nd_sockeye [Pony 1-1] (P-47D-30): 4.1 nm on the 281 radial, "
         "4,659 ft, heading 026 | 362nd Shooter (P-47D-30): 0.5 nm on the 114 "
         "radial, 40 ft, heading 216")


class TestReadingTheScope(unittest.TestCase):
    def test_units_and_their_tags(self):
        us = {u.name: u for u in identity.units_on(SCOPE)}
        self.assertEqual(us["362nd_sockeye"].callsign, "Pony 1-1")
        self.assertEqual(us["362nd_sockeye"].type, "P-47D-30")
        self.assertEqual(us["362nd Shooter"].callsign, "")   # not correlated yet

    def test_junk_costs_nobody_his_identity(self):
        """The scope is prose assembled for a model to read. A parser that
        threw on an odd line would take every aeroplane down with it."""
        self.assertEqual(identity.units_on(""), [])
        self.assertEqual(identity.units_on("no contacts"), [])
        self.assertEqual(len(identity.units_on("garbage | " + SCOPE)), 2)


class TestThePhysicalLink(unittest.TestCase):
    """SRS names a client after the human, DCS names the unit after his slot,
    and one contains the other. Nobody speaks either."""

    def setUp(self):
        self.units = identity.units_on(SCOPE)

    def test_a_radio_finds_its_aeroplane(self):
        self.assertEqual(
            identity.unit_for_radio("Sockeye", self.units).name, "362nd_sockeye")

    def test_decoration_does_not_matter(self):
        """DCS and SRS decorate the same human differently -- squadron numbers,
        underscores, case."""
        for name in ("sockeye", "SOCKEYE", "362nd_Sockeye", "Sockeye "):
            with self.subTest(name):
                self.assertEqual(
                    identity.unit_for_radio(name, self.units).name, "362nd_sockeye")

    def test_a_radio_nobody_is_flying_resolves_to_nothing(self):
        self.assertIsNone(identity.unit_for_radio("Bandit", self.units))

    def test_a_name_too_short_is_not_evidence(self):
        """Two characters would match half the mission."""
        self.assertIsNone(identity.unit_for_radio("So", self.units))

    def test_ambiguity_is_refused_rather_than_tie_broken(self):
        """Picking the first is how a controller vectors somebody's wingman."""
        us = identity.units_on(
            "Viper 1 (F-16C_50): 1 nm on the 090 radial, 100 ft, heading 010 | "
            "Viper 11 (F-16C_50): 2 nm on the 090 radial, 100 ft, heading 010")
        self.assertIsNone(identity.unit_for_radio("Viper1", us))


class TestTheLadder(unittest.TestCase):
    def setUp(self):
        self.reg = identity.Registry()

    def test_radar_via_the_radio_beats_everything(self):
        i = self.reg.resolve("guid-a", "Sockeye", spoken="Pony 1-1", scope=SCOPE)
        self.assertEqual(i.authority, "radar")
        self.assertEqual(i.track, "362nd_sockeye")

    def test_a_garbled_callsign_cannot_move_the_identity(self):
        """THE POINT OF THE WHOLE MODULE. Whisper wrote "Tony 1-1" for a man
        saying Pony 1-1 seven times in one recording. The aeroplane he is
        sitting in does not change because of it."""
        i = self.reg.resolve("guid-a", "Sockeye", spoken="Tony 1-1", scope=SCOPE)
        self.assertEqual(i.track, "362nd_sockeye")
        self.assertEqual(i.authority, "radar")

    def test_a_claim_matching_nothing_is_not_an_aeroplane(self):
        """The rung that does not exist, and whose absence is the fix. "You 4",
        out of "with you 4,100 level", is well-formed and matches nothing."""
        i = self.reg.resolve("guid-z", "Nobody", spoken="You 4", scope=SCOPE)
        self.assertFalse(i)
        self.assertEqual(i.authority, "")
        self.assertIn("no track", i.why)

    def test_a_filed_plan_is_an_authority(self):
        """A procedural controller has no radar and is still not working
        voices -- he is working strips, typed before the sortie."""
        i = self.reg.resolve("guid-b", "Bandit", spoken="Colt 2-1",
                             scope=SCOPE, plans=["Colt 2-1", "Uzi 1-1"])
        self.assertEqual(i.authority, "plan")
        self.assertEqual(i.callsign, "Colt 2-1")

    def test_a_plan_is_matched_not_believed(self):
        i = self.reg.resolve("guid-b", "Bandit", spoken="Maintained 2",
                             scope=SCOPE, plans=["Colt 2-1"])
        self.assertFalse(i)

    def test_the_roster_is_the_weakest_rung(self):
        i = self.reg.resolve("guid-c", "Ranger", spoken="Hoover 1-1",
                             scope=SCOPE, roster=["Hoover 1-1"])
        self.assertEqual(i.authority, "roster")

    def test_spelling_of_a_claim_does_not_have_to_match_exactly(self):
        """"Pony 11" and "Pony 1-1" are the same aeroplane; a hyphen is a
        convention of ours, not something a pilot pronounces."""
        i = self.reg.resolve("guid-b", "Bandit", spoken="Pony 11",
                             scope=SCOPE, plans=["Pony 1-1"])
        self.assertEqual(i.callsign, "Pony 1-1")


class TestIdentityPersists(unittest.TestCase):
    def test_a_resolved_radio_survives_a_clipped_call(self):
        """He does not stop being in that aeroplane because a gust ate a word.
        Re-deriving identity from every garbled transmission is the behaviour
        being replaced."""
        reg = identity.Registry()
        reg.resolve("guid-a", "Sockeye", spoken="Pony 1-1", scope=SCOPE)
        i = reg.resolve("guid-a", "Sockeye", spoken="", scope="no contacts")
        self.assertEqual(i.track, "362nd_sockeye")
        self.assertEqual(i.callsign, "Pony 1-1")

    def test_a_weak_resolution_does_not_persist(self):
        """A roster match was somebody else's authority, borrowed. It is not
        good enough to keep answering with once the evidence has gone."""
        reg = identity.Registry()
        reg.resolve("g", "Ranger", spoken="Hoover 1-1", roster=["Hoover 1-1"])
        self.assertFalse(reg.resolve("g", "Ranger", spoken="", scope=""))

    def test_a_pilot_can_change_slots_without_an_engineer(self):
        """#38: a callsign is a position, not a person, and a man flies several
        in a night. Needing an engineer to reset that is a design smell the
        pilot named himself."""
        reg = identity.Registry()
        reg.resolve("guid-a", "Sockeye", spoken="Pony 1-1", scope=SCOPE)
        reg.forget("guid-a")
        self.assertFalse(reg.resolve("guid-a", "Sockeye", spoken="", scope=""))

    def test_one_garble_does_not_rename_a_pilot(self):
        """A label changes only on corroboration.

        The asymmetry the design rests on is that a wrong label is rude and a
        wrong track is dangerous -- but rude is not free either. Replaying the
        recordings found a pilot relabelled "Talking 4" and another "Hammer
        1-0" off one bad transmission each, while the physical chain had their
        aeroplanes right the whole time. Real callsigns repeat; noise does not.
        """
        reg = identity.Registry()
        a = reg.resolve("guid-a", "Sockeye", spoken="Pony 1-1", scope=SCOPE)
        b = reg.resolve("guid-a", "Sockeye", spoken="Tony 1-1", scope=SCOPE)
        self.assertEqual(b.callsign, a.callsign)
        self.assertEqual(b.track, a.track)

    def test_he_may_still_rename_himself_with_corroboration(self):
        """Protecting the label must not freeze it: a pilot who takes a new
        callsign -- a different sortie, a different position in the flight --
        has to be able to say so. What he cannot do is be renamed by noise."""
        reg = identity.Registry()
        reg.resolve("guid-a", "Sockeye", spoken="Pony 1-1", scope=SCOPE)
        i = reg.resolve("guid-a", "Sockeye", spoken="Colt 2-1", scope=SCOPE,
                        plans=["Colt 2-1"])
        self.assertEqual(i.callsign, "Colt 2-1")
        self.assertEqual(i.track, "362nd_sockeye")

    def test_every_answer_says_why(self):
        reg = identity.Registry()
        for kw in (dict(spoken="Pony 1-1", scope=SCOPE),
                   dict(spoken="You 4", scope=SCOPE)):
            self.assertTrue(reg.resolve("g", "Sockeye", **kw).why)


if __name__ == "__main__":
    unittest.main()
