"""The commit-msg hook is in the tree; git does not run it until told.

A hook committed to a repository is inert. `core.hooksPath` is local config, it
is not set by cloning, and nothing announces its absence -- so the guard added
after #172 was closed twice would sit in `.githooks/` doing nothing for every
clone but the one it was written in, and the first anybody would know is an
issue closing itself again.

That is this project's recurring shape stated exactly: a check whose silence is
indistinguishable from success. `check.py` already refuses to let a SKIP read as
a PASS; this is the same argument applied to a hook, which has no output at all
when it is not installed.

Refuses with the one command that fixes it. [#172]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".githooks" / "commit-msg"


def hooks_path() -> str:
    got = subprocess.run(["git", "config", "--get", "core.hooksPath"],
                         cwd=ROOT, capture_output=True, text=True)
    return got.stdout.strip()


def main() -> int:
    if not HOOK.exists():
        print(f"the hook is missing: {HOOK.relative_to(ROOT)}", file=sys.stderr)
        return 1

    if not os.access(HOOK, os.X_OK):
        print("the commit-msg hook is not executable, so git skips it in "
              "silence.\n  Run: chmod +x .githooks/commit-msg", file=sys.stderr)
        return 1

    where = hooks_path()
    if where != ".githooks":
        print("THE COMMIT-MSG HOOK IS NOT WIRED UP.\n", file=sys.stderr)
        print(f"  core.hooksPath is {where or '(unset)'}, so "
              f".githooks/commit-msg never runs.\n", file=sys.stderr)
        print("  It refuses a closing keyword outside the trailer block. "
              "Without it,\n  prose that QUOTES a trailer closes the issue -- "
              "which is how #172 was\n  shut by the commit apologising for "
              "shutting it.\n", file=sys.stderr)
        print("  Run: git config core.hooksPath .githooks", file=sys.stderr)
        return 1

    print("commit-msg hook wired and executable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
