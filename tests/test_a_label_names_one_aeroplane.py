"""A name that names two aeroplanes is not a name.

Reproduced live on 29 August with two AI aircraft in the world:

    label='1'  name='Traffic 1-1'
    label='1'  name='Traffic 2-1'

`label` is what `Scope.of` matches first and what `contacts()` keys bindings
by, so one aeroplane's binding reached the other and a lookup returned
whichever the poll listed first.
"""
import unittest

from marshall.atc.agent_atc import Scope
from marshall.core.names import label_for


def _label(name, callsign="", player_name=""):
    """As the feed calls it. NOT through `marshall.feed.tracks`: importing that
    binds the gRPC stubs, whose `dcs` package shadows pydcs's, and the first
    version of this test failed twelve unrelated ones by import ORDER."""
    return label_for(player_name, callsign, name)


class ALabelNamesOneAeroplane(unittest.TestCase):

    def test_an_index_is_not_a_callsign(self):
        """What the sim actually returns for AI, and what it did to the pair."""
        a = _label("Traffic 1-1", callsign="1")
        b = _label("Traffic 2-1", callsign="1")
        self.assertEqual(a, "Traffic 1-1")
        self.assertEqual(b, "Traffic 2-1")
        self.assertNotEqual(a, b, "two aircraft, two names")

    def test_a_human_is_named_after_himself(self):
        self.assertEqual(_label("Viper 1-4", callsign="1",
                               player_name="362nd_Sockeye"), "362nd_Sockeye")

    def test_a_real_word_survives(self):
        """Only a bare NUMBER is rejected; a name is still better prose than a
        slot name for an AI flight."""
        self.assertEqual(_label("Enfield11-1", callsign="Enfield11"),
                         "Enfield11")

    def test_a_colliding_label_matches_nobody(self):
        """The guarantee the feed cannot give on its own. Taking the first is a
        real contact at a real range -- the wrong aeroplane."""
        sc = Scope("", contacts=[
            {"label": "1", "name": "Traffic 1-1"},
            {"label": "1", "name": "Traffic 2-1"}], ok=True)
        self.assertIsNone(sc.of("1"))

    def test_but_the_unit_name_still_finds_him(self):
        """`name` is the tracks primary key, so it is unique by construction and
        a caller holding it is never blocked by a label collision."""
        sc = Scope("", contacts=[
            {"label": "1", "name": "Traffic 1-1"},
            {"label": "1", "name": "Traffic 2-1"}], ok=True)
        self.assertEqual(sc.of("Traffic 2-1")["name"], "Traffic 2-1")

    def test_an_unambiguous_label_is_untouched(self):
        sc = Scope("", contacts=[
            {"label": "362nd_Sockeye", "name": "Viper 1-4"},
            {"label": "362nd Shooter", "name": "Viper 1-2"}], ok=True)
        self.assertEqual(sc.of("362nd_sockeye")["name"], "Viper 1-4")


if __name__ == "__main__":
    unittest.main()
