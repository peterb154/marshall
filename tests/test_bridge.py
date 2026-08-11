"""The SRS bridge's text handling -- what actually reaches Polly.

No network: these are the pure functions between the agent's reply and the
radio. They exist because both failures below were found on the air, in the
controller's voice, mid-sortie.
"""

import pathlib
import shutil
import tempfile
import time
import os
import unittest

from marshall.atc import agent_atc

from marshall.atc import callsign as C

# One store per test module -- see agent_atc.Bridge. These used to be
# module globals and every case had to remember to clear them.
_BRIDGE = agent_atc.Bridge()


class TestForVoice(unittest.TestCase):
    def test_reasoning_above_the_marker_is_not_transmitted(self):
        # Seen live: with extended thinking disabled the model reasons in the
        # OUTPUT, and every word of it was spoken to the pilot.
        reply = ("This is a different transmitter, a wingman, reporting his "
                 "level. He's holding, not yet identified individually.\n"
                 "RADIO: Pony one two, roger, level four thousand.")
        self.assertEqual(agent_atc.for_voice(reply),
                         "Pony one two, roger, level four thousand.")

    def test_marker_alone(self):
        self.assertEqual(agent_atc.for_voice("RADIO: Pony one flight, roger."),
                         "Pony one flight, roger.")

    def test_last_marker_wins(self):
        self.assertEqual(agent_atc.for_voice("a RADIO: b RADIO: c"), "c")

    def test_reply_without_a_marker_is_still_spoken(self):
        # The marker is a safety net, not a requirement -- a model that forgets
        # it must not produce silence on the frequency.
        self.assertEqual(agent_atc.for_voice("Pony one one, cleared approach."),
                         "Pony one one, cleared approach.")

    def test_markdown_is_stripped(self):
        self.assertEqual(
            agent_atc.for_voice("**Pony one one**, `cleared` approach."),
            "Pony one one, cleared approach.")

    def test_newlines_collapse_to_one_line(self):
        self.assertEqual(agent_atc.for_voice("Pony one one,\ncleared\napproach."),
                         "Pony one one, cleared approach.")

    def test_bullets_are_stripped(self):
        self.assertEqual(agent_atc.for_voice("- Pony one one, cleared approach."),
                         "Pony one one, cleared approach.")


class TestCountContacts(unittest.TestCase):
    """The bridge engages the separation engine on contact count, so this
    decides whether a formation gets deterministic sequencing at all."""

    def test_empty_sky(self):
        self.assertEqual(agent_atc.count_contacts(""), 0)
        self.assertEqual(agent_atc.count_contacts("no contacts"), 0)

    def test_single(self):
        self.assertEqual(agent_atc.count_contacts(
            "Enfield11 (P-51D): 6.0 nm on the 332 radial, 4,000 ft, heading 151"), 1)

    def test_two_singles(self):
        self.assertEqual(agent_atc.count_contacts(
            "A (P-51): 6.0 nm on the 332 radial, 4,000 ft, heading 151 | "
            "B (P-51): 8.0 nm on the 300 radial, 5,000 ft, heading 120"), 2)

    def test_a_formation_counts_its_ships_not_its_line(self):
        # The regression this exists for: radar collapses a four-ship into ONE
        # line, so counting lines left the engine switched off for the arrival
        # that most needs sequencing.
        self.assertEqual(agent_atc.count_contacts(
            "Enfield11 (P-51D) IN FORMATION with Enfield12, Enfield13, Enfield14 "
            "— 4 ships, lead 12.3 nm on the 332 radial, 6,004 ft, heading 151"), 4)

    def test_formation_plus_a_single(self):
        self.assertEqual(agent_atc.count_contacts(
            "E11 (P-51D) IN FORMATION with E12 — 2 ships, lead 12.3 nm on the "
            "332 radial, 6,004 ft, heading 151 | "
            "Hawk (P-51D): 8.0 nm on the 300 radial, 5,000 ft, heading 120"), 3)


class TestGroundUnitsAreNotTraffic(unittest.TestCase):
    """Audit #45. Every mission has armour and ships in it, and they were
    counted, so `engaged` was true for a pilot alone in the sky -- which put the
    separation engine to work sequencing him against a tank and sent every
    transmission, radio checks included, through the intent classifier at 2.2
    seconds a turn.

    The category was never a mystery: the streamer subscribes per category and
    then discarded it. It is a column now, and it reaches the scope prose.
    """

    PILOT = ("362nd_sockeye (P-51D-30-NA, manned): 8.0 nm on the 281 radial, "
             "4,000 ft, heading 100, 180 knots")
    ARMOUR = (" | Samovar-1 (T-55, ground) IN FORMATION with "
              "Samovar-2 (T-55, ground, 0.0 nm), Samovar-3 (T-55, ground, 0.1 nm)"
              " — 3 ships, lead 70.1 nm on the 048 radial, 2,054 ft, heading 000")

    def test_a_lone_pilot_with_armour_on_the_map_is_still_alone(self):
        self.assertEqual(agent_atc.count_contacts(self.PILOT + self.ARMOUR), 1)

    def test_the_wingmen_of_a_ground_formation_are_ground_too(self):
        """The bug within the bug: only the LEAD carried the marker, so three
        tanks read as one ground unit and two aeroplanes."""
        self.assertEqual(agent_atc.count_contacts(self.ARMOUR[3:]), 0)

    def test_ships_are_not_traffic_either(self):
        self.assertEqual(agent_atc.count_contacts(
            self.PILOT + " | CVN-74 (Stennis, ship): 40.0 nm on the 270 radial, "
            "0 ft, heading 090, 20 knots"), 1)

    def test_aircraft_are_still_counted_alongside_them(self):
        self.assertEqual(agent_atc.count_contacts(
            self.PILOT + self.ARMOUR +
            " | 362nd_andre (F-16C_50, manned): 20.0 nm on the 090 radial, "
            "8,000 ft, heading 270, 300 knots"), 2)


class TestACallsignNobodyAnswersTo(unittest.TestCase):
    """He is corrected, and it is not conditional on our ignorance.

        "if a pilot says 'falcon 1-1, approach' and there is no falcon 1-1 ...
         atc should say - falcon 1-1 I dont have you on the board or similar --
         even if he KNOWS it's sockeye. Sockeye screwed up by using Falcon1-1 on
         the radio and needs to be corrected."

    Two states that used to be one. The radio says this is Sockeye and nothing
    about that is in doubt; what is wrong is the name he put on the air.
    Absorbing it silently teaches him it works -- untidy with one pilot up, and
    with four it is how a clearance gets read back by the wrong man, because
    everybody on the frequency heard a callsign belonging to nobody and each of
    them had to guess who it meant.
    """

    def setUp(self):
        from marshall.atc import controller as atc
        from marshall.core import route as R
        self.b = agent_atc.Bridge()
        self.ctl = atc.Controller(R.BATUMI_ASR)

    def said(self, claim, known="sockeye", who="sockeye"):
        return agent_atc.misnamed(self.b, self.ctl, claim, known, who)

    def test_a_name_nobody_answers_to_is_corrected(self):
        got = self.said("Falcon 1-1")
        self.assertIn("Falcon one one", got)
        self.assertIn("do not have you on the board", got)

    def test_it_tells_him_what_to_use_instead(self):
        """A correction he cannot act on is just a complaint."""
        self.assertIn("Sockeye", self.said("Falcon 1-1"))

    def test_his_own_handle_is_not_corrected(self):
        self.assertEqual(self.said("Sockeye"), "")

    def test_a_position_name_is_corrected_like_any_other_invention(self):
        """"Pony 1-1" is a slot in a formation and eye candy for pilot-to-pilot
        chat. It names nobody the controller is working."""
        self.assertIn("do not have you", self.said("Pony 1-1"))

    def test_a_flight_name_is_fine_ONCE_THE_FLIGHT_EXISTS(self):
        self.assertIn("do not have you", self.said("Apex", known="sockeye"))
        self.b.flights.create("Apex", "sockeye")
        self.assertEqual(self.said("Apex", known="Apex"), "")

    def test_a_member_designation_is_still_corrected(self):
        self.b.flights.create("Apex", "sockeye")
        self.assertIn("Apex one two", self.said("Apex 1-2", known="Apex"))

    def test_addressing_somebody_actually_on_the_board_is_not_a_correction(self):
        """Calling another pilot by name is ordinary radio, not a claim about
        who you are."""
        self.ctl.check_in("Andre", 1)
        self.assertEqual(self.said("Andre"), "")

    def test_saying_nothing_is_not_a_correction(self):
        self.assertEqual(self.said(""), "")

    def test_with_no_name_for_him_it_only_asks(self):
        """Nothing to offer him, so it does not invent one."""
        got = self.said("Falcon 1-1", known="", who="")
        self.assertIn("Say your callsign", got)
        self.assertNotIn("use that callsign", got)


