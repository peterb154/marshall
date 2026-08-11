"""Measure the ground around a field, so vectoring minima are surveyed not guessed.

A minimum vectoring altitude is the lowest a controller may assign, and it is
only worth anything if it matches the actual ground. Ours were four 90-degree
buckets holding the highest terrain within 25 nm, which is far too coarse to
vector with: north-east of Batumi that rule says 9,500 ft, and it says it four
miles from the runway where the ground is coastal plain a few hundred feet up.
Flown live, an aircraft repositioning four miles out was told to climb to 9,500
and then, one sector boundary later, to descend to 2,000 -- seven thousand feet
of climb for nothing. The same coarseness, applied off the departure end where
the buckets say 13,000, had already flown one aeroplane into the Caucasus.

So: ask the sim. DCS-gRPC's custom Eval runs Lua in the mission environment,
where `land.getHeight` is the terrain itself -- not a guess, not a chart, the
same heightmap the aircraft will hit. This walks a polar grid out from the
field and reports the highest ground in each (sector, range band) cell, which
is the shape a real MVA chart has: rings as well as spokes.

    DCS_GRPC_ADDR=host:50051 uv run python tools/survey_terrain.py

Paste the emitted table into route.py. It is data about a place and it does not
change, so it belongs in the source next to the field it describes.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


import grpc

from marshall import config as _config
from marshall.feed.stubs import bind as _bind

_bind()

from marshall.core import route as R

# WHERE THE SIM IS, from the one place that knows -- env, else
# `director/.env`, which is the file compose reads and no shell does.
# Rolling a local default here is how this tool ended up talking to
# localhost while the sim ran on another machine. See `dcs.grpc_addr`.
ADDR = _config.DCS_GRPC_ADDR
M_PER_NM = 1852.0
FT_PER_M = 3.28084

# Terrain clearance. 1,000 ft is the usual figure over high ground; it is what
# turns "the ground is 4,300 here" into "you may be assigned 5,300".
CLEARANCE_FT = 1000


def eval_lua(ch, lua: str) -> str:
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    return custom_pb2_grpc.CustomServiceStub(ch).Eval(
        # A WHOLE GRID IN ONE CALL, so the deadline is the grid's and not a
        # single sample's. Twelve sectors by four rings at half-mile steps is
        # tens of thousands of `land.getHeight` calls; sixty seconds was the
        # Caucasus's answer and Nevada is bigger and higher.
        custom_pb2.EvalRequest(lua=lua), timeout=600).json


def survey(ch, field, sectors: int, bands: list[float], step_nm: float) -> dict:
    """Highest ground in each (sector, range band) cell, in feet.

    One Eval for the whole grid: a round trip per sample would be thousands of
    them, and the sim is a shared resource. The Lua walks the grid and returns
    a flat list of maxima.
    """
    arc = 360.0 / sectors
    lua = f"""
    local x0, z0 = {field.x}, {field.z}
    local bands = {{{','.join(str(b) for b in bands)}}}
    local out = {{}}
    for s = 0, {sectors - 1} do
      for b = 1, #bands do
        local lo = (b == 1) and 0.5 or bands[b-1]
        local hi = bands[b]
        local peak = -1000
        local r = lo
        while r <= hi do
          local a = s * {arc}
          while a < (s + 1) * {arc} do
            local rad = math.rad(a)
            -- route.py stores x = north, z = east; the sim's land.getHeight
            -- takes (x, z) in exactly that order, so no swap here.
            local x = x0 + r * {M_PER_NM} * math.cos(rad)
            local z = z0 + r * {M_PER_NM} * math.sin(rad)
            local h = land.getHeight({{x = x, y = z}})
            if h > peak then peak = h end
            a = a + 1.0
          end
          r = r + {step_nm}
        end
        out[#out+1] = string.format("%d:%d:%d", s, b, math.floor(peak))
      end
    end
    return table.concat(out, ",")
    """
    return eval_lua(ch, lua)


def _known() -> list:
    """Every aerodrome the system holds, whichever map it is on."""
    from marshall.core import nevada as N
    return [*R.FIELDS, *N.NEVADA_FIELDS]


def _field_named(name: str):
    return next((f for f in _known()
                 if f.name.lower() == (name or "").strip().lower()), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sectors", type=int, default=12, help="30-degree spokes")
    ap.add_argument("--bands", default="5,10,15,25",
                    help="range rings in nm, comma separated")
    ap.add_argument("--step", type=float, default=0.5, help="sample step, nm")
    # WHICH FIELD, because this was written when there was one.
    #
    # `field = R.BATUMI` was hardcoded, so the one tool that turns terrain into
    # a vectoring minimum could only ever answer for the field it was written
    # at. That is fine while a theatre has one aerodrome and is exactly the
    # shape of every other bug this project has had since it grew a second.
    #
    # Resolved across every field the system knows, on either map, by name.
    ap.add_argument("--field", default="Batumi",
                    help="which aerodrome to survey (Batumi, Kobuleti, "
                         "Nellis, Tonopah)")
    args = ap.parse_args()

    field = _field_named(args.field)
    if field is None:
        print(f"no field called {args.field!r}. Known: "
              f"{', '.join(f.name for f in _known())}")
        return 1
    bands = [float(b) for b in args.bands.split(",")]
    arc = 360.0 / args.sectors
    print(f"surveying {field.name} — {args.sectors} sectors of {arc:.0f} deg, "
          f"rings at {bands} nm, {args.step} nm steps\n")

    with grpc.insecure_channel(ADDR) as ch:
        raw = survey(ch, field, args.sectors, bands, args.step)

    peaks: dict[tuple[int, int], int] = {}
    for cell in str(raw).strip('"').split(","):
        if not cell or ":" not in cell:
            continue
        s, b, h = cell.split(":")
        peaks[(int(s), int(b))] = int(h)
    if not peaks:
        print(f"no data back from the sim: {raw!r}")
        return 1

    print(f"{'sector':>12}  " + "  ".join(f"{b:>7.0f}nm" for b in bands))
    for s in range(args.sectors):
        lo, hi = s * arc, (s + 1) * arc
        cells = []
        for b in range(1, len(bands) + 1):
            m = peaks.get((s, b))
            cells.append(f"{m * FT_PER_M:7.0f}ft" if m is not None else "      -")
        print(f"  {lo:03.0f}-{hi:03.0f}  " + "  ".join(cells))

    print("\n# MVA: highest ground + clearance, rounded up to the next 500 ft.")
    print("# (sector_from, sector_to, range_to_nm, altitude_ft)")
    print("MVA_CELLS = [")
    for s in range(args.sectors):
        lo, hi = s * arc, (s + 1) * arc
        for b, ring in enumerate(bands, start=1):
            m = peaks.get((s, b))
            if m is None:
                continue
            ft = m * FT_PER_M + CLEARANCE_FT
            print(f"    ({lo:5.1f}, {hi:5.1f}, {ring:5.1f}, "
                  f"{int(math.ceil(ft / 500.0) * 500):6d}),")
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
