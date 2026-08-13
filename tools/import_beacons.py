"""A map's navaids, out of the sim's own Beacons.lua and into a theatre file.

    "importing a map's naviads should be dead simple"

It is, and that is the point: a navaid is the one kind of fact here that needs
no interpretation at all. DCS ships `Beacons.lua` per terrain with an entry per
transmitter carrying its callsign, its frequency, its type and BOTH FRAMES of
its position -- `position` in DCS metres and `positionGeo` in lat/lon. Nothing
has to be projected, transcribed off a plate, or guessed.

    uv run python tools/import_beacons.py caucasus
    uv run python tools/import_beacons.py nevada --write

WHY THIS MATTERS MORE THAN IT LOOKS. A pilot can fly to exactly two kinds of
place -- a steerpoint in his cartridge, and a navaid he can TUNE -- so the
tunable set is half of everything a controller is allowed to name (see
`docs/CONFIG.md`). Getting it from the sim rather than by hand means a new map
costs a command rather than an afternoon, and it cannot drift from what the
aeroplane will actually receive.

WHAT IS NOT HERE, deliberately:

  * ILS. A localiser and a glideslope are two entries at two positions sharing
    one frequency, and turning that pair into an approach needs a course and a
    threshold -- interpretation, which belongs with the procedure and not in a
    mechanical import.
  * Approach fixes. They are GEOMETRY and need no name: a controller vectors
    against them and the pilot never tunes one. See `docs/CONFIG.md`.

THE 1944 BEACONS ARE NOT THIS. `BATUMI` on `OS` at 132.0 was invented for the
period scenario -- the real Batumi beacon is `LU` on 0.430 and its TACAN is
`BTM`. Fiction is allowed; passing it off as surveyed is not, which is what the
required `source` field exists to stop.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# The kinds a pilot can actually tune and fly to. An ILS pair is excluded here
# and handled with the procedure; a marker is not a place you navigate to.
TUNABLE = {
    "BEACON_TYPE_VOR": "vor",
    "BEACON_TYPE_VORTAC": "vortac",
    "BEACON_TYPE_TACAN": "tacan",
    "BEACON_TYPE_VOR_DME": "vor-dme",
    "BEACON_TYPE_NDB": "ndb",
    "BEACON_TYPE_HOMER": "ndb",
    "BEACON_TYPE_AIRPORT_HOMER": "ndb",
    "BEACON_TYPE_AIRPORT_HOMER_WITH_MARKER": "ndb",
    "BEACON_TYPE_ILS_FAR_HOMER": "ndb",
    "BEACON_TYPE_ILS_NEAR_HOMER": "ndb",
}

_BLOCK = re.compile(r"\{\s*display_name = _\('([^']+)'\);(.*?)\n\t\};", re.S)


def beacons(path: Path) -> list[dict]:
    """Every tunable transmitter on this map, as data."""
    out = []
    for name, body in _BLOCK.findall(path.read_text(errors="replace")):
        kind = re.search(r"type = (\w+)", body)
        if not kind or kind.group(1) not in TUNABLE:
            continue
        geo = re.search(r"positionGeo = \{ latitude = ([-0-9.]+), "
                        r"longitude = ([-0-9.]+)", body)
        pos = re.search(r"position = \{ ([-0-9.]+), ([-0-9.]+), ([-0-9.]+)", body)
        if not (geo and pos):
            # NO POSITION, NO ENTRY. A navaid with no place is a frequency a
            # controller could name and nobody could fly to.
            continue
        cs = re.search(r"callsign = '([^']*)'", body)
        fq = re.search(r"frequency = ([0-9.]+)", body)
        ch = re.search(r"channel = (\d+)", body)
        out.append({
            "field": name,
            "ident": cs.group(1) if cs else "",
            "kind": TUNABLE[kind.group(1)],
            "mhz": round(float(fq.group(1)) / 1e6, 3) if fq else 0.0,
            "channel": int(ch.group(1)) if ch else 0,
            "lat": float(geo.group(1)), "lon": float(geo.group(2)),
            "x": float(pos.group(1)), "z": float(pos.group(3)),
        })
    return out


def as_toml(rows: list[dict], terrain: str) -> str:
    """The `[[navaid]]` tables for a theatre file."""
    out = [
        "", "# --- navaids ----------------------------------------------------------------",
        "#",
        f"# Imported from `vendor/dcs/{terrain}-Beacons.lua` by",
        "# `tools/import_beacons.py`. The sim's own data, in the sim's own",
        "# frames -- nothing here was projected, transcribed or guessed, which is",
        "# why re-running the tool is the way to update it rather than editing",
        "# below.",
        "#",
        "# These are half of what a controller may NAME: a pilot flies his own",
        "# steerpoints and the navaids he can TUNE, and nothing else. See",
        "# docs/CONFIG.md.",
        "",
    ]
    for r in sorted(rows, key=lambda r: (r["field"], r["kind"], r["ident"])):
        out += ["[[navaid]]",
                f'field = "{r["field"]}"',
                f'ident = "{r["ident"]}"',
                f'kind = "{r["kind"]}"']
        if r["mhz"]:
            out.append(f"mhz = {r['mhz']}")
        if r["channel"]:
            out.append(f"channel = {r['channel']}")
        out += [f"lat = {r['lat']}", f"lon = {r['lon']}",
                f"x = {r['x']}", f"z = {r['z']}",
                f'source = "{terrain}-Beacons.lua, the sim\'s own table"', ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("theatre", help="caucasus, nevada, ...")
    ap.add_argument("--write", action="store_true",
                    help="append to config/theatres/<theatre>.toml")
    args = ap.parse_args(argv)

    src = ROOT / "vendor" / "dcs" / f"{args.theatre}-Beacons.lua"
    if not src.exists():
        print(f"!! no {src.name} vendored. See vendor/dcs/README.md",
              file=sys.stderr)
        return 2
    rows = beacons(src)
    print(f"{len(rows)} tunable navaids in {src.name}", file=sys.stderr)
    text = as_toml(rows, args.theatre)
    if not args.write:
        print(text)
        return 0
    out = ROOT / "config" / "theatres" / f"{args.theatre}.toml"
    out.write_text(out.read_text() + text)
    print(f"appended to {out.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
