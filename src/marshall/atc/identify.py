"""Radar identification, persisted in Postgres — the live map of who is who.

Three identities per aircraft never match: the SRS transmitter ("Sockeye"), the
self-proclaimed callsign ("Pony 1-1"), and the radar track ("Enfield11"). The
controller earns the link the real way — correlate a POSITION REPORT to one blip —
and this stores that link so the radar picture can be tagged and it survives an
agent restart.

Nothing here is permanent. Pilots jump slots, a track gets a new pilot, a human
disconnects and another takes the jet. So a positive identification SUPERSEDES:
binding Pony 1-1 to Enfield12 clears any prior row for that callsign AND any prior
row for that track, then writes the new one. Latest positive ID wins — never two
truths for one callsign or one blip.

The rule the agent must honour (rules.md): identify ONLY on an unambiguous single
match; on no match or two candidates, don't — "not radar identified, continue".
"""

from __future__ import annotations

import logging
import re

from marshall.core.db import pool as get_pool

try:
    from strands import tool
except ImportError:
    def tool(fn):
        return fn

log = logging.getLogger(__name__)
_ready = False


def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    with get_pool().connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id            BIGSERIAL PRIMARY KEY,
                session_id    TEXT NOT NULL,
                callsign      TEXT NOT NULL,      -- self-proclaimed, "Pony 1-1"
                track_label   TEXT NOT NULL,      -- radar label, "Enfield11"
                srs_name      TEXT,               -- transmitter identity, "Sockeye"
                identified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (session_id, callsign),
                UNIQUE (session_id, track_label)
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS contacts_session ON contacts(session_id)")
    _ready = True


def bind(session_id: str, callsign: str, track_label: str,
         srs_name: str | None = None) -> None:
    """Positive identification: supersede any prior binding for this callsign or
    this track, then record the new one. Latest positive ID wins."""
    _ensure_table()
    with get_pool().connection() as conn:
        # Clear both directions of conflict so a re-slot or a new pilot can't
        # leave a stale association behind.
        conn.execute(
            "DELETE FROM contacts WHERE session_id=%s AND (callsign=%s OR track_label=%s)",
            (session_id, callsign, track_label))
        conn.execute(
            "INSERT INTO contacts (session_id, callsign, track_label, srs_name) "
            "VALUES (%s, %s, %s, %s)",
            (session_id, callsign, track_label, srs_name))


def unbind(session_id: str, callsign: str) -> None:
    _ensure_table()
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM contacts WHERE session_id=%s AND callsign=%s",
                     (session_id, callsign))


# HOW LONG A POSITIVE IDENTIFICATION IS WORTH ANYTHING.
#
# A radar tag is a statement about an aeroplane that is flying NOW. It survived
# twelve hours and a mission restart: Hoover took an F-16 slot, called himself
# Falcon 1-1, and the scope still tagged his track "Hammer 1-1" from a Jug
# sortie the previous morning. The geometry then could not match his callsign to
# any track, so it fell silent, and the model improvised an entire approach --
# two of them -- while the pilot wondered why he was being flown into the sea.
#
#     "initially he was running on stale data.. that shouldn't be possible."
#
# Quite. A session's identifications are good for one sortie. Two hours is
# longer than any approach here and far shorter than the gap between them, and
# an expired binding costs one transmission to re-establish -- the controller
# asks who is calling, which he should be willing to do anyway.
BINDING_TTL_SEC = 2 * 60 * 60


def bindings_for(session_id: str) -> dict[str, str]:
    """Current {track_label: callsign} for this session, for radar annotation.

    Expired bindings are not returned AND are deleted, so a stale tag cannot
    come back the moment somebody re-reads the table.
    """
    try:
        _ensure_table()
        with get_pool().connection() as conn:
            conn.execute(
                "DELETE FROM contacts WHERE session_id=%s "
                "AND identified_at < now() - make_interval(secs => %s)",
                (session_id, BINDING_TTL_SEC))
            rows = conn.execute(
                "SELECT track_label, callsign FROM contacts WHERE session_id=%s",
                (session_id,)).fetchall()
        return {label: cs for label, cs in rows}
    except Exception as e:                       # radar must never fail on the DB
        log.warning("bindings_for failed: %s", e)
        return {}


# "Pony 1" is a FORMATION. "Pony 1-1" is an aeroplane. Only one of those is a
# thing a radar track can be.
_MEMBER = re.compile(r"^\s*[A-Za-z][A-Za-z' -]{1,}\s+\d+\s*-\s*\d+\s*$")


def is_one_aeroplane(callsign: str) -> bool:
    return bool(_MEMBER.match(callsign or ""))


def identify_tools(session_id: str) -> list:

    @tool
    def identify(callsign: str, contact: str, srs_name: str = "") -> str:
        """Correlate a voice callsign to a radar contact, AFTER his position
        report unambiguously matches exactly one track. `callsign` is what he
        calls himself ("Pony 1-1"); `contact` is the matching track's radar label
        ("Enfield11"); `srs_name` is his SRS transmitter identity if you have it.
        Do NOT call this on no match or more than one match — leave him
        unidentified. This SUPERSEDES any earlier binding for this callsign or
        this track, so use it freely to re-identify when a pilot changes jets or
        a track changes pilots — the latest positive ID is the truth."""
        # A FLIGHT is not a contact. Binding "Pony 1" to a track says a
        # formation is one aeroplane, and it then annotates the radar picture
        # with a name that outranks everything else the controller is told: a
        # wingman who said "Pony one two, checking in" was answered as "Pony one
        # one" and then as "Pony one two" on his leader's call, because the
        # scope kept asserting the flight name and the model believed the scope.
        #
        # While they are together the picture already says "IN FORMATION with"
        # and needs no help. Once broken up they are members and bind normally.
        # A FLIGHT name may only be bound to a track that is ALONE.
        #
        # "Pony 1" is one aeroplane when it is alone and a formation when it is
        # not, and the difference is not in the callsign -- it is out of the
        # window. Binding the flight name to a track that has a wingman on it
        # says a formation is one aircraft, and it then annotates the radar with
        # a name that outranks everything else the controller is told: a wingman
        # who said "Pony one two, checking in" was answered as "Pony one one",
        # because the scope kept asserting the flight name and the model
        # believed the scope over the radio it came from.
        #
        # Refusing outright was tried first and is worse -- it would leave a
        # single ship called "Hoover 1" permanently unidentifiable, and an
        # unidentified aircraft never gets talked down.
        from marshall.feed.tracks import in_formation
        if not is_one_aeroplane(callsign) and in_formation(contact):
            return (f"'{callsign}' is a flight and '{contact}' is flying in "
                    f"formation, so that name covers more than one track. "
                    f"Identify the members individually once they separate; "
                    f"while they are together the picture already shows it.")
        try:
            bind(session_id, callsign, contact, srs_name or None)
        except Exception as e:
            return f"Could not record identification: {e}"
        return f"Radar identified: {callsign} is the contact '{contact}'."

    @tool
    def drop_identification(callsign: str) -> str:
        """Undo a correlation (he landed, or it turned out wrong). Removes any
        track currently bound to this callsign."""
        try:
            unbind(session_id, callsign)
        except Exception as e:
            return f"Could not drop identification: {e}"
        return f"Dropped radar identification for {callsign}."

    return [identify, drop_identification]
