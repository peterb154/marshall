"""Which tools a controller is GIVEN, decided by the seat he is sitting in.

    "Every controller is handed every tool, and prose says who may use them."

One agent was built with one tool list for every session, `spawn_ground`
included, and the Overlord brief was what told an approach controller not to put
armour in a valley. **Prose is not a permission system.** It costs tokens on
every call describing capabilities the seat may not use, and it relies on the
model obeying an instruction rather than on the capability being absent.

The station is known deterministically -- `marshall-atc` resolves who is speaking
from the frequency before the call is ever made -- so it is the natural key.

WHAT IS ABSENT CANNOT BE CALLED, and that is the whole argument. The failure this
prevents already happened in the other direction: asked for a target, Sentry
produced a confident, detailed answer and nothing on the ground. A tool the seat
should not have is the same class of problem, and the fix for both is that
authority is structural rather than advisory -- the same reason an LLM never
invents separation.

THE ROLE IS NOT ONE STRING. A field this size does not staff a seat per phase of
flight: Batumi Ground also works delivery and clearance, Kobuleti Departure also
works approach, and Tonopah Tower works its own clearances because there is no
delivery position. So a seat arrives as its primary role PLUS everything it also
covers, and a capability is granted if any of them qualifies. Getting this wrong
in the safe direction (a seat missing a tool it needs) is a controller who
cannot do his job; in the unsafe direction it is the thing we are removing.

UNKNOWN MEANS EVERYTHING, deliberately. If the caller does not say who is
speaking -- an old voice process, a direct call, a test -- the agent gets the full set
and behaves exactly as it did before. A capability system that silently
disarmed a controller because a field was missing would be worse than none.
"""

from __future__ import annotations

# Every role that appears in `core/stations.py`, and what it may reach for.
#
# `spawn_ground` is the only genuinely dangerous one and the reason this file
# exists: it puts vehicles in the world. It belongs to the OVERLORD -- the
# mission commander seat, Sentry -- and to nobody working an aerodrome.
_TOOLSET = {
    # The seat that issues an IFR clearance. Its numbers are facts about what
    # was filed, so the tool returns finished words.
    "clearance": {"clearance"},
    "delivery": {"clearance"},
    # A tower with no delivery position beside it works clearances too, which
    # is why `also` is consulted rather than the primary role alone.
    "ground": set(),
    "tower": set(),
    "departure": set(),
    "approach": set(),
    "center": set(),
    # The mission commander. Not an aerodrome controller at all.
    "overlord": {"spawn"},
}

# Given to every seat, because every controller needs them: knowing who is
# calling, measuring a range, arranging to be woken, looking up a frequency he
# was not briefed, looking up an approach he was not briefed, and remembering
# the sortie.
#
# `procedure` is universal for the same reason `frequency` is: a pilot asks
# whoever he is talking to. He asks Ground what approaches are in use as
# readily as he asks Approach, and a controller who cannot answer a question
# about his own aerodrome because of a capability table is a worse failure
# than the tokens it saves. ISSUING one is still Approach's alone -- that is
# separation, and it lives in the engine rather than in who may read a list.
# `flightplan` is universal for exactly the reason `frequency` and
# `procedure` are, and it was not: reading an aeroplane's plan rode inside
# the CLEARANCE capability, so the only seats that could see where a man
# was going were the two that issue clearances. Departure told a pilot it
# did not have his steerpoints and was telling the truth. Issuing a
# clearance is a power; knowing what he is doing is not. [#199]
_UNIVERSAL = {"identify", "vector", "hooks", "frequency", "procedure",
              "memory", "flightplan"}


def capabilities(role: str = "", also=()) -> set[str]:
    """The capability names this seat may use.

    Empty `role` means "the caller did not say", and returns everything -- see
    the note at the top of this module. Anything else is the union of what the
    primary role and every additional role allow, plus the universal set.
    """
    if not role:
        return _UNIVERSAL | {"clearance", "spawn"}
    seats = [role.strip().lower(), *(str(a).strip().lower() for a in (also or ()))]
    got = set(_UNIVERSAL)
    for seat in seats:
        got |= _TOOLSET.get(seat, set())
    return got


def describe(role: str = "", also=()) -> str:
    """One line for the log, so a missing tool is diagnosable from the console."""
    seats = "+".join([role or "unknown", *[str(a) for a in (also or ())]])
    return f"{seats}: {', '.join(sorted(capabilities(role, also)))}"
