"""How low a controller may put you, and how low the chart says you may go.

TWO DIFFERENT NUMBERS, and confusing them is the fault this module exists to
prevent. The MSA is published, sector-wide and conservative -- it is what a
pilot reads off a plate when he has lost the picture. The MVA is surveyed, cell
by cell, and it is what a controller may assign when he is watching you on
radar and knows exactly where you are.

Honouring the MSA on a vector holds an aeroplane thousands of feet above a
platform it is about to land on; assigning an MVA to a pilot flying his own
letdown puts him below the only figure he has. So both live here, both are
named for what they are, and `Field_` exposes them separately.
"""

from __future__ import annotations



# The AIP publishes minimum safe altitude as TWO sectors around the LU NDB, not
# four quadrants: 7,000 ft from 217 degrees round through north to 038, and
# 13,600 ft from 038 round through south to 217. Published and conservative, and
# two sectors removes a whole class of bug -- a 45-degree error in a four-
# quadrant lookup once put 330 (the sea, the one place it is safe to be low)
# into the mountain sector.
# Two different minimum altitudes, and conflating them grounds the approach.
#
# **MSA** is published, on the plate, and is the PILOT's number: the lowest he
# may descend to inside 25 nm if he loses everything. Batumi's is 7,000 to the
# north through west and 13,600 the rest of the way round. It is deliberately
# blunt -- one figure for a whole sector of a 25-mile circle, sized by the
# highest thing in it.
#
# **MVA** is the CONTROLLER's number: the lowest he may ASSIGN while vectoring.
# It is lower, because he knows exactly where the aircraft is and only has to
# clear the ground actually underneath it. Vectoring to the published MSA
# instead reads as safety and is not: Batumi's final is flown over open water
# where the MSA is still 7,000, so honouring it holds the aircraft four
# thousand feet above the platform until it is over the threshold. An earlier
# build did exactly that and assigned 11,700 to an aeroplane at 250 feet.
#
# Sectors are (from_bearing, to_bearing, altitude), clockwise, and may wrap.
MSA_SECTORS = [(217.0, 38.0, 7000), (38.0, 217.0, 13600)]

# Minimum vectoring altitudes, surveyed out of the sim itself by
# tools/survey_terrain.py -- `land.getHeight` over a polar grid, then the
# highest ground in each cell plus a thousand feet of clearance, rounded up.
#
# Cells, not quadrants, and the difference is not academic. The predecessor was
# four 90-degree buckets each holding the highest ground within 25 nm, which
# says 9,500 ft for everything north-east of Batumi -- including the coastal
# plain four miles out, where the survey says thirty-six feet. Flown live that
# rule climbed an aircraft repositioning at four miles to 9,500 and then, one
# bucket boundary later, told it to descend to 2,000: seven thousand feet of
# climb for nothing. The same coarseness off the departure end, where the
# buckets said 13,000, had already flown an aeroplane into the Caucasus.
#
# (bearing_from, bearing_to, out_to_nm, altitude_ft). Rings as well as spokes,
# which is the shape a real MVA chart has and for exactly this reason.
MVA_CELLS = [
    (  0.0,  30.0,   5.0,   1500),
    (  0.0,  30.0,  10.0,   1000),
    (  0.0,  30.0,  15.0,   1500),
    (  0.0,  30.0,  25.0,   1500),
    ( 30.0,  60.0,   5.0,   1500),
    ( 30.0,  60.0,  10.0,   3000),
    ( 30.0,  60.0,  15.0,   5500),
    ( 30.0,  60.0,  25.0,   8000),
    ( 60.0,  90.0,   5.0,   3000),
    ( 60.0,  90.0,  10.0,   5500),
    ( 60.0,  90.0,  15.0,   6000),
    ( 60.0,  90.0,  25.0,   9000),
    ( 90.0, 120.0,   5.0,   3000),
    ( 90.0, 120.0,  10.0,   5000),
    ( 90.0, 120.0,  15.0,   6500),
    ( 90.0, 120.0,  25.0,  11000),
    (120.0, 150.0,   5.0,   3000),
    (120.0, 150.0,  10.0,   5000),
    (120.0, 150.0,  15.0,   8000),
    (120.0, 150.0,  25.0,  12000),
    (150.0, 180.0,   5.0,   4000),
    (150.0, 180.0,  10.0,   6000),
    (150.0, 180.0,  15.0,   5500),
    (150.0, 180.0,  25.0,   9500),
    (180.0, 210.0,   5.0,   3000),
    (180.0, 210.0,  10.0,   4000),
    (180.0, 210.0,  15.0,   6000),
    (180.0, 210.0,  25.0,   9000),
    (210.0, 240.0,   5.0,   1500),
    (210.0, 240.0,  10.0,   1000),
    (210.0, 240.0,  15.0,   1000),
    (210.0, 240.0,  25.0,   3500),
    (240.0, 270.0,   5.0,   1500),
    (240.0, 270.0,  10.0,   1000),
    (240.0, 270.0,  15.0,   1000),
    (240.0, 270.0,  25.0,   1000),
    (270.0, 300.0,   5.0,   1500),
    (270.0, 300.0,  10.0,   1000),
    (270.0, 300.0,  15.0,   1000),
    (270.0, 300.0,  25.0,   1000),
    (300.0, 330.0,   5.0,   1500),
    (300.0, 330.0,  10.0,   1000),
    (300.0, 330.0,  15.0,   1000),
    (300.0, 330.0,  25.0,   1000),
    (330.0, 360.0,   5.0,   1500),
    (330.0, 360.0,  10.0,   1000),
    (330.0, 360.0,  15.0,   1000),
    (330.0, 360.0,  25.0,   1000),
]


