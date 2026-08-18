"""Which map a test is flown on -- asked when the test runs, not when it loads.

    MARSHALL_THEATRE=nevada pytest tests -q
      ERROR tests/test_two_fields.py   TOWER names station 'Batumi Tower' ...
      Interrupted: 8 errors during collection

Eight modules could not be COLLECTED on the second map, and the eight were the
two-aerodrome guard, the ILS guard, the ATIS guard, the handoff rule table and
"the wind has one author" -- precisely the files whose whole subject is that a
fact belongs to a field rather than to the process. They failed for one reason,
repeated eight times:

    P = R.BATUMI_ASR        # tests/test_two_fields.py:28, at MODULE SCOPE

`route.__getattr__` resolves that name against the CONFIGURED theatre, and it
resolves it at import. So the map was chosen before the test was, which is the
same defect `core/route.py:126-138` already writes down about default arguments
-- *"a fact captured before anybody has chosen"* -- one directory over, in the
files that exist to catch it.

WHAT THIS MODULE IS. Two things, and they are deliberately different:

    a NAME for the thing this map calls that      arrival(), departure(),
                                                  station(), the_ils(), ...
    a NAMED REFUSAL when the map has no such      only("caucasus", why=...)
    thing at all

The first is the point. A test that says `T.arrival()` instead of
`R.BATUMI_FIELD` asserts the same thing about whichever map is loaded, so the
guard travels. The second is the honest half: the 1944 beacon letdown does not
exist on Nevada and no amount of parameterising will invent one, so that module
SKIPS, with a sentence saying what is therefore unguarded. CLAUDE.md: *"Skipped
is reported, never silent, and it names what is unguarded"* -- a check that
quietly does not run reads exactly like one that passed.

WHAT IT IS NOT. It is not a pytest fixture and there are none in this repo. The
suite is `unittest.TestCase` throughout and stays that way (CLAUDE.md); these
are plain functions, callable from `setUp`, from a class body, or from module
scope, and they resolve on every call.

ONE PROCESS IS ONE MAP. `theatre.current()` is cached and the fields, stations
and approaches behind it are cached per map name, so nothing here can switch
theatres inside a run and nothing should try. Running both maps is running the
suite twice -- see `tools/both_maps.py`.
"""

from __future__ import annotations

import dataclasses
import os
import unittest

from marshall.core import route as R
from marshall.core import theatre as _TH

# --- which map ---------------------------------------------------------------


def name() -> str:
    """The configured map, lower-case. `""` is not possible -- it defaults."""
    return _TH.current().name.lower()


def is_(*maps: str) -> bool:
    return name() in {m.lower() for m in maps}


def only(*maps: str, why: str) -> None:
    """Refuse to run this module anywhere but `maps`, and say what is lost.

    Called at MODULE SCOPE, before anything that would resolve a map-specific
    name. Both runners understand a `SkipTest` raised during import: pytest
    reports the module skipped, `unittest discover` makes a skipped placeholder.
    Neither reports it as passing, which is the whole requirement.

    `why` is not decoration. It is the sentence a reader gets instead of a
    result, so it says what this map has not got -- "Nevada publishes no beacon
    letdown" -- rather than "caucasus only".
    """
    if not is_(*maps):
        raise unittest.SkipTest(
            f"{'/'.join(maps)} only, running on {name()}: {why}")


def skip_unless(*maps: str, why: str):
    """The same refusal for ONE test or one class, as a decorator."""
    return unittest.skipUnless(is_(*maps),
                               f"{'/'.join(maps)} only, running on {name()}: {why}")


# --- the aerodromes ----------------------------------------------------------


def fields() -> tuple:
    """Every aerodrome this map works. Two on both maps today; the guards below
    are written for N, because a role is unique only within an aerodrome and a
    two-candidate list can be got right by accident."""
    return tuple(_TH.current().fields)


def arrival():
    """The field the sortie recovers into. `Field_`, never a name."""
    f = R.field_named(_TH.current().arrival)
    if f is None:                                   # pragma: no cover - config
        raise AssertionError(f"{name()} declares an arrival field "
                             f"{_TH.current().arrival!r} it does not publish")
    return f


