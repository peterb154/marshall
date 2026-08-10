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
from dcs.forcedoptions import ForcedOptions
from dcs.mission import Mission, StartType
from dcs.mapping import Point
from dcs.planes import F_16C_50, MosquitoFBMkVI, P_47D_30, P_51D_30_NA, SpitfireLFMkIX  # noqa: F401
from dcs.planes import PlaneType
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
JUG_CRUISE_MPH = 265

# The allied line-up: everything a squadron mate might want to fly, four each.
# Cruise speeds are per airframe because they are not interchangeable -- the
# Mustang's number spawned a Thunderbolt on the edge of the stall, and the
# Mosquito is heavier again.
class F4U_1D(PlaneType):
    """The Corsair, which this pydcs does not know about.

    The module is newer than the library, so the type simply is not in
    dcs.planes and the mission builder cannot name it. Declaring it here is the
    smaller of the two fixes -- upgrading pydcs mid-evening to gain one airframe
    risks the builder that four other aeroplanes depend on, and DCS only needs
    the id to match. The dimensions and fuel are the aeroplane's; everything
    else follows the Mustang, which is the closest thing pydcs does know.

    Same four-channel VHF card as the rest, because the comms ladder is the
    whole point and an aircraft that cannot tune the controllers is a seat
    nobody can use.
    """

    id = "F4U-1D"
    flyable = True
    height = 4.50
    width = 12.50
    length = 10.26
    fuel_max = 923
    max_speed = 717.0
    category = "Air"
    task_default = P_51D_30_NA.task_default
    tasks = P_51D_30_NA.tasks
    radio_frequency = R.TOWER.freq_mhz
    panel_radio = P_51D_30_NA.panel_radio


# The allied line-up, and how many of each sit on the ramp.
#
# Batumi has TEN parking slots and that is the whole constraint. Three of each
# airframe wants twelve and does not fit; a mission that fails to build is
# worse than one with a slot fewer. So the tens are spent rather than left
# over: three of the two aeroplanes most likely to be flown, two of the others.
# Change the numbers freely -- the arithmetic is ten, however it is divided.
#
# Air starts are not in this list because they need no parking, which is why
# the rehearsal pair below costs nothing.
# Names come from route.py so the ramp and the transcriber's vocabulary cannot
# drift apart -- see SQUADRON_CALLSIGNS.
_PONY, _HAMMER, _SPIT, _WHISTLER = R.SQUADRON_CALLSIGNS
SQUADRON = [
    (_PONY, P_51D_30_NA, 265, 3),         # Mustang
    (_HAMMER, P_47D_30, 265, 3),          # Thunderbolt
    (_SPIT, SpitfireLFMkIX, 250, 2),      # Spitfire LF Mk IX
    (_WHISTLER, F4U_1D, 260, 2),          # Corsair (the Mosquito's two slots)
]        # the Thunderbolt is heavy; 220 stalls it
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


def add_testbed(m, usa) -> None:
    """An air-start F-16, for measuring the controller rather than flying the war.

    Deliberately anachronistic and deliberately behind a flag: a 1944 Caucasus
    mission has no business containing a Viper, and this one does not unless
    somebody asks for it.

    It exists because of what a P-51 cannot tell us. Asked which side of the
    final approach course he was on, Hoover could only answer by looking out of
    the window -- and the instruments that might have helped were worse than no
    help at all. On the runway, his wet compass read 139 where the F10 map said
    123 magnetic, and the DG beside it had drifted seven degrees the other way.

        "I steer by the DG. The mag compass is not reliable in turns."

    Which is correct airmanship and is also the whole problem: a directional
    gyro drifts, so the error between the heading a controller SAYS and the
    heading an aeroplane FLIES is not a constant to be calibrated out -- it
    wanders with time since the pilot last reset it against the compass.

    An F-16's HSI is slaved and does not drift. Flying the same approach in one
    turns "which side am I on" from a judgement into an instrument reading, and
    that is the only way to tell a real error in our geometry from a gyro that
    needed resetting. See #35 and card row A8.

    Air start over the same fix as the rehearsal flight, on Approach's
    frequency, so it can be taken straight to the part under test.
    """
    start = Point(R.AIR_START.x, R.AIR_START.z, m.terrain)
    alt_m = R.CRUISE_ALT_FT * 0.3048
    # ITS OWN SPEED, because the squadron's is a Mustang's.
    #
    # The air start inherited R.CRUISE_TAS_MPH -- 220 mph, about 190 knots --
    # which is a comfortable cruise in a P-51 and below an F-16's clean stall
    # with fuel aboard. It spawned and fell out of the sky.
    #
    # 300 knots: a normal jet holding speed, well clear of the stall at this
    # weight, and slow enough to be useful for approach work without having to
    # bleed off half of it first.
    jet_kt = 300.0
    jet = m.flight_group(
        country=usa, name="Testbed", aircraft_type=F_16C_50,
        airport=None, position=start, altitude=alt_m,
        speed=jet_kt * 0.514444, maintask=CAP,
        start_type=StartType.Runway, group_size=1)
    jet.frequency = R.APPROACH.freq_mhz
    for n, unit in enumerate(jet.units, start=1):
        unit.name = f"Testbed 1-{n}"
        unit.set_client()
        # The UNIT's own spawn speed, which is a different field from the route
        # waypoints and defaults to about 83 knots. Both have to be set: the
        # waypoints decide what he flies TO, this decides what he is doing the
        # instant he appears, and 83 knots is below an F-16's stall. This is the
        # third place the same trap has bitten in this file.
        unit.speed = jet_kt * 0.514444
    set_channels(jet)
    for fix in R.FIXES[1:]:
        jet.add_waypoint(Point(fix.x, fix.z, m.terrain), alt_m)

    # SPEED ON EVERY WAYPOINT, AND AFTER THEY ALL EXIST.
    #
    # Setting it before `add_waypoint` covers only the spawn point; pydcs gives
    # each new waypoint its own default of about 83 knots, which an F-16 cannot
    # fly. The jet spawned at 300 and then obediently slowed towards a speed it
    # stalls at -- so the first fix looked right in the file and still fell out
    # of the sky. The same trap is documented on the Mustang flight below and I
    # walked into it anyway, one function further up.
    for wp in jet.points:
        wp.speed = jet_kt * 0.514444


