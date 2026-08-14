"""Write the sim's own projection of a map's private points into its file.

    "Caucasus is a transverse Mercator and a flat-earth offset was 7.6 nm
     wrong at the target area."

So the projection is never computed here and never estimated. It is asked of
`coord.LOtoLL` over DCS-gRPC, once, and written down -- which is the difference
between a fix a controller can measure from on a bridge that has never reached
the sim and one that silently degrades to "no fix for that".

WHY THIS EXISTS AT ALL. `[[fix]]` rows carry `lat`/`lon` and have since the
catalogue moved into config; `[[sortie.point]]` rows did not, because they were
Python until 14 August and Python could not hold a projection either. They were
projected at every bridge start instead, best-effort, and vanished when the
server was down. #139 -- does a terminal area contain the approach it serves --
cannot be answered offline while any fix on the map is missing its position,
and #130 is blocked behind #139.

    uv run python tools/seed_fixes.py --dry-run     # see what it would write
    uv run python tools/seed_fixes.py               # write it
    uv run python tools/seed_fixes.py --theatre nevada

RE-RUNNABLE AND ADDITIVE. A point that already carries coordinates is left
alone and reported as such: this is a seeding step, not a refresh, and silently
rewriting a value somebody had checked by hand would be the more expensive
behaviour. `--force` re-asks for everything and says what moved.

TEXT, NOT A TOML ROUND TRIP. Writing the file back through a serialiser would
drop every comment in it, and the comments are most of what those files are for
-- the `source` lines are the citations that make the data reviewable. So this
inserts two lines after the `z` of each block that needs them and touches
nothing else.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

BLOCK = re.compile(r"^\[\[sortie\.point\]\]\s*$")
KEY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def blocks(lines: list[str]):
    """Every `[[sortie.point]]` as (start, end, {key: line index}).

    `end` is exclusive and stops at the next section header, so a block's keys
    are exactly its own -- the reason this is a parser rather than a regex over
    the whole file.
    """
    out = []
    i = 0
    while i < len(lines):
        if BLOCK.match(lines[i]):
            j = i + 1
            keys = {}
            while j < len(lines) and not lines[j].lstrip().startswith("["):
                m = KEY.match(lines[j])
                if m:
                    keys[m.group(1)] = j
                j += 1
            out.append((i, j, keys))
            i = j
        else:
            i += 1
    return out


def value_at(line: str):
    raw = line.split("=", 1)[1].strip()
    try:
        return float(raw)
    except ValueError:
        return raw.strip('"')


def ask_the_sim(want: dict) -> dict:
    """`{name: (x, z)}` -> `{name: [lat, lon]}`, through the sim's converter."""
    from marshall.feed.stubs import bind
    bind()
    from marshall.atc import agent_atc as A

    class _P:
        def __init__(self, x, z):
            self.x, self.z = x, z
    return A._eval_fix_positions({n: _P(x, z) for n, (x, z) in want.items()})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--theatre", default="caucasus")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="re-ask for points that already carry coordinates")
    args = ap.parse_args(argv)

    path = ROOT / "config" / "theatres" / f"{args.theatre}.toml"
    if not path.exists():
        print(f"no such theatre file: {path.relative_to(ROOT)}", file=sys.stderr)
        return 2
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    found = blocks(lines)
    if not found:
        print(f"{args.theatre}: no [[sortie.point]] rows -- nothing to seed")
        return 0

    want, have = {}, []
    for _, _, keys in found:
        if "name" not in keys or "x" not in keys or "z" not in keys:
            continue
        name = value_at(lines[keys["name"]])
        if ("lat" in keys and "lon" in keys) and not args.force:
            have.append(name)
            continue
        want[name] = (value_at(lines[keys["x"]]), value_at(lines[keys["z"]]))

    for n in have:
        print(f"  {n:12} already carries coordinates -- left alone")
    if not want:
        print(f"{args.theatre}: nothing to seed")
        return 0

    print(f"  asking the sim for {len(want)}: {', '.join(want)}")
    try:
        got = ask_the_sim(want)
    except Exception as exc:
        print(f"\nthe sim did not answer: {type(exc).__name__}: {exc}\n"
              f"  This needs DCS up with DCS-gRPC reachable. Nothing was "
              f"written.", file=sys.stderr)
        return 1

    missing = [n for n in want if n not in got]
    if missing:
        # NAMED, NOT SKIPPED. A partial answer written silently would leave the
        # file looking seeded, and the next reader would have no way to tell
        # which rows the sim never saw.
        print(f"\nthe sim answered for {len(got)} of {len(want)}; no position "
              f"for: {', '.join(missing)}", file=sys.stderr)

    # BOTTOM UP, so inserting lines cannot move a block this loop has not
    # reached yet. Editing a file by line index from the top is a bug that
    # only shows up when there is more than one edit to make.
    wrote = 0
    for _start, _end, keys in reversed(found):
        if "name" not in keys:
            continue
        name = value_at(lines[keys["name"]])
        if name not in got:
            continue
        la, lo = got[name]
        if "lat" in keys and "lon" in keys:
            was = (value_at(lines[keys["lat"]]), value_at(lines[keys["lon"]]))
            moved = abs(was[0] - la) > 1e-6 or abs(was[1] - lo) > 1e-6
            print(f"  {name:12} {la:.6f} {lo:.6f}"
                  + (f"   (was {was[0]:.6f} {was[1]:.6f})" if moved else "   unchanged"))
            lines[keys["lat"]] = f"lat = {la:.6f}\n"
            lines[keys["lon"]] = f"lon = {lo:.6f}\n"
        else:
            print(f"  {name:12} {la:.6f} {lo:.6f}")
            at = keys["z"] + 1
            lines[at:at] = [f"lat = {la:.6f}\n", f"lon = {lo:.6f}\n"]
        wrote += 1

    if args.dry_run:
        print(f"\n--dry-run: {wrote} block(s) would be written")
        return 0
    path.write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {wrote} block(s) into {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
