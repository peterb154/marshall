"""Do the documents still describe the system that exists?

    "it is not yet safe as a new-agent onboarding system ... it will spend too
     long deciding which document describes today versus history."

The depth was never the problem. The README described the INVERSE of the
architecture for several weeks -- "the controller is blind", "the AI is ears and
mouth, never the brain" -- while `CLAUDE.md` opened with "real ATC by default, a
radar-equipped agent is the controller's brain". Both were the first thing
somebody read, and they disagreed on the single most important fact.

Nothing could have caught that but a person noticing. This catches the
mechanical half of the same disease:

  TYPED       every document under docs/ declares what it is -- current
              reference, work record, proposal, or historical debrief. An
              unmarked document is one a reader has to date by guessing.
  ENDPOINTS   an HTTP path named in prose exists in the code. `/chat` sat in
              DESIGN.md and in the bridge's own docstring for weeks after the
              bridge moved to `/atc`.
  COMMANDS    a `uv run python -m ...` or `tools/x.py` invocation names a
              module or file that is really there.
  LINKS       a relative markdown link resolves.

WHAT IT DELIBERATELY DOES NOT DO is judge prose for truth. "The controller is
blind" is four correct words about a system that changed underneath them, and no
checker was ever going to know. The typing rule is the answer to that one: a
document that says what it is and when it was validated can be wrong, but it
cannot be MISTAKEN FOR CURRENT.

    uv run python tools/docs_check.py

Exit 1 on a finding, 0 when clean. No network, so it runs in the gate.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

TYPES = ("CURRENT REFERENCE", "WORK RECORD", "PROPOSAL", "HISTORICAL DEBRIEF",
         "SUPERSEDED")

# Paths that are not ours to verify: other people's APIs, and the two the
# director's framework registers rather than us.
FOREIGN = ("/health", "/chat", "/sessions", "/messages")


def typed() -> list[str]:
    """Every doc says what it is, near the top where a reader starts."""
    bad = []
    for p in sorted(DOCS.glob("*.md")):
        head = "\n".join(p.read_text(encoding="utf-8").split("\n")[:14])
        if not any(f"Type: {t}" in head for t in TYPES):
            bad.append(f"{p.relative_to(ROOT)} declares no Type: header")
    return bad


def endpoints() -> list[str]:
    """An HTTP path in prose is a promise the code has to keep."""
    src = "\n".join(f.read_text(encoding="utf-8", errors="replace")
                    for f in list((ROOT / "src").rglob("*.py"))
                    + list((ROOT / "director").rglob("*.py")))
    bad = []
    pat = re.compile(r"`(/(?:atc|radar|hooks|prompts|flights|plans|events|diag)"
                     r"[a-z0-9/_{}-]*)`")
    for p in [*sorted(DOCS.glob("*.md")), ROOT / "README.md", ROOT / "CLAUDE.md"]:
        text = p.read_text(encoding="utf-8")
        # Historical documents are ALLOWED to name a dead endpoint -- that is
        # what makes them historical. Checking them would force us to falsify
        # the record to make a checker happy.
        if "Type: HISTORICAL DEBRIEF" in text[:600] or "Type: SUPERSEDED" in text[:600]:
            continue
        for m in set(pat.findall(text)):
            if m in FOREIGN:
                continue
            stem = m.split("{")[0].rstrip("/")
            if stem not in src:
                bad.append(f"{p.relative_to(ROOT)} names `{m}`, which is in no source file")
    return bad


def commands() -> list[str]:
    """A command in the docs should be runnable."""
    bad = []
    mod = re.compile(r"python -m (marshall[a-z_.]*)")
    tool = re.compile(r"(tools/[a-z_]+\.py)")
    for p in [*sorted(DOCS.glob("*.md")), ROOT / "README.md", ROOT / "CLAUDE.md"]:
        text = p.read_text(encoding="utf-8")
        if "Type: HISTORICAL DEBRIEF" in text[:600] or "Type: SUPERSEDED" in text[:600]:
            continue
        for m in set(mod.findall(text)):
            # A trailing dot is prose, not a module: "python -m marshall.<pkg>".
            if m.endswith("."):
                continue
            got = ROOT / "src" / Path(m.replace(".", "/") + ".py")
            pkg = ROOT / "src" / Path(m.replace(".", "/")) / "__init__.py"
            if not (got.exists() or pkg.exists()):
                bad.append(f"{p.relative_to(ROOT)} runs `-m {m}`, which does not exist")
        for m in set(tool.findall(text)):
            # TWO `tools/` DIRECTORIES, and the docs mean both. The repo has
            # `tools/` and the director has `director/tools/` -- its agent-side
            # tools -- and prose says "tools/plans.py" for either. Checking only
            # the first reported eleven healthy references as broken, which is
            # how a checker teaches people to ignore it.
            if not ((ROOT / m).exists() or (ROOT / "director" / m).exists()):
                bad.append(f"{p.relative_to(ROOT)} names `{m}`, which does not exist")
    return bad


def links() -> list[str]:
    """A relative link that 404s is a document telling you to go nowhere."""
    bad = []
    pat = re.compile(r"\[[^\]]+\]\((?!https?:|#)([^)#]+)")
    for p in [*sorted(DOCS.glob("*.md")), ROOT / "README.md", ROOT / "CLAUDE.md"]:
        for m in set(pat.findall(p.read_text(encoding="utf-8"))):
            if not (p.parent / m).exists():
                bad.append(f"{p.relative_to(ROOT)} links to {m}, which is missing")
    return bad


def main() -> int:
    checks = (("untyped documents", typed),
              ("endpoints named in prose", endpoints),
              ("commands named in prose", commands),
              ("relative links", links))
    findings = 0
    for name, fn in checks:
        got = fn()
        findings += len(got)
        print(f"{'FAIL' if got else 'ok  '}  {name}")
        for line in got:
            print(f"        {line}")
    if not findings:
        print("\nthe documents name things that exist, and each says what it is")
        return 0
    print(f"\n{findings} finding(s). A document that cannot be dated is one a "
          f"reader has to date by guessing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