def add_session_slots(m, usa, air_alt_ft: dict | None = None,
                      each: int = 2) -> list[tuple[int, str]]:
    """Eight client slots for a two-pilot session: half on the ramp, half airborne.

    RETURNS ITS OWN (unit id, type) SLOTS, and that return value is not
    decoration. `write_presets` injects the SCR-522 channel file under a path
    keyed on the unit id, and it was being handed the list built by `build` --
    which names the STANDING flight, the one `--session` deletes a few lines
    later. So a session mission wrote radio presets for four Mustangs and two
    Thunderbolts that were no longer in the file, and wrote none at all for the
    eight aeroplanes somebody was about to fly.

    It did not bite because the F-16 takes its presets from the mission table
    instead, and the F-16 is what has been flown. A session Mustang has been
    mute the whole time and nobody has sat in one to find out.

        "two F-16's on the ground and 2 P-51s on the ground, two F-16s in the
         air, 2 P-51s in the air"

    The two halves test different things and both are needed in one mission,
    because swapping missions to change one costs the session its continuity.

    ON THE RAMP exercises the part that has never been flown properly: clearance
    delivery, taxi, the departure handoff, and -- since 28 July -- the sim's
    `takeoff` event moving a pilot off Tower. Every one of those was written
    against an aeroplane that began in the air and therefore skipped all of it.

    AIRBORNE is the approach itself, which is what most of this system is, and
    starting there costs nobody fifteen minutes of taxiing to reach the bit
    under test.

    TWO TYPES because they fail differently and the difference is the point: an
    F-16 has a slaved HSI and flies the pattern at three hundred knots; a P-51
    has a drifting gyro and flies it at a hundred and fifty. A procedure that
    works for one and not the other is not a working procedure, and until now
    the only way to compare them was to fly two sorties an hour apart.

    Callsigns are deliberately distinct per aeroplane -- Viper and Pony, one
    and two -- so that two humans on one frequency are never ambiguous to a
    controller keyed on what it hears (#40).
    """
    # -- on the ramp -------------------------------------------------------
    #
    # THE JET STARTS HOT, the warbird cold, and that is the pilot's call:
    #
    #     "F16 on ground should be hot started"
    #
    # A cold F-16 is a ten minute checklist before the radio is even alive, and
    # the thing under test here is clearance delivery and the departure
    # handoff, not the INS alignment. A Mustang cold is a couple of minutes and
    # is worth keeping -- somebody has to exercise the ramp from properly cold.
    # THEY NO LONGER SIT AT THE SAME AERODROME, and that is the whole point of
    # the new test bed:
    #
    #     "Let's move our parked f16s to kobeleti. Let's create a flight plan to
    #      fly from kob to batumi."
    #
    # A sortie that starts and ends at the same field never exercises a handoff
    # between two facilities, an en-route controller, or the half of the ladder
    # that belongs to the arrival. Departing Kobuleti and recovering into Batumi
    # walks every rung: clearance, ground, departure, Center, approach, tower.
    #
    # The Mustang stays at Batumi. He has four buttons and cannot carry a
    # two-field ladder (see `_short_card`), and he is pulled from session
    # missions anyway -- so parking him where his own controllers are is the
    # honest arrangement rather than giving him a card he cannot use.
    mine: list[tuple[int, str]] = []
    for name, kind, how, home in (
            ("Viper", F_16C_50, StartType.Warm, "Kobuleti"),
            ("Pony", P_51D_30_NA, StartType.Cold, "Batumi")):
        grp = m.flight_group_from_airport(
            country=usa, name=name, aircraft_type=kind,
            airport=m.terrain.airports[home],
            start_type=how, group_size=each)
        # THE FIRST RUNG OF HIS OWN LADDER, not Tower.
        #
        # He is parked and has not called anybody yet, so the frequency his
        # radio comes up on should be the one he actually needs first -- the
        # clearance seat at the field he is standing on. Coming up on Tower
        # meant the very first call of the sortie was on the wrong frequency,
        # which is a poor way to start testing a comms ladder.
        first = (R.BATUMI_ASR.station_for("clearance", field=home)
                 or R.BATUMI_ASR.station_for("ground", field=home))
        grp.frequency = first.freq_mhz
        for n, unit in enumerate(grp.units, start=1):
            unit.name = f"{name} 1-{n}"
            unit.set_client()
            mine.append((unit.id, kind.id))
        set_channels(grp, home=home)
        # THE FLIGHT PLAN IN THE AEROPLANE, not only on the kneeboard.
        #
        #     "Don't forget to add the flight plan waypoints to f16 dtc."
        #
        # A route in the .miz IS the DTC load: the jet reads these into its
        # steerpoints, so the pilot flies the same fixes the nav log times and
        # the controller expects him over. Printed on paper alone, the plan is
        # something he has to hand-enter before engine start and get wrong.
        #
        # `R.FIXES[1:]` skips the KOBULETI fix itself -- it sits a few hundred
        # metres off the field he is parked on, and a steerpoint there is a
        # waypoint you have already passed on the takeoff roll. Waypoint zero is
        # the ramp; the plan proper is INITIAL then BATUMI, which is exactly the
        # two legs `solve_route` times.
        if home == R.DEPARTURE_FIELD:
            cruise_m = R.CRUISE_ALT_FT * 0.3048
            for fix in R.FIXES[1:]:
                grp.add_waypoint(Point(fix.x, fix.z, m.terrain), cruise_m)

    # -- airborne ----------------------------------------------------------
    #
    # Separated in altitude as well as type. Two flights spawning at one point
    # and one height is a mid-air before anybody has said a word, and it is the
    # sort of thing that reads fine in a diff.
    air = air_alt_ft or {}
    for name, kind, kt, alt_ft in (
            ("Viper", F_16C_50, 300.0, air.get("Viper", R.CRUISE_ALT_FT + 3000)),
            ("Pony", P_51D_30_NA, R.CRUISE_TAS_MPH * 0.868,
             air.get("Pony", R.CRUISE_ALT_FT))):
        speed_ms = kt * 0.514444
        alt_m = alt_ft * 0.3048
        start = Point(R.AIR_START.x, R.AIR_START.z, m.terrain)
        grp = m.flight_group(
            country=usa, name=f"{name} Air", aircraft_type=kind, airport=None,
            position=start, altitude=alt_m, speed=speed_ms, maintask=CAP,
            start_type=StartType.Runway, group_size=each)
        grp.frequency = R.APPROACH.freq_mhz
        for n, unit in enumerate(grp.units, start=1):
            unit.name = f"{name} 2-{n}"
            unit.set_client()
            # THE UNIT'S OWN SPAWN SPEED, which is a different field from the
            # route waypoints and defaults to about 83 knots -- below an F-16's
            # stall. This trap has now bitten four times in this file.
            unit.speed = speed_ms
            mine.append((unit.id, kind.id))
        set_channels(grp)
        for fix in R.FIXES[1:]:
            grp.add_waypoint(Point(fix.x, fix.z, m.terrain), alt_m)
        for wp in grp.points:
            wp.speed = speed_ms
    return mine


