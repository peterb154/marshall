"""What reaches the radio, and what must never leave the room.

Three jobs that all answer the same question -- what does the pilot actually
HEAR -- and each of them was somewhere in the middle of the receive loop:

    route_tier                which model gets this turn
    simple_response           the answers that need no model at all
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


def simple_response(transcript: str) -> str | None:
    """Instant canned reply for the handful of calls where the rich agent adds
    nothing -- a radio check, a closing acknowledgement. Returns None for anything
    with substance, which goes to the agent. Deterministic simple responses inside
    the rich experience, at zero cost/latency."""
    from marshall.atc import callsign as C, intents
    m = re.search(r"\b([A-Za-z]+(?:\s+(?:one|two|three|four|five|six|seven|eight|"
                  r"niner|nine|\d+))+)", transcript, re.I)
    # SPOKEN, not canonical. This interpolated "Falcon 1-1" straight into
    # speech, and Polly reads the hyphen: it comes out "Falcon one TO one",
    # which a pilot hears as "Falcon one two one" and reports as the controller
    # not knowing who he is.
    #
    #     "batumi tower thought I was falcon 121 again.. approach never did that"
    #
    # Approach never did it because every other path spells the callsign with
    # .spoken. Only the canned replies -- a radio check, a closing
    # acknowledgement -- took the shortcut, and closing calls are exactly what
    # Tower gets. Verified through Polly and Whisper rather than guessed at.
    cs = intents.normalize_callsign(m.group(1)) if m else "Station calling"
    if m:
        cs = C.parse(cs).spoken or cs
    if _CHECK.search(transcript):
        return f"{cs}, loud and clear."
    if _CLOSE.search(transcript):
        return f"{cs}, roger, welcome, taxi to parking when ready, good day."
    return None

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
    return re.sub(r"\s{2,}", " ", text).strip()
