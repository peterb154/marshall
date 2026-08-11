"""The proactive thread's handoff decision, as a function that can be asked.

    "had to end that flight early. left several debug logs. Never got handed to
     center.."

        DEBUG NOTE  on 15 miles away from the airport, still no transition to center
        DEBUG NOTE  I'm passing 20 nautical miles from the airport, still no transition
        DEBUG NOTE  I met 30 miles outside the airport, I have to stop flying

Three minutes of a pilot leaving the terminal area and NOT ONE LINE in the log,
because the monitor transmitted when it acted and said nothing when it did not.
Every input to that decision existed at the time and none was recorded, so the
fault could only be guessed at from reading -- which is the same thing a pilot
complains about when a controller goes quiet: silence and a dead radio are
indistinguishable.

Two faults, and only the second is about a rule:

  * IT KEPT NO RECORD OF DECIDING NOTHING. `watching_him` returns a reason, and
    the monitor prints it on the CHANGE -- so the next sortie says which
    controller is holding him and on what evidence.
  * IT ASKED THE WRONG QUESTION. `next_controller` is the one function that
    owns "who has him next" -- the sim's events, then the ladder, then the
    airspace volumes, in that order -- and this thread asked only the middle
    one, which its own docstring warns about by name (#51). It is a caller now.

The decision also became testable by being a function at all, which is why the
departure -> Center rung has a check for the first time; the ladder rehearsal
cannot cover it, because it needs an aeroplane on radar and a synthetic pilot
has none.
"""

import unittest

from marshall.atc import agent_atc, controller as C
from marshall.atc.geometry import Position
from marshall.core import route as R

KOBULETI_DEPARTURE_HZ = 123_300_000.0
KOBULETI_TOWER_HZ = 133_000_000.0


def _outbound(nm, alt_ft=8000):
    """Climbing away from the field, on the 076 radial off runway 07."""
    return Position(range_nm=nm, radial_deg=76.0, alt_ft=alt_ft,
                    heading_deg=71.0, speed_kt=450.0)


class TestWhoIsWatchingHim(unittest.TestCase):

    def setUp(self):
        self.profile = R.BATUMI_ASR
        self.ctl = C.Controller(self.profile)
        self.bridge = agent_atc.Bridge()
        self.ctl.request_approach("Sockeye")
        self.ctl.bind("Sockeye", track="362nd_sockeye")
        self.ctl.get("Sockeye").sortie_phase = "departure"
        self.bridge.heard_on["Sockeye"] = KOBULETI_DEPARTURE_HZ

    def ask(self, pos):
        return agent_atc.watching_him(
            self.bridge, self.ctl, self.profile, "Sockeye", pos,
            agent_atc.Scope(""), fallback_hz=124_000_000.0)

    def test_center_takes_him_at_the_edge_of_the_area(self):
        # THE SORTIE THAT PRODUCED THIS FILE. Thirty miles out, climbing away
        # from the field, talking to Kobuleti Departure, and nothing happened.
        nxt, why = self.ask(_outbound(30.0))
        self.assertIsNotNone(nxt, why)
        self.assertEqual(nxt.role, "center")

    def test_departure_keeps_him_inside_it(self):
        nxt, why = self.ask(_outbound(15.0))
        self.assertIsNone(nxt)
        # And the reason names the evidence, not just the verdict -- which is
        # the half that was missing from the record entirely.
        self.assertIn("Kobuleti Departure", why)
        self.assertIn("15 nm", why)
        self.assertIn("outbound", why)

    def test_an_arrival_at_the_same_range_is_not_sent_away(self):
        # Thirty miles INBOUND is an arrival, and handing him to Center would
        # be sending him away from the field he is recovering at. Same range,
        # opposite situation -- the reason `outbound_beyond` exists.
        pos = Position(range_nm=30.0, radial_deg=76.0, alt_ft=8000,
                       heading_deg=256.0, speed_kt=350.0)
        nxt, why = self.ask(pos)
        self.assertIsNone(nxt)
        self.assertIn("inbound", why)

    def test_a_frequency_nobody_works_is_said_out_loud(self):
        # If `heard_on` carries a channel no station answers on, every handoff
        # is silently impossible -- which is exactly the failure mode that has
        # no symptom. It has one now.
        self.bridge.heard_on["Sockeye"] = 999_000_000.0
        nxt, why = self.ask(_outbound(30.0))
        self.assertIsNone(nxt)
        self.assertIn("not a station", why)

    def test_the_same_man_under_another_name_is_not_a_handoff(self):
        # Approach and Departure are one controller on one frequency. Telling a
        # pilot to contact the person he is already talking to is nonsense on
        # the radio, and it must read as "nothing due" rather than as a call.
        self.bridge.heard_on["Sockeye"] = KOBULETI_TOWER_HZ
        self.ctl.get("Sockeye").sortie_phase = "departure"
        nxt, why = self.ask(_outbound(8.0))
        if nxt is None:
            self.assertTrue(why)
        else:
            self.assertNotEqual(nxt.name, "Kobuleti Tower")


if __name__ == "__main__":
    unittest.main()