def build(weather: str = "light", traffic: bool = False,
          formation: bool = False, testbed: bool = False,
          session: bool = False, ceiling_ft: int = 0,
          tops_ft: int = 0, visibility_m: int = 0,
          air_alt_ft: dict | None = None,
          session_each: int = 2) -> tuple[Mission, list[int]]:
    m = Mission(terrain=Caucasus())
    # The brief goes IN the mission as well as on the kneeboard. A pilot who
    # joins without OpenKneeboard, or who wants to read it while the aeroplane
    # is still cold, should not have to be told where it lives -- DCS shows
    # this on the slot screen before anyone spawns.
    m.set_sortie_text("Operation Samovar")
    m.set_description_text(_brief_text())
    m.set_description_bluetask_text(_brief_text())
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
        # AN EXPLICIT DECK, when one is asked for.
        #
        #     "the second mission should have 800 foot ceilings and 3000 foot
        #      tops"
        #
        # The derived modes tie the base to the plate's ceiling, which is right
        # when the point is to fly minimums and wrong when the point is to
        # choose the weather. A layer 800 to 3000 is a real instrument approach
        # -- solid from the platform, breaking out two hundred feet above MDA,
        # and thin enough to climb out of on a missed rather than staying in it
        # to the hold.
        base = ceiling_ft or (P.ceiling_ft if weather == "hard"
                              else P.ceiling_ft + 1500)
        thick = (tops_ft - base) if tops_ft > base else 2000
        m.weather.clouds_base = int(base * 0.3048)         # ft -> m
        m.weather.clouds_thickness = int(thick * 0.3048)
        m.weather.clouds_density = 9
        # VISIBILITY IS A SEPARATE DIAL FROM THE CEILING, and confusing them
        # cost a sortie. The deck was built at eight hundred feet and the pilot
        # broke out below two hundred -- because `hard` also drops visibility
        # to four kilometres, and under a dense overcast that keeps the runway
        # invisible long after the aeroplane is technically clear of cloud.
        #
        #     "raise the bases a little if you can. It was below 200 that time"
        #
        # The base was never the problem. Overridable now, so a low ceiling and
        # decent visibility underneath -- which is what a real instrument
        # approach usually is -- can actually be asked for.
        m.weather.visibility_distance = (
            visibility_m or (4000 if weather == "hard" else 8000))
    for w in (m.weather.wind_at_ground, m.weather.wind_at_2000,
              m.weather.wind_at_8000):
        # Wind is what makes timed legs hard; it must match the briefed value
        # on the nav log or the whole plan is a lie.
        w.direction = int((R.WIND_FROM_DEG + 180) % 360)   # DCS stores "blowing to"
        w.speed = R.WIND_MPH * 0.44704
    # The altimeter setting the controller will pass, so the number he says and
    # the number the sim is running are the same one.
    m.weather.qnh = int(round(R.QNH_MMHG))

    # ---- the front line ---------------------------------------------------
    #
    # Batumi is the only blue field on the map and everything else is red: a
    # foothold in hostile country. It is a scenario decision with teeth rather
    # than dressing -- there is nowhere to divert to, so a go-around means
    # coming back and doing it again, and a fuel state becomes a real problem
    # instead of a number. It also makes an overlord's tasking honest, since
    # anything outside the wire is a legitimate target.
    for airport in m.terrain.airports.values():
        airport.set_red()
    # TWO BLUE FIELDS NOW, and Kobuleti has to be one of them or the jets
    # parked there cannot spawn -- a red airport will not take a blue client,
    # and the failure is a slot that simply is not in the list when the pilot
    # goes looking for it.
    #
    # It costs some of what the single-field arrangement bought: with Batumi
    # alone there was nowhere to divert, so a go-around meant coming back and
    # doing it again and a fuel state was a real problem. There is a second
    # aerodrome now, forty miles up the coast. That is a fair trade for a route
    # with two ends, and the diversion is a procedure worth being able to fly.
    for name in ("Batumi", "Kobuleti"):
        m.terrain.airports[name].set_blue()

    # ---- what the map is allowed to tell you --------------------------------
    #
    # F10 shows only our own side. Left at the default it shows everybody, and
    # the whole scenario falls apart: the flak batteries and the armour at
    # Tsutsnvati are visible before anyone starts an engine, so the route round
    # the guns is pointless and the overlord's tasking is a formality. Finding
    # the target is meant to be part of the sortie.
    #
    # It also makes the ATC worth talking to. A pilot who can see every
    # aeroplane on the map does not need a controller to tell him where anyone
    # is -- take the map away and the radio becomes the only source of the
    # picture, which is the entire point of the project.
    # `options_view`, not `views`. Setting the wrong name is silent -- Python
    # takes the attribute happily, pydcs serialises nothing, and the mission
    # ships with the map wide open. Checked in the built .miz afterwards.
    m.forced_options.options_view = ForcedOptions.Views.OnlyAllies
    # Labels off as well: a name floating over an aeroplane at fifteen miles
    # is the same cheat by another route, and this is a WW2 mission where
    # seeing the other fellow first is the whole of air combat.
    m.forced_options.labels = ForcedOptions.Labels.None_

    usa = m.country("USA")

    # Airborne over the departure beacon, already at cruise. Getting four
    # Mustangs off a wet runway in formation is a different mission.
    # Airborne over the sea south-west of Batumi, not over Kobuleti -- that
    # field now has 88s, and spawning inside their envelope means the rehearsal
    # flight is under fire before anyone has hands on the throttle.
    start = Point(R.AIR_START.x, R.AIR_START.z, m.terrain)
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

    # (The old lone "Sockeye" hot-ramp listening slot lived here. The squadron
    # below replaces it -- every one of those is a client on the ramp, so there
    # is always somewhere to sit and listen, and Batumi's ten parking slots are
    # too few to spend one on a seat that does nothing else.)

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
        position=Point(R.AIR_START.x - 4000, R.AIR_START.z - 4000, m.terrain),
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

    # ---- the squadron ----------------------------------------------------
    #
    # Every allied airframe, cold and dark on the Batumi ramp. This is
    # what missions get flown with: a slot for whoever turns up, in whatever
    # they feel like flying, starting where a sortie actually starts. Cold
    # start rather than hot because the comms ladder now begins on the ground
    # -- clearance, taxi, departure -- and a hot ramp skips the half of it that
    # has never been exercised.
    #
    # Every one of them is a client. An empty slot costs nothing; a missing one
    # costs a squadron mate the sortie.
    client_slots: list[tuple[int, str]] = []
    # A SESSION MISSION REPLACES THE SQUADRON RATHER THAN JOINING IT. Seventeen
    # warbird slots fill every parking space at Batumi, and an F-16 needs a
    # bigger one than any that is left -- so the eight slots actually being
    # flown could not spawn. Two pilots do not need a squadron behind them, and
    # an empty ramp is also a quieter scope to debug against.
    for name, kind, _cruise, howmany in ([] if session else SQUADRON):
        sq = m.flight_group_from_airport(
            country=usa, name=name, aircraft_type=kind,
            airport=m.terrain.airports["Batumi"],
            start_type=StartType.Cold, group_size=howmany)
        sq.frequency = R.TOWER.freq_mhz        # cold on the ramp: ground/tower
        for n, unit in enumerate(sq.units, start=1):
            unit.name = f"{name} 1-{n}"
            unit.set_client()
            client_slots.append((unit.id, kind.id))
        set_channels(sq)

    if traffic:
        add_traffic(m, usa)
    if formation:
        add_formation(m, usa)
    if testbed:
        add_testbed(m, usa)
    if session:
        _air = air_alt_ft or {}
        # EXCLUSIVE, not additive. The standing sortie puts four Mustangs and
        # two Thunderbolts in the air and seventeen more on the ramp, and a
        # session mission asked for eight slots -- so the rest are not company,
        # they are clutter on the scope and four extra callsigns for a
        # controller to keep apart while two humans are trying to test it.
        #
        # Removed by name AFTER they are built rather than by threading a flag
        # through the whole builder: the standing flight carries a route, a
        # speed fix and a channel card that would all have to be duplicated.
        keep = [g for g in usa.plane_group
                if g.name not in ("Pony", "Hammer")]
        usa.plane_group = keep
        # AND THE PRESET LIST IS REPLACED, not appended to. Everything collected
        # up to here belongs to aeroplanes that were just deleted; keeping them
        # writes a radio file for a unit id that is not in the mission and, far
        # worse, leaves the eight that ARE with none.
        session_slots = add_session_slots(m, usa, _air, each=session_each)

    # NO BEACON TRANSMITTERS.
    #
    # They are left from the NDB letdown, which this field no longer flies, and
    # they were actively breaking the radio: the Kobuleti NDB transmits on
    # 124.000, which is Batumi Approach's frequency. A pilot on Approach heard
    # a beacon instead of a controller, and could not be heard by anybody. The
    # frequencies were assigned from the AIP months after the beacons were
    # placed and nobody put the two lists side by side.
    #
    # The FIXES stay in route.py as coordinates -- the radar picture is still
    # measured off BATUMI -- they simply do not transmit any more. Nothing in
    # the aeroplane can receive them and nothing in the approach needs them.
    beacon_lua = []
    for fix in R.FIXES:
        beacon_lua.append(
            f'  -- {fix.name} ({fix.ident}) not transmitted: radar approach')

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

    # Every CLIENT slot needs its four-channel VHF presets injected, or its
    # buttons cannot tune the controllers. (unit id, DCS type) for each: the
    # type matters, because the Avionics override is written under a
    # per-aircraft path and a Mustang's radio file dropped into a Thunderbolt's
    # folder is ignored -- silently, which is how a flight of Jugs once spent a
    # sortie unable to talk to anybody.
    #
    # Collected as the groups are built rather than listed here by hand, so
    # adding an airframe to the squadron cannot leave it mute.
    #
    # A SESSION MISSION IS THE SESSION SLOTS AND NOTHING ELSE, because the
    # standing flight and the Jugs have been deleted from the country by the
    # time this runs. Appending them anyway wrote SETTINGS.lua for unit ids that
    # are not in the file -- harmless -- and, in the same stroke, wrote none for
    # the eight aeroplanes somebody was about to fly, which is not.
    #
    # It has never been noticed because the F-16 takes its presets from the
    # mission table instead and the F-16 is what gets flown. A session Mustang
    # has been mute since session missions were added.
    if session:
        return m, list(session_slots)
    slots = list(client_slots)
    slots += [(u.id, P_51D_30_NA.id) for u in flight.units]
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


