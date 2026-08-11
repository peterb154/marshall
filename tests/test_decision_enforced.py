"""A fact the engine decided and the agent did not say now reaches the air.

    #79 [SEAM-1]

`decision.verify` has been able to answer "did he actually say it?" since the
module was written, and until now the answer changed nothing. It printed
`NOT VOICED` and the transmission went out regardless. That is the shape this
repo keeps finding: a correct mechanism whose output nothing acts on.

THE EVIDENCE IS TWO REAL TRANSMISSIONS, out of the flight recorder rather than
imagined for this file:

    engine: Sockeye, runway one three, cleared for take-off, wind zero nine
            zero at six.
    air:    Sockeye, roger.

    engine: Take-off is Tower's, contact Kobuleti Tower one three three
            decimal zero.
    air:    sockeye, Kobuleti Ground, go ahead.

An aeroplane cleared for take-off and never told, and a pilot refused a
clearance and never redirected -- the second one recorded at 20:52 on 9 August,
after every other fix made that day. Both replayed below.

WHY THE VERIFIER GOT STRICTER FIRST, and why half this file is about that: while
`verify` was advisory a false positive cost a misleading log line. Now it costs
an extra sentence on the radio restating something the pilot already has. The
canonical spelling alone flagged four innocent replies -- a hyphen, digits,
grouped digits, and a frequency written to one decimal instead of three. Every
one of those is a controller saying the right thing.
"""

import unittest

from marshall.atc import decision as D


class TheVerifierMustNotCryWolf(unittest.TestCase):
    """A false positive now costs a transmission, so these are the guard."""

    RWY = D.Decision(kind="cleared_takeoff", to="Sockeye 1-1", runway="13")
    ALT = D.Decision(kind="hold", to="Sockeye 1-1", altitude_ft=2000)
    HDG = D.Decision(kind="vector", to="Sockeye 1-1", heading_deg=130)
    REF = D.Decision(kind="refuse", to="Sockeye 1-1", role="tower",
                     station="Kobuleti Tower", frequency_mhz=133.0)

    def ok(self, d, said):
        self.assertEqual(D.verify(d, said), [],
                         f"said it perfectly well, but was reported missing: {said!r}")

    def missing(self, d, said):
        self.assertTrue(D.verify(d, said),
                        f"the fact was NOT spoken and went unnoticed: {said!r}")

    def test_spoken_form(self):
        self.ok(self.RWY, "Sockeye, runway one three, cleared for take-off.")

    def test_a_hyphen_is_not_a_missing_fact(self):
        self.ok(self.RWY, "Sockeye, runway one-three, cleared for take-off.")

    def test_digits_are_not_a_missing_fact(self):
        self.ok(self.RWY, "Sockeye, runway 13, cleared for take-off.")

    def test_grouped_digits_are_not_a_missing_fact(self):
        self.ok(self.ALT, "Sockeye, maintain 2,000 feet.")

    def test_a_frequency_to_one_decimal_is_the_same_frequency(self):
        # 133, 133.0 and 133.000 are one number, and no amount of string
        # matching says so -- which is why the numeric forms compare by value.
        for form in ("133", "133.0", "133.000"):
            self.ok(self.REF, f"contact Kobuleti Tower {form}")

    def test_a_trailing_full_stop_is_punctuation(self):
        # The first version of this check treated the sentence-ending period as
        # part of the last word and reported a perfect transmission as a miss.
        self.ok(self.REF, "Contact Kobuleti Tower one three three decimal zero.")

    def test_a_station_name_may_be_followed_by_a_frequency(self):
        # A station is a NAME. Holding it to the numeric rule -- next word must
        # not be a number word -- made "Kobuleti Tower one three three decimal
        # zero" read as a missing station.
        self.ok(D.Decision(kind="handoff", to="S", station="Kobuleti Tower"),
                "contact Kobuleti Tower one three three decimal zero")


