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
# The engine transmits these itself, on its own schedule -- see `asr.py` and the
# monitor. They are verified like everything else and never repaired, because a
# repair would duplicate a transmission rather than restore a missing one.
SPOKEN_BY_THE_ENGINE = frozenset({"vector"})

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
    "advise_atis",       # tell me you have the current information
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
    # THE INFORMATION LETTER, and it is a fact a pilot must receive like any
    # other. The engine asked for it three times on one sortie -- "Advise you
    # have information Alpha" -- and the agent dropped it every time, silently,
    # because the check-in path composes PROSE and only a Decision is verified.
    atis_letter: str = ""
    # THE TRANSPONDER CODE. Four octal digits, spoken one by one -- never
    # "sixty-five twenty-one" -- which is why it is a string and not an int.
    squawk: str = ""

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


# `spoken_facts` WAS HERE and is deliberately gone. It returned one canonical
# rendering per fact, and `accepted_forms` below returns that same string as the
# first element of every entry along with the variants a controller might
# actually have used. Keeping both meant two functions that had to agree about
# what a fact sounds like, which is the duplication this module exists to
# remove. `tools/unwired.py` flagged it the moment the last caller moved.
def accepted_forms(d: Decision) -> list[tuple[str, list[str], float | None]]:
    """Every way a controller could legitimately have said each fact.

    ONE FACT, SEVERAL RENDERINGS, and this matters far more now that a failed
    check REPAIRS the transmission rather than just printing about it. While
    `verify` was advisory a false positive cost a misleading log line; now it
    costs an unnecessary second sentence on the radio restating something the
    pilot already has. That is the frequency-filling this project exists to
    avoid.

    Measured against the recorded sorties and the obvious variations, the
    canonical spelling alone flagged four innocent replies:

        runway one-three          a hyphen instead of a space
        runway 13                 digits instead of words
        maintain 2,000 feet       grouped digits
        contact ... 133.0         a frequency with one decimal, not three

    All four are a controller saying the right thing. So each fact carries its
    spoken form, its string variants, AND -- for anything numeric -- its VALUE,
    because `133`, `133.0` and `133.000` are one number and no amount of string
    matching says so.

    Returns [(canonical spoken form, [string renderings], numeric value or None)].
    """
    from marshall.core import say
    def _num(v) -> float | None:
        """The numeric value of a field, or None when there is not one.

        NOTHING HERE MAY RAISE. This function is called on the transmit path
        for every decision of every turn, so an exception is not a wrong answer
        -- it is a dead controller. `accepted_forms` did `float(d.runway)` and
        `Controller.request_taxi` had been carrying `runway="zero seven"` since
        long before any of this, because `_runway_in_use` returns the SPOKEN
        form. It killed the bridge on the ramp, mid-sortie, at Q4.

        The old verifier compared strings only, so it never had to care what
        was in the field. Adding value comparison added a way to crash on data
        that had always been there.
        """
        try:
            return float(str(v).strip().replace(",", "").lstrip("0") or 0)
        except (TypeError, ValueError):
            return None

    out: list[tuple[str, list[str], float | None]] = []
    if d.altitude_ft is not None:
        n = _num(d.altitude_ft)
        if n is not None:
            out.append((say.spell_alt(int(n)), [say.spell_alt(int(n))], n))
    if d.heading_deg is not None:
        n = _num(d.heading_deg)
        if n is not None:
            out.append((say.spell_hdg(int(n)),
                        [say.spell_hdg(int(n)), f"{int(n):03d}"], n))
    if d.runway:
        # ALREADY SPOKEN IS A VALID RUNWAY. `spell_rwy("zero seven")` returns it
        # unchanged, so the canonical form is right either way; only the numeric
        # alternative is unavailable, and a missing alternative is not a fault.
        out.append((say.spell_rwy(d.runway), [say.spell_rwy(d.runway)],
                    _num(d.runway)))
    if d.frequency_mhz is not None:
        f = _num(d.frequency_mhz)
        if f is not None:
            out.append((say.spell_freq(f), [say.spell_freq(f)], f))
    # A STATION IS A NAME, not a number, and must not be held to the numeric
    # rules below -- "Kobuleti Tower one three three decimal zero" is the name
    # followed by the frequency, and treating the digits after it as part of
    # the name reported a perfectly good transmission as a miss.
    if d.station:
        out.append((d.station, [d.station], None))
    # A LETTER, NOT A NUMBER. "Information Alpha" is the whole fact -- the word
    # "information" alone is not it, and neither is a bare "alpha" in a
    # sentence about something else.
    if d.atis_letter:
        want = f"information {d.atis_letter}"
        out.append((want, [want], None))
    if d.squawk:
        digits = str(d.squawk).strip()
        out.append((say.spell_squawk(digits), [say.spell_squawk(digits), digits],
                    float(digits) if digits.isdigit() else None))
    return out


