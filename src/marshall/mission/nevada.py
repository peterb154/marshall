"""The Nevada mission: hot F-16s at Nellis, IFR to Tonopah.

    "let's build a mission where hot f16 are in parking ... Let's load the
     database up for nellis and tonopah so that we can test flying between them"

A SEPARATE BUILDER, and deliberately. `mission/build.py` is the 362nd's 1944
sortie -- Morse beacon audio, an SCR-522 card, a squadron of warbirds, a
Caucasus terrain object at the top -- and threading a second theatre through it
would mean a flag in every function and a mission that is half one war and half
another. The two share what is genuinely shared (`channels_for`, `set_channels`,
`write_presets`) and nothing else.

WHAT IT PROVES, which is the point of building it at all: everything below is
`marshall.core.nevada` and pydcs. No geometry, no phraseology, no controller
logic is duplicated or special-cased for this map. If the ATC works here it
works because it was already field-parameterised, not because it was ported.

HOT IN PARKING, not cold and not on the runway. `StartType.Warm` is engines
running at a parking slot: the pilot can talk to Ground within seconds, which is
what makes the ladder testable without ten minutes of alignment first, and he is
still on the ramp so the ground half of the sortie is real.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dcs.mission import Mission, StartType
from dcs.mapping import Point
from dcs.planes import F_16C_50
from dcs.terrain import Nevada

from marshall import config
from marshall.core import nevada as N
from marshall.mission.build import channels_for, set_channels, write_presets

OUT = config.MISSION_OUT / "Nevada-Nellis-Tonopah.miz"

# The leg. Nellis to Tonopah Test Range is 124 nm north-west, which is a real
# IFR sortie rather than a circuit: a departure, an enroute segment on the TPH
# VORTAC, and an arrival that is somebody else's field.
CRUISE_FT = 24000
CRUISE_KT = 350


def build(*, hot: bool = True, each: int = 2, wind_from: int = 210,
          wind_kt: int = 8, weather: str = "clear") -> tuple[Mission, list]:
    m = Mission(terrain=Nevada())
    usa = m.country("USA")

    # WIND FROM 210, so 21L is the runway in use at Nellis and 15 at Tonopah --
    # both ILS-equipped ends. `runway_in_use` decides that from the wind rather
    # than being told, so this is the one number that chooses both procedures.
    m.weather.wind_at_ground.direction = wind_from
    m.weather.wind_at_ground.speed = wind_kt * 0.514444
    if weather == "hard":
        m.weather.clouds_base = int((N.NELLIS_FIELD.elevation_ft + 400) * 0.3048)
        m.weather.clouds_density = 9
        m.weather.clouds_thickness = 2000
        m.weather.visibility = 4000

    # SEATS AT BOTH ENDS, because a two-field sortie is only half testable from
    # one of them. The Kobuleti-to-Batumi run could only ever be flown outbound;
    # anybody wanting to test an arrival had to fly the whole leg first, and the
    # return trip -- Tonopah's ILS, Silverbow's ladder, a departure from a field
    # a mile and a half up -- was never reachable in under twenty minutes.
    #
    # Hot at both, so either direction starts on the radio rather than on a
    # checklist.
    slots: list[tuple[int, str, str]] = []
    for name, home, first in (("Viper", "Nellis", N.NELLIS_CLEARANCE),
                              ("Dagger", "Tonopah", N.TONOPAH_TOWER)):
        slots += _seats(m, usa, name, home, first, hot, each)
    return m, slots


def _seats(m, usa, name: str, home: str, first, hot: bool, each: int):
    """One flight of client slots, hot in parking at `home`."""
    slots: list[tuple[int, str, str]] = []
    grp = m.flight_group_from_airport(
        country=usa, name=name, aircraft_type=F_16C_50,
        airport=m.terrain.airports[home],
        start_type=StartType.Warm if hot else StartType.Cold,
        group_size=each)
    # THE FIRST RUNG OF HIS OWN LADDER. He is parked and has not called anybody,
    # so the radio comes up on the seat he actually needs first -- the same rule
    # as Kobuleti, and the reason a sortie does not open on the wrong frequency.
    # Tonopah staffs no
    # delivery position -- Silverbow Tower works clearances too, `also=
    # ("clearance", "delivery")` -- so the first rung there is Tower.
    grp.frequency = first.freq_mhz
    for i, unit in enumerate(grp.units, start=1):
        unit.name = f"{name} 1-{i}"
        unit.set_client()
        # THE FIELD HE IS PARKED AT travels with the slot. `write_presets`
        # writes a card per aerodrome now, because a role is only unique
        # within one and the first five seats in the theatre's table are the
        # other field's.
        slots.append((unit.id, F_16C_50.id, home))
    set_channels(grp, home=home)

    # THE FLIGHT PLAN IN THE JET. A route in the .miz IS the DTC load, so the
    # steerpoints come up already holding TPH and Tonopah -- the same fixes the
    # controller expects him over, rather than something he hand-enters and gets
    # wrong before engine start.
    alt_m = CRUISE_FT * 0.3048
    speed_ms = CRUISE_KT * 0.514444
    # THE ROUTE IS THE OTHER FIELD, whichever end he starts at. Both flights get
    # TPH in the middle because the VORTAC is on the leg either way.
    away = N.NELLIS_FIELD if home == "Tonopah" else N.TONOPAH_FIELD
    for fix in (N.TPH, away):
        grp.add_waypoint(Point(fix.x, fix.z, m.terrain), alt_m)
    for wp in grp.points:
        wp.speed = speed_ms
    for unit in grp.units:
        unit.speed = speed_ms
    return slots


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cold", action="store_true",
                    help="cold and dark instead of hot in parking")
    ap.add_argument("--hard", action="store_true",
                    help="overcast at minimums, for a real ILS")
    ap.add_argument("--each", type=int, default=2, help="client slots")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    m, slots = build(hot=not args.cold, each=args.each,
                     weather="hard" if args.hard else "clear")
    out = Path(args.out) if args.out else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out))
    write_presets(out, slots)

    print(f"\nbuilt -> {out}")
    seats = [u.name for c in m.coalition.values() for co in c.countries.values()
             for g in getattr(co, "plane_group", []) for u in g.units
             if "Client" in str(getattr(u, "skill", ""))]
    print(f"  {len(seats)} client seats, "
          f"{'HOT in parking' if not args.cold else 'cold and dark'}: "
          f"{', '.join(seats)}")
    for f in N.NEVADA_FIELDS:
        print(f"  {f.name}: elevation {f.elevation_ft:,} ft, variation "
              f"{f.variation():.0f}E, runway in use "
              f"{f.runway_in_use(m.weather.wind_at_ground.direction):02d}")
    print("\n  comms ladder:")
    for n, hz in channels_for(N.NELLIS_ILS):
        who = next((s.name for s in N.NEVADA_STATIONS
                    if abs(s.freq_mhz - hz) < 1e-6), "?")
        print(f"    ch {n}  {hz:8.3f}  {who}")
    print("\n  approaches:")
    for p in (N.NELLIS_ILS, N.TONOPAH_ILS):
        print(f"    {p.chart_name}: runway {p.runway}, course {p.final_crs:03d}M"
              f", minima {p.min_hat_ft} ft, MDA {p.mda_ft:,} ft")
    print("\n  vectoring minima, surveyed out of the sim:")
    for f in N.NEVADA_FIELDS:
        lo = min(c[3] for c in f.mva_cells)
        hi = max(c[3] for c in f.mva_cells)
        print(f"    {f.name}: {len(f.mva_cells)} cells, {lo:,}-{hi:,} ft, "
              f"grid convergence {f.grid_convergence_deg:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
