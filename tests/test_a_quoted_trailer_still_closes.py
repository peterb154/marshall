"""Quoting a closing trailer to explain it closes the issue anyway.

The commit that apologised for closing #172 with a trailer closed #172, because
its message quoted the trailer in backticks and GitHub's parser does not read
markdown. Thirty seconds of open, between two closures by the same person for
the same reason.

    552d4c7   `Closes #172` as a trailer  -- the plain fault
    1fb846a   "Then I wrote `Closes #172` on one." -- the apology

Both are refused now, and the second is the one this file is really about: it is
the failure that survives knowing the rule. See `tools/commit_msg_check.py`.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import commit_msg_check as C

ROOT = Path(__file__).resolve().parent.parent


class TestProseIsRefusedAndTrailersAreNot(unittest.TestCase):

    def test_the_message_that_actually_did_it(self):
        """Verbatim from `1fb846a`, which is in this repository's history and
        can be read back. A guard justified by an incident should be tested
        against the incident rather than against a paraphrase of it."""
        got = subprocess.run(["git", "log", "-1", "--format=%B", "1fb846a"],
                             cwd=ROOT, capture_output=True, text=True)
        if got.returncode:
            self.skipTest("shallow clone: that commit is not present")
        bad = C.offending(got.stdout)
        self.assertTrue(bad, "the message that closed #172 twice passes the "
                             "check that exists because it closed #172 twice")
        self.assertIn("Closes #172", bad[0][1])

    def test_a_trailer_on_its_own_line_is_allowed(self):
        """The convention is kept. This check is about WHERE, not whether."""
        self.assertEqual(C.offending("subject\n\nbody\n\nCloses #11\n"), [])

    def test_refs_is_never_touched(self):
        self.assertEqual(C.offending("subject\n\nRefs #11 and see #12\n\n"
                                     "Refs #11\n"), [])

    def test_backticks_do_not_help(self):
        """The whole point. A committer who quotes it is being careful."""
        self.assertTrue(C.offending("subject\n\nI wrote `Closes #1` on one.\n"))

    def test_every_keyword_and_tense(self):
        for kw in C.KEYWORDS:
            with self.subTest(kw):
                self.assertTrue(C.offending(f"subject\n\nsaying {kw} #9 here\n"))

    def test_the_gh_dash_form_counts(self):
        """`GH-12` links exactly as `#12` does and reads as prose, so it is the
        form most likely to slip through a check that only knew about `#`."""
        self.assertTrue(C.offending("subject\n\nthis fixes GH-12 apparently\n"))

    def test_a_keyword_with_no_number_is_ordinary_english(self):
        """"This closes the gap" must not be refused -- a check that fires on
        the word alone would refuse half the commit messages in this repo and
        be switched off within a day."""
        self.assertEqual(C.offending("subject\n\nthis closes the gap #\n"), [])
        self.assertEqual(C.offending("subject\n\nfixed the handoff at last\n"), [])

    def test_gits_own_commentary_is_not_the_message(self):
        """`git commit` appends the diff and the branch under `#`, and strips
        them. A `#172` in there is not a reference and refusing it would refuse
        every commit made through an editor."""
        msg = ("subject\n\nbody\n\nCloses #11\n"
               "# Please enter the commit message for your changes.\n"
               "# On branch main -- this closes #172 in the diff below\n")
        self.assertEqual(C.offending(msg), [])

    def test_the_line_number_points_at_it(self):
        """A refusal that does not say where is a refusal somebody works
        around by deleting the message and starting again."""
        n, line = C.offending("subject\n\nfirst\n\nfixes #3 in prose\n")[0]
        self.assertEqual(n, 5)
        self.assertIn("fixes #3", line)


class TestTheHookIsWiredAndWillRun(unittest.TestCase):
    """A check nobody runs is the thing this project keeps finding."""

    HOOK = ROOT / ".githooks" / "commit-msg"

    def test_it_exists_and_is_executable(self):
        import os
        self.assertTrue(self.HOOK.exists(), "no commit-msg hook")
        self.assertTrue(os.access(self.HOOK, os.X_OK),
                        "the hook is not executable, so git skips it in "
                        "silence -- which is indistinguishable from passing")

    def test_it_runs_the_checker(self):
        self.assertIn("commit_msg_check.py", self.HOOK.read_text())

    def test_it_says_how_to_enable_itself(self):
        """`core.hooksPath` is not set by cloning, so a hook in the tree does
        nothing at all until somebody points git at it. The instruction lives
        in the hook because that is the file a reader has open when they
        wonder why it never fired."""
        self.assertIn("core.hooksPath", self.HOOK.read_text())

    def test_it_refuses_a_real_message_end_to_end(self):
        """Through the shell, as git invokes it -- the python path inside the
        hook is a thing that can be wrong while the module imports fine."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False) as f:
            f.write("subject\n\nI wrote `Closes #172` on one.\n")
            path = f.name
        got = subprocess.run([str(self.HOOK), path], capture_output=True,
                             text=True)
        self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
        self.assertIn("STILL CLOSES THE ISSUE", got.stderr)


if __name__ == "__main__":
    unittest.main()
