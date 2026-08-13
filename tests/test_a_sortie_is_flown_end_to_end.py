"""What a whole sortie found that eight separate rungs could not. [#134 #135]

`tools/ghost_flight.py --sortie` flew Kobuleti to Batumi on 13 August -- the
first time one aeroplane, under one callsign, had climbed every rung of the
ladder in one run. Two of the three things it found were invisible to every
test in this suite, and both for the same reason: they live in the JOIN between
two rungs, and every fixture until now stood on one rung at a time.

    R1  Kobuleti Clearance, Marlin31, request IFR clearance to Batumi, Domino
    ATC cleared to Batumi as filed, maintain five thousand, expect one zero
        thousand, departure frequency one two three decimal three, squawk seven
        one four six, read back
    R2  (a deliberately incomplete read-back)
    ATC negative -- say again one zero thousand, seven one four six
    R3  Kobuleti Ground, Marlin31, ready to taxi
    ATC Marlin three one, taxi to runway zero seven, hold short          <-- #135
    R4  the departure frequency is one two three decimal THREE, and we're going
        to squawk seven one four six                                (as spoken)
        ...the departure frequency is one two three decimal TREE         (heard)
    ATC negative -- say again one zero thousand, one two three decimal three
                                                                        <-- the
        frequency he had just read back correctly, asked for again

The first is #135's refusal being unreachable in flight: `clearance_agreed` was
written by `hydrate` (once, at startup) and by `clearance_read_back` (only ever
TRUE), so nothing in a live sortie could ever set it False and the guard was
dead code that the unit tests kept green by assigning the field themselves.

The second is Whisper: a radio says "tree" for three, and a read-back that was
word-perfect matched neither the spoken form nor the digit rejoin. That is the
same fault as #134's split digits arriving through a different door -- and the
same consequence, a request the pilot cannot satisfy.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import ghost_flight as G

from marshall.atc import agent_atc, controller as atc
from marshall.atc import decision as D
from marshall.core import route as R
from marshall.core import say


class WhisperSaysTreeAndMeansThree(unittest.TestCase):
    """The ICAO spellings are the same digits, and a verifier must know it."""

    def freq(self, mhz: float = 123.3) -> D.Decision:
        return D.Decision(kind="clearance", to="Marlin 3-1", frequency_mhz=mhz)

    def test_the_frequency_he_read_back_as_tree(self):
        """Measured, on the air, on the run that prompted this file."""
        said = ("Marlin31, the departure frequency is one two three decimal "
                "tree, and we're going to squawk seven one four six.")
        self.assertEqual([], D.verify(self.freq(), said))

    def test_and_the_ordinary_spelling_still_works(self):
        self.assertEqual([], D.verify(
            self.freq(), "the departure frequency is one two three decimal three"))

    def test_niner_fower_and_fife(self):
        for mhz, spoken in ((129.4, "one two niner decimal fower"),
                            (125.5, "one two fife decimal fife")):
            with self.subTest(mhz=mhz):
                self.assertEqual([], D.verify(self.freq(mhz), spoken))

    def test_an_altitude_said_the_radio_way(self):
        d = D.Decision(kind="clearance", to="X", altitude_ft=9000)
        self.assertEqual([], D.verify(d, "maintain niner thousand"))

    def test_a_squawk_said_the_radio_way(self):
        d = D.Decision(kind="clearance", to="X", squawk="3346")
        self.assertEqual([], D.verify(d, "squawking tree tree fower six"))

    def test_a_number_that_really_is_missing_is_still_missing(self):
        """The bias stays where `_said_words` put it: reporting a fact spoken
        when it was not is the expensive direction."""
        d = D.Decision(kind="clearance", to="X", altitude_ft=10000,
                       squawk="7146")
        self.assertEqual([say.spell_alt(10000)],
                         D.verify(d, "squawk seven one fower six"))


class OneTransmissionInThreeNotations(unittest.TestCase):
    """Whisper is transcribing a man, not a protocol. [#134]

    The 13 August read-back, verbatim off the recorder:

        the departure frequency is 1-2-3 decimal tree, and we're going to
        squawk 5-3-2-5

    Every character of both numbers is there, in three spellings at once, and
    neither matched: `1 2 3` is not the word form, and the digit run stops at
    `decimal` because a WORD follows it, so the slice ends with a trailing point
    and is thrown away. He was asked to say again a frequency he had just said.
    """

    def clearance(self) -> D.Decision:
        return D.Decision(kind="clearance", to="Marlin 4-2",
                          frequency_mhz=123.3, squawk="5325")

    def test_the_mixed_read_back_is_accepted(self):
        self.assertEqual([], D.verify(
            self.clearance(),
            "Marlin42, the departure frequency is 1-2-3 decimal tree, and "
            "we're going to squawk 5-3-2-5."))

    def test_the_12_august_split_digits_still_work(self):
        """Verbatim, from `TheSortieOfTwelveAugust` in tests/test_read_back.py.

        The altitude is genuinely wrong in it -- Whisper wrote "1,000", which is
        a different number -- and asking for that one again is the controller
        doing his job. What must survive this change is the other two.
        """
        d = D.Decision(kind="clearance", to="X", altitude_ft=10000,
                       frequency_mhz=123.3, squawk="3350")
        self.assertEqual(
            [say.spell_alt(10000)],
            D.verify(d, "Roger, we are cleared to Batumi as file, climb, "
                        "maintain 5,000, expect 1,000, 1, 0 minutes after "
                        "departure, frequency is 1, 2, 3 decimal, 3, and we're "
                        "going to squawk 3, 3, 5, 0"))

    def test_a_run_of_WORDS_alone_is_still_not_rejoined(self):
        """THE LIMIT, and it is the guard rather than fussiness. Rejoining a
        spoken number would hand it every sub-number it contains -- so a runway
        would be satisfied by a frequency, which is the confusion `_said_words`
        exists to refuse. Held by `TheVerifierMustStillCatchIt` too; held here
        because this is the change that nearly broke it."""
        rwy = D.Decision(kind="cleared_land", to="X", runway="13")
        self.assertEqual(["one three"], D.verify(
            rwy, "Sockeye, contact Tower one three three decimal zero."))

    def test_and_the_runway_when_it_really_was_said(self):
        rwy = D.Decision(kind="cleared_land", to="X", runway="13")
        self.assertEqual([], D.verify(rwy, "cleared to land runway one three"))


class TheAckIsWrittenForTHISMissionsFlight(unittest.TestCase):
    """`clearance_ack` was never recorded, on any sortie, ever. [#134 #135]

    `_flight_id_of` asked `/flights` with no mission, so it walked the rows of a
    mission called "default" -- which a real sortie is not -- found nobody,
    returned 0, and `_ack_the_clearance` gave up without a word. Invisible until
    the engine started reading the board every turn, at which point a pilot
    whose read-back had just been accepted was refused taxi twice:

        ATC  Marlin four two, readback correct, contact Kobuleti Ground
        ATC  Marlin four two, your IFR clearance has STILL not been read back
    """

    def asked(self, mission: str) -> str:
        got = {}

        def _get(url, *a, **k):
            got["url"] = url
            return {"flights": []}

        old_get, old_mission = agent_atc._get_json, agent_atc.MISSION
        agent_atc._get_json, agent_atc.MISSION = _get, mission
        try:
            agent_atc._flight_id_of("Marlin 4-2")
        finally:
            agent_atc._get_json, agent_atc.MISSION = old_get, old_mission
        return got.get("url", "")

    def test_the_mission_is_in_the_query(self):
        url = self.asked("362nd-Blind-Flying-1444@1786509383")
        self.assertIn("mission=", url)
        self.assertIn("362nd-Blind-Flying-1444", url)

    def test_and_it_is_escaped_because_a_sortie_key_has_an_at_in_it(self):
        self.assertNotIn("@", self.asked("a b@1"))


class ARefusalDoesNotMoveHimOn(unittest.TestCase):
    """#135, and #82's shape again: the board advanced on a call that failed.

    `request_taxi` writes `sortie_phase = "taxi"` before it decides anything.
    That is deliberate for a man on the wrong frequency -- he IS ready to taxi
    -- and wrong for one who has just been refused, because THE PHASE IS THE
    HANDOFF: `handoff.due` owns a geometry-less phase outright, so `taxi` means
    Ground has him. Measured on the first end-to-end sortie, in consecutive
    transmissions:

        ATC  your IFR clearance has not been read back, contact Kobuleti
             Clearance one two five decimal one
        ATC  readback correct, contact Kobuleti Ground one two one decimal eight

    A refusal that changes nothing is #135's own complaint, back again.
    """

    def refused(self):
        from marshall.atc import handoff as H
        ctl = atc.Controller(profile=R.BATUMI_ASR)
        me = R.BATUMI_ASR.station_for("ground", field="Kobuleti")
        ctl._me = me
        ctl.get("Sockeye")
        ctl.note_clearance_agreed("Sockeye", False)
        ctl.request_taxi("Sockeye")
        ac = ctl.aircraft[ctl._resolve("Sockeye")]
        return ctl, me, ac, H

    def test_he_stays_on_clearances_rung(self):
        _ctl, _me, ac, _H = self.refused()
        self.assertEqual("clearance", ac.sortie_phase)

    def test_so_nothing_hands_him_to_ground(self):
        _ctl, me, ac, H = self.refused()
        v = H.due(R.BATUMI_ASR, me, H.State(True, 0.1, False,
                                            phase=ac.sortie_phase))
        got = getattr(getattr(v, "station", None), "name", "")
        self.assertNotEqual("Kobuleti Ground", got,
                            "handed to Ground in the same breath as refusing him")

    def test_and_an_agreed_clearance_still_moves_him(self):
        ctl = atc.Controller(profile=R.BATUMI_ASR)
        ctl._me = R.BATUMI_ASR.station_for("ground", field="Kobuleti")
        ctl.get("Sockeye")
        ctl.note_clearance_agreed("Sockeye", True)
        ctl.request_taxi("Sockeye")
        self.assertEqual("taxi",
                         ctl.aircraft[ctl._resolve("Sockeye")].sortie_phase)


class GroundCanActuallyRefuse(unittest.TestCase):
    """#135 -- and the engine has to be TOLD, because it never issued it.

    `GroundDoesNotMoveAnAircraftOnAnUnagreedClearance` in
    tests/test_ground_procedure.py holds the refusal itself and passed
    throughout, because it sets `clearance_agreed = False` by hand. This holds
    the half that was missing: something in a live turn has to write it.
    """

    def ground(self):
        ctl = atc.Controller(profile=R.BATUMI_ASR)
        ctl._me = R.BATUMI_ASR.station_for("ground", field="Kobuleti")
        return ctl

    def test_the_engine_takes_the_verdict_from_the_board(self):
        ctl = self.ground()
        ctl.get("Sockeye")
        ctl.note_clearance_agreed("Sockeye", False)
        ctl.request_taxi("Sockeye")
        said = " ".join(t.text for t in ctl.out)
        self.assertIn("has not been read back", said)
        self.assertNotIn("taxi to runway", said.lower())

    def test_and_an_agreed_one_lets_him_go(self):
        ctl = self.ground()
        ctl.get("Sockeye")
        ctl.note_clearance_agreed("Sockeye", True)
        ctl.request_taxi("Sockeye")
        self.assertIn("taxi to runway",
                      " ".join(t.text for t in ctl.out).lower())

    def test_an_aeroplane_nobody_has_heard_of_is_not_an_error(self):
        """A guard that fires on missing information silences a controller the
        first time the board is quiet."""
        ctl = self.ground()
        ctl.note_clearance_agreed("Nobody", False)      # no such aircraft
        ctl.request_taxi("Sockeye")
        self.assertIn("taxi to runway",
                      " ".join(t.text for t in ctl.out).lower())

    def test_the_bridge_writes_it_every_turn(self):
        """Beside the cleared LEVEL, off the same board read.

        A source assertion, deliberately, and the same idiom
        `test_phases_derive` uses for `phase_now`: what makes the refusal
        reachable is that this is written on every turn from the durable row,
        rather than at some moment somebody has to remember to catch. A version
        that only wrote it on the read-back turn would pass every behavioural
        test here and still be the bug.
        """
        src = inspect.getsource(agent_atc.separation_context)
        self.assertIn("note_clearance_agreed", src)
        self.assertLess(src.index("_cleared_plan_now(known)"),
                        src.index("note_clearance_agreed"),
                        "the verdict must come from the board that was just read")


class TheFixtureReadsItsOwnAeroplane(unittest.TestCase):
    """The harness's own faults, found by the first run of it.

    Both are the two-aerodrome shape again: an answer that is real, plausible,
    and about somebody else.
    """

    def board(self, *rows) -> list[dict]:
        return [{"kind": "board", "t": 1.0, "board": list(rows)}]

    def test_the_phase_is_HIS_phase(self):
        """Two arrivals from an earlier run were still on the board, so the
        first row belonged to a man who had already landed -- and a ghost that
        had not left the ramp was reported `landed` at every rung."""
        ev = self.board({"callsign": "Ironside 9-7", "track": "Ironside97",
                         "sortie_phase": "landed"},
                        {"callsign": "Marlin 3-1", "track": "Marlin31",
                         "sortie_phase": "clearance"})
        self.assertEqual("clearance", G.board_phase(ev, "Marlin31"))

    def test_by_callsign_when_radar_has_not_bound_him_yet(self):
        ev = self.board({"callsign": "Marlin 3-1", "track": "",
                         "sortie_phase": "taxi"})
        self.assertEqual("taxi", G.board_phase(ev, "Marlin31"))

    def test_and_nothing_for_an_aeroplane_that_is_not_there(self):
        ev = self.board({"callsign": "Ironside 9-7", "track": "Ironside97",
                         "sortie_phase": "landed"})
        self.assertEqual("", G.board_phase(ev, "Marlin31"))


class TheLadderKnowsWhichTower(unittest.TestCase):
    """A role is only unique within an aerodrome, and the sortie visits two.

    Judged on roles, `ground -> tower` is the second rung of a departure AND the
    reverse of the last rung of an arrival: same two words, opposite events, and
    the wrong one is a pilot sent back to a controller who has finished with
    him. So the sequence is built from station NAMES.
    """

    class Theatre:
        departure, arrival = "Kobuleti", "Batumi"
        stations = R.BATUMI_ASR.stations

    def setUp(self):
        self.th = self.Theatre()

    def handoff(self, text: str, to: str) -> dict:
        return {"kind": "atc/handoff", "t": 1.0, "to": to, "text": text}

    def test_the_published_order_is_the_station_list(self):
        self.assertEqual(
            ["Kobuleti Ground", "Kobuleti Tower", "Kobuleti Departure",
             "Georgia Center", "Batumi Approach", "Batumi Tower",
             "Batumi Ground"],
            G.ladder_order(self.th))

    def test_a_whole_sortie_runs_forwards(self):
        ev = [self.handoff("contact Kobuleti Ground one two one decimal eight",
                           "ground"),
              self.handoff("contact Kobuleti Tower one three three decimal zero",
                           "tower"),
              self.handoff("contact Kobuleti Departure one two three decimal "
                           "three", "departure"),
              self.handoff("contact Georgia Center one three nine decimal zero",
                           "center"),
              self.handoff("contact Batumi Approach one two four decimal four "
                           "two five", "approach"),
              self.handoff("contact Batumi Tower one one eight decimal six",
                           "tower"),
              self.handoff("contact Batumi Ground one two one decimal nine",
                           "ground")]
        ok, why = G.the_ladder_ran_forwards(ev, self.th)
        self.assertTrue(ok, why)

    def test_and_a_rung_that_hands_BACKWARDS_is_caught(self):
        """Batumi Tower offering Approach again at a mile on final -- twice on
        12 August, and the reason `--inbound` was written."""
        ev = [self.handoff("contact Batumi Approach one two four decimal four "
                           "two five", "approach"),
              self.handoff("contact Batumi Tower one one eight decimal six",
                           "tower"),
              self.handoff("contact Batumi Approach one two four decimal four "
                           "two five", "approach")]
        ok, why = G.the_ladder_ran_forwards(ev, self.th)
        self.assertIs(ok, False, why)

    def test_the_same_man_twice_is_not_backwards(self):
        """A fixture that wandered out of the terminal area and back in was
        handed to Approach twice, correctly both times, and the first version of
        this predicate called it a ladder running backwards. Being sent to the
        controller you were just sent to is at worst chatter; the fault is being
        pushed DOWN to somebody who has finished with you."""
        twice = [self.handoff("contact Batumi Approach one two four decimal "
                              "four two five", "approach")] * 2
        ok, why = G.the_ladder_ran_forwards(twice, self.th)
        self.assertTrue(ok, why)
        self.assertIn("repeated", why)

    def test_the_first_rung_is_not_matched_against_the_last(self):
        """`range(-1, 7)` starts at -1, and `order[-1]` is the arrival's Ground.
        So the opening handoff of the sortie was scored against the closing one
        and the ladder read as finished before it began."""
        ok, why = G.the_ladder_ran_forwards(
            [self.handoff("contact Kobuleti Ground one two one decimal eight",
                          "ground"),
             self.handoff("contact Kobuleti Tower one three three decimal zero",
                          "tower")], self.th)
        self.assertTrue(ok, why)
        self.assertNotIn("repeated", why)

    def test_the_two_grounds_are_not_the_same_rung(self):
        """Departure's Ground first and the arrival's Ground last is the whole
        ladder; the reverse is a man sent home to the wrong airport."""
        forwards = [self.handoff("contact Kobuleti Ground one two one decimal "
                                 "eight", "ground"),
                    self.handoff("contact Batumi Ground one two one decimal "
                                 "nine", "ground")]
        self.assertTrue(G.the_ladder_ran_forwards(forwards, self.th)[0])
        self.assertIs(False, G.the_ladder_ran_forwards(
            list(reversed(forwards)), self.th)[0])


class EveryReplyOnItsOwnFieldsFrequency(unittest.TestCase):
    """The wrong field's number is always a real number. [#138]"""

    class Theatre:
        departure, arrival = "Kobuleti", "Batumi"
        stations = R.BATUMI_ASR.stations

    def atc(self, mhz: float, text: str) -> dict:
        return {"kind": "atc/pilot", "t": 1.0, "freq_mhz": mhz, "text": text}

    def test_a_destination_is_not_a_claim(self):
        """"Cleared to Batumi as filed" on Kobuleti's Clearance frequency is
        the ladder working, which is why this cannot be `other_fields_numbers`
        on a run that visits both."""
        ok, why = G.right_fields_numbers([self.atc(
            125.1, "Cleared to Batumi as filed, departure one two three "
                   "decimal three, squawk seven one four six.")], self.Theatre())
        self.assertTrue(ok, why)

    def test_answering_for_the_other_aerodrome_is(self):
        ok, why = G.right_fields_numbers([self.atc(
            121.8, "Marlin three one, contact Batumi Tower one one eight "
                   "decimal six.")], self.Theatre())
        self.assertIs(ok, False, why)

    def test_center_belongs_to_no_field_and_may_name_both(self):
        ok, why = G.right_fields_numbers([self.atc(
            139.0, "Marlin three one, contact Batumi Approach one two four "
                   "decimal four two five.")], self.Theatre())
        self.assertIsNone(ok, why)


class ARowWithNoPlanCannotPass(unittest.TestCase):
    """Q1a checked the clearance against a plan that was not there. [#137]

    `filed_plan` looks the theatre's `bootstrap_plan` up on the director, and
    `agent_atc` says in its own words that this name "is not even a row that has
    to exist" -- `362nd-kobuleti-batumi` was deliberately deleted. So it
    returned {} on every Caucasus run and the row degraded to

        said("cleared to", "")        the empty string is in every sentence
        said(_alt_words(0))           which is the word "zero"

    A green row that could not go red, on the seam between a filed plan and the
    clearance issued from it -- the one this week's work is about.
    """

    def reply(self, text: str) -> list[dict]:
        return [{"kind": "atc/pilot", "text": text}]

    def test_no_plan_skips_rather_than_passing(self):
        import ladder_rehearsal as L
        ok, why = L.only_if_there_is_a_plan({}, L.said("cleared to"))(
            self.reply("cleared to nowhere at all, maintain zero"))
        self.assertIsNone(ok)
        self.assertIn("no plan on file", why)

    def test_a_plan_with_no_level_skips_too(self):
        import ladder_rehearsal as L
        ok, _why = L.only_if_there_is_a_plan(
            {"destination": "BATUMI"}, L.said("cleared to"))(
            self.reply("cleared to Batumi"))
        self.assertIsNone(ok)

    def test_and_a_real_plan_is_still_judged_both_ways(self):
        import ladder_rehearsal as L
        plan = {"destination": "BATUMI", "cruise_ft": 10000}
        row = L.only_if_there_is_a_plan(
            plan, L.said("cleared to", "batumi"),
            L.said(L._alt_words(plan["cruise_ft"])))
        self.assertTrue(row(self.reply(
            "cleared to Batumi as filed, maintain one zero thousand"))[0])
        self.assertIs(False, row(self.reply(
            "cleared to Batumi as filed, maintain five thousand"))[0])


if __name__ == "__main__":
    unittest.main()
