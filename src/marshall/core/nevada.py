"""Nellis and Tonopah, by the names the call sites already use.

    "How well do you think this system is going to transport to a totally
     different map and field? ... There had not been anything in code that locks
     it into caucuses"

THIS FILE USED TO BE THE MAP. Two `Field_` objects with their surveyed MVA
grids, nine `Station` objects with their frequencies and their manner, two
`Fix` objects and two `ApproachProfile`s -- four hundred lines of numbers about
a place, in Python, while the Caucasus had been rows in
`config/theatres/caucasus.toml` since the approaches moved. One map was data
and the other was code, and every rule in docs/CONFIG.md applied to one of
them.

The numbers are now `config/theatres/nevada.toml` and what is left here is the
lookup. It is the same shape `route.py` already has for the Caucasus and it is
here for the same reason: some dozens of call sites read `N.NELLIS_ILS` and
`N.NEVADA_FIELDS`, and the seam is worth more in one readable place than spread
over six files. The names resolve LAZILY, so nothing reads a theatre file at
import.

IT PINS THE MAP, which `route.__getattr__` deliberately does not. `R.BATUMI_ASR`
means "the configured theatre's" and answers for whatever `MARSHALL_THEATRE`
says; these names ARE Nevada's, so they ask for Nevada by name and a test may
have them without setting the environment. That was true before the move --
they were module constants -- and it stays true.

THE CLASSES STAY IN PYTHON. `Fix`, `Field_`, `Station` and `ApproachProfile`
are shapes and behaviour; only the instances were data. See docs/CONFIG.md
and #137.
"""

from __future__ import annotations

MAP = "nevada"

_FIELDS = {
    "NELLIS_FIELD": "Nellis",
    "TONOPAH_FIELD": "Tonopah",
}

_STATIONS = {
    "NELLIS_CLEARANCE": "Nellis Clearance",
    "NELLIS_GROUND": "Nellis Ground",
    "NELLIS_TOWER": "Nellis Tower",
    "NELLIS_DEPARTURE": "Nellis Departure",
    "NELLIS_APPROACH": "Nellis Approach",
    "TONOPAH_APPROACH": "Silverbow Approach",
    "TONOPAH_TOWER": "Silverbow Tower",
    "TONOPAH_GROUND": "Silverbow Ground",
    # THE REGION, WHICH IS NOT AN AERODROME'S CONTROLLER. Without a Center a
    # departure worked cleanly through Clearance, Ground, Tower and Departure
    # and then stayed with Departure for the rest of the sortie -- nothing
    # failed, a rung was simply missing (#110). Los Angeles Center owns the
    # enroute airspace over southern Nevada and a transit between two airfields
    # is enroute work.
    "NEVADA_CENTER": "Los Angeles Center",
}

_APPROACHES = {
    "NELLIS_ILS": "nellis-ils-21",
    "TONOPAH_ILS": "tonopah-ils-15",
}

# The two published fixes, under the idents the profiles were written with.
_FIXES = {
    "LSV": "NELLIS",
    "TPH": "TONOPAH",
}

def _published_fixes():
    """The map's fixes, ONE object per fix, so a name used twice is one place."""
    from marshall.core import theatre as _th
    return {f.name: f for f in _th.fixes_now(MAP)}


def __getattr__(name: str):
    """Resolve a Nevada name against `config/theatres/nevada.toml`.

    Raises `AttributeError` for anything else, which is what Python expects and
    what keeps a typo an error rather than a None that becomes a plausible
    number three layers away.
    """
    from marshall.core import theatre as _th
    if name == "NEVADA_FIELDS":
        return tuple(_th.fields_now(MAP))
    if name == "NEVADA_STATIONS":
        # IN LADDER ORDER, which is the file's order: Nellis outbound, then
        # Tonopah written approach-first because that is the order a pilot
        # arriving there presses the buttons.
        return list(_th.stations_now(MAP))
    if name == "NEVADA_FIXES":
        return list(_published_fixes().values())
    if name == "NEVADA_ROUTE":
        # THE SORTIE'S NUMBERED POINTS, and the ORDER is the theatre's -- one
        # list, in `theatre.NEVADA_ROUTE`, so the waypoints a pilot is briefed
        # and the ones the mission builder writes cannot be two routes. Names
        # and not coordinates, so it cannot drift from the catalogue either.
        at = _published_fixes()
        return [at[n] for n in _th.NEVADA_ROUTE]
    if name in _APPROACHES:
        got = _th.approaches_now(MAP).get(_APPROACHES[name])
        if got is None:
            raise AttributeError(
                f"{name} names approach {_APPROACHES[name]!r}, which "
                f"nevada.toml does not publish. See docs/CONFIG.md")
        return got
    if name in _FIXES:
        got = _published_fixes().get(_FIXES[name])
        if got is None:
            raise AttributeError(
                f"{name} names fix {_FIXES[name]!r}, which nevada.toml does "
                f"not publish. See docs/CONFIG.md")
        return got
    table, want, what = (
        (_th.fields_now(MAP), _FIELDS.get(name), "aerodrome")
        if name in _FIELDS
        else (_th.stations_now(MAP), _STATIONS.get(name), "station"))
    if want is not None:
        for got in table:
            if got.name == want:
                return got
        raise AttributeError(
            f"{name} names {what} {want!r}, which nevada.toml does not have. "
            f"See docs/CONFIG.md")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
