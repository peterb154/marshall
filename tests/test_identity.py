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

    VIPERS = ("Viper 1 (F-16C_50): 1 nm on the 090 radial, 100 ft, heading 010 | "
              "Viper 11 (F-16C_50): 2 nm on the 090 radial, 100 ft, heading 010")

    def test_ambiguity_is_refused_rather_than_tie_broken(self):
        """Picking the first is how a controller vectors somebody's wingman.

        A radio calling itself "Viper" against Viper 1 and Viper 11 matches
        both by substring and neither exactly, which is a genuine choice and so
        gets no answer.
        """
        self.assertIsNone(
            identity.unit_for_radio("Viper", identity.units_on(self.VIPERS)))

    def test_an_exact_match_is_not_ambiguous_even_among_lookalikes(self):
        """This used to refuse, and refusing was wrong.

        "Viper1" normalises to exactly one of those two units. Substring
        matching could not see that and threw the answer away -- which is the
        same flaw that would have refused BOTH of two squadron mates called
        Hoover and Hoover2.
        """
        got = identity.unit_for_radio("Viper1", identity.units_on(self.VIPERS))
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "Viper 1")


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

    def test_a_pilot_may_rename_himself(self):
        """THE OUTAGE, 28 July, and it cost an entire approach.

        He checked in as Pony 1-1, changed to Falcon 1-1 and said so a dozen
        times. A rule here refused any rename no filed strip agreed with, so he
        stayed Pony 1-1 forever. Radar had tagged his track "Falcon one one";
        the engine went looking for "Pony 1-1", found nobody, and told him he
        was not radar identified for the whole approach -- while the agent
        cheerfully vectored Falcon 1-1. Two brains, two different aeroplanes.
        """
        reg = identity.Registry()
        reg.resolve("guid-a", "Sockeye", spoken="Pony 1-1", scope=SCOPE)
        i = reg.resolve("guid-a", "Sockeye", spoken="Falcon 1-1", scope=SCOPE)
        self.assertEqual(i.callsign, "Falcon 1-1")
        self.assertEqual(i.track, "362nd_sockeye")

    def test_a_wordless_call_does_not_blank_him(self):
        """What the guard was really for. A clipped or callsign-less
        transmission keeps the name he has been going by."""
        reg = identity.Registry()
        reg.resolve("guid-a", "Sockeye", spoken="Falcon 1-1", scope=SCOPE)
        self.assertEqual(
            reg.resolve("guid-a", "Sockeye", spoken="", scope=SCOPE).callsign,
            "Falcon 1-1")

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


