"""Who a call was for, and whether he read back what he was given.

The radio is one shared room. Everything a pilot says arrives identically
whether he meant it for the controller, for his wingman, or for the tower at a
field two hundred miles away -- so before a turn can be worked at all, three
questions have to be answered from the words alone:

    addressed_to_another_aircraft   was this even for me
    addressed_to / readback_due     is this a read-back of what I just issued
    misnamed                        he called himself something he is not

REAL ATC ASSUMES THE CALL IS FOR IT, and that default is right: a controller who
demands his name first misses the pilot who is task-saturated, which is exactly
the pilot who needs him. So these are narrow tests for the cases where the
assumption is provably wrong, not a gate everything passes through.

`hook_frequency` is here because it answers the same shape of question about a
promise rather than a call -- WHICH frequency a scheduled thing belongs to.
"""

from __future__ import annotations

import os
import time

def addressed_to_another_aircraft(transcript: str, speaker: str,
                                  stations=()) -> str:
    """Whose name this call opens with, if it is somebody else's aeroplane.

    Real ATC assumes a pilot is talking to it -- which is why nobody says
    "Omaha Approach" on every transmission, and why ours answers everything on
    its frequency. But two aircraft occasionally talk to each other on it:

        "Pony one two, Pony one one, join up"

    A controller hears that, understands it is not his, and says nothing. The
    giveaway is the ADDRESSEE, and it is readable: a transmission opening with
    an aircraft callsign that is not the speaker's own is ship-to-ship. Opening
    with a station name, or with his own callsign, or with nothing, is a call to
    the controller exactly as before.

    Returns the addressee, or "" when the call is ours. Refuses to decide
    without knowing who is speaking: guessing that a transmission is not for us
    is worse than answering one that was not, because the pilot gets silence and
    no way to tell why.
    """
    from marshall.atc import callsign as C

    if not speaker or not transcript:
        return ""
    head = transcript.strip()[:44]
    for name in stations:                    # "Batumi Approach, ..." is ours
        if name and name.lower() in head.lower():
            return ""
    first = C.extract(head)
    if not first or not _plausible_callsign(first):
        return ""
    if C.parse(first).flight == C.parse(speaker).flight \
            and C.parse(first).canonical == C.parse(speaker).canonical:
        return ""                            # his own name: talking to us
    return first


# Names that are allowed to become an aeroplane on the strength of one
# transmission: the mission roster, plus anyone named on the command line.
# Everything else has to earn it -- see `_plausible_callsign`.
_heard_names: dict[str, int] = {}


def misnamed(bridge, ctl, claim: str, known: str, who: str,
             said: str = "") -> str:
    """What the controller says when a pilot uses a callsign nobody answers to.

        "if a pilot says 'falcon 1-1, approach' and there is no falcon 1-1 (a
         dcs/srs matching pilot ON the board) atc should say - falcon 1-1 I dont
         have you on the board or similar - even if he KNOWS it's sockeye.
         Sockeye screwed up by using Falcon1-1 on the radio and needs to be
         corrected."

    EVEN THOUGH WE KNOW, and that is the whole point. The radio tells us this is
    Sockeye and nothing about that is in doubt; what is wrong is the name he put
    on the air, and silently absorbing it teaches him it works. With one pilot
    up that is untidy. With four it is how a clearance ends up read back by the
    wrong man, because everybody on the frequency heard a callsign that belongs
    to nobody and each of them had to guess who it meant.

    DETERMINISTIC, and handed to the agent as words to voice rather than left to
    its judgement. Whether a name is on the board is a fact about the board --
    the same class as separation -- and an LLM asked "do you know a Falcon 1-1?"
    will find a way to be helpful about it.

    NAMES THAT ARE FINE: his own handle, the flight he is in, and anybody else
    actually on the frequency -- calling another pilot by name is ordinary radio
    and not his callsign. Everything else is a correction.

    Returns "" when there is nothing to correct, which is the normal case.
    """
    from marshall.atc import callsign as C
    if not claim:
        return ""
    # A MAN DOES NOT GIVE HIMSELF TWO CALLSIGNS IN ONE TRANSMISSION.
    #
    # This is the whole of #52 and it cost five corrections in one sortie:
    #
    #     "Write 305 to send 6,500 sockeye"       -> "Send six, I do not have
    #     "Clear to land one tree, sockeye"          you on the board"
    #     "305, 2000, slow into 250, sockeye"     -> "Into two zero, ..."
    #     "Go on to approach 124 decimal 425,     -> "Decimal four five, ..."
    #      sockeye"
    #
    # Every one is a fragment of a READ-BACK -- an English word that happened to
    # sit in front of a number we ourselves had just given him. The last of them
    # arrived immediately after a landing clearance: "Land one three, I do not
    # have you on the board."
    #
    # `_plausible_callsign` cannot tell them apart, and the comment on its edge
    # rule already suspected as much: any English word in front of a digit is a
    # candidate, and a read-back is made of our own words and numbers.
    #
    # But the transmission answers it. He said "sockeye", the radio says he is
    # Sockeye, and those agree -- so whatever else in the sentence looked like a
    # name is not a second aeroplane. A pilot using the WRONG callsign, which is
    # what this function is for, does not also use the right one.
    if said and known and _names_himself(said, known):
        return ""
    ok = {n.lower() for n in bridge.flights.names()}
    ok |= {n.lower() for n in known_flight_names()}
    for n in (known, who):
        if n:
            ok.add(n.lower())
    # Everybody the engine is actually working, so addressing a wingman by name
    # is not a correction.
    ok |= {r.get("callsign", "").lower() for r in ctl.board()}
    ok.discard("")
    c = C.parse(claim)
    if any(_matches_name(claim, n) or _matches_name(c.flight, n) for n in ok):
        return ""
    # SAID BACK TO HIM THE WAY HE SAID IT, so he can hear which words were the
    # problem. Then the name that will work, when we have one for him.
    said = c.spoken or claim
    if known:
        return (f"{said}, I do not have you on the board. "
                f"You are {C.parse(known).spoken} — use that callsign.")
    return f"{said}, I do not have you on the board. Say your callsign."


