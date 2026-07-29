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

# "request creation of Apex flight of 3", "form Apex flight of two".
# The lead says a NAME and a SIZE. He does not name anybody, which is the whole
# reason this is simple: there is no member list to mis-hear.
_CREATE = re.compile(
    r"\b(?:creat\w*|form\w*|establish\w*)\s+(?:of\s+|a\s+)?"
    r"([A-Za-z][A-Za-z'-]*)(?:\s+flight)?"
    r"(?:\s+of\s+(\w+))?", re.I)

# "Andre, joining Apex", "join Apex flight", "Apex, joining".
_JOINING = re.compile(r"\bjoin(?:ing|s|ed)?\b", re.I)

# "Apex 1-2", "Apex two" -- how a flight talks to itself.
_MEMBER = re.compile(r"^\s*([A-Za-z][A-Za-z'-]*)\s*\d+\s*-\s*\d+\s*$")

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "a": 1, "an": 1}


def _count(word: str) -> int:
    w = (word or "").strip().lower()
    if w.isdigit():
        return int(w)
    return _WORD_NUM.get(w, 0)


@dataclass
class Flight:
    """One group, while it exists."""
    name: str
    lead: str                                   # a handle
    members: list[str] = field(default_factory=list)   # handles, lead included
    formed_at: float = 0.0
    # HOW MANY HE SAID, which is the only thing the lead declares about his
    # members. Until that many have joined, the flight is not yet a flight and
    # ATC still works everybody as individuals -- so a size that came out of
    # Whisper wrong is visible at once rather than leaving the controller
    # believing he is separating three aeroplanes when he is separating two.
    size: int = 0
    # ...and once that many have joined, IT STAYS A FLIGHT. Latched rather than
    # recomputed, because a formation does not stop being one when a member
    # lands or is shot down -- recomputing from the declared size would drop
    # the survivors back to individuals at the worst possible moment, which is
    # the moment they most need to be worked as one.
    formed: bool = False

    def has(self, who: str) -> bool:
        return _same(who, self.lead) or any(_same(who, m) for m in self.members)

    @property
    def complete(self) -> bool:
        """Everybody the lead declared has joined, on his own radio.

        Reads the latch rather than recomputing. Set in `join`, at the moment
        the last man arrives -- computing it here would mean the answer changed
        depending on WHEN somebody happened to ask, and a flight that had lost
        a member would quietly report itself unformed.
        """
        return self.formed


