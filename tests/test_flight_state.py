"""The bridge's half of the one aircraft state.

The store itself lives in the director. What is tested here is the seam: that
the strip a controller reads carries what a handoff is supposed to deliver, and
that the separation engine's private phase names are TRANSLATED to the official
list rather than allowed to spread. Two vocabularies for one idea is how three
components ended up disagreeing about what was happening.
"""

import unittest

from marshall.atc import agent_atc, controller as atc, phases


class TestPhaseTranslation(unittest.TestCase):
    def test_every_engine_phase_maps_to_an_official_one(self):
        for engine_name, official in agent_atc._PHASE_OF.items():
            self.assertIn(official, phases.PHASES,
                          f"{engine_name} maps to {official}, which is not a phase")

    def test_every_engine_phase_is_covered(self):
        # A phase the engine can be in but the map does not know would silently
        # become "unknown", losing a clearance that had actually been given.
        for p in atc.Phase:
            self.assertIn(p.name, agent_atc._PHASE_OF, p.name)

    def test_cleared_means_on_the_approach(self):
        # The engine calls it CLEARED; the official list calls it approach.
        self.assertEqual(agent_atc._PHASE_OF["CLEARED"], "approach")

    def test_banished_is_still_holding(self):
        # Sent to the outer hold is a kind of holding, not a state of its own --
        # he is still waiting his turn and still in the sequence.
        self.assertEqual(agent_atc._PHASE_OF["BANISHED"], "holding")


class TestTheStrip(unittest.TestCase):
    """What a handoff delivers. If it is not in the strip, the next controller
    has to ask a pilot who has already answered."""

    FULL = {"callsign": "Pony 1-1", "claimed_size": 3, "intent": "land",
            "destination": "Batumi", "procedure": "batumi-asr", "runway": "13",
            "cleared": "approach", "assigned_ft": 2000,
            "promised": "call him back in five"}

    def test_it_carries_what_the_next_controller_needs(self):
        s = agent_atc.flight_strip(self.FULL)
        for expected in ("Pony 1-1", "flight of 3", "land Batumi",
                         "batumi-asr", "runway 13", "2,000", "promised"):
            self.assertIn(expected, s)

    def test_a_single_ship_is_not_called_a_flight(self):
        s = agent_atc.flight_strip({"callsign": "Viper 1", "claimed_size": 1})
        self.assertNotIn("flight of", s)

    def test_an_unidentified_aircraft_still_gets_a_strip(self):
        # On the radio and unidentified is a real state; it must not vanish.
        s = agent_atc.flight_strip({"claimed_size": 1, "intent": "land"})
        self.assertIn("unidentified", s)

    def test_nothing_known_produces_nothing_rather_than_noise(self):
        self.assertEqual(agent_atc.flight_strip({}), "")

    def test_the_strip_never_carries_a_position(self):
        # Position is the scope's answer. A strip that quoted one would be a
        # second copy going stale, which is the bug the table exists to kill.
        s = agent_atc.flight_strip({**self.FULL, "observed_alt_ft": 7600,
                                    "radar_heading": 124})
        self.assertNotIn("7,600", s)
        self.assertNotIn("7600", s)
        self.assertNotIn("124", s)


class TestWritesNeverBreakTheRadio(unittest.TestCase):
    """A controller who stops talking because Postgres is unreachable is worse
    than one with no memory. An aeroplane on final does not care."""

    def test_a_bind_against_a_dead_store_returns_empty(self):
        self.assertEqual(agent_atc.flight_bind(base="http://127.0.0.1:9", callsign="X"), {})

    def test_agreeing_against_a_dead_store_returns_empty(self):
        self.assertEqual(agent_atc.flight_agree(1, base="http://127.0.0.1:9", cleared="holding"), {})

    def test_no_flight_id_is_a_no_op_not_an_error(self):
        self.assertEqual(agent_atc.flight_agree(None, cleared="holding"), {})