def departure():
    """The field the sortie starts from. On Nevada it is the same field as the
    arrival, and that is not a bug to paper over here -- `nevada.toml` declares
    no separate recovery field, so a test that needs two DIFFERENT fields asks
    for `other()` instead."""
    f = R.field_named(_TH.current().departure)
    if f is None:                                   # pragma: no cover - config
        raise AssertionError(f"{name()} declares a departure field "
                             f"{_TH.current().departure!r} it does not publish")
    return f


def other():
    """The map's SECOND aerodrome -- the one the arrival is not.

    This is the one worth having. Every fault in the 13 August inventory on the
    ONE FIELD axis is a real controller, a real frequency and a real distance
    belonging to this field instead of the other, so a test that cannot name
    "the other one" cannot see any of them.
    """
    arr = arrival().name
    for f in fields():
        if f.name != arr:
            return f
    raise AssertionError(f"{name()} publishes one aerodrome; there is no other")


def field_of(profile):
    """The `Field_` an approach arrives at. `profile.aerodrome` is a `Fix`.

    CASE-FOLDED, because the two catalogues disagree about it and always have: a
    fix is named `BATUMI` and an aerodrome is named `Batumi`, so
    `field_named(profile.aerodrome.name)` is `None` on the Caucasus and a real
    field on Nevada, where the Tonopah fix happens to be title-cased. That is a
    one-of-a-thing fault of its own and it belongs to `src/`; here it is worked
    around in ONE place rather than in each test that trips over it.
    """
    want = profile.aerodrome.name.lower()
    for f in fields():
        if f.name.lower() == want:
            return f
    return R.field_named(profile.aerodrome.name)


# --- the seats ---------------------------------------------------------------


def station(role: str, field=None):
    """A seat, AT A FIELD. The field defaults to the arrival's, never to
    first-match: `station_for("tower")` with no field is the bug this whole
    directory exists to catch, and `test_two_fields.py` greps `src/` for it."""
    fld = field if isinstance(field, str) else (field or arrival()).name
    return R.station_for(role, field=fld)


def center():
    """The enroute seat. Deliberately fieldless on both maps -- owning a region
    is not owning an aerodrome."""
    return R.station_for("center")


# --- the procedures ----------------------------------------------------------


def approaches() -> dict:
    return dict(_TH.approaches_now())


def the_arrival():
    """A published procedure into this map's ARRIVAL FIELD, chosen HERE.

    It read `theatre.current().approach_key` -- the arrival the radio was
    started on -- so sixty-odd assertions across twenty-seven files were pinned
    to whichever procedure a process global happened to name, and changing that
    global moved every one of them. There is no such global now (#162), and a
    test helper that wants one procedure has to SAY WHICH, which is #175's
    finding one file over.

    THE CHOICE IS DECLARED AND IT IS THE LOWEST KEY AT THE FIELD, not a
    hard-coded name: `batumi-asr-13` on the Caucasus, `nellis-ils-21` on
    Nevada. Sorted so it cannot depend on file order, and asserted rather than
    defaulted -- a map that publishes nothing into the field it recovers at is
    a broken map and should say so here rather than three assertions later.
    """
    want = (_TH.current().arrival or "").lower()
    here = {k: p for k, p in sorted(approaches().items())
            if p.aerodrome.name.lower() == want}
    if not here:                                    # pragma: no cover - config
        raise AssertionError(f"{name()} recovers at {want!r} and publishes no "
                             f"approach there: {sorted(approaches())}")
    return next(iter(here.values()))


