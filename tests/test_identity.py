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


class TestBorrowedAuthorityCannotBeSelfMade(unittest.TestCase):
    """The weakest rung, and the hole it would open if fed the wrong list.

    Rung 3 recognises a pilot because the name he claims is already on the
    board. Handed the raw `Controller.aircraft` dict, a ghost would corroborate
    ITSELF -- mis-heard once it takes a slot, and every repeat of the same
    mis-hearing then matches an entry and is believed. A wrong name that grows
    more convincing each time it is said is precisely what is being designed
    out, so only aircraft radar has actually seen may vouch for anybody.
    """

    def _controller(self):
        from marshall.atc.controller import Controller
        from marshall.core import route as R
        return Controller(R.BATUMI_ASR)

    def test_only_radar_identified_aircraft_may_vouch(self):
        ctl = self._controller()
        ctl.get("Pony 1-1")
        ctl.note_radar_contact("Pony 1-1")
        ctl.get("Maintained 2")                 # a ghost that got in
        self.assertEqual(ctl.identified(), ["Pony 1-1"])

    def test_a_ghost_cannot_confirm_itself_on_the_second_hearing(self):
        ctl = self._controller()
        ctl.get("Maintained 2")
        reg = identity.Registry()
        again = reg.resolve("g", "nobody", spoken="Maintained 2",
                            roster=ctl.identified())
        self.assertFalse(again)

    def test_a_real_aeroplane_still_vouches(self):
        """The rung has to keep working, or a pilot radar has seen but whose
        radio we never matched would be refused for the rest of the sortie."""
        ctl = self._controller()
        ctl.get("Pony 1-1")
        ctl.note_radar_contact("Pony 1-1")
        reg = identity.Registry()
        self.assertEqual(
            reg.resolve("g", "nobody", spoken="Pony 1-1",
                        roster=ctl.identified()).authority, "roster")


class TestTheRealNamesThisProjectHasSeen(unittest.TestCase):
    """The physical link, checked against every pairing actually recorded.

    The chain only holds if the SRS client name and the name radar prints are
    the same human, and that is an empirical claim about two systems nobody
    coordinated -- so it is measured here rather than assumed.

    It holds because the radar line leads with `player_name or callsign or
    name`: for an occupied seat that is the PLAYER, not the slot. Which matters
    for the F-16 testbed, whose slot is called "Testbed 1-1" -- a name no
    pilot's radio will ever match. Flying it, he still appears under his own
    player name, and the chain closes anyway.
    """

    PAIRS = [
        ("Sockeye", "362nd_sockeye"),      # squadron tag, underscore, lower case
        ("Shooter", "362nd Shooter"),      # squadron tag, space
        ("Hoover", "Hoover 1-1-1"),        # slot suffix on the end
    ]

    def test_every_radio_finds_its_pilot(self):
        for srs, unit in self.PAIRS:
            with self.subTest(f"{srs} -> {unit}"):
                units = [identity.Unit(unit)]
                self.assertIsNotNone(identity.unit_for_radio(srs, units))

    def test_and_does_not_find_somebody_elses(self):
        """The same list is a negative test for free: three different humans,
        and no radio may match a unit that is not his."""
        units = [identity.Unit(u) for _s, u in self.PAIRS]
        for srs, unit in self.PAIRS:
            with self.subTest(srs):
                self.assertEqual(identity.unit_for_radio(srs, units).name, unit)

    def test_a_client_slot_name_is_not_what_a_pilot_matches_on(self):
        """The F-16 case stated outright. If radar ever started printing the
        slot instead of the player, identity for that aeroplane would silently
        fall back to the weaker rungs -- so this is the canary."""
        self.assertIsNone(
            identity.unit_for_radio("Sockeye", [identity.Unit("Testbed 1-1")]))


class TestTheStripIsTheOnlyPreSortieEvidence(unittest.TestCase):
    """Why rung 2 reads /flightplans and not /flights.

    `/flights` is the LIVE BOARD -- rows created BY the binding this rung is
    meant to corroborate. Believing it is circular in exactly the way that made
    the naive radar check useless: an aeroplane cannot vouch for the process
    that invented it. Wiring it that way was a real defect in the first cut of
    this work and it would have been invisible in testing, because with one
    pilot flying every day the board is always right.

    A flight plan is typed by a human at a keyboard before the sortie. It is
    the only identity evidence in the system that exists before anybody keys a
    microphone -- which is what makes it the right authority for a FIRST
    transmission, when radar has correlated nobody and there is nothing else.
    """

    def test_a_visitor_on_an_unknown_radio_resolves_on_his_first_call(self):
        """The case that decides whether a guest's first impression works.

        His radio is one we have never heard, his DCS player name may be
        nothing like it, and radar has not tagged him because nothing has
        correlated him yet. A filed strip is all there is, and it is enough.
        """
        reg = identity.Registry()
        i = reg.resolve("guid-visitor", "a-name-we-do-not-know",
                        spoken="Pony 1-2", scope="no contacts",
                        plans=["Pony 1-1", "Pony 1-2"])
        self.assertEqual(i.callsign, "Pony 1-2")
        self.assertEqual(i.authority, "plan")

    def test_with_no_strip_on_file_he_is_refused(self):
        """Stated so the mitigation is obvious rather than folklore: if a
        visitor is not on file, he does not get identified off his own say-so.
        File the strip before he flies -- which is what a real controller has
        in front of him anyway."""
        reg = identity.Registry()
        self.assertFalse(reg.resolve("guid-visitor", "unknown",
                                     spoken="Pony 1-2", scope="no contacts",
                                     plans=["Pony 1-1"]))

    def test_a_strip_does_not_outrank_radar(self):
        """Filing a plan must not become a way to be believed over the sim: if
        the radio is physically in an aeroplane, that wins."""
        reg = identity.Registry()
        i = reg.resolve("g", "Sockeye", spoken="Pony 1-1", scope=SCOPE,
                        plans=["Pony 1-1"])
        self.assertEqual(i.authority, "radar")
