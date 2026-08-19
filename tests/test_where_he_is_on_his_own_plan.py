"""Which leg he is flying, from his own filed steerpoints and radar.

    "we haven't messed with the in-route routing yet much, but obviously she
     doesn't know where those waypoints are and where I'm at on my flight plan"

    "I would expect that since my flight plan steerpoints have coordinates, the
     system can figure out where I am relative to my steer point and which leg
     im on"

The engine measured range from the FIELD and nothing else. Asked what his next
steerpoint was, a controller answered off the theatre file (#188); asked again
after landing, it named the first fix of the plan he had just flown.

THE ROUTE USED HERE IS THE ONE HE ACTUALLY FLEW, and its shape is the whole
reason this file is long: FOO -> BAR -> SPAM -> INITIAL -> BATUMI turns through
nearly 180 degrees at BAR. Every simple rule works on a straight line and this
plan is not one.

THREE ALGORITHMS WERE TRIED. The first two are recorded because both looked
obviously right and both failed on real coordinates:

    each fix tested independently,   standing exactly ON FOO read as "past
    abeam by projection              INITIAL, next fix BATUMI". The
                                     perpendicular through a fix four legs
                                     later, pointing somewhere else entirely,
                                     was already behind him. An abeam test is a
                                     statement about ONE leg

    sequential walk, abeam by        the BAR-SPAM midpoint read as "past FOO,
    "closer to the next fix          next fix BAR". "Closer to the next" only
     than to this one"               becomes true past the leg's MIDPOINT, so
                                     it lagged half a leg, every leg

Both were proxies for the question. The question is which leg he is on, and the
answer is the leg he is NEAREST -- by distance to the SEGMENT, which is the
only measure that survives a route that turns.

AND THEN THE CASE NEITHER OF THEM HAD: he is not on the route at all. On the
ramp at Kobuleti, seventeen miles from the first fix, nearest-leg picked
whichever leg was least far and answered "past BAR, next fix SPAM" before the
engine was running. Off the route, only the nearest FIX means anything.

STATELESS, and that is a requirement rather than a nicety. Everything here is a
pure function of (legs, position), so a restart, a dropped radar frame or a
reconnect cannot lose his place -- see docs/STATE.md.  [#199]
"""

from __future__ import annotations

import unittest

from marshall.atc import progress as P

# HIS PLAN, as filed. Coordinates are the real ones off the live board.
FOO = {"fix": "FOO", "lat": 42.022767, "lon": 42.217717, "alt_ft": 5000}
BAR = {"fix": "BAR", "lat": 42.185800, "lon": 42.094117, "alt_ft": 10000}
SPAM = {"fix": "SPAM", "lat": 42.127000, "lon": 41.256000, "alt_ft": 10000}
IAF = {"fix": "INITIAL", "lat": 41.917000, "lon": 41.138000, "alt_ft": 5000}
BATUMI = {"fix": "BATUMI", "lat": 41.609594, "lon": 41.600234, "alt_ft": 0}
PLAN = {"legs": [FOO, BAR, SPAM, IAF, BATUMI]}

KOBULETI = (41.929922, 41.863275)      # the ramp he departs from


def midway(a: dict, b: dict) -> tuple[float, float]:
    return (a["lat"] + b["lat"]) / 2, (a["lon"] + b["lon"]) / 2


class HeIsWhereTheRouteSaysHeIs(unittest.TestCase):

    def leg(self, lat, lon):
        got = P.where(PLAN, lat, lon)
        self.assertIsNotNone(got)
        return got

    def test_on_the_ramp_the_first_fix_is_next(self):
        """The departure case, and the one nearest-leg gets wrong on its own:
        he is seventeen miles from FOO and not on any leg."""
        got = self.leg(*KOBULETI)
        self.assertEqual(got.to_fix, "FOO")
        self.assertEqual(got.from_fix, "")
        self.assertEqual(got.reached, ())

    def test_at_a_fix_it_is_behind_him_and_the_next_is_ahead(self):
        for at, nxt in ((FOO, "BAR"), (BAR, "SPAM"),
                        (SPAM, "INITIAL"), (IAF, "BATUMI")):
            with self.subTest(at["fix"]):
                got = self.leg(at["lat"], at["lon"])
                self.assertEqual(got.from_fix, at["fix"])
                self.assertEqual(got.to_fix, nxt)

    def test_midway_along_a_leg_names_that_leg(self):
        """The half-leg lag that killed the second algorithm."""
        for a, b in ((FOO, BAR), (BAR, SPAM), (SPAM, IAF), (IAF, BATUMI)):
            with self.subTest(f"{a['fix']}->{b['fix']}"):
                got = self.leg(*midway(a, b))
                self.assertEqual(got.from_fix, a["fix"])
                self.assertEqual(got.to_fix, b["fix"])

    def test_the_turn_at_BAR_does_not_throw_it_forward(self):
        """The route reverses direction here, which is what made an
        independent abeam test read the whole plan as flown."""
        got = self.leg(FOO["lat"], FOO["lon"])
        self.assertNotIn("INITIAL", got.reached)
        self.assertEqual(got.to_fix, "BAR")

    def test_at_the_destination_the_route_is_complete(self):
        got = self.leg(BATUMI["lat"], BATUMI["lon"])
        self.assertTrue(got.done)
        self.assertEqual(got.from_fix, "BATUMI")
        self.assertEqual(got.nm_to_next, None)

    def test_the_distance_is_to_the_NEXT_fix_and_not_the_field(self):
        """The whole point. Range from the field is what the engine already
        had and is not what a pilot asked for."""
        got = self.leg(*midway(FOO, BAR))
        self.assertLess(got.nm_to_next, 12)


class WhenItCannotSayItSaysNothing(unittest.TestCase):
    """#197's rule, one module over: an engine that cannot place him must not
    answer from somewhere else."""

    def test_no_plan(self):
        self.assertIsNone(P.where({}, 41.9, 41.8))
        self.assertIsNone(P.where(None, 41.9, 41.8))

    def test_no_radar_fix(self):
        self.assertIsNone(P.where(PLAN, None, None))

    def test_legs_without_coordinates_are_skipped_not_guessed(self):
        plan = {"legs": [{"fix": "NOWHERE"}, FOO, BAR]}
        got = P.where(plan, *midway(FOO, BAR))
        self.assertEqual(got.to_fix, "BAR")

    def test_and_the_spoken_form_is_empty_rather_than_wrong(self):
        self.assertEqual(P.spoken(None), "")


class ItIsAFactAndNotAClearance(unittest.TestCase):
    """It answers; it does not decide. Nothing here moves a phase, issues
    anything, or contradicts a pilot -- see the module docstring."""

    def test_the_spoken_line_carries_the_fix_and_the_range(self):
        said = P.spoken(P.where(PLAN, *midway(BAR, SPAM)))
        self.assertIn("SPAM", said)
        self.assertIn("past BAR", said)

    def test_it_issues_nothing(self):
        import inspect
        src = inspect.getsource(P)
        for verb in ("cleared", "clearance", "assign", "phase"):
            with self.subTest(verb):
                self.assertNotIn(f"{verb} ", src.split('"""')[-1])


if __name__ == "__main__":
    unittest.main()
