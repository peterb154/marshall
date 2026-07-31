"""The scoring half of the crowded-frequency measurement.

The expensive half needs SRS, Polly, Whisper, Bedrock and a running bridge. The
half that decides what the numbers MEAN is pure, so it is tested here -- a
scoring rule that can only be exercised by flying is a scoring rule nobody
checks, and a harness that reports the wrong number is worse than no harness,
because a wrong number is believed.
"""

import unittest

from marshall.radio import crowd

ROSTER = {"Pony 1-1", "Pony 1-2", "Hoover 1-1"}
RADIOS = {"Sockeye", "Bandit", "Ranger"}


def board(t, *rows):
    return {"t": t, "kind": "board", "board": list(rows)}


def entity(cs, identified=False, letdown=False):
    return {"callsign": cs, "phase": "HOLDING", "assigned_ft": 4000,
            "identified": identified, "members": [], "approaches": 0,
            "in_letdown": letdown}


class TestOneTransmission(unittest.TestCase):
    def test_the_right_aeroplane(self):
        self.assertEqual(
            crowd.classify("Pony 1-1", "Pony 1-1", ROSTER, RADIOS),
            crowd.CORRECT)

    def test_unattributed_is_a_success_not_a_failure(self):
        """A guard fired and nothing moved.

        Worth stating because it is counter-intuitive in a scoreboard: a
        transmission the system declined to attribute changed nobody's altitude
        and nobody's place in the queue. "Say again" is a controller doing his
        job."""
        self.assertEqual(crowd.classify("Pony 1-1", "", ROSTER, RADIOS),
                         crowd.DROPPED)

    def test_the_radio_name_means_not_yet_identified(self):
        """The recorder writes the SRS client name when nothing resolved, so
        the radio names have to be known or an unbound pilot scores as a ghost."""
        self.assertEqual(crowd.classify("Pony 1-1", "Sockeye", ROSTER, RADIOS),
                         crowd.DROPPED)

    def test_somebody_elses_state_moved(self):
        """The failure that matters. Not noise -- a separation error."""
        self.assertEqual(
            crowd.classify("Pony 1-2", "Pony 1-1", ROSTER, RADIOS),
            crowd.MISATTRIBUTED)

    def test_an_aeroplane_was_invented(self):
        self.assertEqual(
            crowd.classify("Pony 1-2", "Maintained 2", ROSTER, RADIOS),
            crowd.GHOST)


class TestGhostCensus(unittest.TestCase):
    def test_identified_once_is_not_a_ghost(self):
        """Radar contact is not required on every sweep -- he can fade behind
        terrain. Having been seen ONCE is what separates an aeroplane from a
        sentence."""
        c = crowd.ghost_census([
            board(1.0, entity("Pony 1-1", identified=False)),
            board(2.0, entity("Pony 1-1", identified=True)),
            board(3.0, entity("Pony 1-1", identified=False)),
        ])
        self.assertFalse(c["Pony 1-1"]["ghost"])

    def test_never_identified_is_a_ghost(self):
        c = crowd.ghost_census([
            board(10.0, entity("Maintained 2")),
            board(70.0, entity("Maintained 2")),
        ])
        self.assertTrue(c["Maintained 2"]["ghost"])
        self.assertEqual(c["Maintained 2"]["seconds"], 60.0)
        self.assertEqual(c["Maintained 2"]["transmissions"], 2)

    def test_a_ghost_holding_the_letdown_is_flagged(self):
        """This is the live failure: something that was never on radar took the
        letdown and a real pilot was held behind it."""
        c = crowd.ghost_census([board(1.0, entity("Maintained 2", letdown=True))])
        self.assertTrue(c["Maintained 2"]["held_letdown"])

    def test_a_known_roster_name_is_never_a_ghost(self):
        """A synthetic run knows who was really flying, and an aeroplane radar
        simply never painted is not evidence of an invented one."""
        c = crowd.ghost_census([board(1.0, entity("Pony 1-1"))],
                               real={"Pony 1-1"})
        self.assertFalse(c["Pony 1-1"]["ghost"])

    def test_the_words_that_made_it_are_named(self):
        """A ghost is made of words; a report that cannot name them is not
        actionable."""
        entries = [
            {"t": 1.0, "kind": "pilot", "transcript": "Pony one one, roger"},
            board(1.1, entity("Pony 1-1", identified=True)),
            {"t": 2.0, "kind": "pilot", "transcript": "maintained 2 thousand"},
            board(2.1, entity("Pony 1-1", identified=True),
                  entity("Maintained 2")),
        ]
        self.assertEqual(crowd.created_by(entries, "Maintained 2"),
                         "maintained 2 thousand")

    def test_an_empty_recording_is_not_a_finding(self):
        self.assertEqual(crowd.ghost_census([]), {})


