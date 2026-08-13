"""A closing keyword in a commit message closes an issue, wherever it sits.

GitHub scans the WHOLE commit message for `closes #12` and friends. It does not
parse markdown, so backticks around one are decoration and nothing else. This
project writes commit messages ABOUT its own trailers -- "every commit names an
issue" is the first rule in CLAUDE.md -- which makes quoting one the natural way
to explain a mistake, and quoting one is indistinguishable from making it.

That is not hypothetical. On 13 August #172 was closed three times in five
minutes:

    552d4c7   a `Closes` trailer on a needs-flight-test issue -- the plain fault
    (reopened)
    1fb846a   the commit APOLOGISING for it, which quoted the trailer in prose
              inside backticks to say what not to do
    (reopened)

The second is the one worth a guard. The first breaks a rule a human can hold in
their head; the second happens to somebody who knows the rule, is trying to
follow it, and is defeated by the message being read by a parser rather than a
reader. The failure is silent from the committer's side -- git says nothing, the
push succeeds, and the issue is shut.

SO THE TRAILER BLOCK IS THE ONLY PLACE A KEYWORD MAY APPEAR. A trailer is a line
that is nothing but `Closes #12`; prose that happens to contain the words is
refused, and the refusal says how to write it instead. `Refs #12` is untouched
and is what the prose should use, because it is what this project means nine
times in ten anyway.

WHY NOT JUST BAN IT EVERYWHERE. Because closing an issue from a commit is a
convention worth keeping -- it is what threads the change onto the issue. The
rule is about WHERE, not whether.
"""

from __future__ import annotations

import re
import sys

# GitHub's own list, all three tenses of each. Case-insensitive there, so here
# too.
KEYWORDS = ("close", "closes", "closed",
            "fix", "fixes", "fixed",
            "resolve", "resolves", "resolved")

# `#12` and `GH-12` are both linkers. A full issue URL is as well, and is caught
# by the same pattern because it ends in the number -- but only the two short
# forms are worth naming in a refusal a human reads.
REF = r"(?:#|GH-)\d+"
ANYWHERE = re.compile(rf"\b({'|'.join(KEYWORDS)})\s+({REF})", re.I)

# A trailer is the whole line. Leading spaces are allowed because git's own
# `--trailer` writes none but editors add them; anything else on the line means
# it is prose.
TRAILER = re.compile(rf"^\s*({'|'.join(KEYWORDS)})\s+({REF})\s*$", re.I)


def strip_comments(text: str) -> str:
    """git's own commented lines are not part of the message.

    `git commit` shows the diff and the branch under `#` and strips them before
    the message is stored -- so a `#123` in that noise is not a reference and
    must not be read as one.
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))


def offending(text: str) -> list[tuple[int, str]]:
    """Every line carrying a closing keyword that is not a trailer.

    Returns (line number, the line) so a refusal can point at it. One-indexed,
    counting the subject as line 1, which is what an editor shows.
    """
    out = []
    for i, line in enumerate(strip_comments(text).splitlines(), 1):
        if TRAILER.match(line):
            continue
        if ANYWHERE.search(line):
            out.append((i, line.strip()))
    return out


def report(bad: list[tuple[int, str]]) -> str:
    lines = ["", "A CLOSING KEYWORD IN PROSE STILL CLOSES THE ISSUE.", ""]
    for n, line in bad:
        lines.append(f"  line {n}:  {line[:72]}")
    lines += [
        "",
        "GitHub scans the whole message and does not read markdown, so",
        "backticks around one change nothing -- this is how #172 was closed",
        "by the commit apologising for closing it.",
        "",
        "Write `Refs #12` in prose, and keep the closing keyword for a trailer",
        "on a line of its own. If you are quoting one to explain it, name it",
        "without the number: \"a closing trailer\", \"the Closes keyword\".",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: commit_msg_check.py <path to message>", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        # A hook that cannot read the message must not block the commit -- the
        # cost of a false refusal here is somebody disabling hooks entirely.
        print(f"commit-msg: could not read the message ({exc}); allowing",
              file=sys.stderr)
        return 0
    bad = offending(text)
    if not bad:
        return 0
    print(report(bad), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
