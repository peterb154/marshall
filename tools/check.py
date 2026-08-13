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

The offline tier runs the unit suite on ONE map and only checks that it LOADS on
the others. Running it on all of them is `tools/both_maps.py --run`, which costs
31 seconds against this tier's 7 -- see the comment on that entry for why that
is not the default.

**Skipped is reported, never silent.** A check that quietly does not run reads
exactly like a check that passed, and that is worse than having no check --
it is the same failure as a controller who goes quiet.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# HOSTS AND PORTS COME FROM `marshall.config`, which reads the .env files
# the rest of the system reads. This is a public repo: a LAN address
# written down here is both a leak and a second opinion.
sys.path.insert(0, str(ROOT / "src"))
from marshall import config as _config

PY = sys.executable

# (name, argv, what it guards, needs the sim/SRS)
CHECKS = [
    ("lint", [PY, "-m", "ruff", "check", "src", "tools", "tests", "director"],
     "undefined names, dead locals, loop-variable closures — it found two real "
     "bugs the first time it ran", False),
    ("unit suite", [PY, "-m", "pytest", "-q"],
     "the separation engine, callsign identity, phraseology, the geometry", False),
    # THE SUITE THAT IS RUN IS THE SUITE THAT IS TRUE. On 13 August the second
    # map did not report failures -- it reported `Interrupted: 8 errors during
    # collection`, and the eight were the two-aerodrome guard, the ILS guard,
    # the ATIS guard, the handoff rule table and "the wind has one author". Each
    # opened with a module-scope `P = R.BATUMI_ASR`, resolved at IMPORT against
    # a theatre chosen by environment. A whole month, unnoticed, because nobody
    # ran it there.
    #
    # COLLECT ONLY, and that is a deliberate line. Loading every module on every
    # published map costs about 1.5 seconds a map and catches exactly the fault
    # above. RUNNING both suites costs 31 seconds against the 7 this whole tier
    # takes today, and Nevada is not green -- it carries a baseline of failures
    # that are real `src/` defects on #137's list. Putting that in the default
    # path would quadruple the runtime of the check people actually run, to show
    # them a number that is red on purpose. `tools/both_maps.py --run` is one
    # command away and is the thing to run before touching `core/theatre.py`.
    ("every module loads on every map",
     [PY, "tools/both_maps.py"],
     "#137 — a test module that binds a Caucasus name at import cannot be "
     "COLLECTED on another map, and a suite that will not load reads exactly "
     "like a suite with nothing to say", False),
    ("nothing new is unwired", [PY, "tools/unwired.py"],
     "#69 — a thing that exists and nothing reaches. The dominant failure mode "
     "here: a complete state machine nobody called, an attribute read six times "
     "and assigned never, a clearance stored and never read back out", False),
    ("approach sweep", [PY, "tools/asr_sweep.py"],
     "1,296 approaches: arrivals, dithering, where they establish", False),
    ("approach sweep, sloppy pilot", [PY, "tools/asr_sweep.py", "--sloppy"],
     "the same, flown by somebody who lags and overshoots", False),
    ("approach sweep, pilot not turning", [PY, "tools/asr_sweep.py", "--deaf"],
     "#19 — whether the controller argues with itself when the geometry refuses "
     "to improve, which an obedient aeroplane can never show", False),
    ("the docs name things that exist", [PY, "tools/docs_check.py"],
     "#78 -- every document says what it is, and the endpoints, commands and "
     "links in prose resolve. The README described the INVERSE of the "
     "architecture for weeks", False),
    ("issues and the card in step", [PY, "tools/issue_sync.py"],
     "#27 — that ISSUES.md, GitHub and the cockpit card still agree. Twenty of "
     "thirty-seven had drifted before anyone looked", False),
    ("filed plans, resolved", [PY, "tools/plan_sweep.py"],
     "#1 G3/G4 — which plan a spoken request means, and when to ASK instead of "
     "picking one", False),
    ("filed plans, assigned", [PY, "tools/plan_assign_check.py"],
     "#1 — two flights, two plans, and an amendment that touches neither the "
     "other aeroplane nor what was filed", False),
    ("wait for the check-in", [PY, "tools/checkin_check.py"],
     "#6 B1a — a controller works the men on HIS frequency and nobody else",
     False),
    ("one in the letdown", [PY, "tools/letdown_check.py"],
     "#15 D4/F4 — nobody vectored until somebody is cleared, and it survives a "
     "restart emptying the stack", False),
    ("handoff cases", [PY, "tools/handoff_check.py"],
     "#16 C5/C6 — airspace handoffs, including one that must FIRE", True),
    ("contested channel", [PY, "tools/channel_check.py"],
     "#5 F2/F3 — holding a call for a pilot, and making it afterwards", True),
    ("visual approaches", [PY, "tools/visual_check.py"],
     "#10 C1/C2/C3 — granted without argument, mile calls stop, and 'field in "
     "sight' is a report", True),
    ("break-up identity", [PY, "-m", "marshall.radio.rehearsal", "--srs",
                           _config.SRS_HOST, "124.0",
                           "breakup"],
     "#12 — two radios through a formation split", True),
    ("go-around", [PY, "-m", "marshall.radio.rehearsal", "--srs",
                   _config.SRS_HOST, "124.0",
                   "goaround"],
     "#11 B8 — no vector back towards the field while climbing out", True),
]


def sim_is_up() -> bool:
    """Cheap liveness for the things a LIVE check needs."""
    import socket
    addr = _config.DCS_GRPC_ADDR
    host, _, port = addr.partition(":")
    for h, p in ((host, int(port or 50051)),
                 (_config.SRS_HOST, 5002)):
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
        # 2 means the check could not run -- no director, nothing on file.
        # Reported as SKIPPED rather than passed, for the same reason as the
        # live tier: a check that quietly does not run reads exactly like one
        # that passed.
        if r.returncode == 2:
            skipped.append((name, guards,
                            (r.stdout or r.stderr or "").strip().splitlines()[-1]
                            if (r.stdout or r.stderr).strip() else "could not run"))
            print("   SKIP\n")
            continue
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
