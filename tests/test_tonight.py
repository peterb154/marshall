"""The four faults of the 30 July sortie, each caught by a cheap test.

    "This is some basic things you could have tested."

Correct. A pilot spent an evening on the radio finding these one at a time, and
not one of them needed a sortie, a second aeroplane, or anything that was not
already sitting on this machine. They are here so the next change to any of it
fails at the desk.

WHAT THEY HAVE IN COMMON is worth more than the four fixes. Every one is a
GUARD that read the wrong input:

  * the context manager guarded on a class name and met a session written under
    the old one;
  * the handoff guarded on RANGE, and a parked aeroplane at 0.4 nm reads exactly
    like one on short final;
  * the ramp guard was correct and was then overwritten three lines later by a
    branch that never heard of it;
  * and it was reading `on_ground` -- an EVENT flag -- for an aeroplane that
    spawned on the ramp and therefore never generated the event.

In each case the logic was defensible and the input was not what it was assumed
to be. The lesson, written down because it was learned three times in one
evening: when a guard does not fire, print what it is reading before changing
what it does.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import handoff as H
from marshall.core import route as R

BATUMI = (41.609594, 41.600234)


def parked(**kw):
    """The pilot as radar actually reported him: cold-started on the ramp.

    `on_ground` is FALSE, and that is the fixture's whole point. It comes from
    the sim's land/takeoff events, and an aeroplane that spawned parked never
    landed, so nothing ever fired. Thirty-nine feet, zero knots, four hundred
    yards from the field -- and the flag that is supposed to mean "he is down"
    says he is not.
    """
    c = {"name": "Viper 1-4", "label": "362nd_sockeye", "callsign": "",
         "type": "F-16C_50", "category": "airplane", "manned": True,
         "on_ground": False, "lat": 41.60646, "lon": 41.60827,
         "alt_ft": 39.0, "heading": 215.3, "speed_kt": 0.0,
         "coalition": 3, "formation": ""}
    c.update(kw)
    return A.Scope("", contacts=[c], origin=BATUMI)


class TestNobodyIsHandedOffFromTheRamp(unittest.TestCase):
    """"Tower handed me to approach, approach handed me to tower."

    Three separate causes, fixed in three passes, each of which looked like the
    answer. The rows below are one per cause so a regression names itself.
    """

    def setUp(self):
        self.p = R.BATUMI_ASR
        self.scope = parked()
        self.fix = A.radar_fix_by_track(self.scope, "362nd_sockeye")

    def test_radar_alone_says_he_is_down(self):
        """CAUSE 3, and the one that actually kept it alive. `on_ground` is an
        EVENT flag; `is_on_the_ground` combines it with the geometry precisely
        so a caller cannot be fooled by a spawned aircraft. Reading the raw
        field instead is what a fourth caller does."""
        self.assertFalse(self.scope.of("362nd_sockeye")["on_ground"])
        self.assertTrue(A.is_on_the_ground(self.scope, "362nd_sockeye", self.fix))

    def test_the_range_rule_alone_would_hand_him_over(self):
        """CAUSE 1. Nothing wrong with the rule -- at 0.4 nm an arrival IS
        Tower's. It simply cannot tell an arrival from a parked jet.

        SHOWN AGAINST THE RULE ITSELF now that `handoff_from` is gone [#51].
        The point survives the move and is worth keeping: fed only a distance,
        the table hands a parked aeroplane to Tower. What saves it is
        `on_ground`, which is why the ramp guard is a FACT the rules are given
        rather than an `if` somewhere upstream.
        """
        import dataclasses
        me = R.station_for("approach", field="Batumi")
        # A distance and a direction, with the ground fact withheld.
        ils = dataclasses.replace(self.p, guidance="intercept")
        v = H.due(ils, me, H.State(on_ground=False,
                                   range_nm=self.fix.range_nm, inbound=True))
        self.assertIsNotNone(v, "the distance alone really would hand him over")
        self.assertEqual(v.station.role, "tower")

    def test_and_the_ground_fact_is_what_stops_it(self):
        """The same aeroplane, with the truth included."""
        me = R.station_for("approach", field="Batumi")
        st = A._handoff_state(self.scope, "362nd_sockeye", self.fix)
        self.assertTrue(st.on_ground, "the ramp fact never reached the rules")
        v = H.due(self.p, me, st)
        # On the ground under a radar controller is corrected TO Tower -- he has
        # landed or never left. What must not happen is a departure being sent
        # away from the man who gives him his clearance.
        self.assertTrue(v is None or v.station.role == "tower")

    def freq(self, role):
        return R.station_for(role).freq_mhz

    def test_a_departure_request_is_not_leaving_the_airspace(self):
        """CAUSE 2. The ramp guard set the handoff to None and the "is he on his
        way out?" branch immediately put it back, because a departure request is
        obviously yes. Two correct-looking pieces cancelling each other, which
        is why the transmit guard then let it through -- by that point the
        handoff really had been authorised."""
        self.assertTrue(A.is_on_the_ground(self.scope, "362nd_sockeye", self.fix))

    def test_tower_hands_off_to_nobody_anyway(self):
        """The half that was always right: an arrival at Tower is the end of
        the line. His only rule is outbound, and a parked jet is not that."""
        me = R.station_for("tower", field="Batumi")
        st = A._handoff_state(self.scope, "362nd_sockeye", self.fix)
        self.assertFalse(H.due(self.p, me, st))


class TestTheAgentMayNotInventAHandoff(unittest.TestCase):
    """Told plainly not to, in the rules, it did it on the radio the same
    evening. A prompt is guidance; where a guarantee is needed the bridge has to
    enforce it -- the same rule that keeps a model out of separation."""

    LOOP = ("Sockeye, Batumi Tower, contact Batumi Approach one two four "
            "decimal zero for departure, good day.")

    def test_an_unauthorised_handoff_is_removed(self):
        out, gone = A.strip_unauthorised_handoff(self.LOOP, None,
                                                 keep_him="Sockeye, Batumi Tower, go ahead.")
        self.assertNotIn("contact Batumi Approach", out)
        self.assertIn("Batumi Approach", gone)

    def test_it_never_leaves_him_with_silence(self):
        """The commonest shape is a reply that is ONLY the handoff, so stripping
        empties it. Returning the original there would make the guard a no-op in
        exactly the case it exists for."""
        out, _ = A.strip_unauthorised_handoff(
            self.LOOP, None, keep_him="Sockeye, Batumi Tower, go ahead.")
        self.assertTrue(out.strip())
        self.assertIn("go ahead", out)

    def test_an_authorised_handoff_passes_untouched(self):
        tower = R.station_for("tower")
        out, gone = A.strip_unauthorised_handoff(self.LOOP, tower)
        self.assertEqual(out, self.LOOP)
        self.assertEqual(gone, "")

    def test_naming_the_frequency_he_is_ON_is_not_a_handoff(self):
        """"this is Batumi Tower, one one eight decimal zero" corrects which
        button he is holding. Stripping it would delete the correction."""
        text = ("Falcon one one, I do not have you on the board, you are "
                "Sockeye, use that callsign. Sockeye, this is Batumi Tower, "
                "one one eight decimal zero.")
        out, gone = A.strip_unauthorised_handoff(text, None)
        self.assertEqual(out, text)
        self.assertEqual(gone, "")


class TestEngineeringAnswersToHisName(unittest.TestCase):
    """Missed twice in one evening, in both directions.

    The pattern was a list of the ways somebody might summon him -- "come up",
    "are you there", "radio check" -- rather than the rule that they addressed
    him. Each gap reads from the cockpit as a dead channel, which is the one
    thing an engineering channel must never be.
    """

    def call(self, said):
        return bool(A._ENG_CALL.search(said))

    def test_the_forms_that_were_missed(self):
        for said in ("Engineering, Sakai.",          # first miss, 30 July
                     "Engineering, Sockeye",
                     "Sockeye to engineering.",      # second miss, same evening
                     "engineering, N2a failed"):
            with self.subTest(said=said):
                self.assertTrue(self.call(said), "a dead channel")

    def test_the_forms_that_already_worked(self):
        for said in ("Engineering?", "engineering radio check",
                     "engineering, come up"):
            with self.subTest(said=said):
                self.assertTrue(self.call(said))

    def test_talking_ABOUT_him_does_not_summon_him(self):
        for said in ("engineering said the vectors are fixed",
                     "engineering",
                     "Batumi Approach, Sockeye, checking in",
                     "Sockeye to Batumi Tower"):
            with self.subTest(said=said):
                self.assertFalse(self.call(said))


class TestASessionFromAnOlderManagerDoesNotSilenceATC(unittest.TestCase):
    """The one that cost the evening, and the cheapest of the four to have
    caught.

    Introducing `RadioContext` renamed the conversation manager. `strands`
    validates a restored session's `__name__` against the class and raises if
    they differ -- sound, and fatal: the live `hooks` session predated the
    rename, so every `/atc` call answered 500 and the agent never ran. One reply
    on check-in and nothing afterwards, on a frequency with a pilot on it.

    Every dry run passed throughout, because a dry run mints a NEW session id
    and a new session has nothing to restore.
    """

    def manager(self):
        from marshall.atc.agent.context import RadioContext
        return RadioContext()

    def setUp(self):
        try:
            self.m = self.manager()
        except Exception as e:              # strands absent -- the shim path
            self.skipTest(f"strands not importable here: {e}")

    def test_a_state_from_the_old_class_is_survivable(self):
        got = self.m.restore_from_session(
            {"__name__": "SlidingWindowConversationManager",
             "removed_message_count": 7})
        self.assertIsNone(got)
        self.assertEqual(self.m.removed_message_count, 7)

    def test_a_state_from_nowhere_at_all_is_survivable(self):
        for state in ({}, None, {"__name__": "Something Else"}):
            with self.subTest(state=state):
                self.manager().restore_from_session(state)

    def test_our_own_state_still_restores_normally(self):
        self.m.restore_from_session(
            {"__name__": "RadioContext", "removed_message_count": 3})
        self.assertEqual(self.m.removed_message_count, 3)


if __name__ == "__main__":
    unittest.main()
