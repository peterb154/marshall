"""Whisper is told the names it will hear, from the table that knows them.

    "Sakai would request the ILS-13 approach."
    "Batumi Ground, Sakai, is clear of active runway 07"

All night, in every transcript. `Sockeye` is a word the recogniser has no
reason to expect and every reason to hear as a commoner name, and priming is
the lever -- `whisper_vocabulary` already carried squadron callsigns, stations,
fixes and plan labels.

IT SEEDED THE WRONG TABLE. `route.SQUADRON_CALLSIGNS` is `("Pony", "Hammer",
"Spit", "Whistler")` -- the flight names the mission builder gives AI aircraft.
The man flying was Sockeye, and `config/callsigns.toml` had held his respelling
all along because the TTS half needed it to SAY his name. The STT half needed
the same word to HEAR it and was reading a different table.

One fact, two tables, and the one that was wrong decides what the transcript
says -- which is what the callsign-correction guard then fires on, and what a
controller reads back at him.

MEASURED, by rendering the name in seven Polly voices and transcribing each
back through the real recogniser:

    unprimed          0/7 correct   ("Sakai" x6, "Suck I" x1)
    live vocabulary   6/7 correct   (the seventh, Joey, gives "Socke")

The test below is offline -- it asserts the CONFIGURED names reach the prompt,
which is the part that broke. Scoring the recogniser costs a model and eight
seconds of synthesis, and belongs in a bench rather than the suite. [#198]
"""

from __future__ import annotations

import unittest


class TheVocabularyCarriesTheConfiguredCallsigns(unittest.TestCase):

    def setUp(self):
        from marshall.atc import agent_atc as A
        self.vocab = A.whisper_vocabulary(A.Bridge())

    def test_every_name_the_config_can_say_is_a_name_it_can_hear(self):
        """The two halves read one table now. A name we know how to pronounce
        and cannot recognise is the exact shape of this bug."""
        from marshall.core import catalogue
        for name in catalogue.known_callsigns():
            with self.subTest(name):
                self.assertIn(name, self.vocab,
                              f"{name} has a respelling for Polly and is not "
                              f"primed for Whisper -- we can say it and not "
                              f"hear it")

    def test_the_squadron_flight_names_are_still_there(self):
        """`SQUADRON_CALLSIGNS` is not wrong, it was incomplete: those are the
        flight names the mission builder gives AI aircraft, and they really can
        be on the frequency."""
        from marshall.core import route as R
        for name in getattr(R, "SQUADRON_CALLSIGNS", ()):
            with self.subTest(name):
                self.assertIn(name, self.vocab)

    def test_a_broken_config_costs_a_prompt_and_not_a_transmission(self):
        """Priming is an optimisation. Losing it must never lose the call."""
        import inspect

        from marshall.atc import agent_atc as A
        src = inspect.getsource(A.whisper_vocabulary)
        at = src.index("known_callsigns")
        self.assertIn("except", src[at - 200:at + 200],
                      "reading the callsign table is unguarded, so a bad "
                      "config file silences the radio")


class AndTheDefaultPromptStillNamesNobody(unittest.TestCase):
    """The rule that made this subtle, and it is right.

    `default_prompt` deliberately carries phraseology and NO names: priming for
    another sortie's callsigns is worse than not priming, because it biases the
    transcript toward words that cannot occur. That is why the fix is to feed
    the LIVE vocabulary the configured names, and not to put them in the
    fallback.
    """

    def test_the_fallback_primes_no_callsign(self):
        from marshall.core import catalogue
        from marshall.radio import stt
        prompt = stt.default_prompt()
        for name in catalogue.known_callsigns():
            with self.subTest(name):
                self.assertNotIn(name, prompt)


if __name__ == "__main__":
    unittest.main()
