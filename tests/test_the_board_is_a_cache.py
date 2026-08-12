"""The table is the source of truth; the board is a write-through cache. [#120]

    "there really shouldn't be much in memory data structures - we addressed
     this - database is fast and should be the single source of truth"

`Controller.aircraft` was built only by transmissions, so a bridge restarted
mid-sortie began knowing nothing: every rung a pilot had climbed, every level
assigned, every approach flown, forgotten, while the aeroplanes went on flying.

It was worse than forgetful. With an empty letdown the restored controller would
clear a SECOND aircraft onto an approach the first was already flying -- the
accident the whole engine exists to prevent, caused by the recovery from a
restart.

Four of the things the board remembers had no column at all (migration 026):
`sortie_phase` -- which decides who owns him -- plus `on_visual`,
`approaches_flown` and `atis_letter`.
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as atc
from marshall.core import route as R


def row(**kw):
    """A `flight_state` row, as the bridge reads it back."""
    base = {"callsign": "Pony 1-1", "claimed_size": 1, "cleared": "unknown",
            "sortie_phase": "", "on_visual": False, "approaches_flown": 0,
            "atis_letter": "", "intent": "", "track_name": "",
            "radar_identified": False, "assigned_ft": None, "cruise_ft": None,
            "cleared_approach": None}
    base.update(kw)
    return base


class ARestartLosesNothing(unittest.TestCase):

    def setUp(self):
        self.c = atc.Controller(R.BATUMI_ASR)

    def test_the_rung_he_is_on(self):
        """`sortie_phase` is what `handoff.due` reads to decide who owns him.
        Losing it loses the entire ground half of a sortie."""
        self.c.hydrate([row(sortie_phase="holding_short")])
        self.assertEqual(self.c.get("Pony 1-1").sortie_phase, "holding_short")

    def test_the_level_he_was_given(self):
        self.c.hydrate([row(cleared="holding", assigned_ft=6000)])
        ac = self.c.get("Pony 1-1")
        self.assertEqual(ac.assigned_ft, 6000)
        self.assertIs(ac.phase, atc.Phase.HOLDING)

    def test_that_he_is_flying_it_himself(self):
        """A restart that forgets this starts reading ranges to a man looking
        out of the window."""
        self.c.hydrate([row(on_visual=True)])
        self.assertTrue(self.c.get("Pony 1-1").on_visual)

    def test_how_many_approaches_he_has_flown(self):
        """What a second missed approach is counted against."""
        self.c.hydrate([row(approaches_flown=2)])
        self.assertEqual(self.c.get("Pony 1-1").approaches, 2)

    def test_what_he_said_he_wanted(self):
        self.c.hydrate([row(intent="VFR to Batumi, visual 13")])
        self.assertEqual(self.c.get("Pony 1-1").wants,
                         "VFR to Batumi, visual 13")

    def test_and_which_information_he_has(self):
        self.c.hydrate([row(atis_letter="Bravo")])
        self.assertEqual(self.c.get("Pony 1-1").atis_letter, "Bravo")


class TheLetdownComesBackWithHim(unittest.TestCase):
    """The dangerous half. An aircraft restored as CLEARED must be restored as
    the man ON the approach, or the next arrival is cleared into him."""

    def test_a_cleared_aircraft_holds_the_letdown(self):
        c = atc.Controller(R.BATUMI_ASR)
        c.hydrate([row(callsign="Lead 1", cleared="approach")])
        ac = c.get("Lead 1")
        self.assertIs(ac.phase, atc.Phase.CLEARED)
        self.assertEqual(c._in_letdown(ac), "Lead 1")

    def test_so_the_next_arrival_is_HELD_and_not_cleared_into_him(self):
        c = atc.Controller(R.BATUMI_ASR)
        c.hydrate([row(callsign="Lead 1", cleared="approach")])
        c.report_beacon("Two 1", 9000)
        self.assertIs(c.get("Two 1").phase, atc.Phase.HOLDING,
                      "a restart cleared two aircraft onto one approach")


class ItRestoresNoPosition(unittest.TestCase):
    """Radar's, reconciled every sweep. A board that remembered a position
    across a restart would assert where an aeroplane was minutes ago."""

    def test_no_position_field_is_written(self):
        import inspect
        src = inspect.getsource(atc.Controller.hydrate)
        for word in ("lat", "lon", "alt_ft", "observed", "speed", "heading"):
            self.assertNotIn(f'row.get("{word}")', src)

    def test_radar_identified_is_taken_from_the_scope_not_remembered(self):
        """It comes off the view's join against `tracks`, so it is current by
        construction rather than restored."""
        c = atc.Controller(R.BATUMI_ASR)
        c.hydrate([row(radar_identified=True)])
        self.assertTrue(c.get("Pony 1-1").radar_identified)


class OneMappingBetweenThePhaseAndItsWord(unittest.TestCase):
    """It lived in `agent_atc` and was needed in both directions the moment the
    board could be rebuilt. Two copies of a translation is how the two come to
    disagree about what "approach" means."""

    def test_the_bridge_uses_the_controllers_mapping(self):
        from marshall.atc import agent_atc as A
        self.assertIs(A._PHASE_OF, atc.PHASE_WORD)

    def test_every_word_round_trips(self):
        for name, word in atc.PHASE_WORD.items():
            if name == "BANISHED":
                continue           # shares "holding" -- documented, deliberate
            self.assertEqual(atc.PHASE_FROM_WORD[word], name)


if __name__ == "__main__":
    unittest.main()


class ARowFromAFinishedSortie(unittest.TestCase):
    """#136 -- the board restores the recent past, not the distant past.

    On 12 August a pilot flew Kobuleti to Batumi on the ILS and picked up the
    03:00 sortie's state the moment the engine engaged: intent 'asr approach',
    phase CLEARED, an assigned altitude of 4,000 nobody had given him. The row
    was simply still there -- `flights` is keyed on (mission, callsign) and a
    mission instance outlives every sortie flown inside it.
    """

    def rows(self, age_sec):
        import datetime as dt
        when = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=age_sec)
        return [{"callsign": "Sockeye", "intent": "asr approach",
                 "cleared": "cleared", "assigned_ft": 4000,
                 "sortie_phase": "approach", "updated_at": when.isoformat()}]

    def test_an_hour_old_row_is_not_somebody_flying(self):
        ctl = atc.Controller(profile=R.BATUMI_ASR)
        self.assertEqual(ctl.hydrate(self.rows(3600)), 0)
        self.assertEqual(ctl.aircraft, {})
        self.assertEqual(ctl.skipped_stale, ["Sockeye"])

    def test_a_bridge_restart_mid_sortie_is_still_invisible(self):
        """The reason the cache exists. Seconds old is a restart, not a sortie."""
        ctl = atc.Controller(profile=R.BATUMI_ASR)
        self.assertEqual(ctl.hydrate(self.rows(20)), 1)
        self.assertEqual(ctl.skipped_stale, [])
        self.assertEqual(ctl.aircraft[ctl._resolve("Sockeye")].wants,
                         "asr approach")

    def test_a_row_with_no_timestamp_is_restored(self):
        """Absence is 'we do not know', and the safe answer is what we did
        before -- every hand-built row in the tests and rehearsals omits it."""
        ctl = atc.Controller(profile=R.BATUMI_ASR)
        self.assertEqual(ctl.hydrate([{"callsign": "Sockeye"}]), 1)
        self.assertEqual(ctl.skipped_stale, [])
