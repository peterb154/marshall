"""Callsigns are two-level: a flight, and the aircraft inside it.

"Pony 1-2" is the second aircraft of the flight "Pony 1". Military flights work
up to four ships, and ATC deliberately treats them as ONE entity while they are
together -- one clearance, one altitude, lead answers for everybody -- because
talking to four aircraft to move four aircraft is a waste of a frequency. Once
they break up for individual approaches they become four ordinary singles.

So every callsign has to answer two questions:

    which flight is this?          -> Callsign.flight   ("Pony 1")
    is this addressed to all of them?  -> Callsign.is_flight

Both readings come off the same string, which is why this lives in one place
rather than being re-guessed at each call site. `intents.normalize_callsign`
remains the front door that turns what a pilot actually said into the canonical
form; this module gives that form structure.

    "Pony one one"      -> Pony 1-1   flight "Pony 1", member 1 (lead)
    "Pony one flight"   -> Pony 1     flight "Pony 1", no member -> ALL of them
    "Sockeye"           -> Sockeye    a bare name, its own flight of one
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Spoken digits, so a number the controller says lands back as a number.
_WORD = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine"]
# What a transcriber makes of a spoken digit. "niner" is the pilot's word; the
# rest are homophones, and they are here because the input is SPEECH and speech
# is what actually arrives. A live rehearsal turned "Pony one two" into "Pony
# one too" -- so the wingman's radio bound itself to "Pony 1", the FLIGHT, which
# is precisely the confusion this module exists to prevent. Whisper cannot know
# that "too" is a number; here, after a callsign name, it can only be one.
# "to" is deliberately NOT here. It is the commonest preposition in English and
# mapping it to a digit turned "a deliberately long transmission to hold the
# frequency" into an aeroplane called "Transmission 2" -- a ghost created by the
# very fix meant to stop them. "too" carries the same mis-hearing at a fraction
# of the risk, and the precision rule means a later correct callsign wins anyway.
_HOMOPHONES = {"niner": "9", "too": "2", "won": "1", "for": "4",
               "fore": "4", "ate": "8", "tree": "3", "fife": "5", "sex": "6"}
_SPOKEN = {w: str(i) for i, w in enumerate(_WORD)} | _HOMOPHONES
_SPOKEN_RE = re.compile(r"\b(" + "|".join(_SPOKEN) + r")\b", re.I)


def _digits(text: str) -> str:
    """Turn spoken digits into numerals so 'Pony one one' parses like 'Pony 1-1'.

    Callers normally hand us the canonical form, but a transcript reaches this
    code un-normalised often enough (and the cost of getting it wrong is a
    formation silently splitting into two entities) that it is worth absorbing
    here rather than trusting every path to normalise first.
    """
    return _SPOKEN_RE.sub(lambda m: _SPOKEN[m.group(1).lower()], text)


@dataclass(frozen=True)
class Callsign:
    """A parsed callsign. `member` is None when the call addresses the flight."""

    flight: str                 # "Pony 1" -- the flight, including its number
    member: int | None = None   # 2 -> the second aircraft; None -> the flight

    @property
    def is_flight(self) -> bool:
        """True when this names the whole formation rather than one aircraft."""
        return self.member is None

    @property
    def canonical(self) -> str:
        """The controller's key for this entity: 'Pony 1-2', or 'Pony 1'."""
        return self.flight if self.member is None else f"{self.flight}-{self.member}"

    @property
    def spoken(self) -> str:
        """How a controller says it out loud -- digits one at a time, never as a
        number ('Pony one two', not 'Pony twelve'). Polly reads this, and a dash
        would be pronounced."""
        words = []
        for tok in re.findall(r"[A-Za-z]+|\d", self.flight):
            words.append(_WORD[int(tok)] if tok.isdigit() else tok)
        if self.member is not None:
            words.append(_WORD[self.member])
        return " ".join(words)

    @property
    def spoken_flight(self) -> str:
        """Addressed to the whole formation: 'Pony one flight'.

        Deliberately NOT part of `spoken`: whether a callsign names a formation
        or one aeroplane is not knowable from the string -- 'Pony 2' is a lone
        ship in one mission and a four-ship in the next. Only the controller
        knows the size, so only the controller decides to say 'flight'."""
        return f"{self.spoken} flight"

    def member_callsign(self, n: int) -> str:
        return f"{self.flight}-{n}"

    def members(self, size: int) -> list[str]:
        """The individual callsigns of a `size`-ship flight, lead first."""
        return [self.member_callsign(n) for n in range(1, size + 1)]


def parse(cs: str) -> Callsign:
    """Structure a canonical callsign. Tolerates the un-normalised forms too.

    The trailing number is the member; everything before it is the flight. A
    callsign with only ONE number is a flight designator addressing the whole
    formation ("Pony 2" = the Pony 2 flight), which is also the right answer for
    a lone aircraft -- a single ship is simply a flight of one.
    """
    cs = (cs or "").strip()
    if not cs:
        return Callsign("")

    # "Pony 1 flight" / "Pony one one flight" -- the word makes it explicit.
    explicit_flight = bool(re.search(r"\bflight\b", cs, re.I))
    cs = re.sub(r"\s*\bflight\b\s*", "", cs, flags=re.I).strip()
    cs = _digits(cs)

    name = re.match(r"([A-Za-z]+)", cs)
    if not name:
        return Callsign(cs)
    stem = name.group(1).capitalize()
    digits = re.findall(r"\d", cs[name.end():])

    if not digits:
        return Callsign(stem)
    if explicit_flight or len(digits) == 1:
        # Addressed to everyone, or a single-number designator (a flight of one).
        return Callsign(f"{stem} {''.join(digits[:1])}" if digits else stem)
    return Callsign(f"{stem} {digits[0]}", int(digits[-1]))


