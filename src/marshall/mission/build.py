"""Build the 362nd blind-flying mission from route.py.

Same data as the kneeboard, so a chart cannot disagree with the sim.

    uv run python build_mission.py            # light IMC, for the first test
    uv run python build_mission.py --hard     # low ceiling, real minimums

Hard-won constraints baked in here (see the project notes):
  * beacons are created from Lua, never from mission-editor trigger actions
  * every group frequency must sit inside the SCR-522's 100-156 MHz band
  * pydcs spawns aircraft at 25 m/s unless every waypoint speed is set
  * the deployed file is size-checked, because the Mission Editor will
    silently overwrite a deploy if it has the mission open
"""

import argparse
import shutil
import struct
import wave
import zipfile
from pathlib import Path

from dcs.action import DoScriptFile
from dcs.mission import Mission, StartType
from dcs.mapping import Point
from dcs.planes import P_51D_30_NA
from dcs.task import CAP, OrbitAction
from dcs.terrain import Caucasus
from dcs.triggers import TriggerStart

from marshall.core import route as R
from marshall import config

HERE = Path(__file__).parent
SOUNDS = config.SOUNDS_DIR
OUT = config.MISSION_OUT / "362nd-Blind-Flying.miz"
MISSIONS = config.DCS_MISSIONS

FLIGHT_SIZE = 4
RATE = 22050
TONE_HZ = 1020.0
DOT = 0.09

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
}


def make_ident_audio(ident: str, seconds: float = 10.0) -> Path:
    """Keyed ident over a carrier that never drops to silence.

    The carrier has to stay up or homing can break in the gaps, but the flight
    sits on this frequency for the whole sortie with ATC talking over it -- so
    the floor is quiet (25%) and only the ident is loud. Loud enough to identify,
    quiet enough to talk across.
    """
    config.ensure_dirs(); SOUNDS.mkdir(parents=True, exist_ok=True)
    path = SOUNDS / f"bcn_{ident.lower()}.wav"
    samples: list[int] = []
    phase = 0.0
    step = 2 * 3.141592653589793 * TONE_HZ / RATE

    def tone(dur: float, amp: float) -> None:
        nonlocal phase
        import math
        for _ in range(int(dur * RATE)):
            samples.append(int(32767 * amp * math.sin(phase)))
            phase += step

    pattern = " ".join(MORSE[c] for c in ident.upper())
    while len(samples) < seconds * RATE:
        for element in pattern:
            if element == " ":
                tone(DOT * 2, 0.25)
                continue
            tone(DOT * (3 if element == "-" else 1), 0.85)
            tone(DOT, 0.25)
        tone(DOT * 6, 0.25)          # gap between repeats
    samples = samples[: int(seconds * RATE)]

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return path


def add_traffic(m: Mission, country) -> None:
    """An AI Mustang circling a few miles off Batumi.

    Its only job is to be a live radar contact -- something the controller can
    actually see now that radar walks the air groups (tools/dcs.py), and, later,
    a second ship to sequence against. Opt-in: the clean training mission keeps an
    empty sky, so this is only added under --traffic.
    """
    bat = R.BATUMI
    alt_m = 3000 * 0.3048
    spd_ms = 180 * 0.44704
    start = Point(bat.x + 7000, bat.z + 4000, m.terrain)     # ~4-5 nm NE of field
    ai = m.flight_group(
        country=country, name="Traffic", aircraft_type=P_51D_30_NA,
        airport=None, position=start, altitude=alt_m, speed=spd_ms,
        maintask=CAP, start_type=StartType.Runway, group_size=1)
    ai.frequency = int(R.BATUMI.freq_mhz)                     # not 251 UHF (rejected)
    # Dormant until called in: the sky stays empty until group.Activate("Traffic")
    # over gRPC spawns them -- traffic on cue, not a fixture.
    ai.late_activation = True
    ai.points[0].tasks.append(
        OrbitAction(altitude=alt_m, speed=spd_ms,
                    pattern=OrbitAction.OrbitPattern.Circle))
    for p in ai.points:
        p.alt, p.speed = alt_m, spd_ms
    for u in ai.units:
        u.alt, u.speed = alt_m, spd_ms


