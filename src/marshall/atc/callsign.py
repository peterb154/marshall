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
_SPOKEN = {w: str(i) for i, w in enumerate(_WORD)} | {"niner": "9"}
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


def flight_of(cs: str) -> str:
    """The flight a callsign belongs to -- 'Pony 1-3' -> 'Pony 1'."""
    return parse(cs).flight


def same_flight(a: str, b: str) -> bool:
    return bool(flight_of(a)) and flight_of(a) == flight_of(b)


if __name__ == "__main__":
    for s in ["Pony 1-1", "Pony 1-2", "Pony 1", "Pony 1 flight",
              "Pony one one flight", "Pony 2", "Sockeye", "Enfield11", ""]:
        c = parse(s)
        print(f"  {s!r:22} -> flight {c.flight!r:10} member {str(c.member):5} "
              f"canonical {c.canonical!r:10} spoken {c.spoken!r:22} as-flight {c.spoken_flight!r}")
