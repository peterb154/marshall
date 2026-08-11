"""What a controller says when the callsign he was given is nobody.

From the sortie of 28 July. The pilot called himself Falcon 1-1; nothing called
Falcon existed, because a callsign is a pilot's own name on the radio or a
flight somebody created and never a word chosen in the air. The identity ladder
refused it, which is the design working.

Then the controller explained it wrong:

    tool  "No flight on the board for Falcon 1-1. Get his callsign and check
           him in first, then ask again."         <- true, about HIM
    said  "no flight plan on file for that callsign"
                                                  <- false, about the FILE

He spent two minutes hunting a flight plan that was on file the whole time and
never got his clearance. The plan lookup was never involved: `Kettle` scores 100
on its label and would have been found on the first call.

So these tests are about a STRING, and that is not a category error -- the tool
return is the only instruction the controller gets, and one that can be
paraphrased into a falsehood will be.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "director"))

from tools.clearance import not_on_the_board


class TestTheMissIsAboutTheManNotThePlan(unittest.TestCase):
    def test_it_never_offers_the_flight_plan_as_the_excuse(self):
        said = not_on_the_board("Falcon 1-1", ["Pony 1-1", "Pony 1-2"]).lower()
        # The exact sentence the controller reached for last time, and the two
        # ways it phrases itself. Wanted ABSENT as a claim, so the negative
        # instruction may name it but nothing may assert it.
        self.assertNotIn("no flight plan on file", said)
        self.assertNotIn("nothing on file", said)

    def test_it_says_plainly_that_this_is_about_who_he_is(self):
        said = not_on_the_board("Falcon 1-1", ["Pony 1-1"])
        self.assertIn("WHO HE IS", said)
        self.assertIn("do NOT tell him a plan is missing", said)

    def test_it_names_the_closed_set(self):
        """The list is what turns a two-minute hunt into one transmission."""
        said = not_on_the_board("Falcon 1-1", ["Pony 1-1", "Pony 1-2"])
        self.assertIn("Pony 1-1", said)
        self.assertIn("Pony 1-2", said)

    def test_an_empty_board_says_so_rather_than_saying_nothing(self):
        said = not_on_the_board("Falcon 1-1", [])
        self.assertIn("board is empty", said)
        self.assertNotIn("On the board: .", said)

    def test_it_explains_why_a_name_from_the_air_is_nobody(self):
        """The pilot's own habit was the cause, so the answer has to teach it --
        otherwise he asks again with another invented name."""
        said = not_on_the_board("Falcon 1-1", ["Pony 1-1"])
        self.assertIn("never a name chosen in the air", said)

    def test_the_refused_callsign_is_quoted_back(self):
        said = not_on_the_board("Falcon 1-1", ["Pony 1-1"])
        self.assertGreaterEqual(said.count("Falcon 1-1"), 2)


class TheRecordedBoardIsTheOneTheTransmissionProduced(unittest.TestCase):
    """`board()` exists so a ghost is timestamped beside the words that minted
    it -- and the record was written BEFORE the engine heard the transmission,
    so a ghost minted by one call turned up attached to the next one.

    Measured on the ladder rehearsal: a pilot reported holding short, the engine
    moved him to `holding_short` correctly, and the recorded board said `taxi` --
    the rung he had been on when he keyed the microphone. The check written to
    catch that transition failing believed it.

    Source order, like `test_the_phase_is_derived_before_anything_acts`. There
    is no seam to inject here and the fault IS the order, so the order is what
    is asserted.
    """

    def _receive_source(self):
        import inspect
        from marshall.atc import agent_atc
        return inspect.getsource(agent_atc)

    def test_the_board_is_recorded_after_the_engine_has_acted(self):
        src = self._receive_source()
        i_decide = src.index("directive, stack, vectoring = decide(")
        i_board = src.index('record(session_id, kind="board"')
        self.assertLess(i_decide, i_board,
                        "the recorded board is a turn stale -- it is written "
                        "before decide() lets the engine hear him")

    def test_the_live_publish_still_runs_before_the_model_call(self):
        """The map must not wait on Bedrock. That snapshot is for a human
        watching, not the record anything is judged against, and moving it
        would put a several-second hole in the dashboard."""
        src = self._receive_source()
        i_publish = src.index("publish_state(bridge, ctl, scope, session_id")
        i_decide = src.index("directive, stack, vectoring = decide(")
        self.assertLess(i_publish, i_decide)