# (draw_plan lived here. The route is drawn on the LIVE map now by
# tools/draw.py, over DCS-gRPC, which needs no rebuild and no restart -- and
# baking a copy into the .miz as well just draws every route twice, the current
# one on top of whichever one was current when the mission was last built.
#
# Live is also the right shape for the job. Tonight the plan went from straight
# over Kutaisi to out-to-sea-and-round-the-top in three iterations, argued
# about while people sat on the ramp; each version baked in would have cost a
# rebuild, a deploy and a server restart.)

def _brief_text() -> str:
    """The mission brief as DCS shows it: plain text, no markup.

    The same words as the kneeboard page, because two briefs that drift apart
    are worse than one -- but rendered for a slot screen rather than a chart, so
    the tables become lines and the frequencies stay where a pilot can find them
    before he has a kneeboard open.
    """
    legs = R.solve_route(legs=R.SORTIE_LEGS)
    route = "\n".join(
        f"    {R.steerpoint(l.frm)}. {l.frm.name:<11s} -> "
        f"{R.steerpoint(l.to)}. {l.to.name:<11s}  hdg {l.heading_mag:03.0f}   "
        f"{l.distance_nm:5.1f} nm   {l.time_str}" for l in legs)
    total_nm = sum(l.distance_nm for l in legs)
    p = R.BATUMI_ASR
    chans = "\n".join(
        f"    {R.preset_label(i + 1)}   {s.freq_mhz:7.3f}   {s.name}"
        for i, s in enumerate(p.stations))
    return f"""OPERATION SAMOVAR
362nd Fighter Squadron - Batumi - Autumn 1945

SITUATION
The war has been over for months. Nobody appears to have circulated the
memorandum east of Kutaisi, where our former allies have developed a sudden
and enthusiastic interest in the refugee columns coming down out of the
mountains - on the grounds, we are told, of "escorting them to safety",
which is a novel use of armour.

Batumi is the only field on this coast still flying our colours. Every other
strip within reach has changed hands, changed flags, or changed its mind.
There is nowhere to divert to. If you cannot get in here, you come round and
get in here again.

Kobuleti, Senaki and Kutaisi are defended. They have 88s, and the route below
goes where it goes because of them -- the direct line to the target flies
straight over Kutaisi, which is a short conversation with a heavy battery.

The valley is the only low ground going east and all three fields sit in it, so
the margins are thinner than anyone would like. Georgia Center has you on radar
and knows where the guns are: if you want to be taken round them, ask.

MISSION
Depart Batumi, transit to Tsutsnvati - the town on the western shore of the
lake east of Kutaisi - and hold for tasking from Sentry. Targets are passed in
the air. Do not go hunting on your own; the refugees are down there too.

ROUTE
{route}
    TOTAL {total_nm:.1f} nm

LOADOUT
    500 lb bombs and/or rockets. You are being sent to discourage tanks.
    Guns alone will annoy a T-55 and little else.

RECOVERY
    Batumi runway {p.runway}, radar approach. The controller navigates; you fly
    the headings he gives you. Minimums {p.mda_ft:,} ft.
    Missed approach: straight ahead, at {p.missed_straight_ft:,} turn
    {p.missed_turn} heading {p.missed_hdg:03d}, climb {p.missed_climb_ft:,}.
    That takes you over water. Everything else takes you into a mountain.

RADIO - the comms ladder, in the order you press it
{chans}

    Altimeter {R.altimeter_spoken(R.qfe_inhg(p.field_elev_ft))} ({p.altimeter_datum}).
    Wind {int(R.WIND_FROM_DEG):03d} at {int(R.WIND_MPH)}.
    Bring the aeroplane back; there is a shortage."""


