"""A pilot who says the plan's name has not asked an ambiguous question.

    15:13:08  PILOT  Roger Sock, I would like Batumi Test, IFR to Batumi.
    15:13:20  ATC    two plans fit that -- say which: transit and recovery
                     filed as Batumi Test, or transit and recovery filed as
                     Domino.

`score` gives 100 points for naming a plan outright, which is by a distance the
strongest signal it has. It could not fire. The test was a plain substring of
the transcript:

    label in said           "batumitest" in "i would like batumi test, ..."

and a label is TYPED by whoever filed the plan while the request is SPOKEN by a
pilot. `BatumiTest` is one token on a screen and two words in a cockpit, so the
two spellings never agree -- and this fails for EVERY multi-word plan name,
always, not intermittently. Whisper writes the space down because the pilot
says it.

What scored instead was `destination`, worth a deliberate one point because
every plan comes home to the same field. Both plans ended at Batumi, so they
tied, and the resolver asked a question whose answer was already in the
transmission. Bare "Batumi Test" -- nothing else said at all -- tied the same
way.

WHY IT LOOKED LIKE THE MODEL'S FAULT. The disambiguation the pilot heard was
not among the engine's decisions for that sortie, so it read as the language
brain improvising, alongside the narrated clearance of #180/#181. It was not.
The engine resolver genuinely could not tell the two apart, and the only way to
see that was to run it.

AND #165 STILL STANDS. An ambiguous request is asked back, never resolved by
list order. The correction here is narrower than it looks: a request that names
nothing is still ambiguous and still gets the question. [#182]
"""

from __future__ import annotations

import unittest

from marshall.atc import plans


def _plan(label: str, **kw) -> dict:
    """Two plans that differ ONLY by name, which is the flown case.

    Same origin, same destination, same shape -- so nothing but the label can
    break the tie, and a test that let them differ elsewhere would pass on the
    wrong evidence.
    """
    return {"label": label, "origin": "KOBULETI", "destination": "BATUMI",
            "task": kw.get("task", "transit and recovery"),
            "route": kw.get("route", "")}


BOARD = [_plan("BatumiTest"), _plan("Domino")]


class NamingItOutrightResolvesIt(unittest.TestCase):

    def _picked(self, said: str):
        got = plans.pick(said, BOARD, callsign="Sockeye")
        return (got["plan"]["label"] if "plan" in got else None), got

    def test_the_transmission_that_was_actually_flown(self):
        label, got = self._picked(
            "Roger Sock, I would like Batumi Test, IFR to Batumi.")
        self.assertEqual(label, "BatumiTest",
                         f"he named it and got {got}")

    def test_the_bare_name_on_its_own(self):
        """The strongest possible form of the request. If this is ambiguous
        nothing a pilot can say will ever resolve."""
        self.assertEqual(self._picked("Batumi Test")[0], "BatumiTest")

    def test_however_he_happens_to_space_it(self):
        """Whisper's spacing is not stable and the pilot's is not either, so
        the match may not depend on either."""
        for said in ("BatumiTest", "Batumi Test", "batumi test",
                     "batumi-test", "BATUMI  TEST"):
            with self.subTest(said):
                self.assertEqual(self._picked(said)[0], "BatumiTest")

    def test_and_the_other_one_too(self):
        """A single-word label worked before and must keep working -- the fix
        must not trade one name for another."""
        self.assertEqual(self._picked("I would like Domino")[0], "Domino")

    def test_the_name_outweighs_the_destination(self):
        """Both share a destination, so the point it is worth must not be
        able to drag the answer away from the plan he named."""
        _lbl, got = self._picked("Batumi Test, IFR to Batumi")
        self.assertIn("named BatumiTest", got.get("why", []))


class ButAskingWithNoNameIsSTILLAmbiguous(unittest.TestCase):
    """#165's rule, which this must not weaken.

    The complaint was never "stop asking". It was "do not ask when he already
    told you". A request that genuinely fits two plans has to be put back to
    the pilot rather than settled by whichever row came out of the database
    first.
    """

    def test_a_request_naming_nothing_is_asked_back(self):
        got = plans.pick("request clearance, IFR to Batumi", BOARD,
                         callsign="Sockeye")
        self.assertIn("ambiguous", got,
                      "resolved a request that named neither plan")
        self.assertEqual(
            sorted(p["label"] for p in got["ambiguous"]),
            ["BatumiTest", "Domino"])

    def test_and_nothing_on_file_is_not_a_guess_either(self):
        got = plans.pick("request clearance to Vaziani", [], callsign="Sockeye")
        self.assertTrue(got.get("none"))


class TheSquashIsNotOverEager(unittest.TestCase):
    """Comparing on letters alone is a real loosening, so it gets a bound.

    Dropping the separators means a label can now match across a word break
    that was never there. That is the POINT for "Batumi Test", and it must not
    extend to a label that simply was not said.
    """

    def test_a_plan_nobody_named_does_not_match(self):
        pts, why, _ctx = plans.score("request clearance", _plan("Domino"))
        self.assertNotIn("named Domino", why)
        self.assertLess(pts, 100)

    def test_an_empty_label_matches_nothing(self):
        """`"" in anything` is True, which is how a guard like this usually
        goes wrong."""
        pts, why, _ctx = plans.score("request clearance", _plan(""))
        self.assertEqual([w for w in why if w.startswith("named")], [])
        self.assertLess(pts, 100)


if __name__ == "__main__":
    unittest.main()
