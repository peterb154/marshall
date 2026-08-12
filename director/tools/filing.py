"""Filing a flight plan, and refusing one that cannot be flown.

    "A plan can be filed without touching the database by hand."  -- [UI-1] #22

Every plan on the board until today was written in a SQL migration. That was
survivable while the board was a fixture and unsurvivable the evening the sortie
changed: the Kobuleti departure went unfiled until the hour it was needed, and
what a pilot heard was his controller telling him there was nothing on file for
him -- on the first transmission of the night, in perfect phraseology (#56).

THE VALIDATION IS THE POINT, not the form. A form is twenty lines of HTML and
anybody can write one; what makes filing safe is that a plan naming a place
nobody holds is refused HERE, at the moment somebody types it, and not on the
radio at two hundred knots.

    route:  KOBULETI, INTIAL, BATUMI
                      ^^^^^^ this fix does not exist

That typo, filed, is a controller reading a route with a fix in it that the
aircraft cannot fly to and that the transcriber has never heard -- and the first
person to notice is a pilot who has been cleared somewhere impossible.

WHY IT IS SERVER-SIDE. The kneeboard form is one caller. `curl` is another, and
so is whatever files plans next year. A check that lives in the page is a check
the next caller does not run, which is how the empty row in #56 got onto the
board in the first place.

**Nothing here assigns.** Filing puts a plan on the board and it belongs to
NOBODY -- see `plans.py`. It becomes an aeroplane's when a clearance copies it
into `assigned_plans`, and not one instant earlier.
"""

from __future__ import annotations

import re

from psycopg.types.json import Json

from marshall.core.db import pool as get_pool

# The columns a filed plan is made of. `active` is deliberately NOT among them:
# it says which approach the bridge loads at start-up, it is set by the bridge's
# own bootstrap, and letting a form move it means a filed plan can silently
# change the procedure a controller is running.
# WHAT A PLAN IS MADE OF, after migration 031. Everything else that used to be
# here was either a fact about the CLEARANCE wearing a plan's clothes (origin,
# approach, cruise_ft -- all of which `assigned_plans` has carried since
# migration 009) or a second copy of the route (destination, route).
#
#     "the origin should be determined at request time, the destination is the
#      last point. We should not define an approach in the flight plan. there
#      should be no cruise alt in flight plan."
FIELDS = ("name", "label", "legs", "task")

# A plan's `name` is a key, not prose: it goes in URLs, in migrations and in
# `assigned_plans.template`.
_NAME_OK = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")

# A LABEL IS ONE WORD, because it is said out loud on a bad channel by somebody
# flying an aeroplane. Migration 012 learned this the hard way: the first two
# labels were "Samovar One" and "Samovar Two", which is the "Alpha One / Alpha
# Two" its own note warns against -- a transcriber that turns "one" into "won"
# picks the wrong sortie and clears a man onto it.
_LABEL_OK = re.compile(r"^[A-Za-z][A-Za-z'-]{1,23}$")


def derived(plan: dict) -> dict:
    """A plan row, plus the facts that used to be columns beside it.

    `route`, `destination` and `cruise_ft` are no longer stored (migration
    031) because every one of them was a second answer to a question `legs`
    already answers -- and two of them had already drifted apart on the live
    board. They are still what the rest of the system speaks, so they are
    computed HERE, once, rather than in the six places that read a plan.

        route        the legs before the last one -- the ENROUTE portion, which
                     is what a controller reads back. #127.
        destination  the last leg, and NOTHING ELSE MAKES IT SPECIAL:

                         "the destination (Nellis) is just the last
                          steerpoint.. nothing special about it except perhaps
                          when referring to the plan 'IFR flight to Nellis'"

                     Which is the whole of it. It is not a column, not a kind
                     of leg, and nothing in the engine branches on it. It is
                     computed here because a controller SAYS it -- "cleared to
                     Nellis as filed" -- and because a pilot asks for a plan by
                     where it goes. A speech concept, derived on the way out.
        cruise_ft    the highest level the route asks for. Kept for the scoring
                     and the strip; the CLEARANCE altitude is `legs[0]`, and
                     which is which is exactly what a single `cruise_ft`
                     column could never say.

    NOT `origin`. It is determined at request time -- he calls Clearance from a
    parking spot, and where he is standing is not something he should have had
    to write down in advance.
    """
    legs = [l for l in (plan.get("legs") or []) if isinstance(l, dict)]
    names = [(l.get("fix") or "").strip() for l in legs]
    alts = [int(l.get("alt_ft") or 0) for l in legs]
    return {**plan,
            "route": ", ".join(n for n in names[:-1] if n),
            "destination": names[-1] if names else "",
            "cruise_ft": max(alts) if alts else 0}