def channels_for(profile=None, limit: int | None = None,
                 home: str = "") -> list[tuple[int, float]]:
    """The radio card: (button, frequency) for this approach's controllers.

    One function so the mission, the kneeboard and the tests cannot disagree
    about what is on button two -- a mismatch there is a pilot transmitting to
    nobody, and it has happened. Derived from the profile's own station list,
    so a different field simply produces a different card.

    FOUR WAS AN AIRFRAME LIMIT WEARING A CARD'S CLOTHES. This used to take
    `stations[:4]` and pad to four, because every aeroplane that had ever been
    given a card was a warbird with a four-crystal SCR-522. The moment the
    route grew a second aerodrome the card silently dropped Batumi Approach,
    Tower and Ground -- the whole arrival half of the sortie -- and the pilot
    would have found out about it airborne, on a frequency nobody was on.

    So the CARD is as long as the ladder, and the truncating belongs to the
    radio being written (see `set_channels`), where the number of buttons is
    actually known. A P-51 still gets four; an F-16 gets all seven.
    """
    profile = profile or R.BATUMI_ASR
    stations = list(getattr(profile, "stations", None) or R.STATIONS)
    # THE LADDER FIRST AND IN ITS OWN ORDER, because which button a controller
    # is on is a fact about the sortie that `route.PRESET_LADDER` owns. Anyone
    # the profile carries who is not a rung -- Sentry, who is a commander rather
    # than a step in the ladder -- keeps a button after it rather than losing
    # one, so "every controller is reachable" stays true without disturbing the
    # seven the pilot was promised.
    ladder = [s for s in R.PRESET_LADDER if s in stations]
    # ...AND WHEN NONE OF THEM IS A RUNG, THE PROFILE'S OWN ORDER IS THE LADDER.
    #
    # `PRESET_LADDER` names Caucasus stations. A Nevada profile matches none of
    # them, so every Nellis controller fell into `rest` and the card came out in
    # whatever order the list happened to be built in -- which is the same
    # inaudibility failure as a dropped rung, arrived at from the other side.
    #
    # A theatre's station list is already written in the order a pilot presses
    # the buttons, so using it is not a fallback so much as the general case
    # that the Caucasus ladder is one instance of.
    rest = [s for s in stations if s not in ladder]
    ordered = (ladder + rest) if ladder else stations
    if limit is not None and len(ordered) > limit:
        ordered = _short_card(ordered, limit, home)
    freqs = [s.freq_mhz for s in ordered]
    while len(freqs) < min(4, limit or 4):      # pad the unused buttons
        freqs.append(freqs[-1] if freqs else 124.0)
    return list(enumerate(freqs, start=1))


