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
