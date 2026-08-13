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

THE DATA WAS ALREADY HERE, AND ITS WRITER IS GONE. That paragraph used to read
"`load_and_push_plate` writes the approach profile into `approaches` on every
bridge start, and the profile carries the whole station list" -- true when this
was built as #67 and false since #162, which moved the station table out of the
profile and onto the THEATRE. `profile_to_dict` is `asdict`, and

    ApproachProfile has no `stations` field   ->  no row written from now on
                                                  carries one

Verified against the live database: `batumi-asr` and `batumi-ils`, written 25
July, still hold nine stations each; `batumi-ndb`, written after the move, holds
none. So on a fresh database this tool answers "no station list is published" to
every frequency question for ever, and the controller falls back to the thing it
was built to stop -- inventing a plausible number in correct phraseology.

WHERE THE ANSWER BELONGS IS A PUSH, and the director cannot start it. The bridge
knows which map is loaded and the director does not; `push_sectors` says exactly
that and pushes the controllers' VOLUMES for the same reason. Sectors are not
the station table -- Ground, Clearance and Sentry have no airspace, so five of
the theatre's nine seats are absent from it -- so the missing half is a
`push_stations` beside it in `atc/agent_atc.py`. Until that exists this reads
what is on the table.

WHAT IS FIXED HERE is the wrong-map answer, which was live. The query took ONE
row -- `ORDER BY name`, `fetchone` -- across rows accumulated from every theatre
ever loaded, and the alphabetically first is `batumi-asr`. So on Nevada a pilot
who asked Nellis Tower for Tonopah's frequency was told "There is no Tonopah
tower position on the published list. Fields published: Batumi, Kobuleti", and
asking for `position="ground"` read him two Georgian frequencies in correct
phraseology.

A profile is a PROCEDURE and the station list is the MAP's, so the question
"which of these lists is mine" has an exact answer and it is not alphabetical:
the one that names the seat doing the asking. `look_up_frequency` is bound to
his station the way `hook_tools` and `memory_tools` are, and resolves against
the list he appears in. Where no published list knows him, it says it cannot
look it up -- which is the answer this tool exists to make sayable.
"""

from __future__ import annotations

import logging

from marshall.core.db import pool as get_pool

log = logging.getLogger(__name__)

# THE ONE TOOL MODULE THAT COULD NOT BE TESTED WITHOUT THE CONTAINER. Every
# other one guards this import; this one did it inside the factory, so the only
# thing reachable from the suite was the query. What the tool RETURNS is the
# controller's entire instruction -- a string that can be paraphrased into a
# falsehood will be, which is `not_on_the_board`'s whole argument -- so it is
# the half that most wanted a test.
try:
    from strands import tool
except ImportError:                     # importable without strands (tests)
    def tool(fn):
        return fn


def _stations(seat: str = "") -> list[dict]:
    """Every published station on the map THIS CONTROLLER is sitting on.

    `seat` is his station name, handed down from the bridge -- the trusted side,
    resolved from the frequency before the call was made. Rows in `approaches`
    accumulate across theatres and nothing ever clears them, so "the list" is
    not a question a `fetchone` can answer. The list that names him is.

    An empty answer is a real answer here. It means no published list knows this
    seat, and the tool must say so rather than read him somebody else's map.
    """
    with get_pool().connection() as c:
        rows = c.execute(
            "SELECT name, data->'stations' FROM approaches "
            "WHERE data ? 'stations' ORDER BY name").fetchall()
    lists = [list(sts) for _name, sts in rows if sts]
    want = (seat or "").strip().lower()
    for sts in lists:
        if any(want == (s.get("name") or "").strip().lower() for s in sts):
            return sts
    # NOBODY TOLD US WHICH SEAT. An older bridge sends no station, and then
    # there is no way to choose -- so one published list is the answer and
    # several is not. Picking the first of several is what this was doing.
    return lists[0] if not want and len(lists) == 1 else []


def _spoken(mhz: float) -> str:
    """"one two four decimal four two five" -- how a controller says it.

    Spelled HERE rather than left to the model, because a frequency is exactly
    the kind of number that gets rounded into uselessness on the way to speech:
    124.425 read as "one two four point four" is a channel nobody is on.
    """
    from marshall.core.say import spell_freq
    return spell_freq(float(mhz))


def frequency_tools(station: str = ""):
    """`station` is the seat that will be asking -- see `_stations`.

    Bound at construction, like `hook_tools` and `memory_tools(namespace=...)`,
    and for the same reason: which map's frequencies a controller may read is a
    fact about where he is sitting, not something the model should be trusted to
    supply. An older bridge sends nothing and the tool falls back to the only
    published list, or to saying it cannot look one up.
    """

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
        # HIS MAP, not the alphabetically first one ever loaded. See
        # `_stations`: the rows accumulate across theatres and this used to take
        # one of them, so a Nevada controller was read Georgian frequencies.
        rows = _stations(station)
        if not rows:
            return ("No station list is published for this field — say you "
                    "cannot look it up rather than offering a number.")
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
