"""Which procedure a plan names, and what a controller calls it out loud.

    "I should be on the ILS13. Why would he say radar approach?"
    "the intent on the board shows ASR approach, but I'm cleared for the ILS"

One line did the whole of that sortie. `_approach_named` matched with

    key.startswith(f"{name}-")

which matches EVERY approach at that aerodrome, so `batumi-ils` returned
whichever Batumi profile the theatre listed first -- the surveillance approach.
Everything followed from reading a talkdown where an ILS was filed:

  * the engine cleared him for a "radar approach" while his plate said ILS
  * `guidance` was "talkdown", so the intercept vectoring never ran
  * the established-and-silent branch was unreachable
  * he flew through the centreline, out to twenty-one miles, and turned
    himself back in

Every number was a real number belonging to the wrong procedure, which is why
nothing looked broken.

It was correct while Batumi had ONE approach -- the shape this project keeps
finding, and the sixth time this month. A second one arrived and it collided on
the first flight.
"""

import unittest
import unittest.mock

from marshall.atc import agent_atc as A
from tests import theatre as TH

# CAUCASUS ONLY, and named rather than left to fail. Every key in this
# file is a Batumi or Kobuleti procedure -- `batumi-ils-13` is not a
# thing Nevada publishes, and asking for it there is not a defect, it is
# a question about another map. What the file GUARDS is theatre-neutral
# and is asserted on whichever map is loaded by
# `TestTwoILSApproachesAtOneField`, which builds its second procedure
# rather than naming one. [#165]
TH.only("caucasus",
        why="every key asserted here names a Georgian procedure; the RULE is map-neutral and is guarded by the two-ILS class, which constructs its own")

from marshall.atc import controller as C
from marshall.core import route as R


class TestAPlanGetsTheProcedureItNames(unittest.TestCase):

    def test_each_batumi_procedure_resolves_to_itself(self):
        for key, kind in (("batumi-ils-13", "ils"), ("batumi-asr-13", "asr"),
                          ("batumi-ndb-12", "ndb")):
            with self.subTest(key):
                self.assertEqual(A._approach_named(key).kind, kind)

    def test_the_ils_is_not_the_surveillance_approach(self):
        # The failure in one assertion: both are vectored, both are at Batumi,
        # and they are not the same thing to fly.
        ils, asr = A._approach_named("batumi-ils-13"), A._approach_named("batumi-asr-13")
        self.assertEqual(ils.guidance, "intercept")
        self.assertEqual(asr.guidance, "talkdown")
        self.assertIsNot(ils, asr)

    def test_another_aerodrome_is_untouched(self):
        self.assertEqual(A._approach_named("kobuleti-ils-07").kind, "ils")

    def test_a_field_with_ONE_procedure_still_resolves_loosely(self):
        # The loose match stays as a SECOND pass, and is worth having exactly
        # while there is nothing to choose between: Kobuleti publishes one.
        self.assertEqual(A._approach_named("kobuleti").kind, "ils")

    def test_but_a_field_with_SEVERAL_refuses_and_names_them(self):
        """This asserted that "batumi" gets "that field's default", and there
        is no such thing -- #162 deleted the concept on the owner's
        instruction: "There should be no such thing".

        Batumi publishes three. Returning the first of them is #131 exactly:
        on 12 August it cleared a man for a radar approach while his plate said
        ILS, and every number he was given was real and belonged to the wrong
        procedure. #1 G3/G4 settled the shape for flight plans -- "when to ASK
        instead of picking one" -- and a procedure is no different.

        So the rule is not "prefer a default", it is "resolve when there is one
        answer". [#165]
        """
        self.assertIsNone(A._approach_named("batumi"))

    def test_a_key_nobody_publishes_gets_nothing(self):
        # Not somebody else's approach. That is the whole reason this function
        # exists rather than a `getattr` on route.py.
        self.assertIsNone(A._approach_named("vaziani-ils"))


