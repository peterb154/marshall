"""An engine that does not know what he is flying must not answer about it.

19 August. An F-16 flew Kobuleti to Batumi, asked for the ILS, was told he was
cleared for it, and flew the whole arrival with the deterministic half of the
system switched off. Three faults, one absence.

    the aeroplane had NO procedure   nothing had assigned one -- the approach
                                     clearance was spoken by the model and
                                     never issued, so `assigned_plans.approach`
                                     was NULL all sortie

    asr.guide(fix, None)             reads `profile.final_crs_true`. There is
                                     no final approach course for a man nobody
                                     has cleared for an approach, and asking
                                     raised AttributeError -- caught by
                                     `separation_context`, which must never
                                     let a classifier failure cost a
                                     transmission. ELEVEN TIMES:

        !! controller classify failed: 'NoneType' object has no attribute
           'final_crs_true'

                                     So the engine was not wrong about the
                                     arrival. It was not running.

    beacon_flown = not may_vector()  `may_vector` answers "may this controller
                                     give headings?", for which "I do not know
                                     what he is flying" is correctly NO.
                                     Inverting it turns an absence into a
                                     positive claim that he is homing a beacon,
                                     and ten position reports were refused with
                                     "you have not reached the fix, continue
                                     inbound" -- to a departure, outbound, at
                                     nineteen miles.

        "why oh why would it be treated as a vector approach? first, I was
         assigned the ILS ... there hsould be no default appaorch"

THERE IS NO DEFAULT. `Controller()` has carried `profile=None` since #162, and
that is exactly the case all three of these mishandled. Unknown must stay
unknown.  [#197]
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as C
from marshall.atc import intents as I
from marshall.core import route as R
from marshall.core.approach import may_vector

import tests.theatre as T


class AnUnknownProcedureIsNotABeacon(unittest.TestCase):

    def test_may_vector_still_refuses_headings_for_an_unknown_procedure(self):
        """The function itself is right and must not be 'fixed'. Not knowing
        what he flies is a good reason not to give him headings."""
        self.assertFalse(may_vector(None))

    def test_but_that_is_not_a_claim_that_he_flies_a_beacon(self):
        """The inversion, asserted where it lives. `beacon_flown` must require
        a procedure that is KNOWN and does not vector -- two facts, and the
        absence of the second is not the first."""
        import ast
        import inspect
        from marshall.atc import agent_atc as A
        src = inspect.getsource(A)
        at = src.index("beacon_flown =")
        line = src[at:src.index("\n", at)]
        self.assertIn("is not None", line,
                      "`beacon_flown` is derived from `not may_vector(...)` "
                      "alone, so an aeroplane with no procedure is claimed to "
                      "be homing a beacon")
        ast.parse(line.strip())


class TheEngineDoesNotThrowOnAnAeroplaneItCannotPlace(unittest.TestCase):
    """The one that actually cost the sortie.

    `separation_context` catches everything on purpose -- "a classifier failure
    must cost a label, never a transmission" -- which is right, and which is
    why an exception here is silent and total: no directive, no engine line, no
    approach issued, and a model answering alone with nothing to voice.
    """

    def setUp(self):
        self.ctl = C.Controller()
        self.ctl._me = R.station_for("approach", field=T.arrival().name)
        if self.ctl._me is None:
            self.skipTest("this map staffs no approach at the arrival field")

    def test_the_controller_carries_no_default_procedure(self):
        """#162's guarantee, and the precondition for everything below."""
        self.assertIsNone(self.ctl.profile)
        self.assertIsNone(self.ctl.procedure_for("Nobody"))

    def test_a_turn_for_an_unplaced_aeroplane_does_not_raise(self):
        """Driven through `dispatch`, which is what the live loop calls."""
        ac = self.ctl.get("Sockeye")
        ac.phase = C.Phase.ENROUTE
        self.assertIsNone(self.ctl.procedure_for("Sockeye"))
        for kind in (I.IntentKind.CHECK_IN, I.IntentKind.REPORT_BEACON,
                     I.IntentKind.REQUEST_APPROACH):
            with self.subTest(kind.name):
                self.ctl.out.clear()
                I.dispatch(self.ctl, I.Intent(kind, "Sockeye", wants="ILS"),
                           on_ground=False)


class AndOnceHeIsClearedTheEngineHasHisProcedure(unittest.TestCase):
    """The other side: the engine ISSUES the approach, and everything above
    stops applying because the absence is gone.

    This is the path that never ran on 19 August. It works, and that is the
    point -- the request was classified correctly (`REQUEST_APPROACH`, wants
    'ILS 13'), `dispatch` reaches it, and `request_approach` issues. The
    clearance the pilot heard was the model's because the engine had thrown
    three lines earlier, not because any of this was missing.
    """

    def setUp(self):
        self.ctl = C.Controller()
        self.ctl._me = R.station_for("approach", field=T.arrival().name)
        if self.ctl._me is None:
            self.skipTest("this map staffs no approach at the arrival field")
        self.ac = self.ctl.get("Sockeye")
        self.ac.phase = C.Phase.ENROUTE

    def test_asking_for_it_by_name_issues_it(self):
        self.ctl.out.clear()
        I.dispatch(self.ctl, I.Intent(I.IntentKind.REQUEST_APPROACH, "Sockeye",
                                      wants="ILS 13"), on_ground=False)
        said = " ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("cleared", said)
        self.assertIsNotNone(self.ctl.procedure_for("Sockeye"),
                             "he was told he was cleared and the engine kept "
                             "no record of what for")

    def test_and_then_he_is_no_longer_an_unknown(self):
        I.dispatch(self.ctl, I.Intent(I.IntentKind.REQUEST_APPROACH, "Sockeye",
                                      wants="ILS 13"), on_ground=False)
        pro = self.ctl.procedure_for("Sockeye")
        self.assertTrue(may_vector(pro),
                        "an ILS is vectored by construction; if this is False "
                        "the beacon branch will start refusing his position "
                        "reports again")


if __name__ == "__main__":
    unittest.main()
