"""The SHARED tables. One file you can read to know what this system stores.

    "I'm not writing this code, you are. But it would make it easier for me to
     comprehend and catch bugs in the IDE"

Which is the whole reason this file exists, and it is a better reason than
performance. Raw SQL in Python is opaque to an editor: no autocomplete, no
navigation, no type checking, and a mistyped column name is a runtime error
discovered in a sortie rather than a red squiggle discovered while reading. A
declarative model is a thing a person can open and understand in one sitting.

WHAT IT IS NOT. These models do not own the schema -- the numbered files in
`migrations/` still do, because they carry the reasoning for every column and
they are how a running database is changed safely. This file MIRRORS them, and
`tests/test_models.py` fails if the two ever drift. A model that quietly
disagrees with the database is worse than no model, because it looks
authoritative in the IDE while being wrong at runtime.

THE CONSTRAINTS ARE THE POINT, not decoration. `flights_track` -- one row per
aeroplane per mission -- is a rule this project hand-wrote in Python on 31 July
after a misheard word put one Mustang on the board twice and the separation
engine began sequencing him against himself. The index had been there since
migration 012, enforcing it correctly, and was never consulted because the
board lived in a dict. Written down here so the next person sees the rule
before writing the bug.
"""

from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (Boolean, DateTime, Float, Integer,
                        Text, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Track(Base):
    """One unit the sim currently has, wherever it is. THE SCOPE.

    Written by the position stream and reaped by `gone`, a mission reset, or the
    reconciliation sweep. NOT by a clock: a row used to expire fifteen seconds
    after it was last written, which meant a parked aeroplane -- one that never
    moves and therefore never updates -- vanished off the scope while a pilot
    sat in it. See `tools/tracks.py` for the whole argument.
    """

    __tablename__ = "tracks"

    # THE SIM'S UNIT NAME. Primary key because it is the sim's own identifier
    # and the only name in this system nobody has to say out loud.
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    # WHAT THE PICTURE PRINTS -- the player's name for a manned unit. Different
    # from `name`, and conflating the two severed the identity chain once
    # already: `unit_for_radio("Sockeye")` matched nothing when it was fed the
    # slot name "Viper 1-4".
    label: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    coalition: Mapped[int | None] = mapped_column(Integer)
    geog: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326))
    alt_ft: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    speed_kt: Mapped[float | None] = mapped_column(Float)
    player: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    # IS IT FLYING? The sim's own answer, from `Unit.inAir()` on the sweep and
    # from land/takeoff events the moment they happen. NULL means nobody has
    # asked yet, which is a third answer and not a synonym for airborne.
    #
    # It replaced a dict in another module built from land/takeoff events alone
    # -- blank for anything that spawned parked, because no `land` had ever
    # fired for it, and lost outright on every restart.
    in_air: Mapped[bool | None] = mapped_column(Boolean)
    # WHEN THE POSITION WAS LAST CONFIRMED. A freshness stamp for the POSITION,
    # never a test of whether the unit exists -- that distinction is the bug
    # this column used to cause.
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())



class Bullseye(Base):
    """The sim's own bullseye, per coalition. Written by `feed`.

    Every pilot's HSI is referenced to it, which is why it is asked for rather
    than invented -- a reference nobody in a cockpit can see is no reference.

    IT WAS A MODULE DICT, cached "because a mission change restarts this
    process". True when written; false since the mission reset stopped needing a
    restart, at which point the cache would have served the previous map's
    bullseye with no way to tell. Per mission, and wiped with everything flown.
    """

    __tablename__ = "bullseye"

    coalition: Mapped[str] = mapped_column(Text, primary_key=True)   # red | blue
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


# WHAT `atc` ADDS is in `atc/models.py`: flight, flight_member, clearance,
# identity. Shared tables live here, domain tables live with their domain --
# and the association between a track and a flight belongs to ATC, because ATC
# is what asserts it. A foreign key from `track` to `flight` would point core at
# a domain, which is the layering upside down. See docs/SCHEMA.md.


class Atis(Base):
    """One aerodrome's current broadcast. THE SOURCE OF TRUTH FOR THE RUNWAY.

        "Atis should probably determine the active runway. Controllers should
         query the db for that info. One source of truth for that."

    Which corrects a fault that had already appeared twice in this table's
    absence: `Field_.runway_in_use()` is a pure function of the wind, so ATIS
    computed it and the ground controller computed it AGAIN when issuing taxi.
    Two computations of one fact, and they agree only for as long as they are
    reading the same wind at the same instant. The moment the weather shifts
    between the recording and the taxi clearance, the broadcast says one runway
    and Ground says the other -- both correct, both defensible, and a pilot
    lined up on the wrong strip.

    So the wind is a measurement, the runway is a DECISION, and a decision has
    one author. ATIS makes it, writes it here, and everybody else reads it.
    That is also how a real aerodrome works: the runway in use is whatever the
    ATIS says it is until a controller changes it and re-records.

    A field with no row has no ATIS. Callers fall back to computing it, which
    is right for an aerodrome nobody broadcasts from, and is not silent -- see
    `atis.current`.
    """

    __tablename__ = "atis"

    # The aerodrome's name, as `Field_.name` and `Station.field` spell it. That
    # string is already the join between a controller and his airport; making
    # it the key here means no fourth spelling of "Kobuleti".
    field: Mapped[str] = mapped_column(Text, primary_key=True)
    # THE INFORMATION LETTER. Alpha, Bravo... and it is a version number a
    # pilot says back, which is the only reason it exists.
    letter: Mapped[str] = mapped_column(Text)
    # THE DECISION. Two digits, as painted on the runway -- not a heading, and
    # not derived from one: see `Field_.ends` on why 124 magnetic is "13".
    runway: Mapped[int] = mapped_column(Integer)
    # The words, kept so the loop and `/diag` read the same recording rather
    # than two renderings of the same weather.
    text: Mapped[str] = mapped_column(Text)
    # The observation behind it, so a controller can answer "say the wind"
    # without a second trip to the sim, and so `/diag` can show WHY the runway
    # is what it is.
    wind_from_deg: Mapped[int | None] = mapped_column(Integer)
    wind_kt: Mapped[int | None] = mapped_column(Integer)
    visibility_m: Mapped[int | None] = mapped_column(Integer)
    sky: Mapped[str | None] = mapped_column(Text)
    # FEET ABOVE THE FIELD, and the column name says so because the sim's own
    # number is metres above SEA LEVEL and the two have been confused before.
    ceiling_ft_agl: Mapped[int | None] = mapped_column(Integer)
    temp_c: Mapped[int | None] = mapped_column(Integer)
    dewpoint_c: Mapped[int | None] = mapped_column(Integer)
    qnh_inhg: Mapped[float | None] = mapped_column(Float)
    qfe_inhg: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