def key_for(label: str) -> str:
    """The storage key for a plan, from the word a pilot says.

    A KEY IS GENERATED AND A LABEL IS AUTHORED. The form used to ask for both --
    "name — the key" beside "label — what a pilot says" -- which is two
    identifiers for one plan and one of them serving no purpose the other
    could not. The label is the one that has to earn its shape: it is spoken on
    a bad channel by somebody flying an aeroplane.

    `name` survives as the key rather than being replaced by an id because it
    is the FK target of `assigned_plans.template`, and because a URL somebody
    has open should keep working.
    """
    return re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:63]


def known_fixes() -> set[str]:
    """Every place a route may name, lowercased.

    The `fixes` table is the authority because it is what the SIM projected --
    `agent_atc.push_fixes` writes it from `route.py` through the sim's own
    coordinate conversion on every bridge start. A fix that is in `route.py` but
    has never been pushed is a fix the controller cannot give a range to, so
    refusing it here is right rather than pedantic.
    """
    with get_pool().connection() as c:
        return {n.strip().lower()
                for (n,) in c.execute("SELECT name FROM fixes").fetchall()}


def known_positions() -> dict[str, tuple[float, float]]:
    """Where each published fix IS, not just what it is called.

    `known_fixes` answers "may a route name this?" and that is all `check` used
    to need. Telling a plan that carries the SAME place from one that carries a
    DIFFERENT place under a published name needs the position too -- see the
    collision rule in `check`.
    """
    with get_pool().connection() as c:
        return {n.strip().lower(): (la, lo) for n, la, lo
                in c.execute("SELECT name, lat, lon FROM fixes").fetchall()}


def known_approaches() -> set[str]:
    with get_pool().connection() as c:
        return {n for (n,) in c.execute("SELECT name FROM approaches").fetchall()}


def taken_labels() -> dict[str, str]:
    """lower(label) -> name, for everything already on the board.

    Unfiltered. `check` drops the row being edited, because deciding what to
    exclude is a rule and this is a reader.
    """
    with get_pool().connection() as c:
        rows = c.execute("SELECT label, name FROM flight_plans "
                         "WHERE label IS NOT NULL").fetchall()
    return {lab.lower(): nm for lab, nm in rows}


def route_fixes(route: str) -> list[str]:
    """The route as a list of fix names, as written."""
    return [p.strip() for p in (route or "").split(",") if p.strip()]


def _near(a: str, b: str) -> bool:
    """Are these two labels too close to tell apart on a radio?

    Not an edit distance. Two words that differ by one letter in the MIDDLE are
    easy to tell apart said aloud ("Marlin"/"Merlin" is a real risk, but so is
    "Anvil"/"Ankle"); what actually collides is a shared opening and a shared
    length, because that is what a transcriber locks onto first.
    """
    a, b = a.lower(), b.lower()
    return a[:3] == b[:3] and abs(len(a) - len(b)) <= 2