class TestAGuestNeedsNothingSetUpInAdvance(unittest.TestCase):
    """"Andre should work without setting anything up in advance."

    His radio is one we have never heard, and his SRS handle may look nothing
    like his DCS player name, so the name-matching chain does not close. Asking
    somebody to file him a strip first is precisely the setup being removed.

    The sim still says how many PEOPLE are flying. One unaccounted human and
    one unidentified radio is not a choice -- it is elimination, the same
    reasoning a controller uses when one aeroplane answers on a quiet
    frequency.
    """

    ONE = ("Nobody-We-Know (F-16C_50, manned): 12.0 nm on the 300 radial, "
           "8,000 ft, heading 130")
    TWO = (ONE + " | Sockeye (P-51D-30-NA, manned): 4.1 nm on the 281 radial, "
           "4,000 ft, heading 026")
    WITH_AI = (ONE + " | Enfield11 (Su-25T): 20.0 nm on the 010 radial, "
               "15,000 ft, heading 200")

    def test_the_scope_says_who_has_a_person_in_it(self):
        us = {u.name: u for u in identity.units_on(self.WITH_AI)}
        self.assertTrue(us["Nobody-We-Know"].manned)
        self.assertFalse(us["Enfield11"].manned)
        self.assertEqual(us["Nobody-We-Know"].type, "F-16C_50")   # marker stripped

    def test_a_stranger_alone_is_identified(self):
        reg = identity.Registry()
        i = reg.resolve("guid-guest", "AndreSomething", spoken="Falcon 2-1",
                        scope=self.ONE)
        self.assertEqual(i.track, "Nobody-We-Know")
        self.assertEqual(i.callsign, "Falcon 2-1")

    def test_an_ai_is_never_the_one_talking(self):
        """A machine that never asked for a clearance must not be handed one."""
        reg = identity.Registry()
        i = reg.resolve("guid-guest", "AndreSomething", spoken="Falcon 2-1",
                        scope=self.WITH_AI)
        self.assertEqual(i.track, "Nobody-We-Know")

    def test_a_stranger_beside_a_known_pilot_is_still_identified(self):
        """The realistic case: one regular whose names match, one guest whose
        names do not. The regular is claimed by name, so the guest is the only
        person left."""
        reg = identity.Registry()
        reg.resolve("guid-hoover", "Sockeye", spoken="Pony 1-1", scope=self.TWO)
        i = reg.resolve("guid-guest", "AndreSomething", spoken="Falcon 2-1",
                        scope=self.TWO)
        self.assertEqual(i.track, "Nobody-We-Know")

    def test_two_strangers_at_once_is_refused_rather_than_guessed(self):
        """It stops being elimination the moment it becomes a choice, and the
        correct answer then is to ask."""
        scope = self.TWO.replace("Sockeye", "Someone-Else")
        reg = identity.Registry()
        i = reg.resolve("guid-a", "UnknownA", spoken="Falcon 2-1", scope=scope)
        self.assertFalse(i)

    def test_it_does_not_steal_a_track_already_resolved(self):
        reg = identity.Registry()
        a = reg.resolve("guid-a", "Nobody-We-Know", spoken="Falcon 2-1",
                        scope=self.ONE)
        b = reg.resolve("guid-b", "SomebodyElse", spoken="Falcon 2-2",
                        scope=self.ONE)
        self.assertEqual(a.track, "Nobody-We-Know")
        self.assertFalse(b)


class TestOverlappingPilotNames(unittest.TestCase):
    """Two squadron mates with similar handles, which is not exotic.

        "How do you change your SRS name independent of DCS? I think it comes
         right out of DCS exports?"

    He is right, and it changes what the matching rule should be. With DCS
    running the SRS client takes its name from the DCS export, so the radio's
    name and the name radar prints are the SAME STRING -- an exact match is the
    normal case, and substring matching is only needed where decoration differs
    ("Sockeye" against "362nd_sockeye").

    Trying substrings FIRST does not merely loosen it, it fails outright: with
    "Hoover" and "Hoover2" both flying, each radio matches both units, the
    ambiguity rule refuses, and NEITHER pilot is identified. It takes out the
    man whose name is a prefix as well as the one whose name contains it.
    """

    OVERLAP = [identity.Unit("Hoover", manned=True),
               identity.Unit("Hoover2", manned=True)]

    def test_both_pilots_are_identified_despite_the_overlap(self):
        self.assertEqual(identity.unit_for_radio("Hoover", self.OVERLAP).name,
                         "Hoover")
        self.assertEqual(identity.unit_for_radio("Hoover2", self.OVERLAP).name,
                         "Hoover2")

    def test_decoration_still_matches_where_there_is_no_exact_hit(self):
        """The fallback has to survive: DCS and SRS decorate differently when
        the player name carries a squadron tag."""
        units = [identity.Unit("362nd_sockeye", manned=True)]
        self.assertEqual(identity.unit_for_radio("Sockeye", units).name,
                         "362nd_sockeye")

    def test_an_exact_match_beats_a_longer_substring_hit(self):
        units = [identity.Unit("Andre", manned=True),
                 identity.Unit("AndreTheGiant", manned=True)]
        self.assertEqual(identity.unit_for_radio("Andre", units).name, "Andre")

    def test_two_units_with_one_name_is_still_refused(self):
        """units_on should have made these distinct; if it did not, refusing is
        the correct answer and not a tie-break."""
        same = [identity.Unit("Hoover", manned=True),
                identity.Unit("Hoover", manned=True)]
        self.assertIsNone(identity.unit_for_radio("Hoover", same))