def alt_for(bearing_deg: float, sectors) -> int:
    """Look a bearing up in a sector table. Sectors may wrap through north."""
    b = bearing_deg % 360
    for lo, hi, alt in sectors:
        inside = (lo <= b < hi) if lo < hi else (b >= lo or b < hi)
        if inside:
            return alt
    return max(a for _, _, a in sectors)


def msa_for(bearing_deg: float, sectors=None) -> int:
    """Published minimum sector altitude -- what the PILOT is briefed."""
    return alt_for(bearing_deg, sectors or MSA_SECTORS)


def mva_for(bearing_deg: float, range_nm: float | None = None, cells=None) -> int:
    """Minimum vectoring altitude -- the lowest a CONTROLLER may assign.

    Looked up by bearing AND range, because terrain has both. With no range
    given, answer for the outermost ring, which is the conservative reading and
    the only safe default when the caller does not know where the aircraft is.

    This is the altitude for where he is NOW. A vector whose track crosses
    higher ground on the way is not caught here; at Batumi every repositioning
    track runs out to the north-west over open water, so the case does not
    arise, but it is a real limit and not a solved problem.
    """
    cells = cells or MVA_CELLS
    b = bearing_deg % 360
    best = None
    for lo, hi, out_to, alt in cells:
        inside = (lo <= b < hi) if lo < hi else (b >= lo or b < hi)
        if not inside:
            continue
        if range_nm is None:
            best = max(best or 0, alt)
        elif range_nm <= out_to and (best is None or out_to < best[0]):
            best = (out_to, alt)
    if best is None:
        return max(a for *_, a in cells)
    return best if isinstance(best, int) else best[1]


# --- who owns which piece of sky -------------------------------------------
#
# WHERE THE TERMINAL AREA ENDS, once, for everybody. `handoff.CENTER_NM` is the
# range at which Center gives an arrival up and takes a departure back, and it
# is the SAME NUMBER as the edge of Approach's volume -- they are two statements
# of one boundary, and a system holding them separately is one edit away from a
# ladder that hands a man over at twenty-five miles into airspace that stops at
# twenty. It lives here because a volume is a fact about the ground and the
# ladder is a fact about procedure; procedure may read geography, not the
# reverse. See LAYERS.md.
TERMINAL_NM = 25.0
# ROOM TO GET ONTO THE PROCEDURE, beyond its furthest published fix. An
# aeroplane is not established the instant he reaches the hold: he is vectored
# onto it, and the vector happens outside it. Five miles is the smallest number
# that is honestly more than nothing. It is not measured, and saying so is
# better than implying it was.
MANOEUVRE_NM = 5.0
# Tower's, and the reason it is small is the reason it is a separate volume: he
# owns the runway and its circuit, not the arrival.
CIRCUIT_NM = 5.0
# Ceilings. Approach works the letdown and the departure climb; above that it is
# the Center's whatever the plan view says.
TERMINAL_CEILING_FT = 15_000
CIRCUIT_CEILING_FT = 4_000
# Descending and closing, he ends with Tower -- so the innermost volume must win
# where they overlap, which is what `flight_airspace` orders by.
RANK_CENTER, RANK_TERMINAL, RANK_CIRCUIT = 10, 20, 30

