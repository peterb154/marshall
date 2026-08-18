"""A field offers a set; Approach asks which, issues it, and supports him in it.

    "A field has a set of approaches available to it. When a pilot approaches
     the field - on a flight plan or not (just coming into the airspace vfr)
     the approach should ask which approach he would like and assign it to him,
     and support him in that approach"

THE HALF #162 LEFT OUT, and it was silent, which is the worst way to be wrong.

That issue established the shape -- a field OFFERS a set, Approach ISSUES one
to one aeroplane -- and wired the issuing to a FILED plan only:
`assign_approach` had exactly one caller and it read `assigned_plans.approach`.
Everything else followed correctly from `_pro(ac)` being None:

    stack_ft         empty, so `_free_slot` returned None
    request_approach fell through without entering the stack
    the engine       said NOTHING AT ALL

A radar-identified pilot asking plainly for the approach got silence from the
deterministic half, and the agent then answered with no directive behind it --
improvising a clearance the separation engine had no record of. Before #162 he
got the radio's loaded arrival instead, which is the wrong answer that issue
existed to delete. Removing a wrong answer without supplying the right one is
how a defect becomes a quieter defect.

WHAT IS ASSERTED HERE:

    he names one            it is issued, and the stack, the levels and the
                            letdown all work from it
    he names none           he is ASKED, with the field's set named
    he names an ambiguous   he is asked back with the CANDIDATES, never
    one                     resolved by list order -- #165's rule
    he is already cleared   he is not asked again
    he asked and was asked  he is NOT stacked, because until he chooses there
                            is no stack of his to enter

And the invariant, which is the reason the assignment is the engine's and not
the language brain's: an approach clearance puts an aeroplane into a letdown
that holds ONE, so which procedure he is on decides who contends with whom.
[#177]
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as C
from marshall.core.approach import match_spoken

import tests.theatre as T


def _approach_seat():
    ctl = C.Controller()
    ctl._me = T.station("approach")
    ctl.working = "approach"
    return ctl


def _inbound(ctl, cs="Pony 1-1"):
    ac = ctl.get(cs)
    ac.radar_identified = True          # he is on the scope; see may_be_sequenced
    return ac


class HeIsAskedWhenNobodyHasGivenHimOne(unittest.TestCase):

    def test_the_field_s_whole_set_is_named(self):
        ctl = _approach_seat()
        _inbound(ctl)
        ctl.request_approach("Pony 1-1")
        said = " ".join(t.text for t in ctl.take_out())
        self.assertTrue(said, "the engine said nothing to a pilot who asked")
        for p in ctl.published_approaches():
            with self.subTest(p.kind):
                self.assertIn(str(p.runway), said)

    def test_and_he_is_not_stacked_before_he_has_chosen(self):
        """Putting him in a stack before he has a procedure would be inventing
        the contention the choice decides -- and `_free_slot` has no levels to
        give him anyway."""
        ctl = _approach_seat()
        ac = _inbound(ctl)
        ctl.request_approach("Pony 1-1")
        self.assertIsNone(ac.assigned_ft)
        self.assertIsNone(ctl._in_letdown(ac))

    def test_a_field_with_one_approach_is_told_not_asked(self):
        """Reading a list of one to a pilot and inviting him to choose costs a
        transmission and tells him nothing."""
        ctl = _approach_seat()
        ac = _inbound(ctl)
        only = ctl.published_approaches(ac)[:1]
        ctl.offer_approaches(ac, only)
        said = " ".join(t.text for t in ctl.take_out())
        self.assertIn("expect", said.lower())
        self.assertNotIn("say which", said.lower())


class NamingOneIssuesIt(unittest.TestCase):

    def test_he_gets_the_one_he_asked_for(self):
        ils = T.the_ils()
        if ils is None:                             # pragma: no cover - config
            self.skipTest(f"{T.name()} publishes no ILS")
        ctl = _approach_seat()
        ac = _inbound(ctl)
        ctl.request_approach("Pony 1-1", wants="the I-L-S")
        got = ctl._pro(ac)
        self.assertIsNotNone(got, "asking by name still issued nothing")
        self.assertEqual((got.kind, str(got.runway)),
                         (ils.kind, str(ils.runway)))

    def test_and_the_machinery_behind_it_comes_alive(self):
        """The point of issuing one: he is supportable. A stack he can be given
        a level in, a letdown he can occupy, a clearance that names HIS
        procedure."""
        ctl = _approach_seat()
        ac = _inbound(ctl)
        ctl.request_approach("Pony 1-1", wants="the I-L-S")
        said = " ".join(t.text for t in ctl.take_out())
        self.assertTrue(getattr(ctl._pro(ac), "stack_ft", ()),
                        "he has a procedure and it offers no levels")
        self.assertIn("cleared", said.lower())
        self.assertEqual(ctl._in_letdown(ac), "Pony 1-1")

    def test_an_aeroplane_already_cleared_is_not_asked_again(self):
        """He said once. A controller who re-opens the question every
        transmission is the over-fitting the plate's own formation block warns
        about, one axis over."""
        ctl = _approach_seat()
        _inbound(ctl)
        ctl.request_approach("Pony 1-1", wants="the I-L-S")
        ctl.take_out()
        ctl.request_approach("Pony 1-1")
        again = " ".join(t.text for t in ctl.take_out())
        self.assertNotIn("say which", again.lower())


class AnAmbiguousRequestIsAskedBack(unittest.TestCase):
    """#165's rule, which this had to obey rather than re-decide: *an ambiguous
    request must ASK rather than pick, naming the candidates, never resolved by
    list order.*"""

    def test_two_of_a_kind_at_one_field_are_named_rather_than_picked(self):
        base = T.the_ils()
        if base is None:                            # pragma: no cover - config
            self.skipTest(f"{T.name()} publishes no ILS")
        import dataclasses
        other = dataclasses.replace(base, runway="31", final_crs=305)
        pair = {"a-ils-13": base, "a-ils-31": other}
        got, cands = match_spoken("the ILS", pair)
        self.assertIsNone(got, "an ambiguous request was resolved by order")
        self.assertEqual(len(cands), 2)

    def test_but_a_runway_settles_it(self):
        base = T.the_ils()
        if base is None:                            # pragma: no cover - config
            self.skipTest(f"{T.name()} publishes no ILS")
        import dataclasses
        other = dataclasses.replace(base, runway="31", final_crs=305)
        pair = {"a-ils-13": base, "a-ils-31": other}
        got, _ = match_spoken(f"ILS runway {base.runway}", pair)
        self.assertIsNotNone(got)
        self.assertEqual(str(got.runway), str(base.runway))

    def test_words_a_pilot_actually_says_all_reach_the_same_procedure(self):
        """One kind, several words. A controller who recognises only the
        published spelling is deaf three times in four."""
        asr = T.approach_of_kind("asr")
        if asr is None:
            self.skipTest(f"{T.name()} publishes no surveillance approach")
        pubs = T.approaches()
        for said in ("radar approach", "the surveillance approach", "ASR",
                     "talk me down"):
            with self.subTest(said):
                got, _ = match_spoken(said, pubs, field=asr.aerodrome.name)
                self.assertIsNotNone(got, f"{said!r} reached no procedure")
                self.assertEqual(got.kind, "asr")

    def test_and_a_procedure_this_map_has_not_got_resolves_NOTHING(self):
        """Never the nearest thing. A pilot asking for a GCA at a field that
        publishes none is asking for something that does not exist, and the
        answer is to say so."""
        got, cands = match_spoken("a G-C-A", T.approaches())
        self.assertIsNone(got)
        self.assertEqual(cands, ())


class TheSeparationInvariantSurvivesIt(unittest.TestCase):
    """Why the assignment is the ENGINE's. An approach clearance puts an
    aeroplane into a letdown that holds one, so which procedure each is on
    decides who contends with whom — and that may never be a thing the language
    half remembers having said."""

    def test_three_aircraft_choosing_differently_still_separate(self):
        ils, asr = T.the_ils(), T.approach_of_kind("asr")
        if ils is None or asr is None:              # pragma: no cover - config
            self.skipTest(f"{T.name()} lacks an ILS or a surveillance approach")
        ctl = _approach_seat()
        for cs, want in (("Lead 1-1", "the I-L-S"),
                         ("Pony 2-1", "radar approach"),
                         ("Hawk 3-1", "the I-L-S")):
            _inbound(ctl, cs)
            ctl.request_approach(cs, wants=want)
            ctl.take_out()
        levels = [a.assigned_ft for a in ctl.aircraft.values()
                  if a.assigned_ft is not None]
        self.assertEqual(len(levels), len(set(levels)),
                         "two aircraft were assigned one level")
        self.assertFalse(ctl.anomalies, f"engine anomalies: {ctl.anomalies}")

    def test_and_each_is_worked_on_the_procedure_he_chose(self):
        ils, asr = T.the_ils(), T.approach_of_kind("asr")
        if ils is None or asr is None:              # pragma: no cover - config
            self.skipTest(f"{T.name()} lacks an ILS or a surveillance approach")
        ctl = _approach_seat()
        for cs, want, kind in (("Lead 1-1", "the I-L-S", "ils"),
                               ("Pony 2-1", "radar approach", "asr")):
            _inbound(ctl, cs)
            ctl.request_approach(cs, wants=want)
            ctl.take_out()
            with self.subTest(cs):
                self.assertEqual(ctl._pro(ctl.aircraft[cs]).kind, kind)


if __name__ == "__main__":
    unittest.main()
