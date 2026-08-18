"""Looking up an approach, instead of carrying every approach in every prompt.

    "Can we give the agent a tool to lookup procedures on demand as he needs
     them? Or does that cost too much latency if we know the agent is going to
     need a procedure?"

Both halves of that question have different answers, and the split is the whole
design.

WHAT IS INJECTED. The approach an aeroplane is CLEARED for. We know it before
the model is called -- `Controller.procedure_for` resolves it off the board --
so a tool would pay a round trip for something already in hand. That round trip
is not free: the model call is a median 3.3 s and a worst case of 13.5, and
`services/app.py` records that a tool call roughly doubles it.

And latency is the smaller reason. **A tool call can fail, or simply not
happen** -- the model decides whether to make it. The procedure being injected
is the one he is being talked DOWN, and a surveillance approach is the one
procedure that never stops talking. An injected block cannot fail to arrive; a
tool call at three miles on final can. See `briefing.procedure_brief`.

WHAT IS A TOOL. Every other approach on the map. A pilot asking what else is
available, or asking to change to the ILS, is asking about a procedure this
controller was not briefed on -- and that request is unpredictable, occasional,
and lands on a CONVERSATIONAL turn rather than a vectoring one. Nobody notices
three seconds while answering a question; everybody notices it on a mile call.
So the latency is paid exactly where it is affordable.

THIS IS `frequencies.py`'S AXIS, ONE STEP OVER, and that module states it:

    "the field a man is sitting at is cheap and constant, and the rest of the
     map is neither"

Substitute "the approach he is flying" and the argument is unchanged. It also
removes the same failure, which is worse than prompt bloat: asked about an
approach it had not been given, a controller invents one -- confidently, in
correct phraseology, with plausible numbers. An invented FREQUENCY sends a
pilot to silence. An invented MINIMUM is a number somebody descends to.

WHERE THE DATA COMES FROM. `agent_atc.load_and_push_plates` writes every
published procedure to the `approaches` table at start, keyed
`<field>-<kind>-<runway>`. That is new: it used to write ONE row -- whichever
arrival the process was started on -- so this tool could not have existed
before #162 without answering for three procedures out of four with whatever a
previous run had left behind. The same defect `frequencies.py` records finding
in its own table, and the reason that module now checks the seat it is given.
[#176]
"""

from __future__ import annotations

from marshall.core.db import pool as get_pool

try:                                   # pragma: no cover - exercised live
    from strands import tool
except Exception:                      # pragma: no cover - offline suite
    # SAME SHIM AS `frequencies.py`, and for the same reason: the suite must be
    # able to import this module and call the function underneath without
    # standing up strands. A decorator that vanishes is safer here than an
    # import guard at every call site.
    def tool(fn):
        return fn


def _rows() -> list[dict]:
    """Every published approach, off the table `load_and_push_plates` writes.

    Read straight off `approaches` rather than through `core.theatre`, which is
    the tempting shortcut and is wrong for the reason `push_sectors` states in
    capitals: **the voice process knows which map is loaded and the container
    does not.** `catalogue.maps()` is `[]` in there and `route.STATIONS` raises
    `FileNotFoundError`, so a tool that read the theatre would answer for
    whatever map the image happened to ship.

    An empty list is a real answer and the caller says so rather than guessing.
    """
    with get_pool().connection() as c:
        rows = c.execute(
            "SELECT name, field, data FROM approaches ORDER BY name").fetchall()
    return [{"key": r[0], "field": r[1] or "", "data": r[2] or {}} for r in rows]