class TestRoster(unittest.TestCase):
    """The SRS name lookup, which is the free identity anchor on every packet."""

    def roster_of(self, *lines):
        from marshall.radio.client import SRSClient
        c = SRSClient.__new__(SRSClient)
        c.roster = {}
        for line in lines:
            c._harvest_roster(line)
        return c.roster

    def test_full_client_list(self):
        self.assertEqual(
            self.roster_of(b'{"MsgType":2,"Clients":['
                           b'{"ClientGuid":"aaa","Name":"Sockeye"},'
                           b'{"ClientGuid":"bbb","Name":"Bandit"}]}'),
            {"aaa": "Sockeye", "bbb": "Bandit"})

    def test_single_client_update(self):
        # How a late-joining wingman becomes known to an already-connected bridge.
        self.assertEqual(
            self.roster_of(b'{"MsgType":3,"Client":{"ClientGuid":"ccc","Name":"Ranger"}}'),
            {"ccc": "Ranger"})

    def test_malformed_messages_are_survivable(self):
        # A live sortie logged two wingmen as raw GUID stubs because this thread
        # had died on an earlier line -- silently, while everything else kept
        # working. Nothing here may raise.
        for bad in (b"null", b"[]", b"not json", b'{"Clients":"nope"}',
                    b'{"Client":5}', b"", b'{"Clients":[1,2]}'):
            with self.subTest(bad=bad):
                self.assertEqual(self.roster_of(bad), {})

    def test_a_bad_message_does_not_lose_a_good_one(self):
        self.assertEqual(
            self.roster_of(b"not json",
                           b'{"MsgType":3,"Client":{"ClientGuid":"ddd","Name":"Hawk"}}'),
            {"ddd": "Hawk"})


class TestSimpleResponse(unittest.TestCase):
    def test_radio_check_is_answered_without_the_agent(self):
        out = agent_atc.simple_response("Batumi Approach, Pony one one, radio check")
        self.assertIsNotNone(out)
        self.assertIn("loud and clear", out.lower())

    def test_substance_goes_to_the_agent(self):
        self.assertIsNone(
            agent_atc.simple_response("Pony one one, over the beacon, four thousand"))

class TestTransmitterIdentity(unittest.TestCase):
    """The radio is the anchor: its NAME is irrelevant, its stability is not."""

    def setUp(self):
        _BRIDGE.transmitters.clear()

    def test_learns_the_callsign_a_radio_uses(self):
        self.assertEqual(
            agent_atc.transmitter_callsign(_BRIDGE, "g1", "Batumi Approach, Pony one one, "
                                           "flight of four, checking in."),
            "Pony 1-1")

    def test_remembers_it_when_the_callsign_is_missing(self):
        # The whole point: Whisper drops or mangles callsigns constantly, and
        # the controller should still know who is talking.
        agent_atc.transmitter_callsign(_BRIDGE, "g1", "Pony one one, checking in.")
        self.assertEqual(
            agent_atc.transmitter_callsign(_BRIDGE, "g1", "uhh, level four thousand"),
            "Pony 1-1")

    def test_a_numbered_phrase_does_not_steal_the_identity(self):
        # "level four thousand" must not rebind the radio to an aircraft called
        # "Level 4" -- a false positive silently reassigns a transmitter.
        agent_atc.transmitter_callsign(_BRIDGE, "g1", "Pony one one, checking in.")
        for noise in ("descending to four thousand",
                      "heading three zero four",
                      "runway one two in sight",
                      "passing five thousand"):
            with self.subTest(noise=noise):
                self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "g1", noise),
                                 "Pony 1-1")

    def test_a_radio_can_re_identify(self):
        agent_atc.transmitter_callsign(_BRIDGE, "g1", "Pony one one, checking in.")
        self.assertEqual(
            agent_atc.transmitter_callsign(_BRIDGE, "g1", "Pony one two, level five thousand"),
            "Pony 1-2")

    def test_radios_are_kept_apart(self):
        agent_atc.transmitter_callsign(_BRIDGE, "g1", "Pony one one, checking in.")
        agent_atc.transmitter_callsign(_BRIDGE, "g2", "Pony one three, level five thousand.")
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "g1", "say again"), "Pony 1-1")
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "g2", "say again"), "Pony 1-3")

    def test_an_unheard_radio_is_honestly_unknown(self):
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "g9", "mumble"), "")

    def test_no_guid_is_harmless(self):
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, None, "Pony one one"), "")


class TestRadarRange(unittest.TestCase):
    SCOPE = ("Enfield11 [Pony one flight] (P-51D) IN FORMATION with Enfield12 "
             "— 2 ships, lead 8.2 nm on the 332 radial, 6,004 ft, heading 151 | "
             "Hawk9 [Hawk one] (P-51D): 2.0 nm on the 300 radial, 4,000 ft, "
             "heading 120 | Bogey (P-51D): 0.3 nm on the 010 radial, 4,000 ft, "
             "heading 090")

    def test_reads_the_range_of_a_tagged_track(self):
        self.assertEqual(agent_atc.radar_range_for(self.SCOPE, "Pony 1-1"), 8.2)
        self.assertEqual(agent_atc.radar_range_for(self.SCOPE, "Hawk 1"), 2.0)

    def test_a_wingman_resolves_to_his_flights_track(self):
        self.assertEqual(agent_atc.radar_range_for(self.SCOPE, "Pony 1-3"), 8.2)

    def test_untagged_contacts_are_ignored(self):
        # An unidentified blip over the beacon proves nothing about who is
        # talking; guessing is how a truthful report gets rejected.
        self.assertIsNone(agent_atc.radar_range_for(self.SCOPE, "Bogey"))

    def test_unknown_callsign(self):
        self.assertIsNone(agent_atc.radar_range_for(self.SCOPE, "Nobody 1"))

    def test_no_radar_is_not_an_opinion(self):
        self.assertIsNone(agent_atc.radar_range_for("", "Pony 1-1"))
        self.assertIsNone(agent_atc.radar_range_for("no contacts", "Pony 1-1"))
        self.assertIsNone(agent_atc.radar_range_for(self.SCOPE, ""))


class TestPositionRejection(unittest.TestCase):
    """The blind engine believes position reports. The bridge must not let it
    act on one the scope flatly contradicts."""

    def setUp(self):
        from marshall.atc import bedrock_intent, controller as atc, intents
        from marshall.core import route as R
        self.intents, self.bedrock = intents, bedrock_intent
        self.ctl = atc.Controller(R.BATUMI_APPROACH)
        self._real = bedrock_intent.classify

    def tearDown(self):
        self.bedrock.classify = self._real

    def fake(self, kind, cs, **kw):
        self.bedrock.classify = lambda _t: self.intents.Intent(kind, cs, **kw)

    def scope(self, nm):
        return (f"E11 [Pony one flight] (P-51D): {nm} nm on the 332 radial, "
                f"6,004 ft, heading 151")

    def test_a_beacon_report_from_eight_miles_is_rejected(self):
        self.fake(self.intents.IntentKind.REPORT_BEACON, "Pony 1-1")
        directive, _ = agent_atc.separation_context(_BRIDGE,
            self.ctl, "over the beacon", self.scope(8.2))
        self.assertIn("POSITION REJECTED", directive)
        # And crucially the engine never saw it.
        self.assertEqual(self.ctl.aircraft, {})

    def test_a_beacon_report_from_overhead_is_accepted(self):
        self.fake(self.intents.IntentKind.REPORT_BEACON, "Pony 1-1")
        directive, _ = agent_atc.separation_context(_BRIDGE,
            self.ctl, "over the beacon", self.scope(1.2))
        self.assertNotIn("POSITION REJECTED", directive)
        # UNDER THE AEROPLANE RADAR SEES, not under the name the classifier
        # heard. The scope line is unit "E11" wearing the tag "Pony one
        # flight"; the engine holds "E 1-1", which is that unit's own name.
        # Since 30 July nothing a microphone produced may key the engine, and
        # the bracketed tag counts as microphone output -- it is only there
        # because an earlier call was correlated into it.
        self.assertIn("E 1-1", self.ctl.aircraft)
        self.assertNotIn("Pony 1-1", self.ctl.aircraft)

    def test_without_radar_the_report_is_believed(self):
        # No scope, or an unidentified aircraft: the blind procedure is all we
        # have, and refusing every report would ground the whole approach.
        self.fake(self.intents.IntentKind.REPORT_BEACON, "Pony 1-1")
        directive, _ = agent_atc.separation_context(_BRIDGE, self.ctl, "over the beacon", "")
        self.assertNotIn("POSITION REJECTED", directive)

    def test_other_intents_are_untouched_by_range(self):
        self.fake(self.intents.IntentKind.REPORT_MISSED, "Pony 1-1")
        directive, _ = agent_atc.separation_context(_BRIDGE,
            self.ctl, "going around", self.scope(8.2))
        self.assertNotIn("POSITION REJECTED", directive)


