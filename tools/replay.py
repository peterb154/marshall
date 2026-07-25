"""Replay a recorded sortie through the current guidance.

The point is regression-testing against reality. When the vectoring was flying
a pilot at the field instead of around to the centreline, diagnosing it meant
copying eight positions out of a prose transcript into a scratch script by hand.
Every one of those positions is now recorded, so the same question -- "would the
fix have done better?" -- is answered by re-running the flight rather than
flying it again.

    uv run python tools/replay.py                       # the newest flight
    uv run python tools/replay.py build/logs/flight-vec-1740.jsonl
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marshall import config  # noqa: E402
from marshall.atc import asr  # noqa: E402
from marshall.core import route as R  # noqa: E402


def newest() -> str | None:
    logs = sorted((config.BUILD_DIR / "logs").glob("flight-*.jsonl"),
                  key=lambda p: p.stat().st_mtime)
    return str(logs[-1]) if logs else None


def replay(path: str, profile=R.BATUMI_ASR) -> None:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue

    print(f"=== {os.path.basename(path)} — {len(rows)} records ===\n")
    print(f"{'range':>6} {'radial':>7} {'alt':>6} {'hdg':>5} | "
          f"{'phase':7} {'fly':>4} {'turn':>5} {'alt':>5} | said")
    print("-" * 104)

    n = flown = 0
    for r in rows:
        if r.get("kind") == "debug":
            print(f"{'':38}| DEBUG: {r.get('text','')}")
            continue
        if r.get("kind") != "pilot" or r.get("range_nm") is None:
            continue
        n += 1
        pos = asr.Position(r["range_nm"], r["radial"], r.get("alt_ft") or 0,
                           r.get("heading") or 0.0)
        g = asr.guide(pos, profile)
        flown += g.established
        said = (r.get("transcript") or "")[:44]
        print(f"{pos.range_nm:6.1f} {pos.radial_deg:7.0f} {pos.alt_ft:6d} "
              f"{pos.heading_deg:5.0f} | {g.phase:7} {g.heading:4d} "
              f"{g.turn:>5} {str(g.altitude_ft):>5} | {said}")

    if not n:
        print("\nNo positions recorded -- was radar identifying him?")
        return
    print(f"\n{n} fixes, {flown} of them established on the approach "
          f"({flown / n * 100:.0f}%).")
    print("A sortie that never reaches 'final' means he was never joined up, "
          "which is a vectoring failure and not a pilot one.")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else newest()
    if not target:
        print("no recorded flights yet -- fly one and it will appear in "
              f"{config.BUILD_DIR / 'logs'}")
        raise SystemExit(1)
    replay(target)