# Words that routinely sit in front of a number on the radio and are NOT
# callsigns. Without these, "level four thousand" reads as an aircraft called
# "Level 4" -- and if that is used to identify a transmitter, one number-carrying
# transmission overwrites who the controller thought was talking.
_NOT_A_NAME = {
    "level", "levels", "heading", "altitude", "runway", "thousand", "hundred",
    "angels", "channel", "maintain", "climb", "descend", "descending",
    "climbing", "passing", "squawk", "flight", "approach", "tower", "departure",
    "ground", "point", "at", "to", "and", "on", "of", "in", "for", "over",
    "number", "wind", "knots", "miles", "mile", "radial", "degrees", "time",
    "minutes", "seconds", "plus", "contact", "report", "cleared", "traffic",
    # Words that turn up immediately before a number in ordinary radio speech.
    # Without them the extractor invents an aeroplane out of a sentence: "I have
    # two aircraft" became "Have 2", and a garbled call bound a real radio to
    # "Waypoint 3" for the rest of a sortie. A callsign that IS one of these
    # words would be rejected, which is the right way round -- a miss leaves a
    # radio unidentified for one transmission, a false positive puts a ghost in
    # the holding stack and sequences real aeroplanes behind it.
    "have", "has", "with", "say", "says", "request", "requesting", "requests",
    "waypoint", "steerpoint", "position", "range", "bearing", "distance",
    "inbound", "outbound", "established", "holding", "turning", "leaving",
    "reaching", "through", "gear", "flaps", "fuel", "bingo", "engine", "angel",
    "checking", "check", "ready", "field", "visual", "missed",
    "transmission", "transmitting", "message", "call", "calling", "frequency",
    # Adjectives and participles that sit in front of "for", which is a digit.
    # "I am going to be busy for a minute" was answered as "Busy four".
    "busy", "ready", "standing", "looking", "waiting", "clear", "set", "good",
    # Verbs that take a number straight after them in ordinary speech. "I need
    # two more minutes" became an aeroplane called "Need 2" -- and a "Need 3"
    # reached a live separation stack, where real aircraft were sequenced behind
    # something nobody had ever flown.
    "need", "needs", "want", "wants", "got", "give", "take", "make", "see", "seen", "hear", "heard", "count", "counting", "about", "around",
    "another", "only", "just", "maybe", "like", "than", "then",
}

_CANDIDATE = re.compile(
    r"\b([A-Za-z]{3,})((?:[\s-]+(?:" + "|".join(_SPOKEN) + r"|\d))+)\b", re.I)


def extract_all(text: str) -> list[str]:
    """Every plausible callsign in a transcript, in the order spoken.

    Radio convention is "[who you are calling], [who you are], [message]", so
    the ORDER carries meaning and a caller who throws it away learns the wrong
    name. "Hoover one two, Hoover one one, join up" rebound the speaker to his
    own wingman, because the first callsign was the only one anybody looked at.
    """
    out = []
    for m in _CANDIDATE.finditer(_digits(text or "")):
        if m.group(1).lower() in _NOT_A_NAME:
            continue
        got = parse(m.group(0)).canonical
        if got not in out:
            out.append(got)
    return out


def speaker_in(text: str) -> str:
    """WHO IS TALKING, by the convention rather than by position.

    One callsign is his own. Two means he addressed somebody first and named
    himself second, which is exactly how a pilot calls his wingman -- and taking
    the first would bind his radio to the man he was calling.
    """
    found = extract_all(text)
    if not found:
        return ""
    return found[1] if len(found) > 1 else found[0]


def extract(text: str) -> str:
    """Pull the first plausible callsign out of a transcript, or "".

    Deliberately conservative. This feeds the controller's memory of who a radio
    is, so a false positive is worse than a miss: a miss just means "I still
    think you are who you were last time", while a false positive silently
    reassigns a transmitter to an aircraft that does not exist.

    Requires a number, so a bare name ("Sockeye, request approach") is NOT
    extracted -- there is nothing in the string to separate it from the field or
    the controller being addressed ("Batumi, request approach"). Military
    callsigns carry a number, and the cost of the miss is only that the radio
    stays unidentified until the agent correlates it properly.
    """
    for m in _CANDIDATE.finditer(_digits(text or "")):
        if m.group(1).lower() in _NOT_A_NAME:
            continue
        return parse(m.group(0)).canonical
    return ""


def flight_of(cs: str) -> str:
    """The flight a callsign belongs to -- 'Pony 1-3' -> 'Pony 1'."""
    return parse(cs).flight


def same_flight(a: str, b: str) -> bool:
    return bool(flight_of(a)) and flight_of(a) == flight_of(b)


if __name__ == "__main__":
    for s in ["Pony 1-1", "Pony 1-2", "Pony 1", "Pony 1 flight",
              "Pony one one flight", "Pony 2", "Sockeye", "Enfield11", ""]:
        c = parse(s)
        print(f"  {s!r:22} -> flight {c.flight!r:10} member {c.member!s:5} "
              f"canonical {c.canonical!r:10} spoken {c.spoken!r:22} as-flight {c.spoken_flight!r}")