class TestAsrContext(unittest.TestCase):
    """Radar guidance for a vectored approach. Costs no model call, which is why
    it can run for a single ship -- the case that was previously flying with no
    deterministic picture at all."""

    def setUp(self):
        from marshall.core import route as R
        self.R = R
        self.asr = R.BATUMI_ASR
        self.ndb = R.BATUMI_APPROACH

    def scope(self, nm, radial=None, alt=2000, tag="Pony one one"):
        """A radar line. `radial` defaults to the inbound centreline.

        Derived from the profile rather than written as 304, because 304 was
        the reciprocal of a course that turned out to be six degrees off -- it
        was in the DCS grid frame while radials are true. Positions written as
        constants silently stop meaning what they were chosen to mean.
        """
        if radial is None:
            radial = (self.asr.final_crs_true + 180) % 360
        return (f"Enfield11 [{tag}] (P-51D-30-NA): {nm} nm on the {radial:.0f} "
                f"radial, {alt:,} ft, heading {self.asr.final_crs_true:.0f}")

    def test_parses_a_tagged_fix(self):
        pos = agent_atc.radar_fix(self.scope(6.4, 304, 2000), "Pony 1-1")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.range_nm, 6.4)
        self.assertAlmostEqual(pos.radial_deg, 304)
        self.assertEqual(pos.alt_ft, 2000)

    def test_untagged_contacts_give_no_guidance(self):
        # Guidance from a blip that might not be him is worse than none: it
        # sounds exactly as confident.
        bogey = "Bogey (P-51D): 6 nm on the 304 radial, 2,000 ft, heading 124"
        self.assertIsNone(agent_atc.radar_fix(bogey, "Pony 1-1"))
        self.assertEqual(agent_atc.asr_context(self.asr, bogey, "Pony 1-1"), "")

    def test_a_wingman_uses_his_flights_track(self):
        """Tagged with the FLIGHT, which is what a joined formation is.

        This used to pass with the scope tagged "Pony one one" -- the LEAD --
        because the lookup matched on flight number alone. That is
        indistinguishable from two pilots who merely share one, and it cost a
        sortie: Falcon 1-1 and Falcon 1-2 were each handed the other's
        position, so one was told "one mile from the runway" at thirty six
        miles while the other was told he was thirty eight miles out as he
        touched down.

        A member may share his FLIGHT's track. He may not share another
        member's. See tests/test_wingmen.py.
        """
        scope = self.scope(6).replace("Pony one one", "Pony one flight")
        pos = agent_atc.radar_fix(scope, "Pony 1-3")
        self.assertIsNotNone(pos)

    def test_silent_on_a_non_vectored_approach(self):
        # A beacon letdown must never receive vectors: the homing adapter points
        # the nose at the beacon, so a heading destroys his only reference.
        self.assertEqual(
            agent_atc.asr_context(self.ndb, self.scope(6), "Pony 1-1"), "")

    def test_far_out_is_vectoring(self):
        out = agent_atc.asr_context(self.asr, self.scope(14, 300), "Pony 1-1")
        self.assertIn("vectored", out)

    def test_the_agent_is_not_handed_the_turn_to_say(self):
        """CHANGED 11 August: it used to assert the ALTITUDE was in the block.

        The monitor issues the turns itself, on its own schedule, and this
        handed the same turn to the agent to say as well -- two transmissions of
        one instruction, and two separate computations of it. The monitor's came
        from its radar poll and this one from the fix on the transmission,
        seconds and a few hundred yards apart; the altitude is range-dependent,
        so it stepped between them:

            ATC[vec] ... turn right heading two four five, maintain three thousand
            ASR:     ... Fly heading 245, maintain 5500

        Neither was wrong about its own instant. Asking the question twice was.
        """
        out = agent_atc.asr_context(self.asr, self.scope(14, 300), "Pony 1-1")
        self.assertIn("do NOT issue a heading", out)
        self.assertNotIn(str(self.asr.platform_ft), out,
                         "the agent was handed an altitude to read out")

    def test_on_final_the_agent_is_told_to_stop_repeating(self):
        # The mile calls already go out automatically; the agent reporting range
        # and heading too meant the pilot heard the same numbers twice from the
        # same controller. That is what "too chatty on final" meant.
        out = agent_atc.asr_context(self.asr, self.scope(6), "Pony 1-1")
        self.assertIn("on final", out)
        self.assertIn("do NOT repeat", out)

    def test_off_course_is_named(self):
        inbound = (self.asr.final_crs_true + 180) % 360
        right = agent_atc.asr_context(
            self.asr, self.scope(6, inbound - 8), "Pony 1-1")
        left = agent_atc.asr_context(
            self.asr, self.scope(6, inbound + 8), "Pony 1-1")
        self.assertIn("right of course", right)
        self.assertIn("left of course", left)

    def test_the_missed_approach_point(self):
        out = agent_atc.asr_context(self.asr, self.scope(0.4, 304), "Pony 1-1")
        self.assertIn("missed approach point", out)

    def test_past_the_field_and_low_gets_the_missed_approach(self):
        # Lined up, low, four miles beyond the threshold: he has flown the
        # approach and not landed, and the plate answers that -- not a vector.
        out = agent_atc.asr_context(self.asr, self.scope(4, 124), "Pony 1-1")
        self.assertIn("issed approach", out)
        self.assertNotIn("of course", out.split("Do NOT")[0])

    def test_no_bare_digits_in_the_range_call(self):
        # Range reaches Polly as words; a bare "6" would be read as a digit.
        #
        # Six miles TO TOUCHDOWN, which is further out on radar -- the reference
        # the sim gives us is the runway centre and the wheels go down half a
        # mile before it. The test says which one it means rather than assuming
        # they are the same number, because for a while they were.
        radar_nm = 6 + self.asr.touchdown_offset_nm
        out = agent_atc.asr_context(self.asr, self.scope(radar_nm), "Pony 1-1")
        self.assertIn("six miles", out)


class TestAsrRangeCall(unittest.TestCase):
    """The metronome underneath a talk-down. Deterministic on purpose: it must
    arrive every mile, on time, with the right number, and there is no judgement
    in the sentence to justify a model call."""

    def setUp(self):
        from marshall.atc import asr
        from marshall.core import route as R
        self.asr, self.p = asr, R.BATUMI_ASR

    def g(self, nm, radial=None, heading=None):
        # A radar track always carries a heading, and the engine will not call
        # an aircraft established without one -- being on the centreline says
        # nothing about which way along it you are going, which is exactly how
        # a go-around tracking outbound was once cleared down to minimums.
        # A radial and an aircraft's heading are both TRUE -- that is the frame
        # radar reports in. Only the number the controller SAYS is magnetic.
        radial = (radial if radial is not None
                  else (self.p.final_crs_true + 180) % 360)
        heading = self.p.final_crs_true if heading is None else heading
        return self.asr.guide(self.asr.Position(nm, radial, 500, heading), self.p)

    def test_on_course_call(self):
        out = agent_atc.asr_call(_BRIDGE, "Pony 1-1", self.g(6 + self.p.touchdown_offset_nm))
        self.assertIn("six miles from the runway, on course", out)
        self.assertIn("altitude should be", out)

    def test_off_course_call_carries_a_heading(self):
        out = agent_atc.asr_call(_BRIDGE, "Pony 1-1", self.g(6, 296))
        self.assertIn("right of course", out)
        self.assertIn("turn heading", out)

    def test_missed_approach_point_call(self):
        out = agent_atc.asr_call(_BRIDGE, "Pony 1-1", self.g(0.4))
        self.assertIn("missed approach point", out)

    def test_no_digits_reach_polly(self):
        # Every branch, not just the tidy one: the off-course call carries a
        # heading and both carry an advisory altitude, and each arrived as bare
        # digits at some point. "127" is read as "one hundred twenty seven".
        for nm in (1, 2, 3, 4, 6, 8):
            for radial in (None, 296, 312):
                out = agent_atc.asr_call(_BRIDGE, "Pony 1-1", self.g(nm, radial))
                with self.subTest(nm=nm, radial=radial):
                    self.assertEqual([c for c in out if c.isdigit()], [], out)

    def test_altitudes_below_a_thousand_are_spoken_properly(self):
        from marshall.atc import controller as ctl
        self.assertEqual(ctl.spell_alt(700), "seven hundred")
        self.assertEqual(ctl.spell_alt(400), "four hundred")
        self.assertEqual(ctl.spell_alt(300), "three hundred")
        self.assertEqual(ctl.spell_alt(1900), "one thousand nine hundred")

    def test_the_callsign_is_spoken_not_written(self):
        self.assertNotIn("1-1", agent_atc.asr_call(_BRIDGE, "Pony 1-1", self.g(6)))


class TestRadarFixes(unittest.TestCase):
    def test_lists_only_identified_contacts(self):
        scope = ("E11 [Pony one one] (P-51D): 6.0 nm on the 304 radial, "
                 "500 ft, heading 124 | "
                 "Bogey (P-51D): 3.0 nm on the 310 radial, 900 ft, heading 100 | "
                 "E12 [Hawk one] (P-51D): 9.0 nm on the 300 radial, 2,000 ft, "
                 "heading 130")
        got = agent_atc.radar_fixes(scope)
        # Three values now: the picture he was fixed AGAINST rides along, so a
        # caller working two aerodromes knows which field's ranges it is
        # holding. See `radar_fixes(picture=...)`.
        self.assertEqual([cs for cs, _, _ in got], ["Pony one one", "Hawk one"])

    def test_empty_scope(self):
        self.assertEqual(agent_atc.radar_fixes(""), [])
        self.assertEqual(agent_atc.radar_fixes("no contacts"), [])