# A departure controller IS the terminal controller wearing the outbound hat --
# see `Station.also`. Kobuleti publishes `departure` and Batumi `approach`, and
# a rule that only knew one of those words would give one of the two fields no
# airspace at all, which is precisely the bug this function exists to end.
TERMINAL_ROLES = ("approach", "departure")


def _nm_between(a, b) -> float:
    """Great-circle miles between two fields."""
    from marshall.core import geo
    nm, _ = geo.range_bearing_true((a.lat, a.lon), b.lat, b.lon)
    return nm


def procedure_reach_nm(field, approaches=()) -> float:
    """How far out this aerodrome's own procedures actually go.

    THE FURTHEST FIX ANY OF THEM USES, plus room to manoeuvre onto it. A
    terminal area exists to hold the approaches worked in it, so its size is a
    question about those approaches and not about a constant.

    Zero when nothing can be measured -- no approaches, or fixes carrying no
    position -- and the caller keeps its default. That is the honest answer
    rather than a small one: an area sized from a procedure nobody could locate
    would be a number with no evidence behind it.
    """
    if field is None or getattr(field, "lat", None) is None:
        return 0.0
    far = 0.0
    for pro in approaches:
        at = getattr(pro, "aerodrome", None)
        if getattr(at, "name", "").lower() != field.name.lower():
            continue
        for attr in ("outer_hold", "iaf", "arrival_fix", "navaid", "aerodrome"):
            f = getattr(pro, attr, None)
            if f is None or getattr(f, "lat", None) is None:
                continue
            far = max(far, _nm_between(field, f))
    return far + MANOEUVRE_NM if far else 0.0


def terminal_reach_nm(field, others=(), approaches=None) -> float:
    """How far THIS aerodrome's terminal area extends. Derived, not declared.

        "If the approach requires us maneuvering outside a 25nm ring then maybe
         we should extend that airspace so that the whole approach is covered
         by the airspace."

    THE MIDPOINT SPLIT IS GONE AND THAT IS THE FIX. It halved each area to the
    nearest neighbour so two fields could not overlap, and the arithmetic was
    absurd: Kobuleti and Batumi are 22.6 nm apart, so both terminal areas were
    eleven-mile circles -- while Batumi's ILS holds at KOBULETI, twenty-two
    miles out. The procedure began at DOUBLE the radius of the airspace that
    owned it, so "he is outside my airspace" fired on a man flying the approach
    exactly as published, and the geometry answered correctly. That is the
    signature of a volume that does not describe what it is for.

    NOT OVERLAPPING WAS THE WRONG CONSTRAINT. Real terminal areas overlap. Two
    fields twenty-two miles apart whose approaches both reach thirty are one
    radar room with two names -- which `Station.also` has always modelled for
    the CONTROLLER and nothing modelled for the AIRSPACE. Where two overlap the
    nearer field's wins, and that tie is broken where the containment test
    happens rather than here; see migration 034.

    `TERMINAL_NM` IS THE FLOOR NOW rather than the cap: an area is at least the
    conventional twenty-five miles and grows to hold its own procedures. A map
    whose approaches carry no positions gets exactly what it got before, which
    is what makes this safe to adopt on a theatre nobody has surveyed.

    `others` is kept in the signature and is no longer consulted. Not dead
    weight: every caller passes the map's other aerodromes, and the day a
    neighbour matters again -- a shelf, a delegated sector -- it is the
    argument that carries them. [#139]
    """
    if approaches is None:
        from marshall.core import theatre as _th
        approaches = list(_th.approaches_now().values())
    return max(TERMINAL_NM, procedure_reach_nm(field, approaches))


