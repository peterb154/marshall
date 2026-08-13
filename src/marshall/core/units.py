"""The numbers everything else is measured in, and the air they are measured through.

Conversions, the mission's altimeter setting, and the two sums that turn a
height into a pressure and a true airspeed into the needle the pilot is
actually looking at. The WIND is deliberately not here; see below. Nothing here knows about a fix, a field or a controller,
which is why it is the bottom of `core` and may be imported by anything.

Speeds are MPH because the P-51's airspeed indicator is. That decision is made
HERE and nowhere else; a module that converts on its own is how two cards come
to disagree about the same leg.
"""

from __future__ import annotations

NM = 1852.0
MPH_PER_KT = 1.15078

# Caucasus magnetic variation, degrees EAST. The compass reads magnetic; every
# heading the pilot actually flies has to be corrected. "East is least" -- east
# variation is subtracted from true.
MAGVAR = 6.0

# Briefed conditions.
CRUISE_TAS_MPH = 220.0
CRUISE_ALT_FT = 5000

# THE WIND IS NOT HERE ANY MORE, and where it went is the point.
#
# It was `WIND_FROM_DEG = 90.0` and `WIND_MPH`, right here, while the runway in
# use was a MEASUREMENT: `atis/` samples the sim's wind over each field, decides
# the active runway from it and writes both to the `atis` table, and a
# controller ASKS that table rather than recomputing. So one sentence carried
# two winds --
#
#     f"{self._runway_in_use()}, {self._wind_phrase()}"
#
# -- the runway from the observation and the wind from this constant, and a
# landing clearance could name a wind that contradicted the ATIS broadcast that
# chose its runway. It survived only because the declared Caucasus wind was
# never far enough off to flip an end, which is luck (#148).
#
# There are two honest answers now and neither of them is a constant in code:
#
#     what was MEASURED     `atis.store.wind(field)` -- per field, per instant,
#                           the same row the runway came out of
#     what was DECLARED     `theatre.declared_wind()`, out of
#                           config/theatres/<map>.toml, which is what the
#                           mission is BUILT with and the fallback for anything
#                           running with no sim
#
# `R.WIND_FROM_DEG` and `R.WIND_MPH` still resolve -- through `route.__getattr__`
# onto the theatre -- so the plate, the nav log and the mission builder read the
# map's declared wind and cannot disagree with the .miz they produce.

# Altimeter setting. Briefed, written into the mission, and passed on radar
# contact -- a pilot who never gets one is flying on whatever was in the
# Kollsman window when he spawned, and every advisory altitude the controller
# reads him is measured against a different datum than the one he is holding.
# DCS stores it in millimetres of mercury; aircrew are given inches, and the
# two must come from one number or they drift.
QNH_MMHG = 760.0
QNH_INHG = QNH_MMHG / 25.4          # sea level: the altimeter reads elevation
                                    # on the ground

# Near sea level the atmosphere loses about this much pressure per foot of
# climb. Enough to convert a field's elevation into the pressure difference
# between QNH and QFE, which is all this is used for.
INHG_PER_FT = 0.00108


def qfe_inhg(field_elev_ft: float, qnh_inhg: float = 0.0) -> float:
    """Field-level pressure: set this and the altimeter reads ZERO on the deck."""
    return (qnh_inhg or QNH_INHG) - field_elev_ft * INHG_PER_FT


def altimeter_spoken(inhg: float = 0.0) -> str:
    """The setting as a controller says it: "two niner niner two"."""
    digits = f"{(inhg or QNH_INHG):.2f}".replace(".", "")
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "niner"}
    return " ".join(words[d] for d in digits)


def ias_mph(tas_mph: float, alt_ft: float) -> int:
    """Indicated airspeed for a true airspeed at a height.

    What the pilot flies is the needle, and the needle reads less than the
    truth as the air thins -- about two per cent per thousand feet, which is
    the rule of thumb every pilot carries and is close enough well below the
    tropopause. Down at five hundred feet over the water they are the same
    number; coming home at eleven thousand they are thirty apart, and a nav log
    quoting only true airspeed asks the pilot to do that sum himself while
    flying an aeroplane.
    """
    return int(round(tas_mph / (1.0 + 0.02 * (alt_ft / 1000.0))))
