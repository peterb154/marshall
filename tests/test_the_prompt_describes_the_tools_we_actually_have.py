"""A prompt naming a tool signature that does not exist is a broken controller.

    - **`request_clearance(callsign, said)` does the finding.** Pass his words
      through unedited

That line survived #183 by ninety minutes. The tool had become
`request_clearance(callsign, plan)` -- the controller names the plan, the engine
validates the label -- and the rules went on telling him to pass the pilot's
transcript through unedited. Flown, every clearance request in the sortie would
have been refused: `named("Roger Sock, I would like Batumi Test...")` matches no
label, so the answer to every request would have been "no plan called that is
filed".

NOTHING WOULD HAVE CAUGHT IT. The suite was green, ruff was clean, the tool's
own docstring was correct and tested, and the prompt is a markdown file nothing
parses. The seam between the two brains is a CONTRACT, and it was the only
contract in the system with no check on it -- which is exactly the shape this
codebase keeps re-learning: rules with mechanical checks hold, rules with only
prose drift.

WHAT THIS CHECKS, and deliberately not more. It reads every `tool_name(args)`
spelled in the prompts and compares it to the real tool. It does not try to
judge whether the PROSE is right -- that is a language question, and a test
that tried would be the same mistake as the plan resolver: a worse reader
standing in front of a better one. It catches the mechanical half, which is the
half that fails silently.

The prose half has an owner: a pilot flying the card. [#185]
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "src" / "marshall" / "atc" / "agent" / "prompts"

# `name(a, b)` inside backticks, which is how every prompt spells a call.
CALL = re.compile(r"`([a-z_][a-z0-9_]*)\(([^`)]*)\)`")


def _prompt_calls() -> dict[str, set[tuple[str, ...]]]:
    """Every tool call spelled in the prompts, as name -> {arg tuples}."""
    found: dict[str, set[tuple[str, ...]]] = {}
    for md in sorted(PROMPTS.glob("*.md")):
        for name, args in CALL.findall(md.read_text(encoding="utf-8")):
            got = tuple(a.strip() for a in args.split(",") if a.strip())
            found.setdefault(name, set()).add(got)
    return found


def _real_tools() -> dict[str, tuple[list[str], int]]:
    """Every `@tool` in the tree, as name -> (parameter names, how many are
    REQUIRED).

    Defaults are counted because a prompt may legitimately show a shorter
    call: `identify(callsign, guid)` against `identify(callsign, guid,
    spoken="")` is one example of a three-parameter tool, not a contradiction.

    Read off the AST rather than by importing and inspecting, because the
    tool factories want a live database to build their closures and this test
    must run with nothing up.
    """
    out: dict[str, list[str]] = {}
    for py in (ROOT / "src" / "marshall").rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:                      # not ours to police
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorated = any(
                (isinstance(d, ast.Name) and d.id == "tool")
                or (isinstance(d, ast.Attribute) and d.attr == "tool")
                for d in node.decorator_list)
            if decorated:
                args = [a.arg for a in node.args.args]
                out[node.name] = (args, len(args) - len(node.args.defaults))
    return out


class EveryToolTheProseNamesExists(unittest.TestCase):

    def setUp(self):
        self.said = _prompt_calls()
        self.real = _real_tools()

    def test_there_are_tools_to_check(self):
        """The check must not pass by finding nothing -- both halves of it
        parse source, and either could quietly come back empty."""
        self.assertTrue(self.real, "no @tool functions found at all")
        self.assertTrue(self.said, "no tool calls found in the prompts")

    def test_no_prompt_names_a_tool_that_does_not_exist(self):
        """Only for names we KNOW are tools. The prompts also spell helper
        functions and engine calls in backticks, and this test has no business
        ruling on those."""
        for name in sorted(self.said):
            if name not in self.real:
                continue                          # not a tool; not ours
            with self.subTest(name):
                self.assertIn(name, self.real)

    def test_the_arguments_match_the_tool(self):
        """The one that would have caught #183's ninety minutes.

        `request_clearance(callsign, said)` in the prose against
        `request_clearance(callsign, plan)` in the code -- same name, same
        arity, one word different, and that word is the whole contract.
        """
        for name, spellings in sorted(self.said.items()):
            got_real = self.real.get(name)
            if got_real is None:
                continue
            real, required = got_real
            for got in sorted(spellings):
                if not got:                       # `tool_name()` as a mention
                    continue
                # AN EXAMPLE IS NOT A SIGNATURE. The prompts also show a call
                # being made -- `set_hook(300, "clear him if the letdown is
                # free")` -- and those arguments are values, not parameter
                # names. ARITY still means something there and is checked;
                # the names are only compared when every argument is spelled
                # as an identifier, which is what a signature looks like.
                names = all(a.isidentifier() for a in got)
                with self.subTest(f"{name}{got}"):
                    self.assertTrue(
                        required <= len(got) <= len(real),
                        f"the prompts show {name} called with {len(got)} "
                        f"argument(s); it takes {required}-{len(real)}")
                    if names and len(got) == len(real):
                        self.assertEqual(
                            list(got), real,
                            f"the prompts tell the controller to call "
                            f"{name}({', '.join(got)}) and the tool is "
                            f"{name}({', '.join(real)}). He will call it the "
                            f"way he was told.")


class AndTheClearanceContractIsSpeltOut(unittest.TestCase):
    """The specific rules #183 and #185 depend on, kept so they cannot be
    quietly dropped by somebody tidying the prose.

    Asserted as PROHIBITIONS PRESENT rather than as words absent -- the file
    has to name the wrong behaviour in order to forbid it, so a substring sweep
    cannot tell the rule from the violation. That reading error has cost this
    project a test before.
    """

    def setUp(self):
        # WHITESPACE COLLAPSED, because the file is hard-wrapped at 79 columns
        # and a rule may be split across a newline anywhere. Asserting on the
        # raw text makes a test that passes or fails on where the paragraph
        # happened to wrap, which is not a fact about the rules.
        import re as _re
        raw = (PROMPTS / "rules.md").read_text(encoding="utf-8").lower()
        self.rules = _re.sub(r"\s+", " ", raw)

    def test_he_is_told_to_choose_the_plan(self):
        self.assertIn("you decide which plan", self.rules)
        self.assertIn("pass the label, not his words", self.rules)

    def test_he_is_told_to_ask_rather_than_guess(self):
        self.assertIn("do not call it with a guess", self.rules)

    def test_he_is_told_a_refusal_is_not_a_clearance(self):
        """The rule that was genuinely missing on 18 August. The prose covered
        what to do with what comes BACK and never said that nothing coming
        back is terminal."""
        self.assertIn("a refusal is not a clearance", self.rules)
        self.assertIn("if the tool did not hand you the words, you have none",
                      self.rules)


if __name__ == "__main__":
    unittest.main()
