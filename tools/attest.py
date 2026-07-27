"""Close an issue with a record of how it was tested, and at what commit.

An issue closed with "works now" is an issue you cannot revisit. Six weeks later
the only questions that matter are *what was actually exercised* and *against
which code* -- and neither is recoverable from a green tick.

    uv run python tools/attest.py 4 --by Hoover \\
        --how "flew card rows A1-A4; both frequencies answered, empty bench
               said so" --close

    uv run python tools/attest.py 18 --by "tools/bench.py + unit suite" \\
        --how "second bridge refused and named the PID; kill -9 left no
               stale lock" --close

The commit is taken from HEAD, so the attestation says which code was tested
rather than which code happens to be current when somebody reads it. Anything
uncommitted at the time is flagged, because "tested at abc1234" is a lie if the
tree was dirty.

Without --close it just records the evidence, which is the right thing when a
test passes but the issue has more to it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("issue", type=int)
    ap.add_argument("--by", required=True,
                    help="who or what tested it: a pilot's callsign, or the tool")
    ap.add_argument("--how", required=True,
                    help="what was actually exercised, in a sentence")
    ap.add_argument("--close", action="store_true")
    args = ap.parse_args()

    gh = shutil.which("gh") or str(Path.home() / ".local" / "bin" / "gh")
    if not Path(gh).exists():
        sys.exit("gh not found")

    sha = _git("rev-parse", "--short", "HEAD")
    subject = _git("log", "-1", "--format=%s")
    dirty = bool(_git("status", "--porcelain"))
    when = time.strftime("%Y-%m-%d %H:%M %Z")

    body = (f"**Tested by:** {args.by}\n"
            f"**What was exercised:** {args.how}\n"
            f"**At commit:** `{sha}` — {subject}\n"
            f"**When:** {when}\n")
    if dirty:
        body += ("\n> ⚠️ The working tree was DIRTY at the time, so `"
                 + sha + "` is not exactly what was tested. Treat this "
                 "attestation as approximate and re-run it on a clean tree "
                 "before relying on it.\n")
    if not args.close:
        body += "\nNot closing — evidence recorded, the issue has more to it.\n"

    env = dict(os.environ)
    cmd = [gh, "issue", "comment", str(args.issue), "--body", body]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"could not comment: {r.stderr.strip()}")
    print(f"#{args.issue}: attested by {args.by} at {sha}"
          + ("  (DIRTY TREE)" if dirty else ""))

    if args.close:
        r = subprocess.run([gh, "issue", "close", str(args.issue)],
                           capture_output=True, text=True, env=env, cwd=ROOT)
        print("  closed" if r.returncode == 0 else f"  !! {r.stderr.strip()}")
    return 0


# Closing on GitHub is only half of it: `docs/ISSUES.md` is the copy that reads
# with no network and the one the kneeboard renders, and for a fortnight it was
# the one that went stale. A close that does not write the status back leaves
# the two disagreeing, and both look authoritative.
def _sync_back() -> None:
    import subprocess as _sp
    import sys as _sys
    from pathlib import Path as _P
    tool = _P(__file__).with_name("issue_sync.py")
    r = _sp.run([_sys.executable, str(tool), "--fix"],
                capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    if tail:
        print("  " + tail[-1])


if __name__ == "__main__":
    _rc = main()
    _sync_back()
    raise SystemExit(_rc)