class TestDebugNote(unittest.TestCase):
    """A note to the log, not to the controller. Saying it in the air must
    produce silence -- a reply both breaks the fiction and buries the note."""

    def test_recognised_forms(self):
        for said, want in [
            ("DEBUG LOG the vectors are taking me at the field",
             "the vectors are taking me at the field"),
            ("debug note, he turned me the long way round",
             "he turned me the long way round"),
            ("Debug: range calls never fired", "range calls never fired"),
        ]:
            with self.subTest(said=said):
                self.assertEqual(agent_atc.debug_note(said), want)

    def test_a_bare_debug_keeps_the_whole_transmission(self):
        self.assertEqual(agent_atc.debug_note("debug"), "debug")

    def test_a_real_call_is_not_a_note(self):
        for said in ("Batumi Approach, Pony one one, checking in",
                     "Pony one one, level two thousand",
                     "request position report"):
            with self.subTest(said=said):
                self.assertIsNone(agent_atc.debug_note(said))

class TestPronunciation(unittest.TestCase):
    """Polly reads "readback" as the past tense -- RED-back -- because that is
    the commoner English word. A controller says REED-back."""

    def setUp(self):
        from marshall.radio import tts
        self.say = tts.pronounce

    def test_readback(self):
        self.assertEqual(self.say("Pony one one, readback correct."),
                         "Pony one one, reed back correct.")

    def test_capitalisation_is_preserved(self):
        self.assertTrue(self.say("Readback correct.").startswith("Reed"))

    def test_field_names(self):
        self.assertNotIn("Batumi", self.say("Batumi Approach, radar contact."))
        self.assertNotIn("Kobuleti", self.say("Contact Kobuleti Departure."))

    def test_ordinary_words_are_untouched(self):
        """Words not in the table pass through exactly. The examples avoid
        three, five and nine on purpose -- those ARE in the table now."""
        for said in ("Pony one one, cleared to land runway one two.",
                     "turn left heading one two four, maintain two thousand"):
            self.assertEqual(self.say(said), said)

    def test_THE_ICAO_DIGITS_ARE_APPLIED_TO_EVERYTHING(self):
        """The rule that replaced putting ICAO words in `core/say`.

            "If we always regex swap nine for niner before it goes to Polly,
             wouldn't that make it easier to write phrases in other modules
             without concern for phraseology like that?"

        Yes -- and the stronger reason is the AGENT, which writes its own prose
        and says "five thousand" no matter what the prompt asks for. Doing it
        in the spellers gave "fife" from the engine and "five" from the model
        in one sortie. Here it catches everything that reaches a pilot,
        including prose nobody in this repo wrote.
        """
        self.assertEqual(self.say("maintain five thousand"),
                         "maintain fife thousand")
        self.assertEqual(self.say("heading three six zero"),
                         "heading tree six zero")
        self.assertEqual(self.say("altimeter two nine eight nine"),
                         "altimeter two niner eight niner")

    def test_it_does_not_chew_words_that_merely_contain_them(self):
        """Whole words only. "fifty" is not "fife-ty" and "ninety" is not
        "niner-ty" -- the regex has always been word-bounded and this is the
        change most likely to expose it if it were not."""
        for said in ("wind two seven zero at fifty",
                     "ninety knots", "threshold", "nineteen"):
            with self.subTest(said=said):
                self.assertEqual(self.say(said), said)

    def test_empty(self):
        self.assertEqual(self.say(""), "")
        self.assertEqual(self.say(None), "")

if __name__ == "__main__":
    unittest.main()


class TestCourseTalkOnlyWhenOnCourse(unittest.TestCase):
    """"Left of course" is a claim about a course he is actually flying.

    Said to an aircraft climbing away on its missed approach -- having just
    been told to fly 330, and flying 330 -- it is simply false, and it invites
    the pilot to correct a course he has been ordered off. Heard live.
    """

    def setUp(self):
        from marshall.atc import asr
        from marshall.core import route as R
        self.asr, self.p = asr, R.BATUMI_ASR

    def g(self, nm, radial, hdg, alt=2000):
        return self.asr.guide(self.asr.Position(nm, radial, alt, hdg), self.p)

    def test_the_missed_approach_is_never_told_it_is_off_course(self):
        g = self.g(5, 120, 330, alt=1600)
        self.assertEqual(g.phase, "missed")
        self.assertFalse(g.off_course)
        self.assertEqual(g.deviation, "")
        # asr_call is what the pilot HEARS; the context is what the agent is
        # told, and it may mention the phrase only to forbid it.
        self.assertNotIn("of course", agent_atc.asr_call(_BRIDGE, "Pony 1-1", g))

    def test_repositioning_outbound_is_not_told_it_is_off_course(self):
        g = self.g(9, 330, 300, alt=3000)
        self.assertFalse(g.off_course)
        self.assertNotIn("of course", agent_atc.asr_call(_BRIDGE, "Pony 1-1", g))

    def test_an_inbound_aircraft_that_drifts_IS_told(self):
        # The whole point of the approach: this one must still be corrected.
        g = self.g(6, 296, 124, alt=1500)
        self.assertTrue(g.off_course)
        self.assertIn("of course", agent_atc.asr_call(_BRIDGE, "Pony 1-1", g))


class TestOneAircraftOneInstruction(unittest.TestCase):
    """The bridge must not ask the agent to arbitrate.

    Three things have an opinion: the separation engine owns the queue and
    cannot see, the vectoring owns the geometry and cannot remember, the agent
    owns the words. All three used to be appended to the agent's context side
    by side, each labelled authoritative.

    A model asked to choose between two confident contradictory instructions
    says both. Heard on the radio, in one transmission: a flight established on
    the final approach course at ten miles was told it was on final AND to climb
    to five thousand and hold. Neither half was wrong about its own job; the
    bridge was wrong to ask the question.
    """

    def setUp(self):
        from marshall.atc import asr
        from marshall.core import route as R
        self.asr, self.p = asr, R.BATUMI_ASR

    def g(self, nm, radial, hdg, alt=2000):
        return self.asr.guide(self.asr.Position(nm, radial, alt, hdg), self.p)

    HOLD = "Pony 1-1, hold present position, maintain five thousand."
    VEC = "ASR: vectoring, eight miles. Fly heading 120."

    # THE SAME HOLD AS A DECISION. `reconcile` reads the kind now rather than
    # searching the sentence for the word -- see the class below, which is the
    # regression that forced it.
    def hold_decision(self):
        from marshall.atc import decision as D
        return D.Decision(kind="hold", to="Pony 1-1", altitude_ft=5000)

    def test_a_hold_is_suppressed_for_an_aircraft_on_the_approach(self):
        # Established and inbound: on the centreline, pointing down it. Both
        # numbers come from the profile because both used to be written out --
        # 304 and 124 -- against a course that was six degrees off.
        from marshall.core import route as _R
        crs = _R.BATUMI_ASR.final_crs_true
        g = self.g(8, (crs + 180) % 360, crs)
        self.assertTrue(g.established or g.phase in ("final", "map"))
        directive, _, vectoring, dropped, _kept = agent_atc.reconcile(
            self.HOLD, "", self.VEC, g)
        self.assertEqual(directive, "", "he was told to hold while on final")
        self.assertTrue(vectoring, "the talk-down was dropped instead")
        self.assertIn("suppressed", dropped)

    def test_the_missed_approach_owns_him_completely(self):
        g = self.g(5, 120, 330, alt=1600)
        self.assertEqual(g.phase, "missed")
        directive, _, _, dropped, _kept = agent_atc.reconcile(
            self.HOLD, "", self.VEC, g)
        self.assertEqual(directive, "")
        self.assertIn("missed", dropped)

    def test_holding_suppresses_the_vector_not_the_other_way_round(self):
        # Out of position and told to wait: the vector would be a second
        # altitude in the same transmission, which is how this started.
        g = self.g(20, 60, 60)
        self.assertFalse(g.established)
        directive, _, vectoring, dropped, _kept = agent_atc.reconcile(
            self.HOLD, "", self.VEC, g)
        self.assertTrue(directive, "the holding clearance was lost")
        self.assertEqual(vectoring, "")
        self.assertIn("two altitudes", dropped)

    def test_the_stack_always_survives(self):
        # It is about the OTHER aircraft, so no state of this one silences it.
        for g in (self.g(8, 304, 124), self.g(5, 120, 330, 1600),
                  self.g(20, 60, 60)):
            _, stack, _, _, _ = agent_atc.reconcile(
                self.HOLD, "STACK: two", self.VEC, g)
            self.assertEqual(stack, "STACK: two")

    def test_with_no_radar_nothing_is_suppressed(self):
        # Blind, we have no grounds to overrule anyone.
        d, s, v, dropped, kept = agent_atc.reconcile(
            self.HOLD, "S", self.VEC, None, [self.hold_decision()])
        self.assertEqual((d, s, v, dropped), (self.HOLD, "S", self.VEC, ""))
        self.assertEqual(len(kept), 1, "nothing was suppressed")


