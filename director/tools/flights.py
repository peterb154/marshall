"""The one aircraft state: who he is, what he wants, what he is doing.

Read the header of migrations/004_flights.sql for why this exists. The short
version: three components each kept their own idea of what was happening to an
aeroplane and they contradicted each other on the radio, in front of a pilot.

The rule this module enforces, and the reason every function here is small:

    it stores what was AGREED. The scope stores what is TRUE.

So there is no way to write a position through this module, and there never
should be. Position comes from `tracks`, joined in the `flight_state` view, and
the gap between the two -- assigned 8,000, observed 7,600 -- is the useful part.

Identity is the other job. One aeroplane has three names that never match: a
callsign a controller hears, a unit name the sim knows, and a radio GUID that
keyed the mic. `bind` is how they get attached to one row, and it is written to
be safe to call repeatedly with partial information, because that is how
identity actually arrives -- a voice before a track, a track before a voice, a
filed plan before either.
"""

from __future__ import annotations

import logging

from strands_pg._pool import get_pool

log = logging.getLogger(__name__)

# Kept in step with phases.py on the bridge side. Duplicated deliberately: the
# director must be able to reject a phase it does not know without importing
# the ATC package, which lives in a different deployable.
PHASES = ("filed", "clearance", "taxi", "departure", "enroute", "tasked",
          "on_station", "rtb", "arrival", "holding", "approach", "missed",
          "landed", "unknown")

_FIELDS = ("callsign", "track_name", "srs_guid", "srs_name", "intent",
           "destination", "claimed_size", "controller", "procedure", "runway",
           "cleared", "assigned_ft", "assigned_hdg", "sequence_no",
           "missed_count", "promised", "promised_at", "lead_of", "flight_plan",
           "origin", "route", "cruise_ft", "clearance_ack")


def _row(r, cols) -> dict:
    return {c: v for c, v in zip(cols, r)}


def find(mission: str = "default", *, callsign: str | None = None,
         srs_guid: str | None = None, track_name: str | None = None) -> dict | None:
    """The row for this aeroplane, by whichever name we happen to have.

    Tried in order of how much the name is worth. The GUID is the anchor: it
    arrives free on every transmission and survives Whisper turning "Pony one
    one" into "Tony one one". The track is next -- one sim unit is one
    aeroplane. The callsign is last and is the least reliable of the three,
    which is exactly why it must not be the key.
    """
    where, args = [], []
    for col, val in (("srs_guid", srs_guid), ("track_name", track_name),
                     ("callsign", callsign)):
        if not val:
            continue
        with get_pool().connection() as c:
            cur = c.execute(
                f"SELECT * FROM flight_state WHERE mission = %s AND {col} = %s "
                "ORDER BY updated_at DESC LIMIT 1", (mission, val))
            r = cur.fetchone()
            if r:
                return _row(r, [d[0] for d in cur.description])
    return None


def bind(mission: str = "default", **names) -> dict:
    """Attach a name to an aeroplane, creating the row if this is the first one.

    Safe to call repeatedly with partial information, because that is how
    identity arrives: a voice with no track, a track with no voice, a plan with
    neither. Each call adds what it knows and never removes what it does not.

    The merge case matters and is easy to get wrong. A pilot calls and gets a
    row keyed on his radio; radar identifies him a minute later and we learn his
    track. That is the SAME aeroplane, and binding the track must not create a
    second row -- so a bind that would collide with an existing row folds into
    it rather than inserting.
    """
    known = {k: v for k, v in names.items() if k in _FIELDS and v is not None}
    if not known:
        raise ValueError("bind needs at least one name")

    # Fold together everything that turns out to be the same aeroplane.
    #
    # Identity arrives in pieces and out of order, so one aircraft can already
    # own two rows -- one created when a voice was heard, another when radar
    # named a track -- and binding the two names together is the moment they
    # are discovered to be one. Updating either row then collides with the
    # other's unique index, which is not a corner case: it happened on a live
    # sortie and every write for that pilot failed from then on.
    #
    # The oldest row wins because it has the history. The others give up what
    # they know and are deleted.
    rows = _all_matching(mission, known)
    row = _merge(rows) if len(rows) > 1 else (rows[0] if rows else None)
    with get_pool().connection() as c:
        if row is None:
            cols = ["mission"] + list(known)
            vals = [mission] + [known[k] for k in known]
            ph = ", ".join(["%s"] * len(cols))
            cur = c.execute(
                f"INSERT INTO flights ({', '.join(cols)}) VALUES ({ph}) "
                "RETURNING id", vals)
            fid = cur.fetchone()[0]
        else:
            fid = row["id"]
            sets = ", ".join(f"{k} = COALESCE(%s, {k})" for k in known)
            c.execute(f"UPDATE flights SET {sets}, updated_at = now() "
                      "WHERE id = %s", [known[k] for k in known] + [fid])
    return get(fid) or {}


