"""What radar can see, read from the table rather than parsed out of English.

THE ROUND TRIP THIS REPLACES. The director rendered `tracks` into prose for the
model, and the bridge parsed that prose back into structs with regexes --
`_SCOPE_LINE`, `_FORMATION`, `_OTHER_SHIP`, `flatten_formation`, `_split_ships`.
A serialise-and-reparse of data that was structured when it left the database
and structured again when it arrived. Every formation bug this project has had
lived in that parser, including the one that deleted wingmen so no member of a
formation had a radar position at all.

The prose stays -- the model needs a picture in words -- but as a RENDERING at
the edge, never as an interchange format between our own components. The bridge
already drew it locally from `Scope.contacts`; this removes the last hop by
reading those contacts from Postgres instead of asking the director for them.

FORMATION CLUSTERING MOVED HERE TOO, and gained named arguments on the way. It
lived in the director and indexed its rows positionally --

    a_alt, a_hdg, a_nm, a_radial = a[3], a[4], a[6], a[7]

-- which its own comment records breaking twice as the row grew, each time as a
ValueError that fires ONLY when two contacts are compared. A single ship never
reaches that line, so every test with one aeroplane passed and the first two
aircraft on the scope would have lost the whole radar picture. Fields have names
now, and the row can grow without anybody counting.
"""

from __future__ import annotations

import math

from marshall.core import geo

# What counts as flying together. Four aeroplanes in close formation are four
# blips a mile apart at the same altitude on the same heading, and presenting
# them as four independent contacts is actively harmful: an ambiguous match must
# not be identified, so a four-ship could never be radar identified at all --
# the more aircraft in the formation, the less the controller can see it. A real
# controller reads that picture as ONE thing.
FORM_NM = 2.0
FORM_FT = 500
FORM_HDG = 20


def _cluster(contacts: list[dict], origin: tuple[float, float]) -> None:
    """Tag each contact with the lead it is formating on, in place.

    CHAINED, not compared to the leader: a four-ship in trail is strung out over
    more than the pairwise threshold end to end, so testing everyone against the
    first drops the tail of the formation.
    """
    def near(a: dict, b: dict) -> bool:
        an, ar = geo.range_bearing_true(origin, a["lat"], a["lon"])
        bn, br = geo.range_bearing_true(origin, b["lat"], b["lon"])
        ax, ay = an * math.sin(math.radians(ar)), an * math.cos(math.radians(ar))
        bx, by = bn * math.sin(math.radians(br)), bn * math.cos(math.radians(br))
        return (math.hypot(ax - bx, ay - by) <= FORM_NM
                and abs((a["alt_ft"] or 0) - (b["alt_ft"] or 0)) < FORM_FT
                and abs(((a["heading"] or 0) - (b["heading"] or 0) + 180)
                        % 360 - 180) <= FORM_HDG)

    groups: list[list[dict]] = []
    for c in contacts:
        if c["lat"] is None or c["lon"] is None:
            groups.append([c])
            continue
        for g in groups:
            if any(near(c, other) for other in g):
                g.append(c)
                break
        else:
            groups.append([c])
    for g in groups:
        # A single ship is not a formation, and saying so would make every
        # contact on the scope look like a flight of one.
        lead = g[0]["name"] if len(g) > 1 else ""
        for c in g:
            c["formation"] = lead


def contacts(origin: tuple[float, float] | None = None,
             bindings: dict | None = None) -> list[dict]:
    """Every unit the sim currently has, as data.

    NO STALENESS FILTER, and that is the whole argument of `SCHEMA.md` in one
    absence. A row exists until the sim says `gone` or the world restarts; a
    parked aeroplane never moves, never updates, and used to vanish off the
    scope fifteen seconds after a pilot climbed into it.

    `origin` is where THIS controller measures from, and it is only used for
    clustering here -- ranges and radials are computed by whoever draws the
    picture, because a controller at another field measures from his own.
    """
    from geoalchemy2 import Geometry
    from sqlalchemy import select

    from marshall.core import db
    from marshall.core.schema import Track

    bindings = bindings or {}
    out: list[dict] = []
    with db.session() as s:
        for t, lat, lon in s.execute(
                # CAST TO GEOMETRY. ST_Y/ST_X are geometry functions; on a
                # geography column Postgres refuses with "function st_y(geography)
                # does not exist", which reads like a missing extension and is
                # not. The hand-written SQL this replaces cast it too.
                select(Track,
                       Track.geog.cast(Geometry).ST_Y().label("lat"),
                       Track.geog.cast(Geometry).ST_X().label("lon"))).all():
            who = t.label or t.name
            out.append({
                "name": t.name,
                # THE LABEL, NOT THE SLOT NAME. The picture prints the player
                # for a manned unit, and feeding `name` instead severed the
                # identity chain once already: `unit_for_radio("Sockeye")`
                # matched nothing when it was handed "Viper 1-4".
                "label": who,
                "callsign": bindings.get(who, ""),
                "type": t.type or "",
                "category": t.category or "",
                "manned": bool(t.player),
                "player": t.player or "",
                # THE SIM'S OWN ANSWER, from `Unit.inAir()`. NULL means nobody
                # has asked yet, which is a third answer -- and reading it as
                # "airborne" is what told a parked Mustang it was flying.
                "on_ground": (t.in_air is False),
                "lat": lat, "lon": lon,
                "alt_ft": t.alt_ft, "heading": t.heading,
                "speed_kt": t.speed_kt,
                "coalition": t.coalition, "formation": "",
            })
    if origin is not None:
        _cluster(out, origin)
    return out


def bullseyes() -> dict:
    """The bullseye per coalition, from the table `feed` writes.

    Empty when the feed has not managed to ask the sim yet -- which is a real
    answer and not zero: a contact quoted against a bullseye at 0,0 would be
    confidently, uselessly wrong, and the drawing code already prints an em dash
    when this is absent.
    """
    from sqlalchemy import select

    from marshall.core import db
    from marshall.core.schema import Bullseye
    with db.session() as s:
        return {b.coalition: {"lat": b.lat, "lon": b.lon}
                for b in s.execute(select(Bullseye)).scalars()}