def _names_himself(said: str, known: str) -> bool:
    """Does this transmission contain the callsign this radio answers to?

    Matched on the FLIGHT NAME rather than the whole callsign, because a
    read-back ends "...sockeye" and not "...sockeye one one" -- a pilot drops
    the numbers when the controller has been talking to him for ten minutes,
    which is exactly the stretch of a sortie where this fired.
    """
    from marshall.atc import callsign as C
    name = (C.parse(known).flight or known).split()
    name = name[0].lower() if name else ""
    return bool(name) and name in (said or "").lower()


def _matches_name(a: str, b: str) -> bool:
    """Two names for one entity, allowing for how Whisper punctuates."""
    from marshall.atc import callsign as C
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    return a == b or C.parse(a).canonical.lower() == C.parse(b).canonical.lower()


def known_flight_names() -> set[str]:
    from marshall.core import route as R
    out = {n.lower() for n in getattr(R, "SQUADRON_CALLSIGNS", ())}
    out |= {n.strip().lower()
            for n in os.environ.get("MARSHALL_CALLSIGNS", "").split(",")
            if n.strip()}
    return out


# The channel the last transmission was on. A one-element list because it is
# written from the pilot thread and read from the scheduler thread, and a bare
# module global rebound in a closure is the kind of thing that works until
# somebody adds a `global` and it does not.


# What the controller last said, and who is owed an answer to a read-back.
#
# An IFR clearance is the one transmission on the whole frequency that MUST be
# read back and MUST be answered. Getting that right was left to the brief, and
# the brief lost: "readback correct" competes with the airborne rule that a good
# read-back is met with silence, and the airborne rule won often enough that
# Hoover read a clearance back on the ramp, got nothing, and had to ask "did you
# hear my read back?" -- after which he was told it was correct.
#
# So it stops being a matter of judgement. The bridge SEES the clearance go out,
# knows the next thing that pilot says is his read-back, and says so.

# How long a clearance stays outstanding. Long enough for a pilot to write five
# elements down and read them back; short enough that it is not still armed when
# he calls for taxi three minutes later.
READBACK_WINDOW_SEC = 150


def addressed_to(said: str) -> str:
    """Who the controller just spoke TO, off his own words.

    The FIRST callsign, not the speaker convention `callsign.extract` uses --
    that one takes the second name, which is right for a pilot saying "Batumi
    Approach, Pony one one" and exactly wrong for a controller saying "Pony one
    one, turn left". A controller leads with the addressee.

    Deliberately reports what he SAID rather than who we resolved, because the
    interesting failure is the two disagreeing: a reply that answers the right
    pilot by the wrong name is a different bug from one that answers the wrong
    pilot, and a log that records only our own conclusion cannot tell them
    apart.
    """
    from marshall.atc import callsign as C
    names = C.extract_all(said or "")
    return names[0] if names else ""


