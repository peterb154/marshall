"""What a controller is GIVEN, decided by the seat rather than by a paragraph.

    #81 [SEAM-3]

One agent was built with one tool list for every session, `spawn_ground`
included, and the Overlord brief was what told an approach controller not to put
armour in a valley. **Prose is not a permission system.** It costs tokens on
every transmission describing capabilities the seat may not use, and it relies on
the model obeying an instruction rather than on the capability being absent.

WHAT IS ABSENT CANNOT BE CALLED. That is the same argument as the one that keeps
an LLM out of separation: authority is structural, not advisory.

THE SEAT COMES FROM THE FREQUENCY, which is the one fact about a transmission no
pilot can influence -- the same reason `station_on` decides who is speaking
rather than anything in the transcript.
"""

import unittest
from pathlib import Path

from marshall.atc.agent.capability import capabilities

from marshall.core import route as R


class OnlyTheOverlordMayPutThingsInTheWorld(unittest.TestCase):
    """`spawn_ground` is the dangerous one and the reason this exists."""

    def test_no_aerodrome_controller_is_given_spawn(self):
        for s in R.STATIONS:
            if s.role == "overlord":
                continue
            self.assertNotIn("spawn", capabilities(s.role, s.also),
                             f"{s.name} was handed the ability to put armour "
                             f"in a valley")

    def test_sentry_keeps_it(self):
        sentry = next(s for s in R.STATIONS if s.role == "overlord")
        self.assertIn("spawn", capabilities(sentry.role, sentry.also),
                      "without it, asking for a target produces a confident "
                      "answer and nothing on the ground")


class ClearanceFollowsTheSeatIncludingWhatItALSOWorks(unittest.TestCase):
    """A role is not one string. A field this size folds seats together."""

    def test_a_delivery_position_may_clear(self):
        st = next(s for s in R.STATIONS if s.role == "clearance")
        self.assertIn("clearance", capabilities(st.role, st.also))

    def test_a_ground_that_also_works_clearance_may_clear(self):
        """Reading the primary role alone would disarm a controller who
        genuinely does the job -- the failure in the safe direction, but still
        a failure.

        THE EXAMPLE MOVED, THE RULE DID NOT. This used Batumi Ground, which
        carried `also = ("delivery", "clearance")` because Batumi had no
        Clearance seat for him to defer to. It has one now, so he stopped
        claiming the role -- two seats answering "clearance" at one field is
        the `station_for` first-match fault (#218).

        The seat is CONSTRUCTED here rather than found on a map, because the
        arrangement it models is not Batumi's: it is the 1944 one, where a
        single controller answers as tower, ground, approach and departure
        because the SCR-522 has four buttons and none to spend on splitting
        him. That folding is the thing under test and it must keep working
        whichever map is loaded."""
        one_man = R.Station("Anyfield Ground", 121.8, "ground",
                            also=("delivery", "clearance"))
        self.assertIn("clearance", capabilities(one_man.role, one_man.also))

    def test_and_the_period_arrangement_folds_every_role_into_one(self):
        """The warbird field: one man, every hat, one frequency."""
        alone = R.Station("Batumi", 132.0, "tower",
                          also=("ground", "clearance", "approach", "departure"))
        got = capabilities(alone.role, alone.also)
        # Capability names are what a seat may DO, not the roles it answers to
        # -- there is no "approach" capability, there is `vector`. One man on
        # one frequency must hold both ends of the sortie: the paperwork and
        # the talk-down.
        for job in ("clearance", "vector"):
            self.assertIn(job, got)

    def test_a_plain_ground_may_not(self):
        st = next(s for s in R.STATIONS if s.name == "Kobuleti Ground")
        self.assertEqual(st.also, ())
        self.assertNotIn("clearance", capabilities(st.role, st.also))

    def test_a_tower_may_not(self):
        for s in R.STATIONS:
            if s.role == "tower" and "clearance" not in s.also:
                self.assertNotIn("clearance", capabilities(s.role, s.also))