def _same(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def parse_create(said: str) -> tuple[str, int]:
    """Read "Approach, request creation of Apex flight of three".

    A NAME AND A COUNT, and deliberately nothing else. An earlier version had
    the lead name his members -- "forming Apex with Shooter and Andre" -- which
    meant matching two or three spoken names against a roster, reporting the
    ones it could not place, and being wrong about the flight's size whenever
    it mis-heard one.

    Each pilot joins himself instead, so the only thing that can be mis-heard
    here is a number, and a number that comes out wrong is visible immediately:
    the flight never completes.
    """
    m = _CREATE.search((said or "").strip().rstrip("."))
    if not m:
        return "", 0
    return m.group(1).strip().title(), _count(m.group(2) or "")


def parse_joining(said: str, flight_names: list[str]) -> str:
    """Read "Approach, Andre, joining Apex". Returns the flight, or "".

    HE DOES NOT NEED TO SAY WHO HE IS. The identity ladder already knows which
    aeroplane is transmitting, so the only thing this has to find is which
    flight he means -- one word, matched against the flights that actually
    exist. Saying his own handle is good radio discipline and a useful
    cross-check; it is not something the system depends on.

    Which is why nobody adopts anybody any more. A man can only join himself,
    so a rogue join is not possible rather than being a thing the lead sorts
    out afterwards.
    """
    if not _JOINING.search(said or ""):
        return ""
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", said or "")
    for w in words:
        for name in flight_names:
            if _same(w, name):
                return name
    return ""


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

    def create(self, name: str, lead: str, size: int,
               now: float | None = None) -> tuple[Flight | None, str]:
        """Open a flight. The lead is in it; nobody else is, yet.

            "approach, request creation of Apex flight of 3"
            "Roger sockeye, you are now the lead of Apex flight of 3. Each
             member of apex flight check in to be joined"

        A PILOT IS IN ZERO OR ONE FLIGHT, refused rather than resolved: a man
        in two flights is separated twice and the second answer is always
        wrong.
        """
        if not name or not lead:
            return None, "a flight needs a name and a lead"
        if size < 1:
            return None, "say how many are in the flight"
        if any(_same(name, n) for n in self.flights):
            return None, f"{name} already exists"
        other = self.of(lead)
        if other is not None:
            return None, f"{lead} is already in {other.name}"
        f = Flight(name, lead, [lead], time.time() if now is None else now,
                   size=size, formed=(size == 1))
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

    def join(self, name: str, handle: str) -> tuple[Flight | None, str]:
        """A pilot joining a flight, on his own radio.

            "approach, Andre, joining apex"  ->  "Roger Andre, joined to apex"

        HE CAN ONLY JOIN HIMSELF. There is no way to add somebody else, which
        is why there is no adoption, no rogue join to sort out in the debrief,
        and no member list for anybody to mis-hear. It is also how a broken-out
        wingman comes back -- rejoining is this, not a case of its own.
        """
        f = next((c for k, c in self.flights.items() if _same(k, name)), None)
        if f is None:
            return None, f"no flight called {name}"
        if f.has(handle):
            return f, ""                        # already aboard; not an error
        other = self.of(handle)
        if other is not None:
            return None, f"{handle} is already in {other.name}"
        if f.size and len(f.members) >= f.size:
            return None, f"{name} is already a flight of {f.size}"
        f.members.append(handle)
        if f.size and len(f.members) >= f.size:
            f.formed = True
        return f, ""

    def leaves(self, handle: str) -> str:
        """One man drops out -- he landed, ejected, or left the slot.

        The flight survives losing a member, INCLUDING ITS LEAD: any member may
        speak for it, so a flight is not bound to one radio and does not end
        because one aeroplane went home. It ends when nobody is left.
        """
        f = self.of(handle)
        if f is None:
            return ""
        # THE LEAD DIES AND THE FLIGHT DIES WITH HIM.
        #
        #     "And maybe if lead dies, the flight is dissolved? And the
        #      remaining members need to create (or recreate) a new one. Simple
        #      simple"
        #
        # Simpler than asking who is now, and more honest: the flight's
        # geometry IS the lead's track, so when he is gone the flight has no
        # position at all. Dissolving says that; promoting somebody pretends
        # otherwise and starts vectoring off an aeroplane nobody chose.
        #
        # It is also the conservative failure. The survivors revert to
        # individuals, which means the controller starts separating them --
        # exactly what you want for two men whose lead has just gone down --
        # and they re-form through the ONE path there is for forming, rather
        # than through a promotion rule that exists nowhere else.
        if _same(f.lead, handle):
            self.dissolve(f.name)
            return f.name

        f.members = [m for m in f.members if not _same(m, handle)]
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
        # ONLY WHEN IT IS COMPLETE. Between "creation of Apex flight of three"
        # and the third man joining, the ones who have joined are still
        # individuals to the controller -- because a flight that ATC treats as
        # one aeroplane while a member has never been heard is exactly the
        # thing this design removes.
        if f is not None and f.complete:
            return f.name
        return handle or ""

    def names(self) -> list[str]:
        return sorted(self.flights)


def lead_lost_call(flight: str, lead: str, survivors: list[str]) -> str:
    """What the controller says when a flight loses its lead.

        "Apex flight, approach, flight lead sockeye is no longer on radar.
         Apex flight is now dissolved. Andre, what are your intentions?"

    THE FACT, THEN THE CONSEQUENCE, THEN THE QUESTION -- in that order, and the
    order is the point. "No longer on radar" is what the controller actually
    observed; "dissolved" is what follows from it; and asking intentions is the
    only thing left to establish, because the survivors are individuals now and
    he has no idea what any of them wants.

    It also tells them something they may not know. A wingman whose lead has
    just gone down is busy, and may not have registered that he is on his own
    -- being told, by name, is how he finds out that ATC is now separating him.
    """
    who = ", ".join(survivors)
    tail = f" {who}, what are your intentions?" if survivors else ""
    return (f"{flight} flight, flight lead {lead} is no longer on radar. "
            f"{flight} flight is now dissolved.{tail}")
