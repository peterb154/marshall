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

# "request creation of Apex flight". The lead says a NAME and nothing else --
# no members, no count -- which is the whole reason this is simple: there is
# nothing in it for Whisper to get wrong.
# "request creation of Apex flight", "form Apex flight of two".
#
# THE WORD "FLIGHT" IS REQUIRED, and `establish` is not a creation verb.
# Both of those cost a live sortie on 31 July:
#
#     "Pony one one, established ON the final approach course"   -> flight "On"
#     "Pony one one, established INBOUND on the beam"            -> flight "Inbound"
#
# The second is a stock letdown call -- it is in this project's own default
# pilot script -- so every NDB approach was creating a flight named after
# whatever word followed "established". The flight then became the pilot's
# callsign via `speaking_as`, and the board carried TWO entries for one
# Mustang, which is what makes the separation engine engage: it started
# sequencing Andre against himself.
#
# "Establish" belongs to approaches, not formations; no pilot forms a flight
# with it. And the fix is a tighter GRAMMATICAL SLOT rather than a list of
# words to refuse, because [#40] measured that road to its end -- ordinary
# English "REPLACED the first class and cannot be blacklisted: the supply of
# English content words is unbounded". A flight is being created only when the
# man says so twice: a creation verb AND the noun.
# "request creation of Apex flight", "form Apex flight", and -- the way a
# pilot actually says it -- "create a flight called Rattler".
#
# THE ARTICLE IS NOT THE NAME. The optional `a\s+` was optional, so "create a
# flight called Rattler" fell through to capturing "a" and formed A FLIGHT
# CALLED "A". Live, 29 August, with two pilots: everything downstream then
# worked perfectly on the wrong name -- the clearance, the taxi, the take-off,
# all issued to "A flight" -- which is what made it hard to see. The name is
# the one thing in this transmission that carries information, and it was the
# one thing being thrown away.
# TWO PATTERNS, TRIED IN THIS ORDER, and the order is the point: as one
# alternation the general branch matches EARLIER in the sentence and wins with
# the article, so "create a flight called Rattler" resolved to "a" before the
# explicit name was ever considered.
_CALLED = re.compile(
    r"\bflight\s+(?:call\w*|nam\w*)\s+([A-Za-z][A-Za-z'-]*)", re.I)
_CREATE = re.compile(
    r"\b(?:creat\w*|form\w*)\s+(?:of\s+|a\s+|an\s+|the\s+)?"
    r"([A-Za-z][A-Za-z'-]*)\s+flight", re.I)

# Words that are never a flight name, however the sentence parses. An article
# captured as a name is a flight nobody asked for, and it is indistinguishable
# downstream from one somebody did.
_NOT_A_NAME = {"a", "an", "the", "my", "our", "this", "that", "new", "of"}

# "Andre, joining Apex", "join Apex flight", "Apex, joining".
_JOINING = re.compile(r"\bjoin(?:ing|s|ed)?\b", re.I)

# "separating from Apex", "breaking out of Apex flight", "detaching from Apex".
# Several words for it because a pilot in trouble says whichever comes first.
_LEAVING = re.compile(
    r"\b(?:separat\w*|break\w*\s+(?:out|away|off)|detach\w*|"
    r"depart\w*\s+the\s+flight|leav\w*)\b", re.I)

# "dissolve Apex flight", "disband Apex", "break up the flight".
#
# THE LEAD ENDING THE WHOLE FLIGHT, which is a different act from one member
# leaving it and had no parser at all. `Roster.dissolve` existed and nothing
# could ask for it, so on 29 August a lead said "would like to dissolve
# A-Flight, sockeye will be a singleton" twice, to two controllers, and stayed
# a flight. `_LEAVING` does not cover it: that is a member breaking HIMSELF
# out, and matching this there would have taken the lead out and left the
# formation standing with a wingman in it.
_DISSOLVE = re.compile(
    r"\b(?:dissolv\w*|disband\w*)\s+(?:the\s+)?"
    r"([A-Za-z][A-Za-z'-]*)", re.I)

# "Apex 1-2", "Apex two" -- how a flight talks to itself.
_MEMBER = re.compile(r"^\s*([A-Za-z][A-Za-z'-]*)\s*\d+\s*-\s*\d+\s*$")

# HOW CLOSE HE HAS TO BE. Formation distance, because that is what joining a
# formation means -- and because joining is the moment the controller stops
# separating him, so it had better be true.
JOIN_NM = 1.0

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