class TestNoiseDoesNotStealTheRadio(unittest.TestCase):
    """One garbled call must not rebind a radio that has identified properly.

    A P-47 bound itself to "Waypoint 3" off a single misheard transmission and
    then overrode every correct "Hammer one two" that followed -- and the
    separation stack filled with aeroplanes that did not exist.
    """

    def setUp(self):
        _BRIDGE.transmitters.clear()
        _BRIDGE.order.clear()

    def test_an_established_binding_survives_one_garble(self):
        for _ in range(3):
            agent_atc.transmitter_callsign(_BRIDGE, "g9", "Hammer one two, level five thousand")
        self.assertEqual(
            agent_atc.transmitter_callsign(_BRIDGE, "g9", "Waypoint three, say distance"),
            "Hammer 1-2")

    def test_saying_it_twice_re_identifies(self):
        for _ in range(3):
            agent_atc.transmitter_callsign(_BRIDGE, "g9", "Hammer one two, level five thousand")
        agent_atc.transmitter_callsign(_BRIDGE, "g9", "Pony one one, checking in")
        agent_atc.transmitter_callsign(_BRIDGE, "g9", "Pony one one, five thousand")
        agent_atc.transmitter_callsign(_BRIDGE, "g9", "Pony one one, inbound")
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "g9", "say again"),
                         "Pony 1-1")


