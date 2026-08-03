"""The numbers everything else is measured in, and the air they are measured through.

Conversions, the mission's wind and altimeter setting, and the two sums that
turn a height into a pressure and a true airspeed into the needle the pilot is
actually looking at. Nothing here knows about a fix, a field or a controller,
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

# Briefed conditions. Wind is the direction it blows FROM.
CRUISE_TAS_MPH = 220.0
CRUISE_ALT_FT = 5000
# FIVE KNOTS FROM THE EAST, and it is the runway that chose it.
#
#     "Let's also move the wind to 090 at 5, so runway 13 makes sense."
#
# The wind is what makes a runway the runway in use, and 180 did not favour
# either end of Batumi's 13/31 -- it was a pure crosswind, so landing 13 was a
# decision the mission had made rather than one the weather justified. A pilot
# reading the plate had no way to derive the runway in use from anything he
# could see.
#
# 090 fixes both ends of the route at once, which is the point of picking it
# rather than something merely non-crosswind: Batumi 13 (125 magnetic) and
# Kobuleti 07 (064 magnetic) are both into the easterly, so the departure end
# and the arrival end agree without anybody having to special-case one of them.
#
# THIS IS STILL THE INPUT AND NOT THE ANSWER. "Runway in use" should be
# computed from the wind rather than declared beside it -- see SCHEMA.md -- and
# while that is still a constant in `Field_.runway`, the two have to be kept
# consistent by hand. Changing the wind here without checking the runways is a
# way to have the controller land people downwind.
#
# WHAT CAME BEFORE, and why it is not 20 mph from 270 any more.
#
# It was 20 mph from 270 -- a stiff, near-direct crosswind on runway 13, which
# is a fine thing to fly against once the procedure works and a poor thing to
# debug an approach in. Every heading correction the controller gave had a wind
# component buried in it, so "he put me left of course" and "I drifted left of
# course" looked identical from both ends.
#
#     "wind should be much much less aggressive. Let's just go with 5 kn from
#      the south"
#
# Changed HERE and nowhere else on purpose: the nav log's timed legs, the
# plate, the mission file and the controller's landing clearance all read this
# one number, so they cannot disagree about it.
WIND_FROM_DEG = 90.0
WIND_MPH = 5.0 * 1.15078          # five knots, in the mph this file works in

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
