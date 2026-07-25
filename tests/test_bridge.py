"""The SRS bridge's text handling -- what actually reaches Polly.

No network: these are the pure functions between the agent's reply and the
radio. They exist because both failures below were found on the air, in the
controller's voice, mid-sortie.
"""

import unittest

from marshall.atc import agent_atc


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


class TestRoster(unittest.TestCase):
    """The SRS name lookup, which is the free identity anchor on every packet."""

    def roster_of(self, *lines):
        from marshall.srs.client import SRSClient
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
        agent_atc._transmitters.clear()

    def test_learns_the_callsign_a_radio_uses(self):
        self.assertEqual(
            agent_atc.transmitter_callsign("g1", "Batumi Approach, Pony one one, "
                                           "flight of four, checking in."),
            "Pony 1-1")

    def test_remembers_it_when_the_callsign_is_missing(self):
        # The whole point: Whisper drops or mangles callsigns constantly, and
        # the controller should still know who is talking.
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        self.assertEqual(
            agent_atc.transmitter_callsign("g1", "uhh, level four thousand"),
            "Pony 1-1")

    def test_a_numbered_phrase_does_not_steal_the_identity(self):
        # "level four thousand" must not rebind the radio to an aircraft called
        # "Level 4" -- a false positive silently reassigns a transmitter.
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        for noise in ("descending to four thousand",
                      "heading three zero four",
                      "runway one two in sight",
                      "passing five thousand"):
            with self.subTest(noise=noise):
                self.assertEqual(agent_atc.transmitter_callsign("g1", noise),
                                 "Pony 1-1")

    def test_a_radio_can_re_identify(self):
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        self.assertEqual(
            agent_atc.transmitter_callsign("g1", "Pony one two, level five thousand"),
            "Pony 1-2")

    def test_radios_are_kept_apart(self):
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        agent_atc.transmitter_callsign("g2", "Pony one three, level five thousand.")
        self.assertEqual(agent_atc.transmitter_callsign("g1", "say again"), "Pony 1-1")
        self.assertEqual(agent_atc.transmitter_callsign("g2", "say again"), "Pony 1-3")

    def test_an_unheard_radio_is_honestly_unknown(self):
        self.assertEqual(agent_atc.transmitter_callsign("g9", "mumble"), "")

    def test_no_guid_is_harmless(self):
        self.assertEqual(agent_atc.transmitter_callsign(None, "Pony one one"), "")


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
        directive, _ = agent_atc.separation_context(
            self.ctl, "over the beacon", self.scope(8.2))
        self.assertIn("POSITION REJECTED", directive)
        # And crucially the engine never saw it.
        self.assertEqual(self.ctl.aircraft, {})

    def test_a_beacon_report_from_overhead_is_accepted(self):
        self.fake(self.intents.IntentKind.REPORT_BEACON, "Pony 1-1")
        directive, _ = agent_atc.separation_context(
            self.ctl, "over the beacon", self.scope(1.2))
        self.assertNotIn("POSITION REJECTED", directive)
        self.assertIn("Pony 1-1", self.ctl.aircraft)

    def test_without_radar_the_report_is_believed(self):
        # No scope, or an unidentified aircraft: the blind procedure is all we
        # have, and refusing every report would ground the whole approach.
        self.fake(self.intents.IntentKind.REPORT_BEACON, "Pony 1-1")
        directive, _ = agent_atc.separation_context(self.ctl, "over the beacon", "")
        self.assertNotIn("POSITION REJECTED", directive)

    def test_other_intents_are_untouched_by_range(self):
        self.fake(self.intents.IntentKind.REPORT_MISSED, "Pony 1-1")
        directive, _ = agent_atc.separation_context(
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

    def scope(self, nm, radial, alt=2000, tag="Pony one one"):
        return (f"Enfield11 [{tag}] (P-51D-30-NA): {nm} nm on the {radial} "
                f"radial, {alt:,} ft, heading 124")

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
        pos = agent_atc.radar_fix(self.scope(6, 304), "Pony 1-3")
        self.assertIsNotNone(pos)

    def test_silent_on_a_non_vectored_approach(self):
        # A beacon letdown must never receive vectors: the homing adapter points
        # the nose at the beacon, so a heading destroys his only reference.
        self.assertEqual(
            agent_atc.asr_context(self.ndb, self.scope(6, 304), "Pony 1-1"), "")

    def test_far_out_is_vectoring(self):
        out = agent_atc.asr_context(self.asr, self.scope(14, 300), "Pony 1-1")
        self.assertIn("vectoring", out)
        self.assertIn(str(self.asr.platform_ft), out)

    def test_on_final_the_agent_is_told_to_stop_repeating(self):
        # The mile calls already go out automatically; the agent reporting range
        # and heading too meant the pilot heard the same numbers twice from the
        # same controller. That is what "too chatty on final" meant.
        out = agent_atc.asr_context(self.asr, self.scope(6, 304), "Pony 1-1")
        self.assertIn("on final", out)
        self.assertIn("do NOT repeat", out)

    def test_off_course_is_named(self):
        right = agent_atc.asr_context(self.asr, self.scope(6, 296), "Pony 1-1")
        left = agent_atc.asr_context(self.asr, self.scope(6, 312), "Pony 1-1")
        self.assertIn("right of course", right)
        self.assertIn("left of course", left)

    def test_the_missed_approach_point(self):
        out = agent_atc.asr_context(self.asr, self.scope(0.4, 304), "Pony 1-1")
        self.assertIn("missed approach point", out)

    def test_past_the_field_is_vectored_back(self):
        out = agent_atc.asr_context(self.asr, self.scope(4, 124), "Pony 1-1")
        self.assertTrue("vectoring" in out or "downwind" in out, out)

    def test_no_bare_digits_in_the_range_call(self):
        # Range reaches Polly as words; a bare "6" would be read as a digit.
        out = agent_atc.asr_context(self.asr, self.scope(6, 304), "Pony 1-1")
        self.assertIn("six miles", out)


class TestAsrRangeCall(unittest.TestCase):
    """The metronome underneath a talk-down. Deterministic on purpose: it must
    arrive every mile, on time, with the right number, and there is no judgement
    in the sentence to justify a model call."""

    def setUp(self):
        from marshall.atc import asr
        from marshall.core import route as R
        self.asr, self.p = asr, R.BATUMI_ASR

    def g(self, nm, radial=None):
        radial = radial if radial is not None else (self.p.final_crs + 180) % 360
        return self.asr.guide(self.asr.Position(nm, radial, 500), self.p)

    def test_on_course_call(self):
        out = agent_atc.asr_call("Pony 1-1", self.g(6))
        self.assertIn("six miles from the runway, on course", out)
        self.assertIn("altitude should be", out)

    def test_off_course_call_carries_a_heading(self):
        out = agent_atc.asr_call("Pony 1-1", self.g(6, 296))
        self.assertIn("right of course", out)
        self.assertIn("turn heading", out)

    def test_missed_approach_point_call(self):
        out = agent_atc.asr_call("Pony 1-1", self.g(0.4))
        self.assertIn("missed approach point", out)

    def test_no_digits_reach_polly(self):
        for nm in (1, 4, 6, 8):
            out = agent_atc.asr_call("Pony 1-1", self.g(nm))
            digits = [c for c in out if c.isdigit()]
            self.assertEqual(digits, [], out)

    def test_the_callsign_is_spoken_not_written(self):
        self.assertNotIn("1-1", agent_atc.asr_call("Pony 1-1", self.g(6)))


class TestRadarFixes(unittest.TestCase):
    def test_lists_only_identified_contacts(self):
        scope = ("E11 [Pony one one] (P-51D): 6.0 nm on the 304 radial, "
                 "500 ft, heading 124 | "
                 "Bogey (P-51D): 3.0 nm on the 310 radial, 900 ft, heading 100 | "
                 "E12 [Hawk one] (P-51D): 9.0 nm on the 300 radial, 2,000 ft, "
                 "heading 130")
        got = agent_atc.radar_fixes(scope)
        self.assertEqual([cs for cs, _ in got], ["Pony one one", "Hawk one"])

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

if __name__ == "__main__":
    unittest.main()
