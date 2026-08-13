"""The radar picture, drawn for ONE controller.

    "why is that using batumi and not bull?"

Because the wrong layer was drawing it. Rendering needs an origin -- every range
in the picture is measured from somewhere -- and an origin is a property of the
CONTROLLER, not of the world. The director held the only one that existed
(`BATUMI_LAT, BATUMI_LON`, a module constant) and every consumer on the map read
its ranges, sorted by distance from its aerodrome.

Bullseye is not the fix for that; it is a better wrong answer. An approach
controller talking a man down needs range from his own field -- "six miles, turn
left one three zero" -- and bullseye range would make him do arithmetic on every
transmission. Bullseye is the right reference for anything SHARED between
controllers, BRAA is right between two aircraft, and the field is right for a
letdown. Three renderings of one fact, which is why the fact is stored as a
position and rendered here.

So this takes the contacts -- absolute positions, no opinion about who is asking
-- and an origin, and produces the prose that goes into one controller's prompt.
Senaki runs the same function with a different origin over the same contacts.

WHAT IS DELIBERATELY UNCHANGED. The format is byte-for-byte the director's, port
of `tools/tracks.py:_render`, because the agent has been reading it for weeks and
its prompt is written around it. `tests/test_picture.py` pins that. The only
number that moves is the one that is supposed to: with a different origin you get
different ranges, which is the entire point.
"""

from __future__ import annotations


from marshall.core import geo as _geo
# What the sim calls a return, and the one question anybody asks about it.
from marshall.feed import categories as _cat

# A formation is tight: line abreast or trail, inside a couple of miles and a
# few hundred feet, all pointing the same way. These live here as well as in the
# streamer because the streamer decides WHO is in a formation (a fact about the
# world) and this only draws it -- but the numbers are quoted in the comments of
# both, and a reader of either deserves to see them.
#
# The grouping arrives on the contact as `formation`, naming the lead. Nothing
# here re-derives it; that would be two answers to one question.


def _label(c: dict) -> str:
    """What the line calls him, and the bracketed tag if anything correlated one.

    The tag is CORROBORATION and never the primary key -- see atc/identity.py.
    It is printed because a controller reading his own scope wants to see which
    blip he has already tied to a callsign.
    """
    tag = f" [{c['callsign']}]" if c.get("callsign") else ""
    return f"{c.get('label') or c.get('name', '')}{tag}"


def _marks(c: dict) -> str:
    """The parenthetical after the airframe: manned, category, on the ground.

    Additive, in the order the director emitted them, because every existing
    parser splits on the comma and takes the type first.
    """
    out = ""
    if c.get("manned"):
        out += ", manned"
    # ANYTHING THAT IS NOT AN AEROPLANE SAYS SO, and what counts as one is
    # `feed.categories`' answer rather than two literals written out here. The
    # column has two writers and they did not agree on a capital letter. [#156]
    cat = c.get("category") or ""
    if not _cat.is_aircraft(cat):
        out += f", {_cat.word(cat)}"
    if c.get("on_ground"):
        out += ", on the ground"
    return out


def _other_ship(c: dict, lead: dict) -> str:
    """One wingman on the lead's line: name, airframe, and how far off he is.

    Compact on purpose -- the formation is meant to scan as ONE contact -- but
    it carries the three facts something downstream cannot do without.

    THE OFFSET IS GEODESIC NOW, computed from the two aircraft's own positions
    rather than by projecting both their ranges off a third point and taking a
    hypotenuse. It matters because the join rule measures a real gap against a
    one-mile radius while this detector's threshold is two, so "radar shows them
    as a formation" is not proof they are within a mile. The number is printed
    and the rule keeps measuring.
    """
    bits = [c.get("type") or ""]
    if c.get("manned"):
        bits.append("manned")
    cat = c.get("category") or ""
    if not _cat.is_aircraft(cat):
        bits.append(_cat.word(cat))
    if c.get("on_ground"):
        bits.append("on the ground")
    bits.append(f"{nm_between(lead, c):.1f} nm")
    name = c.get("label") or c.get("name", "")
    return f"{name} ({', '.join(b for b in bits if b)})"


# ONE IMPLEMENTATION, IN `core.geo`. This was byte-for-byte identical to
# `agent_atc._range_radial`, and a third version in `route.bearing_distance`
# returned a GRID bearing while promising true -- which is why the frame is now
# in the name of everything that produces one.
range_radial = _geo.range_bearing_true


