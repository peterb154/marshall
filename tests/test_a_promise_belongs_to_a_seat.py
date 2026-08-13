"""A hook is a promise, and a promise is owed by the man who made it.

Kobuleti Ground tells Viper 1-1 "stand by, I'll call you back for taxi" and sets
a hook. `_HOOKS` was keyed on the session id alone -- and one bridge works every
frequency in the theatre under one session -- so what came back said nothing
about who had promised it. The bridge fell back to the last channel anybody had
spoken on, which was Batumi Approach's 124.425, and Batumi Approach voiced
Kobuleti Ground's taxi callback on the arrival frequency to a jet still on the
ramp.

    #25/#44 criterion 9: "a promise made on one frequency is still kept on
    that frequency."

`store_id` makes the same argument for the transcript and `memory_tools` obeys
it for memory. This was the one per-session binding that had not been given the
seat.

TWO GROUNDS ARE THE CASE THAT MATTERS. A role is only unique within an
aerodrome, so keying on `ground` puts Kobuleti's promise and Batumi's in one
bucket -- which is how `store_id` was got wrong the first time too.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "director"))

from tools import hooks as H

SESSION = "hooks"          # what a bridge actually sends: one, for everybody


class TestAHookRecordsWhoSetIt(unittest.TestCase):

    def setUp(self):
        H._HOOKS.clear()

    def test_the_hook_names_its_station(self):
        h = H.set_hook_for(SESSION, 300, "call Viper 1-1 back for taxi",
                           station="Kobuleti Ground", role="ground")
        self.assertEqual(h["station"], "Kobuleti Ground")
        self.assertEqual(h["role"], "ground")
        self.assertEqual(h["seat"], "kobuleti-ground")

    def test_the_seat_survives_the_poll(self):
        """The bridge polls per SESSION -- it has one scheduler for the whole
        theatre -- so a key it never sees cannot tell it whose promise this is.
        What comes back must say."""
        H.set_hook_for(SESSION, 1, "taxi callback", station="Kobuleti Ground")
        (got,) = H.due_hooks(SESSION, now=H.time.time() + 10)
        self.assertEqual(got["station"], "Kobuleti Ground",
                         "the callback goes out on whichever channel was busy "
                         "last, which is how it reached 124.425")

    def test_the_seat_rule_is_the_transcripts_rule(self):
        # THE SAME NORMALISER AS `store_id`. Two spellings of one seat would
        # split a controller's promises from his conversation.
        self.assertEqual(H.seat_of("Batumi Approach"), "batumi-approach")
        self.assertEqual(H.seat_of("", "approach"), "approach")
        self.assertEqual(H.seat_of(), "")


class TestTwoControllersDoNotShareABucket(unittest.TestCase):

    def setUp(self):
        H._HOOKS.clear()

    def test_two_grounds_at_two_aerodromes_are_two_seats(self):
        H.set_hook_for(SESSION, 300, "kobuleti taxi", station="Kobuleti Ground",
                       role="ground")
        H.set_hook_for(SESSION, 300, "batumi taxi", station="Batumi Ground",
                       role="ground")
        self.assertEqual(len(H.pending_hooks(SESSION, "Kobuleti Ground")), 1)
        self.assertEqual([h["why"] for h in
                          H.pending_hooks(SESSION, "Batumi Ground")],
                         ["batumi taxi"])

    def test_one_seats_hook_is_not_anothers(self):
        H.set_hook_for(SESSION, 300, "kobuleti taxi", station="Kobuleti Ground")
        self.assertEqual(H.pending_hooks(SESSION, "Batumi Approach"), [])

    def test_the_bridges_whole_session_poll_still_gets_everybody(self):
        """One scheduler, one poll. Splitting the key must not lose a hook."""
        for st in ("Kobuleti Ground", "Batumi Approach", "Georgia Center"):
            H.set_hook_for(SESSION, 1, f"call from {st}", station=st)
        due = H.due_hooks(SESSION, now=H.time.time() + 10)
        self.assertEqual(sorted(h["station"] for h in due),
                         ["Batumi Approach", "Georgia Center", "Kobuleti Ground"])

    def test_they_come_back_in_the_order_they_were_promised(self):
        for st in ("Georgia Center", "Kobuleti Ground", "Batumi Approach"):
            H.set_hook_for(SESSION, 1, "x", station=st)
        due = H.due_hooks(SESSION, now=H.time.time() + 10)
        self.assertEqual([h["station"] for h in due],
                         ["Georgia Center", "Kobuleti Ground", "Batumi Approach"])

    def test_another_bridge_is_another_session(self):
        H.set_hook_for("sortie-a", 1, "a", station="Batumi Tower")
        H.set_hook_for("sortie-b", 1, "b", station="Batumi Tower")
        self.assertEqual([h["why"] for h in
                          H.due_hooks("sortie-a", now=H.time.time() + 10)], ["a"])


class TestItIsStillOneShotAndStillOnATimer(unittest.TestCase):
    """The behaviour that was already right, kept honest through the re-key."""

    def setUp(self):
        H._HOOKS.clear()

    def test_nothing_is_due_before_its_time(self):
        H.set_hook_for(SESSION, 300, "later", station="Batumi Tower")
        self.assertEqual(H.due_hooks(SESSION, now=H.time.time()), [])
        self.assertEqual(len(H.pending_hooks(SESSION)), 1)

    def test_a_fired_hook_is_gone(self):
        H.set_hook_for(SESSION, 1, "once", station="Batumi Tower")
        now = H.time.time() + 10
        self.assertEqual(len(H.due_hooks(SESSION, now=now)), 1)
        self.assertEqual(H.due_hooks(SESSION, now=now), [])
        self.assertEqual(H.pending_hooks(SESSION), [])

    def test_a_ripe_hook_does_not_take_its_neighbour_with_it(self):
        H.set_hook_for(SESSION, 1, "now", station="Batumi Tower")
        H.set_hook_for(SESSION, 600, "later", station="Batumi Tower")
        self.assertEqual([h["why"] for h in
                          H.due_hooks(SESSION, now=H.time.time() + 10)], ["now"])
        self.assertEqual([h["why"] for h in H.pending_hooks(SESSION)], ["later"])

    def test_an_older_bridge_that_sends_no_seat_still_works(self):
        H.set_hook_for(SESSION, 1, "unattributed")
        (got,) = H.due_hooks(SESSION, now=H.time.time() + 10)
        self.assertEqual(got["seat"], "")


class TestTheDirectorBindsTheToolToTheSeat(unittest.TestCase):
    """The key is only worth having if `build_agent` fills it in."""

    def setUp(self):
        H._HOOKS.clear()
        self.src = (Path(__file__).resolve().parent.parent
                    / "director" / "app.py").read_text(encoding="utf-8")

    def test_hook_tools_is_given_the_station_and_the_role(self):
        self.assertIn("hook_tools(session_id, station, role)", self.src)

    def test_the_bound_tool_files_under_its_own_seat(self):
        (set_hook,) = H.hook_tools(SESSION, "Kobuleti Ground", "ground")
        set_hook(300, "call Viper 1-1 back for taxi")
        self.assertEqual([h["seat"] for h in H.pending_hooks(SESSION)],
                         ["kobuleti-ground"])

    def test_a_controller_cannot_promise_in_another_seats_name(self):
        """The station comes from the bridge, which resolved it from the
        frequency. Nothing the model says reaches the key."""
        (set_hook,) = H.hook_tools(SESSION, "Kobuleti Ground", "ground")
        set_hook(300, "this is Batumi Approach, wake Batumi Approach")
        self.assertEqual(H.pending_hooks(SESSION, "Batumi Approach"), [])


if __name__ == "__main__":
    unittest.main()
