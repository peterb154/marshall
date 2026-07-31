"""The tables ATC owns. A flight is an ATC concept; nobody else needs it.

`feed` knows tracks. `traffic` thinks in sim groups -- if ATC controls an AI
four-ship, ATC forms a flight over it and traffic never needs the notion. The
kneeboard renders rows without knowing when a flight forms. Only ATC decides
what a flight IS, so these live here and `core.schema` holds what everyone
shares.

THE ASSOCIATION BELONGS TO WHOEVER ASSERTS IT. `flight_member` is here rather
than as a `flight_id` column on `core.schema.Track`, which was the first draft
and was elegant -- `IS NULL` would have meant "untracked". It inverts the
layering: `track` is core, `flight` is atc, and the key must sit on `track`
because that is the many side, so it cannot simply be turned round. Untracked
becomes a LEFT JOIN instead, which is the price of the arrow pointing the right
way -- and it is still a fact the schema holds rather than one `publish_state`
derives, which was the point. That derivation put one aeroplane on the board AND
in the untracked list on 31 July.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from marshall.core.schema import Base

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



class FlightMember(Base):
    """Which tracks make up a flight.

    A formation is ONE entity to the separation engine -- one level, one
    clearance, one place in the letdown -- and this is the list of aeroplanes
    behind it. It replaces the `lead_of` text column, which named a flight in a
    string and could not be joined on.
    """

    __tablename__ = "flight_member"

    flight_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flights.id", ondelete="CASCADE"),
        primary_key=True)
    # NOT a foreign key to `tracks`, deliberately: a member can be named before
    # radar has the contact, and a flight losing its track must not lose its
    # member. The join is by name and may legitimately find nothing.
    track_name: Mapped[str] = mapped_column(Text, primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("flight_member_track", "track_name"),)


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


