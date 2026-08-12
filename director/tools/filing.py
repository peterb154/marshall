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
FIELDS = ("name", "label", "origin", "destination", "route", "legs",
          "cruise_ft",
          "task", "approach")

# A plan's `name` is a key, not prose: it goes in URLs, in migrations and in
# `assigned_plans.template`.
_NAME_OK = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")

# A LABEL IS ONE WORD, because it is said out loud on a bad channel by somebody
# flying an aeroplane. Migration 012 learned this the hard way: the first two
# labels were "Samovar One" and "Samovar Two", which is the "Alpha One / Alpha
# Two" its own note warns against -- a transcriber that turns "one" into "won"
# picks the wrong sortie and clears a man onto it.
_LABEL_OK = re.compile(r"^[A-Za-z][A-Za-z'-]{1,23}$")


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
          taken: dict[str, str], updating: str = "") -> tuple[list[str], list[str]]:
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

    if not _NAME_OK.match(name):
        bad.append("name must be lowercase letters, digits and hyphens "
                   "(3-63 characters) — it is a key, not a title")
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

    for who in ("origin", "destination"):
        if not (plan.get(who) or "").strip():
            bad.append(f"{who} is required — it is what a controller reads back")

    # THE ROUTE IS THE ENROUTE PORTION, AND EMPTY IS LEGAL.
    #
    #     "So ORIGIN and DESTINATION - should these be on the flightplan as
    #      fixes?"
    #
    # No. ICAO keeps them apart -- field 13 departure, field 15 the enroute
    # portion, field 16 destination -- and this table has all three columns.
    # Repeating the aerodromes inside `route` was duplication, and the rule
    # underneath quietly came to depend on it: "at least two fixes" only ever
    # passed BECAUSE the endpoints were padding the list. A genuine direct
    # flight -- Kobuleti to Batumi with nothing published in between, which is
    # most of what gets flown here -- has zero enroute fixes and could not be
    # filed at all without writing its endpoints in twice.
    #
    # The rule this file actually wants is the one its own docstring states:
    # every fix NAMED is one the sim holds. That is unchanged and is the whole
    # point; what is gone is a length test standing in for it. See #127.
    legs = route_fixes(plan.get("route", ""))
    # ...OR ONE THE PLAN DEFINES ITSELF. A private fix is named by the pilot and
    # carried with its position in `legs`, so the plan is self-contained and a
    # route naming FOO resolves for anybody holding that plan. It does NOT make
    # the name public: nothing else can see it, which is the point.
    own = {(l.get("fix") or "").lower() for l in (plan.get("legs") or [])
           if l.get("lat") is not None and l.get("lon") is not None}
    # THE WHOLE REASON THIS FILE EXISTS. Named one at a time so a typo in a
    # six-fix route says which of the six, rather than "invalid route".
    for fx in legs:
        if fx.lower() in own:
            continue
        if fx.lower() not in fixes:
            bad.append(f"no fix called {fx} — the controller would have to "
                       f"say a place that is not on any chart")
    # A route that names its own endpoints is not refused -- every row filed
    # before this change does -- but it is worth saying, because it is the
    # difference between "via" and "direct" and a controller reads it out.
    ends = {(plan.get("origin") or "").strip().lower(),
            (plan.get("destination") or "").strip().lower()}
    dupes = [f for f in legs if f.lower() in ends and f.strip()]
    if dupes:
        warn.append(f"{', '.join(dupes)} is already the origin or destination — "
                    f"the route is the ENROUTE portion, and repeating an "
                    f"aerodrome in it says he overflies his own field")

    alt = plan.get("cruise_ft")
    try:
        alt = int(alt)
    except (TypeError, ValueError):
        alt = 0
    if alt <= 0:
        bad.append("cruise altitude must be a positive number of feet")
    elif alt % 100:
        warn.append(f"{alt} ft is not a round hundred; a controller will say it "
                    f"as you wrote it")

    if not (plan.get("task") or "").strip():
        bad.append("task is required — it is what a pilot actually asks for, "
                   "and the only thing that tells two similar plans apart")
    else:
        # The mistake of #57, refused rather than repeated. The endpoints have
        # their own columns and are scored from them; repeating them in the task
        # gives one plan triple credit for the same word and turns a deliberately
        # ambiguous request into a confident wrong answer.
        task = _words(plan["task"])
        for who in ("origin", "destination"):
            for w in _words(plan.get(who, "")):
                if w in task:
                    warn.append(
                        f"the task repeats the {who} ({w}). It has its own "
                        f"column and is scored from it — saying it twice makes "
                        f"this plan outrank the board on any request that "
                        f"mentions {w}")

    ap = (plan.get("approach") or "").strip()
    if ap and ap not in approaches:
        bad.append(f"no approach called {ap}")

    return bad, warn


def check_live(plan: dict, updating: str = "") -> tuple[list[str], list[str]]:
    """`check`, against the board as it actually is."""
    return check(plan, fixes=known_fixes(), approaches=known_approaches(),
                 taken=taken_labels(), updating=updating)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2}


def file_plan(plan: dict, updating: str = "") -> dict:
    """Put it on the board, or say why not. Never partially."""
    bad, warn = check_live(plan, updating=updating)
    if bad:
        return {"filed": False, "refused": bad, "warnings": warn}

    row = {k: (plan.get(k) or None) for k in FIELDS}
    row["name"] = row["name"].strip()
    row["label"] = row["label"].strip()
    row["cruise_ft"] = int(plan["cruise_ft"])
    row["route"] = ", ".join(route_fixes(plan["route"]))
    # THE LEVEL PER LEG. Stored as given: it is the pilot's own profile and
    # nothing here is entitled to round it. `cruise_ft` remains the highest,
    # which is what a controller means by cruise -- see migration 030.
    row["legs"] = Json(plan.get("legs")) if plan.get("legs") else None
    with get_pool().connection() as c:
        c.execute(
            "INSERT INTO flight_plans (name, label, origin, destination, "
            "route, legs, cruise_ft, task, approach) "
            "VALUES (%(name)s, %(label)s, %(origin)s, %(destination)s, "
            "%(route)s, %(legs)s, %(cruise_ft)s, %(task)s, %(approach)s) "
            "ON CONFLICT (name) DO UPDATE SET "
            "label=EXCLUDED.label, origin=EXCLUDED.origin, "
            "destination=EXCLUDED.destination, route=EXCLUDED.route, "
            "legs=EXCLUDED.legs, "
            "cruise_ft=EXCLUDED.cruise_ft, task=EXCLUDED.task, "
            "approach=EXCLUDED.approach", row)
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
