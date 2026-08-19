"""What reaches the radio, and what must never leave the room.

Three jobs that all answer the same question -- what does the pilot actually
HEAR -- and each of them was somewhere in the middle of the receive loop:

    route_tier                which model gets this turn
    radio_check_reply         the one answer that needs no model at all
    strip_unauthorised_handoff  ...and the one that must be taken back out
    for_voice                 prose to speech: what Polly may not be given

`for_voice` is the last thing between the agent and the air, so it is the last
place a mistake can be caught. It is also the only place that knows a hyphen,
a bracket and a bare numeral are not sounds.

STRIPPING A HANDOFF IS NOT COSMETIC. The agent will cheerfully send a pilot to
another frequency because it reads well, and a pilot who changes frequency on a
transmission the controller was not entitled to make is a pilot nobody is
working. So the authorisation is decided by the engine and the words are edited
to match, rather than the other way round.
"""

from __future__ import annotations

import os
import re

# Two-tier router, kept wired but OFF by default. Everything goes to the smart
# tier -- the radar-aware, fluent "color" the controller is valued for -- because
# Haiku 4.5 doesn't reliably hold the approach sequence even when handed the exact
# clearance. Flip MARSHALL_FAST_TIER=1 to route standard phraseology to the fast
# model (reserved for a future stronger cheap model, or a speak-the-directive fast
# path); a question / odd request / trouble always stays on the smart tier.
FAST_TIER_ON = os.environ.get("MARSHALL_FAST_TIER", "").lower() in ("1", "true", "yes", "on")
# Engage the deterministic separation engine only when there's real traffic (radar


_COMPLEX = re.compile(
    r"\?|\bcan i\b|\bcould you\b|\bunable\b|\bhow\b|\bwhy\b|\bwhat\b|\bsay again\b|"
    r"\bproblem\b|\bemergenc|\bmayday\b|\bnot sure\b|\bi need\b|\bhelp\b|\bexplain\b|"
    r"\badvise\b|\bconfus|\bunsure\b|\bdon'?t (?:copy|understand|know)\b", re.I)


def route_tier(transcript: str) -> str:
    if not FAST_TIER_ON:
        return "sonnet"
    return "sonnet" if _COMPLEX.search(transcript or "") else "haiku"


# A note to the log, not to the controller. Saying "debug log, the vectors are
# taking me at the field" during a sortie should record the thought and produce
# SILENCE -- the pilot is talking to the project, not to ATC, and a controller
# who answers has both broken the fiction and buried the note in a reply. Kept
# loose because it arrives through Whisper: "debug log", "debug note", and the
# bare "debug" all count.
_DEBUG = re.compile(r"\b(?:debug|de-bug)\b[\s,:-]*(?:log|note|entry)?\b", re.I)


def debug_note(transcript: str) -> str | None:
    """The note, if this transmission was one. None means it is a real call."""
    m = _DEBUG.search(transcript or "")
    if not m:
        return None
    return (transcript[m.end():].strip(" ,.:-") or transcript.strip())


_CHECK = re.compile(r"radio check|how do you (?:read|copy)|how copy|read you|comm check", re.I)
_CLOSE = re.compile(r"down and stopped|clear of the (?:runway|active)|off the runway|"
                    r"parking|shutting down|clear of active", re.I)
# ...unless he is ASKING for something. A request is the engine's, however
# closing the rest of the sentence sounds.
_ASKS = re.compile(r"\brequest\b|\btaxi\b|\bcan i\b|\bready\b|\?", re.I)


def radio_check_reply(known: str = "") -> str:
    """"Sockeye, loud and clear." Nothing else, and no matching.

    THIS WAS `simple_response`, AND IT MATCHED. A grammar of `_CHECK`, `_CLOSE`
    and `_ASKS` patterns ran BEFORE the classifier and before the engine, so a
    regex decided whether the deterministic half of a turn happened at all:

        _CLOSE = "down and stopped|clear of the (?:runway|active)|off the
                  runway|parking|shutting down|clear of active"
        _ASKS  = "request|taxi|can i|ready|?"

    On 18 August the first transmission of the sortie was "Kobuleti Clearance,
    sockeye, parking spot, number 22 with information, Delta." `_CLOSE` matched
    the word "parking", `_ASKS` matched nothing, and a cold opening call was
    answered "roger, welcome, good day" with the engine never seeing it.

        "that regex matching has bit us so many any times and is way too
         brittle"

    It had bitten before in this same function, on "clear of active, request
    taxi to parking" -- `_ASKS` was the patch then, and "parking spot" walked
    straight past it. A second grammar competing with the classifier will keep
    losing, because the classifier is the thing that reads.

    WHAT IS LEFT IS THE RENDERING. Which calls deserve a canned answer is now
    `IntentKind.RADIO_CHECK`, decided by the classifier; the closing
    acknowledgement is gone from here entirely, because "clear of the active"
    moves him to `taxi_in` and a phase transition IS a handoff (#77). [#194]
    """
    from marshall.atc import callsign as C
    cs = (C.parse(known).spoken or known) if known else "Station calling"
    return f"{cs}, loud and clear."

