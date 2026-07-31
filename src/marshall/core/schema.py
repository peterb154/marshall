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



# WHAT `atc` ADDS is in `atc/models.py`: flight, flight_member, clearance,
# identity. Shared tables live here, domain tables live with their domain --
# and the association between a track and a flight belongs to ATC, because ATC
# is what asserts it. A foreign key from `track` to `flight` would point core at
# a domain, which is the layering upside down. See docs/SCHEMA.md.
