"""What can I actually hear on the Detrola from here?

The Detrola is a plain LF receiver, so every terrain NDB in range is audible and
easy to mistake for one of our own transmitters. This prints the real beacons
near a point with their idents rendered as Morse, so an ident heard in the
cockpit can be matched by eye instead of guessed at.

Doubles as the siting tool for the real mission: it shows which genuine beacons
a route can be built around.

Usage:
  uv run python nearby_beacons.py                     # around Kobuleti
  uv run python nearby_beacons.py --radius 80
  uv run python nearby_beacons.py --terrain Nevada --lo 150 --hi 600
"""

import argparse
import math
import re
from pathlib import Path

from marshall import config
DCS = config.DCS_INSTALL

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}

# Somewhere useful to measure from on each map.
ORIGINS = {
    "Caucasus": ("Kobuleti", -317962, 635633),
    "Nevada": ("Creech", -360000, -75000),
}


def morse(ident: str) -> str:
    return " ".join(MORSE.get(ch.upper(), "?") for ch in ident if ch.strip())


def parse(terrain: str):
    text = (DCS / "Mods/terrains" / terrain / "Beacons.lua").read_text(
        encoding="utf-8", errors="ignore")
    out = []
    for block in re.findall(r"\{(.*?)\}", text, re.S):
        freq = re.search(r"frequency\s*=\s*([\d.]+)", block)
        if not freq:
            continue
        pos = re.search(r"position\s*=\s*\{\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)",
                        block)
        callsign = re.search(r"callsign\s*=\s*'([^']*)'", block)
        btype = re.search(r"type\s*=\s*(\w+)", block)
        out.append(dict(
            khz=float(freq.group(1)) / 1000,
            x=float(pos.group(1)) if pos else None,
            z=float(pos.group(3)) if pos else None,
            ident=callsign.group(1) if callsign else "?",
            type=(btype.group(1) if btype else "?").replace("BEACON_TYPE_", ""),
        ))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terrain", default="Caucasus")
    ap.add_argument("--lo", type=float, default=150, help="kHz")
    ap.add_argument("--hi", type=float, default=550, help="kHz")
    ap.add_argument("--radius", type=float, default=60, help="nm")
    args = ap.parse_args()

    label, ox, oz = ORIGINS.get(args.terrain, ("origin", 0, 0))
    rows = []
    for b in parse(args.terrain):
        if not (args.lo <= b["khz"] <= args.hi):
            continue
        if b["x"] is None:
            continue
        nm = math.hypot(b["x"] - ox, b["z"] - oz) / 1852
        if nm > args.radius:
            continue
        rows.append((nm, b))
    rows.sort(key=lambda r: r[0])

    print(f"{args.terrain}: real LF beacons {args.lo:.0f}-{args.hi:.0f} kHz "
          f"within {args.radius:.0f} nm of {label}\n")
    print(f"{'nm':>6}  {'kHz':>6}  {'ident':<6} {'morse':<18} type")
    print("-" * 70)
    for nm, b in rows:
        print(f"{nm:6.1f}  {b['khz']:6.1f}  {b['ident']:<6} "
              f"{morse(b['ident']):<18} {b['type']}")
    if not rows:
        print("  (nothing in range -- widen --radius or the kHz window)")


if __name__ == "__main__":
    main()
