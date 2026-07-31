"""The world, as rows. One file you can read to know what this system stores.

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
from sqlalchemy import (BigInteger, Boolean, DateTime, Float, Index, Integer,
                        Text, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Flight(Base):
    """One entity a controller is working. THE BOARD.

    Usually one aeroplane; while a formation is together it is one row with
    `lead_of` set, holding one level and answering to one clearance -- which is
    what a controller actually does, and why the separation logic needs no idea
    that formations exist.

    THIS IS THE BOARD, and for a long time it was only a copy of one. The bridge
    POSTed to `/flights/bind` and `/agree` and never read a row back, so the
    real board lived in a dict in one process: lost on restart, invisible to
    anything else, and free to disagree with this table indefinitely. It did --
    eight live-looking rows survived from missions that had ended days earlier.
    """

    __tablename__ = "flights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # WHICH WORLD THIS ROW BELONGS TO. Everything starts over when the mission
    # does, so a row can never outlive the world it describes -- see
    # `tools.tracks.clear_all` and the mission_start/mission_end handling.
    mission: Mapped[str] = mapped_column(Text, nullable=False,
                                         server_default="default")

    # --- who ----------------------------------------------------------------
    # WHAT THE CONTROLLER CALLS HIM: a person's handle, or a flight's name.
    # Never a member designation, and never a word off the radio -- see #48.
    callsign: Mapped[str | None] = mapped_column(Text)
    # THE SIM'S OWN NAME FOR THE AEROPLANE. The one identifier in this row that
    # no transcript can reach, which is why the unique index below is on this
    # and not on the callsign.
    track_name: Mapped[str | None] = mapped_column(Text)
    # THE RADIO. Free on every transmission, impossible to mis-hear, and the
    # strongest link in the identity chain.
    srs_guid: Mapped[str | None] = mapped_column(Text)
    srs_name: Mapped[str | None] = mapped_column(Text)

    # --- what he wants, and who has him -------------------------------------
    # WHAT HE SAID HE IS HERE FOR. Blank until a controller asks, and the blank
    # is the useful part: it means nobody has established intentions, which is
    # the first thing a controller is supposed to do.
    intent: Mapped[str | None] = mapped_column(Text)
    destination: Mapped[str | None] = mapped_column(Text)
    # THE STATION THAT OWNS HIM -- "Batumi Approach", never "approach". A role
    # cannot express ownership the moment there are two aerodromes, because
    # Batumi Approach and Kobuleti Approach are both `approach`.
    controller: Mapped[str | None] = mapped_column(Text)
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- what has been agreed ------------------------------------------------
    procedure: Mapped[str | None] = mapped_column(Text)
    runway: Mapped[str | None] = mapped_column(Text)
    # WHERE THE SEPARATION MACHINE HAS GOT TO: unknown, enroute, holding,
    # approach, missed, landed. Distinct from `intent` (what he asked for) and
    # from the sim's own account of what he is doing. Three facts, three
    # authorities, and collapsing them is how an observation comes to overwrite
    # something a pilot actually said.
    cleared: Mapped[str] = mapped_column(Text, nullable=False,
                                         server_default="unknown")
    assigned_ft: Mapped[int | None] = mapped_column(Integer)
    assigned_hdg: Mapped[int | None] = mapped_column(Integer)
    sequence_no: Mapped[int | None] = mapped_column(Integer)
    missed_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                              server_default="0")
    promised: Mapped[str | None] = mapped_column(Text)
    promised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- formation ------------------------------------------------------------
    # THE FLIGHT THIS ROW LEADS, if any. A flight is one entity to the engine.
    lead_of: Mapped[str | None] = mapped_column(Text)
    claimed_size: Mapped[int] = mapped_column(Integer, nullable=False,
                                              server_default="1")

    # --- the strip ------------------------------------------------------------
    flight_plan: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(Text)
    cruise_ft: Mapped[int | None] = mapped_column(Integer)
    clearance_ack: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # ONE AEROPLANE, ONE ROW. The rule the storage layer can enforce and
        # Python keeps failing to: on 31 July a pilot said "established ON the
        # final approach course", a parser took "on" for a flight name, and the
        # in-memory board opened a second entry against the same track. Two
        # entries are what makes the separation engine engage, so a single ship
        # became a sequencing problem between a man and himself. This index
        # would have refused it outright.
        Index("flights_track", "mission", "track_name", unique=True,
              postgresql_where=track_name.isnot(None)),
        # ONE RADIO, ONE AEROPLANE, for the same reason.
        Index("flights_srs_guid", "mission", "srs_guid", unique=True,
              postgresql_where=srs_guid.isnot(None)),
        Index("flights_callsign", "mission", "callsign"),
        Index("flights_cleared", "mission", "cleared"),
        Index("flights_ctrl", "mission", "controller"),
        Index("flights_lead", "mission", "lead_of"),
        Index("flights_plan", "mission", "flight_plan"),
    )


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


class Contact(Base):
    """A callsign, tied to a track, by evidence rather than by a claim.

    The identity graph: what the controller decided somebody was, and on what
    grounds. Kept so a sortie can be scored afterwards -- "Pony 1-1" in a log
    looks identical whether radar put it there or a transcript did, and those
    are the two cases worth telling apart.
    """

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    callsign: Mapped[str] = mapped_column(Text, nullable=False)
    track_label: Mapped[str] = mapped_column(Text, nullable=False)
    srs_name: Mapped[str | None] = mapped_column(Text)
    identified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


# EVERYTHING THAT IS WIPED WHEN THE WORLD RESTARTS.
#
#     "If the mission restarts the board should be wiped. Everything --
#      everything starts over."
#
# Named here rather than spelled out at the call site so that adding a table
# and forgetting to clear it is a visible omission in one place, instead of a
# row that survives a mission and is discovered days later still holding an
# aeroplane at six thousand feet.
PER_MISSION = (Flight, Track, Contact)
