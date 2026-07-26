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
    members: list[str] = field(default_factory=list)   # non-empty => a joined flight
    # Cleared for a VISUAL approach: he is flying it himself from here. The
    # controller's job shrinks to spacing, and the talk-down must stop -- reading
    # ranges to a man looking at the runway is chatter over somebody busy.
    on_visual: bool = False
    # Can this flight maintain VISUAL separation between its own aircraft?
    # None = not asked yet. True = they can see each other, so they may share one
    # holding level. False = IMC, so the controller must separate them himself.
    # Tri-state on purpose: "we haven't asked" and "they said no" lead to the
    # same separation but very different transmissions, and defaulting an unasked
    # flight to "yes" would stack four aeroplanes on one level in cloud.
    visual: bool | None = None

    @property
    def is_flight(self) -> bool:
        return len(self.members) > 1

    @property
    def size(self) -> int:
        return max(1, len(self.members))


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


def spell_hdg(deg: float) -> str:
    """A heading, digit by digit: 127 -> 'one two seven'. Polly reads a bare
    127 as 'one hundred twenty seven', which is not a heading.

    North is THREE SIX ZERO. No controller says "zero zero zero" -- it is not a
    heading anyone flies, and a pilot hearing it wonders what was garbled.
    """
    d = {c: w for c, w in zip("0123456789",
         "zero one two three four five six seven eight nine".split())}
    hdg = int(round(deg)) % 360 or 360
    return " ".join(d[c] for c in f"{hdg:03d}")


def spell_time(t: float) -> str:
    """Minutes past the hour, spoken as digits: 'at four five'."""
    d = {c: w for c, w in zip("0123456789",
         "zero one two three four five six seven eight nine".split())}
    return " ".join(d[c] for c in f"{(int(t) // 60) % 60:02d}")


def spell_freq(mhz: float) -> str:
    """132.0 -> 'one three two', 128.5 -> 'one two eight decimal five'.

    Digit by digit, the way a controller reads a frequency; a trailing .0 is
    dropped because nobody says "one three two decimal zero".
    """
    d = {c: w for c, w in zip("0123456789",
         "zero one two three four five six seven eight nine".split())}
    whole, _, frac = f"{mhz:.3f}".rstrip("0").rstrip(".").partition(".")
    out = " ".join(d[c] for c in whole)
    if frac:
        out += " decimal " + " ".join(d[c] for c in frac)
    return out


