"""Run everything that can be run, cheapest first, and say what was skipped.

The unit suite runs on demand and the rest did not: the sweep, the voice
rehearsals, the handoff and channel checks were each a thing somebody had to
remember. A fix nobody re-runs is a fix that rots, and this project has already
shipped one regression an hour after writing down the rule against it.

    uv run python tools/check.py             # everything that needs no sim
    uv run python tools/check.py --live      # add the ones that do

Two tiers, and the split is about what they need rather than what they cover:

  OFFLINE   unit tests and the approach sweep. No sim, no SRS, no model. A few
            seconds. There is no excuse for not running these.
  LIVE      the voice rehearsals and the sim-backed checks. They need DCS, the
            SRS server and the bridge, take minutes, and cost model calls.

**Skipped is reported, never silent.** A check that quietly does not run reads
exactly like a check that passed, and that is worse than having no check --
it is the same failure as a controller who goes quiet.
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
PY = sys.executable

# (name, argv, what it guards, needs the sim/SRS)
CHECKS = [
    ("unit suite", [PY, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
     "the separation engine, callsign identity, phraseology, the geometry", False),
    ("approach sweep", [PY, "tools/asr_sweep.py"],
     "1,296 approaches: arrivals, dithering, where they establish", False),
    ("approach sweep, sloppy pilot", [PY, "tools/asr_sweep.py", "--sloppy"],
     "the same, flown by somebody who lags and overshoots", False),
    ("handoff cases", [PY, "tools/handoff_check.py"],
     "#16 C5/C6 — airspace handoffs, including one that must FIRE", True),
    ("contested channel", [PY, "tools/channel_check.py"],
     "#5 F2/F3 — holding a call for a pilot, and making it afterwards", True),
    ("break-up identity", [PY, "-m", "marshall.srs.rehearsal", "--srs",
                           os.environ.get("SRS_HOST", "192.168.0.35"), "124.0",
                           "breakup"],
     "#12 — two radios through a formation split", True),
    ("go-around", [PY, "-m", "marshall.srs.rehearsal", "--srs",
                   os.environ.get("SRS_HOST", "192.168.0.35"), "124.0",
                   "goaround"],
     "#11 B8 — no vector back towards the field while climbing out", True),
]


def sim_is_up() -> bool:
    """Cheap liveness for the things a LIVE check needs."""
    import socket
    addr = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
    host, _, port = addr.partition(":")
    for h, p in ((host, int(port or 50051)),
                 (os.environ.get("SRS_HOST", "192.168.0.35"), 5002)):
        try:
            with socket.create_connection((h, p), timeout=3):
                pass
        except OSError:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true",
                    help="also run the checks that need DCS, SRS and the bridge")
    args = ap.parse_args()

    live_ok = sim_is_up() if args.live else False
    if args.live and not live_ok:
        print("!! --live asked for, but the sim or SRS is not reachable.\n"
              "   The live checks will be SKIPPED, not silently passed.\n")

    results, skipped = [], []
    for name, argv, guards, needs_live in CHECKS:
        if needs_live and not (args.live and live_ok):
            skipped.append((name, guards,
                            "needs --live" if not args.live else "sim unreachable"))
            continue
        print(f"── {name}")
        print(f"   {guards}")
        t0 = time.monotonic()
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        dt = time.monotonic() - t0
        ok = r.returncode == 0
        results.append((name, ok))
        tail = (r.stdout or r.stderr or "").strip().splitlines()[-3:]
        for line in tail:
            print(f"     {line}")
        print(f"   {'PASS' if ok else 'FAIL'}  ({dt:.0f}s)\n")

    print("=" * 62)
    bad = [n for n, ok in results if not ok]
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    for name, guards, why in skipped:
        print(f"  SKIP  {name}  ({why})")
        print(f"        unguarded right now: {guards}")
    if skipped:
        print("\n  Skipped is not passed. Those checks guard real regressions and\n"
              "  nothing is watching them until they run.")
    print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
