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
from marshall.core import names as _names
# The sim's vocabulary for what a return IS, from the module that defines it.
# Pure and grpc-free on purpose -- `feed.tracks`, where `_CATEGORY` lives, needs
# a simulator to import and this is below it. See `feed/categories.py`.
from marshall.feed import categories as _cat
from dataclasses import dataclass, field

# One line of the radar picture:  362nd_sockeye [Pony 1-1] (P-47D-30): 4.1 nm ...
# The bracketed callsign is present only once something has already correlated
# him, so it is CORROBORATION and never the primary key -- believing it as
# primary is circular, and measuring that circularity is what killed the obvious
# version of this fix (it threw away 43% of legitimate bindings).
#
# THE COLON IS NOT ALWAYS THERE, and assuming it was blinded the ladder to
# every aeroplane in a formation. A lone contact reads "NAME (TYPE): 4.1 nm
# ..."; a formation collapses onto one line and reads "NAME (TYPE) IN FORMATION
# with OTHER — 2 ships, lead 13.5 nm ...", with no colon anywhere. So the lead
# did not parse, the wingman was named only inside the prose, and BOTH vanished.
#
# Which is exactly backwards for the flight model: forming up is what a pilot
# does immediately before asking to join a flight, and the act of forming up
# made both aeroplanes unidentifiable -- so neither could create a flight, join
# one, or break out. Found by the rehearsal, where Sockeye and Andre were
# spawned a few hundred yards apart to exercise the one-mile rule and thereby
# made themselves invisible, while Shooter ten miles away resolved perfectly.
_SCOPE_LINE = re.compile(
    r"([^|\[\(]+?)\s*(?:\[([^\]]+)\])?\s*\(([^)]+)\)\s*"
    r"(?::|(?=\s*IN FORMATION\b))", re.I)

# The other ships on a formation line, between "IN FORMATION with" and the dash
# that starts the lead's position. Each is a name, optionally followed by its
# own "(TYPE, manned, 0.3 nm)" -- see tracks._render. The parenthetical is
# optional because the bridge and the director are separate deployables and one
# can be restarted without the other; an older picture still yields the NAMES,
# which is what identity needs, and only the geometry is lost.
_FORMATION = re.compile(r"IN FORMATION with\s+(.+?)\s*(?:—|--|$)", re.I)
_OTHER_SHIP = re.compile(r"\s*([^(]+?)\s*(?:\(([^)]*)\))?\s*$")


# The whole "IN FORMATION with ... — N ships, lead " span, which is everything
# standing between a formation's lead and the position that belongs to him.
_FORM_SPAN = re.compile(
    r"\s*IN FORMATION with\s+[^|]+?\s*(?:—|--)\s*\d+\s+ships,\s*lead\s*", re.I)


def flatten_formation(scope: str) -> str:
    """Rewrite each formation line as an ordinary contact line for its LEAD.

    Every regex that reads a position out of the picture looks for the first
    "N nm" after the name. On a formation line the first one is now a WINGMAN'S
    OFFSET, so each of them would have read 0.3 nm as the lead's range from the
    field and put a flight three hundred yards off the runway.

    Rather than teach four separate patterns about formations, take the
    formation out of the line: what is left is exactly the shape they already
    parse, and the wingmen are read separately by `units_on`. One place to be
    right instead of four places to be kept in step.
    """
    return _FORM_SPAN.sub(": ", scope or "")


def _split_ships(text: str) -> list[str]:
    """Split "A (P-51D, manned, 0.3 nm), B (P-51D)" into its ships.

    ON COMMAS AT DEPTH ZERO. A plain split eats the ones inside the
    parenthetical, and the type field has two of them -- so "A (P-51D, manned)"
    became a ship called "A (P-51D" and another called "manned)", and a made-up
    aeroplane on the scope is worse than a missing one.
    """
    out, depth, cur = [], 0, []
    for ch in text or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [s for s in (p.strip() for p in out) if s]