def flying(procedure, *callsigns):
    """A `Controller` holding these aeroplanes, each CLEARED for this procedure.

    THE INSTRUMENT #162 NEEDED. Everything that reads an arrival fact now asks
    the aeroplane -- `asr_context`, `settle`, `flying_the_missed`, the whole
    monitor -- because there is no process-wide approach left to ask. The
    tests were handing those functions a bare `ApproachProfile`, which was
    exactly the shape being deleted; a test that passes the old singleton is
    not testing the new code, it is keeping the old path alive in the suite.

    So a test that wants a procedure flown SAYS WHO IS FLYING IT. That is one
    line here and it is the whole difference between "the bridge is on the ASR"
    and "Pony 1-1 was cleared for the ASR", which is the distinction the issue
    is about.

    No callsigns is a real case and a useful one: a controller working traffic
    nobody has cleared for anything. `_pro` answers None for all of them, which
    is what the live code now has to cope with.
    """
    from marshall.atc import controller as _C
    ctl = _C.Controller()
    for cs in callsigns:
        ctl.aircraft[cs] = _C.Aircraft(callsign=cs, profile=procedure)
    return ctl


def approach_of_kind(kind: str, field=None):
    """A published procedure of this kind, at this field. `None` if the map has
    none -- which is a fact about the map, and the caller says what it means."""
    want = (field or arrival()).name if not isinstance(field, str) else field
    for p in approaches().values():
        if p.kind == kind and p.aerodrome.name.lower() == want.lower():
            return p
    return None


def the_ils(field=None):
    """An ILS at this field, or the map's first one. Both maps publish one."""
    return (approach_of_kind("ils", field)
            or next((p for p in approaches().values() if p.kind == "ils"), None))


def two_approaches():
    """Two procedures at TWO DIFFERENT aerodromes, on whichever map is loaded.

    The instrument the suite did not have. `tests/test_a_profile_per_flight.py`
    was the first test in the repo to construct two of the thing, and it did it
    by importing `marshall.core.nevada` directly -- which is correct for that
    file and does not travel. This does.
    """
    here, there = arrival().name, other().name
    a = next((p for p in approaches().values()
              if p.aerodrome.name.lower() == here.lower()), None)
    b = next((p for p in approaches().values()
              if p.aerodrome.name.lower() == there.lower()), None)
    if a is None or b is None:
        raise unittest.SkipTest(
            f"{name()} publishes no approach at {here if a is None else there}, "
            f"so two aerodromes cannot be worked at once here")
    return a, b


def letdown():
    """A beacon letdown: `kind='ndb'`, `guidance='talkdown'`, homing a navaid.

    PUBLISHED WHERE THE MAP HAS ONE, CONSTRUCTED WHERE IT HAS NOT, and the
    difference is stated rather than hidden. Caucasus publishes `batumi-ndb` --
    the 1944 procedure the whole separation engine was written against -- and
    this returns it unchanged, so nothing on that map moves by a foot. Nevada
    publishes two ILS approaches and no letdown at all, so one is built here,
    at that map's arrival field, out of the same numbers.

    That construction is the point rather than a compromise. The engine tests
    are about the RULES -- enter at the top, step down on vacate, one in the
    letdown -- and a rule that only holds over Georgia is not a rule. The census
    in the 13 August inventory reads *"ApproachProfiles the suite constructs:
    zero"*, and every one of those tests was quietly asserting against Batumi's
    stack because Batumi's stack was the only one that existed.
    """
    for p in approaches().values():
        if p.kind == "ndb" and p.guidance == "talkdown":
            return p
    base = the_arrival()
    return dataclasses.replace(
        base, kind="ndb", guidance="talkdown",
        # He homes the field itself, which is what a letdown at a field with one
        # beacon does. `arrival_fix` is where he is worked BEFORE the beacon.
        navaid=base.aerodrome, arrival_fix=base.iaf or base.outer_hold,
        iaf=None)


# --- what the map calls its places -------------------------------------------


def a_fix():
    """Any published fix on this map, for a test that needs *a* place."""
    fx = _TH.fixes_now()
    if not fx:                                      # pragma: no cover - config
        raise AssertionError(f"{name()} publishes no fixes")
    return fx[0]


def mission_bucket() -> str:
    """A test gets its own mission instance -- see `fakeradio.Sortie`."""
    return os.environ.setdefault("MARSHALL_MISSION", "unit-test")
