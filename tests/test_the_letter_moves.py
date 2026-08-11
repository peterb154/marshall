"""The information letter is a fact about a SORTIE, and it never moved.

    "But again, I still have never heard anything but information Alpha.. im
     not sure its rotating today."

It was not. Both aerodromes read Alpha and had done for hours, while
`broadcast.first_letter` -- written precisely so that a field is "already
broadcasting when you tune it" -- would have given Batumi SIERRA and Kobuleti
FOXTROT. So the rows predated that function, and nothing could replace them.

THREE MECHANISMS, none wrong alone, welding one value in place:

  * `first_letter` runs only when the stored letter is EMPTY, and once a row
    exists it is never empty again.
  * a bridge restart re-records the SAME letter, which is right in itself -- a
    pilot who copied Alpha two minutes ago has not been overtaken by an hour.
  * hourly rotation demanded a PREVIOUS observation, which is None on the first
    tick after every restart, and this bridge restarts far more often than
    hourly.

Together: a value written once that outlives the world it described, which is
docs/STATE.md's subject one table further along than #119 found it. The letter
is keyed on the mission instance now, so a new sortie has no row and the
derivation takes over.
"""

import unittest

from marshall.atis import broadcast as B


class TestTheFirstLetterIsNotAlways(unittest.TestCase):

    def test_two_aerodromes_are_never_in_step(self):
        # The whole point of deriving it. Two fields reading the same letter is
        # the symptom that started this, and it is what a constant looks like.
        self.assertNotEqual(B.first_letter("Batumi", 0),
                            B.first_letter("Kobuleti", 0))

    def test_it_is_not_alpha_just_because_we_just_started(self):
        # "A real one has been broadcasting all day and is on whatever letter
        # that many hours have taken it to."
        got = {B.first_letter(f, h * 3600)
               for f in ("Batumi", "Kobuleti", "Kutaisi")
               for h in range(0, 24)}
        self.assertGreater(len(got), 6, "the letter barely moves")

    def test_it_is_stable_across_a_restart(self):
        # DERIVED, NOT RANDOM: a pilot who copied Bravo on the ramp and heard
        # Delta ten minutes later would be right to report it as a bug.
        self.assertEqual(B.first_letter("Batumi", 5 * 3600),
                         B.first_letter("Batumi", 5 * 3600))

    def test_it_advances_through_the_day(self):
        self.assertNotEqual(B.first_letter("Batumi", 0),
                            B.first_letter("Batumi", 3 * 3600))


class TestAnHourPassesWhetherWeWereRunningOrNot(unittest.TestCase):
    """The half of the fault that survived a restart."""

    class _Obs:
        def same_as(self, other):
            return True

    def test_an_old_recording_rotates_with_no_previous_observation(self):
        # THE BUG. `previous_obs` is the loop's memory of the last weather it
        # saw, so it is None on the first tick after a restart -- and requiring
        # it meant the hourly rotation was unreachable for a process that
        # restarts more often than hourly.
        self.assertTrue(B.due_for_rotation(self._Obs(), None, 7200.0))

    def test_a_fresh_recording_does_not(self):
        self.assertFalse(B.due_for_rotation(self._Obs(), None, 60.0))

    def test_nothing_on_the_air_is_not_a_rotation(self):
        # The first recording wants Alpha's derived equivalent, not Bravo.
        self.assertFalse(B.due_for_rotation(self._Obs(), None, None))

    def test_changed_weather_still_rotates_inside_the_hour(self):
        class Moved:
            def same_as(self, other):
                return False
        self.assertTrue(B.due_for_rotation(Moved(), self._Obs(), 60.0))


if __name__ == "__main__":
    unittest.main()