def build(weather: str = "light", traffic: bool = False) -> tuple[Mission, list[int]]:
    m = Mission(terrain=Caucasus())
    m.set_sortie_text("362nd - Blind Flying")
    m.start_time = m.start_time.replace(hour=9, minute=0)

    # Weather modes:
    #   clear -- CAVOK. A first VMC look to fly the geometry and find where the
    #            beacon null and runway actually are, before trusting them blind.
    #   light -- overcast, base lifted 1500 ft above the briefed ceiling: IMC but
    #            a gentle break-out well above MDA.
    #   hard  -- overcast at the briefed ceiling itself: real minimums.
    # For light/hard the cloud base is the SAME ceiling the plate's MDA is derived
    # from, so the sim can never contradict the chart: level at MDA and you break
    # out just below the overcast with the runway there.
    P = R.BATUMI_APPROACH
    if weather == "clear":
        m.weather.clouds_density = 0            # no overcast
        m.weather.clouds_thickness = 0
        m.weather.visibility_distance = 80000
    else:
        ceiling_ft = P.ceiling_ft if weather == "hard" else P.ceiling_ft + 1500
        m.weather.clouds_base = int(ceiling_ft * 0.3048)   # ft -> m
        m.weather.clouds_thickness = 2000
        m.weather.clouds_density = 9
        m.weather.visibility_distance = 4000 if weather == "hard" else 8000
    for w in (m.weather.wind_at_ground, m.weather.wind_at_2000,
              m.weather.wind_at_8000):
        # Wind is what makes timed legs hard; it must match the briefed value
        # on the nav log or the whole plan is a lie.
        w.direction = int((R.WIND_FROM_DEG + 180) % 360)   # DCS stores "blowing to"
        w.speed = R.WIND_MPH * 0.44704

    usa = m.country("USA")

    # Airborne over the departure beacon, already at cruise. Getting four
    # Mustangs off a wet runway in formation is a different mission.
    start = Point(R.KOBULETI.x, R.KOBULETI.z, m.terrain)
    alt_m = R.CRUISE_ALT_FT * 0.3048
    flight = m.flight_group(
        country=usa, name="Pony", aircraft_type=P_51D_30_NA,
        airport=None, position=start, altitude=alt_m,
        speed=R.CRUISE_TAS_MPH * 0.44704, maintask=CAP,
        start_type=StartType.Runway, group_size=FLIGHT_SIZE)

    # 251 MHz (pydcs's default) is UHF and DCS rejects the mission outright.
    flight.frequency = int(R.KOBULETI.freq_mhz)
    for unit in flight.units:
        unit.set_client()

    for fix in R.FIXES[1:]:
        flight.add_waypoint(Point(fix.x, fix.z, m.terrain), alt_m)

    # Speed has to be set in BOTH places. pydcs leaves the route waypoints at
    # 25 m/s and each unit's own spawn speed at 27 m/s (61 mph) -- the Mustang
    # falls out of the sky before anyone has hands on the stick.
    cruise_ms = R.CRUISE_TAS_MPH * 0.44704
    for point in flight.points:
        point.alt = alt_m
        point.speed = cruise_ms
    for unit in flight.units:
        unit.speed = cruise_ms
        unit.alt = alt_m

    # A hot-ramp P-51 at Batumi: a listening station. Sit in it to hear ATC on
    # the SRS radios (SCR-522 button A = Kobuleti Departure, 124.000) without
    # flying the approach. Engines running, parked -- StartType.Warm.
    listen = m.flight_group_from_airport(
        country=usa, name="Sockeye", aircraft_type=P_51D_30_NA,
        airport=m.terrain.airports["Batumi"], start_type=StartType.Warm)
    listen.frequency = int(R.KOBULETI.freq_mhz)   # start tuned to button A
    for unit in listen.units:
        unit.set_client()

    if traffic:
        add_traffic(m, usa)

    beacon_lua = []
    for fix in R.FIXES:
        make_ident_audio(fix.ident)
        m.map_resource.add_resource_file(
            str(SOUNDS / f"bcn_{fix.ident.lower()}.wav"))
        beacon_lua.append(
            f'  {{name="{fix.name}", ident="{fix.ident}", '
            f'freq={fix.freq_mhz:.3f}, x={fix.x:.0f}, z={fix.z:.0f}, '
            f'file="bcn_{fix.ident.lower()}.wav", power=1000}},')

    # One generated file: beacon table then script. A DoScript carrying Lua as
    # dictionary text fails at run time -- getValueDictByKey returns the key
    # name, which DCS then tries to compile.
    generated = config.MISSION_OUT / "_generated_beacons.lua"
    generated.write_text(
        "-- GENERATED by build_mission.py -- edit beacons.lua / ai_control.lua instead.\n"
        "BEACONS = {\n" + "\n".join(beacon_lua) + "\n}\n\n"
        + (HERE / "beacons.lua").read_text(encoding="utf-8")
        + "\n\n" + (HERE / "ai_control.lua").read_text(encoding="utf-8"),
        encoding="utf-8")

    boot = TriggerStart(comment="362nd beacons and reporting")
    boot.add_action(DoScriptFile(
        m.map_resource.add_resource_file(str(generated))))
    m.triggerrules.triggers.append(boot)

    # Every client unit needs SCR-522 presets injected (the Pony flight and the
    # Sockeye listening station both), or their channels can't tune the beacons.
    return m, [u.id for u in flight.units] + [u.id for u in listen.units]


