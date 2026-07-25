"""Generate the mission-specific 'plate' prompt block from route.py.

The agent's soul and rules are field-agnostic and hand-written — how a controller
talks, identifies, hooks, stays honest. The FACTS — this field's beacon, runway,
altitude ladder, headings, timing, wind, and the controller's capability /
handicaps — are data, and they already live in `route.py`. This turns that data
into the markdown block the bridge pushes to the director as the 'plate' prompt
part, so standing up a new field or dialing in a handicap is a route.py change,
not a prompt rewrite. It also keeps the plate and the actual mission/chart from
ever disagreeing, since all three read the one profile.
"""

from __future__ import annotations

from marshall.core import route as R

_PHON = {"A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
         "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliet",
         "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
         "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
         "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "Xray", "Y": "Yankee",
         "Z": "Zulu"}


def _phonetic(ident: str) -> str:
    return " ".join(_PHON.get(c.upper(), c) for c in ident)


def _inbound_hdg(profile: R.ApproachProfile) -> int:
    """The charted inbound course, falling back to the runway designation.

    final_crs wins. Deriving the course from the runway number instead ("12" ->
    120) is off by however much the runway's real centreline differs from its
    rounded name -- at Batumi that is 124 vs 120, so the agent was reading the
    plate four degrees off the nav log the pilot flies.
    """
    if profile.final_crs:
        return profile.final_crs
    try:
        return int(profile.runway) * 10
    except (ValueError, TypeError):
        return 0


def _mmss(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m} minutes {s} seconds"


def _channels(profile: R.ApproachProfile) -> list[str]:
    """Which controller sits on which frequency, and why it is not a choice.

    The aircraft has four radio presets and its homing adapter works only on the
    frequency the set is tuned to, so the pilot cannot listen to you on one
    channel while homing a beacon on another. Each phase's controller therefore
    lives on the beacon flown in that phase.
    """
    enr_name, enr_freq = profile.station(enroute=True)
    twr_name, twr_freq = profile.station()
    out = []
    if enr_freq and enr_freq != twr_freq:
        out.append(
            f"- **Channels.** Enroute he homes {profile.arrival_fix.name} and is "
            f"on **{enr_freq:.1f}** ({enr_name}); the letdown is flown homing "
            f"{profile.beacon.name}, so it belongs to {twr_name} on "
            f"**{twr_freq:.1f}**. Hand him over as he leaves "
            f"{profile.arrival_fix.name}. He physically cannot hear you on a "
            "channel he is not homing.")
    return out


def _formation(flight: str, size: int, profile: R.ApproachProfile) -> list[str]:
    """How to handle a formation. Deliberately says nothing about WHICH one.

    This block used to name the flight the mission expected -- callsign, size,
    every member -- which reads as "this is who is coming" and taught the
    controller to expect one aeroplane in particular. A pilot noticed the
    consequence immediately: Center greeted him already knowing where he was
    going. The plate describes the FIELD and its procedures; who turns up, in
    what, going where, is theirs to say and the controller's to ask.
    """
    ladder = ", ".join(f"{ft}" for ft in profile.stack_ft[:4])
    return [
        "- **A formation is ONE aircraft to you while it is together**: one "
        "clearance, one altitude, lead answers for all of them. Address it as "
        "a flight. A wingman who transmits is the flight talking — do not open "
        "a second conversation with him.",
        "- **Break a flight up before the approach**, into individually-"
        "sequenced singles. Ask first whether they can maintain visual "
        "separation: in visual conditions they may split inside ONE level, in "
        "trail; in cloud you separate them yourself, a level each, lead lowest "
        f"so he lands first (the ladder is {ladder}). Never assume — assuming "
        "they can see each other puts several aeroplanes on one level in cloud.",
        "- After the break-up they are ordinary singles on their own callsigns.",
    ]

def _setting(profile: R.ApproachProfile) -> str:
    """The altimeter setting this field passes, spoken.

    QFE or QNH is the field's convention and it changes the number. It also
    changes what every altitude on the plate MEANS -- height above the runway
    or altitude above the sea -- which is why the datum is said out loud rather
    than assumed.
    """
    if getattr(profile, "altimeter_datum", "QNH").upper() == "QFE":
        return R.altimeter_spoken(R.qfe_inhg(profile.field_elev_ft))
    return R.altimeter_spoken()