def _summary(row: dict) -> str:
    """One approach, in the words a controller would use about it.

    DELIBERATELY NOT THE FULL PLATE. What a controller needs about somebody
    else's procedure is what it IS, where it goes and what it demands of him --
    enough to offer it, refuse it, or agree to a change. The mile-call rules,
    the formation break-up ladder and the altimeter datum arrive with the
    aeroplane when he is actually cleared for it (`briefing.procedure_brief`),
    because until then they are describing work he is not doing.
    """
    from marshall.core.approach import may_vector, profile_from_dict
    d = row["data"] or {}
    kind = (d.get("kind") or "").upper() or "approach"
    rwy = d.get("runway") or "in use"
    # WHO FLIES IT is the fact that changes the controller's job, so it leads --
    # and it is asked of `may_vector` rather than worked out here.
    #
    # I worked it out here first, off `guidance`, and got the letdown wrong:
    # `batumi-ndb-12` carries `guidance="talkdown"` AND `vectored=False`,
    # because the pilot is talked down a procedure he flies on his own homing
    # adapter and a HEADING destroys his only reference. `may_vector`'s own
    # docstring names that trap -- "ONE QUESTION, ONE ANSWER, and it was being
    # asked three different ways ... which disagreed" -- and this was a fourth.
    #
    # THEN THE DICT LOST THE ANSWER. Reproducing `may_vector`'s precedence
    # against the stored JSON described the surveillance approach as unvectored,
    # because `vectored` is a computed PROPERTY (`kind == "asr"`) and
    # `profile_to_dict` is `asdict`, which keeps fields and drops properties.
    # The row is lossy and reasoning over it directly cannot be made correct.
    #
    # So the row is rebuilt into the object it came from and the one function
    # is asked. `profile_from_dict` is `profile_to_dict`'s inverse and exists
    # for exactly this. [#176]
    pro = profile_from_dict(d)
    if may_vector(pro) and (d.get("guidance") or "").lower() == "talkdown":
        flown = ("**you** navigate — continuous headings and a range every "
                 "mile, and he has no approach aid of his own")
    elif may_vector(pro):
        flown = ("**he** navigates — you vector to intercept, clear him, and "
                 "then stop talking")
    else:
        flown = ("**he** navigates and you may NOT vector him — he flies a "
                 "published pattern homing his own beacon, and a heading "
                 "destroys the only reference he has")
    bits = [f"`{row['key']}`: {kind} to runway {rwy} at "
            f"{row['field'] or 'this field'} — {flown}"]
    if d.get("final_crs"):
        bits.append(f"final approach course {int(d['final_crs']):03d}")
    if d.get("final_intercept_nm"):
        bits.append(f"intercept by {float(d['final_intercept_nm']):.0f} miles")
    if d.get("mda_ft"):
        elev = d.get("field_elev_ft") or 0
        bits.append(f"minimum {int(d['mda_ft'])} ({int(d['mda_ft']) - int(elev)} "
                    f"above the field)")
    if d.get("missed_ft"):
        turn = (d.get("missed_turn") or "").upper()
        bits.append(f"missed approach climbing {turn or 'straight'} to "
                    f"{int(d['missed_ft'])}")
    return "; ".join(bits) + "."


def procedure_tools():
    """The approach-lookup tool, for every seat.

    UNIVERSAL, like `look_up_frequency`, because a pilot asks whoever he is
    talking to. He asks Ground what approaches are in use as often as he asks
    Approach, and a controller who cannot answer a question about his own
    aerodrome because of a capability table is a worse failure than the tokens
    it saves. Issuing one is still Approach's alone -- that is separation and
    lives in the engine, not in who may read a list.
    """

    @tool
    def look_up_approach(key: str = "", field: str = "") -> str:
        """Look up an instrument approach published on this map.

        CALL THIS RATHER THAN RECALLING NUMBERS FOR AN APPROACH YOU WERE NOT
        GIVEN. The approach the aeroplane you are working is cleared for
        arrives with his transmission, in full — you do not need this for him.
        Use it when a pilot asks what else is available, asks to change to a
        different procedure, or asks about an approach at another field.

        A minimum, a course or a missed approach you produce from memory is one
        you have invented, and unlike an invented frequency — which sends a
        pilot to silence — an invented minimum is an altitude somebody
        descends to.

        `key` is the published name, `batumi-ils-13`. `field` is an aerodrome,
        "Batumi". Both may be omitted to list everything this map publishes,
        which is the right call when a pilot asks what approaches are in use.

        Returns what each approach IS, who flies it, and its principal numbers
        — or a plain statement that there is no such procedure, which is a real
        answer and must be passed on as it stands.
        """
        key, field = (key or "").strip().lower(), (field or "").strip().lower()
        rows = _rows()
        if not rows:
            return ("No approaches are published — say you cannot look it up "
                    "rather than describing a procedure from memory.")
        hit = [r for r in rows
               if (not key or key == r["key"].lower() or key in r["key"].lower())
               and (not field or field in (r["field"] or "").lower())]
        if not hit:
            # NAMED, AND NOT AN EMPTY LIST -- `look_up_frequency`'s rule. "There
            # is no such approach" is the answer to a real question; an empty
            # result invites the model to fill the silence itself, which is the
            # failure this tool exists to remove.
            what = " ".join(x for x in (key, field.title()) if x)
            return (f"There is no approach matching {what or 'that'} on this "
                    f"map. Published: {', '.join(r['key'] for r in rows)}. "
                    f"Tell the pilot plainly that it does not exist — do not "
                    f"describe one.")
        return " | ".join(_summary(r) for r in hit)

    return [look_up_approach]
