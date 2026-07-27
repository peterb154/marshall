"""Do docs/ISSUES.md, GitHub and the test card still agree?

They stopped, and nobody noticed for a fortnight. Twenty issues of thirty-seven
were CLOSED on GitHub while `ISSUES.md` still called them SHIPPED/UNVERIFIED,
OPEN or TODO -- including [OPS-2], whose entire subject is keeping the backlog
and the issues in step, and which was itself closed and stale.

It matters because the two copies are not equals. `ISSUES.md` is the one that
reads with no network and no token, it is what the kneeboard renders in the
cockpit, and it is the one a pilot consults at three in the morning. GitHub is
the mirror. A mirror that has moved on without telling anybody is worse than no
mirror, because both look authoritative.

    uv run python tools/issue_sync.py            # report, exit 1 on drift
    uv run python tools/issue_sync.py --fix      # write GitHub's state back

Three things are checked:

  STATE      an issue closed on GitHub must not read OPEN/TODO in the markdown
  FILED      every issue in the markdown has a number
  CARD       no cockpit test row cites a CLOSED issue -- a pilot's attention is
             the scarcest thing here and a closed row is spending it on nothing

`--fix` only ever writes the STATUS line, and only from closed-on-GitHub to
CLOSED. It will not reopen anything and it will not touch prose: a status is
bookkeeping, and the words around it are the record of what somebody learned.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISSUES = ROOT / "docs" / "ISSUES.md"
CARD = ROOT / "docs" / "TEST_PLAN.md"

HEAD = re.compile(r"^## \[([A-Z]+-\d+)\]\s+(.*?)(?:\s+—\s+#(\d+))?\s*$", re.M)
STATUS = re.compile(r"^\*\*Status:\*\*\s*([A-Z/]+)", re.M)
# A cockpit row: "| H7 | P2 | ... [#19] ...". Struck-through IDs are already
# retired and are not a finding.
ROW = re.compile(r"^\|\s*(~~)?([A-Z]\d+)~?~?\s*\|.*?\[#(\d+)\]", re.M)

# Statuses that mean "this is finished". Everything else is live work.
DONE = {"VALIDATED", "CLOSED", "DONE"}


def gh_states() -> dict[int, str]:
    gh = shutil.which("gh") or str(Path.home() / ".local" / "bin" / "gh")
    out = subprocess.run(
        [gh, "issue", "list", "--state", "all", "--limit", "200",
         "--json", "number,state"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"gh failed: {out.stderr.strip() or 'no output'}")
    return {i["number"]: i["state"] for i in json.loads(out.stdout or "[]")}


def entries(text: str) -> list[dict]:
    marks = list(HEAD.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        st = STATUS.search(body)
        out.append({"slug": m.group(1), "num": m.group(3),
                    "status": st.group(1) if st else "",
                    "span": (m.end(), end),
                    "status_at": (m.end() + st.start(1), m.end() + st.end(1))
                    if st else None})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true",
                    help="write GitHub's closed state back into ISSUES.md")
    args = ap.parse_args()

    text = ISSUES.read_text(encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    state = gh_states()
    items = entries(text)

    drift, unfiled, stale_rows = [], [], []
    for e in items:
        if not e["num"]:
            unfiled.append(e["slug"])
            continue
        n = int(e["num"])
        gs = state.get(n)
        if gs is None:
            drift.append((e, None, "not on GitHub"))
        elif gs == "CLOSED" and e["status"] not in DONE:
            drift.append((e, n, f"closed on GitHub, reads {e['status'] or '?'}"))
        elif gs == "OPEN" and e["status"] in DONE:
            drift.append((e, n, f"open on GitHub, reads {e['status']}"))

    for _, rid, num in ROW.findall(card):
        if state.get(int(num)) == "CLOSED":
            stale_rows.append((rid, int(num)))

    print(f"{len(items)} issues in ISSUES.md, {len(state)} on GitHub\n")
    if unfiled:
        print("NOT FILED (run tools/file_issues.py)")
        for s in unfiled:
            print(f"  {s}")
    if drift:
        print("OUT OF STEP")
        for e, n, why in drift:
            print(f"  {e['slug']:10} #{n}  {why}")
    if stale_rows:
        print("CLOSED ISSUES STILL ON THE COCKPIT CARD")
        for rid, n in stale_rows:
            print(f"  row {rid} cites #{n}, which is closed")
        print("  A pilot's attention is the scarcest thing here; retire the row")
        print("  (strike the ID through) and keep its script as the regression.")
    if not (drift or unfiled or stale_rows):
        print("in step: statuses match, everything filed, no closed rows on the card")
        return 0

    if args.fix and drift:
        # Only ever closed-on-GitHub -> CLOSED, and only the status word.
        for e, n, _why in sorted(drift, key=lambda d: -(d[0]["status_at"] or (0, 0))[0]):
            if n is None or state.get(n) != "CLOSED" or not e["status_at"]:
                continue
            a, b = e["status_at"]
            text = text[:a] + "CLOSED" + text[b:]
        ISSUES.write_text(text, encoding="utf-8")
        print(f"\nwrote {sum(1 for e, n, _ in drift if n and state.get(n) == 'CLOSED')} "
              f"status lines back into docs/ISSUES.md")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
