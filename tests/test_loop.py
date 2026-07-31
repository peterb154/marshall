"""What the receive loop does today. Step 0 of the layering work.

`_run_srs` is 1,167 lines, touches every layer, and until this file **no test
executed one line of it**. That is not a coincidence -- it is the one place
where nothing could be tested in isolation, so nothing was, and it is where
every finding at the top of the 29 July audit lives.

CHARACTERISATION, NOT SPECIFICATION. Everything here asserts what the code does
NOW, including behaviour that is arguably wrong and at least one thing that is
plainly surprising (see `test_intra_flight_is_caught_by_the_SHIP_TO_SHIP_gate`).
When the refactor changes one of these on purpose, the diff on the expectation is
the record of that decision. A test written to describe the INTENDED behaviour
would prove nothing about a refactor, because it would already disagree with the
code it is supposed to be protecting.

So: if one of these fails during the extraction, the question is not "is the new
behaviour better". It is "did I mean to change this, and is it written down".

See `tests/fakeradio.py` for the harness. No production code was changed to make
any of this testable, which is the other half of the rule -- a safety net woven
out of edits to the thing it is protecting has a hole exactly where the work is
about to happen.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakeradio import Sortie

# A manned contact ten miles out, tagged -- the shape the picture takes once the
# agent has bound the callsign with `identify`.
SCOPE = ("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 10.0 nm on the 281 "
         "radial, 4,000 ft, heading 100, 180 knots")
GUID = "pony-guid"
NAME = "362nd_sockeye"


def sortie():
    return Sortie()


class TestATransmissionGetsThrough(unittest.TestCase):
    def test_a_normal_call_reaches_the_director_and_the_reply_is_sent(self):
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, ten miles")
             .radar(SCOPE)
             .replies("RADIO: Pony one one, Batumi Approach, radar contact.")
             .fly())
        self.assertEqual(len(s.asked()), 1)
        self.assertEqual(s.said(), ["Pony one one, Batumi Approach, radar contact."])

    def test_the_reply_goes_out_on_the_frequency_it_arrived_on(self):
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, ten miles")
             .radar(SCOPE).replies("RADIO: roger").fly())
        self.assertEqual(s.said_on(124.0), ["roger"])


class TestWhatTheDirectorIsHanded(unittest.TestCase):
    """The prompt seam. The refactor moves this wholesale, so what goes into it
    is worth pinning line by line."""

    def message(self):
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, ten miles")
             .radar(SCOPE).replies("RADIO: roger").fly())
        return s.asked()[0]

    def test_the_scope_is_injected_whole(self):
        self.assertIn("RADAR: " + SCOPE, self.message())

    def test_the_transmitter_is_named_and_it_is_the_resolved_callsign(self):
        m = self.message()
        self.assertIn("TRANSMITTER:", m)
        self.assertIn("Pony 1-1", m)

    def test_the_pilots_words_come_last(self):
        """Everything before PILOT: is situation, and [CTX-1] strips exactly
        that from history. If the marker moves, context.py stops working and
        nothing else would notice."""
        m = self.message()
        self.assertIn("PILOT:", m)
        self.assertTrue(m.rstrip().endswith("ten miles"), m[-80:])

    def test_the_radar_guidance_is_computed_and_handed_over(self):
        self.assertIn("ASR", self.message())


class TestTheGatesThatDropATransmission(unittest.TestCase):
    """A dropped transmission is indistinguishable from a dead radio in the
    cockpit, and it is the most frequent complaint after a sortie. Each gate is
    pinned with what the pilot HEARS, including silence."""

    def test_our_own_station_is_ignored_silently(self):
        """Two bridges on one frequency answer each other forever."""
        s = (sortie().say(GUID, "Marshall", "Batumi Approach, Pony one one")
             .radar(SCOPE).replies("RADIO: must not be sent").fly())
        self.assertEqual(s.said(), [])
        self.assertEqual(s.asked(), [], "the director was asked about our own voice")

    def test_a_call_with_no_callsign_is_challenged_WITHOUT_asking_the_model(self):
        """The challenge is canned and local. Worth pinning: it means a pilot
        who mumbles his callsign costs nothing and gets an instant answer."""
        s = (sortie().say(GUID, NAME, "level four thousand turning left")
             .radar(SCOPE).replies("RADIO: must not be sent").fly())
        self.assertEqual(s.asked(), [])
        self.assertEqual(len(s.said()), 1)
        self.assertIn("say your callsign", s.said()[0].lower())

    def test_intra_flight_is_ANSWERED_now_not_dropped(self):
        """CHANGED ON PURPOSE, 30 July. This test used to assert the opposite,
        and the diff is the record of the decision.

        It was written to pin a surprise: "Apex two, tighten it up" was dropped
        by the SHIP-TO-SHIP gate rather than by `is_intra_flight`, and since
        both produced identical silence nothing had ever revealed which fired.

        Both gates are now gone. The pilot's ruling: ship-to-ship does not
        belong on this frequency at all -- real aircraft carry a second radio
        and this squadron uses Discord -- so anything arriving here is
        addressed to somebody here, and the controller answers. Guessing at
        intent from the words was the same mistake as guessing at identity from
        the words, which cost two days.

        The RULE is never silently ignore, not always transmit. A correct
        read-back is still answered with silence, on purpose -- an uncorrected
        read-back is the acknowledgement -- but that is now a decision with a
        reason rather than a gate that ate the transmission.
        """
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, request creation "
                              "of Apex flight")
             .radar(SCOPE).replies("RADIO: you are lead of Apex.")
             .say(GUID, NAME, "Apex two, tighten it up")
             .radar(SCOPE).replies("RADIO: Apex, say again for the controller.")
             .fly())
        self.assertEqual(len(s.asked()), 2,
                         "the second call was dropped instead of answered")
        self.assertEqual(len(s.said()), 2)

    def test_a_member_number_never_becomes_his_label(self):
        """The knowledge that used to justify the gate is still worth having,
        one step further in. "Apex 1-2" is how a flight speaks to itself and is
        not a name anybody is addressed by -- left as a claim it would become
        his LABEL, and the controller would start calling a man by a member
        number nobody uses on the air."""
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, request creation "
                              "of Apex flight")
             .radar(SCOPE).replies("RADIO: you are lead of Apex.")
             .say(GUID, NAME, "Apex two, tighten it up")
             .radar(SCOPE).replies("RADIO: roger.")
             .fly())
        self.assertNotIn("Apex 1-2", s.asked()[1])


class TestTheFlightModelInTheLoop(unittest.TestCase):
    def test_creating_a_flight_changes_who_he_is_addressed_as(self):
        """`speaking_as`: once he leads Apex, the TRANSMITTER line names the
        flight rather than the man."""
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, request creation "
                              "of Apex flight")
             .radar(SCOPE).replies("RADIO: you are lead of Apex.")
             .say(GUID, NAME, "Batumi Approach, Apex, ten miles")
             .radar(SCOPE).replies("RADIO: Apex, roger.")
             .fly())
        self.assertEqual(len(s.asked()), 2)
        self.assertIn("Apex", s.asked()[1])

    def test_the_verdict_is_put_in_front_of_the_model(self):
        """Membership is decided here and the agent only voices it -- the same
        rule as separation. If this stops appearing, the controller goes back to
        challenging a man whose flight was just created."""
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, request creation "
                              "of Apex flight")
             .radar(SCOPE).replies("RADIO: you are lead of Apex.")
             .fly())
        self.assertIn("FLIGHT", s.asked()[0])
        self.assertIn("lead of Apex", s.asked()[0])


class TestTheLoopSurvivesTheAwkwardCases(unittest.TestCase):
    def test_an_empty_scope_does_not_stop_the_sortie(self):
        s = (sortie().say(GUID, NAME, "Batumi Approach, Pony one one, ten miles")
             .radar("no contacts").replies("RADIO: not radar identified.").fly())
        self.assertEqual(len(s.said()), 1)

    def test_an_empty_transcript_is_skipped_without_reaching_anything(self):
        s = (sortie().say(GUID, NAME, "")
             .say(GUID, NAME, "Batumi Approach, Pony one one, ten miles")
             .radar(SCOPE).replies("RADIO: roger").fly())
        self.assertEqual(len(s.asked()), 1)

    def test_two_pilots_on_one_frequency_are_kept_apart(self):
        other = ("362nd_andre [Falcon 1-1] (F-16C_50, manned): 20.0 nm on the "
                 "090 radial, 8,000 ft, heading 270, 300 knots")
        s = (sortie()
             .say(GUID, NAME, "Batumi Approach, Pony one one, ten miles")
             .radar(SCOPE + " | " + other).replies("RADIO: Pony one one, roger.")
             .say("andre-guid", "362nd_andre", "Batumi Approach, Falcon one one, twenty miles")
             .radar(SCOPE + " | " + other).replies("RADIO: Falcon one one, roger.")
             .fly())
        self.assertEqual(len(s.asked()), 2)
        self.assertIn("Pony 1-1", s.asked()[0])
        self.assertIn("Falcon 1-1", s.asked()[1])


if __name__ == "__main__":
    unittest.main()


class TestComposeMessageDirectly(unittest.TestCase):
    """The point of the extraction, demonstrated.

    Until 30 July the only way to ask "what does the controller get handed?"
    was to drive 1,167 lines of receive loop. `compose_message` is now a pure
    function of twelve arguments, so the question costs a call. These run in
    microseconds where the loop tests take a third of a second each.
    """

    def compose(self, **over):
        from marshall.atc import agent_atc as A
        from marshall.core import route as R
        args = dict(scope=SCOPE, known="Pony 1-1", transcript="ten miles",
                    profile=R.BATUMI_ASR, me=None, fix=None, nxt=None,
                    directive="", stack="", vectoring="", _flight={},
                    _flight_say="")
        args.update(over)
        return A.compose_message(A.Bridge(), **args)[0]

    def test_the_pilots_words_are_last(self):
        """[CTX-1] strips everything BEFORE the PILOT: marker out of the
        conversation history. If this ordering changes, the context split
        silently stops working and nothing else would notice."""
        m = self.compose()
        self.assertIn("PILOT: ten miles", m)
        self.assertTrue(m.rstrip().endswith("PILOT: ten miles"))

    def test_the_scope_leads(self):
        self.assertTrue(self.compose().startswith("RADAR: "))

    def test_no_scope_means_no_radar_line(self):
        self.assertNotIn("RADAR:", self.compose(scope=""))

    def test_the_engines_directive_is_labelled_as_decided(self):
        """The two-brain seam. The agent must be told these numbers are not
        his to invent -- see the CONTROLLER wording."""
        m = self.compose(directive="descend three thousand")
        self.assertIn("CONTROLLER", m)
        self.assertIn("descend three thousand", m)

    def test_the_stack_is_labelled_separately_from_the_directive(self):
        m = self.compose(stack="Pony 1-1 at five thousand")
        self.assertIn("SEPARATION", m)

    def test_a_flight_verdict_is_carried_verbatim(self):
        m = self.compose(_flight_say="Roger Andre, joined to Apex.")
        self.assertIn("FLIGHT", m)
        self.assertIn("Roger Andre, joined to Apex.", m)

    def test_it_is_pure(self):
        """Same arguments, same answer, and nothing observable changed. That is
        why this block could be moved without a behaviour risk."""
        self.assertEqual(self.compose(), self.compose())


class TestHearDirectly(unittest.TestCase):
    """L0 -> the turn. Audio in, words out, no aviation."""

    def radio(self, script):
        from fakeradio import FakeRadio
        return FakeRadio(script)

    def test_silence_is_not_a_transmission(self):
        from marshall.atc import agent_atc as A

        class Quiet:
            last_sender_guid = None
            def recv_utterance(self, **k): return None, None
        self.assertIsNone(A.hear(A.Bridge(), Quiet(), None, None))

    def test_an_empty_transcript_is_not_a_transmission(self):
        """Whisper returning nothing is the same answer as no audio: both used
        to `continue`, so both return None."""
        import marshall.atc.agent_atc as A
        from marshall.radio import stt
        r = self.radio([("g", "sockeye", "")])
        old = stt.transcribe
        stt.transcribe = lambda *a, **k: r.consume()
        try:
            self.assertIsNone(A.hear(A.Bridge(), r, None, None))
        finally:
            stt.transcribe = old

    def test_it_returns_the_words_and_the_radio_that_said_them(self):
        import marshall.atc.agent_atc as A
        from marshall.radio import stt
        r = self.radio([("g", "362nd_sockeye", "Batumi Approach, Pony one one")])
        old = stt.transcribe
        stt.transcribe = lambda *a, **k: r.consume()
        try:
            r.recv_utterance()
            transcript, srs, _hz = A.hear(A.Bridge(), r, None, None)
        finally:
            stt.transcribe = old
        self.assertEqual(transcript, "Batumi Approach, Pony one one")
        self.assertEqual(srs, "362nd_sockeye")


class TestAttributeDirectly(unittest.TestCase):
    """The identity ladder, now reachable without a sortie. This is the stage
    the whole board keys on, and the one that cost two days when it was wrong."""

    def attribute(self, transcript, srs, scope):
        import marshall.atc.agent_atc as A

        class Radio:
            last_sender_guid = "guid-1"

        class Ctl:
            def identified(self): return []
        saved = (A.fetch_radar, A.filed_plans)
        A.fetch_radar = lambda *a, **k: scope
        A.filed_plans = lambda *a, **k: []
        try:
            return A.attribute(A.Bridge(), Radio(), transcript, srs, "s",
                               True, Ctl())
        finally:
            A.fetch_radar, A.filed_plans = saved

    def test_the_radio_decides_who_he_is_not_the_words(self):
        """He says he is Falcon. Radar and SRS say otherwise, and they win."""
        _scope, claim, ident, _known, who = self.attribute(
            "Batumi Approach, Falcon one one, ten miles", "362nd_sockeye", SCOPE)
        self.assertEqual(ident.authority, "radar")
        self.assertEqual(ident.track, "362nd_sockeye")
        self.assertEqual(who, "sockeye")
        self.assertIn("Falcon", claim)

    def test_with_nothing_on_the_scope_the_chain_does_not_close(self):
        _scope, _claim, ident, _known, who = self.attribute(
            "Batumi Approach, Pony one one", "362nd_sockeye", "no contacts")
        self.assertEqual(ident.track, "")
        self.assertEqual(who, "", "a person was invented from a name")

    def test_the_scope_it_decided_against_is_returned(self):
        """So the rest of the turn reasons about the same picture identity did
        -- fetching it twice would let them disagree."""
        scope, *_ = self.attribute("Pony one one", "362nd_sockeye", SCOPE)
        self.assertEqual(scope, SCOPE)


class TestMembershipDirectly(unittest.TestCase):
    """The flight model, reachable without SRS, Polly, Whisper or a sortie.

    Until now this was only exercised by `tools/flight_rehearsal.py`, which
    needs a running sim, a live bridge and about six minutes. These run in
    milliseconds and cover the same verdicts.
    """

    def setUp(self):
        import marshall.atc.agent_atc as A
        self.A = A
        self._saved = A.record
        A.record = lambda *a, **k: None
        self.bridge = A.Bridge()

    def tearDown(self):
        self.A.record = self._saved

    def ident(self, track):
        return self.A.identity.Identity(callsign="x", track=track,
                                        authority="radar", why="")

    def say(self, who, words, scope=SCOPE, track="362nd_sockeye"):
        return self.A.membership(self.bridge, who, words, scope,
                                 self.ident(track), "s")

    def test_creating_a_flight_is_voiced(self):
        said = self.say("sockeye", "approach, sockeye, request creation of Apex flight")
        self.assertIn("lead of Apex", said)
        self.assertIn("Apex", self.bridge.flights.names())

    def test_a_flight_nobody_created_is_refused_by_name(self):
        said = self.say("sockeye", "approach, sockeye, joining Bolt")
        self.assertIn("unable", said.lower())
        self.assertIn("Bolt", said)

    def test_nothing_happens_without_a_person(self):
        """`_who` empty means identity did not close. A flight formed from a
        name nobody can corroborate is the ghost problem with a new noun."""
        said = self.say("", "approach, request creation of Apex flight")
        self.assertEqual(said, "")
        self.assertEqual(self.bridge.flights.names(), [])

    def test_an_ordinary_transmission_says_nothing_about_flights(self):
        self.assertEqual(self.say("sockeye", "approach, sockeye, ten miles"), "")