class TestGarbleProtectionLivesInTheVote(unittest.TestCase):
    """Where the protection belongs, and where it does NOT.

    `identity._label` takes what the pilot says, because `spoken` reaches it
    already voted across the sortie by `transmitter_callsign` -- count weighed
    against recency, so real callsigns repeat and noise does not.

    A SECOND layer of protection inside the registry was an outage: it refused
    a legitimate rename and left the engine hunting an aeroplane that no longer
    answered to that name. The evidence for it came from replaying the RAW
    extractor one transmission at a time, with no vote in front of it -- a fix
    for a problem the live path did not have.

    So these test the vote, which is the thing that actually has to be right.
    """

    def setUp(self):
        from marshall.atc import agent_atc as A
        A._transmitters.clear()
        A._order.clear()
        self.A = A

    def test_one_garble_does_not_outvote_an_established_name(self):
        for _ in range(4):
            self.A.transmitter_callsign("g", "Falcon one one, level four thousand")
        got = self.A.transmitter_callsign("g", "Talcon one one, say again")
        self.assertEqual(got, "Falcon 1-1")

    def test_a_repeated_rename_does_win(self):
        """Said once it is probably noise; said again it is a decision. This is
        exactly the case the registry was overriding."""
        self.A.transmitter_callsign("g", "Pony one one, radio check")
        for _ in range(3):
            self.A.transmitter_callsign("g", "Falcon one one, with you level")
        self.assertEqual(
            self.A.transmitter_callsign("g", "Falcon one one, request approach"),
            "Falcon 1-1")


class TestAManUnderVectorsIsNotLeaving(unittest.TestCase):
    """Eight offers to Georgia Center in one approach.

        "when flying around the IF area, several times he tried to hand me off
         to georgia center -- i never went.. have a feeling this is a separate
         thread than the one flying the approach"

    Right about the shape: a different decision path from the one flying the
    approach, and the two disagreed. Approach control was vectoring him
    downwind at eleven to eighteen miles -- taking him outbound ON PURPOSE --
    while the airspace path saw an aeroplane heading away and offered him on.

    Being taken outbound by MY OWN vectors is the opposite of leaving, and no
    range test can tell the two apart because the geometry is identical.
    """

    class _Me:
        role = "approach"

    def test_no_handoff_while_we_are_vectoring_him(self):
        from marshall.atc import agent_atc as A
        self.assertIsNone(
            A.leaving_my_airspace("http://unused", "s", "Falcon 1-1",
                                  self._Me(), None, None,
                                  under_our_vectors=True))