def spell_dur(sec: float) -> str:
    """A duration as aviation timing: 204 -> 'three plus two four'."""
    d = {c: w for c, w in zip("0123456789",
         "zero one two three four five six seven eight nine".split())}
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

    def _hold_phrase(self, alt_ft: int) -> str:
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
        if not self._vectored:
            return (f"hold at {self.profile.beacon.name} as published, "
                    f"maintain {spell_alt(alt_ft)}")
        out = self.profile.hold_outbound_hdg
        return (f"hold at {spell_alt(alt_ft)}, {spell_hdg(out)} outbound, "
                f"{spell_hdg((out + 180) % 360)} inbound, expect vectors for "
                "the approach, I will call you")

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
        themselves -- and a call addressed to the flight then means lead, who is
        the one still answering for the formation's name.
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
            if any(m in self.aircraft for m in c.members(size)):
                return self.get(cs)           # already split; leave them alone
            ac = self.aircraft.get(c.flight)
            if ac is None:
                ac = self.aircraft[c.flight] = Aircraft(c.flight)
            if not ac.members:
                ac.members = c.members(size)
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
        ac = self.get(cs)
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
        # Can they see each other? In VMC a flight may break up into singles in
        # the SAME pattern at the SAME level -- the pilots accept responsibility
        # for staying apart, which is what "maintain visual separation" means and
        # is far quicker than laddering four aeroplanes up the stack. In cloud
        # that is not available and the controller must separate them himself.
        # He cannot know which it is from the ground, so he asks, once.
        # When the hold is above the weather -- which on a vectored approach it
        # is, by construction -- there is nothing to ask. They can see each
        # other, so they hold as one aeroplane at one level in trail, and the
        # levels go to separating FLIGHTS from other flights. Laddering a
        # formation up the stack in clear air is work that buys nothing and
        # spends four levels on one arrival.
        if ac.visual is None and getattr(self.profile, "hold_in_clear_air", False):
            ac.visual = True
        if ac.visual is None:
            if ac.assigned_ft is None:
                ac.assigned_ft = self._free_slot() or self.profile.bottom_ft
            ac.phase, ac.last_report_t = Phase.HOLDING, self.t
            self.say(ac.callsign,
                     f"{self._addr(ac)}, {self._hold_phrase(ac.assigned_ft)}. "
                     "Can you maintain visual separation between your aircraft?")
            return

        members = list(ac.members)
        self.aircraft.pop(ac.callsign, None)
        assigned: list[tuple[str, int]] = []
        if ac.visual:
            # One level for the whole flight; they keep themselves apart.
            level = ac.assigned_ft or self._free_slot() or self.profile.bottom_ft
            for m in members:
                self.aircraft[m] = Aircraft(m, Phase.HOLDING, level, self.t,
                                            visual=True)
                assigned.append((m, level))
        else:
            for m in members:
                slot = self._free_slot()
                if slot is None:
                    break
                self.aircraft[m] = Aircraft(m, Phase.HOLDING, slot, self.t)
                assigned.append((m, slot))

        if len(assigned) < len(members):
            # Only the oxygen ceiling can cause this. Half a formation is worse
            # than none -- the ones without a level would have nowhere legal to
            # go -- so put it back and keep them together until room appears.
            for m, _ in assigned:
                self.aircraft.pop(m, None)
            self.aircraft[ac.callsign] = ac
            self.say(ac.callsign, ref=ac, text=
                     f"{self._addr(ac)}, unable break-up, holding is full to "
                     f"{spell_alt(self.profile.top_ft)}. Remain as a flight, "
                     f"maintain {spell_alt(ac.assigned_ft or self.profile.bottom_ft)}, "
                     f"expect break-up shortly.")
            return

        # Hand over to the sequencer BEFORE announcing. It may clear the bottom
        # aircraft -- normally lead -- and settle everyone above him a level
        # lower, and the break-up call has to state the levels they will actually
        # fly. Announce first and lead gets assigned a holding altitude and
        # cleared out of it in the same breath, which is not a thing a controller
        # says. Its transmissions are held back and replayed after ours.
        mark = len(self.out)
        self._try_clear()
        followup = self.out[mark:]
        del self.out[mark:]

        announced = [m for m, _ in assigned
                     if self.aircraft[m].phase == Phase.HOLDING]
        call = f"{self._addr(ac)}, break up for individual approaches."
        if ac.visual and announced:
            # One level, one instruction -- reading four identical altitudes out
            # would be noise, and the point is that they stay together.
            call += (f" Maintain visual separation, all maintain "
                     f"{spell_alt(self.aircraft[announced[0]].assigned_ft)}, "
                     f"in trail.{self._identify_phrase([m for m, _ in assigned])}")
        elif announced:
            levels = ". ".join(
                f"{callsign.parse(m).spoken} maintain "
                f"{spell_alt(self.aircraft[m].assigned_ft)}" for m in announced)
            call += (f" {levels}."
                     + self._identify_phrase([m for m, _ in assigned],
                                             already_named=True))
        self.say(ac.callsign, call, ref=ac)

        # Drop the sequencer's step-downs for aircraft this call already gave a
        # level to -- they would repeat, verbatim, the altitude just assigned.
        # Anything aimed at somebody else (a single already holding behind the
        # formation) still has to go out.
        self.out.extend(tx for tx in followup if tx.to not in announced)

    def request_breakup(self, cs: str) -> None:
        """Lead asking to split the formation up himself."""
        ac = self.get(cs)
        if not ac.is_flight:
            self.say(ac.callsign, f"{self._addr(ac)}, roger, no flight to break up.")
            return
        self._break_up(ac)

    def report_conditions(self, cs: str, visual: bool) -> None:
        """The flight answering "can you maintain visual separation?".

        Affirmative means the pilots take responsibility for staying apart, so
        the whole flight can break up inside one holding level. Negative means
        the controller separates them by altitude. Either way the answer arrives
        while they are holding as a flight, so it is followed straight by the
        break-up it was asked for.
        """
        ac = self.get(cs)
        ac.visual, ac.last_report_t = visual, self.t
        if not ac.is_flight:
            self.say(ac.callsign, f"{self._addr(ac)}, roger.")
            return
        if not visual:
            self.say(ac.callsign, f"{self._addr(ac)}, roger, instrument "
                                  f"conditions, I will separate you.")
        self._break_up(ac)

    def report_beacon(self, cs: str, altitude_ft: int | None = None,
                      size: int = 1) -> None:
        """Reported over the approach beacon."""
        ac = self._enter(cs, size) if size > 1 else self.get(cs)
        ac.last_report_t = self.t

        if ac.phase in (Phase.UNKNOWN, Phase.ENROUTE):
            # A formation arriving at the fix is the moment it stops being one
            # aeroplane. You do NOT hold four ships in formation through a
            # letdown -- a holding pattern is minutes of turning in cloud with
            # three wingmen welded to lead exactly when lead's attention is on
            # the plate and the clock. Break them up on arrival, every time.
            if ac.is_flight:
                self._break_up(ac)
                return
            slot = self._free_slot()
            if slot is None:
                self.say(ac.callsign,
                         f"{self._addr(ac)}, no holding available, remain clear.")
                return
            ac.phase, ac.assigned_ft = Phase.HOLDING, slot
            self.say(ac.callsign,
                     f"{self._addr(ac)}, hold at {self.profile.beacon.name} as "
                     f"published, maintain {spell_alt(slot)}.")
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
        self.say(ac.callsign, f"{self._addr(ac)}, roger, landing assured. Good day.")
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
        ac = self.get(cs)
        if ac.is_flight:
            self._break_up(ac)          # four ships cannot fly one approach
            return
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
                 f"{self._addr(ac)}, {self._hold_phrase(ac.assigned_ft)}. "
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
        if ac.is_flight:
            # A formation asking for the approach is asking to be broken up,
            # whether or not it uses the word: four ships cannot fly one letdown.
            self._break_up(ac)
            return
        if ac.phase == Phase.CLEARED:
            # Already cleared (e.g. the aircraft ahead just landed and freed the
            # letdown for him) -- re-affirm, don't send him back to the hold.
            self.say(ac.callsign,
                     f"{self._addr(ac)}, cleared {self._approach_name()} runway "
                     f"{self.profile.runway or 'in use'}, continue.")
            return
        if ac.phase in (Phase.UNKNOWN, Phase.ENROUTE):
            slot = self._free_slot()
            if slot is not None:
                ac.phase, ac.assigned_ft, ac.last_report_t = Phase.HOLDING, slot, self.t
                self.say(ac.callsign,
                         f"{self._addr(ac)}, {self.profile.controller}, "
                         f"{self._hold_phrase(slot)}.")
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
    (re.compile(r"(?P<cs>\w+ [\d-]+)(?: flight)? (?:affirm|vmc|visual)", re.I),
     lambda c, cs, g: c.report_conditions(cs, True)),
    (re.compile(r"(?P<cs>\w+ [\d-]+)(?: flight)? (?:negative|imc|in cloud)", re.I),
     lambda c, cs, g: c.report_conditions(cs, False)),
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