# When woken by a hook (or asked anything) the agent may decide no call is
# warranted; it replies with this and the bridge stays off the air.
NO_CALL = {"(no call)", "no call", "(none)", "standby."}


# "Falcon 1-1" -- the way a callsign is WRITTEN. It must never reach Polly.
_SPOKEN_CALLSIGN = re.compile(r"\b([A-Z][a-z]+)\s+(\d)-(\d)\b")


def _digit_words(digits: str) -> str:
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine"]
    return " ".join(words[int(d)] for d in digits)


_SENDS_HIM_AWAY = re.compile(
    r"[^.!?]*\b(?:contact|switch to|go to|monitor)\b[^.!?]*"
    r"\b(?:approach|tower|center|centre|departure|ground|sentry)\b[^.!?]*[.!?]?",
    re.I)


def strip_unauthorised_handoff(text: str, authorised, keep_him: str = "") -> tuple[str, str]:
    """Remove a frequency change nobody authorised. Returns (text, what went).

    A HANDOFF IS A CONTROL ACTION, NOT LANGUAGE, and it is the same rule that
    keeps an LLM out of separation: whether this pilot should be worked by
    somebody else depends on where he is, whose airspace that is, and who is
    free to take him -- none of which the model can see. When a handoff is due
    the bridge hands it over as a `HANDOFF:` line. No line, no handoff.

    THE RULES ALREADY SAY SO and it was not enough. Told plainly not to invent
    one, the model obeyed on a dry run and did it anyway on the radio the same
    evening -- to a pilot parked on the ramp, who was sent from Tower to
    Approach, back to Tower, and round again with nowhere to go. A prompt is
    guidance; this is a guarantee, and the difference matters for the same
    reason it matters in the separation engine.

    Deliberately narrow. It removes a SENTENCE that tells him to contact
    somebody, and leaves everything else -- including "this is Batumi Tower, one
    one eight decimal zero", which names the frequency he is ON and is a
    correction rather than a handoff.
    """
    if authorised is not None or not text:
        return text, ""
    gone = []

    def drop(m):
        gone.append(m.group(0).strip())
        return " "
    out = _SENDS_HIM_AWAY.sub(drop, text)
    if not gone:
        return text, ""
    out = re.sub(r"\s{2,}", " ", out).strip()
    # NEVER HAND BACK NOTHING, and never hand back the thing we just refused.
    # When the whole reply was the handoff -- which is the commonest shape, "X,
    # contact Y, good day" -- stripping leaves an empty string, and returning
    # the original would make the guard a no-op in exactly the case it exists
    # for. So the fallback keeps him on this frequency in the plainest words a
    # controller has.
    return (out or keep_him or text), " | ".join(gone)


def for_voice(text: str, agent: bool = False) -> str:
    """Reduce the agent's reply to the words that actually go over the air.

    Two problems, both seen live:

    * The model narrates. With extended thinking disabled it reasons in the
      OUTPUT instead, and Polly reads every word of it -- a real run transmitted
      "This is a different transmitter, a wingman, reporting his level. He's
      holding, not yet identified individually. Since the flight isn't broken up
      on radar... Pony one two, roger, level four thousand." The pilot hears the
      controller's inner monologue. Telling it not to in the prompt helps and
      does not hold, so the reply carries an explicit RADIO: marker and
      everything before the last one is thinking, not talking.
    * It emits markdown. A radio does not speak asterisks.

    `agent=True` for anything the MODEL wrote, where a missing marker means the
    reply is thinking and must not be heard. Deterministic strings -- the mile
    calls, the canned replies -- carry no marker by design and pass through.
    """
    if "RADIO:" in text:
        text = text.rsplit("RADIO:", 1)[1]
    elif agent:
        # No marker at all, from the AGENT. The reply is malformed and the
        # whole of it is thinking -- which is precisely when the model has
        # decided NOT to speak and written its reasoning instead. Transmitting
        # it read a pilot ten seconds of "his readback was correct, no
        # acknowledgment needed, but I notice he's turning through heading
        # 042... the ASR line contradicts what I just told him" in a
        # controller's voice. Silence is the right answer to a malformed reply:
        # the model meant to say nothing, and saying nothing is free.
        return ""
    text = re.sub(r"[*_`#>]+", "", text)          # emphasis / code / heading marks
    text = re.sub(r"(?m)^\s*[-•]\s+", "", text)    # list bullets
    text = re.sub(r"\s*\n+\s*", " ", text)          # collapse newlines to one line
    # NO CANONICAL CALLSIGNS OVER THE AIR. "Falcon 1-1" is how this system
    # WRITES a callsign; Polly reads the hyphen and says "Falcon one TO one",
    # which a pilot hears as a different aeroplane. One path did this and the
    # rest happened to spell it properly, which is luck rather than design --
    # so it is caught here, where every transmission passes, instead of in each
    # place that composes one.
    text = _SPOKEN_CALLSIGN.sub(
        lambda m: f"{m.group(1)} {_digit_words(m.group(2))} "
                  f"{_digit_words(m.group(3))}", text)
    text = spell_numbers(text)
    return re.sub(r"\s{2,}", " ", text).strip()


