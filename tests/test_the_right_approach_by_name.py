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

from marshall.atc import agent_atc as A
from marshall.atc import controller as C
from marshall.core import route as R


class TestAPlanGetsTheProcedureItNames(unittest.TestCase):

    def test_each_batumi_procedure_resolves_to_itself(self):
        for key, kind in (("batumi-ils", "ils"), ("batumi-asr", "asr"),
                          ("batumi-ndb", "ndb")):
            with self.subTest(key):
                self.assertEqual(A._approach_named(key).kind, kind)

    def test_the_ils_is_not_the_surveillance_approach(self):
        # The failure in one assertion: both are vectored, both are at Batumi,
        # and they are not the same thing to fly.
        ils, asr = A._approach_named("batumi-ils"), A._approach_named("batumi-asr")
        self.assertEqual(ils.guidance, "intercept")
        self.assertEqual(asr.guidance, "talkdown")
        self.assertIsNot(ils, asr)

    def test_another_aerodrome_is_untouched(self):
        self.assertEqual(A._approach_named("kobuleti-ils").kind, "ils")

    def test_a_field_with_no_procedure_still_gets_its_default(self):
        # The loose match stays as a SECOND pass -- a plan naming just the field
        # wants that field's default rather than nothing at all.
        self.assertIsNotNone(A._approach_named("batumi"))

    def test_a_key_nobody_publishes_gets_nothing(self):
        # Not somebody else's approach. That is the whole reason this function
        # exists rather than a `getattr` on route.py.
        self.assertIsNone(A._approach_named("vaziani-ils"))


class TestWhatHeCallsItOnTheRadio(unittest.TestCase):
    """It knew two procedures and there are more than two."""

    def test_an_ils_is_called_an_ils(self):
        self.assertEqual(C.Controller(R.BATUMI_ILS)._approach_name(),
                         "I-L-S approach")

    def test_a_surveillance_approach_keeps_its_name(self):
        self.assertEqual(C.Controller(R.BATUMI_ASR)._approach_name(),
                         "radar approach")

    def test_the_beacon_letdown_keeps_its_name(self):
        self.assertEqual(C.Controller(R.BATUMI_APPROACH)._approach_name(),
                         "beacon approach")

    def test_it_is_keyed_on_the_procedure_not_on_being_vectored(self):
        # An ILS and a surveillance approach are BOTH vectored. Asking "may I
        # vector him" cannot tell them apart, which is exactly what it did.
        from marshall.core.approach import may_vector
        self.assertTrue(may_vector(R.BATUMI_ILS))
        self.assertTrue(may_vector(R.BATUMI_ASR))
        self.assertNotEqual(C.Controller(R.BATUMI_ILS)._approach_name(),
                            C.Controller(R.BATUMI_ASR)._approach_name())


if __name__ == "__main__":
    unittest.main()