class TestOneBridgeAtATime(unittest.TestCase):
    """Two bridges on one frequency is the most expensive failure here.

    Killing the `uv run` launcher does not kill the python child, so "restart
    the bridge" quietly leaves the old one logged into SRS. Both answer, and
    each hears the other's reply as a pilot call. It happened twice on squadron
    night and was reported both times as "duplicate controllers": two stacks,
    two conversations, one believing a pilot inbound while the other believed
    him outbound, both fluent.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "bridge.lock")
        self._saved = agent_atc._lock_fd
        agent_atc._lock_fd = None

    def tearDown(self):
        if agent_atc._lock_fd:
            agent_atc._lock_fd.close()
        agent_atc._lock_fd = self._saved

    def test_the_first_bridge_takes_the_frequency(self):
        self.assertTrue(agent_atc.claim_the_frequency(self.path))

    def test_the_second_is_refused(self):
        held = agent_atc.claim_the_frequency(self.path)
        self.assertTrue(held)
        first = agent_atc._lock_fd
        agent_atc._lock_fd = None       # a genuinely separate claim
        self.assertFalse(agent_atc.claim_the_frequency(self.path))
        agent_atc._lock_fd = first

    def test_the_lock_names_the_process_holding_it(self):
        agent_atc.claim_the_frequency(self.path)
        with open(self.path) as fh:
            self.assertEqual(fh.read().strip(), str(os.getpid()),
                             "the refusal message has to say what to kill")

    def test_releasing_frees_it(self):
        agent_atc.claim_the_frequency(self.path)
        agent_atc._lock_fd.close()      # what process death does for us
        agent_atc._lock_fd = None
        self.assertTrue(agent_atc.claim_the_frequency(self.path),
                        "a crashed bridge must not block the next one")


class TestEngineeringChannel(unittest.TestCase):
    """Getting a human on the line, and knowing whether one is there.

    The failure this replaces: a pilot transmitted into what he thought was a
    live channel and got nothing back -- "I tried talking to you, no response"
    -- with no way to tell a dead process from an engineer who was heads-down
    in code. Either answer is fine. Not knowing is not.
    """

    def test_the_ways_a_pilot_actually_asks(self):
        """Saying the word is the call.

        A list of accepted wordings is a list of ways to be ignored: of
        twenty-five natural phrasings against the original pattern, twelve
        missed -- including just saying "Engineering".
        """
        for said in ("get engineering on the line",
                     "Engineering, are you there?",
                     "engineering come up",
                     "engineering radio check",
                     "Engineering?",
                     "engineering, you up?",
                     "engineering, how do you read",
                     "is engineering there",
                     "Hoover one one for engineering",
                     "need engineering"):
            with self.subTest(said=said):
                self.assertTrue(agent_atc._ENG_CALL.search(said))

    def test_merely_mentioning_engineering_is_not_a_summons(self):
        """Said TO a controller, these are ordinary talk. Routing them away
        from ATC would be its own kind of not-listening."""
        for said in ("engineering",
                     "engineering said the vectors are fixed",
                     "the engineering fix worked",
                     "tell approach the engineering change is in"):
            with self.subTest(said=said):
                self.assertIsNone(agent_atc._ENG_CALL.search(said))


    def test_an_ordinary_call_is_not_a_summons(self):
        for said in ("Batumi Approach, Hammer one one, request the approach",
                     "Hammer one one going around",
                     "Sentry, Hammer one one, request a target"):
            with self.subTest(said=said):
                self.assertIsNone(agent_atc._ENG_CALL.search(said))


    # THE BENCH FILE IS LIVE STATE. These used to touch and unlink the real
    # `build/engineering.attended`, which is the same file a human claims when
    # he sits down at the bench -- so running the unit suite VACATED THE BENCH,
    # silently, from anywhere.
    #
    # It cost a live test. Hoover called for engineering on the ramp and was
    # told nobody was there while I was sitting at the keyboard; the difference
    # between the two was that I had run pytest ninety seconds earlier. He
    # reported A1 as failing, which it was, for a reason that had nothing to do
    # with A1.
    #
    # A test may not write anywhere a running system reads. The path is swapped
    # for a temporary one and put back.

    def setUp(self):
        self._real_attended = agent_atc.ENG_ATTENDED
        self._tmp = tempfile.mkdtemp(prefix="marshall-bench-")
        agent_atc.ENG_ATTENDED = pathlib.Path(self._tmp) / "engineering.attended"

    def tearDown(self):
        agent_atc.ENG_ATTENDED = self._real_attended
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_the_real_bench_is_never_touched_by_a_test(self):
        """The guard for the guard. If this class ever writes to the live path
        again, this is the test that says so."""
        self.assertNotEqual(agent_atc.ENG_ATTENDED, self._real_attended)
        self.assertNotIn("build", str(agent_atc.ENG_ATTENDED))

    def test_an_unattended_bench_says_so_rather_than_going_quiet(self):
        self.assertFalse(agent_atc.engineering_attended())
        ack = agent_atc.engineering_ack(summoned=True)
        self.assertIn("not at the bench", ack)
        self.assertIn("recorded", ack, "silence is the thing being fixed")

    def test_an_attended_bench_invites_him_to_talk(self):
        agent_atc.ENG_ATTENDED.touch()
        self.assertTrue(agent_atc.engineering_attended())
        self.assertIn("go ahead", agent_atc.engineering_ack(summoned=True))

    def test_a_stale_claim_counts_as_nobody_home(self):
        import os as _os
        import time as _t
        agent_atc.ENG_ATTENDED.touch()
        old = _t.time() - agent_atc.ENG_ATTENDED_SEC - 60
        _os.utime(agent_atc.ENG_ATTENDED, (old, old))
        self.assertFalse(agent_atc.engineering_attended(),
                         "a stale claim is worse than an honest 'not here'")


class TestChannelCourtesy(unittest.TestCase):
    """A radio is half duplex, and so are the manners.

    "the controller talks over us constantly, and didnt give us time for a
    readback" -- the mile-call metronome transmitted on its own schedule
    regardless of what was happening on the frequency. The radio lock only ever
    stopped the bridge's own threads overlapping each other; it knew nothing
    about the humans.
    """

    def setUp(self):
        from marshall.radio.client import SRSClient
        self.c = SRSClient.__new__(SRSClient)     # no socket, no server
        self.c.last_rx = 0.0

    def test_a_quiet_channel_is_free(self):
        self.assertFalse(self.c.someone_is_talking())

    def test_a_pilot_mid_transmission_holds_the_channel(self):
        import time as _t
        self.c.last_rx = _t.monotonic()
        self.assertTrue(self.c.someone_is_talking())

    def test_the_channel_comes_back_after_he_stops(self):
        import time as _t
        self.c.last_rx = _t.monotonic() - 3.0
        self.assertFalse(self.c.someone_is_talking(),
                         "three seconds of silence is his transmission ended")

    def test_the_window_is_short_enough_to_be_courtesy_not_deafness(self):
        """Deferring must not mean missing. A mile call held for a whole mile
        is worse than one that steps on a word."""
        import time as _t
        self.c.last_rx = _t.monotonic() - 1.4
        self.assertTrue(self.c.someone_is_talking())
        self.c.last_rx = _t.monotonic() - 1.6
        self.assertFalse(self.c.someone_is_talking())


class TestIdentityThroughBreakUp(unittest.TestCase):
    """Telling two aeroplanes apart after the formation stops existing.

    Live, a two-ship split for individual approaches and the controller went on
    calling one of them "Pony 1" -- the FLIGHT -- and the other "Pony 1-1".
    Adjacent, confusable, and one of those names did not refer to an aeroplane
    at all: it referred to a formation that had just ceased to exist.

    Fixed by letting a MORE PRECISE self-identification win at once, rather than
    by forgetting the old binding. Forgetting was tried and rejected in the
    voice rehearsal: it hands identity to the transcriber at the exact moment
    everyone is saying new callsigns, and it produced "Pony won", "Pony12" and
    an aeroplane called "21-2" that took a place in the holding stack.
    """

    def setUp(self):
        _BRIDGE.transmitters.clear()
        _BRIDGE.order.clear()

    def bind(self, guid, said, times=1):
        for _ in range(times):
            agent_atc.transmitter_callsign(_BRIDGE, guid, said)

    def test_a_member_callsign_beats_the_flight_at_once(self):
        self.bind("shooter", "Pony one, flight of two, checking in", times=6)
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "shooter", ""), "Pony 1")
        self.assertEqual(
            agent_atc.transmitter_callsign(_BRIDGE, "shooter", "Pony one two, checking in"),
            "Pony 1-2",
            "he cannot out-vote himself, so counting must not decide this")

    def test_and_it_sticks(self):
        self.bind("shooter", "Pony one, checking in", times=6)
        agent_atc.transmitter_callsign(_BRIDGE, "shooter", "Pony one two, checking in")
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "shooter", "say again"),
                         "Pony 1-2")

    def test_a_different_flight_does_not_hijack_him(self):
        """Precision only wins WITHIN the flight he already answers to."""
        self.bind("shooter", "Pony one, checking in", times=6)
        agent_atc.transmitter_callsign(_BRIDGE, "shooter", "Hammer one two, checking in")
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "shooter", ""), "Pony 1")

    def test_noise_still_loses_to_an_established_member_binding(self):
        self.bind("sockeye", "Pony one one, checking in", times=4)
        self.assertEqual(
            agent_atc.transmitter_callsign(_BRIDGE, "sockeye", "Waypoint three, say range"),
            "Pony 1-1")


class TestPlausibleCallsign(unittest.TestCase):
    """The classifier is a model, and a model asked "whose call is this?" will
    answer even when the transcript has no callsign in it.

    Whisper turned "Pony one two, say my altitude" into "21-2, same by
    altitude"; the classifier filed it as an aircraft called 21-2, and it took a
    place in the holding stack behind two real ones.
    """

    def test_a_callsign_needs_a_name(self):
        for bad in ("21-2", "2 1 2", "1-1", "7"):
            with self.subTest(bad=bad):
                self.assertFalse(agent_atc._plausible_callsign(bad))

    def test_real_callsigns_pass(self):
        for good in ("Pony 1-1", "Hammer 1", "Whistler 2-3", "Hoover 1"):
            with self.subTest(good=good):
                self.assertTrue(agent_atc._plausible_callsign(good))


class TestCallingAControllerLetsYouGo(unittest.TestCase):
    """Forgetting to release must not make the controller deaf to you.

    Everything a pilot says goes to engineering until he releases the line, and
    the moment he is most likely to forget is the moment it costs most -- four
    miles out with other things to think about. Addressing a station by name is
    an unambiguous statement about who he is talking to.
    """

    def setUp(self):
        from marshall.core import route as R
        import re as _re
        names = [s.name for s in R.BATUMI_ASR.stations]
        self.rx = _re.compile("|".join(_re.escape(n) for n in names), _re.I)

    def test_naming_a_controller_releases(self):
        for said in ("Batumi Approach, Hoover one one, request the approach",
                     "Batumi Tower, Hoover one one, going around",
                     "Sentry, Hoover one one, request a target",
                     "Georgia Center, Hoover one one, checking in"):
            with self.subTest(said=said):
                self.assertTrue(self.rx.search(said))

    def test_talking_to_engineering_does_not(self):
        for said in ("B4 passed", "the vectors turned me at four miles",
                     "engineering, B4 passed", "thanks engineering"):
            with self.subTest(said=said):
                self.assertIsNone(self.rx.search(said))


class TestShipToShipIsNotOurs(unittest.TestCase):
    """Two aircraft talking to each other on our frequency.

    Real ATC assumes a pilot is talking to it -- nobody says "Omaha Approach" on
    every transmission -- so ours answers everything on its channel. But
    occasionally a flight talks to itself on it, and a controller hears that,
    understands it is not his, and says nothing.
    """

    def setUp(self):
        from marshall.core import route as R
        self.f = agent_atc.addressed_to_another_aircraft
        self.st = [s.name for s in R.BATUMI_ASR.stations]

    def test_opening_with_another_aircraft_is_theirs(self):
        for said in ("Pony one two, Pony one one, join up",
                     "Pony one two, you are cleared to cross",
                     "Hammer one two, Hammer one one, go button three"):
            with self.subTest(said=said):
                self.assertTrue(self.f(said, "Pony 1-1", self.st))

    def test_opening_with_his_own_name_is_ours(self):
        self.assertEqual(self.f("Pony one one, level five thousand",
                                "Pony 1-1", self.st), "")

    def test_opening_with_a_station_is_ours(self):
        for said in ("Batumi Approach, Pony one one, request the approach",
                     "Sentry, Pony one one, request a target",
                     "Batumi Tower, Pony one one, going around"):
            with self.subTest(said=said):
                self.assertEqual(self.f(said, "Pony 1-1", self.st), "")

    def test_opening_with_nothing_is_ours(self):
        """The normal case: he does not re-address us every time."""
        self.assertEqual(self.f("level five thousand", "Pony 1-1", self.st), "")

    def test_an_unidentified_speaker_is_always_answered(self):
        """Guessing a call is not for us is worse than answering one that was
        not -- the pilot gets silence and no way to tell why."""
        self.assertEqual(self.f("Pony one two, Pony one one, join up",
                                "", self.st), "")


class TestWhoIsCallingLevelFourThousand(unittest.TestCase):
    """A controller does not harass a man for his callsign mid-conversation --
    he knows the voice. But a report out of a silent frequency gets asked.

        "when a quick back and forth is happening, atc knows the pilots voice
         and doesn't harass him for his callsign. But 4000 level out of the
         blue! That will get a 'who's calling level 4000?' kind of call"
    """

    def setUp(self):
        _BRIDGE.last_heard.clear()

    def test_a_reply_inside_a_conversation_is_not_challenged(self):
        _BRIDGE.last_heard["g"] = time.time()
        self.assertTrue(agent_atc.in_conversation(_BRIDGE, "g"))

    def test_out_of_the_blue_is(self):
        _BRIDGE.last_heard["g"] = time.time() - agent_atc.CONVERSATION_SEC - 5
        self.assertFalse(agent_atc.in_conversation(_BRIDGE, "g"))

    def test_a_radio_never_heard_from_is_out_of_the_blue(self):
        self.assertFalse(agent_atc.in_conversation(_BRIDGE, "never-spoken"))

    def test_the_challenge_repeats_what_was_heard(self):
        """So he knows he WAS heard and only the identity is missing -- a
        different problem from a dead radio, and it should not sound like one."""
        said = agent_atc.challenge_for("four thousand level")
        self.assertIn("four thousand level", said)
        self.assertIn("say your callsign", said)

    def test_it_copes_with_nothing_worth_repeating(self):
        self.assertIn("say your callsign", agent_atc.challenge_for(""))


class TestOnlyRealNamesBecomeAeroplanes(unittest.TestCase):
    """Six ghosts reached a live separation stack before this was structural.

    21-2, Have 2, Waypoint 3, Need 3, Transmission 2, Busy 4 -- and every fix
    was another word on a denylist, which cannot converge: any English word in
    front of a digit is a candidate, and one of those fixes CREATED the next
    ghost. #13 was closed on that denylist and had to be reopened within the
    hour.

    Two things ARE enumerable where English words are not: the roster, and
    POSITION. A callsign opens a transmission; noise sits mid-sentence. Every
    ghost here was mid-sentence and every real callsign was in the first few
    words, which is how radio works rather than a coincidence.
    """

    def setUp(self):
        os.environ["MARSHALL_CALLSIGNS"] = "Hoover"

    def test_a_roster_name_is_an_aeroplane_on_sight(self):
        self.assertTrue(agent_atc._plausible_callsign("Pony 1-1", "Pony one one, level"))

    def test_a_name_from_the_command_line_too(self):
        self.assertTrue(agent_atc._plausible_callsign(
            "Hoover 1-1", "Batumi Approach, Hoover one one, checking in"))

    def test_an_unknown_name_that_OPENS_a_call_is_admitted(self):
        """A visiting pilot must not be refused for being new."""
        self.assertTrue(agent_atc._plausible_callsign(
            "Viper 2-1", "Viper two one, checking in"))

    def test_an_unknown_name_mid_sentence_is_not(self):
        for cs, said in (("Busy 4", "I am going to be busy for a minute"),
                         ("Transmission 2",
                          "a deliberately long transmission to hold the frequency"),
                         ("Minute 2", "give me a minute two sort this out")):
            with self.subTest(said=said):
                self.assertFalse(agent_atc._plausible_callsign(cs, said))

    def test_with_no_transcript_it_does_not_block_on_nothing(self):
        self.assertTrue(agent_atc._plausible_callsign("Viper 2-1"))


class TestAFiledPlanIsNotAnAeroplane(unittest.TestCase):
    """A flight plan's spoken name is a callsign by shape.

    It is chosen the way a callsign is chosen -- short, ordinary, phonetically
    distinct -- so "Samovar Three" and "Pony Three" are indistinguishable to any
    rule that looks at the string. A dry run of clearance delivery bound the
    pilot's radio to his own flight plan on the first transmission: everything
    afterwards came from an aeroplane that had never flown, and the controller
    spent the exchange asking a man who had said his callsign twice to say it
    again.

    Two defences, and both are enumerable rather than a guess at English:
    the names we assigned ourselves are registered as not-aircraft, and identity
    binding runs the same roster-or-position test that guards the stack.
    """

    def setUp(self):
        os.environ["MARSHALL_CALLSIGNS"] = "Hoover"
        _BRIDGE.transmitters.clear()
        _BRIDGE.order.clear()
        C._NOT_AN_AIRCRAFT.clear()

    def tearDown(self):
        C._NOT_AN_AIRCRAFT.clear()

    SAID = "Batumi Ground, Hoover one one, request clearance, Samovar Three"

    def test_without_the_list_the_plan_looks_exactly_like_a_callsign(self):
        """Stated so the next person does not mistake the fix for a coincidence:
        the shape alone cannot tell them apart, which is WHY there is a list."""
        self.assertIn("Samovar 3", C.extract_all(self.SAID))

    def test_a_registered_plan_name_is_not_extracted(self):
        C.these_are_not_aircraft(["Samovar One", "Samovar Two", "Samovar Three"])
        self.assertEqual(C.extract_all(self.SAID), ["Hoover 1-1"])
        self.assertEqual(C.extract(self.SAID), "Hoover 1-1")

    def test_position_alone_no_longer_separates_them_and_that_is_deliberate(self):
        """An honest record of a guarantee that WEAKENED.

        Position used to refuse "Samovar Three" because it sat late in the
        sentence. Then the rule had to widen: a callsign is at the START or the
        END of a transmission, because reading back puts it last -- "Left zero
        nine zero, Falcon one one" -- and rejecting that made a pilot's own
        aeroplane vanish from the board every time he did the correct thing.

        The plan name is also at the end, so position can no longer tell them
        apart. What does is the REGISTERED list of plan names, which the bridge
        loads from the director when it primes the transcriber. That is the
        structural fix and this is the belt it replaced.
        """
        C._NOT_AN_AIRCRAFT.clear()
        self.assertIn("Samovar 3", C.extract_all(self.SAID))

    def test_with_the_plans_registered_the_radio_binds_to_the_pilot(self):
        C.these_are_not_aircraft(["Samovar One", "Samovar Two", "Samovar Three"])
        got = agent_atc.transmitter_callsign(_BRIDGE, "guid-sockeye", self.SAID)
        self.assertEqual(got, "Hoover 1-1")

    def test_asking_for_a_clearance_does_not_invent_clearance_four(self):
        """"for" is a homophone of "four", so "clearance for the CAS" produced an
        aeroplane called Clearance 4 -- in the one exchange where every pilot
        says those exact words."""
        said = "Batumi Ground, Hoover one two, request clearance for the CAS"
        self.assertEqual(C.extract_all(said), ["Hoover 1-2"])
        self.assertEqual(agent_atc.transmitter_callsign(_BRIDGE, "guid-two", said),
                         "Hoover 1-2")


class TestTalkingAboutAControllerIsNotCallingHim(unittest.TestCase):
    """Engineering steps aside when the pilot calls a controller. It has to know
    the difference between calling him and mentioning him.

    Hoover's A5 bug report -- "requested a call back, got no call back on one
    three nine Georgia Center" -- contained a station name in the middle of a
    sentence. Engineering stepped out of the way, the controller answered the
    bug report with "say your callsign", and the report went nowhere. An
    ADDRESS opens a transmission; that is how radio works.
    """

    STATIONS = ("Georgia Center", "Batumi Approach", "Batumi Tower")

    def _addressed(self, said: str) -> bool:
        """The predicate as the bridge computes it: whoever is named FIRST in the
        opening of the transmission is who he is calling."""
        import re
        pattern = re.compile("|".join(re.escape(n) for n in self.STATIONS), re.I)
        opening = " ".join(said.split()[:6])
        atc = pattern.search(opening)
        eng = re.search(r"\bengineering\b", opening, re.I)
        return bool(atc) and not (eng and eng.start() < atc.start())

    def test_calling_a_controller_steps_engineering_aside(self):
        for said in ("Georgia Center, Pony one one, checking in",
                     "Batumi Approach Pony one one request the approach",
                     "Batumi Tower, Pony one one, ready to taxi"):
            with self.subTest(said=said):
                self.assertTrue(self._addressed(said))

    def test_a_bug_report_that_names_one_does_not(self):
        for said in ("Engineering, A5 failed, no call back on one three nine "
                     "Georgia Center",
                     "engineering, Batumi Approach vectored me into the hill",
                     "that last one came from Batumi Tower and it was wrong"):
            with self.subTest(said=said):
                self.assertFalse(self._addressed(said))


class TestWhereAPromisedCallbackIsSpoken(unittest.TestCase):
    """A promise kept on a channel nobody is listening to is worse than never
    promising: the pilot cannot tell it from a timer that never fired.

    Hoover asked Georgia Center on 139 for a call in sixty seconds. The hook
    fired on time and the controller made the call on 124, because that is the
    frequency the bridge was started on.
    """

    CENTER, APPROACH = 139.0e6, 124.0e6
    WHY = "Call back Pony 1-1 as he requested on Georgia Center 139.0"

    def test_it_follows_the_man_it_is_owed_to(self):
        got = agent_atc.hook_frequency(self.WHY, {"Pony 1-1": self.CENTER},
                                       self.APPROACH)
        self.assertEqual(got, self.CENTER)

    def test_a_reason_naming_nobody_falls_back_to_the_live_channel(self):
        got = agent_atc.hook_frequency("check the weather again", {},
                                       self.CENTER)
        self.assertEqual(got, self.CENTER)

    def test_a_callsign_we_have_never_heard_does_not_pick_a_channel_for_him(self):
        """He may be named in the reason and have never keyed a mic here."""
        got = agent_atc.hook_frequency(self.WHY, {"Viper 2-1": self.APPROACH},
                                       self.CENTER)
        self.assertEqual(got, self.CENTER)

    def test_with_nothing_known_it_says_so_rather_than_guessing(self):
        self.assertIsNone(agent_atc.hook_frequency(self.WHY, {}, None))


class TestTheReadBackOfAClearanceIsAnswered(unittest.TestCase):
    """An IFR clearance is the one transmission that must be read back AND must
    be answered, and leaving that to the brief lost.

    "Readback correct" competes with the airborne rule that a correct read-back
    is met with silence, and the airborne rule won often enough that Hoover read
    a clearance back on the ramp, got nothing, and had to ask "did you hear my
    read back?" -- after which he was told it was correct.

    So the bridge decides an answer is owed and the agent supplies the words,
    which is the same division as a separation call.
    """

    CLEARANCE = ("Pony one one, cleared to Batumi as filed, maintain four "
                 "thousand, departure frequency one two four decimal zero, "
                 "squawk seven five six zero.")

    def setUp(self):
        _BRIDGE.awaiting_readback.clear()

    def test_a_clearance_is_recognised_by_what_it_carries(self):
        self.assertTrue(agent_atc.is_a_clearance(self.CLEARANCE))

    def test_nothing_else_on_the_frequency_looks_like_one(self):
        for said in ("Pony one one, taxi to active approved, contact Georgia "
                     "Center one three nine",
                     "Pony one one, cleared to land runway one three, wind two "
                     "seven zero at two zero",
                     "Pony one one, descend and maintain four thousand",
                     "Pony one one, radar contact, report the beacon inbound"):
            with self.subTest(said=said):
                self.assertFalse(agent_atc.is_a_clearance(said))

    def test_the_next_transmission_from_him_is_owed_an_answer(self):
        _BRIDGE.awaiting_readback["Pony 1-1"] = 1000.0
        self.assertTrue(agent_atc.readback_due(_BRIDGE, "Pony 1-1", now=1005.0))

    def test_it_is_owed_to_HIM_and_not_to_whoever_speaks_next(self):
        _BRIDGE.awaiting_readback["Pony 1-1"] = 1000.0
        self.assertFalse(agent_atc.readback_due(_BRIDGE, "Pony 1-2", now=1005.0))

    def test_it_stops_being_a_read_back_after_a_while(self):
        """Long enough to write five elements down; short enough that it is not
        still armed when he calls for taxi three minutes later."""
        _BRIDGE.awaiting_readback["Pony 1-1"] = 1000.0
        self.assertFalse(
            agent_atc.readback_due(_BRIDGE,
                "Pony 1-1", now=1000.0 + agent_atc.READBACK_WINDOW_SEC + 1))

    def test_nobody_is_owed_one_by_default(self):
        self.assertFalse(agent_atc.readback_due(_BRIDGE, "Pony 1-1"))


class TestARelativeCorrection(unittest.TestCase):
    """"Turn left ten degrees" -- Hoover's, and it removes a class of error.

        "when in the final phases they say left 10 right 5 and don't bother with
         headings... this would avoid all dg drift and mag compass problems"

    An absolute heading is only as good as the gyro he sets it on, and his read
    seven degrees off the compass while the compass read sixteen off the map. A
    relative correction is the DIFFERENCE between two headings, so every
    constant frame offset -- grid convergence, magnetic variation, a mis-set
    gyro -- cancels out of it.
    """

    def setUp(self):
        from marshall.atc import asr
        from marshall.core import route as R
        self.asr, self.p = asr, R.BATUMI_ASR
        self.inbound = (self.p.final_crs_true + 180) % 360

    def at(self, nm, off_deg, hdg):
        pos = self.asr.Position(nm + self.p.touchdown_offset_nm,
                                (self.inbound + off_deg) % 360, 1500, hdg)
        return self.asr.guide(pos, self.p), pos

    def test_it_names_a_turn_a_pilot_can_fly(self):
        g, pos = self.at(6, 1.5, 145)
        said = agent_atc.relative_correction(g, pos)
        self.assertIn("turn left", said)
        self.assertIn("degrees", said)

    def test_it_is_words_not_digits(self):
        """Everything here reaches Polly as text; a bare 10 is read as a digit."""
        g, pos = self.at(6, 1.5, 145)
        self.assertNotRegex(agent_atc.relative_correction(g, pos), r"\d")

    def test_it_rounds_to_five(self):
        for hdg in range(100, 165, 3):
            g, pos = self.at(5, 1.0, hdg)
            said = agent_atc.relative_correction(g, pos)
            if not said:
                continue
            n = said.split("turn ")[1].split(" ", 1)[1].replace(" degrees", "")
            self.assertIn(n, ("five", "ten", "fifteen", "twenty", "twenty five",
                              "thirty", "thirty five", "forty", "forty five"))

    def test_nothing_to_say_when_he_is_already_on_it(self):
        g, pos = self.at(5, 0.0, int(self.p.final_crs_true))
        self.assertEqual(agent_atc.relative_correction(g, pos), "")

    def test_a_constant_frame_error_cancels(self):
        """The whole point. Shift his heading and the assigned heading by the
        same amount -- a mis-set gyro, a variation, a grid convergence -- and
        the correction is unchanged, because it is a difference."""
        g, pos = self.at(6, 1.5, 145)
        plain = agent_atc.relative_correction(g, pos)
        shifted = self.asr.Position(pos.range_nm, pos.radial_deg, pos.alt_ft,
                                    (pos.heading_deg + 17) % 360)
        from marshall.atc.geometry import Guidance
        g2 = Guidance(g.phase, g.heading, g.altitude_ft, g.range_nm, g.xtk_nm,
                      g.deviation, g.turn, g.speed_kt,
                      heading_true=(g.heading_true + 17) % 360)
        self.assertEqual(agent_atc.relative_correction(g2, shifted), plain)


class TestTheAltitudeCallIsAnInstruction(unittest.TestCase):
    """A talk-down tells a pilot what to DO, one mile before he has to do it.

        "at 4 miles out he should say 4 miles out, on course, descend to 1200.
         This is an anticipatory call so I can be there on time rather than a
         reactive call."

    "Three miles, altitude should be twelve hundred" describes where he ought
    already to be. By the time he has heard it, started down and got there, he
    is a mile further in and behind the profile -- chasing it from above, for
    the whole approach.
    """

    def setUp(self):
        from marshall.atc import asr
        from marshall.core import route as R
        self.asr, self.p = asr, R.BATUMI_ASR
        self.inbound = (self.p.final_crs_true + 180) % 360

    def call_at(self, miles_to_run):
        pos = self.asr.Position(miles_to_run + self.p.touchdown_offset_nm,
                                self.inbound, 1500, self.p.final_crs_true)
        g = self.asr.guide(pos, self.p)
        return agent_atc.asr_call(_BRIDGE, "Pony 1-1", g, pos, self.p), g

    def test_the_call_carries_the_NEXT_miles_altitude(self):
        for miles in (5, 4, 3, 2):
            with self.subTest(miles=miles):
                _, g = self.call_at(miles)
                self.assertEqual(g.descend_to_ft,
                                 self.asr.advisory_altitude(miles - 1, self.p))

    def test_it_is_phrased_as_an_order_not_an_observation(self):
        said, _ = self.call_at(4)
        self.assertIn("descend to", said)
        self.assertNotIn("altitude should be", said)

    def test_a_level_segment_says_maintain(self):
        said, _ = self.call_at(7)
        self.assertIn("maintain", said)
        self.assertNotIn("descend", said)

    def test_the_bottom_step_is_minimums_not_an_odd_number(self):
        """Nobody sets 732 on a subscale."""
        said, _ = self.call_at(1)
        self.assertIn("minimums", said)
        self.assertNotIn("seven hundred", said)

    def test_it_never_steps_below_minimums(self):
        for miles in (3, 2, 1):
            with self.subTest(miles=miles):
                _, g = self.call_at(miles)
                self.assertGreaterEqual(g.descend_to_ft, self.p.mda_ft)

    def test_one_mile_is_not_one_miles(self):
        said, _ = self.call_at(1)
        self.assertIn("one mile from the runway", said)


class TestTheEngineOwnsTheTalkdown(unittest.TestCase):
    """The agent ran a second talkdown beside the engine's, and it cost the
    pilot his descent.

        "He switched between right/left and headings on final. Also missed the
         descent call until the last 900'"

    Both from one cause. The metronome was giving relative corrections every
    mile; the agent was giving absolute headings between them -- and because the
    channel courtesy holds the metronome while somebody is transmitting, the 6,
    5, 4 and 3 mile calls never went out at all. The descent instructions live in
    those calls, so the first he heard about coming down was at two miles.
    """

    class G:
        def __init__(self, phase):
            self.phase = phase

    AGENT_TALKDOWN = [
        "Falcon one one, six miles from the runway, mile left of course, "
        "come right heading one three zero.",
        "Falcon one one, four miles from the runway, slightly left of course, "
        "come right heading one three three.",
        "Falcon one one, turn left heading two nine five, maintain two thousand.",
        "Falcon one one, descend and maintain two thousand.",
    ]

    def test_a_second_talkdown_is_hushed(self):
        for said in self.AGENT_TALKDOWN:
            with self.subTest(said=said):
                out, why = agent_atc.hush_a_second_talkdown(said, self.G("final"))
                self.assertEqual(out, "")
                self.assertTrue(why)

    def test_an_acknowledgement_still_goes_out(self):
        """He is allowed to answer the pilot -- just not to fly him."""
        for said in ("Falcon one one, roger.",
                     "Falcon one one, roger, cleared to land runway one three, "
                     "wind two seven zero at two zero.",
                     "Falcon one one, say again."):
            with self.subTest(said=said):
                out, why = agent_atc.hush_a_second_talkdown(said, self.G("final"))
                self.assertEqual(out, said)
                self.assertEqual(why, "")

    def test_off_the_approach_he_may_vector_normally(self):
        """This is a rule about the FINAL, not a muzzle. While repositioning the
        agent's headings are the only ones there are."""
        said = "Falcon one one, turn left heading two nine five, maintain two thousand."
        for phase in ("vector", "missed", ""):
            with self.subTest(phase=phase):
                out, _ = agent_atc.hush_a_second_talkdown(said, self.G(phase))
                self.assertEqual(out, said)

    def test_no_geometry_means_no_opinion(self):
        said = "Falcon one one, six miles from the runway, come right heading one three zero."
        out, _ = agent_atc.hush_a_second_talkdown(said, None)
        self.assertEqual(out, said)