# EVERY AVIATION QUANTITY THAT HAS A SPOKEN FORM, and the word that identifies
# it. Order matters only in that frequencies are matched before bare numbers.
_QUANTITY = (
    # runway 13, runway 07L -> runway one three / runway zero seven left
    (re.compile(r"\b(runway)\s+(\d{1,2})\s*([LRC])?\b", re.I), "rwy"),
    # wind 090 at 6 -> wind zero nine zero at six
    (re.compile(r"\b(wind)\s+(\d{2,3})\s*(?:at\s*)?(\d{1,3})?\b", re.I), "wind"),
    # squawk 4271 -> squawk four two seven one
    (re.compile(r"\b(squawk)\s+(\d{4})\b", re.I), "squawk"),
    # heading 130, turn left heading 090
    (re.compile(r"\b(heading)\s+(\d{1,3})\b", re.I), "hdg"),
    # contact ... 133.0 / 124.425
    (re.compile(r"\b(\d{3}\.\d{1,3})\b"), "freq"),
    # 2,000 feet / 2000 ft / climb to 5000
    (re.compile(r"\b(?:(maintain|climb to|descend to|at|to)\s+)?"
                r"(\d{1,2},?\d{3}|\d{3,5})\s*(feet|ft)\b", re.I), "alt"),
    # 250 knots
    (re.compile(r"\b(\d{2,3})\s*(knots|kts)\b", re.I), "kt"),
)


def spell_numbers(text: str) -> str:
    """Digits in an aviation quantity become the words a controller says.

        "runway 13"      -> "runway one three"      not "thirteen"
        "heading 090"    -> "heading zero nine zero"
        "2,000 feet"     -> "two thousand feet"
        "133.0"          -> "one three three decimal zero"

    WHY THIS IS NOT A BLANKET DIGIT-SPELLER. The quantities do not share a
    convention: a runway is spelled digit by digit, an ALTITUDE is not --
    "two zero zero zero feet" is nobody's phraseology and "two thousand" is.
    So each quantity is recognised by the word beside it and rendered by the
    function that already knows its rules, in `core/say.py`, which is the same
    place the engine's own decisions are spelled. One convention, one home.

    A bare number with no unit is left alone. "Flight of 2", "in 5 minutes" and
    a squawk are not the same kind of thing, and a speller that guessed would be
    worse than one that declines.

    MEASURED BEFORE IT WAS BUILT: across 886 recorded agent transmissions, nine
    contained a digit and all nine were the "station calling ... say your
    callsign" template quoting the pilot's own words back. The agent has never
    written a clearance number in digits. This is therefore a GUARANTEE rather
    than a repair -- it makes the failure impossible instead of unlikely, which
    is the point of putting it where every transmission passes.
    """
    from marshall.core import say

    _SIDE = {"l": "left", "r": "right", "c": "center"}

    def rwy(m):
        side = _SIDE.get((m.group(3) or "").lower(), "")
        return f"{m.group(1)} {say.spell_rwy(m.group(2))}{' ' + side if side else ''}"

    def wind(m):
        out = f"{m.group(1)} {say.spell_hdg(int(m.group(2)))}"
        return f"{out} at {_digit_words(m.group(3))}" if m.group(3) else out

    def squawk(m):
        return f"{m.group(1)} {_digit_words(m.group(2))}"

    def hdg(m):
        return f"{m.group(1)} {say.spell_hdg(int(m.group(2)))}"

    def freq(m):
        return say.spell_freq(float(m.group(1)))

    def alt(m):
        lead = f"{m.group(1)} " if m.group(1) else ""
        n = int(m.group(2).replace(",", ""))
        return f"{lead}{say.spell_alt(n)} {m.group(3)}"

    def kt(m):
        return f"{say.spell_speed(int(m.group(1)))} {m.group(2)}"

    for pat, kind in _QUANTITY:
        text = pat.sub({"rwy": rwy, "hdg": hdg, "freq": freq, "alt": alt,
                        "kt": kt, "wind": wind, "squawk": squawk}[kind], text)
    return text