def _all_matching(mission: str, known: dict) -> list[dict]:
    """Every row that any of these names points at, oldest first."""
    seen, out = set(), []
    for col in ("srs_guid", "track_name", "callsign"):
        val = known.get(col)
        if not val:
            continue
        with get_pool().connection() as c:
            cur = c.execute(
                f"SELECT * FROM flight_state WHERE mission = %s AND {col} = %s",
                (mission, val))
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                d = _row(r, cols)
                if d["id"] not in seen:
                    seen.add(d["id"])
                    out.append(d)
    out.sort(key=lambda d: d["id"])
    return out


def _merge(rows: list[dict]) -> dict:
    """Collapse several rows for one aeroplane into the oldest of them.

    Anything the survivor does not know, it takes from the others; anything it
    already knows, it keeps, because the earlier record is the one with the
    conversation behind it. The losers are deleted rather than blanked, since a
    row with every name stripped out is a ghost that the next lookup will
    happily create all over again.
    """
    keep, rest = rows[0], rows[1:]
    fill = {}
    for other in rest:
        for k in _FIELDS:
            if keep.get(k) in (None, "", 0) and other.get(k) not in (None, ""):
                fill.setdefault(k, other[k])
    with get_pool().connection() as c:
        for other in rest:
            c.execute("DELETE FROM flights WHERE id = %s", (other["id"],))
        if fill:
            sets = ", ".join(f"{k} = %s" for k in fill)
            c.execute(f"UPDATE flights SET {sets}, updated_at = now() "
                      "WHERE id = %s", list(fill.values()) + [keep["id"]])
    log.info("merged %d duplicate flight rows into %s", len(rest), keep["id"])
    return get(keep["id"]) or keep


def get(flight_id: int) -> dict | None:
    with get_pool().connection() as c:
        cur = c.execute("SELECT * FROM flight_state WHERE id = %s", (flight_id,))
        r = cur.fetchone()
        return _row(r, [d[0] for d in cur.description]) if r else None


def agree(flight_id: int, **fields) -> dict | None:
    """Record something that was AGREED. The only way state changes.

    Named for what it is. Every column it can touch is a thing a controller and
    a pilot settled between them -- a clearance, a level, a place in the queue,
    a promise to call back -- and none of it is observable from a radar scope.
    Anything the scope can answer has no business being written here.
    """
    known = {k: v for k, v in fields.items() if k in _FIELDS}
    if not known:
        return get(flight_id)
    if "cleared" in known and known["cleared"] not in PHASES:
        raise ValueError(f"unknown phase {known['cleared']!r}")
    sets = ", ".join(f"{k} = %s" for k in known)
    with get_pool().connection() as c:
        c.execute(f"UPDATE flights SET {sets}, updated_at = now() WHERE id = %s",
                  list(known.values()) + [flight_id])
    return get(flight_id)


def hand_off(flight_id: int, to_controller: str) -> dict | None:
    """Give him to the next controller, with everything we know attached.

    This is the point of the table. What Center learned -- where he is going,
    what he was cleared to, what level he was left at -- goes with him, so
    Approach does not start by interrogating a pilot who has already answered.
    """
    with get_pool().connection() as c:
        c.execute("UPDATE flights SET controller = %s, handed_off_at = now(), "
                  "updated_at = now() WHERE id = %s", (to_controller, flight_id))
    return get(flight_id)


def working(mission: str = "default", controller: str | None = None) -> list[dict]:
    """Everyone a controller currently has, in sequence order.

    Excludes the finished and the never-started, so it is the list a controller
    would actually have in front of him rather than everything the mission has
    ever seen.
    """
    sql = ("SELECT * FROM flight_state WHERE mission = %s "
           "AND cleared NOT IN ('landed', 'filed')")
    args: list = [mission]
    if controller:
        sql += " AND controller = %s"
        args.append(controller)
    sql += " ORDER BY sequence_no NULLS LAST, first_seen"
    with get_pool().connection() as c:
        cur = c.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [_row(r, cols) for r in cur.fetchall()]


def due_handoff(mission: str = "default") -> list[dict]:
    """Aircraft inside one controller's airspace while on another's frequency.

    A handoff is due when the two disagree -- which is the same shape as "you
    are four hundred feet below your assigned altitude", and replaces guessing
    at a distance from the field. Whether to act is the controller's judgement;
    this only says the question is worth asking.
    """
    with get_pool().connection() as c:
        cur = c.execute(
            "SELECT * FROM flight_airspace WHERE mission = %s "
            "AND should_be_with IS NOT NULL "
            "AND should_be_with IS DISTINCT FROM working_with", (mission,))
        cols = [d[0] for d in cur.description]
        return [_row(r, cols) for r in cur.fetchall()]


def clear_mission(mission: str = "default") -> int:
    """Forget everything. Called when a mission loads, because stale aircraft
    from the last sortie are worse than none -- they are a controller confidently
    sequencing aeroplanes that no longer exist."""
    with get_pool().connection() as c:
        cur = c.execute("DELETE FROM flights WHERE mission = %s", (mission,))
        return cur.rowcount
