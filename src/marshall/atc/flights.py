"""A person is his handle. A flight has a name. Members have neither.

    "Sockeye is sockeye as a single. No matter what I'm flying. Always sockeye
     -- unless I'm flight lead - then the flight has a name and I can speak for
     the flight. While the flight is working together the members have no
     identity (as heard on the radio)."

    "Maybe apex1-1 is intra flight speak and never lands in atc"

[ARCH-4] / #42. Every identity failure of 28 July came from deriving a member's
radio identity from a flight number. "Falcon 1-1" and "Falcon 1-2" share a
flight, so a radar lookup on the flight handed two pilots each other's
position. A lead refused for want of a track let his wingman's radio take the
FLIGHT's name. A callsign a man had used an hour earlier separated him from
himself.

This removes the thing that breaks rather than guarding it. After this there
are exactly two kinds of name on an ATC frequency:

    A HANDLE       one person. "Sockeye". Unique, never spoken by us to mean
                   anything else, and true whatever he is flying.
    A FLIGHT NAME  one group. "Apex". Derived from nobody, owned by nobody in
                   particular, and gone when the group is.

Both are CLOSED SETS -- we know who is connected and what flights exist -- and
that is what makes matching speech against them safe, in exactly the way
matching an unbounded supply of English words never was.

A MEMBER NUMBER IS NOT A THIRD KIND. "Apex 1-2" is how the flight talks to
itself, and hearing it is evidence the transmission is NOT ADDRESSED TO THE
CONTROLLER. That is the whole reason this design is simpler than what it
replaces: the hardest case to resolve becomes a case there is no need to
resolve.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# "forming apex flight of three with shooter and andre"
# "forming apex with shooter and andre"
# "apex flight of two, sockeye and andre"
_FORMING = re.compile(
    r"\bform(?:ing|s|ed)?\s+(?:up\s+)?(?:as\s+)?([A-Za-z][A-Za-z'-]*)"
    r"(?:\s+flight)?(?:\s+of\s+\w+)?(?:\s+with\s+(.+))?$", re.I)

# The tail of a declaration: "shooter and andre", "shooter, andre and viper".
_SPLIT_NAMES = re.compile(r"\s*(?:,|\band\b|\bplus\b|&)\s*", re.I)

# "Apex 1-2", "Apex two" -- how a flight talks to itself.
_MEMBER = re.compile(r"^\s*([A-Za-z][A-Za-z'-]*)\s*\d+\s*-\s*\d+\s*$")


@dataclass
class Flight:
    """One group, while it exists."""
    name: str
    lead: str                                   # a handle
    members: list[str] = field(default_factory=list)   # handles, lead included
    formed_at: float = 0.0

    def has(self, who: str) -> bool:
        return _same(who, self.lead) or any(_same(who, m) for m in self.members)


def _same(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _match_handle(said: str, known: list[str]) -> str:
    """One spoken word against the people who are actually here.

    THE CLOSED SET IS THE WHOLE SAFETY ARGUMENT. Matching "shooter" against
    every word English can produce is the mistake this project spent two days
    undoing; matching it against the four people demonstrably connected is a
    lookup. Whisper mangling a name into something that is nobody's handle
    yields nothing, which is the correct answer.
    """
    want = re.sub(r"[^a-z0-9]", "", (said or "").lower())
    if not want:
        return ""
    exact = [k for k in known if re.sub(r"[^a-z0-9]", "", k.lower()) == want]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return ""                               # two people, no answer
    near = [k for k in known
            if want in re.sub(r"[^a-z0-9]", "", k.lower())
            or re.sub(r"[^a-z0-9]", "", k.lower()) in want]
    return near[0] if len(near) == 1 else ""


def parse_forming(said: str, speaker: str, known: list[str]) -> tuple[str, list[str], list[str]]:
    """Read a declaration. Returns (flight name, members, names not recognised).

        "Georgia Center, Sockeye -- forming Apex flight of three with Shooter
         and Andre"

    The speaker is always a member: he is the one declaring it, and a flight
    formed without the man who called it in would be nobody's.

    Unrecognised names are RETURNED RATHER THAN DROPPED, because a flight that
    quietly forms with two of the three people asked for is worse than one that
    fails -- the controller would be separating a group whose size he is wrong
    about. The caller asks about the missing man instead.
    """
    m = _FORMING.search((said or "").strip().rstrip("."))
    if not m:
        return "", [], []
    name = m.group(1).strip().title()
    members, unknown = ([speaker] if speaker else []), []
    for word in _SPLIT_NAMES.split(m.group(2) or ""):
        word = word.strip().strip(".,")
        if not word:
            continue
        got = _match_handle(word, known)
        if got and not any(_same(got, x) for x in members):
            members.append(got)
        elif not got:
            unknown.append(word)
    return name, members, unknown


def is_intra_flight(said: str, flight_names: list[str]) -> bool:
    """Is this the flight talking to itself?

    "Apex 1-2" is intra-flight and never lands in ATC, so hearing it is
    evidence the transmission is not addressed to the controller at all. Only
    for a flight we actually know: an unknown name in that shape is somebody's
    callsign in the old scheme, and refusing to hear him would be worse than
    the noise.
    """
    m = _MEMBER.match(said or "")
    if not m:
        return False
    return any(_same(m.group(1), n) for n in flight_names)


@dataclass
class Roster:
    """Which flights exist, and who is in them."""
    flights: dict[str, Flight] = field(default_factory=dict)

    def of(self, handle: str) -> Flight | None:
        """The flight this person is in, if any."""
        for f in self.flights.values():
            if f.has(handle):
                return f
        return None

    def form(self, name: str, members: list[str],
             now: float | None = None) -> tuple[Flight | None, str]:
        """Create a flight. Returns (flight, why not).

        A PILOT IS IN ZERO OR ONE FLIGHT, and it is refused rather than
        resolved: a man in two flights is separated twice, and the second
        answer is always wrong.
        """
        members = [m for m in members if m]
        if not name or not members:
            return None, "a flight needs a name and at least one member"
        if name.lower() in {n.lower() for n in self.flights}:
            return None, f"{name} already exists"
        for m in members:
            other = self.of(m)
            if other is not None:
                return None, f"{m} is already in {other.name}"
        f = Flight(name, members[0], list(members),
                   time.time() if now is None else now)
        self.flights[name] = f
        return f, ""

    def dissolve(self, name: str) -> list[str]:
        """Break it up. Everyone reverts to his handle and the name means
        nobody -- which is what real procedure does, and what
        Controller.ambiguous_after_breakup already assumes."""
        for key in list(self.flights):
            if _same(key, name):
                return self.flights.pop(key).members
        return []

    def leaves(self, handle: str) -> str:
        """One man drops out -- he landed, ejected, or left the slot.

        The flight survives losing a member, INCLUDING ITS LEAD: any member may
        speak for it, so a flight is not bound to one radio and does not end
        because one aeroplane went home. It ends when nobody is left.
        """
        f = self.of(handle)
        if f is None:
            return ""
        f.members = [m for m in f.members if not _same(m, handle)]
        if _same(f.lead, handle) and f.members:
            f.lead = f.members[0]
        if not f.members:
            self.dissolve(f.name)
            return f.name
        return ""

    def speaking_as(self, handle: str) -> str:
        """What ATC should call whoever just transmitted.

        The flight while he is in one, his own handle otherwise. Never a member
        number: that is intra-flight and does not reach here.
        """
        f = self.of(handle)
        return f.name if f is not None else (handle or "")

    def names(self) -> list[str]:
        return sorted(self.flights)