class TestTheRoster(unittest.TestCase):
    def test_the_names_are_actually_confusable(self):
        """The point of the fleet. Distinct names would make this a test of
        nothing: a controller who can tell Pony from Viper proves nothing about
        one who has to tell Pony 1-1 from Pony 1-2."""
        canon = [r[3] for r in crowd.ROSTER]
        self.assertIn("Pony 1-1", canon)
        self.assertIn("Pony 1-2", canon)          # one syllable apart
        self.assertIn("Hoover 1-1", canon)        # same digits, different name

    def test_every_ship_gets_its_own_radio_and_voice(self):
        """Two aeroplanes sharing an SRS client would pass a test a real pair
        fails: the radio GUID is the guard being measured."""
        self.assertEqual(len({r[0] for r in crowd.ROSTER}), len(crowd.ROSTER))
        self.assertEqual(len({r[1] for r in crowd.ROSTER}), len(crowd.ROSTER))

    def test_ships_say_different_things(self):
        """If two aeroplanes say identical words, a mis-attribution and a
        correct attribution produce identical transcripts and the run cannot be
        scored at all."""
        a, b = crowd.script_for("Pony one one", 0), crowd.script_for("Pony one two", 1)
        self.assertNotEqual(a[1], b[1])


class TestTheBoardSnapshot(unittest.TestCase):
    def test_the_engine_can_say_what_it_believes_exists(self):
        from marshall.atc.controller import Controller
        from marshall.core import route as R

        ctl = Controller(R.BATUMI_ASR)
        ctl.get("Pony 1-1")
        ctl.note_radar_contact("Pony 1-1")
        ctl.get("Maintained 2")
        rows = {r["callsign"]: r for r in ctl.board()}
        self.assertTrue(rows["Pony 1-1"]["identified"])
        self.assertFalse(rows["Maintained 2"]["identified"])

    def test_the_snapshot_survives_json(self):
        """It goes straight into the flight recorder, which is JSON lines -- a
        frozenset or an Enum in there costs a transmission."""
        import json

        from marshall.atc.controller import Controller
        from marshall.core import route as R

        ctl = Controller(R.BATUMI_ASR)
        ctl.get("Pony 1-1")
        json.dumps(ctl.board())



class TestTheHarnessDoesNotCryWolf(unittest.TestCase):
    """Both scorers called correct behaviour a failure on the first real run.

    Whisper turned "Pony one two" into "Pony wants you"; the controller replied
    "station calling, say your callsign again" -- exactly right, no aeroplane
    was invented -- and this scored it a GHOST, because the recorder had logged
    the radio as a six-character GUID stub rather than a name.

    The census made the mirror-image mistake, calling two correctly identified
    aeroplanes ghosts because radar had not painted them. Radar is the
    strongest authority, not the only one: a procedural controller has none at
    all and works filed strips.

    A harness that cries wolf gets switched off, and then it measures nothing.
    """

    def test_a_refusal_is_read_off_the_recorded_authority(self):
        self.assertEqual(
            crowd.classify("Pony 1-2", "MrfGeW", ROSTER, RADIOS, authority=""),
            crowd.DROPPED)

    def test_an_unnamed_radio_is_recognised_even_without_the_authority(self):
        """Recordings made before the field existed still have to score."""
        self.assertEqual(crowd.classify("Pony 1-2", "MrfGeW", ROSTER, RADIOS),
                         crowd.DROPPED)

    def test_a_real_callsign_is_not_mistaken_for_a_guid(self):
        for name in ("Pony 1-1", "Colt 2-1", "Hoover 1-1"):
            with self.subTest(name):
                self.assertFalse(crowd._looks_like_a_guid(name))

    def test_a_filed_strip_is_identification_too(self):
        c = crowd.ghost_census([
            {"t": 1.0, "kind": "pilot", "callsign": "Pony 1-1",
             "authority": "plan"},
            board(1.1, entity("Pony 1-1", identified=False)),
        ])
        self.assertFalse(c["Pony 1-1"]["ghost"])
        self.assertEqual(c["Pony 1-1"]["authority"], "plan")

    def test_a_name_nothing_ever_vouched_for_is_still_a_ghost(self):
        """The guard must not swallow the thing it was built to find."""
        c = crowd.ghost_census([
            {"t": 1.0, "kind": "pilot", "callsign": "Maintained 2",
             "authority": ""},
            board(1.1, entity("Maintained 2", identified=False)),
        ])
        self.assertTrue(c["Maintained 2"]["ghost"])

if __name__ == "__main__":
    unittest.main()
