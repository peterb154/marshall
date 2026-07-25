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
from dcs.planes import P_47D_30, P_51D_30_NA
from dcs.task import CAP, OrbitAction
from dcs.terrain import Caucasus
from dcs.triggers import TriggerStart

from marshall.atc import callsign as C
from marshall.core import route as R
from marshall import config

HERE = Path(__file__).parent
SOUNDS = config.SOUNDS_DIR
OUT = config.MISSION_OUT / "362nd-Blind-Flying.miz"
MISSIONS = config.DCS_MISSIONS

FLIGHT_SIZE = 4
JUG_CRUISE_MPH = 265        # the Thunderbolt is heavy; 220 stalls it
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
    ai.frequency = R.APPROACH.freq_mhz        # in-band VHF; 251 UHF is rejected
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


def add_formation(m: Mission, country, size: int = R.FLIGHT_SIZE) -> None:
    """A late-activated AI four-ship, for testing formation handling.

    Named for the FLIGHT ("Pony 1"), because DCS names a group's units
    "<group>-<n>" -- so a group called "Pony 1" produces exactly the callsigns the
    controller expects: Pony 1-1 through Pony 1-4, lead first. Radar labels then
    correlate to spoken callsigns for free.

    The AI flies this as a real formation (wingmen on lead's wing, one cluster on
    the scope), which is what we want to exercise: the radar picture of a
    four-ship, and the controller working them as one entity. The AI will NOT
    actually split up and fly four individual approaches -- a DCS group is tasked
    as a whole and wingmen follow lead -- so the break-up is driven from the radio
    by synthetic pilots. That is the right split anyway: the thing under test is
    the controller, not the autopilot.
    """
    # The GROUP is named for the flight, so DCS's "<group>-<n>" unit naming
    # produces the member callsigns: "Pony 1" -> Pony 1-1 .. Pony 1-4.
    group_name = C.parse(R.FLIGHT_CALLSIGN).flight
    start = Point(R.INITIAL.x + 6000, R.INITIAL.z + 6000, m.terrain)
    alt_m, spd_ms = 6000 * 0.3048, 200 * 0.44704
    flight = m.flight_group(
        country=country, name=group_name,
        aircraft_type=P_51D_30_NA, airport=None, position=start,
        altitude=alt_m, speed=spd_ms, maintask=CAP,
        start_type=StartType.Runway, group_size=size)
    flight.frequency = R.APPROACH.freq_mhz
    flight.late_activation = True
    flight.points[0].tasks.append(
        OrbitAction(altitude=alt_m, speed=spd_ms,
                    pattern=OrbitAction.OrbitPattern.Circle))
    for p in flight.points:
        p.alt, p.speed = alt_m, spd_ms
    # pydcs names units "<group> Pilot #n" -- rename them to the member
    # callsigns so the tracks table reads the way the radio does. The DCS
    # CALLSIGN (Enfield11, ...) is deliberately left alone: radar labels are
    # supposed to disagree with what the pilot calls himself, and correlating
    # the two from a position report is the machinery under test.
    for n, u in enumerate(flight.units, start=1):
        u.alt, u.speed = alt_m, spd_ms
        u.name = f"{group_name}-{n}"


