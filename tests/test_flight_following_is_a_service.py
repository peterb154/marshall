"""Flight following: requested on the radio, carried by the aeroplane.

    "Perhaps the pilot can request flight following to get this kind of
     guidance. It needs to work across handoffs"

This file is the service and nothing else -- no geometry, no headings. That
split is deliberate: the half that spans SEATS is the half that breaks, and it
is testable before a single leg has been computed. [#217]
"""
from __future__ import annotations

import unittest

from marshall.atc import controller as atc
from marshall.core import route as R


def seat(role="center"):
    c = atc.Controller(R.BATUMI_ASR)
    c.working = role
    return c


def said(c) -> str:
    return " ".join(t.text for t in c.out).lower()


class OwnNavIsTheDefault(unittest.TestCase):
    """The engine says nothing unless asked, and the reason is not the airspace
    rules -- this system has no VFR/IFR distinction to hang them on.

        "the reason we don't give guidance on all flights is that in a combat
         sim, we might not want the nag (own nav)"
    """

    def test_a_new_aeroplane_is_on_own_nav(self):
        self.assertFalse(seat().get("Sockeye").following)

    def test_and_hears_nothing_about_it(self):
        c = seat("approach")
        c.check_in("Sockeye")
        self.assertNotIn("following", said(c))

    def test_ending_a_service_nobody_has_is_silent(self):
        c = seat()
        c.end_following("Sockeye")
        self.assertEqual(c.out, [])


class HeAsksForIt(unittest.TestCase):

    def test_it_is_granted(self):
        c = seat()
        c.request_following("Sockeye", wants="request flight following")
        self.assertTrue(c.get("Sockeye").following)
        self.assertIn("flight following approved", said(c))

    def test_a_named_fix_is_carried(self):
        """"Direct BAR" is a one-leg route. Requiring a filed plan would make
        the commonest request unserviceable."""
        c = seat()
        c.request_following("Sockeye", wants="flight following direct BAR")
        self.assertEqual(c.get("Sockeye").following_to, "BAR")
        self.assertIn("direct bar", said(c))

    def test_naming_nothing_means_his_filed_route(self):
        c = seat()
        c.request_following("Sockeye", wants="request flight following")
        self.assertEqual(c.get("Sockeye").following_to, "")

    def test_a_word_nobody_can_resolve_is_not_a_target(self):
        """Being taken to a place nobody can resolve is worse than being taken
        along the route he filed."""
        c = seat()
        c.request_following("Sockeye", wants="following direct the field")
        self.assertEqual(c.get("Sockeye").following_to, "")


class ItSurvivesAHandoff(unittest.TestCase):
    """THE POINT OF THE WHOLE DESIGN. A service recorded against the CONTROLLER
    would have to be copied at every rung, and the rung it was forgotten at is
    where a pilot goes quiet and nobody notices."""

    def test_the_receiving_seat_knows(self):
        c = seat("departure")
        c.request_following("Sockeye", wants="request flight following")
        c.bind("Sockeye", owner="Georgia Center")      # a handoff
        self.assertTrue(c.following_continues("Sockeye"))

    def test_and_says_so_when_he_checks_in(self):
        """A pilot cannot see a boolean. This line is how he learns the new
        controller knows -- and the only thing a test can look for."""
        c = seat("approach")
        c.request_following("Sockeye", wants="request flight following")
        c.out.clear()
        c.check_in("Sockeye")
        self.assertIn("flight following continues", said(c))

    def test_a_man_on_own_nav_gets_no_such_line(self):
        c = seat("approach")
        c.check_in("Andre")
        self.assertNotIn("continues", said(c))


class TwoEndingsAndTheyAreNotTheSame(unittest.TestCase):
    """"Resume own navigation" is off vectors and still watched; "radar service
    terminated" is the service over. A pilot told the first still expects to
    hear about somebody converging."""

    def _following(self):
        c = seat()
        c.request_following("Sockeye", wants="request flight following")
        c.out.clear()
        return c

    def test_cancelling_terminates_the_service(self):
        c = self._following()
        c.request_following("Sockeye", wants="cancel flight following")
        self.assertIn("radar service terminated", said(c))
        self.assertFalse(c.get("Sockeye").following)

    def test_own_navigation_in_his_words_also_cancels(self):
        c = self._following()
        c.request_following("Sockeye", wants="we'll go own navigation")
        self.assertFalse(c.get("Sockeye").following)

    def test_stopping_the_vectors_is_the_other_phrase(self):
        c = self._following()
        c.end_following("Sockeye")
        self.assertIn("resume own navigation", said(c))
        self.assertNotIn("terminated", said(c))

    def test_either_way_he_is_back_on_own_nav(self):
        for over in (True, False):
            with self.subTest(service_over=over):
                c = self._following()
                c.end_following("Sockeye", service_over=over)
                self.assertFalse(c.get("Sockeye").following)
                self.assertEqual(c.get("Sockeye").following_to, "")


class ItIsNotGatedOnThingsThatDoNotExist(unittest.TestCase):

    def test_not_on_radar(self):
        """`AtcCapability.radar` looked like the natural gate and is dead
        configuration -- `radar = true` is its only occurrence in either theatre
        file and nothing sets it false. Gating on a dial nobody turns is a
        branch that has never run."""
        import re
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "config" / "theatres"
        for f in root.glob("*.toml"):
            with self.subTest(theatre=f.name):
                self.assertEqual(
                    re.findall(r"^radar\s*=\s*false", f.read_text(), re.M), [],
                    "a theatre turns radar off -- the gate may now be real")

    def test_not_on_having_a_flight_plan(self):
        c = seat()
        c.request_following("Sockeye", wants="flight following direct BAR")
        self.assertTrue(c.get("Sockeye").following)


if __name__ == "__main__":
    unittest.main()
