"""Who is talking, decided by something other than what he said.

    "the fact that this can happen -- that there is some dictionary with ghost
     aircraft -- makes me concerned about the foundational architecture of what
     we've built... wait till there are 10 guys on."

[ARCH-2] / #40. The board was keyed on a string Whisper guessed at from audio,
and 846 recorded transmissions say what that costs: the extractor would bind a
radio to 37 distinct names, of which ten were aeroplanes. With one pilot up the
other 27 are ghosts, which is merely embarrassing. With four, names like
"Hammer 1-3" and "Pony 1-4" ARE aeroplanes, and the same mis-transcription
becomes a separation error nothing in the system reports.

THE RULE THIS MODULE EXISTS TO ENFORCE:

    An aeroplane exists because something that is not a voice says it exists.

Two things can say it, and they are the same two a real controller has:

    A RADAR TRACK      the sim states the unit, its type and its position. It
                       cannot be mis-heard because it was never spoken.
    A FILED PLAN       typed before the sortie, which is precisely what a
                       controller's strip is. A procedural controller with no
                       radar has only this -- and he is not working voices
                       either, he is working strips.

A callsign heard on the radio is a CLAIM. It is matched against those
authorities and it is never itself one. A claim that matches nothing does not
create an aeroplane; it produces "say again", which is a controller doing his
job.

WHY THE RADIO IS THE STRONGEST LINK, and the measurement that settles it. Radar
tagged the unit `362nd_sockeye` with five different callsigns across a week --
Pony 1-1, Hammer 1-1, Falcon 1-1 and two garbles -- because a callsign is a
POSITION and this pilot flew a different one each night (#38). The SRS client
name did not move: it was "Sockeye" every time, and it is a substring of the
unit name every time. So

    SRS GUID -> SRS client name -> sim unit -> track

is a chain with no microphone anywhere in it. That is the identity; the
callsign is a label hung on it for addressing him by.

WHAT THIS DOES NOT DO. It will not invent an aeroplane out of a confident guess.
When the chain does not close it says so and names the reason, because a
controller who cannot identify a pilot must ask, and an ATC that guesses at
identity is the thing being fixed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# One line of the radar picture:  362nd_sockeye [Pony 1-1] (P-47D-30): 4.1 nm ...
# The bracketed callsign is present only once something has already correlated
# him, so it is CORROBORATION and never the primary key -- believing it as
# primary is circular, and measuring that circularity is what killed the obvious
# version of this fix (it threw away 43% of legitimate bindings).
_SCOPE_LINE = re.compile(
    r"([^|\[\(]+?)\s*(?:\[([^\]]+)\])?\s*\(([^)]+)\)\s*:", re.I)


@dataclass(frozen=True)
class Unit:
    """One thing the sim says is flying."""
    name: str                  # the sim's unit name -- never spoken, never garbled
    callsign: str = ""         # what something has already correlated it to
    type: str = ""             # the airframe, which is where equipment comes from
    manned: bool = False       # is there a person in it? see `by_elimination`
    # THE SIM SAID SO, from its land/takeoff events -- not inferred from
    # altitude and speed. False means either "airborne" or "nothing has told
    # us", and the caller keeps its own fallback for the second; see
    # director/tools/events.py and [ARCH-3] / #41.
    on_ground: bool = False


@dataclass(frozen=True)
class Identity:
    """The answer, with its provenance attached.

    `authority` is the point of the whole exercise and is worth logging on every
    transmission: it says WHY we believe this is who is talking, and the day it
    reads "radio" for a pilot who should have been on radar is the day something
    upstream broke.
    """
    callsign: str = ""         # the label to address him by; "" means unknown
    track: str = ""            # the sim unit, when the chain reached one
    authority: str = ""        # radar | plan | roster | ""
    why: str = ""              # one line, for the log and for a human

    def __bool__(self) -> bool:
        return bool(self.callsign)


def units_on(scope: str) -> list[Unit]:
    """Parse the radar picture into units.

    Tolerant on purpose: the scope is prose assembled for an LLM to read, and a
    parser that throws on an unexpected line would take the identity of every
    aeroplane down with it.
    """
    out: list[Unit] = []
    for chunk in (scope or "").split("|"):
        m = _SCOPE_LINE.search(chunk)
        if not m:
            continue
        name = m.group(1).strip()
        if not name:
            continue
        # "(P-51D-30-NA, manned)" -- the airframe, and whether a person is in
        # it. The sim knows, because a client-occupied unit reports a player
        # name and an AI does not.
        kind = (m.group(3) or "").strip()
        low = kind.lower()
        manned = "manned" in low
        grounded = "on the ground" in low
        kind = kind.split(",")[0].strip()
        out.append(Unit(name, (m.group(2) or "").strip(), kind, manned, grounded))
    return out


def _key(s: str) -> str:
    """Squash a name to what two systems can agree on.

    "362nd_sockeye" and "Sockeye" are the same human; "362nd Shooter" and
    "Shooter" likewise. Case, spaces, underscores and squadron numbers are
    decoration that DCS and SRS decorate differently.
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def unit_for_radio(srs_name: str, units: list[Unit]) -> Unit | None:
    """The physical link: which aeroplane is this radio sitting in?

    SRS names a client after the human; DCS names the unit after the slot he
    took, and in practice one contains the other. Nobody speaks either of them,
    which is the entire point.

    AMBIGUITY IS REFUSED, not broken by a tie-break. Two units matching one
    radio means we do not know which aeroplane he is in, and picking the first
    is how a controller ends up vectoring somebody's wingman. A wrong identity
    is worse than none: none produces "say again", wrong produces a clearance
    for the wrong aeroplane.
    """
    k = _key(srs_name)
    if len(k) < 3:                    # too short to be evidence of anything
        return None

    # AN EXACT MATCH FIRST, and it is the normal case rather than a special one.
    # With DCS running, the SRS client takes its name from the DCS export -- a
    # pilot cannot set it independently -- so the radio's name and the name
    # radar prints are the SAME STRING, and the substring rule below is only
    # needed where decoration differs ("Sockeye" against "362nd_sockeye").
    #
    # Trying substrings first is not merely loose, it fails outright on names
    # that overlap: with "Hoover" and "Hoover2" both flying, each radio matches
    # BOTH units, the ambiguity rule refuses, and NEITHER pilot is identified.
    # Two squadron mates with similar handles is not an exotic case, and the
    # failure takes out the man whose name is a prefix as well as the one whose
    # name contains it.
    exact = [u for u in units if _key(u.name) == k]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None                   # two units with one name: see units_on

    hits = [u for u in units if k in _key(u.name) or _key(u.name) in k]
    return hits[0] if len(hits) == 1 else None


