"""An action the procedure does not contain is never dispatched.

    "why would one of the brains (the one doing the wrong thing) be invoked at
     all when that phase of flight isn't happening. I feel like there is a
     fundamental flaw in the state machinery"

There was. The router was a flat `match intent.kind` -- a classifier's label
straight to a controller method, with nothing asking whether the action existed.
On 9 August a pilot on a RADAR approach read back a heading twelve times and was
answered twelve times with "roger, station passage two plus three two", which is
beacon-letdown phraseology for a procedure that has no beacon.

The cases below are that sortie's actual transmissions.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.atc import reachable as RE
from marshall.atc.intents import IntentKind as K
from marshall.core import route as R


class TestTheBeaconReportThatStartedIt(unittest.TestCase):

    def test_a_radar_approach_has_no_station_to_pass(self):
        self.assertFalse(RE.reachable(K.REPORT_BEACON, R.BATUMI_ASR))

    def test_nor_does_an_ils(self):
        """He reports established on an ILS, which is a different thing and a
        different intent. There is still no station passage."""
        self.assertFalse(RE.reachable(K.REPORT_BEACON, R.KOBULETI_ILS))

    def test_the_beacon_letdown_keeps_it(self):
        """The procedure it belongs to. Station passage IS the letdown: the
        pilot flies the missed approach point off his own clock and the
        controller backs him up."""
        self.assertTrue(RE.reachable(K.REPORT_BEACON, R.BATUMI_APPROACH))

    def test_a_blind_controller_keeps_it_on_any_procedure(self):
        """The rule is not "is it an NDB". A controller with no radar has no
        other way of finding out where anybody is, so a position report is the
        only thing he has -- whatever the procedure is called."""
        import dataclasses
        blind = dataclasses.replace(
            R.BATUMI_ASR,
            atc=dataclasses.replace(R.BATUMI_ASR.atc, radar=False))
        self.assertTrue(RE.reachable(K.REPORT_BEACON, blind))

    def test_the_reason_is_sayable(self):
        why = RE.why_not(K.REPORT_BEACON, R.BATUMI_ASR)
        self.assertIn("no station to pass", why)


class TestWhereTheAeroplaneIs(unittest.TestCase):

    def test_a_parked_jet_cannot_go_around(self):
        for kind in (K.REPORT_MISSED, K.REQUEST_APPROACH, K.REQUEST_VISUAL):
            with self.subTest(kind=kind):
                self.assertFalse(
                    RE.reachable(kind, R.BATUMI_ASR, on_ground=True))

    def test_an_airborne_aeroplane_cannot_ask_to_taxi(self):
        for kind in (K.REQUEST_TAXI, K.REQUEST_CLEARANCE,
                     K.REPORT_HOLDING_SHORT, K.REQUEST_TAKEOFF):
            with self.subTest(kind=kind):
                self.assertFalse(
                    RE.reachable(kind, R.BATUMI_ASR, on_ground=False))

    def test_ground_actions_work_on_the_ground(self):
        for kind in (K.REQUEST_TAXI, K.REQUEST_CLEARANCE,
                     K.REPORT_HOLDING_SHORT, K.REQUEST_TAKEOFF):
            with self.subTest(kind=kind):
                self.assertTrue(
                    RE.reachable(kind, R.BATUMI_ASR, on_ground=True))

    def test_not_knowing_never_blocks(self):
        """`on_ground` is None when the scope has dropped or no event has been
        seen. A guard that fires on missing information silences a controller at
        the one moment a pilot most needs him."""
        for kind in (K.REPORT_MISSED, K.REQUEST_TAXI, K.REQUEST_TAKEOFF):
            with self.subTest(kind=kind):
                self.assertTrue(
                    RE.reachable(kind, R.BATUMI_ASR, on_ground=None))

    def test_check_in_and_landing_are_always_reachable(self):
        """Two things a pilot may do at any point of any procedure, in the air
        or on the ground. If either of these is ever gated, a pilot who has just
        landed or just called up gets silence."""
        for kind in (K.CHECK_IN, K.REPORT_LANDED):
            for ground in (True, False, None):
                with self.subTest(kind=kind, on_ground=ground):
                    self.assertTrue(
                        RE.reachable(kind, R.BATUMI_ASR, on_ground=ground))


class TestTheRouterActuallyHonoursIt(unittest.TestCase):
    """The table is worth nothing if `dispatch` does not consult it -- which is
    the shape of half the bugs in this project: a rule that exists in one
    function and is not called from the path that needed it."""

    def controller(self, profile=R.BATUMI_ASR):
        from marshall.atc import controller as C
        return C.Controller(profile)

    def dispatch(self, ctl, kind, on_ground=None):
        from marshall.atc import intents
        return intents.dispatch(ctl, intents.Intent(kind=kind,
                                                    callsign="Sockeye"),
                                on_ground=on_ground)

    def test_the_beacon_report_never_reaches_the_engine(self):
        """The twelve calls. `report_beacon` on a radar approach must not run,
        so nothing is said and nothing is recorded against him."""
        ctl = self.controller()
        ctl.get("Sockeye")
        handled = self.dispatch(ctl, K.REPORT_BEACON)
        self.assertTrue(handled, "an unreachable action is handled, not a "
                                 "'say again' -- the agent answers it")
        self.assertEqual([t.text for t in ctl.take_out()], [],
                         "the engine spoke about a beacon that does not exist")
        self.assertTrue(ctl.unreachable, "the stand-down was not logged")

    def test_and_it_does_reach_the_engine_on_the_letdown(self):
        ctl = self.controller(R.BATUMI_APPROACH)
        ctl.get("Sockeye")
        self.dispatch(ctl, K.REPORT_BEACON)
        self.assertEqual(ctl.unreachable, [],
                         "the letdown's own procedure was gated out")

    def test_an_unreachable_action_is_never_a_say_again(self):
        """Returning False makes the caller ask him to say again -- which for a
        perfectly clear read-back is worse than the bug being fixed."""
        ctl = self.controller()
        ctl.get("Sockeye")
        self.assertTrue(self.dispatch(ctl, K.REQUEST_TAXI, on_ground=False))
        self.assertEqual([t.text for t in ctl.take_out()], [])




class TestTheGateDidNotShutTheDoorOnEntry(unittest.TestCase):
    """The risk the gate creates, checked rather than assumed.

    An aeroplane gets onto the board when a dispatched intent calls `get` or
    `_enter`. Gating `report_beacon` off a radar approach removes one of those
    doors -- so the ones that remain have to be enough, or a pilot vanishes from
    the engine entirely and nobody is sequenced.
    """

    def board_after(self, kind):
        from marshall.atc import controller as C
        from marshall.atc import intents
        ctl = C.Controller(R.BATUMI_ASR)
        intents.dispatch(ctl, intents.Intent(kind=kind, callsign="Sockeye"),
                         on_ground=False)
        return [r.get("callsign") for r in ctl.board()]

    def test_checking_in_still_puts_him_on_the_board(self):
        self.assertIn("Sockeye", self.board_after(K.CHECK_IN))

    def test_asking_for_the_approach_still_puts_him_on_the_board(self):
        self.assertIn("Sockeye", self.board_after(K.REQUEST_APPROACH))

    def test_both_are_reachable_airborne_on_every_procedure(self):
        """Because if either were ever gated, the door closes completely."""
        for profile in (R.BATUMI_ASR, R.KOBULETI_ILS, R.BATUMI_APPROACH):
            for kind in (K.CHECK_IN, K.REQUEST_APPROACH):
                with self.subTest(procedure=profile.kind, kind=kind):
                    self.assertTrue(
                        RE.reachable(kind, profile, on_ground=False))


if __name__ == "__main__":
    unittest.main()