def nm_between(a: dict, b: dict) -> float:
    """Separation of two contacts. Needs no origin: it is about the two of them."""
    return range_radial((a["lat"], a["lon"]), b["lat"], b["lon"])[0]


def render(contacts: list, origin) -> list[str]:
    """The picture, from THIS controller's field.

    Ordered nearest first, which is a controller's own priority and was
    previously an ORDER BY in the director measured from its constant -- so a
    controller anywhere else got his traffic in somebody else's order before he
    had read a line of it.
    """
    if not origin or not contacts:
        return []
    fixed = []
    for c in contacts:
        if c.get("lat") is None or c.get("lon") is None:
            continue
        nm, radial = range_radial(origin, c["lat"], c["lon"])
        fixed.append((nm, radial, c))
    fixed.sort(key=lambda t: t[0])

    # Group by the formation the streamer already detected. Order is preserved
    # from the sort, so the nearest formation appears where its LEAD would --
    # and the lead is whichever member the streamer named, not whoever happens
    # to be closest to us.
    groups: dict = {}
    order: list = []
    for nm, radial, c in fixed:
        key = c.get("formation") or c.get("name", "")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((nm, radial, c))

    lines = []
    for key in order:
        members = groups[key]
        # The LEAD is the contact the streamer named, wherever it sorted.
        lead_i = next((i for i, (_, _, c) in enumerate(members)
                       if c.get("name") == key), 0)
        nm, radial, lead = members[lead_i]
        others = [c for i, (_, _, c) in enumerate(members) if i != lead_i]
        typ = lead.get("type") or ""
        alt_ft = lead.get("alt_ft") or 0
        heading = lead.get("heading") or 0
        spd = f", {lead['speed_kt']:.0f} knots" if lead.get("speed_kt") else ""
        head = f"{_label(lead)} ({typ}{_marks(lead)})"
        if others:
            ships = ", ".join(_other_ship(o, lead) for o in others)
            lines.append(
                f"{head} IN FORMATION with {ships} — "
                f"{len(members)} ships, lead {nm:.1f} nm on the {radial:03.0f} "
                f"radial, {alt_ft:,.0f} ft, heading {heading:03.0f}{spd}")
        else:
            lines.append(
                f"{head}: {nm:.1f} nm on the {radial:03.0f} radial, "
                f"{alt_ft:,.0f} ft, heading {heading:03.0f}{spd}")
    return lines


def picture(contacts: list, origin) -> str:
    """The whole scope as the controller's prompt wants it."""
    lines = render(contacts, origin)
    if lines:
        return " | ".join(lines)
    if contacts and not origin:
        return unranged(contacts)
    return "no contacts"


def unranged(contacts: list) -> str:
    """The contacts, with no bearing and no range, because we cannot measure.

    A CONTROLLER WHO CANNOT MEASURE SAYS SO. Without a projected origin of his
    own this used to fall back to the DIRECTOR's prose -- ranges and radials
    from an origin he does not own, sorted by distance from it -- and the
    comment justifying it said "drawing from a stale constant beats drawing
    nothing".

    It does not. That is how a Nevada controller reads distances measured from
    Georgia, and every one of them is a plausible number, so nothing looks
    wrong until a pilot flies it:

        "A fallback must be conservatively unavailable, not confidently wrong
         on another map."                          -- CODEX_NTTR_AUDIT.md

    What survives is what does not need an origin -- who, what, how high, which
    way -- and that is genuinely useful: it is enough to answer "do you have
    me", to correlate a radio with an aeroplane, and to see that four contacts
    exist. `vector` already models the right failure for the rest: "negative DME
    to ingress, you'll have to call it off your own nav."
    """
    out = []
    for c in sorted(contacts, key=lambda x: str(x.get("name") or "")):
        who = c.get("label") or c.get("name") or "unknown"
        bits = [f"{who}"]
        if c.get("type"):
            bits.append(f"({c['type']})")
        if c.get("alt_ft") is not None:
            bits.append(f"{float(c['alt_ft']):,.0f} ft")
        if c.get("heading") is not None:
            bits.append(f"heading {float(c['heading']):03.0f}")
        out.append(" ".join(bits))
    return ("NO RANGES -- this controller has no projected origin, so bearing "
            "and distance are unavailable and must not be stated: "
            + "; ".join(out))
