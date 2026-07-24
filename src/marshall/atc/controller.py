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
        else:
            self.say(cs, f"{cs} roger, {spell_alt(altitude_ft or ac.assigned_ft or 0)}.")

    def report_missed(self, cs: str) -> None:
        ac = self.get(cs)
        ac.approaches += 1
        ac.last_report_t = self.t
        if self._letdown == cs:
            self._letdown = None

        if ac.approaches >= MAX_APPROACHES:
            ac.phase = Phase.BANISHED
            ac.assigned_ft = self.profile.top_ft
            self.say(cs, f"{cs}, climb {spell_alt(self.profile.top_ft)}, proceed "
                         f"{self.profile.outer_hold.name} "
                         f"{self.profile.outer_hold.freq_mhz:.3f}, hold, expect "
                         f"re-sequence. Traffic holding.")
        else:
            ac.phase, ac.assigned_ft = Phase.MISSED, self.profile.missed_ft
            self.say(cs, f"{cs} roger, climb {spell_alt(self.profile.missed_ft)}, "
                         f"return to the beacon. You are number one for the approach.")
        self._try_clear()

    def report_landed(self, cs: str) -> None:
        ac = self.get(cs)
        ac.phase, ac.last_report_t = Phase.LANDED, self.t
        if self._letdown == cs:
            self._letdown = None
        self.say(cs, f"{cs}, roger, landing assured. Good day.")
        self._try_clear()

    def request_approach(self, cs: str) -> None:
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
        (240, "Pony 1 missed"),           # go-around: front of line, number one
        (200, "Pony 1 landed"),           # second try sticks; stack steps up
        (30,  "Pony 2 request approach"),
        (260, "Pony 2 landed"),
        (260, "Pony 3 landed"),
    ]
    for dt, line in script:
        ctl.tick(dt)
        print(f"\n>>> {line}")
        feed(ctl, line)
        for tx in ctl.out:
            print("    " + str(tx))
        ctl.out.clear()

    print("\n--- final ---")
    for cs, ac in sorted(ctl.aircraft.items()):
        alt = f"{ac.assigned_ft} ft" if ac.assigned_ft else "-"
        print(f"  {cs:8} {ac.phase.name:9} {alt:9} approaches={ac.approaches}")