class TheVerifierMustStillCatchIt(unittest.TestCase):
    """The other direction. Missing a real miss is the worse failure: the pilot
    never gets the fact and nothing knows."""

    RWY = TheVerifierMustNotCryWolf.RWY
    REF = TheVerifierMustNotCryWolf.REF
    HDG = TheVerifierMustNotCryWolf.HDG

    def test_roger_is_not_a_takeoff_clearance(self):
        self.assertEqual(D.verify(self.RWY, "Sockeye, roger."), ["one three"])

    def test_a_runway_is_not_satisfied_by_a_frequency_containing_it(self):
        # "one three" sits inside "one three three decimal zero". Accepting that
        # would confirm the wrong fact entirely.
        self.assertTrue(
            D.verify(self.RWY, "Sockeye, contact Tower one three three decimal zero."))

    def test_a_longer_number_is_not_the_number(self):
        self.assertTrue(D.verify(self.HDG, "turn left heading one three zero five"))

    def test_go_ahead_is_not_a_redirect(self):
        missed = D.verify(self.REF, "sockeye, Kobuleti Ground, go ahead.")
        self.assertIn("Kobuleti Tower", missed)
        self.assertIn("one three three decimal zero", missed)


class TheRecordedFailuresAreRepaired(unittest.TestCase):
    """The two transmissions from the flight recorder, replayed.

    These are the whole reason for the issue, so they are asserted as
    themselves rather than paraphrased into something tidier.
    """

    def test_cleared_for_takeoff_and_told_only_roger(self):
        d = D.Decision(kind="cleared_takeoff", to="Sockeye 1-1", runway="13")
        said = "Sockeye, roger."
        add = D.repair(d, said)
        self.assertTrue(add, "nothing was added, so the pilot still is not cleared")
        self.assertIn("one three", add)
        # And the repaired transmission passes the check that failed.
        self.assertEqual(D.verify(d, f"{said} {add}"), [])

    def test_refused_a_clearance_and_never_redirected(self):
        # 20:52 on 9 August, after every other fix that day. Ground correctly
        # refused a take-off request and named Tower; the agent said "go ahead".
        d = D.Decision(kind="refuse", to="Sockeye 1-1", role="tower",
                       station="Kobuleti Tower", frequency_mhz=133.0)
        said = "sockeye, Kobuleti Ground, go ahead."
        add = D.repair(d, said)
        self.assertTrue(add, "the pilot was left on the wrong frequency")
        self.assertIn("Kobuleti Tower", add)
        self.assertEqual(D.verify(d, f"{said} {add}"), [])

    def test_a_reply_that_said_everything_is_left_alone(self):
        d = D.Decision(kind="cleared_takeoff", to="Sockeye 1-1", runway="13")
        self.assertEqual(
            D.repair(d, "Sockeye, runway one three, cleared for take-off."), "",
            "a correct transmission must not be added to -- that is the "
            "frequency-filling this is supposed to prevent")

    def test_an_unrenderable_decision_adds_nothing(self):
        # `say_again` has no phrasebook rendering. Saying nothing is correct;
        # inventing words for a decision we cannot phrase is what the engine
        # must never do.
        d = D.Decision(kind="say_again", to="Sockeye 1-1")
        self.assertEqual(D.repair(d, "..."), "")


class TheBridgeAppendsRatherThanReplaces(unittest.TestCase):
    """Manner is the half the agent is good at; the fact is the half it is not."""

    def test_the_transmit_path_repairs_before_it_speaks(self):
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc)
        i_fix = src.index("_decision.repair(")
        i_frames = src.index("_frames = voice_for(")
        self.assertLess(i_fix, i_frames,
                        "the repair must happen before the words are rendered, "
                        "or it never reaches the radio")

    def test_it_does_not_substitute_the_reply(self):
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc)
        self.assertIn('reply = f"{reply.strip().rstrip', src,
                      "the agent's own words must survive the repair")


if __name__ == "__main__":
    unittest.main()