def _asr_plate(profile: R.ApproachProfile, flight: str, size: int) -> str:
    """The facts for a surveillance-radar approach.

    A different procedure needs a different briefing, not the letdown's with
    words changed: on an ASR the controller navigates, so what he must know is
    the course to put the pilot on, the altitudes, and where to stop -- there
    are no legs for the pilot to fly and nothing for him to home.
    """
    inbound = profile.final_crs
    rwy = profile.runway or "in use"
    stations = "; ".join(f"**{s.name} {s.freq_mhz:.1f}**" for s in profile.stations)
    return "\n".join([
        "# This mission's plate (the field-specific facts)",
        "",
        f"- This is a **surveillance radar approach** to runway **{rwy}** at "
        f"**{profile.beacon.name}**. **You** navigate; the pilot flies the "
        "headings you give him. He has no approach aid of his own.",
        f"- Controllers: {stations}.",
        f"- Final approach course **{inbound:03d}**. Vector him to intercept it "
        f"by **{profile.final_intercept_nm:.0f} miles** from the field.",
        f"- Vectoring altitude **{profile.platform_ft}** until established on "
        f"final; then down to **MDA {profile.mda_ft}** "
        f"({profile.mda_ft - profile.field_elev_ft} ft above the field).",
        f"- Missed approach point **{profile.map_nm:.1f} miles** from the field. "
        f"Missed approach: climbing **{profile.missed_turn}** turn to "
        f"**{profile.missed_ft}**, re-sequence.",
        "- **Call range every mile on final**, with his position relative to the "
        "course: \"six miles from the runway, on course\", \"drifting right of "
        "course, turn left heading one two zero\".",
        "- **There is no glidepath.** You give range and course; his descent is "
        "his own. Never invent a glidepath call.",
        f"- **Altimeter {_setting(profile)}** ({profile.altimeter_datum}) — pass "
        "it when you call radar contact, and to anyone who asks. Every height "
        "you read him is measured against this datum; a pilot who never gets it "
        "is holding a different one and neither of you knows by how much.",
        f"- Wind **{int(R.WIND_FROM_DEG):03d} at {int(R.WIND_MPH)}** mph. Do NOT "
        "pass it as a correction while vectoring — you are watching his ground "
        "track, so the drift is already inside the heading you give him. "
        "Correct what the scope shows, not what the wind should do. It IS said "
        "with the landing clearance, where it tells him what to expect in the "
        "flare: \"cleared to land, wind two seven zero at two zero\".",
        f"- Assignable altitudes: **{profile.platform_ft}** vectoring, "
        f"**{profile.mda_ft}** MDA, **{profile.missed_ft}** missed. Nothing else.",
        *_threats(),
        *_formation(flight, size, profile),
    ])


def _threats() -> list[str]:
    """What is shooting, and how far it reaches.

    The controller has radar and the pilot has a chart, and only one of them can
    see where the aeroplane actually is relative to a battery. A pilot asking to
    be kept clear of Kutaisi is asking a reasonable thing; without this the
    controller has never heard of Kutaisi's guns and says something reassuring
    and useless.
    """
    if not getattr(R, "DEFENDED", None):
        return []
    fields = "; ".join(f"**{n}** ({r:.0f} nm)" for n, _, _, r in R.DEFENDED)
    return [
        f"- **Defended enemy fields**: {fields}. Heavy anti-aircraft guns that "
        "reach well above transit altitude. Everything outside Batumi is "
        "hostile, and these three are the ones that shoot back.",
        "- **Keep him clear of them, and say so when you do.** If his track is "
        "closing on one, turn him — \"come left twenty degrees, you are "
        "closing on the Kutaisi defences\" — and if he asks to be routed round "
        "them, do it. You can see his position against them; he is looking at a "
        "chart and guessing.",
    ]


def plate(profile: R.ApproachProfile = R.BATUMI_ASR,
          flight: str = R.FLIGHT_CALLSIGN,
          size: int = R.FLIGHT_SIZE) -> str:
    if getattr(profile, "vectored", False):
        return _asr_plate(profile, flight, size)
    return _ndb_plate(profile, flight, size)


def _ndb_plate(profile: R.ApproachProfile,
               flight: str = R.FLIGHT_CALLSIGN,
               size: int = R.FLIGHT_SIZE) -> str:
    """The field-specific facts, as the markdown 'plate' prompt part."""
    cap = profile.atc
    b = profile.beacon
    inbound = _inbound_hdg(profile)
    outbound = (inbound + 180) % 360
    hold, platform = profile.stack_ft[0], profile.platform_ft
    mda, missed = profile.mda_ft, profile.missed_ft
    rwy = profile.runway or "in use"

    return "\n".join([
        "# This mission's plate (the field-specific facts)",
        "",
        f"- Controller **{profile.controller}**, recovering to runway **{rwy}**.",
        f"- Beacon **{b.name}**, **{b.freq_mhz:.1f}**, Morse ident "
        f"**{_phonetic(b.ident)}** — the pilot homes it.",
        *_channels(profile),
        f"- Capability: radar **{'ON' if cap.radar else 'OFF'}**, "
        f"aircraft DME **{'yes' if cap.dme else 'NO'}**, "
        f"separation **{cap.separation}**, era **{cap.era}**.",
        "",
        "The letdown, in order — never skip a leg:",
        f"1. Inbound to the beacon: home it, descend and maintain **{hold}**.",
        "2. Station passage (crossing the beacon) begins the approach.",
        f"3. Outbound heading **{outbound:03d}** for the procedure turn, descend "
        f"to platform **{platform}**. The outbound leg runs about two minutes.",
        f"4. Procedure turn, back inbound on the beam heading **{inbound:03d}**.",
        f"5. Down the beam to **MDA {mda}**. Runway in sight → land {rwy}; not in "
        f"sight → missed.",
        f"- Missed approach: climbing **{profile.missed_turn}** turn to "
        f"**{missed}**, back to the beacon, re-sequence.",
        f"- Timing: about **{_mmss(profile.final_approach_sec)}** from established "
        "inbound to the threshold — flown on a watch (no cone of silence).",
        f"- Wind **{int(R.WIND_FROM_DEG):03d} at {int(R.WIND_MPH)}** — expect a "
        f"tailwind float on {rwy}; plant it early.",
        *_formation(flight, size, profile),
        f"- Assignable levels: holding **{', '.join(str(f) for f in profile.stack_ft)}** "
        f"(bottom first), platform **{platform}**, MDA **{mda}**, missed "
        f"**{missed}** — and headings **{outbound:03d} out / {inbound:03d} in**. "
        "Nothing else.",
    ])


if __name__ == "__main__":
    print(plate())