class EverySeatKeepsWhatEverySeatNeeds(unittest.TestCase):
    """Knowing who is calling, measuring a range, being woken, looking up a
    frequency, remembering the sortie. Disarming any of these breaks the job."""

    def test_the_universal_set(self):
        for s in R.STATIONS:
            got = capabilities(s.role, s.also)
            for want in ("identify", "vector", "hooks", "frequency", "memory"):
                self.assertIn(want, got, f"{s.name} lost {want}")


class AnUnknownSeatIsNotDisarmed(unittest.TestCase):
    """A capability system that silently disarmed a controller because a lookup
    missed would be worse than none at all."""

    def test_no_role_means_everything(self):
        got = capabilities("", ())
        self.assertIn("spawn", got)
        self.assertIn("clearance", got)

    def test_an_unrecognised_role_still_gets_the_universal_set(self):
        got = capabilities("harbourmaster", ())
        self.assertIn("identify", got)
        self.assertNotIn("spawn", got,
                         "an unknown seat must not inherit the dangerous one")


class TheDirectorActuallyHonoursIt(unittest.TestCase):
    """The map is only worth having if `build_agent` reads it.

    This is the check that would have caught the original bug: the capability
    table could be perfect and every controller still be handed everything.
    """

    def setUp(self):
        self.src = (Path(__file__).resolve().parent.parent
                    / "services" / "app.py").read_text()

    def test_spawn_is_conditional(self):
        self.assertIn('*([spawn_ground] if "spawn" in may else [])', self.src)

    def test_clearance_is_conditional(self):
        self.assertIn('if "clearance" in may else []', self.src)

    def test_the_agent_cache_is_keyed_on_the_seat(self):
        # ONE BRIDGE, ONE SESSION, THIRTEEN FREQUENCIES. The role varies within
        # a session, so caching on the session alone would hand Batumi Approach
        # whatever tool set Sentry was built with -- reopening the leak through
        # the cache.
        # THE STATION, not just the role: two aerodromes have a Ground and a
        # Tower each, and a role is only unique WITHIN an aerodrome.
        #
        # AND THE MISSION since 11 August. It decides which board the clearance
        # tools read, so a cached agent built under the previous sortie would go
        # on reading the previous sortie's flights -- the same leak the station
        # and the role were added here to close, one key along.
        self.assertRegex(self.src, r"_key = \(session_id, station, role, also,"
                                   r"\s*mission\)")
        self.assertIn("_atc_agents[_key] = agent", self.src)

    def test_the_role_comes_from_the_request_not_the_transcript(self):
        self.assertIn('body.get("role")', self.src)
        self.assertIn('body.get("station")', self.src)

    def test_two_grounds_do_not_share_a_conversation(self):
        """Keyed on the role, Kobuleti Ground and Batumi Ground were one store.

        Two controllers writing one conversation compute the same next
        message_id, and one loses:

            UniqueViolation: Key (session_id, agent_id, message_id)
                             =(hooks:ground, default, 28) already exists
        """
        # Read the behaviour off the source: importing app.py would need the
        # whole director stack stood up for one string comparison.
        src = self.src
        self.assertIn("key = (station or role or \"\")", src)
        self.assertNotIn('return f"{session_id}:{role}" if role else session_id', src)


class TheBridgeSendsTheSeat(unittest.TestCase):

    def setUp(self):
        from marshall.atc import agent_atc
        import inspect
        self.src = inspect.getsource(agent_atc)

    def test_ask_agent_carries_role_and_also(self):
        self.assertIn('"role": role', self.src)
        self.assertIn('"also": list(also or ())', self.src)

    def test_the_seat_is_resolved_from_the_frequency(self):
        self.assertIn("def seat_on(", self.src)
        self.assertIn("_stations.on_frequency(_seats, ", self.src)

    def test_an_unclaimed_channel_reports_no_seat(self):
        # Which the director reads as "the bridge did not say".
        self.assertIn('return "", ()', self.src)


if __name__ == "__main__":
    unittest.main()
