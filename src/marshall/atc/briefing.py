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


def plate(profile: R.ApproachProfile = R.BATUMI_APPROACH,
          flight: str = R.FLIGHT_CALLSIGN) -> str:
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
        f"- Expected inbound flight: **{flight}** (any pilot may call with his own "
        "callsign; correlate by position, don't assume this one).",
        f"- Assignable levels: **{hold}, platform {platform}, MDA {mda}, missed "
        f"{missed}** — and headings **{outbound:03d} out / {inbound:03d} in**. "
        "Nothing else.",
    ])


if __name__ == "__main__":
    print(plate())