class TestWhatHeCallsItOnTheRadio(unittest.TestCase):
    """It knew two procedures and there are more than two."""

    def test_an_ils_is_called_an_ils(self):
        self.assertEqual(C.Controller(R.BATUMI_ILS)._approach_name(None),
                         "I-L-S approach")

    def test_a_surveillance_approach_keeps_its_name(self):
        self.assertEqual(C.Controller(R.BATUMI_ASR)._approach_name(None),
                         "radar approach")

    def test_the_beacon_letdown_keeps_its_name(self):
        self.assertEqual(C.Controller(R.BATUMI_APPROACH)._approach_name(None),
                         "beacon approach")

    def test_it_is_keyed_on_the_procedure_not_on_being_vectored(self):
        # An ILS and a surveillance approach are BOTH vectored. Asking "may I
        # vector him" cannot tell them apart, which is exactly what it did.
        from marshall.core.approach import may_vector
        self.assertTrue(may_vector(R.BATUMI_ILS))
        self.assertTrue(may_vector(R.BATUMI_ASR))
        self.assertNotEqual(C.Controller(R.BATUMI_ILS)._approach_name(None),
                            C.Controller(R.BATUMI_ASR)._approach_name(None))


if __name__ == "__main__":
    unittest.main()


class TestTwoILSApproachesAtOneField(unittest.TestCase):
    """Batumi is 13/31, and an ILS to 31 is an ordinary thing to add.

        "batumi_ils … I don't know what that is. There could be multiple ils
         approaches into a field"

    A key of `<field>-<kind>` can NAME only one of them, so the second cannot
    be published at all -- and if it could, `<field>-<kind>` would match both
    and the resolver returned the first. That is #131 one axis over: the fix
    then was to match exactly first, and matching exactly is no help when two
    procedures have the same exact name.

    Real procedures are named for the runway they serve -- ILS RWY 13, VOR RWY
    31 -- because the runway is what makes two approaches at one field
    different things. [#165]
    """

    def build_the_reciprocal(self):
        """Batumi's ILS from the other end, as data, off the published one."""
        import dataclasses
        from marshall.core import route as R
        ils = R.BATUMI_ILS
        return dataclasses.replace(
            ils, runway="31",
            final_crs=(ils.final_crs + 180) % 360,
            controller=ils.controller)

    def test_the_key_can_tell_them_apart(self):
        ils13, ils31 = R.BATUMI_ILS, self.build_the_reciprocal()
        self.assertNotEqual(A._key_of(ils13), A._key_of(ils31))
        self.assertEqual(A._key_of(ils13), "batumi-ils-13")
        self.assertEqual(A._key_of(ils31), "batumi-ils-31")

    def test_and_each_resolves_to_itself(self):
        """The assertion that could not previously be written: with both
        published, asking for one must not hand back the other."""
        import dataclasses
        from marshall.core import theatre as _th
        th = _th.current()
        both = dataclasses.replace(
            th, approaches=(*th.approaches, self.build_the_reciprocal()))
        with unittest.mock.patch.object(A, "_theatre",
                                        unittest.mock.Mock(current=lambda: both)):
            self.assertEqual(A._approach_named("batumi-ils-13").runway, "13")
            self.assertEqual(A._approach_named("batumi-ils-31").runway, "31")

    def test_and_the_runway_less_key_becomes_ambiguous(self):
        """`batumi-ils` names one procedure today and two once 31 exists. The
        honest answer then is that the request does not name a procedure --
        not whichever the theatre happens to list first."""
        import dataclasses
        from marshall.core import theatre as _th
        th = _th.current()
        both = dataclasses.replace(
            th, approaches=(*th.approaches, self.build_the_reciprocal()))
        with unittest.mock.patch.object(A, "_theatre",
                                        unittest.mock.Mock(current=lambda: both)):
            # THE RUNWAY-LESS FORM, deliberately. A blanket rename of the old
            # keys rewrote this line to `batumi-ils-13` and quietly inverted
            # the test -- 13 resolves to itself and always will, which is the
            # assertion above. What becomes ambiguous is the key that does not
            # say which runway.
            self.assertIsNone(A._approach_named("batumi-ils"))