@dataclass(frozen=True)
class Unit:
    """One thing the sim says is flying."""
    name: str                  # the sim's unit name -- never spoken, never garbled
    callsign: str = ""         # what something has already correlated it to
    type: str = ""             # the airframe, which is where equipment comes from
    manned: bool = False       # is there a person in it? see `by_elimination`
    # THE SIM SAID SO, from `Unit.inAir()` on the track row -- not inferred
    # from altitude and speed. THE SIM SAYS HE IS DOWN, and nothing else: it is
    # False for an aeroplane in the air AND for one nothing has been reported
    # about, which is why it is not the thing to ask when you mean "flying".
    on_ground: bool = False
    # ...AND THE THIRD ANSWER, WHICH USED TO BE DESCRIBED HERE AND NOT CARRIED.
    #
    # The comment on `on_ground` said "False means either 'airborne' or
    # 'nothing has told us', and the caller keeps its own fallback for the
    # second" -- and no caller did. There was nothing to keep a fallback ON: by
    # the time a Unit reached anybody there were two states where the database
    # had three, so `not on_ground` was the only test available and it answered
    # True for an aeroplane radar had never reported.
    #
    #     None   nothing has told us      the sweep has not reached him, the
    #                                     cache is cold, the scan is degraded
    #     True   the sim says he is up
    #     False  the sim says he is down  (and `on_ground` is True)
    #
    # `handoff._airborne` is the model: "he is flying, POSITIVELY -- not merely
    # 'not known to be down'". Anything that MOVES an aeroplane asks
    # `in_air is True`. [#149]
    in_air: bool | None = None
    # "ground" or "ship" when the sim says so, empty for aircraft. The streamer
    # has always known it and used to throw it away; without it nothing
    # downstream could tell a T-55 from an F-16 -- see audit #45, where a lone
    # pilot engaged the separation engine because four parked tanks counted as
    # traffic.
    category: str = ""


@dataclass(frozen=True)
class Identity:
    """The answer, with its provenance attached.

    `authority` is the point of the whole exercise and is worth logging on every
    transmission: it says WHY we believe this is who is talking, and the day it
    reads "radio" for a pilot who should have been on radar is the day something
    upstream broke.
    """
    # WHAT TO CALL HIM, and since 30 July it is never a word off the radio:
    # his HANDLE, out of the name the transport gives his radio or the sim
    # gives his aeroplane. A flight name replaces it upstream, in
    # `flights.speaking_as`, because being in a flight is a fact this module
    # has no view of.
    callsign: str = ""
    track: str = ""            # the sim unit, when the chain reached one
    authority: str = ""        # radar | plan | roster | ""
    why: str = ""              # one line, for the log and for a human
    # THE STRIP HE MATCHED, kept separately now that it is no longer his label.
    # A plan is filed under a callsign -- "Pony 1-1" -- and that string still
    # has to be joinable to him, or the board and the flight-plan table can no
    # longer be shown side by side.
    plan: str = ""
    # WHO KEYED THE MIC, which is NOT the same question as whether he is on the
    # board -- and conflating them is what made this module refuse to name a man
    # it could name perfectly well.
    #
    #     "if a pilot says 'falcon 1-1, approach' and there is no falcon 1-1 ...
    #      atc should say - falcon 1-1 I dont have you on the board - even if he
    #      KNOWS it's sockeye"
    #
    # Two states in one sentence. `who` is filled whenever the transport names
    # the radio, because an SRS client name arrives with the packet and is not a
    # voice. It NEVER admits an aeroplane: a man with a radio may be in a
    # spectator slot, in the tower, or at the menu, and "anyone with a radio is
    # an aeroplane" is the ghost problem in a new coat.
    #
    # `callsign` still means ADMITTED -- something that is not a voice says this
    # aeroplane exists -- and `__bool__` still asks that, so every refusal in
    # this module means what it always meant.
    who: str = ""

    def __bool__(self) -> bool:
        """Admitted, not merely audible. See `who`."""
        return bool(self.callsign)