def sectors_for(fields, stations) -> list[dict]:
    """Every controller's volume, DERIVED from the theatre rather than declared.

        "So how do we prevent missing airspace bug going forward. We're going to
         add dozens of airfields"

    You cannot, by hand. `sectors` was three rows written into a migration --
    batumi-approach, batumi-tower, georgia-center -- and a second aerodrome
    arrived without one, so a jet three miles off Kobuleti's runway fell through
    to the unbounded fallback and was offered Georgia Center in the circuit. The
    row was not wrong; it was ABSENT, and absence read as an answer.

    Hand-authoring does not scale to a second field, never mind a fortieth, and
    the reason is not effort. It is that `sectors` was a SECOND COPY of a fact
    the theatre already holds -- where the aerodromes are and who works them --
    maintained independently, which is the shape docs/STATE.md is about. So it
    stops being an authority and becomes a projection of one, pushed at startup
    exactly as the fix catalogue is, and for the identical reason: the bridge
    knows which map is loaded and the director does not.

    A NEW AERODROME NOW GETS AIRSPACE BY EXISTING. Give it a lat/lon and a
    Tower and it has a volume; give it neither and it has none, which is honest.

    WHERE THE BOUNDARY GOES, with no polygon drawn by anybody: half way to the
    nearest neighbour, capped at the terminal range. Kobuleti and Batumi are
    twenty-two miles apart, so they meet at eleven and neither swallows the
    other -- which is what went wrong when the first attempt gave both of them
    twenty-five and an aeroplane on Kobuleti's ramp resolved to Batumi Approach.
    It is also how it is actually done: a boundary between two terminal areas
    twenty miles apart is not at either field's twenty-five mile ring.

    Circles, not polygons, because a terminal area IS a radius from the field --
    every rule in `handoff.py` is a distance -- and a polygon is only a circle
    somebody had to type.
    """
    by_name = {f.name: f for f in fields}
    # Which fields actually have a terminal controller. A field with no
    # approach and no departure has no terminal area to describe, and inventing
    # one would put a volume where nobody is listening.
    worked = sorted({s.field for s in stations
                     if s.role in TERMINAL_ROLES and s.field in by_name})
    out: list[dict] = []

    # THE CENTER IS UNBOUNDED, and that is not laziness -- it is what a Center
    # is. Drawing a polygon round the whole map to say "everywhere else" would
    # be a lie in the shape of precision, which is 005's phrase and still right.
    for s in stations:
        if s.role == "center":
            out.append({"name": _slug(s.name), "label": s.name, "role": "center",
                        "field": "", "freq_mhz": s.freq_mhz,
                        "rank": RANK_CENTER, "floor_ft": None,
                        "ceiling_ft": None, "lat": None, "lon": None,
                        "radius_nm": None})

    for name in worked:
        f = by_name[name]
        others = [by_name[o] for o in worked if o != name]
        reach = terminal_reach_nm(f, others)
        term = next((s for s in stations
                     if s.field == name and s.role in TERMINAL_ROLES), None)
        twr = next((s for s in stations
                    if s.field == name and s.role == "tower"), None)
        # NAMED FOR THE VOLUME'S ROLE, NOT THE STATION'S. Kobuleti's terminal
        # controller answers as Departure, and `leaving_my_airspace` reads the
        # role off the END of the sector name -- so `kobuleti-departure` would
        # have told it the volume was a departure's, which is not a rung of any
        # ladder and would have silently switched airspace off for that field.
        # The AREA is an approach area whoever is speaking on it.
        if term is not None:
            out.append({"name": f"{name.lower()}-approach", "label": term.name,
                        "role": "approach", "field": name,
                        "freq_mhz": term.freq_mhz, "rank": RANK_TERMINAL,
                        "floor_ft": None, "ceiling_ft": TERMINAL_CEILING_FT,
                        "lat": f.lat, "lon": f.lon, "radius_nm": reach})
        if twr is not None:
            out.append({"name": f"{name.lower()}-tower", "label": twr.name,
                        "role": "tower", "field": name,
                        "freq_mhz": twr.freq_mhz, "rank": RANK_CIRCUIT,
                        "floor_ft": None, "ceiling_ft": CIRCUIT_CEILING_FT,
                        "lat": f.lat, "lon": f.lon,
                        # Never larger than the terminal area that contains it.
                        # Two fields six miles apart would otherwise give each
                        # Tower a circuit reaching over the other's runway.
                        "radius_nm": min(CIRCUIT_NM, reach)})
    return out


def _slug(name: str) -> str:
    """'Kobuleti Approach' -> 'kobuleti-approach'.

    The sector name is read back by `leaving_my_airspace`, which splits the last
    hyphenated word off to get a ROLE -- so the shape matters and is not
    cosmetic.
    """
    return "-".join(str(name).lower().split())
