"""Issues that say OPEN while a test in the tree already cites them.

A grooming pass on 14 August found FOUR statuses that were wrong -- #151, #153,
#169 and #170 all said OPEN or "diagnosed, not fixed" while the code carried the
fix and, in three cases, a test file written for it. One of them named its own
remaining work in detail and had been true a week earlier.

WHY THAT MATTERS MORE THAN TIDINESS. The backlog is what decides what gets done
next and what a pilot is asked to fly. Four entries claiming work that was
finished is four things nobody picked up because they looked done-adjacent, and
it is why the list *felt* unbounded while it was shrinking. It also wastes the
scarcest thing here, which is a sortie: an issue that says OPEN does not get a
card row, so a fix that landed gets flown by nobody.

THIS IS A HEURISTIC AND SAYS SO. A test citing an issue does NOT mean the issue
is closed -- this project deliberately writes CHARACTERISATION tests that pin a
bug in place before fixing it, and `test_nothing_has_told_us_is_not_he_is_flying`
is exactly that: #149 is genuinely open and its test describes what is wrong.
So this prints a list to READ, never a failure. The judgement stays human.

    uv run python tools/stale_check.py

Exits 0 always. It is a grooming aid, not a gate -- a check that went red on a
correct characterisation test would be switched off within a week, and then the
real drift would be invisible again.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

# Statuses that CLAIM there is work left. Anything else -- FIXED, CLOSED,
# PARTLY, REOPENED -- is either finished or honestly mid-flight.
CLAIMS_WORK = ("OPEN", "TODO")


def open_on_github() -> dict[int, set[str]]:
    import file_issues as F
    got = subprocess.run(
        [F.gh_path(), "issue", "list", "--state", "open", "--limit", "300",
         "--json", "number,labels"], capture_output=True, text=True)
    if got.returncode:
        return {}
    return {i["number"]: {x["name"] for x in i.get("labels", [])}
            for i in json.loads(got.stdout or "[]")}


def citations() -> dict[int, set[str]]:
    """Which files mention `#N`. Tests only -- source citing an issue is the
    normal way this codebase explains itself and means nothing about state."""
    out: dict[int, set[str]] = {}
    for p in sorted(Path("tests").rglob("*.py")):
        text = p.read_text(errors="ignore")
        for n in {int(x) for x in re.findall(r"#(\d{1,3})\b", text)}:
            out.setdefault(n, set()).add(str(p))
    return out


def main() -> int:
    import file_issues as F
    live = open_on_github()
    if not live:
        print("stale check: GitHub is not reachable, so nothing was compared")
        return 0
    cites = citations()
    entries = {int(e["number"]): e
               for e in F.parse((ROOT / "docs" / "ISSUES.md").read_text())
               if e["number"]}

    suspect = []
    for num, labels in sorted(live.items()):
        if "needs-flight-test" in labels:
            continue              # code complete already; waiting on a pilot
        e = entries.get(num)
        if not e:
            continue
        m = re.search(r"\*\*Status:\*\*\s*(\w+)", e["body"])
        if not m or m.group(1).upper() not in CLAIMS_WORK:
            continue
        # A file NAMED for this issue's fix is the strong signal. Any old
        # mention is weak -- issues cite each other constantly.
        files = sorted(cites.get(num, ()))
        if files:
            suspect.append((num, m.group(1).upper(), e["title"], files))

    if not suspect:
        print("no open issue has a test citing it")
        return 0

    print(f"{len(suspect)} open issue(s) already cited by a test -- READ, do "
          f"not act:\n")
    for num, st, title, files in suspect:
        print(f"  #{num:<4} [{st}] {title[:58]}")
        for f in files[:3]:
            print(f"           {f}")
    print("\n  A test citing an issue does NOT mean it is done. This project "
          "writes\n  characterisation tests that pin a bug before fixing it -- "
          "#149's names\n  the defect in its own filename and is correctly "
          "open. Check the code\n  against the acceptance criteria, then either "
          "fix the status or leave it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
