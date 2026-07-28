"""Who the controller thinks is talking, who he is talking TO, and what is flying.

    "I wonder, if while debugging, we can show who the controller thinks is
     talking and he is talking to.. maybe also a roster of active tracks?"

Three questions that have always had to be reconstructed from a transcript
afterwards, and which disagree with each other in exactly the interesting
cases:

  TRACKS   what the sim says is flying, which aeroplanes have a PERSON in them,
           and which of those a callsign has been tied to. The ground truth,
           and the only one of the three that cannot be argued with.

  BOARD    what the separation engine believes exists. The gap between this and
           TRACKS is the whole ghost problem -- an entry here with no track out
           there was made of words.

  RADIO    the last exchanges: who spoke, what evidence identified him, and who
           the controller answered. A reply addressed to the right pilot by the
           wrong NAME is a different bug from one answered to the wrong pilot,
           and only showing both columns tells them apart.

    uv run python tools/whos_who.py              # refresh every few seconds
    uv run python tools/whos_who.py --once       # one look, for a script

Read-only, and it asks the director rather than the bridge: a diagnostic that
can disturb the thing it is diagnosing is one nobody dares run during a sortie.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall import config
from marshall.atc import identity

RADAR_URL = "http://localhost:8000/radar"
LOGS = config.BUILD_DIR / "logs"


def scope_now(timeout: float = 5.0) -> str:
    try:
        with urllib.request.urlopen(RADAR_URL, timeout=timeout) as r:
            return json.load(r).get("picture") or ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return f"!! radar unavailable: {e}"


def newest_session() -> str:
    files = sorted(LOGS.glob("flight-*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1].stem[len("flight-"):] if files else ""


def tail(session: str, n: int = 400) -> list[dict]:
    path = LOGS / f"flight-{session}.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    out = []
    for raw in lines:
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def draw(session: str) -> None:
    scope = scope_now()
    entries = tail(session)

    print("\033[2J\033[H", end="")            # clear, so it reads as a display
    print(f"WHO'S WHO   session {session}   {time.strftime('%H:%M:%S')}")

    # -- TRACKS ------------------------------------------------------------
    print("\nTRACKS — what the sim says is flying")
    if scope.startswith("!!"):
        print(f"  {scope}")
    elif not scope or scope == "no contacts":
        print("  no contacts")
    else:
        units = identity.units_on(scope)
        if not units:
            print(f"  (unparsed) {scope[:100]}")
        print(f"  {'contact':22} {'type':16} {'person?':8} tied to")
        for u in units:
            who = u.callsign or "-- not correlated --"
            print(f"  {u.name[:22]:22} {u.type[:16]:16} "
                  f"{'MANNED' if u.manned else 'AI':8} {who}")

    # -- BOARD -------------------------------------------------------------
    # `None` means no snapshot has been taken; `[]` means one was taken and the
    # engine believes NOTHING exists. Those are different answers and reading
    # them the same is how a diagnostic misleads at the worst moment -- "no
    # data" and "no aircraft" look identical and mean opposite things.
    snap = next((e for e in reversed(entries) if e.get("kind") == "board"), None)
    board = None if snap is None else (snap.get("board") or [])
    print("\nBOARD — what the separation engine believes exists")
    if board is None:
        print("  (no snapshot yet — the bridge has not taken a transmission)")
    elif not board:
        print("  empty — the engine is tracking nobody")
    else:
        print(f"  {'callsign':16} {'phase':10} {'level':>7} {'radar?':8} letdown")
        for r in board:
            lvl = r.get("assigned_ft")
            print(f"  {(r.get('callsign') or '')[:16]:16} "
                  f"{(r.get('phase') or '')[:10]:10} "
                  f"{(f'{lvl:,}' if lvl else '-'):>7} "
                  f"{('seen' if r.get('identified') else 'NOT SEEN'):8} "
                  f"{'<-- in the letdown' if r.get('in_letdown') else ''}")
        # The comparison the two panels exist for.
        on_scope = {u.callsign for u in identity.units_on(scope) if u.callsign}
        ghosts = [r.get("callsign") for r in board
                  if not r.get("identified") and r.get("callsign") not in on_scope]
        if ghosts:
            print(f"\n  !! on the board, not on radar: {', '.join(ghosts)}")

    # -- RADIO -------------------------------------------------------------
    print("\nRADIO — last exchanges")
    print(f"  {'time':8} {'heard from':16} {'via':8} {'answered to':16} what")
    shown = 0
    for e in reversed(entries):
        if shown >= 6:
            break
        if e.get("kind") == "pilot":
            when = time.strftime("%H:%M:%S", time.localtime(e.get("t", 0)))
            who = e.get("callsign") or "?"
            auth = e.get("authority") or "REFUSED"
            reply = next((x for x in entries
                          if str(x.get("kind", "")).startswith("atc/")
                          and x.get("t", 0) >= e.get("t", 0)), None)
            to = (reply or {}).get("to") or "-"
            # The disagreement worth seeing: answered to somebody other than
            # the man we concluded was talking.
            mark = "  <-- MISMATCH" if to not in ("-", who) else ""
            print(f"  {when:8} {who[:16]:16} {auth[:8]:8} {to[:16]:16} "
                  f"{(e.get('transcript') or '')[:38]}{mark}")
            shown += 1
    if not shown:
        print("  (nothing yet)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=float, default=4.0)
    args = ap.parse_args()

    session = args.session or newest_session()
    if not session:
        raise SystemExit(f"no flight recordings under {LOGS}")
    if args.once:
        draw(session)
        return 0
    try:
        while True:
            draw(session)
            time.sleep(args.every)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
