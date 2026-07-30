"""Procedural (non-radar) approach control -- field-agnostic.

The controller is BLIND: no telemetry, no radar, no connection to DCS. Its whole
world model is what pilots report plus a clock. It cannot detect a false
position report, so you get exactly the service your navigation earned, and
separation is by ASSIGNED ALTITUDE -- it holds only if pilots fly their level.

The procedure is the SAME at every field. What differs is one ApproachProfile
(route.py): the controller name, the beacon, the altitude ladder, and the
escape-valve outer hold. Hand it a different profile and the identical state
machine runs a different field.

Stack rules, all forced by the letdown geometry (aircraft descend IN the hold,
so only one aircraft may be in the letdown block at a time):

  * ENTER at the top    -- a new arrival takes the lowest free slot above the
                           current holders.
  * STEP DOWN on vacate -- when the bottom aircraft commences its approach,
                           everyone above drops 1,000 ft.
  * ONE IN THE LETDOWN  -- the next approach is cleared only when the current
                           one reports landed or missed (event-based), with a
                           timeout so a silent aircraft cannot deadlock the stack.
  * MISSED -> FRONT      -- a go-around climbs to the missed altitude (below the
                           stack) and gets the NEXT approach. It never climbs
                           back through occupied levels, which is why front-of-
                           line is the only clean option on a single beacon.
  * REPEAT MISS -> BANISH -- after two misses it is sent to the outer hold to
                           re-sequence, so one aircraft cannot block the field.

Pure logic, no audio. Drive it from text now; wire Whisper + TTS over SRS later.
The state machine does not change.

    uv run python atc.py            # scripted four-ship arrival demo
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from marshall.atc import callsign
from marshall.core import route as R

CLEARANCE_TIMEOUT_SEC = 12 * 60      # silent aircraft -> assume clear, move on
REPORT_OVERDUE_SEC = 5 * 60          # prompt a quiet holder for a position
MAX_APPROACHES = 2                   # then banish to the outer hold


class Phase(Enum):
    UNKNOWN = auto()        # never checked in
    ENROUTE = auto()
    HOLDING = auto()
    CLEARED = auto()        # in the letdown
    MISSED = auto()         # front of the line, at missed_ft
    BANISHED = auto()       # sent to the outer hold
    LANDED = auto()


@dataclass
class Aircraft:
    """One entity the controller separates.

    Usually one aeroplane -- but while a formation is together it is ONE entity
    with `members` filled in, holding one level and answering to one clearance.
    That is not a shortcut: it is what the controller actually does, and it means
    the whole stack (enter at the top, step down on vacate, one in the letdown)
    needs no idea that formations exist. Break-up simply replaces this single
    entry with one per member.
    """
    callsign: str
    phase: Phase = Phase.UNKNOWN
    assigned_ft: int | None = None
    last_report_t: float = 0.0
    approaches: int = 0
    map_t: float | None = None       # computed station-passage (missed approach point) time
    # Cleared for a VISUAL approach: he is flying it himself from here. The
    # controller's job shrinks to spacing, and the talk-down must stop -- reading
    # ranges to a man looking at the runway is chatter over somebody busy.
    on_visual: bool = False
    # WHAT HE CAN RECEIVE -- a SET, not a rating. "adf", "tacan", "vor",
    # "ils", "ins", in any combination, from the airframe radar reports. In the
    # real world this is the equipment suffix on an IFR flight plan; here the
    # sim states the type, so nobody declares anything and no pilot can be
    # wrong about his own aeroplane.
    #
    # A set rather than a ladder because capability is not ordered: the DCS
    # F-16 has TACAN and an inertial platform and no ADF, so it cannot home the
    # NDB a 1944 Mustang homes easily. See equipment.py.
    #
    # None means nobody has told us yet.
    #
    # AT THE END on purpose. Four call sites build an Aircraft positionally, so
    # a field inserted anywhere above shifts every argument after it: putting
    # this after `phase` silently turned `Aircraft(m, Phase.HOLDING, level,
    # self.t)` into an aeroplane holding at zero feet, and twelve tests went red
    # with altitudes of 0.0 rather than anything about equipment.
    kit: frozenset | None = None
    # HAS RADAR ACTUALLY SEEN HIM? On a radar approach this is a precondition
    # for everything, not a nicety: "radar contact" is a specific thing a
    # controller says, and until he has said it nobody can be vectored,
    # sequenced or cleared.
    #
    # Without it the engine sequenced a SENTENCE. A mis-heard read-back became
    # an aircraft called "Maintained 2", took a level in the stack and the
    # letdown with it, and a real pilot was held as number two behind something
    # that had never been identified, never been on the scope, and could never
    # be contradicted -- because the engine is blind, and a thing that was never
    # on radar cannot leave it.
    radar_identified: bool = False

    # HOW MANY, which is all a flight report tells you. "Flight of four" is a
    # number; it is not four names, and the engine used to turn it into four by
    # minting "Pony 1-1" through "Pony 1-4" off the flight key. That worked
    # only while the key happened to look like a callsign -- and it stopped the
    # day identity started keying on handles, when the same code began putting
    # "Sockeye one" through "Sockeye four" on the air: four aeroplanes nobody
    # has and no pilot will answer to.
    ships: int = 1
    # WHO, and only ever from something that knows: a member is a person who
    # keyed his own microphone and was bound to his own handle. Empty is the
    # honest answer until then, and an honest empty is what stops the
    # controller reading out names he invented.
    members: list[str] = field(default_factory=list)

    @property
    def is_flight(self) -> bool:
        return self.ships > 1 or len(self.members) > 1

    @property
    def size(self) -> int:
        return max(self.ships, len(self.members), 1)


@dataclass
class Tx:
    """One transmission, and the channel it has to go out on.

    The frequency is not decoration. A WW2 set has four presets and the ARA-8
    homes only on the frequency it is tuned to, so the pilot is always listening
    on the channel of the beacon he is currently flying. Transmit a clearance on
    the wrong one and it is not heard at all.
    """
    to: str
    text: str
    t: float
    freq_mhz: float = 0.0
    controller: str = ""

    def __str__(self) -> str:
        chan = f" {self.freq_mhz:.3f}" if self.freq_mhz else ""
        return (f"[{int(self.t)//60:02d}:{int(self.t)%60:02d}]{chan} "
                f"{self.to}: {self.text}")


def spell_speed(kt: float) -> str:
    """180 -> 'one eight zero'. A speed, not a heading.

    Its own function rather than borrowing spell_hdg, which pads to three
    figures: a heading of ninety is "zero nine zero" and a speed of ninety is
    "nine zero", and a controller who pads a speed sounds like he is reading a
    heading. Rounded to the nearest ten, because nobody assigns 183 knots.
    """
    d = {c: w for c, w in zip("0123456789",
         ["zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine"])}
    return " ".join(d[c] for c in str(int(round(kt / 10.0)) * 10))


def spell_alt(ft: int) -> str:
    """7000 -> 'seven thousand', 3500 -> 'three thousand five hundred'.

    Five figures and up are read digit by digit -- "one zero thousand", the way
    a controller says it, not "10 thousand". Reachable since the stack's ceiling
    became the P-51's oxygen limit rather than a four-element list.
    """
    words = {0: "", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine"}
    th, hu = divmod(ft, 1000)
    # Under a thousand there is no "thousand" to say. This used to emit a
    # leading empty word -- " thousand seven hundred" for 700 -- which was
    # unreachable while every altitude in the system was a stack level, and
    # appeared the moment the approach started advising heights on final.
    if th == 0:
        return f"{words[hu // 100]} hundred" if hu else "zero"
    thousands = (words[th] if th < 10
                 else " ".join(words[int(c)] or "zero" for c in str(th)))
    out = f"{thousands} thousand"
    if hu:
        out += f" {words[hu // 100]} hundred"
    return out


def spell_minutes(mins: float) -> str:
    """"one minute", "two minutes", "one and a half minutes".

    Words, because everything here reaches Polly as text and a bare "1" is read
    out as a digit. Halves because a minute and a half is a real leg length and
    "one point five minutes" is not something a controller says.
    """
    if abs(mins - round(mins)) < 0.01:
        n = int(round(mins))
        names = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        return f"{names.get(n, str(n))} minute" + ("" if n == 1 else "s")
    if abs(mins - 1.5) < 0.01:
        return "one and a half minutes"
    return f"{mins:g} minutes"


def spell_hdg(deg: float) -> str:
    """A heading, digit by digit: 127 -> 'one two seven'. Polly reads a bare
    127 as 'one hundred twenty seven', which is not a heading.

    North is THREE SIX ZERO. No controller says "zero zero zero" -- it is not a
    heading anyone flies, and a pilot hearing it wonders what was garbled.
    """
    d = {c: w for c, w in zip("0123456789",
         ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])}
    hdg = int(round(deg)) % 360 or 360
    return " ".join(d[c] for c in f"{hdg:03d}")


def spell_time(t: float) -> str:
    """Minutes past the hour, spoken as digits: 'at four five'."""
    d = {c: w for c, w in zip("0123456789",
         ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])}
    return " ".join(d[c] for c in f"{(int(t) // 60) % 60:02d}")


def spell_freq(mhz: float) -> str:
    """132.0 -> 'one three two decimal zero', 128.5 -> 'one two eight decimal five'.

    Digit by digit, the way a controller reads a frequency, and ALWAYS with the
    decimal.

    This used to drop a trailing .0, on the reasoning that nobody says "one
    three two decimal zero". They do, and the pilot asked for it twice --
    first as a debug note in the middle of an approach, then plainly:

        "when the controllers give me frequencies, they should give it to me
         with full decimal, like 134.00"

        "Make frequency instructions include decimal always."

    The reason is that a bare "one two four" has to be RECOGNISED as a
    frequency from context, and a pilot reaching for a radio while flying an
    approach in cloud should not have to do that work. The decimal makes it
    unambiguous the moment it is heard, which is the whole job of the
    phraseology. Consistency also means he can read it back the same way every
    time, and a read-back that is always the same shape is one a controller can
    check at a glance.
    """
    d = {c: w for c, w in zip("0123456789",
         ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])}
    whole, _, frac = f"{mhz:.3f}".rstrip("0").rstrip(".").partition(".")
    out = " ".join(d[c] for c in whole)
    return out + " decimal " + " ".join(d[c] for c in (frac or "0"))


def spell_dur(sec: float) -> str:
    """A duration as aviation timing: 204 -> 'three plus two four'."""
    d = {c: w for c, w in zip("0123456789",
         ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])}
    m, s = divmod(int(round(sec)), 60)
    minutes = d[str(m)] if m < 10 else str(m)
    return f"{minutes} plus " + " ".join(d[c] for c in f"{s:02d}")


@dataclass
class Controller:
    profile: R.ApproachProfile
    aircraft: dict[str, Aircraft] = field(default_factory=dict)
    out: list[Tx] = field(default_factory=list)
    t: float = 0.0
    _letdown: str | None = None         # callsign currently in the letdown
    _letdown_since: float = 0.0
    # Flights that have been broken up. Remembered because a name that means
    # nobody still has to be RECOGNISED as meaning nobody -- and once the
    # break-up stopped putting members on the board, the only evidence a flight
    # ever existed left with it.
    _broken_up: dict = field(default_factory=dict)   # flight name -> members
    # WHICH STATION IS SPEAKING, set by the bridge from the frequency the
    # transmission arrived on. None means "not told", and everything behaves as
    # it always did -- the engine is blind by design and this is the one fact it
    # cannot do its job without:
    #
    #     "tower controls the runway and is the only one that can give takeoff
    #      and landing clearance"
    #
    # Which is standard everywhere, and was being broken on every sortie: the
    # engine reads a landing clearance out of `report_landed` regardless of who
    # is on the microphone, so Approach was clearing aircraft to land on a
    # runway that is not its to give.
    working: str | None = None

    # -- plumbing ----------------------------------------------------------
    # -- phraseology that follows the approach type ------------------------
    #
    # These used to be literals, and they were the beacon letdown's: "cleared
    # beacon approach", "hold at BATUMI as published", "report beacon inbound".
    # On a radar approach every one of them is wrong, and wrong in the worst
    # way -- it names a fix the aeroplane may have no receiver for. A pilot
    # heard the controller clear him for a beacon approach and report a beacon
    # inbound on a procedure that has neither, in an aircraft with no ADF.
    #
    # A vectored approach holds on ALTITUDE, not on a fix: stack them above the
    # weather where they can hold visually on a heading, and call them in one at
    # a time. That is what a controller with radar and a pilot with no navaid
    # actually do, and it is the only thing they CAN do.

    @property
    def _vectored(self) -> bool:
        return bool(getattr(self.profile, "vectored", False)
                    or getattr(self.profile, "kind", "") == "asr")

    def _approach_name(self) -> str:
        return "radar approach" if self._vectored else "beacon approach"

    def release(self, callsign: str) -> bool:
        """Take him off the board. Nobody is sitting in that aeroplane.

        A LEFTOVER ENTRY IS NOT MERELY UNTIDY. Two entries are what makes this
        engine engage at all, so one stale callsign turns a single-ship
        approach into a sequencing problem between a pilot and HIS OWN FORMER
        SELF: he flew as Falcon 1-1, came back an hour later as Pony 1-1, and
        was assigned ten thousand, held at five, and banished to Kobuleti --
        every one of those a correct answer to a question about two aeroplanes,
        asked about one.

        Driven by the sim's `player_leave_unit`, because vacating the slot is
        exactly when he stops being that aeroplane (#38, #41). Nothing else
        knows: he does not say goodbye, and a controller with no traffic has no
        reason to notice.
        """
        key = self._resolve(callsign)
        if key not in self.aircraft:
            return False
        if self._letdown == key:
            # He owned the approach. Free it or the next arrival waits behind
            # somebody who has gone home.
            self._letdown = None
            self._letdown_since = self.t
        self.aircraft.pop(key, None)
        return True

    def note_radar_contact(self, callsign: str, seen: bool = True) -> None:
        """Radar has this aircraft, or has lost him.

        The one fact that separates an aeroplane from a sentence. Set from the
        scope by the bridge; never inferred from anything a pilot says, because
        what a pilot says is exactly what produced the sentences.
        """
        ac = self.aircraft.get(self._resolve(callsign))
        if ac is not None:
            ac.radar_identified = bool(seen)

    def may_be_sequenced(self, ac) -> bool:
        """Can this aircraft take a place in the stack?

        On a radar approach, only if radar has him. On a beacon letdown the
        controller is procedural and works position reports, so being unseen is
        the normal condition and this cannot apply.
        """
        return ac.radar_identified or not self._vectored

    def identified(self) -> list[str]:
        """Aeroplanes something other than a voice has vouched for.

        Not the same as `self.aircraft.keys()`, and the difference is a real
        hole rather than a nicety. The identity ladder's weakest rung lets a
        pilot be recognised because the name he claims is already on the board
        -- borrowed authority. Handing it the raw dict would let a ghost
        corroborate ITSELF: mis-heard once it takes a slot, and from then on
        every repeat of the same mis-hearing matches an entry and is believed.
        A wrong name that gets more convincing each time it is said is the exact
        failure mode being designed out.

        So only aircraft radar has actually seen may vouch for anybody. On a
        procedural approach there are none, which is correct -- there the
        authority is the filed strip, and it is checked one rung higher.
        """
        return sorted(cs for cs, ac in self.aircraft.items()
                      if ac.radar_identified)

    def board(self) -> list[dict]:
        """Every entity the engine currently believes exists.

        There was no way to ask this. `tools/whats_out_there.py` asks the SIM
        what is flying; nothing asked the CONTROLLER what it thinks is flying,
        and the difference between those two answers is the entire ghost
        problem. An aeroplane called "Maintained 2" took a level in the stack
        and held a real pilot behind it for a whole approach, and the only
        evidence it had ever existed was a phrase in a transcript.

        Written to the flight recorder on every transmission, so a ghost is
        timestamped and attached to the words that minted it, rather than being
        reconstructed afterwards from prose. Cheap enough to do unconditionally:
        a handful of dicts, once per push-to-talk.
        """
        return [{"callsign": cs, "phase": ac.phase.name,
                 "assigned_ft": ac.assigned_ft, "identified": ac.radar_identified,
                 "members": list(ac.members), "approaches": ac.approaches,
                 # WHICH PROCEDURE, not just which phase. CLEARED means he is in
                 # the letdown; it does not say whether he is flying the
                 # surveillance approach or looking out of the window, and those
                 # are different jobs for the controller. The engine has always
                 # known -- it is what stops it reading him vectors he does not
                 # want -- and it was the one thing about him nothing could ask.
                 "on_visual": ac.on_visual,
                 "in_letdown": cs == self._letdown}
                for cs, ac in sorted(self.aircraft.items())]

    def note_equipment(self, callsign: str, kit) -> None:
        """Record what he can receive, from the airframe on radar.

        Separate from every other write on this class because it is not
        something a pilot AGREED to -- it is a fact about the aeroplane, and the
        controller reads it off the scope the same way he reads a range. It is
        also the only state here that never changes.
        """
        if kit is None:
            return
        ac = self.aircraft.get(self._resolve(callsign))
        if ac is not None:
            ac.kit = frozenset(kit)

    def _hold_phrase(self, alt_ft: int, kit=None) -> str:
        """Where to wait, said in a way he can actually fly.

        Three cases, and the aircraft decides which:

        A navaid and a fix -- hold as published. He can find the place.

        No navaid -- the controller describes a racetrack in headings, because
        headings are the one thing every aeroplane can fly: "hold at eight
        thousand, one eight zero outbound, three six zero inbound". He will
        drift; without a fix to hold over he cannot not drift. It does not
        matter. The levels are what keep him off the others, the clear air is
        what lets him see them, and the drift is a mile or two of empty sky.

        Precision here was the over-engineering. What has to be right is the
        SEQUENCING -- peeling one off at a time and vectoring him to the fix --
        and that is not made better by a tidier hold.
        """
        # TWO QUESTIONS, and they used to be one. Whether the FIELD has a
        # published hold, and whether THIS AEROPLANE can navigate to it. A P-51
        # with its homing adapter can; the Spitfire on the next level cannot,
        # and telling it to hold at BATUMI sends it somewhere it cannot find.
        #
        # CAN HE FIND THE PLACE? Two questions that used to be one: whether the
        # field publishes a hold, and whether THIS aeroplane can navigate to the
        # station it is held at. A P-51 homes the NDB; the Spitfire on the level
        # below cannot, and an F-16 -- better equipped in every other respect --
        # has no ADF either.
        #
        # `kit` of None means nobody has told us, and at a beacon field that
        # means able: a published hold is only ever offered where the approach
        # IS the beacon letdown, and anything flying that has already shown it
        # can home the beacon by being in the procedure.
        from marshall.atc import equipment

        navaid = getattr(self.profile.beacon, "navaid", "ndb")
        able = kit is None or equipment.can_hold_at(kit, navaid)
        if not self._vectored and able:
            return (f"hold at {self.profile.beacon.name} as published, "
                    f"maintain {spell_alt(alt_ft)}")
        # A SHAPE AND A CLOCK. He has no navaid, so he cannot hold OVER
        # anything -- and a heading with no leg time is not a hold, it is a
        # vector he will fly until somebody stops him.
        #
        #     "When ATC asks an airplane with no navaids to hold, it's going to
        #      need to help him... 'turn 180 heading fly 2 mins, then right turn
        #      to 360 and fly 2 minutes'. Right now he just says to hold."
        #
        # Everything he needs, in one transmission and in the order he flies it:
        # the level that keeps him off the others, which way he turns, and the
        # two headings with the time on each.
        out = self.profile.hold_outbound_hdg
        mins = getattr(self.profile, "hold_leg_minutes", 1.0)
        turns = getattr(self.profile, "hold_turns", "right")
        leg = spell_minutes(mins)
        return (f"hold at {spell_alt(alt_ft)}, {turns} turns, "
                f"{spell_hdg(out)} outbound {leg}, then "
                f"{spell_hdg((out + 180) % 360)} inbound {leg}, "
                f"expect vectors for the approach, I will call you")

    def _report_phrase(self) -> str:
        """What he should call next. Never a fix he cannot navigate to."""
        if self._vectored:
            return "report established on the final approach course"
        return f"report {self.profile.beacon.name} inbound"

    def say(self, to: str, text: str, ref: Aircraft | None = None) -> None:
        """Queue a transmission on the channel this aircraft is actually on.

        `ref` overrides the lookup for the one case where the addressee is no
        longer in the dictionary: a break-up announcement is addressed to the
        flight, and the flight entry has just been replaced by its members. Left
        to the lookup it would come out on the enroute channel -- which is
        precisely the channel the flight has already been told to leave.
        """
        ac = ref if ref is not None else self.aircraft.get(to)
        enroute = ac is None or ac.phase in (Phase.UNKNOWN, Phase.ENROUTE)
        banished = ac is not None and ac.phase is Phase.BANISHED
        name, freq = self.profile.station(enroute=enroute, banished=banished)
        self.out.append(Tx(to, text, self.t, freq, name))

    def _resolve(self, cs: str) -> str:
        """Which entity owns this callsign.

        A wingman who keys the mic while the flight is still together is the
        FLIGHT talking -- ATC does not open a second conversation with Pony 1-3.
        This also absorbs the commonest speech-to-text failure there is: Whisper
        hears "one two" for "one one" constantly, and without this a single
        garbled digit silently forks one aeroplane into two entries in the stack,
        each holding its own level.

        After break-up the members exist in their own right, so they resolve to
        themselves. A call still addressed to the FLIGHT is ambiguous and is not
        resolved by guessing -- see `ambiguous_after_breakup`.
        """
        c = callsign.parse(cs)
        key = c.canonical
        if key in self.aircraft:
            return key
        owner = self.aircraft.get(c.flight)
        if owner is not None and owner.is_flight:
            return c.flight                       # a member, still joined
        if c.is_flight:
            lead = f"{c.flight}-1"
            if lead in self.aircraft:
                return lead                       # broken up; the name means lead
        return key

    def get(self, cs: str) -> Aircraft:
        key = self._resolve(cs)
        return self.aircraft.setdefault(key, Aircraft(key))

    def ambiguous_after_breakup(self, cs: str) -> bool:
        """Is this the name of a formation that has already been split?

        Once a flight is broken up its name refers to nobody. Answering it by
        picking lead is an inference, and the wrong kind: the controller cannot
        actually tell which of two aeroplanes keyed the mic, and separating men
        he cannot tell apart is the failure this whole feature exists to
        prevent. It also had a visible symptom -- two Mustangs addressed as
        "Pony one" and "Pony one one", adjacent and confusable.

        A controller in this position asks. He does not guess and carry on.
        """
        c = callsign.parse(cs)
        if not c.is_flight or c.canonical in self.aircraft:
            return False
        # He was a flight and is not one now: the name refers to nobody, even
        # if none of his members has checked in yet. Without this the question
        # "who is Pony one?" got no answer at all in the window between the
        # break-up and the first individual call -- which is exactly when it is
        # most likely to be asked.
        if any(_n.lower() == c.canonical.lower() for _n in self._broken_up):
            return True
        return any(callsign.parse(k).flight == c.flight and k != c.canonical
                   for k in self.aircraft)

    def say_again_who(self, cs: str) -> None:
        """Ask him who he is, and do nothing else with the call."""
        c = callsign.parse(cs)
        members = sorted(k for k in self.aircraft
                         if callsign.parse(k).flight == c.flight)
        if not members:
            # He asked as a flight that has been broken up and whose members
            # have not checked in yet. They are still the answer to "which of
            # you is this?" -- offering no names at all would leave a pilot with
            # a question and no way to answer it.
            for _n, _m in self._broken_up.items():
                if callsign.parse(_n).flight == c.flight:
                    members = sorted(_m)
                    break
        if not members:
            # NOBODY HAS CHECKED IN YET, and there are no names to offer --
            # which used to be impossible, because the engine minted four the
            # moment a flight reported its size. It said "I have ." with an
            # empty list on the day that stopped. Ask the question without the
            # list: he knows his own callsign, and we do not.
            self.say(cs, f"{c.spoken_flight} is broken up for individual "
                         f"approaches — say your callsign and your intentions.")
            return
        names = ", ".join(callsign.parse(m).spoken for m in members)
        self.say(cs, f"{c.spoken_flight}, you are broken up for individual "
                     f"approaches — say your callsign. I have {names}.")

    def _addr(self, ac: Aircraft) -> str:
        """How to say this entity on the radio: 'Pony one flight' while they are
        together, 'Pony one one' once they are not. Spoken form, never the
        canonical 'Pony 1-1' -- that reaches Polly as 'Pony one dash one'."""
        c = callsign.parse(ac.callsign)
        return c.spoken_flight if ac.is_flight else c.spoken

    def _holders(self) -> list[Aircraft]:
        # Callsign breaks ties so a flight sharing one level under visual
        # separation still sequences lead first (Pony 1-1 before Pony 1-2).
        return sorted((a for a in self.aircraft.values()
                       if a.phase == Phase.HOLDING and a.assigned_ft is not None),
                      key=lambda a: (a.assigned_ft, a.callsign))

    def _free_slot(self) -> int | None:
        """Lowest stack level nobody holds -- a new arrival enters here, i.e.
        on top of the current holders (which always fill from the bottom up)."""
        taken = {a.assigned_ft for a in self._holders()}
        for ft in self.profile.stack_ft:
            if ft not in taken:
                return ft
        return None                     # stack full

    def _enter(self, cs: str, size: int = 1) -> Aircraft:
        """Find or create the entity for this call, as a formation if size > 1.

        A flight of four is keyed on the FLIGHT no matter who keyed the mic --
        "Pony one one, flight of four" and "Pony one flight" are the same entity.
        If the formation has already been broken up, its members own themselves
        again and a late size report must not re-merge them.
        """
        c = callsign.parse(cs)
        if size > 1:
            # ALREADY SPLIT, asked of the record rather than of a set of names
            # this function used to invent. `_broken_up` is the fact -- it is
            # written the moment a flight stops existing -- and consulting it
            # works whatever the members turned out to be called.
            if any(callsign.parse(n).flight == c.flight for n in self._broken_up):
                return self.get(cs)           # leave them alone
            ac = self.aircraft.get(c.flight)
            if ac is None:
                ac = self.aircraft[c.flight] = Aircraft(c.flight)
            ac.ships = max(ac.ships, size)
            return ac
        return self.get(cs)

    # -- pilot inputs ------------------------------------------------------
    def owns_the_approach(self) -> str | None:
        """Whose turn it is. None when nobody has been cleared.

        The sequencing IS the hard part of a radar approach -- peeling one off
        the stack at a time, vectoring him to the fix, and getting him in before
        the next one starts. The geometry does not know about queues and the
        queue does not know about geometry, so this is what joins them: the
        vectoring asks who owns the approach and works only him.
        """
        return self._letdown

    def waiting(self) -> list[str]:
        """Everyone who is not the one being worked. They hold; they are not
        vectored, because a vector is an invitation to start the approach."""
        return [cs for cs, ac in self.aircraft.items()
                if cs != self._letdown
                and ac.phase.name not in ("LANDED", "UNKNOWN")]

    def seen_on_final(self, cs: str, size: int = 1) -> bool:
        """Radar shows him already established. Enter him as such, not as new.

        This engine is BLIND -- it knows only what has been said to it -- while
        the vectoring half watches the scope, and until now the two never spoke.
        The consequence was heard on the radio: a flight established on the
        final approach course at ten miles and two thousand feet checked in, the
        engine had never heard the callsign, filed it as a fresh arrival, and
        assigned it the bottom of the holding stack -- climb to five thousand
        and hold. The vectoring half was simultaneously talking it down. The
        agent voiced both, in one transmission.

        Neither half was wrong about its own job. The gap was that the one
        making the sequencing decision could not see, and nobody handed it the
        picture. So: an aircraft the radar shows on the approach IS the
        approach, and it owns the letdown rather than queueing for it.

        Returns True if it did anything, so the caller can tell a seeding from
        an ordinary call.
        """
        # LOOK, DO NOT CREATE. `get` inserts, so asking it whether he is
        # already on the approach MADE an aeroplane called "Pony 1-1" before
        # `_enter` had a chance to make the FLIGHT -- and then the flight and
        # the stray both existed, with radar's clearance landing on the flight
        # and every later call resolving to the stray.
        #
        # It went unnoticed because `_enter` used to check "have any of this
        # flight's members already been entered?" against names it had itself
        # minted, so it found the stray, concluded the formation was already
        # split, and worked the stray instead. Two wrongs that happened to
        # cancel; removing the minting left only the first one.
        ac = self.aircraft.get(self._resolve(cs))
        if ac is not None and ac.phase in (Phase.CLEARED, Phase.LANDED):
            return False                       # already known to be on it
        ac = self._enter(cs, size)
        ac.phase, ac.last_report_t = Phase.CLEARED, self.t
        ac.assigned_ft = None                  # he is not in the stack
        self._letdown, self._letdown_since = ac.callsign, self.t
        return True

    def check_in(self, cs: str, size: int = 1) -> None:
        ac = self._enter(cs, size)
        ac.phase, ac.last_report_t = Phase.ENROUTE, self.t

        # OUT OF A FLIGHT THAT HAS JUST SPLIT.
        #
        #     "The flight splits, the members check in - response should be -
        #      radar contact, what are your intentions"
        #
        # And that is the whole answer for him. He is not a new arrival to be
        # told where to report -- he has been on this frequency for twenty
        # minutes inside a formation, so the standard check-in reply would
        # brief him on things he already has. What the controller genuinely
        # does not know is what he wants now that he is his own aeroplane,
        # because the break-up deliberately assigned him nothing.
        #
        # It also stops the controller assuming. Four aeroplanes coming out of
        # a flight may want four different things -- one for the approach, one
        # departing, one to hold for his wingman -- and the old flow gave all
        # four a holding level nobody asked for.
        if any(callsign.parse(n).flight == callsign.parse(cs).flight
               for n in self._broken_up):
            self.say(ac.callsign,
                     f"{self._addr(ac)}, radar contact, say intentions.")
            return
        here, here_freq = self.profile.station(enroute=True)
        tower, tower_freq = self.profile.station()
        fix = self.profile.arrival_fix
        if fix is not None and tower_freq and tower_freq != here_freq:
            # Report the fix he is CURRENTLY homing, and change channel when he
            # gets there. Telling him to contact Tower now would take him off
            # the arrival fix's frequency while he is still navigating to it --
            # the set homes whatever it is tuned to, so switching early does not
            # just change who he is talking to, it removes the needle he is
            # steering on. The handoff is a trigger he owns and flies to.
            call = (f"{self._addr(ac)}, {here}, radar not available, "
                    f"report {fix.name}. At {fix.name} contact {tower} "
                    f"{spell_freq(tower_freq)} -- you will be homing "
                    f"{self.profile.beacon.name} from there.")
        else:
            call = (f"{self._addr(ac)}, {here}, "
                    f"{self._report_phrase()}.")
        self.say(ac.callsign, call)

    # -- formations --------------------------------------------------------
    def _identify_phrase(self, members: list[str],
                         already_named: bool = False) -> str:
        """Ask each aeroplane to say who it is, now that they are separate.

        Until this moment the flight was one entity and one voice spoke for it,
        which is correct. The instant they are separated they are N aircraft the
        controller must be able to tell apart -- and he cannot, because the only
        names he has came off the radar, which labels tracks by whatever the sim
        called the units.

        Live, that produced a controller addressing two Mustangs as "Pony one"
        and "Pony one one": adjacent, confusable, and never agreed with anybody.
        The pilot's read was the right one -- "he probably should have asked for
        separate identification for the wingman on separation". A real controller
        establishes identity before he separates people; he does not infer it and
        hope.

        Named in order, and asked to answer in that order, because the sequence
        is what binds each voice to each track.

        Every aircraft in the break-up is named, not merely the ones still
        holding. The sequencer usually clears lead in the same breath, and a
        cleared aeroplane is exactly the one whose identity matters most -- he
        is the one about to be talked down.
        """
        if not members:
            # NOTHING TO NAME, and that is the normal case now. A flight report
            # is a number; the only thing that produces a name is a pilot
            # keying his own microphone. So ask for exactly that instead of
            # reading out a list the engine made up.
            return (" Each of you check in individually with your own callsign "
                    "so I can identify you.")
        if len(members) < 2:
            return " Report established."
        if already_named:
            # Their levels were just read out one by one, so every callsign has
            # already been said. Saying all four again inside the same
            # transmission is noise, and noise on a break-up is the last place
            # it belongs.
            return " Check in individually in that order so I can identify you."
        names = [callsign.parse(m).spoken for m in members]
        in_turn = ", ".join(names[:-1]) + f", then {names[-1]}"
        return (f" Check in individually in that order, {in_turn}, so I can "
                f"identify each of you.")

    def _break_up(self, ac: Aircraft) -> None:
        """Split a joined formation into individually-separated aircraft.


        This is the whole formation feature. Everything upstream treats the
        flight as one entity; here it becomes N, each with its own level, lead at
        the bottom so he lands first. From this moment on they are ordinary
        singles and the existing sequencing runs unchanged.

        The flight's own slot is released first so its members can reuse it --
        otherwise a four-ship holding at the bottom would step over its own level.
        """
        # SEPARATION INSIDE A FLIGHT IS NEVER THE CONTROLLER'S.
        #
        #     "It's the flights choice if they want to break up. Not atc
        #      problem... If the flight reports a breakup then 4 pilots check
        #      in, they all need to ask for the approach."
        #
        # Which is also the rule: separation between aircraft WITHIN a
        # formation rests with the flight lead and the pilots concerned (FAA JO
        # 7110.65). So there was never anything to negotiate, and the question
        # "can you maintain visual separation between your aircraft?" is gone
        # along with the tri-state field it set and the two ways of assigning
        # levels it chose between.
        #
        # The break-up now does ONE thing: the flight stops existing. Each
        # aeroplane is an ordinary arrival from that moment, checks in, asks
        # for the approach, and is separated through the same path as any
        # single -- which also deletes the capacity problem outright, because
        # there are no longer four levels to find before the split may happen.
        members = list(ac.members)
        self.aircraft.pop(ac.callsign, None)
        # AND IT GIVES UP THE LETDOWN. A flight that no longer exists cannot be
        # the one being talked down, and this was unreachable until 30 July --
        # the engine always split a formation on ARRIVAL at the fix, so it was
        # never cleared as a flight and never held the letdown when it split.
        # Now that a flight may fly the approach as a flight, lead can perfectly
        # well decide to break up half way down it, and `_letdown` was left
        # pointing at the dissolved entity: `_try_clear` found the slot taken by
        # a name no longer on the board, so all four members sat holding and
        # nobody was ever cleared. Silent, and it would have read as the
        # controller simply forgetting about them.
        if self._letdown == ac.callsign:
            self._letdown = None
        self._broken_up[ac.callsign] = members
        self.say(ac.callsign, ref=ac, text=
                 f"{self._addr(ac)}, break up for individual approaches."
                 f"{self._identify_phrase(members)}")
        # The flight was holding a slot and has just released it, so somebody
        # else may now be next for the letdown.
        self._try_clear()

    def request_breakup(self, cs: str) -> None:
        """Lead asking to split the formation up himself."""
        ac = self.get(cs)
        if not ac.is_flight:
            self.say(ac.callsign, f"{self._addr(ac)}, roger, no flight to break up.")
            return
        self._break_up(ac)

    def report_beacon(self, cs: str, altitude_ft: int | None = None,
                      size: int = 1) -> None:
        """Reported over the approach beacon."""
        ac = self._enter(cs, size) if size > 1 else self.get(cs)
        ac.last_report_t = self.t

        if ac.phase in (Phase.UNKNOWN, Phase.ENROUTE):
            # A FORMATION HOLDS AS ONE, and this used to break it up on
            # arrival, every time.
            #
            #     "if a flight wants to fly an approach in formation - they
            #      can. That's up to the flight lead."
            #
            # Which is the rule, and it was already the shape of everything
            # here: a joined flight IS one entity to this engine -- one level,
            # one clearance, one place in the letdown -- so there was never
            # anything to do differently. The break-up was the controller
            # reaching into a formation and dissolving it because he had
            # decided four ships could not fly one approach. That is the
            # lead's decision and nobody else's, and if he wants to bring four
            # aeroplanes down as one, that is a formation approach and it is
            # perfectly ordinary.
            slot = self._free_slot()
            if slot is None:
                self.say(ac.callsign,
                         f"{self._addr(ac)}, no holding available, remain clear.")
                return
            ac.phase, ac.assigned_ft = Phase.HOLDING, slot
            # Through `_hold_phrase`, not around it. This path wrote its own
            # "hold at BATUMI as published" and so told a pilot on a RADAR
            # approach to hold over a beacon he has no receiver for -- the exact
            # thing the phrase function exists to decide. Two ways of saying the
            # same thing is how one of them ends up wrong.
            self.say(ac.callsign,
                     f"{self._addr(ac)}, {self._hold_phrase(slot, ac.kit)}.")
            self._try_clear()
        elif ac.phase == Phase.CLEARED:
            # Established inbound on the beam: start the station-passage clock.
            # The pilot flies the MAP on a watch; ATC times the same number and
            # calls it as backup (aural station passage does not read in the sim).
            ac.map_t = self.t + self.profile.final_approach_sec
            self.say(ac.callsign,
                     f"{self._addr(ac)}, roger, station passage "
                     f"{spell_dur(self.profile.final_approach_sec)}, "
                     f"report field in sight or missed approach.")
        elif (altitude_ft and ac.assigned_ft
              and altitude_ft != ac.assigned_ft):
            # He is not where he was put. Reading his own number back to him is
            # how two aeroplanes end up at the same level in cloud -- especially
            # just after a break-up, when three wingmen have all just been given
            # a new altitude and one of them heard someone else's.
            verb = "descend and maintain" if altitude_ft > ac.assigned_ft else "climb and maintain"
            self.say(ac.callsign,
                     f"{self._addr(ac)}, negative, you are assigned "
                     f"{spell_alt(ac.assigned_ft)}, {verb} "
                     f"{spell_alt(ac.assigned_ft)}.")
        else:
            self.say(ac.callsign, f"{self._addr(ac)} roger, "
                                  f"{spell_alt(altitude_ft or ac.assigned_ft or 0)}.")

    def _do_missed(self, ac: Aircraft) -> bool:
        """Missed-approach state transition. Returns True if banished (2nd miss)."""
        ac.approaches += 1
        ac.last_report_t = self.t
        ac.map_t = None
        if self._letdown == ac.callsign:
            self._letdown = None
        if ac.approaches >= MAX_APPROACHES:
            ac.phase, ac.assigned_ft = Phase.BANISHED, self.profile.top_ft
            return True
        ac.phase, ac.assigned_ft = Phase.MISSED, self.profile.missed_ft
        return False

    def _missed_instruction(self, banished: bool) -> str:
        if banished:
            return (f"climb {spell_alt(self.profile.top_ft)}, proceed "
                    f"{self.profile.outer_hold.name}, contact "
                    f"{self.profile.outer_hold.sector or 'the outer hold'} "
                    f"{spell_freq(self.profile.outer_hold.freq_mhz or 0)}, hold, "
                    f"expect re-sequence. Traffic holding.")
        return (f"climb {spell_alt(self.profile.missed_ft)}, "
                f"return to the beacon. You are number one for the approach.")

    def report_missed(self, cs: str) -> None:
        ac = self.get(cs)
        banished = self._do_missed(ac)
        addr = self._addr(ac)
        prefix = f"{addr}, " if banished else f"{addr} roger, "
        self.say(ac.callsign, prefix + self._missed_instruction(banished))
        self._try_clear()

    def _station_passage(self, ac: Aircraft) -> None:
        """Beam time up with no landing: ATC hears it overhead and calls the
        missed. The pilot's own watch should already be prompting this -- the
        cone of silence is unreliable in the sim, so ATC backs the timing up."""
        banished = self._do_missed(ac)
        inst = self._missed_instruction(banished)
        self.say(ac.callsign, f"{self._addr(ac)}, heard a Mustang overhead, field is "
                              f"beneath you, go missed. " + inst[0].upper() + inst[1:])
        self._try_clear()

    def report_landed(self, cs: str) -> None:
        ac = self.get(cs)
        ac.phase, ac.last_report_t = Phase.LANDED, self.t
        ac.map_t = None
        if self._letdown == ac.callsign:
            self._letdown = None
        # THE RUNWAY IS TOWER'S. Anybody else who has the field in sight gets
        # sent to the man who can actually give him the runway, rather than a
        # clearance the speaker had no authority to issue. A pilot cannot tell
        # the difference on the radio, which is exactly why it matters: he lands
        # believing he was cleared, and Tower never knew he was there.
        twr = self.profile.station_for("tower")
        if self.working and twr is not None and self.working != "tower":
            self.say(ac.callsign,
                     f"{self._addr(ac)}, roger, field in sight, contact "
                     f"{twr.name} {spell_freq(twr.freq_mhz)} for landing.")
            self._try_clear()
            return
        # He has the field. What a controller owes him now is the CLEARANCE and
        # the wind -- not a verdict on whether the landing is assured, which is
        # the pilot's call and not a phrase a real controller uses.
        self.say(ac.callsign,
                 f"{self._addr(ac)}, roger, cleared to land runway "
                 f"{self.profile.runway or 'in use'}, {self._wind_phrase()}")
        self._try_clear()

    def report_down(self, cs: str) -> None:
        """Radar shows him stopped on the aerodrome. Get him off the runway.

        Distinct from `report_landed`, which answers a pilot who has the field
        in sight and is still flying -- what he is owed there is the clearance
        and the wind. Reading a landing clearance to a man already stopped on
        the runway is a controller who has not noticed the aeroplane arrive.

        What a tower actually says once the roll is over is where to go: off the
        runway, then to parking. It is also the transmission that tells him he
        has been SEEN to land, which is the only difference between "he has me
        down" and "he has crashed" -- and this is the last thing that happens on
        every flight.
        """
        ac = self.get(cs)
        ac.phase, ac.last_report_t = Phase.LANDED, self.t
        ac.map_t = None
        if self._letdown == ac.callsign:
            self._letdown = None
        twr = (self.profile.station_for("tower")
               if hasattr(self.profile, "station_for") else None)
        who = f"{twr.name}, " if twr else ""
        self.say(ac.callsign,
                 f"{self._addr(ac)}, {who}welcome. Exit the runway when able, "
                 f"taxi to parking. Good day.")
        self._try_clear()

    def request_visual(self, cs: str, field_in_sight: bool = False) -> None:
        """He would like to fly it himself, and in decent weather that is the
        normal thing to do.

        Pilots reported having to FORCE the controller into a visual, which is
        backwards: the surveillance approach is the hard, weather-driven case
        and a visual is what everybody flies on a clear day. Asking should be
        enough.

        The controller's part ends when the pilot has the field. Until then he
        gets a vector towards it; after, it is the pilot's approach and the
        controller's spacing -- which is exactly what route.py's `guidance`
        comment has said all along.
        """
        # A flight may fly a visual as a flight -- see `report_beacon`. It is
        # one entity, it gets one clearance, and the lead flies it.
        ac = self.get(cs)
        runway = self.profile.runway or "in use"
        if not self._letdown or self._letdown == ac.callsign:
            self._letdown = ac.callsign
            ac.phase, ac.on_visual, ac.last_report_t = Phase.CLEARED, True, self.t
            if field_in_sight:
                self.say(ac.callsign,
                         f"{self._addr(ac)}, cleared visual approach runway "
                         f"{runway}, {self._wind_phrase()}")
            else:
                self.say(ac.callsign,
                         f"{self._addr(ac)}, cleared visual approach runway "
                         f"{runway}, report the field in sight.")
            return
        # Somebody is already in the letdown. A visual does not jump the queue --
        # spacing is still the controller's, and it is the only thing he still
        # owns once the pilot is flying his own approach.
        ac.phase = Phase.HOLDING
        if ac.assigned_ft is None:
            ac.assigned_ft = self._free_slot() or self.profile.bottom_ft
        place = len(self._holders())
        words = ["", "one", "two", "three", "four", "five", "six"]
        self.say(ac.callsign,
                 f"{self._addr(ac)}, {self._hold_phrase(ac.assigned_ft, ac.kit)}. "
                 f"Expect the visual, you are number "
                 f"{words[place] if place < len(words) else place}.")

    def _wind_phrase(self) -> str:
        """The wind, on the clearance that ends with a landing."""
        from marshall.core import route as _R
        return (f"wind {spell_hdg(int(_R.WIND_FROM_DEG))} at "
                f"{spell_hdg(int(_R.WIND_MPH))[-9:].strip()}.")

    def request_approach(self, cs: str) -> None:
        # A pilot who calls up asking for the approach directly (no prior check-in
        # or beacon report) should still be worked, not ignored. Enter a new
        # arrival into the stack bottom-up, then let the sequencer clear them.
        ac = self.get(cs)
        if ac.phase == Phase.CLEARED:
            # Already cleared (e.g. the aircraft ahead just landed and freed the
            # letdown for him) -- re-affirm, don't send him back to the hold.
            self.say(ac.callsign,
                     f"{self._addr(ac)}, cleared {self._approach_name()} runway "
                     f"{self.profile.runway or 'in use'}, continue.")
            return
        if not self.may_be_sequenced(ac):
            # NOT RADAR IDENTIFIED. He does not get a level, he does not get a
            # place in the queue, and nobody is held behind him -- because we
            # cannot see him and may not even have him. Ask, which is what a
            # controller does.
            self.say(ac.callsign,
                     f"{self._addr(ac)}, not radar identified, say your "
                     f"position and altitude.")
            return
        # ENTER HIM IN THE STACK SILENTLY, THEN SEE IF HE IS ABOUT TO BE CLEARED.
        #
        # Holding him is a state change; SAYING so is a separate decision, and
        # they were the same statement. A lone arrival with the letdown free got
        # both transmissions in one breath:
        #
        #   "hold at five thousand, right turns, one eight zero outbound one
        #    minute, then three six zero inbound one minute, I will call you."
        #   "cleared radar approach runway one three."
        #
        #     "then issued me a hold for some reason"
        #
        # He was right, and it was not a mis-heard callsign or a ghost -- the
        # engine meant it. Entering the stack is how an arrival is sequenced
        # even when the sequence is one aeroplane long, and the hold was the
        # bookkeeping leaking onto the radio. A pattern nobody will fly, read to
        # a pilot who is already cleared, is worse than noise: he has to decide
        # which of two instructions to obey.
        held_at = None
        if ac.phase in (Phase.UNKNOWN, Phase.ENROUTE):
            slot = self._free_slot()
            if slot is not None:
                ac.phase, ac.assigned_ft, ac.last_report_t = Phase.HOLDING, slot, self.t
                held_at = slot
        # Asked BEFORE anything is said, rather than reordering the outbox
        # afterwards: the answer is knowable, and a rule that reaches past `say`
        # to shuffle what it queued would not survive the first caller that
        # routes transmissions somewhere else.
        #
        # It also lands the two in the right order for free -- the pattern, and
        # then "continue holding, number two", which is a sequence number that
        # has to follow the instructions it refers to.
        if held_at is not None and not (self._letdown is None
                                        and self._next_up() is ac):
            self.say(ac.callsign,
                     f"{self._addr(ac)}, {self.profile.controller}, "
                     f"{self._hold_phrase(held_at, ac.kit)}.")
        self._try_clear(requested_by=ac.callsign)

    # -- the sequencing core ----------------------------------------------
    def _next_up(self) -> Aircraft | None:
        """Who gets the next approach: a go-around at the front of the line
        first, otherwise the bottom of the stack."""
        missed = [a for a in self.aircraft.values() if a.phase == Phase.MISSED]
        if missed:
            return min(missed, key=lambda a: a.approaches)
        holders = self._holders()
        return holders[0] if holders else None

    def _try_clear(self, requested_by: str | None = None) -> None:
        """Clear the next aircraft for approach, if the letdown block is free."""
        if self._letdown is not None:
            if requested_by:
                self.say(requested_by, f"{requested_by}, continue holding, "
                                       f"number two, expect approach shortly.")
            return
        ac = self._next_up()
        if ac is None:
            return

        was_bottom_holder = ac.phase == Phase.HOLDING
        ac.phase = Phase.CLEARED
        ac.last_report_t = self.t
        self._letdown, self._letdown_since = ac.callsign, self.t
        self.say(ac.callsign,
                 f"{self._addr(ac)}, cleared {self._approach_name()} runway "
                 f"{self.profile.runway or 'in use'}, {self._report_phrase()}. "
                 f"Report missed approach or landing.")
        if was_bottom_holder:
            self._step_down()

    def _step_down(self) -> None:
        """The bottom slot just emptied; drop the stack down to close the gap.

        Steps LEVELS, not aircraft. Under visual separation a whole flight shares
        one level, and walking the holders one at a time would hand them
        4,000 / 5,000 / 6,000 -- silently undoing the visual break-up and
        re-separating a flight that had just been told to stay together.
        """
        levels = sorted({a.assigned_ft for a in self._holders()})
        for i, level in enumerate(levels):
            want = self.profile.stack_ft[i]
            if level == want:
                continue
            movers = [a for a in self._holders() if a.assigned_ft == level]
            for ac in movers:
                ac.assigned_ft = want
            # One call for a flight moving together, one per aircraft otherwise.
            flights = {callsign.parse(a.callsign).flight for a in movers}
            if len(movers) > 1 and len(flights) == 1:
                addr = callsign.Callsign(flights.pop()).spoken_flight
                self.say(movers[0].callsign,
                         f"{addr}, descend and maintain {spell_alt(want)}.")
            else:
                for ac in movers:
                    self.say(ac.callsign, f"{self._addr(ac)}, descend and maintain "
                                          f"{spell_alt(want)}.")

    def tick(self, seconds: float) -> None:
        """Advance the clock. Two time-based safety nets:
        prompt a quiet holder, and break a deadlock if the letdown goes silent."""
        self.t += seconds

        # Missed approach point, timed. The pilot flies this on a watch; ATC
        # backs it up -- when the beam clock runs out with the aircraft still in
        # the letdown and no landing reported, the controller calls the missed.
        if self._letdown:
            ac = self.aircraft.get(self._letdown)
            if ac and ac.map_t is not None and self.t >= ac.map_t:
                self._station_passage(ac)

        if self._letdown and self.t - self._letdown_since > CLEARANCE_TIMEOUT_SEC:
            cs = self._letdown
            ac = self.aircraft.get(cs)
            addr = self._addr(ac) if ac else callsign.parse(cs).spoken
            self.say(cs, f"{addr}, {self.profile.controller}, no report, "
                         f"say intentions.")
            self._letdown = None                # assume clear; do not deadlock
            self._try_clear()

        # Prompt at most one quiet holder per tick, so a lull does not produce a
        # burst of simultaneous calls stepping on each other.
        overdue = [a for a in self.aircraft.values()
                   if a.phase in (Phase.HOLDING, Phase.MISSED)
                   and self.t - a.last_report_t > REPORT_OVERDUE_SEC]
        if overdue:
            ac = max(overdue, key=lambda a: self.t - a.last_report_t)
            ac.last_report_t = self.t
            self.say(ac.callsign, f"{self._addr(ac)}, {self.profile.controller}, "
                                  f"report position.")


# --- text driver ------------------------------------------------------------
# The eventual voice grammar is tiny, so the text form mirrors it:
#   "Pony 1 checking in"
#   "Pony 1 beacon 4000"
#   "Pony 1 missed" / "Pony 1 landed" / "Pony 1 request approach"
_SIZE = {"two": 2, "three": 3, "four": 4}


def _size(g: dict) -> int:
    """'flight of four' -> 4. Absent means a single ship."""
    tok = (g.get("size") or "").lower()
    if not tok:
        return 1
    return _SIZE.get(tok) or (int(tok) if tok.isdigit() else 1)


PATTERNS = [
    (re.compile(r"(?P<cs>\w+ [\d-]+)(?: flight)?(?: of (?P<size>\w+))? check", re.I),
     lambda c, cs, g: c.check_in(cs, _size(g))),
    (re.compile(r"(?P<cs>\w+ [\d-]+)(?: flight)? break", re.I),
     lambda c, cs, g: c.request_breakup(cs)),
    (re.compile(r"(?P<cs>\w+ [\d-]+) miss", re.I), lambda c, cs, g: c.report_missed(cs)),
    (re.compile(r"(?P<cs>\w+ [\d-]+) land", re.I), lambda c, cs, g: c.report_landed(cs)),
    (re.compile(r"(?P<cs>\w+ [\d-]+) request", re.I),
     lambda c, cs, g: c.request_approach(cs)),
    (re.compile(r"(?P<cs>\w+ [\d-]+)(?: flight)?(?: of (?P<size>\w+))? "
                r"beacon(?: (?P<alt>\d+))?", re.I),
     lambda c, cs, g: c.report_beacon(cs, int(g["alt"]) if g["alt"] else None,
                                      _size(g))),
]


def feed(ctl: Controller, line: str) -> None:
    for pattern, action in PATTERNS:
        m = pattern.match(line.strip())
        if m:
            action(ctl, m.group("cs"), m.groupdict())
            return
    print(f"  ?? unparsed: {line}")


FORMATION_SCRIPT = [
    # A four-ship recovers, plus a single already in the pattern behind them.
    (0,   "Pony 1 flight of four checking in"),   # ONE entity, one clearance
    (20,  "Hawk 2 checking in"),                  # a single, separate flight
    (90,  "Pony 1 flight of four beacon 6000"),   # arrival = break-up, four levels
    (10,  "Pony 1-3 beacon"),                     # a wingman talks: now his own ship
    (20,  "Hawk 2 beacon 5000"),                  # the single takes what is left
    (150, "Pony 1-1 beacon inbound"),             # lead flies the letdown first
    (120, "Pony 1-1 landed"),                     # stack steps down, two is cleared
    (30,  "Pony 1-2 beacon inbound"),
    (120, "Pony 1-2 landed"),
]


def _run(ctl: Controller, script) -> None:
    for dt, line in script:
        ctl.tick(dt)
        if line:
            print(f"\n>>> {line}")
            feed(ctl, line)
        else:
            print(f"\n>>> ...{int(dt)}s pass, no landing reported...")
        for tx in ctl.out:
            print("    " + str(tx))
        ctl.out.clear()

    print("\n--- final ---")
    for cs, ac in sorted(ctl.aircraft.items()):
        alt = f"{ac.assigned_ft} ft" if ac.assigned_ft else "-"
        size = f" x{ac.size}" if ac.is_flight else ""
        print(f"  {cs:10} {ac.phase.name:9} {alt:9} approaches={ac.approaches}{size}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--formation":
        _run(Controller(R.BATUMI_APPROACH), FORMATION_SCRIPT)
        raise SystemExit(0)

    ctl = Controller(R.BATUMI_APPROACH)
    script = [
        (0,   "Pony 1 checking in"),
        (4,   "Pony 2 checking in"),
        (4,   "Pony 3 checking in"),
        (4,   "Pony 4 checking in"),
        (90,  "Pony 1 beacon 4000"),      # arrives, holds bottom, cleared
        (15,  "Pony 2 beacon 5000"),      # stacks on top
        (15,  "Pony 3 beacon 6000"),
        (15,  "Pony 4 beacon 7000"),
        (150, "Pony 1 beacon inbound"),   # established -> ATC starts the MAP clock
        (210, None),                      # beam time runs out, no landing reported
        (10,  "Pony 1 beacon inbound"),   # go-around re-cleared, established again
        (120, "Pony 1 landed"),           # runway there this time; stack steps up
        (30,  "Pony 2 beacon inbound"),
        (120, "Pony 2 landed"),
        (260, "Pony 3 landed"),
    ]
    _run(ctl, script)
