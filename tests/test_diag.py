"""The live diagnostics page, and the one comparison in it that can be wrong.

    "I'll bet if I could see state machine info I'd know why / when things are
     going wrong."

Most of `kneeboard/diag.py` is assembly -- read the recorder, read the scope,
hand both to a template. The part worth guarding is `_on_scope`, which decides
whether an entry on the deterministic engine's board is something radar can
actually see. Everything the page claims about ghosts rests on it.

IT IS THE COMPARISON THAT HAS ALREADY BEEN GOT WRONG ONCE. Finding 1.1 of the
29 July audit is `release_stale` testing a set of printed radar names against
board keys:

    here = {_key_name(u.name) for u in identity.units_on(scope)}
    if ac.radar_identified or _key_name(cs) in here:

`u.name` is what radar prints -- `362nd_sockeye`. `cs` is a board key -- a
spoken callsign, a handle or a flight name. On a real scope line the two never
match, so the clause was dead and the stale entry it existed to remove was
immortal. A diagnostics page that repeated the same mistake would report every
aircraft as a ghost and be worse than no page at all.
"""

import unittest

from marshall.kneeboard import diag

# A real scope line, in the shape the director actually renders: the label is
# the PLAYER name, the bracketed tag is the callsign something has correlated,
# and neither is the spoken callsign the board is keyed on.
SCOPE = ("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 8.0 nm on the 281 "
         "radial, 4,659 ft, heading 026, 180 knots | "
         "362nd_Andre-1 (P-51D-30-NA, manned): 12.0 nm on the 300 radial, "
         "5,000 ft, heading 062, 200 knots")


def units():
    from marshall.atc import identity
    return identity.units_on(SCOPE)


def labels():
    return {diag._key(u.callsign) for u in units() if u.callsign}


class TestIsThisBoardEntryReal(unittest.TestCase):
    def on_scope(self, cs):
        return diag._on_scope(cs, units(), labels())

    def test_the_bracketed_callsign_counts(self):
        """The normal case once the agent has correlated him: the board says
        Pony 1-1 and radar is printing that tag."""
        self.assertTrue(self.on_scope("Pony 1-1"))

    def test_the_handle_counts(self):
        """THE ONE release_stale MISSED. The board can be keyed on a handle
        while radar prints the squadron name it came from."""
        self.assertTrue(self.on_scope("sockeye"))
        self.assertTrue(self.on_scope("Andre"))

    def test_the_raw_unit_name_counts(self):
        self.assertTrue(self.on_scope("362nd_sockeye"))

    def test_somebody_radar_cannot_see_is_a_ghost(self):
        """The entry that costs a sortie: a leftover from an earlier flight,
        holding a level in the stack with nobody flying it."""
        self.assertFalse(self.on_scope("Falcon 1-1"))

    def test_an_empty_callsign_is_not_quietly_accounted_for(self):
        self.assertFalse(self.on_scope(""))

    def test_an_empty_scope_makes_everyone_a_ghost_not_nobody(self):
        """Radar down and the board full is a REAL divergence and must show as
        one. Reporting 'all clear' because the scope is empty would hide the
        exact case a pilot needs to see."""
        self.assertFalse(diag._on_scope("Pony 1-1", [], set()))


class TestReplayingTheRoster(unittest.TestCase):
    """The flight panel is rebuilt from the verdicts, not from a live roster --
    the roster lives in the bridge's RAM and this page never touches it."""

    def test_create_join_and_leave(self):
        got = diag._flights_from([
            {"kind": "flight/created", "callsign": "Apex", "who": "Sockeye"},
            {"kind": "flight/joined", "callsign": "Apex", "who": "Andre", "miles": 0.2},
            {"kind": "flight/joined", "callsign": "Apex", "who": "Shooter", "miles": 0.4},
            {"kind": "flight/left", "callsign": "Apex", "who": "Shooter"},
        ])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["lead"], "Sockeye")
        self.assertEqual(got[0]["members"], ["Andre"])

    def test_losing_the_lead_dissolves_it(self):
        got = diag._flights_from([
            {"kind": "flight/created", "callsign": "Apex", "who": "Sockeye"},
            {"kind": "flight/joined", "callsign": "Apex", "who": "Andre"},
            {"kind": "flight/left", "callsign": "Apex", "who": "Sockeye"},
        ])
        self.assertEqual(got, [])

    def test_a_refusal_does_not_put_him_in_the_flight(self):
        got = diag._flights_from([
            {"kind": "flight/created", "callsign": "Apex", "who": "Sockeye"},
            {"kind": "flight/refused", "callsign": "Apex", "who": "Shooter",
             "miles": 8.9},
        ])
        self.assertEqual(got[0]["members"], [])

    def test_joining_a_flight_that_was_never_created_is_ignored(self):
        self.assertEqual(diag._flights_from(
            [{"kind": "flight/joined", "callsign": "Bolt", "who": "Andre"}]), [])


class TestTheStateItHandsThePage(unittest.TestCase):
    def test_it_survives_no_recorder_and_no_radar(self):
        """A page that 500s when nothing is flying is a page nobody trusts when
        something is."""
        st = diag.state(session="does-not-exist", scope="")
        self.assertEqual(st["radios"], [])
        self.assertEqual(st["board"], [])
        self.assertEqual(st["ghosts"], [])
        self.assertFalse(st["radar_ok"])

    def test_the_scope_is_parsed_with_the_shared_parser(self):
        """Not a sixth regex. The 29 July audit counted five parsers of this
        one string already; adding another is how they drift."""
        st = diag.state(session="does-not-exist", scope=SCOPE)
        self.assertEqual({u["name"] for u in st["scope"]},
                         {"362nd_sockeye", "362nd_Andre-1"})
        self.assertTrue(all(u["manned"] for u in st["scope"]))


if __name__ == "__main__":
    unittest.main()