def write_presets(miz: Path, unit_ids: list[int]) -> None:
    """SCR-522 channel presets. They can only be set on the ground, so without
    this the flight has no way to tune any beacon."""
    presets = [f.freq_mhz for f in R.FIXES]
    while len(presets) < 5:
        presets.append(R.FIXES[-1].freq_mhz)
    body = ("settings=\n{\n\t[\"dials\"]=\n\t{\n\t\t[\"channel\"]=0,\n\t},\n"
            "\t[\"presets\"]=\n\t{\n"
            + "".join(f"\t\t[{i+1}]={int(f*1_000_000)},\n"
                      for i, f in enumerate(presets[:5]))
            + "\t},\n}\n")

    with zipfile.ZipFile(miz) as zf:
        blobs = {n: zf.read(n) for n in zf.namelist()}
    blobs.setdefault("theatre", b"Caucasus")     # pydcs omits it
    for uid in unit_ids:
        blobs[f"Avionics/P-51D-30-NA/{uid}/VHF_RADIO/SETTINGS.lua"] = \
            body.encode("utf-8")
    with zipfile.ZipFile(miz, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, data in blobs.items():
            zf.writestr(n, data)


def deploy(miz: Path) -> None:
    dest = MISSIONS / miz.name
    # When DCS_MISSIONS is unset it defaults to the build dir -- the same place
    # the .miz was just written -- so there is nothing to copy. Guard against
    # unlinking the source and destroying it.
    if dest.resolve() == miz.resolve():
        print(f"  built -> {miz} ({miz.stat().st_size} B); DCS_MISSIONS unset, "
              f"not deployed")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    shutil.copy2(miz, dest)
    if dest.stat().st_size != miz.stat().st_size:
        raise SystemExit("DEPLOY FAILED - close the Mission Editor and rebuild")
    print(f"  deployed -> {dest} ({dest.stat().st_size} B, verified)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--hard", action="store_true",
                   help="overcast at the briefed ceiling -- real minimums")
    g.add_argument("--clear", action="store_true",
                   help="CAVOK -- clear skies for a first VMC look")
    ap.add_argument("--traffic", action="store_true",
                    help="add a late-activated AI contact off Batumi (call in "
                         "with group.Activate('Traffic') over gRPC)")
    args = ap.parse_args()
    weather = "hard" if args.hard else "clear" if args.clear else "light"

    mission, ids = build(weather, traffic=args.traffic)
    mission.save(str(OUT))
    write_presets(OUT, ids)
    deploy(OUT)

    wx = {"clear": "CAVOK (clear)",
          "light": "overcast, base 1500 ft above ceiling",
          "hard": "overcast at ceiling (minimums)"}[weather]
    print(f"\n{FLIGHT_SIZE} x P-51D-30, airborne over {R.KOBULETI.name} "
          f"at {R.CRUISE_ALT_FT:,} ft")
    print(f"MDA {R.BATUMI_APPROACH.mda_ft}, weather: {wx}"
          f", wind {R.WIND_FROM_DEG:.0f}/{R.WIND_MPH:.0f}\n")
    for i, f in enumerate(R.FIXES):
        print(f"  ch {'ABCD'[i]}  {f.freq_mhz:7.3f}  {f.ident:3} {f.name:9} "
              f"{f.sector}")
    print()
    for leg in R.solve_route():
        print(f"  {leg.frm.ident} -> {leg.to.ident}   hdg {leg.heading_mag:03.0f}M   "
              f"{leg.distance_nm:4.1f} nm   {leg.time_str}")