class TestAGoodReadBackIsNotAnError(unittest.TestCase):
    """The engine moves on between issuing an instruction and hearing it back.

        "he gives me a heading -- say 140 -- then I read back 140 and he says
         incorrect, 135... The result is that it feels like I misspoke it when
         I didn't."

    A read-back is judged against what the pilot was GIVEN, not against what the
    engine has since decided it wants. If the engine now wants something else
    that is a new instruction, and it is spoken as an amendment.
    """

    def setUp(self):
        _BRIDGE.issued.clear()
        agent_atc.note_issued(_BRIDGE,
            "Falcon 1-1",
            "Falcon one one, turn left heading one four zero, maintain two thousand.")

    def test_reading_back_what_he_was_given_is_correct(self):
        for said in ("Left one four zero, two thousand, Falcon one one",
                     "Left 140, Falcon one one",
                     "Falcon one one, one four zero"):
            with self.subTest(said=said):
                self.assertTrue(
                    agent_atc.reads_back_what_we_said(_BRIDGE, "Falcon 1-1", said))

    def test_reading_back_something_else_is_not(self):
        self.assertFalse(agent_atc.reads_back_what_we_said(_BRIDGE,
            "Falcon 1-1", "Left one three five, Falcon one one"))

    def test_his_own_callsign_is_not_a_read_back(self):
        """"Falcon one one" carries an eleven. Without excluding it, every
        transmission he makes counts as reading back an instruction that
        happened to contain one -- including "say again"."""
        for said in ("Falcon one one, say again",
                     "Falcon one one, request the approach"):
            with self.subTest(said=said):
                self.assertFalse(
                    agent_atc.reads_back_what_we_said(_BRIDGE, "Falcon 1-1", said))

    def test_an_altitude_spoken_as_words_still_matches(self):
        self.assertTrue(agent_atc.reads_back_what_we_said(_BRIDGE,
            "Falcon 1-1", "maintain two thousand, Falcon one one"))

    def test_nothing_issued_means_nothing_to_read_back(self):
        self.assertFalse(agent_atc.reads_back_what_we_said(_BRIDGE, "Viper 2-1", "two thousand"))
