"""File docs/ISSUES.md to GitHub, and write the issue numbers back into it.

The list has to be readable with no network and no token -- that is the whole
point of keeping it in the repo -- so this script treats the markdown as the
source and GitHub as a copy. Run it whenever the file gains an issue.

    export GH_TOKEN=<a PAT with repo scope>
    uv run python tools/file_issues.py --dry-run     # see what it would do
    uv run python tools/file_issues.py

Idempotent: an entry that already carries a number is skipped, so re-running
after adding one issue files exactly that one. Nothing is ever edited or closed
from here -- issues get closed by a human flying the test, which is the point of
the exercise.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ISSUES = Path(__file__).resolve().parent.parent / "docs" / "ISSUES.md"

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print("!! no GH_TOKEN in the environment -- gh will use its own login "
              "if you have one", file=sys.stderr)

    gh = gh_path()
    text = ISSUES.read_text(encoding="utf-8")
    issues = parse(text)
    todo = [i for i in issues if not i["number"]]

    print(f"{len(issues)} issues in {ISSUES.name}; {len(todo)} not yet filed")
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


if __name__ == "__main__":
    raise SystemExit(main())