def _short_card(stations, limit: int, home: str):
    """Which rungs survive when the radio has fewer buttons than the ladder.

    A SEVEN-RUNG LADDER DOES NOT FIT AN SCR-522, and the first four is the
    wrong four. Taking the head of the list gives a Batumi-based Mustang three
    Kobuleti controllers and Center -- nobody at the field he is standing on.

    So: his own aerodrome first, then the region controllers, who are reachable
    from anywhere and worth a button precisely because they are. Another field's
    controllers come last and fall off the end.

    THIS IS NOT ENOUGH FOR A TWO-FIELD SORTIE IN A FOUR-BUTTON AEROPLANE and it
    is worth saying so plainly. Flying Kobuleti to Batumi on an SCR-522 needs
    his ground, his departure, and the arrival field's approach and tower --
    four buttons chosen by the ROUTE rather than by the ramp he started on. That
    wants the sortie's endpoints, which this function is not given. It does not
    bite today because warbirds are pulled from session missions, and the day it
    does, this comment is the design note.
    """
    mine = [s for s in stations if getattr(s, "field", "") == home] if home else []
    region = [s for s in stations if not getattr(s, "field", "")]
    others = [s for s in stations if s not in mine and s not in region]
    # THE REGION CONTROLLER KEEPS A BUTTON, and it costs one of his field's.
    #
    # Kobuleti gained a Tower, which gave it four rungs of its own -- exactly a
    # period set's whole capacity -- and Center fell off the end. That is the
    # wrong four: he is reachable from ANYWHERE, which is precisely what makes
    # him worth one of only four buttons, and a warbird who loses him has
    # nobody at all once he leaves the circuit.
    #
    # So one seat is reserved for him and the field gives up its last rung.
    # Which rung that is follows the ladder order, so it is the one furthest
    # down the departure -- his own Departure controller, whose work Center
    # takes over anyway.
    if region and limit > 1:
        keep = [s for s in region if s.role == "center"][:1] or region[:1]
        mine = [s for s in mine if s not in keep][:limit - len(keep)]
        return (mine + keep + [s for s in others if s not in keep])[:limit]
    return (mine + region + others)[:limit]


