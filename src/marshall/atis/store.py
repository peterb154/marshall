"""Reading and writing the current broadcast. One source of truth.

    "Atis should probably determine the active runway. Controllers should query
     the db for that info. One source of truth for that."

WHY THE RUNWAY LIVES HERE and not in whoever needs it. `Field_.runway_in_use()`
is a pure function of the wind, which makes it tempting to call wherever it is
wanted -- and that is exactly the fault this project has spent a week removing.
Two callers computing the same thing agree only while they read the same input
at the same instant. The wind moves; the broadcast is recorded at one moment
and the taxi clearance issued at another; and then the recording says 07 while
Ground says 25, both correct, both defensible, and an aeroplane lined up the
wrong way.

The wind is a MEASUREMENT. The runway is a DECISION. A decision has one author.

WHAT A MISSING ROW MEANS. No row is a field with no ATIS, which is a real
arrangement rather than an error -- most aerodromes do not have one. Callers
fall back to computing the runway themselves, and `current` says which happened
so a controller can be honest on the radio about whether there is a broadcast
to have.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC

from marshall.core import db
from marshall.core.schema import Atis


@dataclass(frozen=True)
class Current:
    """What is on the air at one aerodrome, and where the answer came from."""

    field: str
    letter: str | None
    runway: int
    text: str = ""
    # HOW LONG THIS LETTER HAS BEEN UP, in seconds, or None when nobody is
    # broadcasting. The table has always recorded WHEN; nothing read it back,
    # so a bridge restart began the alphabet again and a mission that ran all
    # day never left the first letter.
    age_sec: float | None = None
    wind_from_deg: int | None = None
    wind_kt: int | None = None
    # FALSE MEANS NOBODY IS BROADCASTING and the runway was computed rather
    # than looked up. Carried rather than inferred from `letter is None`,
    # because a caller that has to reconstruct why an answer is what it is will
    # eventually reconstruct it wrongly.
    on_the_air: bool = True

    @property
    def spoken_letter(self) -> str:
        return self.letter or ""


def publish(obs, letter: str, text: str) -> None:
    """Record this observation as the current broadcast."""
    with db.session() as s:
        row = s.get(Atis, obs.field) or Atis(field=obs.field)
        row.letter = letter
        row.runway = int(obs.runway)
        row.text = text
        row.wind_from_deg = obs.wind_from_deg
        row.wind_kt = obs.wind_kt
        row.visibility_m = obs.visibility_m
        row.sky = obs.sky
        row.ceiling_ft_agl = obs.ceiling_ft_agl
        row.temp_c = obs.temp_c
        row.dewpoint_c = obs.dewpoint_c
        row.qnh_inhg = obs.qnh_inhg
        row.qfe_inhg = obs.qfe_inhg
        row.recorded_at = datetime.now(UTC)
        s.add(row)
        s.commit()


def current(field, fallback_wind_deg: float | None = None) -> Current:
    """What is on the air at this aerodrome, or what it would be if anyone were.

    `field` is a `Field_`, not a name, because the fallback needs to compute a
    runway and only the field knows its own ends. Passing a string here would
    mean the caller looking the field up first, which is one more place to get
    the spelling wrong.

    NEVER RAISES ON A DEAD DATABASE. A controller who cannot reach Postgres
    still has to clear an aeroplane to taxi, and a runway computed from the
    wind is a far better answer than an exception on the radio.
    """
    try:
        with db.session() as s:
            row = s.get(Atis, field.name)
            if row is not None:
                _age = None
                if row.recorded_at is not None:
                    _at = row.recorded_at
                    if _at.tzinfo is None:
                        _at = _at.replace(tzinfo=UTC)
                    _age = (datetime.now(UTC) - _at).total_seconds()
                return Current(field=field.name, letter=row.letter,
                               age_sec=_age,
                               runway=int(row.runway), text=row.text or "",
                               wind_from_deg=row.wind_from_deg,
                               wind_kt=row.wind_kt, on_the_air=True)
    except Exception:
        # Falls through to the computed answer, deliberately and silently on
        # the radio -- but see `atis.serve`, which is where a failure to
        # publish should be noisy. A read is a poor place to raise an alarm.
        pass
    return Current(field=field.name, letter=None,
                   runway=field.runway_in_use(fallback_wind_deg),
                   on_the_air=False)


def runway_in_use(field, fallback_wind_deg: float | None = None) -> int:
    """The active runway, from the broadcast when there is one.

    The one call a controller makes. It exists so that `current().runway`
    is not spelled out at every site that wants a runway -- which is how the
    second computation got in last time.
    """
    return current(field, fallback_wind_deg).runway
