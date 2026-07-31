"""Eight controllers who sound like eight people, and none of whom decide less.

    "See if you can add some soul to each of the controllers so there's a
     different texture in the way they talk to us. Some might be grouchy. Some
     might be super helpful."

WHAT THESE TESTS ARE ACTUALLY GUARDING. Personality is the one feature here that
can degrade the system while looking like it is working. Everything else fails
loudly -- a wrong frequency reaches nobody, a wrong heading shows up on the
scope. A controller who is *in character* while being unhelpful produces a
sortie where the pilot was refused something he was entitled to, and the
transcript reads like flavour rather than like a bug. It would be diagnosed by
somebody reading the separation engine, which would be innocent.

So the fence matters more than the flavour, and it is what most of this file
checks: manner owns the words AROUND the numbers and never the numbers.
"""

import unittest

from marshall.core import route as R


class TestEverybodyHasOne(unittest.TestCase):

    def test_every_station_has_a_manner(self):
        """A station with no manner falls back to the house voice, which is the
        thing this was added to stop -- eight controllers who are audibly one
        prompt."""
        for s in R.STATIONS:
            with self.subTest(station=s.name):
                self.assertTrue(getattr(s, "manner", ""),
                                f"{s.name} has no manner")

    def test_no_two_controllers_share_a_manner(self):
        """Copy-paste is the likely failure as controllers are added, and it is
        invisible in the air until you notice two fields sound identical."""
        seen = {}
        for s in R.STATIONS:
            with self.subTest(station=s.name):
                self.assertNotIn(s.manner, seen,
                                 f"{s.name} sounds exactly like {seen.get(s.manner)}")
                seen[s.manner] = s.name

    def test_no_two_controllers_share_a_voice(self):
        """A distinct manner in an identical timbre is still the same person to
        a pilot -- he is listening, not reading."""
        seen = {}
        for s in R.STATIONS:
            with self.subTest(station=s.name):
                self.assertNotIn(s.voice, seen,
                                 f"{s.name} shares a voice with {seen.get(s.voice)}")
                seen[s.voice] = s.name


class TestTheFence(unittest.TestCase):
    """The part that stops a mood becoming a fault."""

    def test_the_approach_controller_is_never_short_with_anybody(self):
        """He is the one talking a pilot down through cloud, which is the single
        moment where manner does real work. Everybody else can afford a temper;
        he cannot."""
        m = R.APPROACH.manner.lower()
        self.assertIn("never", m)
        self.assertTrue("calm" in m or "unflappable" in m)

    def test_the_grouchy_ones_are_still_correct_and_still_help(self):
        """Grouchy is a tone. It is not permission to withhold anything.

        Both of these are written as brusque, and both descriptions have to say
        out loud that the work still gets done -- because that sentence is what
        a model reads when it decides how far to take the character.
        """
        for s in (R.GROUND, R.KOB_CLEARANCE):
            with self.subTest(station=s.name):
                m = s.manner.lower()
                self.assertTrue(
                    "correctly" in m or "will explain" in m
                    or "not rude" in m or "never unsafe" in m
                    or "willing" in m,
                    f"{s.name} is brusque with nothing saying he still does "
                    f"the job")

    def test_no_manner_licenses_withholding(self):
        """A manner must never describe the controller as unhelpful in a way
        that touches the WORK. 'Curt' is fine; 'unhelpful' is not."""
        banned = ("refuse", "ignore", "unhelpful", "withhold", "won't help",
                  "will not help", "hang up", "unsafe")
        for s in R.STATIONS:
            for word in banned:
                with self.subTest(station=s.name, word=word):
                    # "never unsafe" and "not rude" are the allowed shapes --
                    # a negation, which is the opposite of a licence.
                    txt = s.manner.lower()
                    if word in txt:
                        idx = txt.index(word)
                        before = txt[max(0, idx - 12):idx]
                        self.assertTrue(
                            "never" in before or "not " in before,
                            f"{s.name} manner says {word!r} unqualified")


class TestTheBridgeActuallySendsIt(unittest.TestCase):
    """A field nothing reads is the `AtcCapability.era` mistake again."""

    def test_the_bridge_sends_this_fence(self):
        """The guardrail has to be in the code that talks to the model, not
        only in a docstring. Read as text so importing the voice stack is not
        required."""
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "src/marshall/atc/agent_atc.py"
        txt = src.read_text()
        self.assertIn("YOUR MANNER:", txt, "the manner is never sent")
        # The three things the fence must actually say.
        for phrase in ("never changes", "read-back", "trouble"):
            with self.subTest(phrase=phrase):
                after = txt.split("YOUR MANNER:", 1)[1][:1500]
                self.assertIn(phrase, after,
                              f"the fence does not mention {phrase!r}")

    def test_the_manner_is_read_from_the_station(self):
        """Not a table in the bridge. A controller carries his own voice and
        his own manner, so adding one is still a row."""
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "src/marshall/atc/agent_atc.py"
        self.assertIn('me, "manner"', src.read_text())


if __name__ == "__main__":
    unittest.main()
