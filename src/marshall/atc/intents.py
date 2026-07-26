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
    REQUEST_BREAKUP = "request_breakup"   # "Pony 1 requesting break-up"
    REQUEST_VISUAL = "request_visual"     # "Pony 1 requests the visual"
    REPORT_CONDITIONS = "report_conditions"   # "affirm, we have visual"
    UNKNOWN = "unknown"             # hand to the LLM fallback, or ask again

    @classmethod
    def coerce(cls, value: str) -> "IntentKind":
        """A model's answer -> a kind, without ever raising.

        Structured output is not a guarantee: given an enum of seven values,
        Sonnet still returns 'report_approach' (a plausible blend of two real
        ones) often enough to matter. Raising there costs the whole transmission
        -- the bridge catches it and the controller falls silent with an empty
        directive -- when the honest answer is simply 'I did not understand',
        which the caller already knows how to handle by asking him to say again.
        """
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class Intent:
    kind: IntentKind
    callsign: str = ""
    altitude_ft: int | None = None
    confidence: float = 1.0
    transcript: str = ""
    # How many aircraft are in this flight, when the pilot says so ("flight of
    # four"). 1 means a single ship -- or that he did not say, which the
    # controller treats the same way until told otherwise. This is the ONLY way
    # the controller learns a formation is a formation, so a classifier that
    # misses it turns a four-ship into one aeroplane that never breaks up.
    flight_size: int = 1
    # Answer to "can you maintain visual separation?" -- True/False, or None if
    # the transmission was not about conditions at all. Only meaningful on a
    # REPORT_CONDITIONS intent, and it decides whether a whole flight may share
    # one holding level, so an unsure model must say None rather than guess.
    visual: bool | None = None


# JSON schema for a structured-output parser (Haiku today, Nova Sonic later).
# The model fills this in; it cannot say anything else. That is what keeps the
# LLM classifying rather than controlling.
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [k.value for k in IntentKind],
            # Spell the taxonomy out. Benching showed both Haiku and Sonnet
            # reading "level five thousand" as a check-in, because the enum NAME
            # says beacon and nothing told them a bare level report is the same
            # kind of thing. The names are for us; the model only sees this.
            "description": (
                "check_in: first contact on this frequency, a radio check, or "
                "'with you' -- he is announcing himself, not reporting a "
                "position.\n"
                "report_beacon: ANY position, altitude or progress report from an "
                "aircraft already working this controller -- 'over the beacon', "
                "'level five thousand', 'established inbound', 'turning "
                "outbound', 'passing four thousand', 'platform'. If he is telling "
                "you where he is or what he is doing, it is this one.\n"
                "report_missed: going around, overshooting, missed approach.\n"
                "report_landed: field or runway in sight, landing, down.\n"
                "request_approach: asking for the approach or to commence, "
                "without naming which one.\n"
                "request_visual: asking specifically for a VISUAL approach -- "
                "'request the visual', 'we'd like a visual to one three'. He "
                "wants to fly it himself. Distinct from report_landed: 'request "
                "the visual' is asking, 'field in sight' is reporting.\n"
                "request_breakup: asking to split a formation into individual "
                "aircraft.\n"
                "report_conditions: answering whether he can maintain VISUAL "
                "separation between his own aircraft -- 'affirm', 'we're VMC', "
                "'negative, in cloud', 'IMC'. Set `visual` on this one.\n"
                "unknown: unintelligible, or none of the above. Use it rather "
                "than inventing a value -- the enum above is exhaustive."),
        },
        "callsign": {"type": "string",
                     "description": "flight name plus its number as spoken digits, "
                     "dash-separated: 'Pony one one' -> 'Pony 1-1', 'Pony two' -> "
                     "'Pony 2'. Never merge digits into one number (not 'Pony 11')."},
        "altitude_ft": {"type": ["integer", "null"],
                        "description": "reported altitude in feet, or null"},
        "visual": {"type": ["boolean", "null"],
                   "description": "for report_conditions only: true if the pilot "
                   "says he CAN maintain visual separation / is VMC / has the "
                   "others in sight; false if he cannot / is IMC / in cloud; "
                   "null if the transmission is not about conditions."},
        "flight_size": {"type": "integer",
                        "description": "how many aircraft are in this flight, if "
                        "the pilot says so: 'flight of four' -> 4, 'Pony one "
                        "flight, three ship' -> 3, 'as a section' -> 2. Use 1 when "
                        "he does not say a number -- never guess a formation size "
                        "from the callsign alone."},
    },
    "required": ["kind", "callsign"],
}

