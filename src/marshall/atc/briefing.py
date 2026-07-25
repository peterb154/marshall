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
    """The formation block: who is expected, and how a flight gets handled.

    Generated rather than written into the prompt, because the break-up levels
    are the stack's business and the stack is data. If the hold base moves, this
    moves with it, and the controller never briefs a level the engine will not
    assign."""
    from marshall.atc import callsign as C

    lead = C.parse(flight)
    if size <= 1:
        return [f"- Expected inbound: **{lead.spoken}**, single ship (any pilot "
                "may call with his own callsign; correlate by position)."]
    members = lead.members(size)
    ladder = ", ".join(
        f"{C.parse(m).spoken} {ft}"
        for m, ft in zip(members, profile.stack_ft))
    # The FLIGHT is addressed without a member number: lead is "Pony one one",
    # but all four of them together are "Pony one flight".
    as_flight = C.Callsign(lead.flight).spoken_flight
    return [
        f"- Expected inbound: **{as_flight}**, a **{size}-ship** "
        f"({', '.join(C.parse(m).spoken for m in members)}). Any pilot may call "
        "with his own callsign; correlate by position, don't assume this one.",
        f"- **Work a formation as ONE aircraft** while it is together: one "
        f"clearance, one altitude, lead answers for all of them. Address it "
        f"\"{as_flight}\". A wingman who transmits is the flight talking "
        "— do not start a second conversation with him.",
        f"- **Break them up at the holding fix**, into individually-sequenced "
        "singles. You do not hold a formation through a letdown. After the "
        "break-up they are ordinary singles and you use their own callsigns.",
        "- **Ask first: \"can you maintain visual separation between your "
        "aircraft?\"** In visual conditions they may break up inside ONE holding "
        f"level, in trail — all {size} at {profile.hold_base_ft} — because the "
        "pilots can see each other and keep themselves apart. That is quicker "
        "and it is what they will usually want.",
        f"- **In cloud, you separate them yourself** — a level each, lead lowest "
        f"so he lands first: {ladder}.",
    ]


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
        f"- Wind **{int(R.WIND_FROM_DEG):03d} at {int(R.WIND_MPH)}** mph. Do NOT "
        "pass it as a correction — you are watching his ground track, so the "
        "drift is already inside the heading you give him. Correct what the "
        "scope shows, not what the wind should do.",
        f"- Assignable altitudes: **{profile.platform_ft}** vectoring, "
        f"**{profile.mda_ft}** MDA, **{profile.missed_ft}** missed. Nothing else.",
        *_formation(flight, size, profile),
    ])


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