def _matches(claim: str, name: str) -> bool:
    return _key(claim) == _key(name)


@dataclass
class Registry:
    """What each radio has been resolved to, and how confidently.

    Kept per session. A radio that has been physically resolved ONCE stays
    resolved: he does not stop being in that aeroplane because the next
    transmission was clipped, and re-deriving identity from every garbled call
    is the behaviour being replaced.
    """
    by_guid: dict[str, Identity] = field(default_factory=dict)

    def forget(self, guid: str) -> None:
        """He changed slots. A callsign is a position, not a person (#38), so
        this has to be possible without an engineer -- see the acceptance
        criteria on that issue."""
        self.by_guid.pop(guid, None)

    def claimed_tracks(self, except_guid: str = "") -> set[str]:
        """Tracks another radio has already been resolved to."""
        return {i.track for g, i in self.by_guid.items()
                if i.track and g != except_guid}

    def by_elimination(self, guid: str, units: list[Unit]) -> Unit | None:
        """The aeroplane that must be his, because there is no other.

        A visiting pilot has to work with NOTHING set up in advance. His radio
        is one we have never heard, and his SRS name may look nothing like his
        DCS player name, so the name-matching chain does not close for him --
        and requiring somebody to file him a strip first is exactly the "set it
        up beforehand" this is meant to remove.

        But the sim still says how many PEOPLE are flying. If one human on the
        scope is unaccounted for and one radio is unidentified, there is no
        choice to make: that is him. This is not a guess, it is elimination,
        and it is the same reasoning a controller uses when one aeroplane
        answers on a quiet frequency.

        It refuses the moment it becomes a choice. Two unclaimed humans and an
        unknown radio is genuinely ambiguous -- and the correct behaviour then
        is to ask, which is what a controller does and what the caller falls
        through to.

        AI is excluded, which is the whole reason the sim's player name is
        carried through the radar picture: an aeroplane nobody is sitting in
        cannot be the one talking, and matching a radio to one would hand a
        pilot's clearances to a machine that never asked for them.
        """
        taken = self.claimed_tracks(except_guid=guid)
        free = [u for u in units if u.manned and u.name not in taken]
        return free[0] if len(free) == 1 else None

    @staticmethod
    def _label(spoken: str, prior: Identity | None, u: Unit,
               plans: list[str] | None) -> str:
        """What to CALL him, once we already know which aeroplane he is.

        Separate from identity on purpose, and the asymmetry is the point: the
        track is what gets separated, the label is only ever used to address
        him. So a wrong label is rude and a wrong track is dangerous, and they
        deserve different rules.

        WHAT HE CALLS HIMSELF WINS. `spoken` is not one transmission's guess --
        it arrives already voted across the whole sortie by
        `transmitter_callsign`, which weighs how often a radio has used a name
        against how recently. Real callsigns repeat and noise does not, and
        that vote is where the protection belongs.

        A SECOND LAYER OF PROTECTION HERE WAS A REAL OUTAGE. It refused any
        rename that no filed strip agreed with -- so a pilot who checked in as
        Pony 1-1, then flew as Falcon 1-1 and said so a dozen times, stayed
        Pony 1-1 forever. Radar had tagged his track "Falcon one one", the
        engine went looking for "Pony 1-1", found nobody, and told him he was
        not radar identified for the whole approach while the agent cheerfully
        vectored Falcon 1-1. Two brains working two different aeroplanes, which
        is the exact failure this module exists to prevent.

        The evidence for that guard came from replaying the RAW extractor, one
        transmission at a time, with no vote in front of it. The live path has
        never worked that way. It was a fix for a problem this code did not
        have, and it cost an approach.
        """
        known = (prior.callsign if prior else "") or u.callsign
        # Nothing said this time: keep the name he has been going by. This is
        # the case the guard was really for -- a clipped or wordless call must
        # not blank him.
        if not spoken:
            return known or u.callsign or u.name
        return spoken

    def resolve(self, guid: str, srs_name: str, spoken: str = "",
                scope: str = "", plans: list[str] | None = None,
                roster: list[str] | None = None) -> Identity:
        """Who is this, in order of how much the evidence can be trusted.

        The ordering IS the design, so it is worth reading as a ladder:

          1. RADAR, via the radio. No microphone in the chain at all. A garbled
             callsign cannot touch it and neither can a confident wrong one.
          2. A FILED PLAN he claims. Typed before the sortie, so the claim is
             being matched against a strip rather than believed on its own.
          3. AN AEROPLANE ALREADY ADMITTED that he claims. Somebody else's
             authority, borrowed -- weakest of the three, and only reachable
             when the first two have failed.
          4. Nothing. Say again.

        Note what is absent: a rung where a well-formed callsign that matches
        NOTHING becomes an aeroplane. That rung is the bug.
        """
        prior = self.by_guid.get(guid)
        units = units_on(scope)

        # 1. The physical chain. Re-run every time rather than trusted from
        #    cache, because he may have swapped slots -- but a prior physical
        #    resolution survives a sweep that simply did not paint him.
        u = unit_for_radio(srs_name, units)
        why = f"radio {srs_name!r} is in {{}} on radar"
        if u is None and (prior is None or not prior.track):
            # 1b. NOBODY ELSE IT COULD BE. A guest whose SRS name and DCS name
            #     do not resemble each other still gets identified, with
            #     nothing set up for him in advance -- which is the requirement.
            u = self.by_elimination(guid, units)
            if u is not None:
                why = ("the only person flying who is not already accounted "
                       "for is in {}")
        if u is not None:
            # His callsign is what he SAYS he is, once we know which aeroplane
            # is talking. That is safe in a way the reverse never was: the
            # label can be wrong without the identity being wrong, and a label
            # is only ever used to address him.
            label = self._label(spoken, prior, u, plans)
            ident = Identity(label, u.name, "radar", why.format(repr(u.name)))
            self.by_guid[guid] = ident
            return ident

        # 2. A claim against a filed plan.
        for label in plans or []:
            if spoken and _matches(spoken, label):
                ident = Identity(label, "", "plan",
                                 f"claimed {spoken!r}, and {label!r} is filed")
                self.by_guid[guid] = ident
                return ident

        # 3. A claim against somebody already admitted.
        for label in roster or []:
            if spoken and _matches(spoken, label):
                ident = Identity(label, "", "roster",
                                 f"claimed {spoken!r}, already on the board")
                self.by_guid[guid] = ident
                return ident

        # A radio resolved earlier keeps its identity through a bad
        # transmission. This is not a fourth authority -- it is the one it was
        # granted before, and it does not decay because a gust ate a word.
        if prior is not None and prior.authority in ("radar", "plan"):
            return prior

        return Identity("", "", "",
                        f"{spoken!r} matches no track and no filed plan"
                        if spoken else "nobody named, and the radio is unknown")