def units_on(scope: str) -> list[Unit]:
    """Parse the radar picture into units.

    Tolerant on purpose: the scope is prose assembled for an LLM to read, and a
    parser that throws on an unexpected line would take the identity of every
    aeroplane down with it.
    """
    # STRUCTURE WHEN IT IS THERE ([#47]). A `Scope` carries the contacts the
    # prose was drawn from, and reading them removes the whole class of bug this
    # parser has produced: a formation line defeated EVERY regex at once, so both
    # aeroplanes in a formation vanished from the identity ladder -- which is
    # exactly the moment before a pilot asks to join a flight.
    #
    # `flatten_formation` was added to fix that and introduced the next one: it
    # deletes the wingmen before the position regexes see them, so no aircraft
    # but a lead has a position. Neither is needed here. Every ship in a
    # formation is its own contact, carrying its own type, manned flag, category
    # and position, because the collapse is a PRESENTATION and the data was
    # never collapsed.
    #
    # Duck-typed rather than imported: this module is below `agent_atc` in the
    # layering and must not reach up to it for a type.
    got = getattr(scope, "contacts", None)
    if got:
        # THE LABEL, NOT THE SIM'S UNIT NAME, and the distinction is the whole
        # identity chain. The prose printed the LABEL -- "362nd_sockeye" -- so
        # `Unit.name` has always meant the scope label, and everything built on
        # it means that too: `unit_for_radio` matches an SRS client name against
        # it, `handle` takes the human out of it, `_track_of` compares handles.
        #
        # Reading `name` instead fed it "Viper 1-4", the sim's slot name. The
        # symptom was cosmetic -- the board said CONTACT Viper 1-4 -- and the
        # damage was not: `unit_for_radio("Sockeye")` returned None, so the
        # strongest link in the system was severed and the pilot was identified
        # only by ELIMINATION, which works with one man up and fails with two.
        # He was being called "viper".
        # `in_air` IS READ, NOT RECONSTRUCTED. A contact dict that carries the
        # key states one of three things; one that does not carry it has told
        # us nothing, and `None` is what nothing looks like. Deriving it from
        # `not on_ground` here would rebuild the collapse this exists to
        # remove -- one line further down the pipe, where it would be harder to
        # find. Every producer in the tree emits it: `core/scope.contacts`,
        # `feed.tracks.contacts` and the degraded `feed.dcs.contacts_live`.
        # [#149]
        #
        # THE CATEGORY, AND WHY IT IS BLANKED FOR AN AEROPLANE. `Unit.category`
        # does not mean "what the sim called it"; it means WHAT IT IS IF IT IS
        # NOT AN AEROPLANE. Six readers in `agent_atc` are written on that
        # contract -- `not u.category` is "does it fly" at every one of them --
        # so this is the single place the sim's word becomes that answer.
        #
        # IT ASKS `feed.categories` NOW, because it used to compare against two
        # lower-case literals and `tracks.category` has a second writer:
        # `tools/ghost_flight.py` painted `Airplane`, and one capital letter made
        # every ghost a tank. `is_aircraft: false`, no derived callsign, no
        # state, no amber on the untracked panel, and `count_contacts` returning
        # nought so the separation engine never engaged. That is [#156], and its
        # filed diagnosis blames `_contact` for a comparison that was made here.
        return [Unit(c.get("label") or c.get("name", ""),
                     c.get("callsign", "") or "",
                     c.get("type", "") or "", bool(c.get("manned")),
                     on_ground=bool(c.get("on_ground")),
                     in_air=c.get("in_air"),
                     category="" if _cat.is_aircraft(c.get("category"))
                     else _cat.word(c.get("category")))
                for c in got if c.get("name")]

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
        # The same vocabulary the structured path reads, from the same module,
        # so a fifth category is one edit rather than two -- and the prose and
        # the data cannot come to disagree about what a tank is called.
        category = next((c for c in _cat.WORDS
                         if c not in _cat.FLYING and f", {c}" in low), "")
        kind = kind.split(",")[0].strip()
        # THE PROSE HAS TWO STATES AND CANNOT GET A THIRD, so this parser says
        # so out loud instead of leaving `in_air` at its `None` default. The
        # picture prints "on the ground" or it prints nothing; there is no
        # marker for "not known" because a controller does not say that about a
        # blip he can see. Absence of the marker has always MEANT airborne
        # here, and this is the fallback path -- a director too old to send
        # contacts, or a radar hiccup -- so turning every regex-parsed aircraft
        # into an unknown would disarm the event handoff for the one case that
        # is already degraded. Today's behaviour, stated rather than inherited.
        out.append(Unit(name, (m.group(2) or "").strip(), kind, manned,
                        on_ground=grounded, in_air=not grounded,
                        category=category))

        # THE REST OF THE FORMATION. They are real aeroplanes with real radios
        # and each one is somebody -- the lead's line is simply where the
        # picture chose to print them. Left out, the whole flight model dies at
        # the first thing a flight does.
        fm = _FORMATION.search(chunk)
        if not fm:
            continue
        for ship in _split_ships(fm.group(1)):
            om = _OTHER_SHIP.match(ship)
            if not om:
                continue
            oname = (om.group(1) or "").strip()
            if not oname or oname == name:
                continue
            spec = (om.group(2) or "")
            olow = spec.lower()
            ogrounded = "on the ground" in olow
            out.append(Unit(oname, "", spec.split(",")[0].strip(),
                            "manned" in olow, on_ground=ogrounded,
                            in_air=not ogrounded,     # same two states -- above
                            category=next((c for c in ("ground", "ship")
                                           if f", {c}" in olow), "")))
    return out


