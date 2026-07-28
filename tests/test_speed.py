"""Telling an aeroplane to slow down.

    "An airplane going any speed should get sequenced. If that's not
     reasonable, have the controller tell the aircraft to slow down. It's not
     reasonable to fly an approach at 500 kts anyway."

route.py has always known what speed each leg wants -- `speed_kt_at`, which the
descent planner and the mission's AI tasking both read -- and the controller had
no way to SAY it. So an F-16 arriving at three hundred knots was vectored as
though it were a Mustang at a hundred and fifty, and the base turn that works at
pattern speed overshoots at twice it (#39).

Speed is the cheapest instrument a controller has, and the realistic one: real
approach control assigns it on nearly every vector.
"""

import unittest
from dataclasses import dataclass

from marshall.atc import agent_atc as A
from marshall.atc import controller as C


@dataclass
class G:
    speed_kt: float = 0.0


@dataclass
class P:
    speed_kt: float = 0.0


class TestSayingASpeed(unittest.TestCase):
    def test_a_speed_is_not_a_heading(self):
        """spell_hdg pads to three figures. Ninety knots read as "zero nine
        zero" sounds like a heading, and a pilot reaching for the wrong
        instrument is the whole cost of borrowing the function."""
        self.assertEqual(C.spell_speed(180), "one eight zero")
        self.assertEqual(C.spell_speed(90), "nine zero")

    def test_rounded_to_something_a_controller_would_assign(self):
        self.assertEqual(C.spell_speed(183), "one eight zero")


class TestWhenItIsSaid(unittest.TestCase):
    def setUp(self):
        A._speed_asked.clear()

    def test_a_fast_aeroplane_is_asked_to_slow_down(self):
        said = A.speed_instruction(G(180), P(300), "Pony 1-1", now=1000.0)
        self.assertIn("reduce speed to one eight zero knots", said)

    def test_an_aeroplane_already_at_speed_is_left_alone(self):
        """An instruction to slow down issued to somebody already at approach
        speed is a controller who cannot see."""
        self.assertEqual(A.speed_instruction(G(180), P(175), "x", now=1000.0), "")

    def test_slightly_fast_is_fast_not_wrong(self):
        self.assertEqual(A.speed_instruction(G(180), P(200), "x", now=1000.0), "")

    def test_nothing_is_said_without_a_real_groundspeed(self):
        """Guessing would be worse than silence: the sim does not always give
        one, and a speed we invented is a speed he is judged against."""
        self.assertEqual(A.speed_instruction(G(180), P(0), "x", now=1000.0), "")
        self.assertEqual(A.speed_instruction(G(180), None, "x", now=1000.0), "")

    def test_nothing_is_said_where_the_leg_wants_no_speed(self):
        self.assertEqual(A.speed_instruction(G(0), P(400), "x", now=1000.0), "")


class TestItIsNotRepeatedEverySweep(unittest.TestCase):
    """The failure mode of anything computed per transmission.

    The guidance is recomputed on every call, so an unguarded instruction goes
    out in every single one -- and a controller who says "reduce speed" six
    times in ninety seconds reads as one who is not listening.
    """

    def setUp(self):
        A._speed_asked.clear()

    def test_said_once_then_left_alone(self):
        first = A.speed_instruction(G(180), P(300), "Pony 1-1", now=1000.0)
        again = A.speed_instruction(G(180), P(300), "Pony 1-1", now=1010.0)
        self.assertTrue(first)
        self.assertEqual(again, "")

    def test_repeated_if_he_still_has_not_complied(self):
        A.speed_instruction(G(180), P(300), "Pony 1-1", now=1000.0)
        later = A.speed_instruction(G(180), P(300), "Pony 1-1",
                                    now=1000.0 + A.SPEED_REPEAT_SEC + 1)
        self.assertTrue(later)

    def test_a_new_speed_is_issued_immediately(self):
        """Waiting out the timer to assign a DIFFERENT speed would leave him
        flying the old one through the leg it was wrong for."""
        A.speed_instruction(G(210), P(320), "Pony 1-1", now=1000.0)
        now = A.speed_instruction(G(150), P(320), "Pony 1-1", now=1005.0)
        self.assertIn("one five zero", now)

    def test_each_aeroplane_is_tracked_separately(self):
        A.speed_instruction(G(180), P(300), "Pony 1-1", now=1000.0)
        other = A.speed_instruction(G(180), P(300), "Pony 1-2", now=1001.0)
        self.assertTrue(other)


if __name__ == "__main__":
    unittest.main()
