"""What the engine DECIDED, as facts rather than as a sentence.

    "I'm worried that the deterministic part is too rigid and will be difficult
     to maintain at scale."

It is, and the rigidity is not in the determinism -- it is in the PROSE.
`controller.py` is 1,669 lines carrying 94 long f-strings and some 506 words of
English. Adding progressive taxi means writing more English inside Python, and
that is what scales badly.

WHY THIS FIXES THE CONFLICTS TOO, which is the part that surprised me. Both
halves compose English today: the engine writes sentences so the agent cannot
paraphrase its numbers away, and the agent writes sentences because that is its
job. Two finished utterances then have to be reconciled, and that reconciliation
is the guards -- 27 firings on the last sortie, each one a referee catching a
disagreement AFTER both halves had already spoken.

A guard is evidence that two things can disagree. It manages the disagreement
rather than removing it. If only one thing composes English there is nothing to
reconcile and the guards become unnecessary rather than better.

AND A DECISION IS VERIFIABLE WHERE A SENTENCE IS NOT. Given
`Decision(kind="cleared_approach", altitude_ft=2000, runway="13")` the bridge
can check MECHANICALLY that the reply contains two thousand and one three -- no
model, no latency, and a failed check can retry or fall back to a template.
`/diag`'s `voiced` column attempts that today with fuzzy matching against prose,
which is why it is advisory rather than enforcing. Three of seventeen issued
altitudes never reached the air on the last sortie and nothing stopped it.

WHAT STAYS AS PROSE, deliberately: the ASR talkdown. It is pure geometry on a
metronome, it transmits directly with no model in the loop, and it is talking
somebody to a runway in cloud. "The engine speaks" is correct there rather than
a compromise -- see `asr.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# THE KINDS, and they are named for what the controller DID rather than for the
# words he used. "cleared_approach" survives a change of phraseology, an era, a
# language and a field; "cleared for the surveillance approach runway one three"
# does not, and every one of those variations is why the phrasebook grew.
KINDS = (
    "hold",              # enter the stack at a level
    "continue_hold",     # stay where you are, somebody is ahead
    "cleared_approach",  # the letdown is yours
    "cleared_visual",    # you are flying it, I am spacing you
    "cleared_land",      # the runway is yours
    "cleared_takeoff",   # ...and the other direction
    "taxi",              # to the runway, and no further
    "hold_short",        # stop at the edge
    "clearance",         # the IFR clearance itself
    "handoff",           # somebody else has you now
    "climb",             # a level, without a clearance attached
    "vector",            # a heading, without a clearance attached
    "missed",            # go around, published track
    "say_again",         # I did not get that
    "ack",               # roger, and nothing else
    "refuse",            # not mine to give -- see `owner`
)


@dataclass(frozen=True)
class Decision:
    """One thing the engine decided. No English in it.

    Every field is optional because a decision carries only what it decided:
    a handoff has a station and no altitude, a hold has an altitude and no
    runway. A renderer reads what is there.
    """

    kind: str
    to: str = ""                       # the callsign it is addressed to

    # THE NUMBERS, which are what must survive being spoken. These are the
    # fields a verifier checks against the agent's reply -- if the engine
    # decided two thousand and the pilot did not hear two thousand, the turn
    # failed regardless of how well the sentence read.
    altitude_ft: int | None = None
    heading_deg: int | None = None
    runway: str = ""
    frequency_mhz: float | None = None
    range_nm: float | None = None

    # WHO, for a handoff or a refusal. A name rather than a Station, so a
    # decision can be logged, stored and compared without dragging the whole
    # station table along with it.
    station: str = ""
    role: str = ""

    # The hold pattern, when there is one. A dict rather than five more fields
    # because nothing outside a hold reads it.
    pattern: dict = field(default_factory=dict)

    # Anything that genuinely is prose and has no structure -- a reason, a
    # caveat. Kept separate so it cannot be mistaken for a fact, and so a
    # verifier never looks for it.
    note: str = ""

    def facts(self) -> dict:
        """The numbers a pilot must actually receive.

        This is what `verify` checks and what `/diag` shows. Deliberately NOT
        everything: `note` is excluded because prose is not a fact, and `role`
        because a pilot hears a station's name rather than its role.
        """
        got = {}
        if self.altitude_ft is not None:
            got["altitude_ft"] = self.altitude_ft
        if self.heading_deg is not None:
            got["heading_deg"] = self.heading_deg
        if self.runway:
            got["runway"] = self.runway
        if self.frequency_mhz is not None:
            got["frequency_mhz"] = round(self.frequency_mhz, 3)
        if self.station:
            got["station"] = self.station
        return got


def spoken_facts(d: Decision) -> list[str]:
    """Each fact as the words a controller would use for it.

    The bridge checks the agent's reply against these. Spelled here rather than
    at the check site because "two thousand" and "2000" are the same fact, and
    a verifier comparing digits to words would fail every time -- which is the
    trap `/diag`'s fuzzy matching fell into.
    """
    from marshall.core import say
    out = []
    if d.altitude_ft is not None:
        out.append(say.spell_alt(d.altitude_ft))
    if d.heading_deg is not None:
        out.append(say.spell_hdg(d.heading_deg))
    if d.runway:
        out.append(say.spell_rwy(d.runway))
    if d.frequency_mhz is not None:
        out.append(say.spell_freq(d.frequency_mhz))
    if d.station:
        out.append(d.station)
    return out


def verify(d: Decision, said: str) -> list[str]:
    """Which of the engine's facts did NOT survive being spoken.

    Empty means the agent voiced everything that mattered. This is the check
    that a sentence cannot support and a decision can, and it is the whole
    reason for this module: on the last sortie three of seventeen issued
    altitudes never reached the air, and nothing noticed.

    CASE- AND PUNCTUATION-INSENSITIVE, and nothing cleverer. A verifier that
    tries to understand the reply is a second model with a second opinion,
    which is the problem rather than the fix.
    """
    hay = " ".join((said or "").lower().replace(",", " ").replace(".", " ").split())
    missed = []
    for want in spoken_facts(d):
        needle = " ".join(want.lower().split())
        if needle and needle not in hay:
            missed.append(want)
    return missed
