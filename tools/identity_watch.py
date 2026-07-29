"""Watch the controller decide WHO is talking, live, one line per transmission.

Yesterday's debugging was archaeology: fly, land, read a transcript, guess. The
recorder now keeps the whole identity decision on every transmission -- the
radio's SRS name, what the words claimed, which authority resolved it and to
which track -- so it can be read as it happens, over the engineering radio,
while the pilot is still airborne.

    uv run python tools/identity_watch.py                  # follow the live session
    uv run python tools/identity_watch.py --session live1  # or a past one
    uv run python tools/identity_watch.py --replay         # from the top, then follow

WHAT TO LOOK FOR, in the order it matters:

  AUTHORITY  `radar` is the chain with no microphone in it: SRS name -> the name
             radar prints -> track. Anything else means that chain did NOT
             close, and the reason is printed. A regular pilot on `plan` or
             `roster` every call is a finding, not a curiosity.

  MANNED     how many contacts the scope says have a person in them. A guest is
             identified by ELIMINATION against that count, so if it reads 0
             while somebody is flying, the whole guest path is dead and nothing
             else will tell you.

  CLAIM      what Whisper made of his callsign, beside what we concluded. When
             those differ and the identity still held, the design worked --
             that is the case that used to invent an aeroplane.

Read-only, and it never touches the bridge: a diagnostic that can break the
thing it is diagnosing is one nobody dares run during a sortie.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall import config

LOGS = config.BUILD_DIR / "logs"


def newest_session() -> str:
    files = sorted(LOGS.glob("flight-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"no flight recordings under {LOGS}")
    return files[-1].stem[len("flight-"):]


def manned_count(scope: str) -> int:
    from marshall.atc import identity
    return sum(1 for u in identity.units_on(scope or "") if u.manned)


def line_for(e: dict) -> str | None:
    if e.get("kind") != "pilot":
        return None
    when = time.strftime("%H:%M:%S", time.localtime(e.get("t", 0)))
    srs = (e.get("srs_name") or "?")[:14]
    claim = (e.get("claimed") or "")[:14]
    who = (e.get("callsign") or "")[:14]
    auth = e.get("authority") or "-"
    # A resolution that is NOT the physical chain is the thing worth seeing, so
    # it gets the marker rather than the normal case getting one. An eye
    # scanning a column of "radar" should catch the one row that is not.
    flag = "   <<" if auth not in ("radar",) else ""
    scope = e.get("scope") or ""
    n = manned_count(scope)
    contacts = "no contacts" if not scope or scope == "no contacts" else f"{n} manned"
    person = (e.get("who") or "")[:10]
    out = (f"{when}  radio={srs:14} claim={claim:14} -> {who:14} "
           f"[{auth:6}] {person:10} {contacts}{flag}")
    if auth not in ("radar",) and e.get("why"):
        out += f"\n           why: {e['why']}"
    if claim and who and claim != who:
        out += f"\n           heard {claim!r}, concluded {who!r}"
    return out


def follow(path: Path, replay: bool) -> int:
    print(f"watching {path.name}\n")
    print("time      radio          claim          -> resolved       "
          "authority  who        scope")
    with open(path, encoding="utf-8", errors="replace") as fh:
        if not replay:
            fh.seek(0, 2)                     # only what happens from now
        while True:
            where = fh.tell()
            raw = fh.readline()
            if not raw:
                time.sleep(0.5)
                fh.seek(where)
                continue
            try:
                e = json.loads(raw)
            except ValueError:
                continue                       # a half-written line; it will come
            out = line_for(e)
            if out:
                print(out, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="", help="default: the newest recording")
    ap.add_argument("--replay", action="store_true",
                    help="print the whole recording first, then follow")
    args = ap.parse_args()

    session = args.session or newest_session()
    path = LOGS / f"flight-{session}.jsonl"
    if not path.exists():
        raise SystemExit(f"no recording at {path}")
    try:
        return follow(path, args.replay)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
