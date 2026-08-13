"""A restart that changes the procedure is not a restart.

`tools/bridge.py` had no test at all, and this is what it cost. `DEFAULT_ARGS`
carried `--theatre` and never the approach, so `MARSHALL_APPROACH` survived a
restart only if the operator happened to have exported it in the shell he was
restarting from. From anywhere else it silently reverted to the map's default.

    started:   MARSHALL_APPROACH=batumi-ils  ->  ILS runway 13, intercept
    restarted: (nothing carried)             ->  batumi-asr, a TALKDOWN

It happened twice on 13 August. Once by accident, mid-rehearsal, which
invalidated the run and was noticed only because the agent flying it checked the
log line before judging anything; once deliberately, to reproduce it.

`theatre.py` already knows why this matters and says so about a different
mechanism: *"an unknown one is named rather than silently swapped for the
default, which is how a pilot came to fly a talkdown after asking for an ILS."*
The same sentence applies to a restart, which is the far more common way to get
there -- a live bridge is restarted several times in a sortie for a patch.

THE ANSWER IS TO ASK THE PROCESS. What is RUNNING is the only thing that knows
which procedure is loaded; a restart that consults a note instead is right until
somebody starts the bridge by hand. `/proc/<pid>/environ` is that question. [#158]
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import bridge


class TestTheApproachIsReadOffTheRunningProcess(unittest.TestCase):

    def test_it_finds_what_a_process_was_STARTED_with(self):
        """A REAL child, because `/proc/<pid>/environ` is the environment at
        EXEC time and does not follow `os.environ` afterwards.

        That is not an inconvenience, it is the property being relied on: a
        bridge started with `MARSHALL_APPROACH=batumi-ils` carries it there for
        as long as it lives, whatever any shell does later. Setting the
        variable in this interpreter and reading our own `environ` would have
        tested nothing and passed anyway.
        """
        import subprocess
        import time
        env = dict(os.environ, MARSHALL_APPROACH="kobuleti-ils-07")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 env=env)
        try:
            for _ in range(50):            # exec is not instant
                if bridge.approach_of([child.pid]):
                    break
                time.sleep(0.02)
            self.assertEqual(bridge.approach_of([child.pid]), "kobuleti-ils-07")
        finally:
            child.kill()
            child.wait(timeout=5)

    def test_a_process_that_was_not_told_answers_empty(self):
        """Empty is a real answer: he is on the map's default and carrying
        nothing forward is correct. It must not be confused with a failure to
        read, which is why the caller checks for a value rather than a flag."""
        os.environ.pop("MARSHALL_APPROACH", None)
        self.assertEqual(bridge.approach_of([os.getpid()]), "")

    def test_a_dead_pid_does_not_raise(self):
        """`running()` races a bridge that is exiting, and a restart that
        crashed on the way to stopping the old one would leave a pilot on a
        dead frequency -- which is the failure this whole file exists for."""
        self.assertEqual(bridge.approach_of([999_999_999]), "")

    def test_it_takes_the_first_that_answers(self):
        """Two bridges is already a refused state -- `start` says "another
        bridge holds the frequency" -- so this need only be defined, not
        clever."""
        got = bridge.approach_of([999_999_999, os.getpid()])
        self.assertEqual(got, "")   # this process has none set


class TestTheFlagAndTheInheritanceAgree(unittest.TestCase):
    """`--approach` beats what is running, and both beat the map's default.

    The same precedence `--theatre` has, which is the reason to spell it the
    same way: an operator who has learned one has learned the other.
    """

    def test_the_flag_is_parsed_like_theatre(self):
        src = Path(bridge.__file__).read_text()
        self.assertIn('if "--approach" in sys.argv:', src)
        self.assertIn('os.environ["MARSHALL_APPROACH"] = '
                      'sys.argv[sys.argv.index("--approach") + 1]', src)

    def test_restart_reads_before_it_stops(self):
        """Order matters and cannot be asserted by running it: after `stop()`
        there is no process left to ask. So this pins the ORDER in the source,
        which is the thing that would silently regress."""
        src = Path(bridge.__file__).read_text()
        block = src[src.index('if what == "restart":'):]
        block = block[:block.index("return start()")]
        self.assertLess(block.index("approach_of(running())"),
                        block.index("stop()"),
                        "the approach is read after the bridge is stopped, so "
                        "there is nothing left to read it from")

    def test_a_deliberate_change_is_announced(self):
        """An operator may ask for a different procedure -- that is allowed.
        Doing it in silence is not: #158's second criterion is a stop sign a
        human can read."""
        src = Path(bridge.__file__).read_text()
        self.assertIn("the running bridge is on", src)


if __name__ == "__main__":
    unittest.main()
