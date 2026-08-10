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
  UNFLOWN    no issue labelled `needs-flight-test` is missing from the card. The
             label says a human is the only instrument that can close it; if it
             is not on the card, nobody will ever pick it up
  ROWS       no two cockpit rows share an ID. "H18 failed" has to name ONE
             test -- two rows called H18 sat on the card for days, one of them
             cited by #50, and a pilot reporting it would have been reporting
             either
  UNIQUE     no two issues share a slug. [OPS-4] must mean one thing -- the
             slug is how a human refers to these in conversation and in a
             commit, and I filed three collisions in two days without noticing
  BODY       the text on GitHub still matches the markdown. `file_issues.py`
             wrote a body once and never again, so 58 of 76 had drifted --
             including #70, which went on telling a reader that the Nevada
             terrain surveys were outstanding after they had been flown and
             recorded. Fix with `file_issues.py --sync`

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
# A cockpit row: "| H7 | P2 | ... [#19] ..." or "| **Q1b** | ... [#57] ...".
# Struck-through IDs are already retired and are not a finding.
#
# THE BOLD FORM AND THE LETTERED SUFFIX ARE NOT DECORATION -- they are how the
# four newest sections are written, and this pattern could not see any of them.
# Q, R, S and T went in on 2 August with fourteen rows in Q alone, and every one
# was invisible here: the check reported "labelled needs-flight-test and no row
# cites it" for issues whose rows were sitting on the card, in the section
# written for them.
#
# A check that silently ignores a quarter of the document is worse than no
# check, because its silence reads as agreement -- the same fault as the three
# tools in #59, in the thing that is supposed to catch faults.
# `[R#n]` IS A DIFFERENT CLAIM FROM `[#n]`, and conflating them is #60. A row
# citing `[#n]` is CHASING finding n and is spent when n closes. A row citing
# `[R#n]` EXERCISES the fix in n and is the regression that tells us if it rots
# -- closing n is exactly when it starts earning its keep.
#
# Seventeen rows were written in the first form meaning the second, so this
# check told us to strike out the only rows that test handoffs between two
# aerodromes, on the grounds that the single-aerodrome fixes they exercise had
# been closed on earlier sorties -- which is the condition under which four of
# them were correct BY ACCIDENT.
ROW = re.compile(r"^\|\s*(~~)?\**([A-Z]\d+[a-z]?)\**~?~?\s*\|.*?\[(R)?#(\d+)\]",
                 re.M)

# Statuses that mean "this is finished". Everything else is live work.
DONE = {"VALIDATED", "CLOSED", "DONE"}


def gh_flight_test() -> dict[int, list[str]]:
    """Open issues a human is the only instrument for."""
    gh = shutil.which("gh") or str(Path.home() / ".local" / "bin" / "gh")
    out = subprocess.run(
        [gh, "issue", "list", "--state", "open", "--limit", "200",
         "--json", "number,labels"], capture_output=True, text=True)
    if out.returncode != 0:
        return {}
    got = {}
    for i in json.loads(out.stdout or "[]"):
        labs = [l["name"] for l in i.get("labels", [])]
        if "needs-flight-test" in labs:
            got[i["number"]] = labs
    return got


def gh_bodies() -> dict[int, str]:
    """Every issue body, in ONE call.

    Per-issue `gh issue view` is 76 round trips and about forty seconds, which
    is the kind of cost that gets a check quietly dropped from the gate. The
    list endpoint returns bodies just as happily.
    """
    gh = shutil.which("gh") or str(Path.home() / ".local" / "bin" / "gh")
    out = subprocess.run(
        [gh, "issue", "list", "--state", "all", "--limit", "300",
         "--json", "number,body"], capture_output=True, text=True)
    if out.returncode != 0:
        return {}
    return {i["number"]: (i.get("body") or "")
            for i in json.loads(out.stdout or "[]")}


