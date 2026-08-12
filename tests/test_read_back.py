"""The clearance read-back: whose it is, and when it is finished.

Written after the sortie of 12 August, where one defect put this on the air
eight times, the last of them on short final and one AFTER LANDING:

    Sockeye, negative -- say again one zero thousand,
    one two three decimal three, three three five zero.

The pilot read it as three separate faults -- a squawk being re-issued, the
wrong field's departure frequency, and a controller who had lost track of the
flight. It was one function, reciting his departure clearance at him for the
rest of the sortie.

Two rules, and neither was being applied:

    A read-back belongs to the man who ISSUED the instruction. Clearance
    Delivery owns the IFR clearance; a read-back to Batumi Tower is not a
    read-back of it.

    A correction is a CONVERSATION. What he has already said correctly stays
    said, so asking for two missing items and getting exactly those two ends
    the exchange rather than restarting it.
"""

from __future__ import annotations

import unittest

from marshall.atc import agent_atc


class Bridge:
    """Just enough bridge: the cache `_read_back_correct` consults."""

    def __init__(self, plan: dict):
        self.cleared_plan = {"sockeye": plan}


def plan(**over) -> dict:
    """The clearance actually issued at Kobuleti on 12 August."""
    return {"cruise_ft": 10000, "squawk": "3350", "departure_mhz": 123.3,
            "acknowledged": False, "sortie_phase": "clearance", **over}


class TheExchangeCanBeFinished(unittest.TestCase):
    """The loop that had no exit."""

    def test_a_complete_read_back_is_correct(self):
        ok, missed = agent_atc._read_back_correct(
            Bridge(plan()), "sockeye",
            "maintain one zero thousand, one two three decimal three, "
            "squawk three three five zero")
        self.assertIs(ok, True)
        self.assertEqual(missed, [])

    def test_a_partial_read_back_names_only_what_is_missing(self):
        ok, missed = agent_atc._read_back_correct(
            Bridge(plan()), "sockeye", "one two three decimal three, sockeye")
        self.assertIs(ok, False)
        self.assertEqual(sorted(missed),
                         ["one zero thousand", "three three five zero"])

    def test_saying_exactly_what_was_asked_for_ENDS_it(self):
        """The transmission that used to make it worse.

        He is told two elements are missing and reads back exactly those two.
        Judged against the whole clearance that is a FAILURE -- he did not
        repeat the frequency that time -- and the frequency he got right on the
        first call becomes a miss on the second. That is the unwinnable loop,
        and it is why `clearance_ack` was never written.
        """
        b = Bridge(plan())
        ok, missed = agent_atc._read_back_correct(
            b, "sockeye", "one two three decimal three, sockeye")
        self.assertIs(ok, False)
        self.assertEqual(sorted(missed),
                         ["one zero thousand", "three three five zero"])

        ok, missed = agent_atc._read_back_correct(
            b, "sockeye",
            "we expect one zero thousand, one zero minutes after departure, "
            "and we're going to squawk three three five zero, sockeye")
        self.assertIs(ok, True, "what he said the first time is still said")
        self.assertEqual(missed, [])

    def test_the_carried_transcript_is_dropped_once_agreed(self):
        b = Bridge(plan())
        agent_atc._read_back_correct(b, "sockeye", "one two three decimal three")
        agent_atc._read_back_correct(
            b, "sockeye", "one zero thousand, three three five zero")
        self.assertNotIn("sockeye", getattr(b, "read_back_said", {}))

    def test_two_aircraft_do_not_share_a_read_back(self):
        """The accumulator is keyed on the callsign, or one pilot finishes
        another's clearance for him -- which is the whole family of bug this
        codebase keeps producing."""
        b = Bridge(plan())
        b.cleared_plan["lancer38"] = plan()
        agent_atc._read_back_correct(b, "sockeye", "one zero thousand")
        ok, missed = agent_atc._read_back_correct(
            b, "lancer38", "one two three decimal three")
        self.assertIs(ok, False)
        self.assertIn("one zero thousand", missed)


