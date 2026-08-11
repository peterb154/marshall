"""File docs/ISSUES.md to GitHub, and write the issue numbers back into it.

The list has to be readable with no network and no token -- that is the whole
point of keeping it in the repo -- so this script treats the markdown as the
source and GitHub as a copy. Run it whenever the file gains an issue.

    GH_TOKEN=<a PAT with repo scope>      in the repo root .env
    uv run python tools/file_issues.py --dry-run     # see what it would do
    uv run python tools/file_issues.py

Idempotent: an entry GitHub already holds is skipped, so re-running after adding
one issue files exactly that one. Nothing is ever CLOSED from here -- issues get
closed by a human flying the test, which is the point of the exercise.

    uv run python tools/file_issues.py --sync     # push changed bodies too

BODIES DRIFT, AND THAT IS WHAT `--sync` IS FOR. This script wrote a body once,
at filing time, and never again -- so every issue on GitHub carried the text it
was born with while `ISSUES.md` went on being edited. An outside grooming pass
found the result: **#70 still told a reader the Nevada MVA and grid-convergence
surveys were outstanding**, when both had been flown and recorded with measured
values, which reads as a live safety blocker that does not exist. #3 said TODO
for an approach that is built and test-covered; #50 said the cause of a requeue
was unknown when the issue text names it.

"Nothing is ever edited" was a rule about not CLOSING things behind a human's
back, and it silently grew to cover the body as well. The markdown is the
source and GitHub is the copy -- a copy that stops being updated is not a
mirror, it is a second, older document that looks equally authoritative.

"ALREADY FILED" MEANS GITHUB HAS IT, not that the markdown says so. This used to
skip any entry carrying a number, which treats a number typed into a heading as
proof the issue exists. Eleven did not: five had been given numbers by hand over
previous sessions and six more in one afternoon, all of them plausible, none of
them on GitHub -- and this script reported "0 not yet filed" every time it ran,
which is the most reassuring possible way to do nothing.

`issue_sync.py` was reporting the drift correctly the whole time. Nobody could
run it, because it needs the token and the token was set in an interactive-only
branch of a shell profile.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# IMPORTED FOR ITS SIDE EFFECT, and that is the whole point: `marshall.config`
# reads the git-ignored `.env` at the repo root into the environment. `gh` then
# finds `GH_TOKEN` there, exactly as it would have found it exported by hand.
#
# It used to live in `~/.bashrc`, behind the non-interactive early-return every
# shell profile has -- so it was invisible to anything this repo ran and had to
# be sourced by line number, which is not a thing anybody should be doing with
# a credential. One file holds this machine's secrets now, it is the file
# `SRS_HOST` is already in, and it is the one `config` reads.
from marshall import config as _config       # noqa: F401  (imported for .env)

ISSUES = ROOT / "docs" / "ISSUES.md"

# "## [SLUG] Title" with an optional "— #12" already appended.
HEAD = re.compile(r"^## \[([A-Z]+-\d+)\]\s+(.*?)(?:\s+—\s+#(\d+))?\s*$")


def gh_path() -> str:
    found = shutil.which("gh") or str(Path.home() / ".local" / "bin" / "gh")
    if not Path(found).exists():
        sys.exit("gh not found. Install it, or put it on PATH.")
    return found


def parse(text: str) -> list[dict]:
    """Every issue in the file, with its body and any number it already has."""
    out: list[dict] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = HEAD.match(line)
        if not m:
            continue
        slug, title, number = m.group(1), m.group(2), m.group(3)
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if HEAD.match(lines[j]):
                end = j
                break
        body = "\n".join(lines[i + 1:end]).strip()
        labels = []
        lm = re.search(r"^labels:\s*(.+)$", body, re.M)
        if lm:
            labels = [x.strip() for x in lm.group(1).split(",") if x.strip()]
            body = re.sub(r"^labels:.*$", "", body, count=1, flags=re.M).strip()
        out.append({"slug": slug, "title": title, "body": body,
                    "labels": labels, "number": number, "line": i})
    return out


def ensure_labels(gh: str, labels: set[str]) -> None:
    """Create any label that does not exist yet. A missing label makes
    `issue create` fail outright, which would strand half the list."""
    try:
        have = subprocess.run([gh, "label", "list", "--limit", "100",
                               "--json", "name", "-q", ".[].name"],
                              capture_output=True, text=True, check=True)
        existing = set(have.stdout.split())
    except subprocess.CalledProcessError:
        existing = set()
    for name in sorted(labels - existing):
        subprocess.run([gh, "label", "create", name], capture_output=True)


def known_numbers(gh: str) -> set[int]:
    """Every issue number GitHub actually holds, open or closed."""
    r = subprocess.run([gh, "issue", "list", "--state", "all", "--limit", "500",
                        "--json", "number", "-q", ".[].number"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"could not read the issue list: {r.stderr.strip()}")
    return {int(n) for n in r.stdout.split()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sync", action="store_true",
                    help="also push bodies, titles and labels that have drifted")
    args = ap.parse_args()

    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print("!! no GH_TOKEN in the environment -- gh will use its own login "
              "if you have one", file=sys.stderr)

    gh = gh_path()
    text = ISSUES.read_text(encoding="utf-8")
    issues = parse(text)

    # ASK GITHUB WHAT IT HAS. An entry is filed when GitHub holds that number,
    # not when the markdown claims one -- see the note at the top of this file.
    have = known_numbers(gh)
    todo = [i for i in issues
            if not i["number"] or int(i["number"]) not in have]

    stale = [i for i in todo if i["number"]]
    print(f"{len(issues)} issues in {ISSUES.name}; {len(have)} on GitHub; "
          f"{len(todo)} not yet filed")
    if stale:
        # Say it out loud. A heading that names an issue number nobody can open
        # is worse than one with no number: the commit trailer points at it, the
        # test card cites it, and every one of those links is dead.
        print(f"  {len(stale)} of them CLAIM a number GitHub does not have -- "
              f"they will be filed and renumbered:")
        for i in stale:
            print(f"    was #{i['number']:<4} [{i['slug']}] {i['title'][:52]}")
    # BEFORE the dry-run return, or `--sync --dry-run` silently reports nothing
    # -- which is the one combination somebody runs first to see what it will do.
    if args.sync and not todo:
        return sync_bodies(gh, issues, args.dry_run)

    if args.dry_run:
        for i in todo:
            print(f"  [{i['slug']}] {i['title']}"
                  f"  labels={','.join(i['labels']) or '-'}"
                  f"  body={len(i['body'])} chars")
        return 0
    if not todo:
        return 0

    ensure_labels(gh, {l for i in todo for l in i["labels"]})

    lines = text.splitlines()
    for i in todo:
        cmd = [gh, "issue", "create", "--title", f"[{i['slug']}] {i['title']}",
               "--body", i["body"]]
        for label in i["labels"]:
            cmd += ["--label", label]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  !! [{i['slug']}] failed: {r.stderr.strip()}", file=sys.stderr)
            continue
        url = r.stdout.strip().splitlines()[-1]
        num = url.rstrip("/").rsplit("/", 1)[-1]
        lines[i["line"]] = f"## [{i['slug']}] {i['title']} — #{num}"
        print(f"  #{num:<5} [{i['slug']}] {i['title']}")

    ISSUES.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("numbers written back to docs/ISSUES.md")
    return 0


def sync_bodies(gh, issues, dry_run: bool = False) -> int:
    """Push any body GitHub holds that no longer matches the markdown.

    Compared rather than blindly written, so a run that changes nothing says so
    and a run that changes ten things names them. Titles too: a slug rename has
    to reach the mirror or the two documents disagree about what a thing is
    called, which is how [OPS-4] came to mean two issues.
    """
    changed = 0
    for i in issues:
        if not i["number"]:
            continue
        n = int(i["number"])
        r = subprocess.run(
            [gh, "issue", "view", str(n), "--json", "body,title,labels"],
            capture_output=True, text=True)
        if r.returncode != 0:
            continue
        import json as _json
        got = _json.loads(r.stdout or "{}")
        want_title = f"[{i['slug']}] {i['title']}"
        same_body = (got.get("body") or "").strip() == i["body"].strip()
        same_title = (got.get("title") or "").strip() == want_title
        # LABELS DRIFT AND NOBODY WAS PUSHING THEM. This sweep has always
        # written the body and the title and never the labels, so a label added
        # in ISSUES.md simply never reached GitHub -- and one of them decides
        # who owns an issue. Thirteen entries declared `needs-flight-test` and
        # carried no such label on GitHub, where `issue_sync.gh_flight_test`
        # looks, so the check that demands a card row for every issue only a
        # pilot can close was blind to all thirteen.
        #
        # ADDITIVE ONLY. GitHub carries priority labels (`p1`, `p2`) set there
        # and belonging there; ISSUES.md is not the authority on those and
        # removing what it does not mention would throw them away.
        have_labs = {x["name"] for x in got.get("labels", [])}
        add_labs = sorted(set(i["labels"]) - have_labs)
        if same_body and same_title and not add_labs:
            continue
        what = ", ".join(filter(None, [
            "" if same_body else "body",
            "" if same_title else "title",
            f"labels ({', '.join(add_labs)})" if add_labs else ""]))
        print(f"  #{n:<5} [{i['slug']}] {what} drifted")
        changed += 1
        if dry_run:
            continue
        if add_labs:
            ensure_labels(gh, set(add_labs))
        cmd = [gh, "issue", "edit", str(n), "--body", i["body"]]
        if not same_title:
            cmd += ["--title", want_title]
        for lab in add_labs:
            cmd += ["--add-label", lab]
        e = subprocess.run(cmd, capture_output=True, text=True)
        if e.returncode != 0:
            print(f"     !! failed: {e.stderr.strip()}", file=sys.stderr)
    print(f"{changed} issue(s) {'would be ' if dry_run else ''}brought in step"
          if changed else "every body on GitHub matches ISSUES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