# ONE IMPLEMENTATION, IN `core.names`. The docstring and the reasoning moved
# with it -- the rule ("drop any chunk with a digit in it") is not specific to
# identity resolution, and the chart, the board and the diagnostics page all
# need the same answer.
handle = _names.handle


# ONE IMPLEMENTATION, IN `core.names`. This was written three times -- here,
# in `agent_atc`, and in `kneeboard.diag` -- plus a fourth in the diagnostics
# page's JavaScript, and two of the three were not the same function. The
# ASCII-only version here reduced "Соколов" to the empty string, which is below
# `unit_for_radio`'s evidence floor, so a Cyrillic-named pilot was disqualified
# from the physical chain and identified by elimination instead.
_key = _names.squash


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

    # THE HANDLE, before falling back to substrings. "Andre" and "362nd Andre"
    # are the same person and neither contains the other once the squadron tag
    # is in the way of a plain comparison. Still exact-on-the-handle, so
    # "Hoover" and "Hoover2" stay two people.
    h = _key(handle(srs_name))
    if h:
        by_handle = [u for u in units if _key(handle(u.name)) == h]
        if len(by_handle) == 1:
            return by_handle[0]
        if by_handle:
            return None

    hits = [u for u in units if k in _key(u.name) or _key(u.name) in k]
    return hits[0] if len(hits) == 1 else None


def _matches(claim: str, name: str) -> bool:
    return _key(claim) == _key(name)