def _normalise(said: str) -> str:
    """Lower-case, punctuation to spaces -- keeping numbers intact.

    Two periods' worth of trouble. `one three three decimal zero.` ends a
    sentence, and treating that full stop as part of the word reported a fact
    as missing when it had been spoken perfectly; `133.0` needs its point kept
    or the numeric form falls apart. Likewise a comma: it separates clauses AND
    groups digits, and turning `2,000` into `2 000` loses the number.

    So: a period or comma BETWEEN DIGITS belongs to the number and survives.
    Everything else is punctuation.
    """
    import re
    s = (said or "").lower()
    s = re.sub(r"[;:!?\-/()\[\]\"']", " ", s)
    s = re.sub(r"(?<=\d),(?=\d\d\d)", "", s)          # 2,000 -> 2000
    s = re.sub(r",", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    return " ".join(s.split())


# The words a spoken number is made of. A spoken match that runs straight into
# one of these has not found the fact -- it has found the FRONT OF A LONGER ONE.
_NUM = {"zero", "one", "two", "three", "tree", "four", "fower", "five", "fife",
        "six", "seven", "eight", "niner", "nine", "decimal", "point",
        "thousand", "hundred"}


def _said_words(hay: str, form: str, numeric: bool) -> bool:
    """Is this spoken rendering present as the WHOLE fact, not the start of another?

    Two ways to be wrong, and they are not equally bad. Reporting a fact missing
    when it was spoken costs one unnecessary sentence. Reporting it spoken when
    it was not means the pilot never got it and nothing knows. Biased to the
    first, deliberately.

    `one three` sits inside `one three three decimal zero`, so a runway check
    would pass against a FREQUENCY. For a numeric fact the next word must not be
    another number word; a station name is exempt, since a frequency legitimately
    follows it.
    """
    import re
    f = " ".join(form.lower().split())
    if not f:
        return False
    for m in re.finditer(rf"(?<![\w.]){re.escape(f)}(?![\w.])", hay):
        rest = hay[m.end():].split()
        if not numeric or not rest or rest[0] not in _NUM:
            return True
    return False


def _said_number(hay: str, value: float) -> bool:
    """Was this NUMBER said, in digits, however it was written?

    Compared as a value rather than as text: 133, 133.0 and 133.000 are one
    frequency, and 2000 and 2,000 are one altitude. String matching cannot say
    that without enumerating spellings forever.
    """
    import re
    for tok in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])", hay):
        try:
            if abs(float(tok) - value) < 1e-6:
                return True
        except ValueError:
            continue
    return False


def verify(d: Decision, said: str) -> list[str]:
    """Which of the engine's facts did NOT survive being spoken.

    Empty means the agent voiced everything that mattered. This is the check
    that a sentence cannot support and a decision can, and it is the whole
    reason for this module: on the last sortie three of seventeen issued
    altitudes never reached the air, and nothing noticed.

    CASE- AND PUNCTUATION-INSENSITIVE, and nothing cleverer. A verifier that
    tries to understand the reply is a second model with a second opinion,
    which is the problem rather than the fix. Hyphens and slashes become spaces
    because "one-three" is one fact spelled with a dash, not a missing one.
    """
    hay = _normalise(said)
    missed = []
    for canonical, forms, value in accepted_forms(d):
        numeric = value is not None
        ok = any(_said_words(hay, f, numeric) for f in forms)
        if not ok and numeric:
            ok = _said_number(hay, value)
        if not ok:
            missed.append(canonical)
    return missed


def repair(d: Decision, said: str = "") -> str:
    """The words that must be added because the agent did not say them.

    THE POINT OF THE WHOLE MODULE, and the thing it did not do until now. The
    engine decided, the agent phrased, `verify` noticed a fact had gone missing
    -- and the transmission went out anyway. The recorded sorties show what that
    costs:

        [controller] Sockeye, runway one three, cleared for take-off, wind ...
        [transmitted] Sockeye, roger.

        [controller] Take-off is Tower's, contact Kobuleti Tower one three
                     three decimal zero.
        [transmitted] sockeye, Kobuleti Ground, go ahead.

    An aeroplane cleared for take-off and never told; a pilot refused a
    clearance and never redirected. Both from a controller who sounded fine.

    APPENDED, NOT SUBSTITUTED. Replacing the reply would throw away the agent's
    manner and its read of the conversation, which is the half it is good at --
    and a controller who suddenly speaks in templates is the thing the agent
    exists to avoid. Adding the missing clause keeps the person and guarantees
    the fact.

    Returns "" when there is nothing to add, which includes the case where the
    phrasebook has no rendering for this kind. A silent no-op is correct there:
    inventing words for a decision we cannot phrase is exactly what the engine
    must never do.
    """
    if said and not verify(d, said):
        return ""
    # KINDS THE ENGINE SPEAKS FOR ITSELF ARE NOT REPAIRED HERE.
    #
    # The talkdown and the vectors go out on their own transmissions -- ATC[asr]
    # and ATC[vec] -- rendered from this same phrasebook by the monitor. The
    # module already says why: "the ASR talkdown ... transmits directly with no
    # model in the loop ... 'the engine speaks' is correct there rather than a
    # compromise."
    #
    # So appending one to the agent's reply would not restore a lost fact, it
    # would say the same thing twice from two transmissions -- which a pilot
    # reported on 11 August as "I'm getting redundant instructions" and "he's
    # stepping on me". VERIFYING them is still worth everything: it is how the
    # MVA altitude going missing became visible at all.
    if d.kind in SPOKEN_BY_THE_ENGINE:
        return ""
    from marshall.atc import phrasebook
    try:
        return (phrasebook.render(d) or "").strip()
    except Exception:
        # Never let a rendering failure cost a transmission. The agent's reply
        # still goes out; the miss is already recorded.
        return ""