class ASuppressedDecisionCannotComeBackThroughTheRepair(unittest.TestCase):
    """The two fixes met, and one undid the other. #80.

    `reconcile` exists because a pilot established on the final approach course
    at ten miles was told, in ONE transmission, that he was on final AND to
    climb to five thousand and hold. It suppresses the holding clearance when
    radar shows him established.

    It suppressed the WORDS. Since #79 the bridge repairs any decided fact the
    agent did not voice -- reading `bridge.decided`, which still held the hold.
    So the suppressed clearance came straight back on the air, through the door
    built to fix a different problem. Caught before it flew, by asking what the
    two changes do together rather than what each does alone.

    A guard that edits prose while the structured decision survives is not a
    guard. `reconcile` owns both halves now.
    """

    def setUp(self):
        from marshall.atc import agent_atc
        self.A = agent_atc
        self.hold = D.Decision(kind="hold", to="Sockeye 1-1", altitude_ft=5000)
        self.words = "Sockeye, hold at present position, maintain five thousand."
        self.vec = "ASR: vectoring, eight miles. Fly heading 130."

    class _OnFinal:
        phase, established = "final", True

    class _Missed:
        phase, established = "missed", False

    class _OutOfPosition:
        phase, established = "downwind", False

    def test_established_on_final_keeps_neither_the_words_nor_the_decision(self):
        d, _s, _v, dropped, kept = self.A.reconcile(
            self.words, "", self.vec, self._OnFinal(), [self.hold])
        self.assertEqual(d, "")
        self.assertIn("suppressed", dropped)
        self.assertEqual(kept, [],
                         "the hold survived as a decision and #79 would put it "
                         "back on the air -- two altitudes in one transmission")

    def test_the_missed_approach_takes_the_decision_too(self):
        _d, _s, _v, dropped, kept = self.A.reconcile(
            self.words, "", self.vec, self._Missed(), [self.hold])
        self.assertIn("missed", dropped)
        self.assertEqual(kept, [])

    def test_suppressing_the_VECTOR_keeps_the_hold(self):
        # The other direction: he is out of position and told to wait, so the
        # holding clearance is the instruction and must reach him.
        d, _s, v, dropped, kept = self.A.reconcile(
            self.words, "", self.vec, self._OutOfPosition(), [self.hold])
        self.assertTrue(d)
        self.assertEqual(v, "")
        self.assertIn("two altitudes", dropped)
        self.assertEqual(len(kept), 1, "the hold he must actually fly was lost")

    def test_other_decisions_are_untouched_by_a_hold_suppression(self):
        # Only the holding decision goes. A landing clearance in the same turn
        # is a different fact and still owed.
        land = D.Decision(kind="cleared_land", to="Sockeye 1-1", runway="13")
        _d, _s, _v, _dropped, kept = self.A.reconcile(
            self.words, "", self.vec, self._OnFinal(), [self.hold, land])
        self.assertEqual([k.kind for k in kept], ["cleared_land"])