LLM_SYSTEM = (
    "You are the ears of an approach controller, not the controller. "
    "Classify one pilot radio transmission into exactly one intent. Never invent "
    "a clearance, altitude, or instruction -- only report what the pilot said. "
    "Altitudes: 'four thousand' -> 4000, 'niner thousand' -> 9000. A callsign is "
    "usually a single word like 'Sockeye', sometimes a flight name plus a number "
    "like 'Pony 2'. Use it EXACTLY as spoken -- never add a number the pilot did "
    "not say (do not turn 'Sockeye, do you copy' into 'Sockeye 2'). A pilot asking "
    "for something (approach, a DME, a frequency) is request_approach if it is the "
    "approach, otherwise the closest report; a bare radio check is check_in.\n"
    "\n"
    "FORMATIONS. Military aircraft arrive in flights of up to four. 'Pony one "
    "one' is the LEAD of the flight 'Pony 1'; 'Pony one two' is his number two. "
    "'Pony one flight' addresses all of them -- report that as callsign 'Pony 1' "
    "with no member number. If the pilot states how many aircraft he has ('flight "
    "of four', 'three ship', 'a section'), put that in flight_size; it is how the "
    "controller learns to work them as one formation, so do not miss it and do "
    "not invent it. A pilot asking to split the formation into individual "
    "aircraft ('request break-up', 'we'd like to split up for individual "
    "approaches', 'breaking up now') is request_breakup, NOT request_approach.\n"
    "\n"
    "VISUAL SEPARATION. The controller asks a flight whether it can maintain "
    "visual separation between its own aircraft. An answer to that -- 'affirm', "
    "'affirmative, visual', 'we're VMC', 'negative, we're in cloud', 'IMC', "
    "'no joy on the others' -- is report_conditions, with `visual` true or "
    "false. Only set `visual` on that intent.\n"
    "\n"
    "ASKING FOR A VISUAL vs HAVING THE FIELD. These are one word apart and mean "
    "opposite things. 'Request the visual approach' is request_visual -- he "
    "wants to fly it himself and has not necessarily seen the field yet. "
    "'Field in sight', 'runway in sight', 'we have the field visual' is "
    "report_landed -- he is telling you he can see it. Getting this backwards "
    "either denies a pilot an approach he asked for, or clears one who is still "
    "in cloud."
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


def normalize_callsign(cs: str) -> str:
    """Canonical 'Flight D-D' callsign. Spoken digit runs and the classifier's
    run-together numbers both collapse the same way: 'Pony one one' and 'Pony 11'
    -> 'Pony 1-1'; 'Pony two' -> 'Pony 2'; a name with no number ('Sockeye') is
    left alone. Keeps the separation engine's key identical to what the agent says,
    so a stack never splits one pilot into two."""
    cs = (cs or "").strip()
    m = re.match(r"([A-Za-z]+)(.*)$", cs)
    if not m:
        return cs
    flight = m.group(1).capitalize()
    digits: list[str] = []
    for tok in re.findall(r"[A-Za-z]+|\d+", m.group(2)):
        if tok.isdigit():
            digits.extend(tok)                       # "11" -> "1","1"
        elif tok.lower() in _NUM:
            digits.append(str(_NUM[tok.lower()]))
    return f"{flight} " + "-".join(digits) if digits else flight


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
    # ASKING for the visual, before REPORT_LANDED claims the bare word. "I have
    # the field visual" and "request the visual" are opposite ends of the same
    # approach and one token apart, so the specific pattern has to win.
    (re.compile(r"(?:request|requesting|ready for|like|take|give me)"
                r"[^.]{0,20}?visual|visual approach", re.I),
     IntentKind.REQUEST_VISUAL),
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
    # A formation that has been split no longer names an aeroplane. Ask rather
    # than infer -- picking lead is a guess, and a controller who cannot tell two
    # men apart must not act as though he can.
    if ctl.ambiguous_after_breakup(cs):
        ctl.say_again_who(cs)
        return True
    match intent.kind:
        case IntentKind.CHECK_IN:
            ctl.check_in(cs, intent.flight_size)
        case IntentKind.REPORT_BEACON:
            ctl.report_beacon(cs, intent.altitude_ft, intent.flight_size)
        case IntentKind.REPORT_MISSED:
            ctl.report_missed(cs)
        case IntentKind.REPORT_LANDED:
            ctl.report_landed(cs)
        case IntentKind.REQUEST_APPROACH:
            ctl.request_approach(cs)
        case IntentKind.REQUEST_BREAKUP:
            ctl.request_breakup(cs)
        case IntentKind.REQUEST_VISUAL:
            ctl.request_visual(cs, field_in_sight=bool(intent.visual))
        case IntentKind.REPORT_CONDITIONS:
            if intent.visual is None:
                return False            # ask again rather than assume cloud
            ctl.report_conditions(cs, intent.visual)
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
