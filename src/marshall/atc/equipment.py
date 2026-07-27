"""What can this aeroplane actually receive?

    "somehow we need to infer or request what equipment a pilot has. IRL it's in
     the IFR flight plan. In DCS, we could make a module table or something?"

    "there are some aircraft that can use a vortac or tacan station."

Both right, and the second one is why this is a SET and not a ladder.

The obvious model is a scale -- dead reckoning, then ADF, then TACAN, then INS,
each better than the last. It is wrong, and wrong in a way that would put an
aeroplane somewhere it cannot navigate to. **The DCS F-16 has TACAN and an
inertial platform and NO ADF AT ALL.** It cannot home the NDB that a 1944
Mustang homes without difficulty. Better equipped overall, and less able to fly
this particular approach.

So capability is a set of RECEIVERS, and the question is never "how good is he"
but "can he use THIS station":

    adf     a needle that points at an NDB. Bearing only, no distance.
    tacan   bearing AND distance from a TACAN or the military half of a VORTAC.
    vor     bearing from a VOR or the civil half of a VORTAC.
    ils     a localiser and glideslope on one runway.
    ins     he knows where he is without any station at all.

In the real world this is field 10 of an IFR flight plan, typed by a human who
can get it wrong. Here the sim states the airframe on every radar return, so
nobody declares anything and no pilot can be mistaken about his own aeroplane --
which is better than the system it replaces.

WHAT IS NOT MODELLED, deliberately: whether a station is actually radiating.
The sim's Airbase object exposes runways and callsigns and no beacon table, so
there is no authority to ask. `route.py` says what is published at this field;
if that is wrong, it is wrong in one place.
"""

from __future__ import annotations

# By the type string the sim reports, exactly as it appears on radar.
#
# The warbirds are nearly all empty sets, and that is not an oversight -- a
# Spitfire has a compass, a watch and a map, and every instruction a controller
# gives it has to be a heading, an altitude or a time.
RECEIVERS: dict[str, frozenset[str]] = {
    # The one warbird here with a homing adapter (AN/ARA-8), and the reason the
    # beacon letdown is flyable at all.
    "P-51D-30-NA": frozenset({"adf"}),
    "P-51D": frozenset(),
    "P-47D-30": frozenset(),
    "SpitfireLF Mk IX": frozenset(),
    "SpitfireLFMkIX": frozenset(),
    "F4U-1D": frozenset(),
    "MosquitoFBMkVI": frozenset(),
    "Bf-109K-4": frozenset(),
    "FW-190D9": frozenset(),
    "FW-190A8": frozenset(),
    "I-16": frozenset(),

    # Modern types. NOTE THE F-16: TACAN, ILS and an inertial platform, and no
    # ADF -- it cannot home an NDB the Mustang homes easily.
    "F-16C_50": frozenset({"tacan", "ils", "ins"}),
    "FA-18C_hornet": frozenset({"tacan", "ils", "ins"}),
    "F-15ESE": frozenset({"tacan", "ils", "ins"}),
    "A-10C_2": frozenset({"tacan", "vor", "ils", "ins"}),
    "A-10C": frozenset({"tacan", "vor", "ils", "ins"}),
    "AV8BNA": frozenset({"tacan", "ils", "ins"}),
    "M-2000C": frozenset({"tacan", "vor", "ils", "ins"}),
    "F-14B": frozenset({"tacan", "ils", "ins"}),
    "Ka-50": frozenset({"adf", "ins"}),
    "UH-1H": frozenset({"adf", "vor"}),
    "Mi-8MT": frozenset({"adf"}),
}

# What an aeroplane nobody has listed is assumed to carry. Anything absent from
# the table is far more likely to be a modern type than a 1944 fighter -- but it
# is deliberately NOT given an ADF, because the airframes that have one are
# nearly all old and are all listed.
ASSUMED_MODERN = frozenset({"tacan", "ils", "ins"})


def receivers(aircraft_type: str | None) -> frozenset[str]:
    """What he can tune, from the type radar reports.

    An empty set means dead reckoning: a compass, a watch and a map. An UNKNOWN
    type -- no radar contact, or a scope line without a type -- is a different
    thing again, and the caller decides what to do about it.
    """
    if not aircraft_type or not aircraft_type.strip():
        return ASSUMED_MODERN
    return RECEIVERS.get(aircraft_type.strip(), ASSUMED_MODERN)


# WHAT RECEIVER EACH KIND OF STATION NEEDS. Written out because the two
# vocabularies do not match and assuming they do is a real bug: the station is
# an NDB and the receiver is an ADF, and comparing the words directly said a
# P-51 could not use the beacon it was built to home. A VORTAC is one
# installation with two halves and answers to either receiver, which is the
# whole reason this is a mapping to a SET.
RECEIVER_FOR = {
    "ndb": frozenset({"adf"}),
    "tacan": frozenset({"tacan"}),
    "vor": frozenset({"vor"}),
    "vortac": frozenset({"vor", "tacan"}),
    "ils": frozenset({"ils"}),
}


def can_use(kit: frozenset[str], navaid_kind: str | None) -> bool:
    """Can he navigate to a station of this kind?"""
    if not navaid_kind:
        return False                       # a point in space is nobody's fix
    needs = RECEIVER_FOR.get(navaid_kind.strip().lower())
    if needs is None:
        return False                       # a station nobody has modelled
    return bool(kit & needs)


def can_hold_at(kit: frozenset[str], navaid_kind: str | None) -> bool:
    """May a controller send him to hold OVER this station?

    An inertial platform is enough on its own: he can hold at a point in space
    because he knows where he is. That is the one case where the answer does not
    depend on what is on the ground.
    """
    return "ins" in kit or can_use(kit, navaid_kind)


def described(kit: frozenset[str]) -> str:
    """One line for a controller's brief, and for a log line worth reading."""
    if not kit:
        return "dead reckoning only -- compass, watch and map"
    return "carries " + ", ".join(sorted(kit))
