"""The seam between the audio layer and the controller brain.

Everything upstream -- Whisper, a regex grammar, Haiku, Nova Sonic -- exists only
to turn one pilot transmission into one Intent. Everything downstream is atc.py.
Because the contract is this small structured object, you can swap Whisper for
Nova or regex for Haiku without touching the state machine, and you can test the
brain in plain text (as atc.py's demo does).

The invariant: a parser CLASSIFIES, it never decides. An Intent carries what the
pilot said (who, what, what altitude); the controller alone decides what to do
about it. No clearance is ever produced here.

    regex (free, offline, instant)  --.
                                       +--> Intent --> dispatch() --> Controller
    Haiku / Nova (fallback, cloud) --'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from marshall.atc import controller as atc


class IntentKind(str, Enum):
    CHECK_IN = "check_in"           # "Pony 1 checking in"
    REPORT_BEACON = "report_beacon"  # "Pony 1 over the beacon, four thousand"
    REPORT_MISSED = "report_missed"  # "Pony 1 going around"
    REPORT_LANDED = "report_landed"  # "Pony 1 field in sight, landing"
    REQUEST_APPROACH = "request_approach"
    UNKNOWN = "unknown"             # hand to the LLM fallback, or ask again


@dataclass
class Intent:
    kind: IntentKind
    callsign: str = ""
    altitude_ft: int | None = None
    confidence: float = 1.0
    transcript: str = ""


# JSON schema for a structured-output parser (Haiku today, Nova Sonic later).
# The model fills this in; it cannot say anything else. That is what keeps the
# LLM classifying rather than controlling.
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string",
                 "enum": [k.value for k in IntentKind]},
        "callsign": {"type": "string",
                     "description": "flight and number, e.g. 'Pony 2'"},
        "altitude_ft": {"type": ["integer", "null"],
                        "description": "reported altitude in feet, or null"},
    },
    "required": ["kind", "callsign"],
}

LLM_SYSTEM = (
    "You are the ears of a radar-less approach controller, not the controller. "
    "Classify one pilot radio transmission into exactly one intent. Never invent "
    "a clearance, altitude, or instruction -- only report what the pilot said. "
    "Altitudes: 'four thousand' -> 4000, 'niner thousand' -> 9000. Callsigns are "
    "a flight name plus a number, e.g. 'Pony 2'."
)


# --- regex grammar (the cheap, offline path) --------------------------------

_NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "niner": 9}


def _callsign(text: str) -> str:
    """Normalise 'pony two' / 'Pony 2' / 'PONY-2' to 'Pony 2'."""
    m = re.search(r"([A-Za-z]+)[\s-]*(\d|" + "|".join(_NUM) + r")", text, re.I)
    if not m:
        return ""
    flight = m.group(1).capitalize()
    tok = m.group(2).lower()
    num = tok if tok.isdigit() else str(_NUM.get(tok, ""))
    return f"{flight} {num}".strip()


def _altitude(text: str) -> int | None:
    m = re.search(r"(\d{1,2})[,\s]*000|(\d{4,5})", text)
    if m:
        return int(m.group(1)) * 1000 if m.group(1) else int(m.group(2))
    # spoken: "four thousand [five hundred]"
    m = re.search(r"(" + "|".join(_NUM) + r")\s+thousand"
                  r"(?:\s+(" + "|".join(_NUM) + r")\s+hundred)?", text, re.I)
    if m:
        ft = _NUM[m.group(1).lower()] * 1000
        if m.group(2):
            ft += _NUM[m.group(2).lower()] * 100
        return ft
    return None


_RULES = [
    (re.compile(r"check|with you|on frequency", re.I), IntentKind.CHECK_IN),
    (re.compile(r"missed|going around|go around|overshoot", re.I),
     IntentKind.REPORT_MISSED),
    (re.compile(r"land|field in sight|runway in sight|visual", re.I),
     IntentKind.REPORT_LANDED),
    (re.compile(r"request.*approach|ready for approach", re.I),
     IntentKind.REQUEST_APPROACH),
    (re.compile(r"beacon|over the|passing|inbound|holding|level", re.I),
     IntentKind.REPORT_BEACON),
]


def parse_regex(transcript: str) -> Intent:
    cs = _callsign(transcript)
    if not cs:
        return Intent(IntentKind.UNKNOWN, transcript=transcript, confidence=0.0)
    for pattern, kind in _RULES:
        if pattern.search(transcript):
            alt = _altitude(transcript) if kind == IntentKind.REPORT_BEACON else None
            return Intent(kind, cs, alt, confidence=0.9, transcript=transcript)
    return Intent(IntentKind.UNKNOWN, cs, transcript=transcript, confidence=0.2)


def parse(transcript: str, llm=None) -> Intent:
    """Regex first; fall back to an injected LLM only when regex is unsure.

    `llm` is any callable (transcript, system, schema) -> dict, so this module
    stays agnostic about Anthropic vs Bedrock vs Nova -- see parse_with_llm for
    the expected shape.
    """
    intent = parse_regex(transcript)
    if intent.kind is not IntentKind.UNKNOWN or llm is None:
        return intent
    try:
        data = llm(transcript, LLM_SYSTEM, INTENT_SCHEMA)
        return Intent(IntentKind(data["kind"]), data.get("callsign", ""),
                      data.get("altitude_ft"), confidence=0.7,
                      transcript=transcript)
    except Exception:
        return intent           # keep the low-confidence regex result


# --- driving the controller -------------------------------------------------

def dispatch(ctl: atc.Controller, intent: Intent) -> bool:
    """Route one Intent to the controller. Returns False if unhandled, so the
    caller can ask the pilot to say again rather than guess."""
    cs = intent.callsign
    if not cs or intent.kind is IntentKind.UNKNOWN:
        return False
    match intent.kind:
        case IntentKind.CHECK_IN:
            ctl.check_in(cs)
        case IntentKind.REPORT_BEACON:
            ctl.report_beacon(cs, intent.altitude_ft)
        case IntentKind.REPORT_MISSED:
            ctl.report_missed(cs)
        case IntentKind.REPORT_LANDED:
            ctl.report_landed(cs)
        case IntentKind.REQUEST_APPROACH:
            ctl.request_approach(cs)
        case _:
            return False
    return True


if __name__ == "__main__":
    # Show the grammar coping with the sloppy phrasing Whisper actually returns.
    samples = [
        "Batumi, Pony 1 checking in",
        "Pony one with you",
        "Pony 2 over the beacon four thousand",
        "pony two, passing four grand at the beacon",     # 'grand' -> regex UNKNOWN
        "Pony 3 holding, niner thousand",
        "Pony 1 going around",
        "Pony 2 field in sight, landing",
        "Pony 4 request approach",
        "uhh Batumi Pony 3 is, uh, established",          # -> UNKNOWN, needs LLM
    ]
    for s in samples:
        it = parse_regex(s)
        alt = f" @{it.altitude_ft}" if it.altitude_ft else ""
        print(f"  {it.kind.value:16} {it.callsign or '?':8}{alt:8} "
              f"conf {it.confidence:.1f}  <- {s!r}")
