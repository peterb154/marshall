"""Run the unit suite once per published map, and judge each on its own terms.

    uv run python tools/both_maps.py            # collect on every map (fast)
    uv run python tools/both_maps.py --run      # and actually run them
    uv run python tools/both_maps.py --run --map nevada

WHY THIS EXISTS. On 13 August, `MARSHALL_THEATRE=nevada pytest tests -q` did not
report failures -- it reported `Interrupted: 8 errors during collection`. Eight
modules could not be LOADED, and the eight were the two-aerodrome guard, the ILS
guard, the ATIS guard, the handoff rule table and "the wind has one author": the
files whose entire subject is that a fact belongs to a field rather than to the
process. Each of them opened with a module-scope constant like `P = R.BATUMI_ASR`
that resolves against the configured theatre AT IMPORT.

Nobody noticed for a month, because nobody ran the suite on the second map. The
suite that is run is the suite that is true.

TWO TIERS, AND THE SPLIT IS THE POINT.

  COLLECT (default)   every test module IMPORTS under every published map. About
                      a second per map. This is the check that would have caught
                      the thing above, and it is cheap enough to live in
                      `tools/check.py`, which is where it now is.

  RUN (--run)         the whole suite, per map. The Caucasus run must be GREEN;
                      it is the map that flies today and a failure there is a
                      regression, full stop. Any OTHER map is judged against a
                      recorded baseline, exactly as the approach sweep is:

                          "The sweep exits non-zero on a REGRESSION against its
                           recorded baseline, not on the known-open bugs,
                           because a check that is always red is a check nobody
                           reads. Beat the baseline and move it in the same
                           commit."

WHY NEVADA IS NOT EXPECTED TO BE GREEN, and why that is not this tool going
soft. The failures left there are `src/` reading Caucasus literals -- most of
them one line each, all of them on #137's list, and all of them REAL: a
controller who says nothing at all to a pilot asking for his clearance, a
vectoring altitude read off another country's mountains, a mission builder that
will not import. Making them skip would hide four live defects to make a number
green. They fail, they are counted, and the count may only go down.

ONE PROCESS IS ONE MAP. `theatre.current()` is cached and so is everything
behind it, so a map cannot be changed inside a run and nothing should try. That
is why this is subprocesses rather than a parametrised fixture.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# THE BASELINE, per map, as of the commit that recorded it. `None` means "must
# be green" -- that is the map the sortie is flown on.
#
# `failed` is the number of failing TESTS. Beat it and move it in the same
# commit; that is the whole discipline, and it is the sweep's, not a new one.
BASELINE = {
    "caucasus": None,
    # 13 August. Every one of these is `src/` resolving a Caucasus name on a map
    # that does not publish it. Named in the report so nobody has to guess:
    #   * `controller.py` `_atis_phrase` falls back to `_R.ARRIVAL_FIELD`
    #   * `core/fixes.py` is a Caucasus module re-exported through `route.py`
    #   * `briefing.py` / `mission/build.py` bind Caucasus names at import
    #   * neither Nevada field has a surveyed MSA or MVA grid
    "nevada": 407,
}

_TAIL = re.compile(
    r"(?:(?P<failed>\d+) failed[, ]+)?"
    r"(?:(?P<passed>\d+) passed)"
    r"(?:[, ]+(?P<skipped>\d+) skipped)?")


def maps() -> list[str]:
    """Every map the configuration publishes. Adding a map is adding a file, so
    this globs rather than naming two."""
    got = sorted(p.stem for p in (ROOT / "config" / "theatres").glob("*.toml"))
    return got or ["caucasus"]


def _run(theatre: str, argv: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ,
           "MARSHALL_THEATRE": theatre,
           "MARSHALL_MISSION": "unit-test",
           "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, env=env)


def collect(theatre: str) -> tuple[bool, str]:
    """Does every module LOAD on this map. The cheap half, and the one that
    caught the eight."""
    r = _run(theatre, [PY, "-m", "pytest", "tests", "-q", "--collect-only",
                       "--continue-on-collection-errors"])
    bad = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("ERROR ")]
    if bad:
        return False, "\n".join(f"      {ln}" for ln in bad)
    n = re.search(r"(\d+) tests? collected", r.stdout or "")
    return True, f"      {n.group(1) if n else '?'} tests collected"


def run(theatre: str) -> tuple[int, int, int, str]:
    """The whole suite. Returns (failed, passed, skipped, the summary line)."""
    r = _run(theatre, [PY, "-m", "pytest", "tests", "-q", "-rs",
                       "--continue-on-collection-errors"])
    tail = [ln for ln in (r.stdout or "").splitlines() if " passed" in ln]
    line = tail[-1] if tail else (r.stdout or r.stderr or "").strip()[-200:]
    m = _TAIL.search(line)
    if not m:
        return -1, 0, 0, line
    return (int(m.group("failed") or 0), int(m.group("passed") or 0),
            int(m.group("skipped") or 0), line)


def skips(theatre: str) -> list[str]:
    """WHY each skip was skipped. CLAUDE.md: skipped is reported, never silent,
    and it names what is unguarded."""
    r = _run(theatre, [PY, "-m", "pytest", "tests", "-q", "-rs",
                       "--continue-on-collection-errors"])
    out, seen = [], set()
    for ln in (r.stdout or "").splitlines():
        if not ln.startswith("SKIPPED"):
            continue
        why = ln.partition(": ")[2].strip()
        if why and why not in seen:
            seen.add(why)
            out.append(why)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true",
                    help="run the suites, not just collect them")
    ap.add_argument("--map", action="append", default=None,
                    help="only this map (repeatable). Default: every published one")
    ap.add_argument("--why-skipped", action="store_true",
                    help="print the reason for every distinct skip, per map")
    args = ap.parse_args()

    wanted = args.map or maps()
    unknown = [m for m in wanted if m not in maps()]
    if unknown:
        print(f"!! no such map: {', '.join(unknown)}. Published: "
              f"{', '.join(maps())}")
        return 2

    bad: list[str] = []
    print(f"maps: {', '.join(wanted)}\n")

    for theatre in wanted:
        t0 = time.monotonic()
        print(f"── {theatre}: collect")
        ok, detail = collect(theatre)
        print(detail)
        print(f"   {'PASS' if ok else 'FAIL'}  ({time.monotonic() - t0:.0f}s)")
        if not ok:
            bad.append(f"{theatre}: modules that will not load")
        if not args.run:
            print()
            continue

        t0 = time.monotonic()
        print(f"── {theatre}: run")
        failed, _passed, skipped, line = run(theatre)
        print(f"      {line}")
        base = BASELINE.get(theatre, 0)
        if base is None:
            verdict = failed == 0
            print("      must be green -- this is the map that flies")
        else:
            verdict = failed <= base
            print(f"      baseline {base} failed; a regression is MORE than that")
            if failed < base:
                print(f"      *** {base - failed} better than the baseline. "
                      f"Move BASELINE['{theatre}'] to {failed} in this commit.")
        print(f"   {'PASS' if verdict else 'FAIL'}  ({time.monotonic() - t0:.0f}s)")
        if not verdict:
            bad.append(f"{theatre}: {failed} failed"
                       + ("" if base is None else f", baseline {base}"))
        if args.why_skipped and skipped:
            print(f"   {skipped} skipped, and each names what is unguarded:")
            for why in skips(theatre):
                print(f"      · {why}")
        print()

    print("=" * 62)
    for b in bad:
        print(f"  FAIL  {b}")
    if not bad:
        print("  PASS  every published map")
    print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