def build(weather: str = "light", traffic: bool = False,
          formation: bool = False) -> tuple[Mission, list[int]]:
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
    # The altimeter setting the controller will pass, so the number he says and
    # the number the sim is running are the same one.
    m.weather.qnh = int(round(R.QNH_MMHG))

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
    # Start on APPROACH, not on a beacon. The beacons are still transmitting
    # but nobody is listening on one -- a radio that boots onto a dead frequency
    # is indistinguishable from an ATC that is not answering.
    flight.frequency = R.APPROACH.freq_mhz
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
    set_channels(flight)

    # A hot-ramp P-51 at Batumi: a listening station. Sit in it to hear ATC on
    # the SRS radios (SCR-522 button A = Kobuleti Departure, 124.000) without
    # flying the approach. Engines running, parked -- StartType.Warm.
    listen = m.flight_group_from_airport(
        country=usa, name="Sockeye", aircraft_type=P_51D_30_NA,
        airport=m.terrain.airports["Batumi"], start_type=StartType.Warm)
    listen.frequency = R.APPROACH.freq_mhz        # start tuned to button B
    for unit in listen.units:
        unit.set_client()
    set_channels(listen)

    # A flight of Thunderbolts, airborne alongside the Mustangs. The whole point
    # of moving to a radar approach is that it needs nothing in the cockpit but
    # a radio -- the beacon letdown was locked to the P-51D-30 because the ARA-8
    # homing adapter exists on no other airframe. These are here to fly the
    # approach and prove that.
    # The Thunderbolt is a much heavier aeroplane than the Mustang, and spawning
    # it at the Mustang's cruise put it on the edge of the stall. Give it its own
    # number rather than sharing one that only suits the lighter airframe.
    jug_ms = JUG_CRUISE_MPH * 0.44704
    jugs = m.flight_group(
        country=usa, name="Hammer", aircraft_type=P_47D_30, airport=None,
        position=Point(R.KOBULETI.x - 4000, R.KOBULETI.z - 4000, m.terrain),
        altitude=alt_m, speed=jug_ms, maintask=CAP,
        start_type=StartType.Runway, group_size=2)
    jugs.frequency = R.APPROACH.freq_mhz
    # Both places, every time: pydcs defaults route waypoints to 25 m/s and the
    # unit's own spawn speed separately, and a Mustang -- or a Jug -- stalls off
    # the spawn if either is left alone.
    for p in jugs.points:
        p.alt, p.speed = alt_m, jug_ms
    for n, unit in enumerate(jugs.units, start=1):
        unit.alt, unit.speed = alt_m, jug_ms
        unit.name = f"Hammer 1-{n}"
        unit.set_client()
    set_channels(jugs)

    if traffic:
        add_traffic(m, usa)
    if formation:
        add_formation(m, usa)

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
    # Every CLIENT slot needs SCR-522 presets injected or its channels cannot
    # tune the controllers -- Mustangs, the listening station, and the Jugs.
    # (unit id, DCS type) for every CLIENT slot. The type matters: the Avionics
    # override is written under a per-aircraft path, so a Mustang's radio file
    # dropped into a Thunderbolt's folder is simply ignored -- silently.
    slots = [(u.id, P_51D_30_NA.id) for u in flight.units]
    slots += [(u.id, P_51D_30_NA.id) for u in listen.units]
    slots += [(u.id, P_47D_30.id) for u in jugs.units]
    return m, slots


# Aircraft whose VHF preset FILE we know how to write. The Avionics override is
# the belt; panel_radio below is the braces, and it is the one that works for
# every airframe.
# Both are four-channel WW2 VHF sets and DCS reads the same per-unit override
# path for each. The Jug was missing from this map, so it silently kept the
# stock 105/124/139/131 while the kneeboard said 119/120/131 -- and "silently"
# is the problem: nothing anywhere reported that a listed aircraft had been
# skipped.
PRESET_PATHS = {P_51D_30_NA.id: "VHF_RADIO", P_47D_30.id: "VHF_RADIO"}


def channels_for(profile=None) -> list[tuple[int, float]]:
    """The radio card: (button, frequency) for this approach's controllers.

    One function so the mission, the kneeboard and the tests cannot disagree
    about what is on button two -- a mismatch there is a pilot transmitting to
    nobody, and it has happened. Derived from the profile's own station list,
    so a different field simply produces a different card.
    """
    profile = profile or R.BATUMI_ASR
    stations = list(getattr(profile, "stations", None) or R.STATIONS)
    freqs = [s.freq_mhz for s in stations[:4]]
    while len(freqs) < 4:                       # pad the unused buttons
        freqs.append(freqs[-1] if freqs else 124.0)
    return list(enumerate(freqs, start=1))