def check(plan: dict, *, fixes: set[str], approaches: set[str],
          taken: dict[str, str], updating: str = "",
          at: dict | None = None) -> tuple[list[str], list[str]]:
    """(refusals, warnings). Empty refusals means it can be filed.

    Refusals are things that are provably wrong -- a fix nobody holds, a label
    already taken, an approach that does not exist. Warnings are judgement, and
    the caller is told rather than overruled: a label that sounds like another
    one is a real hazard and it is not the machine's decision.

    THE BOARD IS PASSED IN, not read. Same reason `atis.serve` takes its clock
    and its radio as arguments: these rules are the whole value of this module
    and they are worth testing, and a function that opens its own database
    connection can only be tested by standing one up. `check_live` is the
    two-line wrapper that does the reading.
    """
    bad, warn = [], []
    name = (plan.get("name") or "").strip()
    label = (plan.get("label") or "").strip()

    # THE KEY IS DERIVED WHEN NOBODY SUPPLIED ONE, so it is checked rather than
    # demanded: a pilot types a label and the slug follows from it.
    name = name or key_for(label)
    if not _NAME_OK.match(name):
        bad.append("label must make a usable key — letters and digits, three "
                   "characters or more")
    if not _LABEL_OK.match(label):
        bad.append("label must be ONE word a pilot can say — no digits, no "
                   "spaces. \"Samovar One\" and \"Samovar Two\" are how the "
                   "wrong sortie gets cleared")

    taken = {k: v for k, v in taken.items() if v != (updating or name)}
    if label.lower() in taken:
        bad.append(f"the label {label} is already on the board, filed as "
                   f"{taken[label.lower()]}")
    else:
        for other, nm in taken.items():
            if _near(label, other):
                warn.append(f"{label} sounds like {other.title()} ({nm}) — one "
                            f"garbled transmission and a pilot is cleared onto "
                            f"the wrong sortie")

    # NEITHER ORIGIN NOR DESTINATION IS ASKED FOR any more.
    #
    #     "the origin should be determined at request time, the destination is
    #      the last point"
    #
    # Origin is where he is standing when he calls Clearance, and asking him to
    # have written it down beforehand is asking him to tell you something you
    # can see. Destination is the last leg, and it was in the row twice. Both
    # columns are gone -- migration 031 -- and `filing.derived` computes the
    # destination for everything that reads a plan.

    # THE ROUTE IS THE LEGS, and there is only one list now.
    #
    #     "the destination is the last point"
    #
    # `route` was a comma-separated string beside a structured `legs` array,
    # and the two had already drifted apart on the live board -- route said
    # "FOO, BAR, SPAM, INITIAL" while legs ended at BATUMI, so validation read
    # one and the map read the other. See migration 031.
    legs = [l for l in (plan.get("legs") or []) if isinstance(l, dict)]
    if not legs:
        bad.append("a plan needs at least one leg — the last one is where he "
                   "is going, and a route to nowhere is not a plan")
    # EVERY FIX EITHER PUBLISHED OR CARRIED. A published fix anybody can look
    # up; a private one the plan defines itself, with a position, so it is
    # resolvable to whoever holds the plan and to nobody else. A name that is
    # neither is the one thing this file exists to refuse -- a controller
    # would have to say a place that is on no chart.
    #
    # THE LAST LEG'S ALTITUDE IS THE GROUND. A cartridge writes the field
    # elevation on the destination -- Nellis 1,842 ft, Batumi 33 -- and that is
    # not a level anybody assigns, so the round-hundred check does not apply to
    # it. Warning about it taught a pilot to ignore the one warning that means
    # something.
    #
    # Named ONE AT A TIME so a typo in a six-leg route says which of the six.
    for i, leg in enumerate(legs, start=1):
        fx = (leg.get("fix") or "").strip()
        if not fx:
            bad.append(f"leg {i} has no fix name")
            continue
        carried = leg.get("lat") is not None and leg.get("lon") is not None
        if not carried and fx.lower() not in fixes:
            bad.append(f"no fix called {fx} — it is on no chart and this plan "
                       f"does not give it a position")
        # A PRIVATE FIX MAY NOT WEAR A PUBLISHED NAME, and this is refused
        # rather than resolved because there IS no safe resolution.
        #
        # `route_fixes` checks the published catalogue first, so a plan whose
        # own leg is called INITIAL has that leg silently discarded and the
        # controller vectors to the PUBLISHED initial approach fix instead. The
        # pilot means one place, the controller means another, both are real
        # points, and the range and bearing spoken are perfectly plausible.
        # That is the shape of every bad hour this project has had.
        #
        # Shadowing the other way is no better: a plan that redefined DIOMI for
        # its own convenience would make one word mean two places depending on
        # who is holding which piece of paper.
        #
        # So: pick another name. It is the pilot's own point and he may call it
        # anything not already spoken by somebody else.
        elif carried and fx.lower() in fixes:
            # SAME NAME IS FINE; SAME NAME AND A DIFFERENT PLACE IS NOT.
            #
            # A cartridge carries a position for every steerpoint including the
            # destination, so a plan routing to BATUMI arrives with BATUMI's
            # coordinates in its legs -- and that is not a redefinition, it is
            # the same aerodrome. Refusing on the name alone rejected an
            # ordinary flight plan, which I nearly shipped.
            #
            # What is dangerous is DISAGREEMENT, and it is dangerous precisely
            # because it is silent: `route_fixes` resolves the published
            # catalogue first, so the pilot's point is discarded and the
            # controller vectors to ours. Two real places, one word, a
            # perfectly plausible range and bearing.
            where = (at or {}).get(fx.lower())
            off = _nm_apart(where, leg) if where else 0.0
            if off > 1.0:
                bad.append(
                    f"{fx} is a published fix and this plan puts it {off:.0f} nm "
                    f"from where the chart does — the controller would vector "
                    f"you to his. Give your own point a name nobody else is "
                    f"using")
        alt = leg.get("alt_ft")
        try:
            alt = int(alt)
        except (TypeError, ValueError):
            alt = -1
        if alt < 0:
            bad.append(f"{fx} has no altitude — a leg is a place and a level")
        elif alt and alt % 100 and i < len(legs):
            warn.append(f"{fx} at {alt} ft is not a round hundred; a controller "
                        f"will say it as you wrote it")

    if not (plan.get("task") or "").strip():
        bad.append("task is required — it is what a pilot actually asks for, "
                   "and the only thing that tells two similar plans apart")
    elif legs:
        # The mistake of #57, warned about rather than repeated. The
        # DESTINATION is the last leg and is scored from there; naming it in
        # the task as well gives one plan double credit for the same word and
        # turns a deliberately ambiguous request into a confident wrong answer.
        task = _words(plan["task"])
        for w in _words(legs[-1].get("fix") or ""):
            if w in task:
                warn.append(
                    f"the task repeats the destination ({w}). It is the last "
                    f"leg and is scored from there — saying it twice makes "
                    f"this plan outrank the board on any request that "
                    f"mentions {w}")

    # NO APPROACH CHECK, because a plan no longer names one. Which arrival you
    # fly is a fact about your CLEARANCE -- see migration 031 and #2. The
    # parameter stays so `check` keeps its shape for callers and tests.
    return bad, warn


