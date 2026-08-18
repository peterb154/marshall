"""Filtering a model's words is a patch for a prompt that says the wrong thing.

    "regex guards like that are a smell we should look for, and actively try to
     reduce, finding the root cause of hallucinations (usually our prompts
     fault) rather than patching output"

WHY THIS FILE EXISTS. On 18 August a pilot read back a take-off clearance and
heard "Sockeye, Kobuleti Tower, go ahead" -- an invitation to speak, answering a
read-back. Following it back:

    the model said     "Sockeye, that's correct, contact Kobuleti Departure one
                       two three decimal three airborne, good day."
    the engine had     authorised no handoff. He was stationary on the runway
    the filter         deleted the clause containing "contact ... Departure",
                       which -- because controllers speak in commas rather than
                       full stops -- took "that's correct" with it
    the fallback       spoke, because a rule says never transmit silence

Every layer was defensible and the pilot got nonsense. But the root was none of
them:

    THE MODEL DID NOT INVENT IT. WE TOLD IT, FOUR TIMES.

    the plate, every turn   "A departure leaves the aerodrome's controllers for
                             Departure at about 5 miles"
    the per-turn message    "DEPARTURE FREQUENCY: ... it is the ONLY one to send
                             him to after takeoff"
    its own history         the IFR clearance it had issued, naming 123.3
    the transcript          a take-off clearance being read back

So the rules said "never send a pilot to another frequency off your own bat --
no line, no handoff", the plate said "a departure goes to Departure at 5 miles",
and a regex adjudicated between them AFTER the model had spoken. Two authorities
on one question, resolved by string surgery.

AND THE HISTORY KEPT THE UNCENSORED VERSION. `session_messages` holds what the
model wrote; the pilot heard what survived. The controller believes it handed
him over. Nobody can be trusted about what was said. That is worse than no
filter, because a filter that silently diverges the record from reality poisons
every turn after it.

WHAT THIS TEST DOES. It does not ban filtering -- two exist and both patched a
real incident. It makes taking on a new one deliberate: every filter is declared
here with the PROMPT FAULT it compensates for, and an unregistered one fails. A
filter with no named prompt fault is an admission that nobody looked.

The count is a baseline in `asr_sweep`'s sense: today's truth written down so a
regression is visible. It should go DOWN. [#179]
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# THE FILTERS THAT EXIST, and the prompt fault each one is standing in for.
#
# A registry rather than a ban. Both of these were added after something a
# pilot heard, and deleting them without fixing the cause would put the
# incident back. What the registry forces is the question nobody asked at the
# time: WHY did the model say that, and what did we tell it?
FILTERS = {
    "strip_unauthorised_handoff": (
        "The plate said 'a departure leaves for Departure at about 5 miles' "
        "and the per-turn message said the departure frequency was 'the ONLY "
        "one to send him to after takeoff' -- both rules about WHEN, to a "
        "voice the rules file forbids from deciding it. Fixed 18 August: both "
        "now name WHO and say the timing arrives as a HANDOFF line. The filter "
        "stays until a sortie shows the model has stopped volunteering them."),
    "hush_a_second_talkdown": (
        "The engine flies the talkdown and the agent transmitted its own mile "
        "calls beside it, holding the metronome off the air. The brief tells "
        "it not to and it does it anyway -- which is the same shape and has "
        "NOT been root-caused. Nobody has yet asked what in the prompt makes a "
        "controller on final think range calls are his."),
}

# ...AND THE ONE THAT IS NOT A FILTER. `for_voice` cuts at a `RADIO:` marker
# the model is instructed to emit, which is structured output with a plain-text
# encoding -- the reply declares which part is speech. That is the OPPOSITE of
# guessing from the words, and is the shape the two above should move towards.
NOT_A_FILTER = {"for_voice"}


def _reply_pipeline() -> list[str]:
    """Every function the model's reply is passed through, in `hear`'s caller.

    Found by following the variable rather than by reading, because the point
    is to catch a filter somebody adds later without telling anybody.
    """
    src = (ROOT / "src" / "marshall" / "atc" / "agent_atc.py").read_text()
    tree = ast.parse(src)
    seen: list[str] = []
    for node in ast.walk(tree):
        # `reply = f(reply, ...)` or `reply, x = f(reply, ...)`
        if not isinstance(node, ast.Assign):
            continue
        targets = []
        for t in node.targets:
            if isinstance(t, ast.Name):
                targets.append(t.id)
            elif isinstance(t, ast.Tuple):
                targets += [e.id for e in t.elts if isinstance(e, ast.Name)]
        if "reply" not in targets:
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        name = (call.func.id if isinstance(call.func, ast.Name)
                else getattr(call.func, "attr", ""))
        takes_reply = any(isinstance(a, ast.Name) and a.id == "reply"
                          for a in call.args)
        if name and takes_reply:
            seen.append(name)
    return seen


class EveryFilterOnTheModelsWordsIsDeclared(unittest.TestCase):

    def test_no_undeclared_filter_touches_the_reply(self):
        """The guard on the guards.

        A new one is easy to add and reads as prudence -- the model said
        something wrong, so remove it. It is nearly always cheaper and more
        honest to find what we told it.
        """
        got = set(_reply_pipeline()) - NOT_A_FILTER
        new = sorted(got - set(FILTERS))
        self.assertEqual(
            new, [],
            f"{new} edits what the model said and is not declared in FILTERS. "
            f"Before adding one: read the prompt back and find the sentence "
            f"that made the model say it. On 18 August that sentence existed, "
            f"in two places, and a regex was deleting its consequences.")

    def test_the_registry_is_not_stale(self):
        """A declared filter that no longer runs is a licence nobody revoked."""
        got = set(_reply_pipeline()) - NOT_A_FILTER
        gone = sorted(set(FILTERS) - got)
        self.assertEqual(
            gone, [],
            f"FILTERS declares {gone}, which no longer edits the reply — "
            f"delete the entry in the same commit that removed the filter")

    def test_every_filter_names_the_prompt_fault_it_patches(self):
        """Not decoration. "The model said something wrong" is not a cause; the
        cause is a sentence we wrote. An entry that cannot name one is an
        entry nobody has investigated."""
        for name, why in FILTERS.items():
            with self.subTest(name):
                self.assertGreater(
                    len(why), 120,
                    f"{name} has no real account of WHY the model says it")

    def test_the_count_has_not_grown(self):
        got = set(_reply_pipeline()) - NOT_A_FILTER
        self.assertLessEqual(
            len(got), len(FILTERS),
            f"filters went from {len(FILTERS)} to {len(got)}: {sorted(got)}")


class TheHandoffRuleIsTaughtInOnePlace(unittest.TestCase):
    """The specific root cause, kept so it cannot come back quietly.

    WHEN an aeroplane is handed on is the engine's. The voice may be told WHO
    exists and on what frequency -- it needs that to correct a pilot holding
    the wrong button -- and must not be told the timing, because it will act
    on it and then be censored for doing so.
    """

    def _prompt_text(self) -> str:
        from marshall.atc import assembly, briefing
        from marshall.core import route as R, theatre as T
        from marshall.atc import agent_atc as A
        me = R.station_for("tower", field=T.current().departure)
        msg, _ = assembly.compose_message(
            A.Bridge(), "", "Sockeye", "Clear for takeoff, runway seven.",
            None, me, None, None, "", "", "", {}, "", "", "")
        return msg + "\n" + briefing.plates(T.approaches_now())

    def test_the_voice_is_not_told_when_a_departure_is_handed_on(self):
        """`5 miles` and `after takeoff` were the two that fired. Asserted on
        the RENDERED prompt rather than the source, because that is what the
        model actually reads."""
        said = self._prompt_text().lower()
        for taught in ("at about **5 miles**", "only one to send him to after",
                       "leaves the aerodrome's controllers for departure at"):
            with self.subTest(taught):
                self.assertNotIn(taught, said)

    def test_but_it_is_still_told_who_they_are(self):
        """The correction must not go so far that a controller cannot answer
        "what's the departure frequency?" -- which is his to answer."""
        said = self._prompt_text()
        self.assertIn("Departure", said)
        self.assertIn("HANDOFF", said.upper())


if __name__ == "__main__":
    unittest.main()