class ReconcileReadsTypesNotProse(unittest.TestCase):
    """`"hold" in directive.lower()` decided which authority owned an aeroplane.

    It worked only because `controller.py` happened to write that word. A
    rephrasing there -- "remain at present position", "continue to orbit" --
    silently changed a separation decision two modules away, and no test could
    see the connection because the two files share nothing but a substring.
    """

    def setUp(self):
        from marshall.atc import agent_atc
        self.A = agent_atc

    class _OnFinal:
        phase, established = "final", True

    def test_a_hold_phrased_without_the_word_is_still_a_hold(self):
        # THE POINT. These words contain no "hold" at all.
        said = "Sockeye, remain at present position, maintain five thousand."
        d = D.Decision(kind="hold", to="Sockeye 1-1", altitude_ft=5000)
        out, _s, _v, dropped, kept = self.A.reconcile(
            said, "", "ASR: eight miles.", self._OnFinal(), [d])
        self.assertEqual(out, "", "the rephrased hold was not recognised")
        self.assertIn("suppressed", dropped)
        self.assertEqual(kept, [])

    def test_a_sentence_mentioning_holding_short_is_not_a_hold(self):
        # "hold short" is a GROUND instruction and has nothing to do with the
        # stack. The substring test could not tell them apart.
        said = "Sockeye, taxi to runway one three, hold short of runway one three."
        d = D.Decision(kind="taxi", to="Sockeye 1-1", runway="13")
        out, _s, v, _dropped, kept = self.A.reconcile(
            said, "", "ASR: eight miles.", self._OnFinal(), [d])
        self.assertEqual(out, said, "a taxi clearance was suppressed as a hold")
        self.assertEqual(len(kept), 1)
        self.assertTrue(v)

    def test_continue_hold_counts(self):
        d = D.Decision(kind="continue_hold", to="Sockeye 1-1")
        out, _s, _v, _dropped, kept = self.A.reconcile(
            "Sockeye, continue holding.", "", "ASR: eight miles.",
            self._OnFinal(), [d])
        self.assertEqual(out, "")
        self.assertEqual(kept, [])

    def test_with_no_decisions_it_still_falls_back_to_the_words(self):
        # Six of thirty-two `say` calls carry a decision today. Removing the
        # fallback would silently stop suppressing holds for the rest, which is
        # a worse bug than the one being fixed. It goes when they all carry one.
        out, _s, _v, dropped, _kept = self.A.reconcile(
            "Sockeye, hold at present position, maintain five thousand.", "",
            "ASR: eight miles.", self._OnFinal(), [])
        self.assertEqual(out, "")
        self.assertIn("suppressed", dropped)


class TheVectorIsVerifiedButNeverRepeated(unittest.TestCase):
    """The MVA altitude went missing, and nothing could see it.

        ASR: vectoring, 19 miles. Turn left. Fly heading 225, maintain 8000
        ATC: Sockeye, Batumi Approach, roger, level five thousand five hundred

    The minimum vectoring altitude on that radial at nineteen miles is eight
    thousand feet. He was left at five thousand five hundred and worked it out
    himself:

        "if I were to continue on heading 232, 5500 ... north east of Batumi,
         I would hit a mountain"

    The engine surveyed that terrain cell by cell precisely so a controller
    could not assign an altitude into it. The number was correct and was
    dropped between deciding it and saying it, because a vector crossed the seam
    as PROSE and only a `Decision` is verified.

    IT IS NOT REPAIRED, THOUGH, and that distinction is the point. The engine
    transmits vectors itself, on its own schedule, rendered from this same
    phrasebook -- so appending one to the agent's reply would not restore a lost
    fact, it would say the same thing twice from two transmissions. A pilot
    reported exactly that on the same sortie: "I'm getting redundant
    instructions", "he's stepping on me a couple of times".
    """

    def vector(self):
        return D.Decision(kind="vector", to="Sockeye 1-1",
                          heading_deg=225, altitude_ft=8000)

    def test_the_dropped_mva_altitude_is_caught(self):
        said = "Sockeye, Batumi Approach, roger, level five thousand five hundred."
        missed = D.verify(self.vector(), said)
        self.assertIn("eight thousand", missed)

    def test_a_reply_that_voices_it_passes(self):
        self.assertEqual(
            D.verify(self.vector(),
                     "Sockeye, turn left heading two two five, climb and "
                     "maintain eight thousand."), [])

    def test_it_is_never_appended(self):
        said = "Sockeye, radar contact."
        self.assertTrue(D.verify(self.vector(), said), "the premise: it is missing")
        self.assertEqual(D.repair(self.vector(), said), "",
                         "a repaired vector is a duplicated transmission, not a "
                         "restored fact")

    def test_the_exemption_is_a_named_set_not_a_special_case(self):
        self.assertIn("vector", D.SPOKEN_BY_THE_ENGINE)

    def test_everything_else_is_still_repaired(self):
        # The exemption must not quietly grow into "nothing is repaired".
        d = D.Decision(kind="cleared_takeoff", to="Sockeye 1-1", runway="13")
        self.assertTrue(D.repair(d, "Sockeye, roger."))