def check_live(plan: dict, updating: str = "") -> tuple[list[str], list[str]]:
    """`check`, against the board as it actually is."""
    return check(plan, fixes=known_fixes(), approaches=known_approaches(),
                 taken=taken_labels(), updating=updating, at=known_positions())


def _nm_apart(where, leg) -> float:
    """Miles between a published position and the one a plan carries.

    Great-circle, because a degree of longitude is not a degree of latitude and
    at Batumi's parallel the error would be a third. Nothing here PROJECTS --
    both positions are already lat/lon -- so this is a comparison and needs no
    sim, which is the point of storing the sim's answer (#137).
    """
    import math
    try:
        la1, lo1 = float(where[0]), float(where[1])
        la2, lo2 = float(leg["lat"]), float(leg["lon"])
    except (TypeError, ValueError, KeyError, IndexError):
        return 0.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2}


def file_plan(plan: dict, updating: str = "") -> dict:
    """Put it on the board, or say why not. Never partially."""
    bad, warn = check_live(plan, updating=updating)
    if bad:
        return {"filed": False, "refused": bad, "warnings": warn}

    row = {k: (plan.get(k) or None) for k in FIELDS}
    row["label"] = row["label"].strip()
    # THE KEY IS GENERATED, not typed. Two hand-authored identifiers for one
    # plan was one too many, and the label is the one with a reason: it has to
    # survive being said out loud through Whisper. A caller may still pass a
    # name -- the DTC tool does, to update a plan it filed before -- and the
    # slug is derived from the label when it does not.
    row["name"] = (row["name"] or key_for(row["label"])).strip()
    # THE LEVEL PER LEG. Stored as given: it is the pilot's own profile and
    # nothing here is entitled to round it.
    row["legs"] = Json(plan.get("legs") or [])
    with get_pool().connection() as c:
        c.execute(
            "INSERT INTO flight_plans (name, label, legs, task) "
            "VALUES (%(name)s, %(label)s, %(legs)s, %(task)s) "
            "ON CONFLICT (name) DO UPDATE SET "
            "label=EXCLUDED.label, legs=EXCLUDED.legs, task=EXCLUDED.task",
            row)
    return {"filed": True, "name": row["name"], "warnings": warn}


def unfile(name: str) -> dict:
    """Take a plan off the board. A flight plan is a route somebody filed.

    IT USED TO REFUSE WHILE THE ROW WAS `active`, because that was how the
    bridge found the approach it runs -- so finishing with a route and trying
    to remove it produced:

        "362nd-kobuleti-batumi is the ACTIVE plan -- the bridge reads the
         approach it runs from this row. Make another plan active first."

    Every part of which was a problem. There was no way to make another plan
    active -- no endpoint, no button -- and anything set by hand was overwritten
    at the next bridge start, so the instruction named an action that could not
    be taken and would not have held. And it should never have been the pilot's
    concern in the first place:

        "i dont understand this active business. sounds like mis-alignment
         between you and me"

    There was. `active` is not a fact about a flight plan; it was this bridge's
    note-to-self about which arrival it is running, parked on a route somebody
    else owns. The bridge reads its own theatre now and the director reads
    `sectors`, so nothing consults the column and there is nothing left to
    guard. See #131.

    A plan a flight is ALREADY FLYING is a different question and a real one --
    that lives in `assigned_plans`, which has its own row and its own lifetime,
    and removing the template does not take a clearance away from anybody.
    """
    with get_pool().connection() as c:
        row = c.execute("SELECT name FROM flight_plans WHERE name=%s",
                        (name,)).fetchone()
        if row is None:
            return {"removed": False, "refused": [f"no plan called {name}"]}
        c.execute("DELETE FROM flight_plans WHERE name=%s", (name,))
    return {"removed": True, "name": name}
