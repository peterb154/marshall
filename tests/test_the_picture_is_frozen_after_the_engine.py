"""A turn DECIDES and then DESCRIBES, and the model is briefed on the end of it.

    21:36:11  PILOT   Kobuleti Departure, sockeye with you        (on 123.3)
    21:36:13  ENGINE  Sockeye, Kobuleti Departure, radar contact
    21:36:14  handoff Kobuleti Departure keeps him -- departure, 3 nm, outbound
    21:36:18  ATC     you should be with Tower, one three three decimal zero --
                      you're still with me

He was on the right frequency, sent there four seconds earlier. The seat
answering was Departure. The engine agreed, in the same turn. What disagreed
was the FLIGHT STRIP in the message, which still said Tower owned him -- so
the controller reconciled a contradiction it had been handed and sent him back.

THE ROW WAS READ AT THE TOP OF THE TURN and carried three hundred lines down
into `compose_message`, across `next_controller` (which settles the handoff and
records it) and `settle` (which advances the engine). The model was briefed on
the aeroplane as it stood BEFORE this turn's decisions.

    _bound = flight_bind(...)          <- picture taken
    nxt    = next_controller(...)      <- handoff decided and written
    settle(...)                        <- engine advanced
    compose_message(..., _flight, ...) <- briefed from the OLD picture

IT HAD BITTEN BEFORE, ON A DIFFERENT FIELD. `phase_now`'s docstring records it:
"This lived inside `settle`, which runs AFTER `separation_context`, so the half
of the turn that MUTATES the engine ran before anything had worked out what the
aeroplane was doing." That fix hoisted ONE field to the top of the turn. The
shape was never addressed, so it came back on `owner`.

SO THE TURN HAS A BOUNDARY NOW, and this file guards it rather than the symptom:
everything before the freeze decides, everything after describes. A future
field that goes stale the same way is a line on the wrong side of it. [#190]
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "marshall" / "atc" / "agent_atc.py"


def _receive_turn() -> ast.FunctionDef:
    """The function that runs one transmission, found by what it contains."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        body = ast.dump(node)
        if "compose_message" in body and "flight_bind" in body:
            best = node
    if best is None:                                      # pragma: no cover
        raise AssertionError("no function both binds a flight and composes a "
                             "message; the turn has been restructured")
    return best


def _line_of(fn: ast.FunctionDef, name: str) -> int:
    """Where `name(` is called inside this function."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            called = (node.func.id if isinstance(node.func, ast.Name)
                      else getattr(node.func, "attr", ""))
            if called == name:
                return node.lineno
    raise AssertionError(f"{name} is not called in the turn any more")


class TheModelIsBriefedOnStateTheEngineHasFinishedWith(unittest.TestCase):

    def setUp(self):
        self.fn = _receive_turn()

    def test_the_picture_is_re_read_after_the_engine_settles(self):
        """The fix, asserted as an ORDER rather than as a line of code.

        `flight_now` may move, be renamed or be inlined; what may not change
        is that the row the message is built from is obtained after the engine
        has stopped changing things.
        """
        settled = _line_of(self.fn, "settle")
        frozen = _line_of(self.fn, "flight_now")
        composed = _line_of(self.fn, "compose_message")
        self.assertGreater(
            frozen, settled,
            "the flight row is read before `settle` has advanced the engine, "
            "so the model is briefed on the aeroplane as it was BEFORE this "
            "turn decided anything — which is #190")
        self.assertGreater(
            composed, frozen,
            "the message is composed before the picture is frozen")

    def test_the_handoff_is_decided_before_the_picture_is_taken(self):
        """The specific contradiction: the strip must not predate the handoff
        that the same turn recorded."""
        decided = _line_of(self.fn, "next_controller")
        frozen = _line_of(self.fn, "flight_now")
        self.assertGreater(
            frozen, decided,
            "the strip is read before the handoff is settled, so it can name "
            "a controller the engine has already moved him off")

    def test_the_bind_result_is_not_what_the_model_sees(self):
        """`flight_bind` runs first and must stay a source of the ID only.

        Named apart on purpose. While both were `_flight` the staleness was
        invisible: the same identifier meant "the row when the turn started"
        at the top and "the row to describe him with" at the bottom.
        """
        src = ast.get_source_segment(SRC.read_text(encoding="utf-8"), self.fn)
        self.assertIn("_bound = flight_bind(", src or "")


class AndItIsAReadRatherThanAWrite(unittest.TestCase):
    """Taking a picture must not change what is being photographed.

    `flight_bind` returns the same row and also upserts, so using it to
    re-read would make the freeze itself a mutation — the boundary this file
    exists to draw would then be crossed by the line drawing it.
    """

    def test_flight_now_does_not_post(self):
        from marshall.atc import agent_atc as A
        import inspect
        src = inspect.getsource(A.flight_now)
        self.assertIn("_get_json", src)
        self.assertNotIn("_post_json", src)

    def test_and_it_survives_the_store_being_unreachable(self):
        """A picture that cannot be taken must not lose the turn. The stale
        row is worse than a fresh one and far better than an exception on the
        frequency."""
        from marshall.atc import agent_atc as A
        import inspect
        src = inspect.getsource(A.flight_now)
        self.assertIn("except Exception", src)
        self.assertIn("return {}", src)


if __name__ == "__main__":
    unittest.main()
