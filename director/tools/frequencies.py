"""Looking up a frequency, instead of carrying every frequency in every prompt.

    "giving the agent a tool to look up ANY frequency on demand is more scalable
     and we dont need to waste tokens on every call"

WHY A TOOL AND NOT MORE PROMPT. A controller works ONE aerodrome, so his own
field's frequencies are a handful of lines and stay in the brief -- he knows them
the way a real controller knows his own tower. The unbounded set is everywhere
ELSE: thirty aerodromes at four to eight positions each is two hundred lines that
would be carried on every transmission of every sortie to answer a question a
pilot asks perhaps twice a night.

That is the axis. Not "prompt versus tool" in general -- the field a man is
sitting at is cheap and constant, and the rest of the map is neither.

WHAT IT REPLACES is worse than prompt bloat. Asked for a frequency it had not
been given, the controller invented one -- confidently, in correct phraseology,
with a plausible number. A pilot sent to an invented frequency calls into
silence and cannot tell that from a controller who has stopped answering. The
brief now says to call this rather than guess, which is the same bargain as
`vector`: an exact answer is available, so an estimate is never acceptable.

THE DATA IS ALREADY HERE. `agent_atc.load_and_push_plate` writes the approach
profile into `approaches` on every bridge start, and the profile carries the
whole station list with each entry's field and role. So this is a read of
something the bridge already publishes, not a second copy of the station table
that could drift from `route.py`.
"""

from __future__ import annotations

import logging

from marshall.core.db import pool as get_pool

log = logging.getLogger(__name__)


def _stations() -> list[dict]:
    """Every published station, from the approach the bridge last pushed."""
    with get_pool().connection() as c:
        row = c.execute(
            "SELECT data->'stations' FROM approaches "
            "WHERE data ? 'stations' ORDER BY name").fetchone()
    return list(row[0]) if row and row[0] else []


def _spoken(mhz: float) -> str:
    """"one two four decimal four two five" -- how a controller says it.

    Spelled HERE rather than left to the model, because a frequency is exactly
    the kind of number that gets rounded into uselessness on the way to speech:
    124.425 read as "one two four point four" is a channel nobody is on.
    """
    from marshall.core.say import spell_freq
    return spell_freq(float(mhz))


def frequency_tools():
    from strands import tool

    @tool
    def look_up_frequency(place: str = "", position: str = "") -> str:
        """Look up the radio frequency of any controller anywhere on the map.

        CALL THIS RATHER THAN RECALLING A NUMBER. You know your own field's
        frequencies because they are in your brief; you do not know anybody
        else's, and a frequency you produce from memory is one you have
        invented. A pilot sent to an invented frequency calls into silence and
        cannot tell that from a controller who has stopped answering.

        `place` is an aerodrome or region -- "Batumi", "Kobuleti", "Georgia".
        `position` is the seat -- "tower", "ground", "approach", "departure",
        "clearance", "center". Either may be omitted: give only a place to get
        everything at that field, only a position to get that seat everywhere.

        Returns the frequencies spelled the way you should say them, or a plain
        statement that there is no such position -- which is a real answer and
        must be passed on as it stands. "Kobuleti has no approach control" is
        useful; a number for a seat that does not exist is dangerous.
        """
        place, position = (place or "").strip().lower(), (position or "").strip().lower()
        rows = _stations()
        if not rows:
            return ("No station list is published — say you cannot look it up "
                    "rather than offering a number.")
        hit = [s for s in rows
               if (not place or place in (s.get("field") or "").lower()
                   or place in (s.get("name") or "").lower())
               and (not position
                    or position == (s.get("role") or "").lower()
                    or position in [a.lower() for a in (s.get("also") or [])])]
        if not hit:
            what = " ".join(x for x in (place.title(), position) if x)
            # NAMED, AND NOT AN EMPTY LIST. "There is no such position" is the
            # answer to a real question and the controller should say it; an
            # empty result invites the model to fill the silence itself, which
            # is the failure this tool exists to remove.
            near = sorted({(s.get("field") or "").strip() for s in rows if s.get("field")})
            return (f"There is no {what or 'such'} position on the published "
                    f"list. Fields published: {', '.join(near)}. Tell the pilot "
                    f"plainly that it does not exist — do not offer a number.")
        out = [f"{s['name']}: {_spoken(s['freq_mhz'])}"
               + (f" (also {', '.join(s['also'])})" if s.get("also") else "")
               for s in sorted(hit, key=lambda s: (s.get("field") or "", s["name"]))]
        return "; ".join(out)

    return [look_up_frequency]
