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
    callsign: str
    phase: Phase = Phase.UNKNOWN
    assigned_ft: int | None = None
    last_report_t: float = 0.0
    approaches: int = 0
    map_t: float | None = None       # computed station-passage (missed approach point) time


@dataclass
class Tx:
    to: str
    text: str
    t: float

    def __str__(self) -> str:
        return f"[{int(self.t)//60:02d}:{int(self.t)%60:02d}] {self.to}: {self.text}"


def spell_alt(ft: int) -> str:
    """7000 -> 'seven thousand', 3500 -> 'three thousand five hundred'."""
    words = {0: "", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine"}
    th, hu = divmod(ft, 1000)
    out = f"{words.get(th, str(th))} thousand"
    if hu:
        out += f" {words[hu // 100]} hundred"
    return out


def spell_time(t: float) -> str:
    """Minutes past the hour, spoken as digits: 'at four five'."""
    d = {c: w for c, w in zip("0123456789",
         "zero one two three four five six seven eight nine".split())}
    return " ".join(d[c] for c in f"{(int(t) // 60) % 60:02d}")


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
    def say(self, to: str, text: str) -> None:
        self.out.append(Tx(to, text, self.t))

    def get(self, cs: str) -> Aircraft:
        return self.aircraft.setdefault(cs, Aircraft(cs))

    def _holders(self) -> list[Aircraft]:
        return sorted((a for a in self.aircraft.values()
                       if a.phase == Phase.HOLDING and a.assigned_ft is not None),
                      key=lambda a: a.assigned_ft)

    def _free_slot(self) -> int | None:
        """Lowest stack level nobody holds -- a new arrival enters here, i.e.
        on top of the current holders (which always fill from the bottom up)."""
        taken = {a.assigned_ft for a in self._holders()}
        for ft in self.profile.stack_ft:
            if ft not in taken:
                return ft
        return None                     # stack full

    # -- pilot inputs ------------------------------------------------------
    def check_in(self, cs: str) -> None:
        ac = self.get(cs)
        ac.phase, ac.last_report_t = Phase.ENROUTE, self.t
        self.say(cs, f"{cs}, {self.profile.controller}, radar not available, "
                     f"report {self.profile.beacon.name} inbound.")

    def report_beacon(self, cs: str, altitude_ft: int | None = None) -> None:
        """Reported over the approach beacon."""
        ac = self.get(cs)
        ac.last_report_t = self.t

        if ac.phase in (Phase.UNKNOWN, Phase.ENROUTE):
            slot = self._free_slot()
            if slot is None:
                self.say(cs, f"{cs}, no holding available, remain clear.")
                return
            ac.phase, ac.assigned_ft = Phase.HOLDING, slot
            self.say(cs, f"{cs}, hold at {self.profile.beacon.name} as published, "
                         f"maintain {spell_alt(slot)}.")
            self._try_clear()
        elif ac.phase == Phase.CLEARED:
            # Established inbound on the beam: start the station-passage clock.
            # The pilot flies the MAP on a watch; ATC times the same number and
            # calls it as backup (aural station passage does not read in the sim).
            ac.map_t = self.t + self.profile.final_approach_sec
            self.say(cs, f"{cs}, roger, station passage {spell_dur(self.profile.final_approach_sec)}, "
                         f"report field in sight or missed approach.")
        else:
            self.say(cs, f"{cs} roger, {spell_alt(altitude_ft or ac.assigned_ft or 0)}.")

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
                    f"{self.profile.outer_hold.name} "
                    f"{self.profile.outer_hold.freq_mhz:.3f}, hold, expect "
                    f"re-sequence. Traffic holding.")
        return (f"climb {spell_alt(self.profile.missed_ft)}, "
                f"return to the beacon. You are number one for the approach.")

    def report_missed(self, cs: str) -> None:
        ac = self.get(cs)
        banished = self._do_missed(ac)
        prefix = f"{cs}, " if banished else f"{cs} roger, "
        self.say(cs, prefix + self._missed_instruction(banished))
        self._try_clear()

    def _station_passage(self, ac: Aircraft) -> None:
        """Beam time up with no landing: ATC hears it overhead and calls the
        missed. The pilot's own watch should already be prompting this -- the
        cone of silence is unreliable in the sim, so ATC backs the timing up."""
        banished = self._do_missed(ac)
        inst = self._missed_instruction(banished)
        self.say(ac.callsign, f"{ac.callsign}, heard a Mustang overhead, field is "
                              f"beneath you, go missed. " + inst[0].upper() + inst[1:])
        self._try_clear()

    def report_landed(self, cs: str) -> None:
        ac = self.get(cs)
        ac.phase, ac.last_report_t = Phase.LANDED, self.t
        ac.map_t = None
        if self._letdown == cs:
            self._letdown = None
        self.say(cs, f"{cs}, roger, landing assured. Good day.")
        self._try_clear()

    def request_approach(self, cs: str) -> None:
        # A pilot who calls up asking for the approach directly (no prior check-in
        # or beacon report) should still be worked, not ignored. Enter a new
        # arrival into the stack bottom-up, then let the sequencer clear them.
        ac = self.get(cs)
        if ac.phase == Phase.CLEARED:
            # Already cleared (e.g. the aircraft ahead just landed and freed the
            # letdown for him) -- re-affirm, don't send him back to the hold.
            self.say(cs, f"{cs}, cleared beacon approach runway "
                         f"{self.profile.runway or 'in use'}, continue.")
            return
        if ac.phase in (Phase.UNKNOWN, Phase.ENROUTE):
            slot = self._free_slot()
            if slot is not None:
                ac.phase, ac.assigned_ft, ac.last_report_t = Phase.HOLDING, slot, self.t
                self.say(cs, f"{cs}, {self.profile.controller}, radar not available, "
                             f"hold at {self.profile.beacon.name} as published, "
                             f"maintain {spell_alt(slot)}.")
        self._try_clear(requested_by=cs)

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
                 f"{ac.callsign}, cleared beacon approach runway "
                 f"{self.profile.runway or 'in use'}, report beacon inbound. "
                 f"Report missed approach or landing.")
        if was_bottom_holder:
            self._step_down()

    def _step_down(self) -> None:
        """The bottom slot just emptied; drop every holder 1,000 ft."""
        for i, ac in enumerate(self._holders()):
            want = self.profile.stack_ft[i]
            if ac.assigned_ft != want:
                ac.assigned_ft = want
                self.say(ac.callsign, f"{ac.callsign}, descend and maintain "
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
            self.say(cs, f"{cs}, {self.profile.controller}, no report, "
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
            self.say(ac.callsign, f"{ac.callsign}, {self.profile.controller}, "
                                  f"report position.")


# --- text driver ------------------------------------------------------------
# The eventual voice grammar is tiny, so the text form mirrors it:
#   "Pony 1 checking in"
#   "Pony 1 beacon 4000"
#   "Pony 1 missed" / "Pony 1 landed" / "Pony 1 request approach"
PATTERNS = [
    (re.compile(r"(?P<cs>\w+ \d) check", re.I), lambda c, cs, g: c.check_in(cs)),
    (re.compile(r"(?P<cs>\w+ \d) miss", re.I), lambda c, cs, g: c.report_missed(cs)),
    (re.compile(r"(?P<cs>\w+ \d) land", re.I), lambda c, cs, g: c.report_landed(cs)),
    (re.compile(r"(?P<cs>\w+ \d) request", re.I),
     lambda c, cs, g: c.request_approach(cs)),
    (re.compile(r"(?P<cs>\w+ \d) beacon(?: (?P<alt>\d+))?", re.I),
     lambda c, cs, g: c.report_beacon(cs, int(g["alt"]) if g["alt"] else None)),
]


def feed(ctl: Controller, line: str) -> None:
    for pattern, action in PATTERNS:
        m = pattern.match(line.strip())
        if m:
            action(ctl, m.group("cs"), m.groupdict())
            return
    print(f"  ?? unparsed: {line}")


if __name__ == "__main__":
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
        print(f"  {cs:8} {ac.phase.name:9} {alt:9} approaches={ac.approaches}")
