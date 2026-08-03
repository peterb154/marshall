"""Turning a decision into words, and saying only what changed.

    "The phrasing when calling a heading change was saying amend a lot. And
     unnecessary repeating altitude when it wasn't changing."

BOTH OF THOSE ARE THE SAME FAULT: the engine composed each transmission from
scratch, with no idea what it had already said. Every vector therefore carried
an altitude whether or not the altitude had moved, and every heading arrived
labelled as an amendment because the prompt had been told to say "amend" when
changing something -- which, to a component with no memory, is every time.

Twenty-five "amend"s in one sortie, and a call reading "amend, turn right
heading three zero five, maintain five thousand five hundred" when he was
already at five thousand five hundred and had been for two calls.

A CONTROLLER SAYS WHAT CHANGED. That needs memory, so this holds it: `render`
is given the decision and what this aeroplane was last told, and omits anything
that still stands. It is the smallest thing that could deserve the name
phrasebook, and it is deliberately NOT where the sequencing lives -- see
`decision.py` on why the prose is coming out of `controller.py`.

WHY A DETERMINISTIC RENDERER AT ALL, when the agent is meant to do the words.
Because the agent can fail, be slow, or drift, and the engine's sentences are
what covers that today. Handing rendering entirely to the model means silence
when it is unreachable. So: the agent phrases it, and this answers when the
agent has dropped a number or is not there -- which `decision.verify` can now
detect mechanically.
"""

from __future__ import annotations

from dataclasses import dataclass

from marshall.core import say


@dataclass
class LastSaid:
    """What this aeroplane was last told. The memory a controller has and a
    stateless composer does not."""

    altitude_ft: int | None = None
    heading_deg: int | None = None
    runway: str = ""
    station: str = ""

    def update(self, d, spoken: dict | None = None) -> None:
        """Remember what he was TOLD, not what was computed.

        `spoken` is what `changed` decided to say. Recording the computed
        value instead would defeat the hysteresis entirely: a slide suppressed
        because it was under a thousand feet would still move the memory, so
        the next hundred-foot slide would look like a change from it and the
        whipping would come back one step slower.
        """
        take = spoken if spoken is not None else d.facts()
        for f in ("altitude_ft", "heading_deg", "runway", "station"):
            if f in take and take[f] not in (None, ""):
                setattr(self, f, take[f])


# HOW FAR AN ALTITUDE MUST MOVE BEFORE IT IS WORTH SAYING.
#
# The planner recomputes a descent every sweep against a descending aeroplane,
# so its answer slides continuously -- six thousand five hundred, six thousand,
# five thousand five hundred, a few hundred feet at a time. Each of those is a
# correct number and none of them is worth a transmission.
#
# A controller steps a descent: he issues a level, the aeroplane goes there,
# and the next one comes when it is due. A thousand feet is the smallest step
# worth interrupting a pilot for on an approach.
#
# THE CLAMP IS HERE AND NOT IN THE PLANNER because the planner's answer is
# right -- it is the SAYING that was wrong. An attempt to fix it in
# `asr.vector_altitude` assigned a level below the minimum vectoring altitude
# for an aeroplane that was already low, which is a safety regression a test
# caught immediately.
ALT_STEP_FT = 1000


def changed(d, last: LastSaid | None) -> dict:
    """Which of this decision's facts are NEW to him.

    Everything, when there is no memory of him -- a first call carries the lot,
    which is right: he has just arrived and knows nothing.
    """
    if last is None:
        return d.facts()
    out = {}
    for k, v in d.facts().items():
        was = getattr(last, k, None)
        if was == v:
            continue
        if k == "altitude_ft" and was is not None and abs(v - was) < ALT_STEP_FT:
            # A few hundred feet lower than the last one is the planner
            # sliding, not a new instruction. Say nothing and leave him where
            # he is -- he is already descending.
            continue
        out[k] = v
    return out


def vector(d, last: LastSaid | None = None, amended: bool = False) -> str:
    """A turn, and the altitude only if it moved.

    `amended` is FALSE by default and that is the correction. A routine vector
    is not an amendment -- a controller turning you onto base says "turn left
    heading two five four", not "amend, turn left heading two five four". The
    word belongs to changing a clearance he already gave you and nothing else,
    and using it for every turn taught a pilot to ignore it.
    """
    new = changed(d, last)
    bits = []
    if amended:
        bits.append("amend")
    if "heading_deg" in new:
        turn = f"turn {d.turn} " if getattr(d, "turn", "") else "fly "
        bits.append(f"{turn}heading {say.spell_hdg(d.heading_deg)}")
    if "altitude_ft" in new:
        # "Descend" only when it is one. Telling a man to descend to the level
        # he is already holding is how a pilot stops listening to altitudes.
        verb = "descend and maintain"
        if last and last.altitude_ft is not None and new["altitude_ft"] > last.altitude_ft:
            verb = "climb and maintain"
        bits.append(f"{verb} {say.spell_alt(new['altitude_ft'])}")
    # THE RANGE ONLY WHEN THERE IS SOMETHING TO ATTACH IT TO. A bare "fifteen
    # miles from the field" with no instruction is a position report the pilot
    # can read off his own scope, and on the talkdown the metronome is already
    # calling range every mile.
    if d.range_nm is not None and bits:
        bits.append(f"{d.range_nm:.0f} miles from the field")
    return ", ".join(bits)


def render(d, last: LastSaid | None = None, amended: bool = False) -> str:
    """One decision as words. Empty when there is nothing new to say.

    AN EMPTY STRING IS A REAL ANSWER. If the heading has not moved and the
    altitude has not moved, the correct transmission is none at all -- and a
    renderer that always produces a sentence is what fills a frequency with
    restatements of things the pilot already did.
    """
    if d.kind == "vector":
        return vector(d, last, amended)
    new = changed(d, last)
    if d.kind == "hold":
        alt = new.get("altitude_ft", d.altitude_ft)
        return f"hold at present position, maintain {say.spell_alt(alt)}"
    if d.kind == "continue_hold":
        return "continue holding, expect approach shortly"
    if d.kind == "cleared_approach":
        out = f"cleared {d.note or 'approach'} runway {say.spell_rwy(d.runway)}"
        if "altitude_ft" in new:
            out += f", maintain {say.spell_alt(new['altitude_ft'])}"
        return out
    if d.kind == "taxi":
        r = say.spell_rwy(d.runway)
        return f"taxi to runway {r}, hold short of runway {r}"
    if d.kind == "cleared_takeoff":
        return f"runway {say.spell_rwy(d.runway)}, cleared for take-off"
    if d.kind == "handoff":
        f = say.spell_freq(d.frequency_mhz) if d.frequency_mhz else ""
        return f"contact {d.station} {f}".strip()
    if d.kind == "refuse":
        f = say.spell_freq(d.frequency_mhz) if d.frequency_mhz else ""
        return f"that is {d.role.title()}'s, contact {d.station} {f}".strip()
    if d.kind == "ack":
        return "roger"
    return d.note or ""
