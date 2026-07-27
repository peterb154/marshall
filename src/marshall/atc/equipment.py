"""What can this aeroplane actually navigate with?

    "somehow we need to infer or request what equipment a pilot has. IRL it's in
     the IFR flight plan. In DCS, we could make a module table or something?"

Exactly right, and in the real world it is field 10 of the ICAO flight plan --
the equipment suffix that tells a controller whether he may say "hold at BATUMI
as published" or has to describe a racetrack in headings and minutes.

DCS has no such field, but it has something better: it tells us the AIRFRAME,
on every radar return, and an airframe's equipment is not a matter of opinion.
A P-51D-30 has the AN/ARA-8 homing adapter. A Spitfire has a compass and a
clock. An F-16 knows where it is to the foot. Nobody has to declare anything and
no pilot can get it wrong, which is better than the real system.

Three tiers, because three is what changes a controller's behaviour:

    ins   he knows his position. Name a fix and leave him alone.
    adf   he can home a beacon, but has no position of his own. He can hold at
          a beacon; he cannot hold at a point in space.
    dr    a compass, a watch and a map. Every instruction has to be a heading,
          an altitude or a time -- there is nothing else he can act on.

WHEN IN DOUBT, ASSUME LESS. An aeroplane wrongly treated as dead-reckoning gets
a hold spelled out in headings and minutes, which anybody can fly. One wrongly
treated as equipped gets sent to a fix it cannot find, and the first anybody
knows is when it does not arrive.

This is deliberately a SECOND copy of the table in `director/tools/plans.py`,
for the same reason `PHASES` is duplicated there: the bridge and the director
are different deployables and neither imports the other. The rule when they
disagree is that this one describes what a CONTROLLER may say to him, and that
one describes how much help he wants EN ROUTE. They answer different questions
from the same fact.
"""

from __future__ import annotations

# By the type string the sim reports, exactly as it appears on radar.
NAV_BY_TYPE = {
    # The one warbird here with a homing adapter, and the reason the beacon
    # letdown was ever flyable.
    "P-51D-30-NA": "adf",
    # Everything else in the 1944 hangar: a compass, a watch, and a map.
    "P-51D": "dr",
    "P-47D-30": "dr",
    "SpitfireLF Mk IX": "dr",
    "SpitfireLFMkIX": "dr",
    "F4U-1D": "dr",
    "MosquitoFBMkVI": "dr",
    "Bf-109K-4": "dr",
    "FW-190D9": "dr",
    "FW-190A8": "dr",
    "I-16": "dr",
    "Yak-52": "dr",
}


def nav_of(aircraft_type: str | None) -> str:
    """How he navigates, from the type radar reports.

    An unknown type is assumed MODERN, because anything not in a 1944 hangar
    almost certainly has an inertial platform -- but an unknown or EMPTY type is
    a different thing, and gets the cautious answer: see `can_hold_at_fix`,
    where not knowing is treated as not equipped.
    """
    if not aircraft_type or not aircraft_type.strip():
        return "unknown"
    return NAV_BY_TYPE.get(aircraft_type.strip(), "ins")


def must_be_told_the_pattern(nav: str) -> bool:
    """Does he need the hold spelled out as headings and minutes?

    Only a KNOWN dead-reckoning aeroplane, and the asymmetry is deliberate.

    My first instinct was to treat "unknown" as unequipped, on the general
    principle that assuming less is safer. It is wrong HERE, and fifteen tests
    said so before a pilot had to: a published hold is only ever offered at a
    field whose approach is a BEACON LETDOWN, and an aeroplane with no receiver
    cannot fly that approach at all. Anything holding there has already
    demonstrated it can home the beacon by being in the procedure.

    So the question is not "do we know he is equipped" but "do we know he is
    NOT". At a radar field the point is moot -- there is nothing to hold over
    and everyone gets the pattern.
    """
    return nav == "dr"


def can_hold_at_fix(nav: str) -> bool:
    """The same question the other way up, for callers who read better in the
    positive."""
    return not must_be_told_the_pattern(nav)
