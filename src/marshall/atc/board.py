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

WHY THIS IS `board` AND NOT `flights`. It was `director/tools/flights.py` until
#147 moved it out of the deployable, and `marshall/atc/flights.py` was already
taken by the in-memory ROSTER -- who is flying with whom, handles and flight
names, no database anywhere in it. Two modules called `flights` in one package
is the ambiguity this repo keeps paying for: the wrong answer is always
plausible. This is the `flights` TABLE, which `clearance.not_on_the_board` and
`docs/STATE.md` both already call the board.
"""

from __future__ import annotations

import logging

from marshall.core.db import pool as get_pool

log = logging.getLogger(__name__)

# Kept in step with `atc/phases.py`. Duplicated because the language brain's
# HTTP door had to reject a phase it did not know without importing the ATC
# package, which lived in a different deployable -- a reason that EXPIRED when
# #147 moved this module into `marshall.atc`, beside the list it copies. The
# duplication is now just duplication; collapsing it is a behaviour change and
# is not part of the move.
PHASES = ("filed", "clearance", "taxi", "departure", "enroute", "tasked",
          "on_station", "rtb", "arrival", "holding", "approach", "missed",
          "landed", "unknown")

_FIELDS = ("sortie_phase", "on_visual", "approaches_flown", "atis_letter",
           # HAS HE LEFT THE GROUND THIS SORTIE. A latch, and durable for the
           # same reason `sortie_phase` is: the phase cannot answer it for
           # `departure`, which straddles the ground and the air, so a restart
           # that forgot it would leave an aeroplane unable to be recognised
           # as landed. See migration 035. [#178]
           "has_been_airborne",
           # ...AND WHETHER HE IS OFF THE RUNWAY, which no rung can answer.
           # `sortie_phase` moves to `taxi_in` on the HANDOFF to Ground while
           # he is still rolling, so occupancy needs its own fact. Durable for
           # the same reason: a restart that forgot it would free a runway
           # somebody is standing on. See migration 038. [#170]
           "runway_vacated",
           # ...AND WHETHER HE IS BEING FOLLOWED. On the aeroplane so a handoff
           # carries it, and durable so a restart does not drop a service a
           # pilot is relying on. See migration 040. [#217]
           "following", "following_to",
           "callsign", "track_name", "srs_guid", "srs_name", "intent",
           "destination", "claimed_size", "controller", "procedure", "runway",
           "cleared", "assigned_ft", "assigned_hdg", "sequence_no",
           "missed_count", "promised", "promised_at", "lead_of", "flight_plan",
           # THE SPOKEN LABEL, beside the plan's key. The key is
           # "362nd-kobuleti-batumi"; the label is "Domino", which is the word
           # the pilot said and the word a controller would use back. A strip
           # carrying only the key can either read a database row aloud or say
           # nothing, and it said nothing.
           "flight_plan_label",
           # NO `cruise_ft`. A plan has a level per leg and no cruise; #192
           # dropped the column. The level he is HELD to is `assigned_ft`,
           # written when the clearance is issued.
           "origin", "route", "clearance_ack")


def _row(r, cols) -> dict:
    return {c: v for c, v in zip(cols, r)}


def find(mission: str | None = "default", *, callsign: str | None = None,
         srs_guid: str | None = None, track_name: str | None = None,
         srs_name: str | None = None) -> dict | None:
    """The row for this aeroplane, by whichever name we happen to have.

    Tried in order of how much the name is worth. The GUID is the anchor: it
    arrives free on every transmission and survives Whisper turning "Pony one
    one" into "Tony one one". The track is next -- one sim unit is one
    aeroplane. The callsign is next and is unreliable, which is exactly why it
    must not be the anchor. The SRS NAME is last and weakest -- and is still far
    better than not matching at all, which used to mean minting a new row for
    every transmission from a pilot we had not yet tied to a track.
    """
    # A NAME IS MATCHED WITHOUT REGARD TO CASE; AN IDENTIFIER IS NOT.
    #
    # `srs_guid` and `track_name` are the sim's own strings and must match
    # exactly. `callsign` and `srs_name` are NAMES -- written by whoever bound
    # the row, spoken by a pilot, and title-cased on the way through the agent.
    # The row is bound "sockeye"; the controller asks for "Sockeye"; the
    # comparison was `=` and missed.
    #
    # 28 August, live, with a pilot on the ramp. `clearance_state` answered
    #
    #     "Sockeye IS NOT ON THE BOARD ... On the board: sockeye."
    #
    # -- printing the row it had just failed to match, in the same breath. So
    # `request_clearance` could not clear him, nothing could tell him why, and
    # the controller filled the gap with "you are already cleared on the
    # BatumiTest flight plan" while `assigned_plans` was empty. He could not
    # taxi and could not be cleared, and the only evidence was a capital S.
    _EXACT = ("srs_guid", "track_name")
    for col, val in (("srs_guid", srs_guid), ("track_name", track_name),
                     ("callsign", callsign), ("srs_name", srs_name)):
        if not val:
            continue
        where = (f"{col} = %s" if col in _EXACT else f"lower({col}) = lower(%s)")
        # `mission=None` MEANS ANY MISSION, and it exists because not every
        # caller has one. A tool that runs inside the agent container reads
        # `MARSHALL_MISSION` from an environment that does not set it -- the
        # mission arrives per REQUEST there -- so `vector` looked up a pilot's
        # own steerpoints under the mission "default", found no flight, and
        # told him it had no fix for a waypoint sitting on his own strip. The
        # sim's unit name is unique across a running world, so dropping the
        # filter narrows nothing that matters and the newest row still wins.
        with get_pool().connection() as c:
            cur = (c.execute(
                f"SELECT * FROM flight_state WHERE {where} "
                "ORDER BY updated_at DESC LIMIT 1", (val,))
                if mission is None else
                c.execute(
                f"SELECT * FROM flight_state WHERE mission = %s AND {where} "
                "ORDER BY updated_at DESC LIMIT 1", (mission, val)))
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
            cols = ["mission", *known]
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
    # `srs_name` IS A KEY, and leaving it out minted a row per transmission.
    #
    # One SRS client is one person, exactly as one track is one aeroplane. It is
    # weaker than a GUID -- a name can be changed, two people can pick the same
    # one -- and it is enormously stronger than the alternative, which was to
    # find nothing and INSERT. A pilot whose first calls carry only an SRS name
    # got a fresh row every time he spoke, so every `agree` wrote into a row
    # that identified nobody and the next transmission abandoned it. Three rows
    # in thirty seconds, on the sortie that produced docs/STATE.md.
    #
    # Last, after the three that are stronger, so a GUID or a track still wins
    # when we have one.
    for col in ("srs_guid", "track_name", "callsign", "srs_name"):
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


def _unset(v) -> bool:
    """Does this column hold NO ANSWER, as opposed to a false or zero one?

    "I was not told" and "the answer is no" are two different sentences and only
    one of them is usually true. NULL is the first; so is the empty string, which
    is how every text column on this table spells unset. `False` and `0` are the
    second, and they are answers somebody paid for.

    THIS USED TO BE `v in (None, "", 0)` AND IT COST THE DISTINCTION, because
    `False in (None, "", 0)` is True in Python -- `False == 0`. So a merge could
    overwrite:

        on_visual = False        he is NOT flying it himself, keep talking him down
        approaches_flown = 0     he has flown none
        missed_count = 0         he has gone around none
        assigned_ft = 0          nothing assigned
        sequence_no = 0          not in the sequence

    `on_visual` is the one that reaches a pilot. It means "he has the field and
    is flying it himself, the talk-down must stop", and a merge that turned a
    deliberate False into the loser's True stopped a talk-down for a man who
    never said he had anything in sight. The schema is honest about these
    (`NOT NULL DEFAULT false`); this is where the honesty was thrown away, on the
    identity path, at the moment two rows are discovered to be one aeroplane.
    [#153]
    """
    return v is None or v == ""


def _merge(rows: list[dict]) -> dict:
    """Collapse several rows for one aeroplane into the oldest of them.

    Anything the survivor WAS NOT TOLD, it takes from the others; anything it
    already knows -- including a no and including a nought -- it keeps, because
    the earlier record is the one with the conversation behind it. The losers are
    deleted rather than blanked, since a row with every name stripped out is a
    ghost that the next lookup will happily create all over again.

    See `_unset` for the difference between an empty column and a false one,
    which this got wrong for as long as it existed.
    """
    keep, rest = rows[0], rows[1:]
    fill = {}
    for other in rest:
        for k in _FIELDS:
            # BOTH SIDES ASK THE SAME QUESTION. The donor test was already
            # `not in (None, "")` and therefore already right; they are one
            # function now so they cannot come apart later.
            if _unset(keep.get(k)) and not _unset(other.get(k)):
                fill.setdefault(k, other[k])
    with get_pool().connection() as c:
        for other in rest:
            c.execute("DELETE FROM flights WHERE id = %s", (other["id"],))
        if fill:
            sets = ", ".join(f"{k} = %s" for k in fill)
            c.execute(f"UPDATE flights SET {sets}, updated_at = now() "
                      "WHERE id = %s", [*fill.values(), keep["id"]])
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
                  [*known.values(), flight_id])
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


def save_board(mission: str, rows: list[dict]) -> dict:
    """Make the table say exactly what the separation engine believes.

    THE TABLE WAS A WRITE-ONLY MIRROR. `marshall-atc` POSTed `bind` and `agree` and
    never read a row back, so the real board lived in a dict in one process:
    lost on restart, invisible to anything else, and free to diverge. It did --
    eight live-looking rows survived from missions that had ended days earlier,
    one of them the ghost "On" from a misheard word, another holding an
    aeroplane at six thousand feet since the 28th.

    UPSERT WHAT IS THERE, DELETE WHAT IS NOT, in one transaction. Writing only
    the rows that changed is how a mirror drifts: the row nobody thought to
    update is exactly the row that is wrong, and it is indistinguishable from a
    row that is right.

    THE UNIQUE INDEX IS THE POINT, not an inconvenience to work around. One
    aeroplane per track per mission has been enforced here since migration 012
    and was never consulted, while Python grew its own version of the same rule
    and let a Mustang onto the board twice. A conflict on `flights_track` is the
    database refusing something that should never have been asked, so it is
    reported rather than swallowed.
    """
    keep = [r for r in rows if r.get("callsign")]
    names = [r["callsign"] for r in keep]
    with get_pool().connection() as c:
        # GONE FIRST. An aeroplane released from the board has to leave the
        # table before the upserts, or a callsign that changed hands this turn
        # would collide with the row it is replacing.
        if names:
            c.execute("DELETE FROM flights WHERE mission = %s "
                      "AND NOT (callsign = ANY(%s))", (mission, names))
        else:
            c.execute("DELETE FROM flights WHERE mission = %s", (mission,))
        for r in keep:
            c.execute(
                """
                INSERT INTO flights (mission, callsign, track_name, controller,
                                     intent, cleared, assigned_ft, missed_count,
                                     lead_of, claimed_size, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (mission, callsign) DO UPDATE SET
                    track_name   = EXCLUDED.track_name,
                    controller   = EXCLUDED.controller,
                    intent       = EXCLUDED.intent,
                    cleared      = EXCLUDED.cleared,
                    assigned_ft  = EXCLUDED.assigned_ft,
                    missed_count = EXCLUDED.missed_count,
                    lead_of      = EXCLUDED.lead_of,
                    claimed_size = EXCLUDED.claimed_size,
                    updated_at   = now()
                """,
                (mission, r["callsign"], r.get("track") or None,
                 r.get("owner") or None, r.get("intent") or None,
                 r.get("cleared") or "unknown", r.get("assigned_ft"),
                 int(r.get("missed_count") or 0), r.get("lead_of") or None,
                 int(r.get("size") or 1)))
    return {"saved": len(keep)}


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


def callsigns(mission: str = "default") -> list[str]:
    """Every callsign this mission has actually bound, in the order seen.

    THE CLOSED SET, and it exists to be said out loud. A callsign is somebody's
    own name on the radio or a flight that was created; it is never a word a
    pilot picked in the air. So when a lookup misses, the useful answer is not
    "no" but "no, and here is everything that IS" -- which turns a two-minute
    hunt for a missing flight plan into one transmission.
    """
    with get_pool().connection() as c:
        rows = c.execute(
            "SELECT DISTINCT ON (callsign) callsign FROM flight_state "
            "WHERE mission = %s AND callsign IS NOT NULL AND callsign <> '' "
            "ORDER BY callsign", (mission,)).fetchall()
    return [r[0] for r in rows]


def forget(flight_id: int) -> int:
    """One row, gone, with whatever hangs off it."""
    with get_pool().connection() as c:
        c.execute("DELETE FROM flight_member WHERE flight_id = %s", (flight_id,))
        c.execute("DELETE FROM assigned_plans WHERE flight_id = %s", (flight_id,))
        cur = c.execute("DELETE FROM flights WHERE id = %s", (flight_id,))
        return cur.rowcount


def expire(mission: str = "default", older_than_sec: float = 900.0) -> int:
    """Rows nobody has heard from and radar cannot see. The `tracks` bargain.

    A flight is alive if it has been UPDATED recently -- every transmission
    touches `updated_at` -- or if a radar track still carries its name. Neither
    is a guess: one is a fact about the radio, the other about the sim.

    This is what makes `DELETE /flights` a debugging convenience rather than
    load-bearing. Nothing should ever have to be cleaned by hand.
    """

    with get_pool().connection() as c:
        cur = c.execute(
            "DELETE FROM flights f WHERE f.mission = %s "
            "  AND f.updated_at < now() - (%s || ' seconds')::interval "
            "  AND NOT EXISTS (SELECT 1 FROM tracks t "
            "                  WHERE t.name = f.track_name)",
            (mission, str(int(older_than_sec))))
        return cur.rowcount


def clear_mission(mission: str = "default") -> int:
    """Forget everything. Called when a mission loads, because stale aircraft
    from the last sortie are worse than none -- they are a controller confidently
    sequencing aeroplanes that no longer exist."""
    with get_pool().connection() as c:
        cur = c.execute("DELETE FROM flights WHERE mission = %s", (mission,))
        return cur.rowcount
