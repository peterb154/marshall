"""The weather at one aerodrome, as an ATIS would report it.

    "The atis module should calculate Wx and active runway, and information
     [letter] for each airport with atis. Update this info in the database."

WHAT THIS IS NOT. It is not "the mission weather". The mission has one set of
numbers; an aerodrome has an OBSERVATION, which is those numbers measured at a
place and expressed in the frames a pilot works in. The two differ in ways that
matter, and every one of them has bitten something in this project already:

    ceiling      the sim's cloud base is METRES ABOVE SEA LEVEL. A ceiling is
                 reported in FEET ABOVE THE FIELD. At Batumi that is 32 feet of
                 difference and at Kobuleti 59, which is nothing -- and at a
                 mountain field it is the whole number. Same class of error as
                 grid versus true: two real quantities, one name.
    altimeter    QFE here is not QFE there. The sim gives a pressure per point,
                 so Kobuleti reads 1010.9 hPa and Batumi 1011.8 at the same
                 moment, because one is 26 feet higher than the other.
    runway       computed from the wind, per field. See `Field_.runway_in_use`.

DEWPOINT IS DERIVED, not invented, and there is a real difference.

DCS does not model one, and my first pass left it out on the grounds that a
plausible number is the same mistake as a chart printing a grid heading and
calling it true. That was too pure: the spread is not free to be anything,
because the sim already tells us where the cloud forms.

    "Dew points can be inferred from cloud base."

Which is the standard rule and it runs the other way round from how it is
usually quoted: cloud base in feet AGL is about 400 times the temperature/
dewpoint spread in Celsius, so the base the sim gives us fixes the spread.

That makes the number CONSISTENT with what the pilot can see out of the window
-- a low ragged base reads as a small spread, a high base as a dry day -- which
is worth more than accuracy here. With no cloud at all there is nothing to
derive from, so a dry-day spread is assumed and the code says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

M_TO_FT = 3.28084
HPA_TO_INHG = 0.0295299830714


# DCS reports cloud DENSITY on a scale of ten and no sky-cover code at all, so
# the octas a pilot expects have to be derived. The bands are the conventional
# ones; what matters here is the CEILING RULE, which is not a matter of taste:
#
#   a ceiling is the lowest BROKEN or OVERCAST layer.
#
# Few and scattered are not a ceiling. Reporting one for scattered cloud tells
# a pilot he needs an instrument approach to get in when he can see the runway
# from ten miles, and on a marginal day that is the difference between flying
# the visual and flying the ASR.
SKY = (
    (0, "sky clear", False),
    (3, "few", False),
    (6, "scattered", False),
    (8, "broken", True),
    (10, "overcast", True),
)


def sky_cover(density: int) -> tuple[str, bool]:
    """(spoken cover, is it a ceiling) for a DCS density 0-10."""
    for limit, words, ceiling in SKY:
        if density <= limit:
            return words, ceiling
    return "overcast", True


@dataclass(frozen=True)
class Observation:
    """One aerodrome's weather at one moment. Frames named, like everything."""

    field: str
    wind_from_deg: int              # magnetic, as a pilot is given it
    wind_kt: int
    visibility_m: int
    sky: str                        # "sky clear" | "few" | ... | "overcast"
    ceiling_ft_agl: int | None      # None when there is no ceiling to report
    temp_c: int
    qnh_inhg: float
    qfe_inhg: float
    runway: int                     # the designator in use, computed from wind

    @property
    def is_ceiling(self) -> bool:
        return self.ceiling_ft_agl is not None

    def same_as(self, other: Observation | None) -> bool:
        """Would an ATIS keep the same letter?

        A NEW LETTER MEANS "LISTEN AGAIN", so it must not chase noise. The wind
        wandering by a degree is not new information, and rotating on it would
        train pilots to ignore the letter -- which is the one thing the letter
        is for. Real ATIS rotates on a MATERIAL change, and these are the
        materials: the runway in use, whether there is a ceiling and roughly
        where, the visibility band, and a wind shift big enough to fly.
        """
        if other is None:
            return False
        return (self.runway == other.runway
                and self.is_ceiling == other.is_ceiling
                and _band(self.ceiling_ft_agl) == _band(other.ceiling_ft_agl)
                and _vis_band(self.visibility_m) == _vis_band(other.visibility_m)
                and abs(_diff(self.wind_from_deg, other.wind_from_deg)) < 30
                and abs(self.wind_kt - other.wind_kt) < 10)


def _diff(a: int, b: int) -> int:
    return (a - b + 180) % 360 - 180


def _band(ft: int | None) -> int | None:
    """Ceilings in five-hundred-foot bands. A ceiling that wobbles either side
    of a round number must not spend a sortie rotating the letter."""
    return None if ft is None else int(ft // 500)


def _vis_band(m: int) -> int:
    """Visibility in kilometres, capped -- above ten it is all 'ten or more'
    and nobody re-records for the difference between 40 km and 45."""
    return min(10, int(m // 1000))


def observe(field, wind_from_deg: float, wind_kt: float, cloud_base_m: float,
            cloud_density: int, visibility_m: float, temp_c: float,
            qnh_inhg: float, qfe_inhg: float) -> Observation:
    """Build one aerodrome's observation from the sim's raw numbers.

    `cloud_base_m` IS ABOVE SEA LEVEL, which is the whole reason this function
    exists rather than a dict literal at the call site. The subtraction below
    is the only place it happens.
    """
    cover, ceiling = sky_cover(int(cloud_density))
    agl = None
    if ceiling and cloud_base_m:
        # MSL -> AGL. Negative means the field is IN the cloud, which is a real
        # state (a hill fort in fog) and is reported as zero rather than as a
        # negative height nobody can fly to.
        agl = max(0, int(round(
            (cloud_base_m - field.elevation_ft / M_TO_FT) * M_TO_FT)))
    return Observation(
        field=field.name,
        wind_from_deg=int(round(wind_from_deg)) % 360,
        wind_kt=int(round(wind_kt)),
        visibility_m=int(round(visibility_m)),
        sky=cover,
        ceiling_ft_agl=agl,
        temp_c=int(round(temp_c)),
        qnh_inhg=round(qnh_inhg, 2),
        qfe_inhg=round(qfe_inhg, 2),
        runway=field.runway_in_use(wind_from_deg),
    )


def hpa_to_inhg(hpa: float) -> float:
    return hpa * HPA_TO_INHG


def wind_components(runway_mag: float, wind_from: float, wind_kt: float):
    """(headwind, crosswind) in knots, positive crosswind from the right.

    Not used by the broadcast -- an ATIS reports the wind and lets the pilot do
    this -- but it is what `runway_in_use` is deciding with, and having it in
    one place stops the next caller doing the trigonometry again.
    """
    off = math.radians(wind_from - runway_mag)
    return wind_kt * math.cos(off), -wind_kt * math.sin(off)