def gh_states() -> dict[int, str] | None:
    """GitHub's state per issue, or None when GitHub cannot be reached."""
    gh = shutil.which("gh") or str(Path.home() / ".local" / "bin" / "gh")
    out = subprocess.run(
        [gh, "issue", "list", "--state", "all", "--limit", "200",
         "--json", "number,state"], capture_output=True, text=True)
    if out.returncode != 0:
        # EXIT 2 -- "could not run", not "they disagree". `tools/check.py` reads
        # 2 as SKIP and reports it by name, which is the difference between a
        # gate that is offline and a gate that is failing.
        #
        # An outside audit ran this without a token, got a red check, and
        # reasonably reported that the standard local quality gate depends on
        # the network. It also MASKED the real result: this check is genuinely
        # failing right now on card/issue drift (#60), and an auth error printed
        # in the same red made that indistinguishable from a firewall.
        #
        # A check that goes red for two unrelated reasons is a check nobody can
        # act on -- the same reason the approach sweep gates on a baseline
        # rather than on the known-open bugs.
        why = (out.stderr or "").strip() or "no output"
        print(f"cannot reach GitHub, so ISSUES.md and the card were NOT "
              f"compared: {why.splitlines()[0]}", file=sys.stderr)
        return None
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
    if state is None:
        return 2                      # SKIP, not FAIL -- see gh_states
    flight_test = gh_flight_test()
    items = entries(text)

    # TWO ISSUES WITH ONE NAME, which is how [OPS-4] came to mean both "the card
    # check was blind" and "a paused sim". I did that three times in two days --
    # OPS-4, OPS-5 and OPS-6 -- by appending to the file without reading up, and
    # nothing said a word. The NUMBER is unique because GitHub assigns it; the
    # SLUG is chosen by hand and is what anybody actually says out loud.
    # THE SAME DISEASE ON THE CARD. Row IDs are stable forever because issues
    # and attestations cite them -- "flown by card rows H18/H19" is in #50 --
    # so two rows called H18 means a pilot's report names neither. Found the
    # day the slug check went in, by looking for the same shape one document
    # over.
    seen_rows: dict[str, int] = {}
    dup_rows = []
    for _struck, rid, _reg, _num in ROW.findall(card):
        seen_rows[rid] = seen_rows.get(rid, 0) + 1
    dup_rows = sorted(r for r, n in seen_rows.items() if n > 1)

    seen_slugs: dict[str, str] = {}
    dup_slugs = []
    for e in items:
        if e["slug"] in seen_slugs:
            dup_slugs.append((e["slug"], seen_slugs[e["slug"]], e["num"] or "?"))
        else:
            seen_slugs[e["slug"]] = e["num"] or "?"

    # THE MIRROR HAS TO STILL BE A MIRROR. `ISSUES.md` is the source; GitHub is
    # the copy a reader may open first, and a copy that stopped being updated is
    # not a mirror but a second, older document that looks equally authoritative.
    # PARSED BY `file_issues.parse`, NOT BY A SECOND COPY OF IT. Whatever counts
    # as "the body" has to be the same string this checker compares and that
    # pusher sends, or the check goes permanently red on a difference nobody can
    # act on -- which is worse than not checking, and is the fault this tool
    # exists to catch.
    bodies = gh_bodies()
    body_drift = []
    if bodies:
        import importlib.util as _iu
        _spec = _iu.spec_from_file_location(
            "_file_issues", ROOT / "tools" / "file_issues.py")
        _fi = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(_fi)
        for i in _fi.parse(text):
            if not i["number"]:
                continue
            n = int(i["number"])
            if n in bodies and bodies[n].strip() != i["body"].strip():
                body_drift.append((i["slug"], n))

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

    for struck, rid, regression, num in ROW.findall(card):
        # A STRUCK ROW IS ALREADY RETIRED. The regex captured the marker and
        # the loop threw it away, so every row a pilot had just flown and
        # crossed off was reported as a finding -- the check telling you to do
        # the thing you had done. Its own comment said struck IDs are not a
        # finding; the code did not act on it.
        if struck:
            continue
        # A REGRESSION ROW IS NEVER STALE. Its subject is a CLOSED fix by
        # definition -- that is what makes it a regression -- so reporting it
        # would be reporting the design.
        if regression:
            continue
        if state.get(int(num)) == "CLOSED":
            stale_rows.append((rid, int(num)))

    # ...and the other way round. An issue that only a pilot can close, with no
    # row telling him to fly it, is a job nobody has been given. This direction
    # was unguarded, and #39 sat labelled `needs-design` after it had shipped --
    # which is how a thing gets built, put on the card, and still read as
    # unstarted.
    # BOTH FORMS COUNT AS COVERAGE. A pilot flying an `[R#n]` row is exercising
    # n just as surely as one flying `[#n]`; the notation says why the row
    # exists, not whether it tests the thing.
    on_card = {int(n) for _, _, _, n in ROW.findall(card)}
    unflown = [n for n, labs in flight_test.items()
               if state.get(n) == "OPEN" and n not in on_card]

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
    if unflown:
        print("NEEDS A PILOT, BUT IS NOT ON THE CARD")
        for n in sorted(unflown):
            print(f"  #{n} is labelled needs-flight-test and no row cites it")
    if body_drift:
        print("GITHUB IS SHOWING OLDER TEXT THAN ISSUES.md")
        for slug, n in body_drift[:12]:
            print(f"  #{n} [{slug}]")
        if len(body_drift) > 12:
            print(f"  ...and {len(body_drift) - 12} more")
        print("  Run: uv run python tools/file_issues.py --sync")
    if dup_rows:
        print("TWO COCKPIT ROWS WITH THE SAME ID")
        for rid in dup_rows:
            print(f"  {rid} appears {seen_rows[rid]} times")
        print("  A pilot reporting \"H18 failed\" would be naming neither.")
    if dup_slugs:
        print("TWO ISSUES WITH THE SAME NAME")
        for slug, first, second in dup_slugs:
            print(f"  [{slug}] is both #{first} and #{second}")
        print("  The number is unique because GitHub assigns it; the slug is")
        print("  chosen by hand and is what anybody says out loud. Renumber the")
        print("  LATER one -- first use keeps the name.")
    if not (drift or unfiled or stale_rows or unflown or dup_slugs or body_drift
            or dup_rows):
        print("in step: statuses match, everything filed, every row still earns "
              "its place, and no two issues share a name")
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