class TheSortieOfTwelveAugust(unittest.TestCase):
    """The real transcripts, through real Whisper, off the flight recorder.

    Kept verbatim on purpose. Every rule above was derived from these two
    transmissions, and a rule that passes a tidied-up version of the evidence
    it came from has not been tested against anything.
    """

    FIRST = ("Roger, we are cleared to Batumi as file, climb, maintain 5,000, "
             "expect 1,000, 1, 0 minutes after departure, frequency is 1, 2, 3 "
             "decimal, 3, and we're going to squawk 3, 3, 5, 0")
    THEN = ("Roger, we expect 1-0,000, 1-0 minutes after departure, and we're "
            "going to squawk 3-3-5-0, sockeye.")

    def test_the_exchange_now_ends_in_agreement(self):
        b = Bridge(plan())

        ok, missed = agent_atc._read_back_correct(b, "sockeye", self.FIRST)
        # The frequency and the squawk ARE there -- as "1, 2, 3 decimal, 3" and
        # "3, 3, 5, 0" -- and used to be reported missing. Only the altitude is
        # genuinely wrong: Whisper wrote "1,000", which is a different number,
        # so asking him to say it again is the correct thing to do.
        self.assertIs(ok, False)
        self.assertEqual(missed, ["one zero thousand"])

        ok, missed = agent_atc._read_back_correct(b, "sockeye", self.THEN)
        self.assertIs(ok, True, "'1-0,000' is one zero thousand")
        self.assertEqual(missed, [])

    def test_the_split_digits_are_the_numbers_he_said(self):
        from marshall.atc import decision

        for said, value in ((self.FIRST, 123.3), (self.FIRST, 3350),
                            (self.THEN, 10000), (self.THEN, 3350)):
            with self.subTest(value=value):
                self.assertTrue(
                    decision._said_number(decision._normalise(said), value))

    def test_a_number_he_did_not_say_is_still_missing(self):
        """The rejoining must not become a machine for finding any number.

        `1 0000 1 0` yields ten thousand because he said it; it must not also
        yield the four thousand nobody mentioned.
        """
        from marshall.atc import decision

        hay = decision._normalise(self.THEN)
        for value in (4000, 5000, 121.9, 1234):
            with self.subTest(value=value):
                self.assertFalse(decision._said_number(hay, value))


class ItBelongsToTheManWhoIssuedIt(unittest.TestCase):
    """Every one of the eight bogus transmissions is one of these."""

    def test_a_taxi_read_back_is_not_a_clearance_read_back(self):
        """On the ramp at Kobuleti, 04:40:40.

            PILOT: Taxi to zero seven, and we will hold short of runway
                   zero seven.
            ATC:   negative -- say again one zero thousand, ...
        """
        ok, missed = agent_atc._read_back_correct(
            Bridge(plan(sortie_phase="taxi")), "sockeye",
            "taxi to zero seven and we will hold short of runway zero seven")
        self.assertIsNone(ok, "Ground did not issue the IFR clearance")
        self.assertEqual(missed, [])

    def test_an_approach_read_back_at_thirty_miles_is_not_judged(self):
        ok, _ = agent_atc._read_back_correct(
            Bridge(plan(sortie_phase="approach")), "sockeye",
            "roger, cleared for the ILS runway one three, sockeye")
        self.assertIsNone(ok)

    def test_nor_is_clearing_the_runway_at_the_OTHER_aerodrome(self):
        """05:05:58, on the ground at Batumi, having landed."""
        ok, _ = agent_atc._read_back_correct(
            Bridge(plan(sortie_phase="landed")), "sockeye",
            "batumi tower, sockeye is clear of the active")
        self.assertIsNone(ok)

    def test_an_agreed_clearance_is_not_still_being_read_back(self):
        ok, _ = agent_atc._read_back_correct(
            Bridge(plan(acknowledged=True)), "sockeye", "anything at all")
        self.assertIsNone(ok)

    def test_no_clearance_means_no_verdict_rather_than_yes(self):
        ok, missed = agent_atc._read_back_correct(
            Bridge({}), "nobody", "cleared to Batumi as filed")
        self.assertIsNone(ok)
        self.assertEqual(missed, [])


if __name__ == "__main__":
    unittest.main()