def _band_of(mhz: float) -> str | None:
    """"vhf" or "uhf", by what the number IS rather than by what a radio happens
    to have on it today.

    The first attempt used the min and max of a radio's STOCK presets as its
    band, which is not the same thing at all: the F-16's VHF box ships with
    121-141 on its buttons and tunes 108-152, so Tower on 118 was quietly
    dropped for being outside a range that was never the radio's range.
    """
    if 108.0 <= mhz <= 156.0:
        return "vhf"
    if 225.0 <= mhz <= 400.0:
        return "uhf"
    return None


# A PRESET PANEL RATHER THAN A RECEIVER THAT HAPPENS TO TUNE. The Mustang's
# second "radio" reports a single channel; a real card needs a bank of buttons.
# Four is the smallest bank any airframe here has (the SCR-522), so anything
# below it is not a panel and must not be written to.
MIN_PRESET_PANEL = 4


def set_channels(group, home: str = "") -> None:
    """Write the controller frequencies into a group's radio presets.

    pydcs models the four-channel WW2 set natively as `panel_radio`, and both
    the Mustang and the Thunderbolt expose the same shape -- so this is the way
    to give ANY aeroplane the same card, rather than injecting an Avionics file
    per airframe and silently doing nothing for the ones not listed. That is
    what left the Jugs with the stock 105/124/139/131 presets while the
    kneeboard said 119/120/131.
    """
    # BOTH RADIOS, not just the first.
    #
    # A WW2 set has one four-button box and radio 1 is the whole story. A modern
    # aeroplane has two -- on the F-16, UHF on 1 and VHF on 2 -- and every
    # frequency this field uses (118, 124, 131, 139) is VHF. Writing only radio
    # 1 put the controllers on the UHF set, which cannot tune them, so buttons
    # 1-4 in the Viper did nothing at all while the same buttons in the Mustang
    # worked.
    #
    #     "set the f16 radio 1 2 3 4 same as a b c d in ww2"
    #
    # Setting both is right rather than clever: a preset on a radio that cannot
    # reach the frequency is inert, and a pilot who finds the controllers on
    # whichever box he happens to be using is the point.
    # ONLY ON A RADIO THAT CAN ACTUALLY TUNE IT.
    #
    # A preset a radio cannot reach is not a preset. The F-16 carries UHF on box
    # 1 (its stock presets run 250-305) and VHF on box 2 (121-141), and this
    # field's controllers are all VHF -- so writing the card to both put four
    # unreachable numbers on the UHF set and overwrote the stock UHF presets
    # that are actually useful for anything above the field.
    #
    # The band comes from pydcs's own defaults for that airframe rather than a
    # table here, so a new module needs no edit and a wrong guess is impossible.
    # The AIRFRAME's radio spec, looked up by the type string on the unit.
    # `type(unit)` is pydcs's Unit class and has no panel_radio at all, so that
    # silently produced an empty band table, every frequency passed the "can it
    # reach" test, and the whole card landed on the UHF box -- the exact fault
    # this check exists to prevent, introduced by the check itself.
    from dcs.planes import plane_map
    airframe = plane_map.get(getattr(group.units[0], "type", ""))
    bands = getattr(airframe, "panel_radio", None) or {}
    for unit in group.units:
        unit.set_radio_preset()                 # start from the airframe default
        for radio_id, spec in (bands.items() or [(1, None)]):
            stock = list((spec or {}).get("channels", {}).values())
            # A COMM BOX, not any receiver that happens to have a frequency.
            # The Mustang's second "radio" is a single-channel set; writing the
            # controller card to it retuned something that was never a preset
            # panel.
            #
            # THE TEST USED TO BE "CAN IT HOLD THE WHOLE CARD" and that was safe
            # only while the card was four long. The ladder made it eight, and
            # all-or-nothing then means a four-button SCR-522 gets NOTHING --
            # every warbird silently back on its stock presets while the
            # kneeboard prints the ladder, which is the exact fault this
            # function was written to end.
            #
            # So the bar is "is this a preset panel at all", and a box that
            # holds fewer buttons than the ladder gets as many rungs as it has
            # -- chosen for where the aeroplane is, not sliced off the front.
            if len(stock) < MIN_PRESET_PANEL:
                continue
            box = _band_of(sum(stock) / len(stock)) if stock else None
            for ch, mhz in channels_for(limit=len(stock), home=home):
                if box and _band_of(mhz) != box:
                    continue                    # wrong box for this frequency
                try:
                    unit.set_radio_channel_preset(radio_id, ch, mhz)
                except (TypeError, KeyError, IndexError):
                    break                       # this radio has no such preset


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
        print(f"  presets written for {n} x {kind}  (avionics file)")
    # TWO WAYS AN AEROPLANE GETS ITS PRESETS, and this warned about only one.
    #
    # A WW2 set stores them in an Avionics SETTINGS.lua, which is what the loop
    # above writes. Everything modern carries them in the GROUP's radio table,
    # which `set_channels` fills from pydcs's `panel_radio` -- so the F-16 was
    # correctly given the whole nine-rung ladder on its VHF box and this still
    # announced, in red, that it would "fly on the airframe defaults".
    #
    # Alarming and untrue, which is worse than silent: the honest reading is
    # that the jet has no comms card, and the answer to that is to dial eight
    # frequencies by hand or rebuild something that was already right.
    #
    # So it now asks the airframe. No panel_radio AND no avionics file is a real
    # gap; panel_radio is `set_channels`'s business and is not this function's
    # to report on.
    from dcs.planes import plane_map
    for kind, n in skipped.items():
        if getattr(plane_map.get(kind), "panel_radio", None):
            print(f"  presets written for {n} x {kind}  (group radio table)")
            continue
        print(f"  !! NO presets at all for {n} x {kind} -- no avionics file and "
              f"no radio panel; it will fly on the airframe defaults")
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
    ap.add_argument("--testbed", action="store_true",
                    help="add an air-start F-16 client 'Testbed 1-1' -- an HSI "
                         "that does not drift, for measuring the controller "
                         "rather than flying the war (#35, card A8)")
    ap.add_argument("--each", type=int, default=2,
                    help="client slots per type per position (default 2, so "
                         "--each 4 gives sixteen: four of each type on the "
                         "ramp and four of each airborne)")
    ap.add_argument("--session", action="store_true",
                    help="eight client slots for a two-pilot session: 2 F-16 "
                         "and 2 P-51 cold on the ramp, 2 of each airborne")
    ap.add_argument("--ceiling", type=int, default=0,
                    help="overcast base in feet (with --tops)")
    ap.add_argument("--tops", type=int, default=0,
                    help="cloud tops in feet, so the layer has a real thickness")
    ap.add_argument("--visibility", type=int, default=0,
                    help="metres below the deck; separate dial from the ceiling")
    ap.add_argument("--viper-alt", type=int, default=0,
                    help="air-start altitude for the F-16 slots, feet MSL")
    ap.add_argument("--pony-alt", type=int, default=0,
                    help="air-start altitude for the P-51 slots, feet MSL")
    ap.add_argument("--out", default="",
                    help="write the .miz here instead of the default name")
    ap.add_argument("--formation", action="store_true",
                    help="add a late-activated AI four-ship 'Pony 1' for "
                         "formation testing (units Pony 1-1 .. Pony 1-4)")
    args = ap.parse_args()
    weather = "hard" if args.hard else "clear" if args.clear else "light"

    mission, ids = build(weather, traffic=args.traffic,
                        formation=args.formation, testbed=args.testbed,
                        session=args.session, ceiling_ft=args.ceiling,
                        tops_ft=args.tops, visibility_m=args.visibility,
                        air_alt_ft={k: v for k, v in
                                    (("Viper", args.viper_alt),
                                     ("Pony", args.pony_alt)) if v},
                        session_each=args.each)
    out = Path(args.out) if args.out else OUT
    mission.save(str(out))
    write_presets(out, ids)
    deploy(out)

    wx = {"clear": "CAVOK (clear)",
          "light": "overcast, base 1500 ft above ceiling",
          "hard": "overcast at ceiling (minimums)"}[weather]
    P = R.BATUMI_ASR
    # WHAT WAS ACTUALLY BUILT, read off the mission, not off a sentence.
    #
    # This line was the fixed string "4 x P-51D-30 + 2 x P-47D-30, airborne over
    # REHEARSAL" no matter what was in the .miz. Under `--session` -- which
    # deletes the standing flight and puts F-16s on the Kobuleti ramp -- it
    # reported four Mustangs and two Thunderbolts airborne, and there were
    # neither: eight client slots, half of them Vipers, none of them a P-47.
    #
    # It cost an hour of hunting for missing F-16s that were in the file all
    # along, and it would have cost more than that if it had been believed on
    # the way to the server. A build report is the only thing standing between
    # a rebuild and a deploy, and one that describes the mission it USED to
    # build is worse than printing nothing.
    seats: dict[str, list[str]] = {}
    for c in mission.coalition.values():
        for country in c.countries.values():
            for g in getattr(country, "plane_group", []):
                for u in g.units:
                    if not getattr(u, "skill", None) or "Client" not in str(u.skill):
                        continue
                    seats.setdefault(u.unit_type.id, []).append(u.name)
    if seats:
        print()
        for kind in sorted(seats):
            who = sorted(seats[kind])
            print(f"  {len(who)} x {kind} client: {', '.join(who)}")
    else:
        print("\n  NO CLIENT SLOTS -- nobody can fly this mission")
    print(f"{P.kind.upper()} approach runway {P.runway}, final course "
          f"{P.final_crs:03d}M, MDA {P.mda_ft}")
    print(f"weather: {wx}, wind {R.WIND_FROM_DEG:.0f}/{R.WIND_MPH:.0f}\n")
    for i, s in enumerate(R.STATIONS):
        print(f"  ch {R.preset_label(i + 1)}  {s.freq_mhz:7.3f}  {s.name}")
    print()
    for leg in R.solve_route():
        print(f"  {leg.frm.ident} -> {leg.to.ident}   hdg {leg.heading_mag:03.0f}M   "
              f"{leg.distance_nm:4.1f} nm   {leg.time_str}")