def set_channels(group) -> None:
    """Write the controller frequencies into a group's radio presets.

    pydcs models the four-channel WW2 set natively as `panel_radio`, and both
    the Mustang and the Thunderbolt expose the same shape -- so this is the way
    to give ANY aeroplane the same card, rather than injecting an Avionics file
    per airframe and silently doing nothing for the ones not listed. That is
    what left the Jugs with the stock 105/124/139/131 presets while the
    kneeboard said 119/120/131.
    """
    for unit in group.units:
        unit.set_radio_preset()                 # start from the airframe default
        for ch, mhz in channels_for():
            try:
                unit.set_radio_channel_preset(1, ch, mhz)
            except (TypeError, KeyError):
                break                           # no configurable radio; leave it


def write_presets(miz: Path, slots: list[tuple[int, str]]) -> None:
    """SCR-522 channel presets. They can only be set on the ground, so without
    this the flight has no way to tune the controllers.

    The presets are the CONTROLLERS now, not beacons. Under a radar approach the
    pilot navigates by nothing, so a frequency is only ever somebody to talk to:
    Center, Approach, Tower."""
    presets = [s.freq_mhz for s in R.STATIONS]
    while len(presets) < 5:
        presets.append(presets[-1])
    body = ("settings=\n{\n\t[\"dials\"]=\n\t{\n\t\t[\"channel\"]=0,\n\t},\n"
            "\t[\"presets\"]=\n\t{\n"
            + "".join(f"\t\t[{i+1}]={int(f*1_000_000)},\n"
                      for i, f in enumerate(presets[:5]))
            + "\t},\n}\n")

    with zipfile.ZipFile(miz) as zf:
        blobs = {n: zf.read(n) for n in zf.namelist()}
    blobs.setdefault("theatre", b"Caucasus")     # pydcs omits it
    wrote, skipped = {}, {}
    for uid, kind in slots:
        radio = PRESET_PATHS.get(kind)
        if radio:
            blobs[f"Avionics/{kind}/{uid}/{radio}/SETTINGS.lua"] = body.encode("utf-8")
            wrote[kind] = wrote.get(kind, 0) + 1
        else:
            skipped[kind] = skipped.get(kind, 0) + 1
    for kind, n in wrote.items():
        print(f"  presets written for {n} x {kind}")
    for kind, n in skipped.items():
        print(f"  !! NO preset file for {n} x {kind} -- it will fly on the "
              f"airframe defaults")
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
    ap.add_argument("--formation", action="store_true",
                    help="add a late-activated AI four-ship 'Pony 1' for "
                         "formation testing (units Pony 1-1 .. Pony 1-4)")
    args = ap.parse_args()
    weather = "hard" if args.hard else "clear" if args.clear else "light"

    mission, ids = build(weather, traffic=args.traffic,
                        formation=args.formation)
    mission.save(str(OUT))
    write_presets(OUT, ids)
    deploy(OUT)

    wx = {"clear": "CAVOK (clear)",
          "light": "overcast, base 1500 ft above ceiling",
          "hard": "overcast at ceiling (minimums)"}[weather]
    P = R.BATUMI_ASR
    print(f"\n{FLIGHT_SIZE} x P-51D-30 + 2 x P-47D-30, airborne over "
          f"{R.KOBULETI.name} at {R.CRUISE_ALT_FT:,} ft")
    print(f"{P.kind.upper()} approach runway {P.runway}, final course "
          f"{P.final_crs:03d}M, MDA {P.mda_ft}")
    print(f"weather: {wx}, wind {R.WIND_FROM_DEG:.0f}/{R.WIND_MPH:.0f}\n")
    for i, s in enumerate(R.STATIONS):
        print(f"  ch {'ABCD'[i]}  {s.freq_mhz:7.3f}  {s.name}")
    print()
    for leg in R.solve_route():
        print(f"  {leg.frm.ident} -> {leg.to.ident}   hdg {leg.heading_mag:03.0f}M   "
              f"{leg.distance_nm:4.1f} nm   {leg.time_str}")