class TestTheHandleIsWhoHeAlreadyIs(unittest.TestCase):
    """The pre-existing identity a formation split falls back to.

        "Let's use the srs/dcs suffix -- the chunk after a space, dash or
         underscore. Look at shooter, Andre and sockeye. All have unique names
         already."

    Real formation procedure says each aeroplane reverts to THE CALLSIGN IT
    ALREADY HAD when the flight breaks up -- the one assigned before the
    sortie, at the duty desk. We had no such thing, so a split had nothing to
    fall back to: the lead was refused for want of a radar track, and the
    wingman's radio took the FLIGHT's name.

    Every pilot already has that identity in his player name. It is unique, it
    is never spoken, and it survives a slot change, a callsign change and a
    mis-transcription.
    """

    REAL = [("362nd_sockeye", "sockeye"), ("362nd Andre", "Andre"),
            ("362nd Shooter", "Shooter"), ("362nd-Viper", "Viper")]

    def test_the_squadron_tag_comes_off(self):
        for full, want in self.REAL:
            with self.subTest(full):
                self.assertEqual(identity.handle(full), want)

    def test_a_slot_number_comes_off_too(self):
        """The rule is "drop any chunk with a digit", not "take what follows
        the first separator" -- which is the only version that survives this
        one, since the obvious rule turns it into "1-1-1"."""
        self.assertEqual(identity.handle("Hoover 1-1-1"), "Hoover")

    def test_a_bare_name_is_left_alone(self):
        self.assertEqual(identity.handle("sockeye"), "sockeye")

    def test_a_name_that_is_all_digits_survives(self):
        """Stripping everything would leave nobody, and a pilot calling himself
        Viper2 is still somebody."""
        self.assertEqual(identity.handle("Viper2"), "Viper2")

    def test_two_humans_are_never_confused(self):
        us = [identity.Unit(f, manned=True) for f, _ in self.REAL]
        for full, short in self.REAL:
            with self.subTest(short):
                self.assertEqual(identity.unit_for_radio(short, us).name, full)
                self.assertEqual(identity.unit_for_radio(full, us).name, full)

    def test_similar_handles_stay_distinct(self):
        """The handle must not undo the exact-match fix: Hoover and Hoover2 are
        two squadron mates, not one."""
        us = [identity.Unit("Hoover", manned=True),
              identity.Unit("Hoover2", manned=True)]
        self.assertEqual(identity.unit_for_radio("Hoover", us).name, "Hoover")
        self.assertEqual(identity.unit_for_radio("Hoover2", us).name, "Hoover2")

    def test_it_survives_what_the_radio_calls_him(self):
        """The whole point: the handle is the same whatever callsign he claims,
        so a split has something true to fall back to."""
        scope = ("362nd Andre [Falcon 1] (F-16C_50, manned): 9.0 nm on the 300 "
                 "radial, 9,000 ft, heading 130, 300 knots")
        reg = identity.Registry()
        for claimed in ("Falcon 1", "Falcon 1-2", "Falcon 1-1", ""):
            with self.subTest(claimed or "(nothing)"):
                got = reg.resolve("g", "Andre", spoken=claimed, scope=scope)
                self.assertEqual(identity.handle(got.track), "Andre")


class TestHowAControllerAddressesASingle(unittest.TestCase):
    """"Sockeye is sockeye as a single. No matter what I'm flying. Always
    sockeye -- unless I'm flight lead, then the flight has a name."

    A person is his handle, so the last resort when nothing has named him is
    the handle and not the sim's unit name. Heard in the flight rehearsal: the
    controller addressed a man as "362nd_Andre-1", which the voice read out as
    "3-6-2 and DeAndre-1" -- a squadron tag and a slot number on the air, and
    neither is a thing anybody has ever said on a radio.
    """

    UNTAGGED = ("362nd_Andre-1 (P-51D-30-NA, manned): 13.6 nm on the 307 "
                "radial, 5,950 ft, heading 062, 280 knots")

    def test_he_is_called_by_his_handle(self):
        r = identity.Registry()
        got = r.resolve("guid-andre", "Andre", spoken="", scope=self.UNTAGGED)
        self.assertEqual(got.callsign, "Andre")
        self.assertEqual(got.track, "362nd_Andre-1")

    def test_the_track_is_still_the_sim_unit(self):
        """The label changed; the thing that gets separated did not."""
        r = identity.Registry()
        got = r.resolve("guid-andre", "Andre", spoken="", scope=self.UNTAGGED)
        self.assertEqual(got.authority, "radar")
        self.assertNotEqual(got.callsign, got.track)

    def test_a_tagged_contact_keeps_the_callsign_radar_gave_it(self):
        """The handle is the FALLBACK. Anything that has actually named him
        outranks it."""
        scope = ("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 4.1 nm on "
                 "the 281 radial, 4,659 ft, heading 026")
        r = identity.Registry()
        got = r.resolve("guid-s", "sockeye", spoken="", scope=scope)
        self.assertEqual(got.callsign, "Pony 1-1")