def is_a_clearance(said: str) -> bool:
    """Did we just issue an IFR clearance? Read off the words, because that is
    what a clearance IS -- there is no other transmission on this frequency that
    carries a squawk and a routing together."""
    low = (said or "").lower()
    return "squawk" in low and ("cleared to" in low or "as filed" in low)


def readback_due(bridge, callsign: str, now: float | None = None) -> bool:
    """Is this transmission the read-back of a clearance we just gave him?"""
    when = bridge.awaiting_readback.get(callsign)
    if when is None:
        return False
    return ((now if now is not None else time.time()) - when) <= READBACK_WINDOW_SEC


def hook_frequency(why: str, heard_on: dict, last_hz: float | None) -> float | None:
    """Which channel a promised callback is spoken on.

    A5, live: Hoover asked Georgia Center on 139 for a call in sixty seconds.
    The hook fired on time and the controller said "calling as requested" -- on
    124, the frequency the bridge happened to be started on. He waited eighty
    seconds on 139 and reported no callback, which from the cockpit is
    indistinguishable from a hook that never fired.

    So the frequency comes from the man it is owed to. The hook's own reason
    names him ("Call back Pony 1-1 as he requested on Georgia Center 139.0"), and
    the bridge already knows which channel it last heard that callsign on.
    Failing that, the last channel anybody spoke on -- a hook whose reason names
    nobody still has to be spoken where somebody is listening. Failing that,
    None, and the caller falls back to its own default.
    """
    from marshall.atc import callsign as C

    for cs in C.extract_all(why or ""):
        if cs in heard_on:
            return heard_on[cs]
    return last_hz


def _plausible_callsign(cs: str, said: str = "") -> bool:
    """May this name become an aeroplane the controller sequences?

    A name and a number is not enough, and six ghosts proved it: 21-2, Have 2,
    Waypoint 3, Need 3, Transmission 2, Busy 4. Each was fixed by adding a word
    to a denylist, which cannot converge -- any English word in front of a digit
    is a candidate, and one of those fixes CREATED the next ghost.

    Two things are enumerable where English words are not.

    The ROSTER: route.py knows the squadron and the command line adds visitors,
    so those names are aeroplanes on sight.

    And POSITION. A callsign opens a transmission -- "Hoover one one, request
    the approach", or "Batumi Approach, Hoover one one" after a station. Noise
    sits in the middle of a sentence: "I am going to be busy for a minute", "I
    have two aircraft in sight", "a deliberately long transmission to hold the
    frequency". Every ghost this project has produced was mid-sentence and every
    real callsign was in the first few words, which is not a coincidence -- it
    is how radio works.

    Repetition was tried first and is weaker: the same mis-hearing repeats
    happily if the pilot says the same phrase twice.

    The cost of being wrong is one transmission answered as "station calling".
    The cost of the old behaviour was a ghost at the head of a holding stack
    with real aeroplanes queued behind it.
    """
    from marshall.atc import callsign as C
    flight = C.parse(cs).flight
    name = flight.split()[0] if flight else ""
    if len(name) < 3 or not name.isalpha():
        return False
    if name.lower() in known_flight_names():
        return True
    if not said:
        return True          # no transcript to judge by; do not block on nothing
    # AT THE START OR AT THE END, because those are the two places radio
    # procedure puts a callsign:
    #
    #     "Batumi Approach, Falcon one one, request..."   addressing
    #     "Left zero nine zero, Falcon one one"           reading back
    #
    # Only the first was accepted, and the omission was doing real damage in
    # both directions. A pilot's own callsign at the end of a read-back was
    # rejected as noise -- so the aeroplane vanished from the board every time
    # he did the correct thing -- while our own words at the START of that same
    # read-back sat exactly where a callsign was expected and were let through.
    # The rule was precisely backwards for the commonest transmission there is.
    #
    # Three words at each end. "Batumi Approach, Hoover one one" puts a real
    # callsign third and that is the longest legitimate run-up; a fourth lets
    # "give me a minute two sort this out" in as "Minute 2".
    words = said.split()
    edges = " ".join(words[:3] + words[-3:]).lower()
    return name.lower() in edges