def _names_plan(spoken: str, label: str) -> bool:
    """Did he SAY this plan's label, anywhere in the transmission?

    Not `_matches`, and that distinction is the fifth link of #167. `_matches`
    compares two whole strings, which is right for its own job -- a callsign
    claim that has already been pulled out of a sentence, against a roster
    name. Handed a whole transmission it is an equality test nobody can pass:

        "Kobuleti Clearance, Sockeye, request IFR clearance to Batumi,
         Domino please"   ==   "Domino"        ->  False, forever

    So `Identity.plan` bound only for a pilot whose entire transmission was the
    single word "Domino", which is not how anybody talks. Even with the label
    on the wire and in the set -- the four links repaired above -- the strip
    would still have been blank.

    A WHOLE WORD, not a substring. `squash` strips the decoration two systems
    disagree about, so the comparison happens between reduced forms; matching a
    substring would let a plan called "Dom" bind on "Domino", and a controller
    reading back the wrong sortie is what the label rules in `filing.py` exist
    to prevent.
    """
    key = _key(label)
    if not key:
        return False
    # A CONTIGUOUS RUN OF WORDS, because a label is not always one word.
    # `squash` folds "Colt 2-1" to "colt21", so a single-word scan would miss
    # every multi-word strip -- and those exist: the pre-#142 model keyed a plan
    # on a filed callsign, and `tests/test_identity.py` still flies one.
    #
    # Joining the run and comparing keys rather than comparing word by word is
    # what makes "Colt 2-1" match "Colt two dash one" reduced the same way; it
    # is the same trick `_matches` uses on a whole string, applied to a window.
    words = [w for w in re.split(r"[\s,.;:!?]+", spoken or "") if w]
    for i in range(len(words)):
        run = ""
        for j in range(i, min(i + 4, len(words))):
            run += words[j]
            if _key(run) == key:
                return True
    return False


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
    def _handle_for(u, srs_name: str, prior) -> str:
        """What to CALL him -- and nothing he says can move it.

            "that self-designated callsign crap was the cause of a lot of
             problems. And we should just rip it out now"

        THIS USED TO RETURN WHAT HE SAID. A spoken callsign, voted across the
        sortie, became his label and therefore the key the separation engine
        held him under. It cost, in order: ghost aeroplanes minted out of
        read-back fragments; a board keyed on strings Whisper guessed at; a
        pilot stuck as "Pony 1-1" for a whole approach after he started flying
        as Falcon 1-1, with radar tracking one aeroplane and the engine
        sequencing another; and a member designation -- "Apex 1-2" -- becoming
        a name the controller addressed a man by, which nobody does on the air.

        Every one of those is the same root: a LABEL derived from audio, in a
        system whose entire premise is that identity is not. The label is now
        derived from the same chain the identity is:

            GUID -> SRS client name -> sim unit -> track

        and `handle` takes the human out of either end of it. So a person is
        his handle, a flight has a name, and a member number is neither.

        WHAT HE SAYS IS STILL USED, and this is the distinction worth keeping
        straight: it is a CLAIM, matched against a filed strip or an aeroplane
        already admitted, and it decides WHICH identity he is -- see `resolve`.
        It just never decides what that identity is CALLED.

        THE PRIOR IS THE LAST RESORT, not a rung. It matters for a guest whose
        radio the transport named badly and whom radar has not painted: keeping
        yesterday's answer beats blanking a man mid-approach.
        """
        # ONE CASE, because there are two sources and they disagree by nature:
        # the sim calls him "362nd_sockeye" and SRS calls him "Sockeye". Left
        # alone, a pilot who checks in on a strip and is acquired by radar two
        # minutes later silently changes from "Sockeye" to "sockeye" -- and
        # every dict the bridge keys on that label (what frequency he was heard
        # on, which strip he matched, what the engine holds him under) misses
        # from then on. He would be told to check in on a channel he was
        # already talking on.
        got = handle(u.name) if u is not None else handle(srs_name)
        return (got or (prior.callsign if prior else "")).lower()

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
            # The human in the aeroplane, not the name he gave himself. Still
            # matched against a filed strip below, so the board can be joined
            # to the flight-plan table even though they are keyed differently.
            label = self._handle_for(u, srs_name, prior)
            ident = Identity(label, u.name, "radar", why.format(repr(u.name)),
                             plan=next((n for n in plans or []
                                        if spoken and _names_plan(spoken, n)), ""),
                             who=label)
            self.by_guid[guid] = ident
            return ident

        who = self._handle_for(None, srs_name, prior)

        # 2. GONE, 30 July: a claim matched against a FILED PLAN'S CALLSIGN.
        #
        #        "Flight Plans have position names like Pony 1-1, which
        #         represent a position in a flight. Its just eye candy for pilot
        #         to pilot discusson. ATC shouldnt ever care about that"
        #
        #    It produced an ordering that was exactly backwards. With no radar,
        #    saying "Pony 1-1" -- a position typed into a template when the
        #    mission was BUILT -- admitted him, while saying "Sockeye", which is
        #    who he is and the name SRS handed us before he opened his mouth,
        #    was refused. `director/tools/plans.py` reached the same conclusion
        #    about clearance delivery weeks ago and says it plainly: a
        #    template's callsign "matches a live pilot only by coincidence".
        #    Coincidence is not an authority.
        #
        #    A STRIP STILL IS one -- a procedural controller works strips -- but
        #    it has to be tied to him by ASSIGNMENT, at clearance delivery,
        #    rather than by a name he happened to say. Until that link exists he
        #    is audible and not admitted, which is a real state and is exactly
        #    what the controller is now made to say out loud.
        for name in roster or []:
            if spoken and _matches(spoken, name):
                # 3. A claim against somebody ALREADY ADMITTED. Still legitimate,
                #    and no longer a position name: the roster holds handles and
                #    flight names, so this matches "Sockeye" or "Apex" against
                #    aeroplanes something else already vouched for.
                ident = Identity(who or name, "", "roster",
                                 f"claimed {spoken!r}, already on the board",
                                 who=who)
                self.by_guid[guid] = ident
                return ident

        # A radio resolved earlier keeps its identity through a bad
        # transmission. This is not a fourth authority -- it is the one it was
        # granted before, and it does not decay because a gust ate a word.
        if prior is not None and prior.authority in ("radar", "plan"):
            return prior

        # NOT ADMITTED -- and we may still know exactly who it is. That is the
        # state the controller has to be able to voice: "Falcon one one, I do not
        # have you on the board", said to a man the radio identifies as Sockeye.
        return Identity("", "", "",
                        f"{spoken!r} matches no track and nobody on the board"
                        if spoken else "nobody named, and the radio is unknown",
                        who=who)