def _distance(a: str, b: str) -> int:
    """Single-character edits between two words. Small and dependency-free."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def near_name(said: str, flight_names: list[str]) -> str:
    """Which existing flight did he mean? "" when it cannot be told.

    THE CLOSED SET IS WHAT MAKES THIS SAFE, and it is the same argument the
    whole design rests on: matching a spoken word against unbounded English is
    a guess, and matching it against the two flights that exist is a lookup.
    Whisper turned "Apex" into "Abex" in rehearsal and a member was refused the
    flight he was formating on -- with exactly one flight airborne, "Abex" can
    only have meant that one.

    AMBIGUITY IS REFUSED RATHER THAN TIE-BROKEN, the same rule as
    `identity.unit_for_radio`. Two flights within a hair of what he said means
    we do not know which he wants, and putting a man in the wrong formation is
    worse than asking him to say it again.

    Only ever called on the word in the GRAMMATICAL SLOT -- the one after
    "joining" or "leaving" -- never scanned across the whole transmission. A
    fuzzy match anywhere in a sentence would eventually catch an ordinary word,
    and a flight name is short enough that some of them are one edit from real
    English.
    """
    word = (said or "").strip()
    if len(word) < 3:
        return ""
    exact = [n for n in flight_names if _same(word, n)]
    if exact:
        return exact[0]
    # One edit per four characters, so a four-letter name tolerates one slip
    # and nothing tolerates a wholesale substitution. "Bolt" against "Apex" is
    # four edits and stays the refusal it is meant to be.
    near = [n for n in flight_names
            if _distance(word.lower(), n.lower()) <= max(1, len(n) // 4)]
    return near[0] if len(near) == 1 else ""


def parse_create(said: str) -> str:
    """Read "Approach, request creation of Apex flight". Returns the name.

    A NAME AND NOTHING ELSE. It used to read a count as well, so the flight
    was not treated as one until that many had joined. Once the lead stopped
    naming his members that guard had nothing to protect -- every member joins
    on his own radio, so every member has been heard by construction -- and a
    count is one more thing Whisper can get wrong for no benefit.
    """
    text = (said or "").strip().rstrip(".")
    m = _CALLED.search(text) or _CREATE.search(text)
    if not m:
        return ""
    name = (m.group(1) or "").strip()
    if name.lower() in _NOT_A_NAME:
        return ""
    return name.title()


def parse_joining(said: str, flight_names: list[str]) -> tuple[str, str]:
    """Read "Approach, Andre, joining Apex". Returns (known flight, what he said).

    HE DOES NOT NEED TO SAY WHO HE IS. The identity ladder already knows which
    aeroplane is transmitting, so the only thing to find is which flight he
    means -- one word, against the flights that actually exist. Saying his own
    handle is good radio discipline and a cross-check, not something the system
    depends on.

    THE SECOND VALUE IS FOR THE REFUSAL ONLY. If he names a flight that does
    not exist he still deserves an answer -- "Shooter, unable, Foo flight
    doesn't exist" -- and that needs the word he said. Echoing a name back is
    safe in a way that ACTING on one is not: a mis-heard name in an apology
    costs nothing, and the same mis-hearing used to put him in a formation
    costs him his separation.
    """
    if not _JOINING.search(said or ""):
        return "", ""
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", said or "")
    for w in words:
        for name in flight_names:
            if _same(w, name):
                return name, name
    # Nothing known. Take the word after "joining" as what he probably meant,
    # for the refusal and for nothing else.
    m = re.search(r"\bjoin(?:ing|s|ed)?\b\s+(?:up\s+)?(?:with\s+)?"
                  r"([A-Za-z][A-Za-z'-]*)", said or "", re.I)
    if not m:
        return "", ""
    spoken = m.group(1)
    # THE WORD IN THE SLOT, matched against the flights that exist. Whisper
    # heard "Abex" for "Apex" in rehearsal and a member formating half a mile
    # off his lead was refused the flight he was already in.
    if (hit := near_name(spoken, flight_names)):
        return hit, hit
    return "", spoken.title()


def parse_dissolve(said: str, flight_names: list[str]) -> str:
    """"dissolve Apex flight" -> the flight to end, or "".

    THE WHOLE FLIGHT, not one member. Returns a flight the roster actually
    holds -- `near_name` so a mangled name still resolves -- because dissolving
    something nobody has is a no-op worth reporting rather than performing.

    A lead may dissolve his own flight and nobody else's; the caller checks
    that, because only it knows who is speaking.
    """
    m = _DISSOLVE.search(said or "")
    if not m:
        return ""
    # THE WORD IN THE SLOT, not the sentence. `near_name` is documented as
    # "only ever called on the word in the GRAMMATICAL SLOT -- never scanned
    # across the whole transmission", because a fuzzy match over a sentence
    # eventually catches ordinary English. "A-Flight" is one word to Whisper,
    # so the suffix comes off before the name is matched.
    word = re.sub(r"[-\s]*flight$", "", m.group(1).strip(), flags=re.I)
    if not word:
        return ""
    # AN EXACT NAME WINS OUTRIGHT. `near_name` is a fuzzy match and refuses a
    # single letter -- rightly, one character is one edit from everything --
    # but a flight really called "A" is not a guess when he said "A". That
    # happened: a mis-parsed creation made a flight called A, and the lead
    # could not dissolve the thing he had accidentally created.
    for known in flight_names:
        if (known or "").strip().lower() == word.lower():
            return known
    return near_name(word, flight_names)


def parse_leaving(said: str, flight_names: list[str]) -> str:
    """Read "Approach, Shooter separating from Apex flight".

    A member breaking HIMSELF out, which he must be able to do without the
    lead. A lost wingman who transmits is otherwise answered as the flight, so
    the controller vectors the LEAD -- the man who needs help gets none and
    somebody who did not ask gets turned. That is the case this exists for, and
    it is the case where the lead is least likely to be on the ball.
    """
    if not _LEAVING.search(said or ""):
        return ""
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", said or "")
    for w in words:
        for name in flight_names:
            if _same(w, name):
                return name
    # The word in the slot, near-matched against the flights that exist -- the
    # same allowance joining gets, and needed more here: a man breaking out is
    # usually the one having a bad day, and refusing him over one consonant
    # leaves the controller working him as part of a formation he has left.
    m = re.search(r"\b(?:separat\w*|break\w*|detach\w*|leav\w*)\b"
                  r"(?:\s+(?:out|away|off|from|of|with))*\s+"
                  r"(?:the\s+)?([A-Za-z][A-Za-z'-]*)", said or "", re.I)
    return near_name(m.group(1), flight_names) if m else ""


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

    def create(self, name: str, lead: str,
               now: float | None = None) -> tuple[Flight | None, str]:
        """Open a flight of one. The lead is in it; anybody may join later.

            "approach, request creation of Apex flight"
            "Roger sockeye, you are the lead of Apex flight. Members join when
             you are with him."

        NO SIZE. An earlier version had the lead declare how many, so the
        flight was not treated as one until that many had joined -- a state
        machine guarding against the lead naming men who had never spoken. Once
        he stopped naming anybody that guard had nothing left to protect: every
        member joins on his OWN radio, so every member has been heard by
        construction.

        So there is no count to mis-hear, no pending state, and a flight is a
        flight from the moment it exists.
        """
        if not name or not lead:
            return None, "a flight needs a name and a lead"
        if any(_same(name, n) for n in self.flights):
            return None, f"{name} already exists"
        other = self.of(lead)
        if other is not None:
            return None, f"{lead} is already in {other.name}"
        f = Flight(name, lead, [lead], time.time() if now is None else now)
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

    def join(self, name: str, handle: str,
             miles_from_lead: float | None = None) -> tuple[Flight | None, str]:
        """A pilot joining a flight, on his own radio and in the right place.

            "approach, Andre, joining apex"  ->  "Roger Andre, joined to apex"

        HE CAN ONLY JOIN HIMSELF, so a rogue join is impossible rather than
        something the lead sorts out afterwards, and there is no member list
        for anybody to mis-hear. It is also how a broken-out wingman comes back.

        AND HE HAS TO BE THERE. Joining means the controller stops separating
        him, so a man who says it from forty miles away would go unseparated
        and unwatched while believing he was somebody's wingman. One mile is
        formation distance: the radio call and the physical fact have to agree,
        which is the same rule as everywhere else here -- a claim matched
        against an authority rather than believed on its own.

        A distance we cannot measure is not a pass. If radar cannot see them
        both, the controller cannot confirm it and says so.
        """
        f = next((c for k, c in self.flights.items() if _same(k, name)), None)
        if f is None:
            return None, f"no flight called {name}"
        if f.has(handle):
            return f, ""                        # already aboard; not an error
        other = self.of(handle)
        if other is not None:
            return None, f"{handle} is already in {other.name}"
        if miles_from_lead is None:
            return None, (f"negative {handle}, radar does not show you both -- "
                          f"unable to confirm you are with {name}")
        if miles_from_lead > JOIN_NM:
            # The observed fact, then the rule. Same order as everything else
            # the controller says here: he is not being refused on a
            # technicality, he is being told what radar shows and what it takes.
            return None, (f"negative {handle}, radar shows you "
                          f"{miles_from_lead:.0f} miles from {name} -- you must "
                          f"be within {JOIN_NM:.0f} mile to join")
        f.members.append(handle)
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
        return f.name if f is not None else (handle or "")

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
