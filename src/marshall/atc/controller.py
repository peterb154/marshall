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
from marshall.atc import decision as D
# The spellers live in `core` now -- ATIS needs them too and cannot import
# sideways. Re-exported here so `controller.spell_hdg` still resolves.
from marshall.core.say import (  # noqa: F401
    spell_alt,
    spell_count,
    spell_dur,
    spell_freq,
    spell_hdg,
    spell_minutes,
    spell_rwy,
    spell_speed,
    spell_time,
)

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


def _atis_letter_in(phrase: str) -> str:
    """The information letter a phrase is about, if any.

    `_atis_phrase` has four shapes -- current, superseded, not yet advised, and
    no broadcast at all -- and three of them name a letter. Read once, here,
    rather than by each caller guessing which shape it got.

    A module function rather than a method: it needs nothing from the
    controller, and `tools/unwired.py` cannot tell a static method that is
    called from one that is dead -- which is a fair complaint about putting a
    pure string function on a class in the first place.
    """
    m = re.search(r"information ([A-Za-z]+)", phrase or "")
    return m.group(1) if m else ""


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
    # WHAT HE IS DOING, in `phases.py`'s vocabulary, as distinct from `phase`
    # above -- and they are genuinely two things rather than a duplication.
    #
    #   `phase`        SEPARATION state. Where he sits in the stack, whether he
    #                  is in the letdown, whether he has gone around. The enum
    #                  exists so this engine can sequence aeroplanes, and every
    #                  value in it is about the arrival.
    #
    #   `sortie_phase` WHAT HE IS DOING. Clearance, taxi, holding short,
    #                  departure, enroute, approach. It covers the whole flight
    #                  including the half that has no geometry in it, and it is
    #                  what decides WHO OWNS HIM -- see `handoff.due`.
    #
    # An aeroplane holding short is UNKNOWN to the separation engine and
    # perfectly well defined to the sortie, which is the case that made the
    # distinction necessary rather than tidy: the ground half of a flight has
    # no stack, no levels and no sequence, and forcing it into an arrival enum
    # would have meant inventing arrival states for a man who has not moved.
    sortie_phase: str = ""
    # WHICH INFORMATION HE SAID HE HAS. Empty means he did not mention one,
    # which gets a different answer on the radio from claiming the wrong one:
    # the first is a prompt, the second is a correction.
    atis_letter: str = ""
    # WHAT HE SAID HE WANTS, verbatim and in his own words.
    #
    # Carried here for one turn on its way to `flights.intent`, exactly as
    # `atis_letter` is -- the board is not where it lives, it is how it crosses
    # the seam. See docs/STATE.md: this is the fact a pilot stated on his first
    # call and at every handoff and that nothing ever wrote down, so each
    # controller reconstructed his intentions from his last sentence.
    wants: str = ""
    # THE TWO ALTITUDES, and they are two because they have two owners.
    #
    #   `assigned_ft`  THE SEPARATION ENGINE'S. A stack slot, the vectoring
    #                  altitude, the missed-approach level -- a number this
    #                  engine chose in order to keep aeroplanes apart. `None`
    #                  means it has not put him anywhere, which is what
    #                  `_free_slot` and `seen_on_final` both depend on.
    #
    #   `cleared_ft`   THE CLEARANCE'S. The cruise level Delivery read to him
    #                  and he read back. Nobody was separated by it and this
    #                  engine did not pick it, but he is FLYING it, and being
    #                  told he is at the wrong altitude while level at the one
    #                  he was cleared to is the complaint that started this:
    #
    #                      "I was clearly assigned to 5,000. Don't know why
    #                       you said that"
    #
    # They were one field, which meant the clearance either overwrote the stack
    # slot or was not recorded at all. It was the second: `clearance_read_back`
    # moved the phase and touched no altitude, so en route there was nothing
    # authoritative to point at and the strip carried the plan's number beside
    # the engine's with no rule about which governed. See `governing_ft`.
    assigned_ft: int | None = None
    cleared_ft: int | None = None
    # WHICH APPROACH HE IS FLYING. His, not the bridge's.
    #
    #     "One approach profile per flight, not per bridge -- THIS IS THE WALL
    #      IN FRONT OF MULTIPLE AIRPORTS."                      -- #2, day one
    #
    # `Controller` holds one `profile` and every arrival fact was read off it:
    # the beacon, the stack levels, the runway, the minima, the missed
    # approach, the name of the controller. That is correct for one aerodrome
    # and wrong for two, and it is not a subtle wrongness -- it is one
    # aeroplane being given another airport's runway and minima, and every
    # number is real, so nothing looks wrong until somebody flies it.
    #
    # None means "the bridge's", which is what everything did before and is
    # right for an aircraft nobody has assigned a recovery to. See
    # `Controller._pro`.
    profile: object | None = None
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
    # THE SIM'S OWN NAME FOR THE AEROPLANE, carried so nothing downstream has to
    # work it out again.
    #
    # This is not the engine being allowed to see. A track is an opaque PRIMARY
    # KEY -- no position, no heading, nothing separation could be computed from,
    # and this class cannot ask the scope anything about it. What it removes is
    # the join: `publish_state` and `release_stale` have both been matching a
    # handle against a canonical against a scope label, three derivations of one
    # aeroplane's name compared as strings, and every board bug of the last
    # month lived in that gap. Bound once, at the door, by the one caller that
    # holds both names.
    track: str = ""
    # WHO IS WORKING HIM. Exactly one controller at a time.
    #
    #     "that controller OWNS me unless i am released to go back to untracked"
    #
    # Set when he is taken on, changed by a handoff, cleared only by release.
    # A handoff is NOT a release: ownership moves directly from one controller
    # to the next and he is never unowned in between -- dropping him to
    # untracked mid-approach is precisely what `release_stale` was doing.
    owner: str = ""
    # WHAT HE SAYS HE WANTS, which nothing else here knows.
    #
    #     "The first thing a controller should do is figure out what my
    #      intentions are"
    #
    # Blank until he says, and the blank is the useful part: it means nobody has
    # asked. Distinct from `phase`, which is where the separation machine has
    # got to, and from the STATE the sim reports -- what he is doing, what he
    # intends, and what the engine has decided about him are three facts with
    # three different authorities and they must not be collapsed into one word.
    intent: str = ""
    # WHICH PROCEDURE HIS CLEARANCE NAMES -- `batumi-asr`, `kobuleti-ils`.
    #
    # The key, not the profile: `profile` beside it is the geometry and has no
    # name, and a board that had to reverse-match a profile back to a key would
    # be re-deriving a fact it was handed. Blank means nobody has assigned him
    # one, which is different from "he is flying the bridge's default" and is
    # exactly the distinction a pilot cannot see any other way.
    approach: str = ""

    @property
    def is_flight(self) -> bool:
        return self.ships > 1 or len(self.members) > 1

    @property
    def size(self) -> int:
        return max(self.ships, len(self.members), 1)

    @property
    def governing_ft(self) -> int | None:
        """THE ALTITUDE HE IS HELD TO. One door, over the two that own one.

        The engine's assignment outranks the clearance, and the order is the
        whole content of this property: a stack slot, a vectoring altitude or a
        missed-approach level was issued to keep him away from another
        aeroplane, and it supersedes a cruise level agreed on the ramp. When the
        engine has issued nothing, the clearance stands -- which is the en-route
        case, and the one where there used to be no answer at all.

        Everything that ASSERTS an altitude reads this: the strip, the
        correction in `report_level`, and the verifier that checks the agent did
        not invent one. Reading either field directly is how they came to
        disagree, and a controller telling a pilot he is at the wrong altitude
        is the one place in this system where being wrong is unarguable.
        """
        return self.assigned_ft if self.assigned_ft is not None else self.cleared_ft


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
    # WHAT THIS TRANSMISSION DECIDED, as facts rather than as the sentence
    # above. Optional while the phrasebook is being moved out -- a site that
    # has not been converted carries None and behaves exactly as before.
    #
    # The point of it is that a decision can be CHECKED against what the agent
    # actually said, and a sentence cannot. See `decision.verify`.
    decision: object = None

    def __str__(self) -> str:
        chan = f" {self.freq_mhz:.3f}" if self.freq_mhz else ""
        return (f"[{int(self.t)//60:02d}:{int(self.t)%60:02d}]{chan} "
                f"{self.to}: {self.text}")


# THE SEPARATION PHASE AS THE BOARD SPELLS IT, and back again.
#
# One mapping, here, next to the enum it describes. It lived in `agent_atc` and
# was needed in both directions the moment the board could be rebuilt from the
# table -- and two copies of a translation is how the two come to disagree about
# what "approach" means. `agent_atc` imports it.
PHASE_WORD = {
    "UNKNOWN": "unknown", "ENROUTE": "enroute", "HOLDING": "holding",
    "CLEARED": "approach", "MISSED": "missed", "BANISHED": "holding",
    "LANDED": "landed",
}
# Not a strict inverse: BANISHED and HOLDING share a word, so a rebuilt board
# reads "holding" as HOLDING. That is the safe direction -- a banished aircraft
# restored as a holder is one the controller will sequence rather than one he
# has forgotten about.
PHASE_FROM_WORD = {"unknown": "UNKNOWN", "enroute": "ENROUTE",
                   "holding": "HOLDING", "approach": "CLEARED",
                   "missed": "MISSED", "landed": "LANDED"}


@dataclass
class Controller:
    profile: R.ApproachProfile
    aircraft: dict[str, Aircraft] = field(default_factory=dict)
    out: list[Tx] = field(default_factory=list)
    t: float = 0.0
    # WHO IS IN THE LETDOWN, PER APPROACH. One string was one letdown for the
    # whole bridge -- correct while there was one aerodrome, and the moment
    # there are two it means an aeroplane on the Nellis ILS blocks the approach
    # at Tonopah, a hundred and twenty miles away, for no reason anybody could
    # explain on the radio.
    #
    # Keyed on the procedure's BEACON, which is what a letdown is single-
    # occupancy ABOUT: the fix everybody flies over. Two aircraft on one
    # approach contend; two aircraft on two approaches do not. See `_key`.
    _letdown_by: dict = field(default_factory=dict)
    _letdown_since_by: dict = field(default_factory=dict)
    # STATES THAT SHOULD BE IMPOSSIBLE, recorded when they happen anyway.
    #
    # The separation engine has invariants -- one aircraft in the letdown, a
    # cleared aircraft is not also a holder -- and when one breaks, the
    # symptom on the radio is something a pilot can hear and the cause is
    # somewhere else entirely. #50 was four transmissions of "you are number
    # two" with one aeroplane in the sky, and the fault was an unguarded line
    # in `check_in` two hundred lines away.
    #
    # Correcting the radio answer is right. Correcting it SILENTLY is how the
    # cause survives, so anything that repairs an impossible state says so
    # here and `/diag` shows it.
    anomalies: list = field(default_factory=list)
    # Actions the classifier chose that the procedure does not contain. Not
    # failures -- see `note_unreachable` -- but a count worth watching, because
    # a taxonomy that stops fitting shows up here first.
    unreachable: list = field(default_factory=list)
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

    # WHICH PROCEDURES THE CONTROLLER VECTORS FOR. A radar approach and an ILS
    # both start with him turning the aeroplane onto a course; a beacon letdown
    # does not, because the pilot navigates it himself off the needle.
    #
    # NOT read off `atc.radar`, which would be the obvious thing and is wrong
    # today: the NDB letdown profile carries radar=True, which looks like a
    # data error given the whole point of that profile is the non-radar
    # handicap. Keying on it would quietly give a 1944 letdown radar
    # phraseology. Named procedures instead, until that flag is worth trusting.
    VECTORED_KINDS = ("asr", "ils")

    @property
    def _vectored(self) -> bool:
        """Does this controller steer him, or does the pilot fly the procedure?

        ASKED OF THE CAPABILITY, and it used to be asked of the procedure's
        NAME. The obvious key -- `atc.radar` -- is wrong, and #53 exists because
        it looks right: the 1944 beacon letdown carries `radar=True` deliberately
        so the controller can read ranges off his scope, while the pilot has no
        DME and flies the published pattern himself. Seeing an aeroplane and
        steering it are different capabilities, and one flag was answering both.
        `AtcCapability.vectors` separates them; `None` means ask the procedure,
        which is what this did all along.
        """
        from marshall.core.approach import may_vector
        return may_vector(self.profile)

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
        ac = self.aircraft[key]
        if self._in_letdown(ac) == key:
            # He owned the approach. Free it or the next arrival waits behind
            # somebody who has gone home.
            self._set_letdown(ac, None)
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

    def hydrate(self, rows, approach_named=None) -> int:
        """Rebuild the board from the table. THE TABLE IS THE SOURCE OF TRUTH.

            "there really shouldn't be much in memory data structures - we
             addressed this - database is fast and should be the single source
             of truth"

        This board was built only by transmissions, so a bridge restarted
        mid-sortie began knowing nothing: every rung a pilot had climbed, every
        level assigned, every approach flown, forgotten, while the aeroplanes
        went on flying. The controller then met everybody for the first time --
        and, worse, would happily clear a second aircraft for an approach the
        first was already on, because the letdown was empty too.

        The board is a WRITE-THROUGH CACHE now, not the original. Every fact
        here is written to `flights` as it changes (see `flight_agree`) and
        rebuilt from it here, so a restart is invisible and the durable copy is
        the one that counts.

        `approach_named` resolves a plan's approach key to a profile -- passed
        in rather than imported, because the theatre catalogue lives above this
        module and reaching up for it is what `LAYERS.md` forbids.

        NOT POSITION. Nothing here restores where anybody is: that is radar's,
        it is in `tracks`, and it is reconciled every sweep. A board that
        remembered a position across a restart would be asserting where an
        aeroplane was several minutes ago.
        """
        n = 0
        for row in rows or []:
            cs = (row.get("callsign") or "").strip()
            if not cs:
                continue
            ac = self._enter(cs, int(row.get("claimed_size") or 1))
            ac.sortie_phase = row.get("sortie_phase") or ""
            ac.on_visual = bool(row.get("on_visual"))
            ac.approaches = int(row.get("approaches_flown") or 0)
            ac.atis_letter = row.get("atis_letter") or ""
            ac.wants = row.get("intent") or ""
            ac.track = row.get("track_name") or ""
            ac.radar_identified = bool(row.get("radar_identified"))
            if row.get("assigned_ft"):
                ac.assigned_ft = int(row["assigned_ft"])
            if row.get("cruise_ft"):
                ac.cleared_ft = int(row["cruise_ft"])
            if approach_named and row.get("cleared_approach"):
                ac.approach = row["cleared_approach"]
                got = approach_named(row["cleared_approach"])
                if got is not None:
                    ac.profile = got
            # THE SEPARATION PHASE, and with it the letdown. `cleared` is the
            # enum's own word for where he sits in the arrival queue, and an
            # aircraft restored as CLEARED must be restored as the man on the
            # approach too -- otherwise the next arrival is cleared straight
            # into him, which is the accident the whole engine exists to
            # prevent, caused by the recovery from a restart.
            want = PHASE_FROM_WORD.get((row.get("cleared") or "").lower())
            if want:
                ac.phase = Phase[want]
            if ac.phase is Phase.CLEARED:
                self._set_letdown(ac, ac.callsign)
            n += 1
        return n

    def _pro(self, ac):
        """THE APPROACH THIS AEROPLANE IS FLYING, not the one the bridge loaded.

        Every arrival fact comes through here: the beacon he homes, the levels
        in his stack, the runway he is cleared to, his minima, his missed
        approach, and the name of the controller working him. They are
        properties of a PROCEDURE, and two aircraft recovering to two fields
        have two of them.

        The facility's station table is deliberately NOT here. `station_for`
        answers "who works ground at Kobuleti" and that is a property of the
        theatre, shared by every profile in it -- routing it through an
        aircraft would imply it could differ per flight, which it cannot.

        Falls back to the bridge's profile, which is what every caller did
        before and is right for an aeroplane nobody has assigned a recovery to.
        """
        return getattr(ac, "profile", None) or self.profile

    def assign_approach(self, callsign: str, profile, named: str = "") -> None:
        """This aeroplane is recovering on THIS procedure. Told, not deduced.

        Set from his filed plan, which names its approach -- so a flight going
        home to Nellis carries the Nellis ILS whatever the bridge happens to
        have loaded, and the outbound aircraft beside him can carry Tonopah's.

        `named` IS SO THE BOARD CAN SAY IT.

            "for the cleared_approach - shouldnt that be on the board i am
             looking at? Isnt it in the database?"

        It is, in `assigned_plans.approach`, and migration 025 put it on the
        strip. It was read on every transmission, used to look up the profile,
        and then dropped on the floor -- so the one fact answering "which
        approach am I flying" existed at every layer except the one a human
        looks at. An `ApproachProfile` has no name of its own (it is geometry),
        so the KEY is what gets carried; without it the board would have to
        reverse a lookup it was already handed the answer to.
        """
        ac = self.aircraft.get(self._resolve(callsign))
        if ac is not None and profile is not None:
            ac.profile = profile
            if named:
                ac.approach = named

    def note_cleared_level(self, callsign: str, ft: int | None) -> None:
        """The cruise level his IFR clearance carries. Told, not decided.

        The clearance is composed by the director's tool and recorded on the
        board, so this engine did not issue it and could not have known it --
        which is why a pilot level at his cleared altitude could be told he was
        at the wrong one. It has a field for it now, kept apart from the one
        this engine assigns, and the bridge sets it from the board every turn.

        Deliberately not a decision and deliberately not `assigned_ft`: nothing
        was separated by this number, and writing it where the stack lives would
        make a cruise level into a holding slot the first time somebody entered
        the pattern.
        """
        ac = self.aircraft.get(self._resolve(callsign))
        if ac is not None and ft:
            ac.cleared_ft = int(ft)

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
                 # WHERE HE IS ON THE LADDER, which is a different question from
                 # where he is in the arrival queue and the one that decides who
                 # has him next -- `handoff.py` reads `sortie_phase`, and a
                 # ground transition IS the handoff (a phase with no geometry is
                 # owned outright by the controller `phases.py` names).
                 #
                 # The board carried the separation enum alone, so everything
                 # downstream of the engine -- the recorder, the diagnostics
                 # page, the ladder rehearsal -- could see that a parked
                 # aeroplane was ENROUTE and could not see that he was holding
                 # short. The engine has always known. Nothing could ask.
                 "sortie_phase": getattr(ac, "sortie_phase", "") or "",
                 "assigned_ft": ac.assigned_ft, "identified": ac.radar_identified,
                 "members": list(ac.members), "approaches": ac.approaches,
                 # WHICH PROCEDURE, not just which phase. CLEARED means he is in
                 # the letdown; it does not say whether he is flying the
                 # surveillance approach or looking out of the window, and those
                 # are different jobs for the controller. The engine has always
                 # known -- it is what stops it reading him vectors he does not
                 # want -- and it was the one thing about him nothing could ask.
                 "on_visual": ac.on_visual,
                 # THE TRACK, FROM THE BOARD ITSELF. It used to be joined on
                 # afterwards by matching names, which is the bug in
                 # `HANDOFF-board.md`: one failed lookup emptied a whole row and
                 # a live aeroplane aged off the board nine times in one sortie.
                 # A row now carries its own key and there is nothing to match.
                 "track": ac.track,
                 "owner": ac.owner,
                 "intent": ac.intent,
                 # WHICH APPROACH HE IS CLEARED FOR. In the database since the
                 # plans table, on the strip since migration 025, read on every
                 # transmission -- and never shown to anybody. See
                 # `assign_approach`.
                 "cleared_approach": getattr(ac, "approach", "") or "",
                 "in_letdown": cs == self._in_letdown(ac)}
                for cs, ac in sorted(self.aircraft.items())]

    def bind(self, cs: str, track: str = "", owner: str = "") -> Aircraft:
        """Record the two opaque facts about an entry: his track, and who owns him.

        WHY THIS IS NOT THE ENGINE GOING SIGHTED. Neither value is telemetry.
        `track` is a name the sim gave an aeroplane and `owner` is a role read
        off the frequency the call arrived on; nothing here reads a position, and
        no separation decision anywhere in this class consults either. They are
        stored because THIS is the one place both are known at once, and every
        attempt to recover them later has been a string match that got it wrong.

        A HANDOFF IS AN OWNER CHANGE, NOT A RELEASE. Passing a new `owner` moves
        him directly; he is never unowned in between. That is the whole
        distinction the board was missing -- the only way off it is `release`.

        Neither value is ever cleared by a later call that does not know it. A
        transmission relayed without a radar picture must not erase the track a
        previous one established, so an empty argument means "no news", not
        "forget".
        """
        ac = self.get(cs)
        if track:
            ac.track = track
        if owner:
            ac.owner = owner
        return ac

    def note_vectored(self, cs: str, alt_ft: int | None) -> None:
        """Record an altitude the RADAR side issued, so the board is not stale.

        THE ASR THREAD IS A SECOND CONTROLLER THAT KEPT NO RECORDS. It computes
        vectors and a descent profile and transmits them directly -- no model,
        no engine -- and until now it told this class nothing. So the board went
        on showing whatever `intents.dispatch` last agreed while the pilot was
        being flown somewhere else entirely. Found on the radio:

            "Doing it says cleared 5,000 but I'm currently cleared to 2,000...
             I believe the reason the board isn't getting updated is that the
             ASR process doesn't update the status on the board."

        Correct, and it is the same shape as every other bug this week: two
        things issuing instructions and one of them keeping the records.

        IT DOES NOT TOUCH `phase`. Being vectored down the approach is not a
        state transition -- he is already CLEARED and stays so until he reports
        the field, goes missed, or lands. This records the NUMBER, which is what
        was wrong; the phase machine is not the ASR's business.

        Nor does it invent an entry. An aircraft the engine has never heard of
        does not get one because radar talked to him -- that is the ghost door,
        and `note_radar_contact` guards it the same way.
        """
        ac = self.aircraft.get(self._resolve(cs))
        if ac is not None and alt_ft:
            ac.assigned_ft = int(alt_ft)

    def note_intent(self, cs: str, intent: str) -> None:
        """What he told the controller he wants.

        Recorded rather than inferred: this is the one fact on the board that
        can only come from the pilot saying so, and a guess at it is a guess at
        the whole reason he is on the frequency.

        NEVER CREATES AN ENTRY, and the first version did. `get` is a
        `setdefault`, so writing an intention through it would let a SENTENCE
        put an aeroplane on the board -- the exact ghost door this project spent
        a month closing, reopened by a display feature. `note_radar_contact` has
        the same shape for the same reason.

        An empty intent is ignored so a request survives the read-backs that
        follow it: he asks for the approach once and then says "heading one six
        nine" twenty times, and none of those should erase what he is here for.
        """
        ac = self.aircraft.get(self._resolve(cs))
        if ac is not None and intent:
            ac.intent = intent

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

    def _report_phrase(self, ac=None) -> str:
        """What he should call next. Never a trigger he cannot detect.

        This used to say "never a fix he cannot navigate to", which is the same
        rule stated narrowly -- and being ESTABLISHED is exactly such a trigger
        on a talkdown, where he has no localiser to be established ON:

            "A pilot doesn't know when he is established -- everything he gets
             he gets from the talk down. That instruction belongs in the ils
             module."

        So it is asked only where the aeroplane can answer it. On a surveillance
        approach the controller reads him the course every mile, and the only
        thing the pilot reports is what he can see out of the window.
        """
        pro = self._pro(ac)
        if self._vectored:
            if getattr(pro, "guidance", "") == "talkdown":
                return "report the field in sight"
            return "report established on the final approach course"
        return f"report {pro.beacon.name} inbound"

    def _no_acknowledgement_phrase(self) -> str:
        """Said ONCE, with the approach clearance, on a talkdown. Then never.

            "on an ASR approach, you should tell me at the beginning of the
             approach not to read back"

        Real procedure rather than a nicety. On a surveillance approach the
        controller talks continuously -- a course and a range every mile -- and a
        read-back of each one puts the pilot on the air over the next
        instruction. The phrase exists so he knows the silence is expected.

        ONLY WHERE HE WOULD OTHERWISE ACKNOWLEDGE, which is the talkdown. On an
        ILS the controller says almost nothing after the clearance and the pilot
        DOES report established -- telling him not to acknowledge would be
        telling him not to make the one call the procedure needs. [#99]
        """
        if self._vectored and getattr(self.profile, "guidance", "") == "talkdown":
            return " Do not acknowledge further transmissions."
        return ""

    def _atis_phrase(self, ac) -> str:
        """Confirm the information, then ask what he wants. Never refuse.

        Only from a seat that would actually do it -- Approach and Clearance
        are the two that check, and Tower asking a man on short final which
        information he has is noise at the worst moment.

        THREE CASES, and they are genuinely different on the radio:

            right letter    acknowledged in passing, then the real question
            wrong letter    given the current one, because he is working from
                            weather that has moved -- and that is the entire
                            point of the letter existing
            said nothing    asked, without being told off. Most pilots have it
                            and forgot to say so.
        """
        if not self._owns("approach") and not self._owns("clearance"):
            return ""
        # AND ONLY OF SOMEBODY ARRIVING, or on the ground about to depart.
        #
        #     "I had an IFR flight plan open and now they're asking for my
        #      intent."
        #
        # A pilot climbing out on a clearance he read back four minutes ago has
        # already said what he wants, and the ATIS he needs is the one at the
        # field he is going TO, not the one he just left. Departure and Center
        # ask him nothing; Approach and Clearance ask, which is who actually
        # does it.
        _on_the_ramp = (getattr(ac, "sortie_phase", "") or "").lower() in (
            "", "unknown", "clearance", "taxi", "holding_short")
        if not self._arriving(ac) and not _on_the_ramp:
            return ""
        from marshall.core import route as _R
        me = getattr(self, "_me", None)
        fld = _R.field_named(getattr(me, "field", "") or _R.ARRIVAL_FIELD)
        if fld is None:
            return ""
        from marshall.atis import store as _atis
        now = _atis.current(fld)
        if not now.on_the_air or not now.letter:
            # No broadcast at this field. Asking a pilot to confirm an ATIS
            # that does not exist is how you get a confused read-back.
            return "Say your request."
        said = getattr(ac, "atis_letter", "") or ""
        if said and said.lower() == now.letter.lower():
            return f"Information {now.letter} is current. Say your request."
        if said:
            return (f"Information {now.letter} is current now, not "
                    f"{said}. Say your request.")
        return (f"Advise you have information {now.letter}. "
                f"Say your request.")

    def take_out(self) -> list:
        """Everything the engine has decided to say, and CLEAR it.

        THE ONLY WAY TO CONSUME THE OUTBOX, and it exists because reading it
        without clearing it produced a directive containing both a hold and a
        clearance -- 7 turns in 97 on a real sortie:

            "Hammer one one, hold at BATUMI as published, maintain five
             thousand. | Hammer one one, cleared radar approach runway 13"

        Those were not one decision. They were two turns' worth, because the
        drain was conditional -- it ran only when `intents.dispatch` returned
        True -- so anything queued on a turn it did not handle stayed in the
        list and reappeared beside the next turn's words. Contradictory
        instructions in one transmission, from the half that is supposed to be
        the reliable one.

        Draining is not a caller's decision to make. Whoever reads it takes it.
        """
        out, self.out = list(self.out), []
        return out

    def _anomaly(self, what: str) -> None:
        """Record an invariant that broke, and be noisy about it.

        Deliberately not an exception: the pilot is in the air and a controller
        that raises is worse than one that repairs and complains. But a repair
        nobody can see is how the CAUSE survives -- see `anomalies`.
        """
        self.anomalies.append((self.t, what))
        print(f"  !! CONTROLLER ANOMALY: {what}", flush=True)

    def note_unreachable(self, why: str) -> None:
        """An action the classifier chose that this procedure does not contain.

        NOT an anomaly. Nothing is broken -- a pilot read something back and the
        classifier, which only ever sees one sentence and a fixed menu, picked
        the nearest label. The engine declining to act is the correct outcome
        and the agent answers him normally.

        Logged anyway, and this is the whole reason it is a method rather than a
        bare `return`: the last suppression that went unlogged repeated twelve
        times in one sortie before a pilot noticed on the radio. If this line
        starts appearing on every transmission, the taxonomy is wrong and that
        should be visible from the log rather than from the air.
        """
        if why:
            self.unreachable.append((self.t, why))
            print(f"  .. engine stood down: {why}", flush=True)

    def say(self, to: str, text: str, ref: Aircraft | None = None,
            decided=None) -> None:
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
        self.out.append(Tx(to, text, self.t, freq, name, decision=decided))

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

    def _key(self, ac=None) -> str:
        """Which letdown/stack this aeroplane belongs to. The beacon's name.

        Empty for a controller with no profile at all, which is the unit-test
        and dry-run case -- one unnamed letdown, exactly as before.
        """
        return getattr(getattr(self._pro(ac), "beacon", None), "name", "") or ""

    def _in_letdown(self, ac=None) -> str | None:
        return self._letdown_by.get(self._key(ac))

    def _set_letdown(self, ac, who: str | None) -> None:
        k = self._key(ac)
        if who is None:
            self._letdown_by.pop(k, None)
            self._letdown_since_by.pop(k, None)
        else:
            self._letdown_by[k] = who
            self._letdown_since_by[k] = self.t

    def _same_stack(self, a, ref) -> bool:
        """Are these two aircraft holding over the same place?

        Two aerodromes are two stacks. A hold over Nellis and a hold over
        Tonopah are a hundred and twenty miles apart and share no airspace, so
        an aeroplane waiting for one is not in the other's way -- and must not
        be able to reserve a level in it.

        Compared by the procedure's BEACON, which is the fix the pattern is
        flown over, rather than by profile identity: two aircraft recovering to
        one field on one approach are the same stack whether or not they were
        handed the same object.
        """
        if ref is None:
            return True
        mine = getattr(getattr(self._pro(ref), "beacon", None), "name", "")
        his = getattr(getattr(self._pro(a), "beacon", None), "name", "")
        return (not mine) or (not his) or mine == his

    def _holders(self, ref=None) -> list[Aircraft]:
        # Callsign breaks ties so a flight sharing one level under visual
        # separation still sequences lead first (Pony 1-1 before Pony 1-2).
        return sorted((a for a in self.aircraft.values()
                       if a.phase == Phase.HOLDING and a.assigned_ft is not None
                       and self._same_stack(a, ref)),
                      key=lambda a: (a.assigned_ft, a.callsign))

    def _spoken_for(self, ref=None) -> set:
        """Stack levels occupied by somebody who is NOT in the holding stack.

        THE LEVEL IS HIS UNTIL HE IS OUT OF IT. An aircraft cleared for the
        approach keeps the altitude he was holding at -- it is the altitude he
        flies the letdown at -- and he does not leave it the instant he is
        cleared. He is still up there.

        This engine used to hand that level straight to the next arrival,
        because `_free_slot` counted only aircraft whose phase was HOLDING and
        a cleared one is not. Three aeroplanes arriving together produced:

            Alpha 1      CLEARED   assigned=5000   <- letdown
            Bravo 1      HOLDING   assigned=5000

        Two aircraft at one altitude, which on THIS approach means nothing
        separates them at all. `ApproachProfile.stack_ft` says why, about
        itself: a beacon letdown holds aircraft over a fix and the fix is what
        keeps them apart, but "take the beacon away, as a radar approach does,
        and there is no pattern and nothing to hold over ... the levels still
        provide the separation". The level IS the separation here. Sharing one
        is not a tighter margin, it is no margin.

        Costs one holding level while somebody is on the approach, which is not
        a loss: a level with an aeroplane in it was never free.

        A missed approach and an aircraft under vectors reserve their levels for
        the same reason -- they are aeroplanes at an altitude, and where they
        got it does not change what a holder above them needs. Landed and
        banished aircraft do not: they are gone.
        """
        return {a.assigned_ft for a in self.aircraft.values()
                if a.assigned_ft is not None
                and a.phase not in (Phase.HOLDING, Phase.LANDED, Phase.BANISHED)
                and self._same_stack(a, ref)}

    def _free_slot(self, ac=None) -> int | None:
        """Lowest level nobody is at IN HIS STACK -- a new arrival enters here,
        on top of everyone already placed (the stack fills from the bottom up).

        NOBODY IS AT, not nobody holds. See `_spoken_for`.

        HIS STACK, and that is not pedantry once there are two aerodromes. A
        hold over Nellis and a hold over Tonopah are a hundred and twenty miles
        apart; they share no airspace, and an aeroplane waiting for one is not
        in the other's way. Counting them together would hand the second arrival
        a level for no reason -- and, worse, would let an aircraft on ANOTHER
        field's approach reserve a level here.
        """
        stack = list(getattr(self._pro(ac), "stack_ft", ()) or ())
        taken = ({a.assigned_ft for a in self._holders(ac)}
                 | self._spoken_for(ac))
        for ft in stack:
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
        return self._in_letdown()

    def waiting(self) -> list[str]:
        """Everyone who is not the one being worked. They hold; they are not
        vectored, because a vector is an invitation to start the approach."""
        return [cs for cs, ac in self.aircraft.items()
                if cs != self._in_letdown()
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
        self._set_letdown(ac, ac.callsign)
        return True

    def _arriving(self, ac) -> bool:
        """Is this aeroplane on its way IN?

        The question a check-in reply turns on, and nothing used to ask it. One
        controller frequently works both ends -- Kobuleti Departure also works
        Kobuleti's arrivals, Batumi Approach also works its departures -- so the
        SEAT cannot answer it and the phase can.

        Unknown counts as arriving, because that is what every sortie looked
        like until the ladder grew a ground half: a voice out of nowhere,
        inbound, wanting an approach. Being asked to report the field in sight
        when you are not arriving is untidy; NOT being asked when you are is a
        controller who has not understood what you want.
        """
        from marshall.atc import phases as _phases
        phase = (getattr(ac, "sortie_phase", "") or "").lower()
        if not phase or phase == "unknown":
            return True
        # `rtb` is going home, which is arriving with more miles to run.
        # `enroute` deliberately is NOT: the long middle of a sortie could be
        # bound anywhere, and Georgia Center asking a man thirty miles out to
        # report the field in sight is the same wrong question one seat over.
        return _phases.owner_of(phase) == "approach" or phase == "rtb"

    def check_in(self, cs: str, size: int = 1) -> None:
        ac = self._enter(cs, size)
        # A CHECK-IN DOES NOT UNDO A CLEARANCE. This is the root cause of #50,
        # and it was one unguarded line.
        #
        # A pilot checks in every time he changes frequency, and the ladder
        # gives him six or seven of those in a sortie. This set him back to
        # ENROUTE each time -- including AFTER he had been cleared for the
        # approach and put in the letdown. `_letdown` still named him, because
        # nothing here touches it. He was then an ENROUTE aircraft holding the
        # approach slot, so the next `request_approach` walked straight into
        # the stack (which only admits UNKNOWN/ENROUTE) and made him a HOLDER
        # who was also the aircraft on the approach.
        #
        # From there `_try_clear` found the letdown occupied and told him he
        # was number two behind the only other aeroplane in the sky, which was
        # him. He held for four transmissions at 44 nm and declared an
        # emergency. Live, 31 July, Fred's first sortie.
        #
        # `seed_from_radar` directly above has exactly this guard already --
        # "already known to be on it" -- and returns without touching the
        # phase. The two functions do the same job from different evidence and
        # only one of them protected the clearance.
        #
        # LANDED is held for the same reason: an aeroplane on the ground that
        # says something is not enroute, and demoting him would put a taxiing
        # jet back in the arrival flow.
        if ac.phase not in (Phase.CLEARED, Phase.LANDED):
            ac.phase = Phase.ENROUTE
        ac.last_report_t = self.t

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
        # WHO IS ACTUALLY SPEAKING, when the bridge has told us.
        #
        # This read `station(enroute=True)` unconditionally, which is Center --
        # so Batumi Approach greeted a pilot as "Georgia Center". The engine is
        # blind by design and that was the right answer while it had no idea
        # who it was; it has known since `_me` arrived, and this was still
        # asking the profile.
        #
        # Falls back to the enroute station when nobody has told us, which is
        # every unit test and the dry runs -- see `_owns` for the same rule.
        me = getattr(self, "_me", None)
        if me is not None and getattr(me, "name", ""):
            here, here_freq = me.name, me.freq_mhz
        else:
            here, here_freq = self.profile.station(enroute=True)
        tower, tower_freq = self.profile.station()
        fix = self._pro(ac).arrival_fix
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
                    f"{self._pro(ac).beacon.name} from there.")
        elif self._arriving(ac) and (self._owns("approach")
                                     or self._owns("center")):
            call = (f"{self._addr(ac)}, {here}, "
                    f"{self._report_phrase()}.")
        elif self._owns("departure") or self._owns("center"):
            # A DEPARTING AIRCRAFT IS NOT ASKED TO REPORT THE FIELD IN SIGHT.
            #
            #     "why would it ask for the field in sight, and why would it be
            #      asking for information alpha at this field"
            #
            # He had just lifted off. Kobuleti Departure wears the approach hat
            # -- `also=("approach",)`, correctly, because it works Kobuleti's
            # arrivals too -- so `_owns("approach")` was true and he got the
            # ARRIVAL greeting on climb-out. The seat could not tell the two
            # jobs apart, because a seat is not what tells them apart.
            #
            # The PHASE is. One man works both, and what he says depends on
            # which way the aeroplane is going -- see `phases.py`, which has
            # said so since it was written.
            call = f"{self._addr(ac)}, {here}, radar contact."
        else:
            # A GROUND SEAT DOES NOT ASK FOR A POSITION REPORT. "Report BATUMI
            # inbound" from Clearance, to a man who has not started his engine,
            # is a radar controller's line coming out of the wrong mouth -- and
            # it only became reachable when the ladder grew seats below
            # Approach. What Clearance and Ground want is the request, which
            # `_atis_phrase` asks for.
            call = f"{self._addr(ac)}, {here}."
        # THE ATIS AND HIS INTENTIONS, and neither of them gates anything.
        #
        #     "Approach should confirm they have information Bravo and ask what
        #      approach they want."
        #
        # Which fixes a real complaint from the air -- "approach just assumed I
        # was flying the ASR" -- and it is the same fault as everywhere else in
        # this system: a controller answering a question the pilot did not ask.
        # There are two approaches published at Batumi and a visual is always
        # available; which one he wants is his to say.
        #
        # ATC DOES NOT GATE THE APPROACH. A wrong letter or no letter is
        # answered with the current one and the sortie continues -- it is a
        # courtesy and a cross-check, never a condition. A pilot may call the
        # field in sight and take the visual at any point regardless.
        extra = self._atis_phrase(ac)
        if extra:
            call = f"{call} {extra}"
        # THE LETTER IS A FACT, so it goes across the seam as one.
        #
        #     "he never once said 'advise you have information alpha'"
        #
        # The engine asked for it on three consecutive transmissions and the
        # agent dropped it every time. Nothing noticed, because this path
        # composes PROSE and only a `Decision` is verified -- the whole point of
        # #79. A directive the engine issued can still vanish silently as long
        # as it carries no decision, which is what this closes.
        #
        # Attached whenever a letter is in play at all, not only for the
        # "advise you have" wording: "information Bravo is current now, not
        # Alpha" carries the same fact and is just as droppable.
        letter = _atis_letter_in(extra)
        self.say(ac.callsign, call,
                 decided=(D.Decision(kind="advise_atis", to=ac.callsign,
                                     atis_letter=letter) if letter else None))

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
        if self._in_letdown(ac) == ac.callsign:
            self._set_letdown(ac, None)
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
            slot = self._free_slot(ac)
            if slot is None:
                # NOT a `hold` decision: there is no hold to give. Naming it one
                # would have `reconcile` suppress a vector to protect a holding
                # clearance that does not exist.
                self.say(ac.callsign,
                         f"{self._addr(ac)}, no holding available, remain clear.")
                return
            ac.phase, ac.assigned_ft = Phase.HOLDING, slot
            # Through `_hold_phrase`, not around it. This path wrote its own
            # "hold at BATUMI as published" and so told a pilot on a RADAR
            # approach to hold over a beacon he has no receiver for -- the exact
            # thing the phrase function exists to decide. Two ways of saying the
            # same thing is how one of them ends up wrong.
            # A DECISION BESIDE THE WORDS. `reconcile` decides which authority
            # owns this aeroplane, and it used to answer "is this a hold?" by
            # searching this sentence for the word -- so a rephrasing here
            # silently changed a separation decision two modules away. It reads
            # the kind now, which is why every holding path has to carry one.
            self.say(ac.callsign,
                     f"{self._addr(ac)}, {self._hold_phrase(slot, ac.kit)}.",
                     decided=D.Decision(kind="hold", to=ac.callsign,
                                        altitude_ft=slot))
            self._try_clear()
        elif ac.phase == Phase.CLEARED:
            # Established inbound on the beam: start the station-passage clock.
            # The pilot flies the MAP on a watch; ATC times the same number and
            # calls it as backup (aural station passage does not read in the sim).
            ac.map_t = self.t + self._pro(ac).final_approach_sec
            self.say(ac.callsign,
                     f"{self._addr(ac)}, roger, station passage "
                     f"{spell_dur(self._pro(ac).final_approach_sec)}, "
                     f"report field in sight or missed approach.")
        elif (altitude_ft and ac.governing_ft
              and altitude_ft != ac.governing_ft):
            # He is not where he was put. Reading his own number back to him is
            # how two aeroplanes end up at the same level in cloud -- especially
            # just after a break-up, when three wingmen have all just been given
            # a new altitude and one of them heard someone else's.
            #
            # `governing_ft`, NOT `assigned_ft`. This gate used to be blind to
            # the clearance: en route the engine has assigned nothing, so a
            # pilot level at his cleared altitude fell through to the `roger`
            # below and nothing in the engine had an opinion about his level at
            # all -- which is what left the agent free to assert one. It also
            # means the CORRECTION now carries the clearance's number when that
            # is the number he is held to, instead of having none to carry.
            want = ac.governing_ft
            verb = "descend and maintain" if altitude_ft > want else "climb and maintain"
            self.say(ac.callsign,
                     f"{self._addr(ac)}, negative, you are assigned "
                     f"{spell_alt(want)}, {verb} {spell_alt(want)}.",
                     decided=D.Decision(kind="level", to=ac.callsign,
                                        altitude_ft=want))
        else:
            # HE IS WHERE HE SHOULD BE. The number still goes out as a decision:
            # "roger, five thousand" is an assertion about his altitude and the
            # verifier has to be able to check it, which is the whole of #98's
            # third criterion -- a pilot level at his cleared altitude is never
            # corrected onto another.
            _lvl = altitude_ft or ac.governing_ft or 0
            self.say(ac.callsign,
                     f"{self._addr(ac)} roger, {spell_alt(_lvl)}.",
                     decided=(D.Decision(kind="level", to=ac.callsign,
                                         altitude_ft=_lvl) if _lvl else None))

    def _do_missed(self, ac: Aircraft) -> bool:
        """Missed-approach state transition. Returns True if banished (2nd miss)."""
        ac.approaches += 1
        ac.last_report_t = self.t
        ac.map_t = None
        if self._in_letdown(ac) == ac.callsign:
            self._set_letdown(ac, None)
        if ac.approaches >= MAX_APPROACHES:
            ac.phase, ac.assigned_ft = Phase.BANISHED, self._pro(ac).top_ft
            return True
        ac.phase, ac.assigned_ft = Phase.MISSED, self._pro(ac).missed_ft
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
        if self._in_letdown(ac) == ac.callsign:
            self._set_letdown(ac, None)
        # THE RUNWAY IS TOWER'S. Anybody else who has the field in sight gets
        # sent to the man who can actually give him the runway, rather than a
        # clearance the speaker had no authority to issue. A pilot cannot tell
        # the difference on the radio, which is exactly why it matters: he lands
        # believing he was cleared, and Tower never knew he was there.
        # HIS field. `station_for` answers the first role match when it is not
        # given one, and on a two-aerodrome map that is a real controller at
        # the wrong airport -- a pilot on final at Batumi was told to "contact
        # Kobuleti Tower one three three decimal zero for landing", and then
        # welcomed on the ground by Kobuleti Tower, forty miles from where he
        # had parked.
        twr = self.profile.station_for(
            "tower", field=getattr(getattr(self, "_me", None), "field", ""))
        if self.working and twr is not None and self.working != "tower":
            self.say(ac.callsign,
                     f"{self._addr(ac)}, roger, field in sight, contact "
                     f"{twr.name} {spell_freq(twr.freq_mhz)} for landing.")
            self._try_clear()
            return
        # He has the field. What a controller owes him now is the CLEARANCE and
        # the wind -- not a verdict on whether the landing is assured, which is
        # the pilot's call and not a phrase a real controller uses.
        # THE RUNWAY IN USE AT HIS FIELD, not the profile's. `profile.runway`
        # is the runway of the approach being FLOWN, which is the arrival
        # field's -- so Kobuleti Tower cleared a landing on runway one three,
        # which is at Batumi. Same source as the taxi and take-off clearances,
        # so all three name one runway; see `_runway_in_use`.
        self.say(ac.callsign,
                 f"{self._addr(ac)}, roger, cleared to land runway "
                 f"{self._runway_in_use()}, {self._wind_phrase()}")
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
        # THE SORTIE PHASE, TOO, and leaving it out is why nothing could hand a
        # landed aeroplane to Ground (#77). `Phase.LANDED` is the SEPARATION
        # engine's enum -- where he sits in the arrival queue. `sortie_phase` is
        # what he is DOING, and it is the one the ladder reads: `handoff.due`
        # gives a phase whose `aims_at` is "none" to the controller the phase
        # table names, and `landed` is Tower's. Without it he stayed in whatever
        # phase the approach left him in and the ground ladder never resumed.
        ac.sortie_phase = "landed"
        ac.map_t = None
        if self._in_letdown(ac) == ac.callsign:
            self._set_letdown(ac, None)
        # HIS field. This welcomed a pilot who had just landed at Batumi as
        # "Kobuleti Tower" -- the last thing said on the whole sortie.
        twr = (self.profile.station_for(
                   "tower", field=getattr(getattr(self, "_me", None), "field", ""))
               if hasattr(self.profile, "station_for") else None)
        who = f"{twr.name}, " if twr else ""
        # "TAXI TO PARKING" IS NOT TOWER'S TO SAY, and this said it on every
        # landing. Tower owns the runway; the taxiways are Ground's. A pilot
        # reported it from the cockpit:
        #
        #     "Batumi Tower ... just gave me clearance to taxi to parking when
        #      that's ground's job"
        #
        # Exactly the fault that made Ground clear an aircraft for take-off, in
        # the other direction -- a seat answering for something it does not own.
        # What Tower owes him is the runway: get off it. Where to go afterwards
        # is the next controller's, and the phase above is what hands him over.
        self.say(ac.callsign,
                 f"{self._addr(ac)}, {who}welcome. Exit the runway when able.")
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
        runway = self._pro(ac).runway or "in use"
        if not self._in_letdown(ac) or self._in_letdown(ac) == ac.callsign:
            self._set_letdown(ac, ac.callsign)
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
            ac.assigned_ft = self._free_slot(ac) or self._pro(ac).bottom_ft
        place = len(self._holders(ac))
        words = ["", "one", "two", "three", "four", "five", "six"]
        self.say(ac.callsign,
                 f"{self._addr(ac)}, {self._hold_phrase(ac.assigned_ft, ac.kit)}. "
                 f"Expect the visual, you are number "
                 f"{words[place] if place < len(words) else place}.",
                 decided=D.Decision(kind="hold", to=ac.callsign,
                                    altitude_ft=ac.assigned_ft))

    def _wind_phrase(self) -> str:
        """The wind, on the clearance that ends with a landing or a take-off.

        A DIRECTION IS THREE DIGITS AND A SPEED IS NOT. The direction is spelled
        digit by digit because that is how a bearing is said; the speed is a
        number said as a number. Slicing the last nine characters off a spelled
        bearing gave "wind zero nine zero at zero five" -- five knots dressed as
        a heading, and nobody says that.
        """
        from marshall.core import route as _R
        return (f"wind {spell_hdg(int(_R.WIND_FROM_DEG))} at "
                f"{spell_count(_R.WIND_MPH)}.")

    # -- the ground half ---------------------------------------------------
    #
    #     "Clearance should handoff to ground for taxi clearance. Ground should
    #      clear to the runway only, telling them to hold short of the runway.
    #      Once they check in and report holding short they should be handed
    #      off to tower. Ground should not clear for takeoff. That's tower."
    #
    # THESE MOVE `sortie_phase` AND NOTHING ELSE. There is no stack on the
    # ramp, no levels and no sequence, so the separation engine has nothing to
    # say here and must not pretend otherwise -- an aeroplane holding short is
    # UNKNOWN to it and perfectly well defined to the sortie.
    #
    # The handoffs are a consequence of the phase and are not issued here: see
    # `handoff.due`, where a phase with no geometry is owned outright by the
    # controller the phase table names. Adding pushback or de-icing later is a
    # phase and no code at all.

    def request_clearance(self, cs: str) -> None:
        """On the ramp, asking for his IFR clearance.

        AND THE ATIS, because delivery is where it belongs. This moved the phase
        and said nothing, so the first controller of the sortie -- the one whose
        whole job is handing over the numbers a pilot writes down -- was the one
        seat that never confirmed he had the weather:

            "Clearance ... never did ask that I had information [alpha]"

        Every later seat asked, because `check_in` composes it and they are the
        ones a pilot checks in with. He does not check in with Delivery; he asks
        for a clearance. Real delivery asks on the first call, before the
        numbers, because the letter says which runway and which approach to
        expect.

        The words are `_atis_phrase`'s, so the four shapes -- current,
        superseded, not yet advised, no broadcast at all -- stay in one place
        rather than being written twice.
        """
        ac = self.get(cs)
        ac.sortie_phase, ac.last_report_t = "clearance", self.t
        extra = self._atis_phrase(ac)
        letter = _atis_letter_in(extra)
        if not letter:
            return                      # no broadcast here; nothing to confirm
        self.say(ac.callsign, f"{self._addr(ac)}, {extra}",
                 decided=D.Decision(kind="advise_atis", to=ac.callsign,
                                    atis_letter=letter))

    def clearance_read_back(self, cs: str, correct: bool | None = True,
                            missed: tuple = ()) -> None:
        """The read-back, and the one place 'readback correct' belongs.

        A CORRECT read-back is what ends Delivery's business and hands him to
        Ground -- so this is the transition, not the words. A WRONG one leaves
        him exactly where he is, which is the whole point of reading it back:
        he does not move until the numbers agree.
        """
        ac = self.get(cs)
        ac.last_report_t = self.t
        # NONE IS NOT FALSE. None means nobody could judge it -- no clearance on
        # the board to compare against -- and an unjudged read-back must leave
        # the phase exactly where it is. Treating it as correct would hand a
        # pilot to Ground in the same breath as being told his squawk is wrong;
        # treating it as wrong would strand a man who read it back perfectly.
        if correct is True:
            ac.sortie_phase = "taxi"
            return
        if correct is False and missed:
            # NAME WHAT HE MISSED, from the verifier that found it. The agent
            # used to compose this sentence itself, which meant guessing which
            # element was wrong -- and it guessed "altitude" at a pilot who had
            # read the altitude back perfectly and dropped the squawk.
            #
            # A read-back that is wrong is not a rebuke; it is a request for one
            # element again. Saying which one is the whole value of the reply.
            what = ", ".join(str(m) for m in missed)
            self.say(ac.callsign,
                     f"{self._addr(ac)}, negative — say again {what}.",
                     decided=D.Decision(kind="say_again", to=ac.callsign,
                                        note=what))

    def taxi_in(self, cs: str) -> None:
        """He is off the runway and wants a stand. GROUND'S, and the last of it.

            PILOT: Taxi to parking my discretion, sockeye.
            ATC:   Sockeye, contact Batumi Tower one one eight decimal six.
            PILOT: Batumi Ground, don't you own parking instructions?

        He does. Two things were wrong and they compound.

        `landed` is TOWER's phase, correctly -- the roll is over and he is still
        on the strip. Nothing moved him off it, so Ground looked at a landed
        aeroplane, read Tower's phase, and handed him BACK. A rung that hands
        backwards puts a pilot on a frequency whose controller has finished with
        him, which is how a man ends up talking to nobody at the end of a flight.

        And parking was owned by nobody. Tower stopped saying it (correctly --
        the taxiways are not his) and Ground never started, so the last
        instruction of the sortie fell down the gap between two seats.

        `taxi_in` is Ground's and NOTHING follows it. He is the end of the
        ladder. [#100]
        """
        ac = self.get(cs)
        ac.sortie_phase, ac.last_report_t = "taxi_in", self.t
        if not self._owns("ground"):
            # Not his to give. Same shape as Ground refusing a take-off: name
            # the man who owns it rather than answering for him.
            gnd = (self.profile.station_for(
                       "ground", field=getattr(getattr(self, "_me", None),
                                               "field", ""))
                   if hasattr(self.profile, "station_for") else None)
            if gnd is not None:
                self.say(ac.callsign,
                         f"{self._addr(ac)}, parking is Ground's, contact "
                         f"{gnd.name} {spell_freq(gnd.freq_mhz)}.",
                         decided=D.Decision(kind="refuse", to=ac.callsign,
                                            role="ground", station=gnd.name,
                                            frequency_mhz=gnd.freq_mhz))
            return
        self.say(ac.callsign,
                 f"{self._addr(ac)}, taxi to parking, your discretion.",
                 decided=D.Decision(kind="taxi", to=ac.callsign,
                                    note="parking"))

    def request_taxi(self, cs: str) -> None:
        """Ready to move. Ground's, and Ground clears him TO the runway only.

        The phase moves either way -- he IS ready to taxi and saying so on the
        wrong frequency does not make it untrue -- but only Ground issues the
        instruction. Symmetric with `request_takeoff`: a controller answers for
        what he owns and points at the man who owns the rest.
        """
        ac = self.get(cs)
        ac.sortie_phase, ac.last_report_t = "taxi", self.t
        if not self._owns("ground"):
            self._not_mine(ac, "ground", "Taxi")
            return
        rwy = self._runway_in_use()
        self.say(ac.callsign,
                 f"{self._addr(ac)}, taxi to runway {rwy}, "
                 f"hold short of runway {rwy}.",
                 decided=D.Decision(kind="taxi", to=ac.callsign, runway=rwy))

    def _owns(self, role: str) -> bool:
        """Is this seat the one that issues that clearance?

        `None` means the bridge has not told us who is speaking, and everything
        behaves as it always did -- the engine is blind by design and must not
        start refusing work because it was not told.
        """
        me = getattr(self, "_me", None)
        if me is None or not getattr(me, "role", ""):
            return True
        return me.role == role or role in getattr(me, "also", ())

    def _not_mine(self, ac, role: str, what: str) -> None:
        """Point him at the man who owns it, with the frequency.

        Naming only the position leaves him hunting for a number while taxiing;
        naming the frequency is the difference between a handoff and a hint.
        """
        me = getattr(self, "_me", None)
        who = self.profile.station_for(role, field=getattr(me, "field", ""))
        where = (f", contact {who.name} {spell_freq(who.freq_mhz)}"
                 if who is not None else "")
        self.say(ac.callsign,
                 f"{self._addr(ac)}, {what} is {role.title()}'s{where}.",
                 decided=D.Decision(
                     kind="refuse", to=ac.callsign, role=role,
                     station=getattr(who, "name", ""),
                     frequency_mhz=getattr(who, "freq_mhz", None)))

    def report_holding_short(self, cs: str) -> None:
        """Stopped at the edge. Ground is finished; Tower owns the runway."""
        ac = self.get(cs)
        ac.sortie_phase, ac.last_report_t = "holding_short", self.t

    def request_takeoff(self, cs: str) -> None:
        """Asking for the runway. TOWER ONLY, and the refusal is deliberate.

        Ground moves aeroplanes on taxiways; the runway is one controller's and
        nobody else's. A ground controller who answers this is not being
        helpful, he is issuing a clearance that is not his -- which is the
        aerodrome half of the invariant that keeps an LLM out of separation.
        """
        ac = self.get(cs)
        ac.last_report_t = self.t
        if not self._owns("tower"):
            self._not_mine(ac, "tower", "Take-off")
            return
        ac.sortie_phase = "departure"
        rwy = self._runway_in_use()
        self.say(ac.callsign,
                 f"{self._addr(ac)}, runway {rwy}, cleared for take-off, "
                 f"{self._wind_phrase()}",
                 decided=D.Decision(kind="cleared_takeoff", to=ac.callsign,
                                    runway=rwy))

    def _runway_in_use(self) -> str:
        """Two digits, ASKED OF THE BROADCAST -- see `atis/store.py`.

        Read here rather than remembered so a ground instruction and a take-off
        clearance cannot name different runways, and asked rather than computed
        so neither of them can disagree with the recording.
        """
        from marshall.core import route as _R
        # HIS field, not the profile's. A ground instruction at Kobuleti must
        # name Kobuleti's runway; the profile describes the approach at the
        # other end of the route and its runway is 13.
        me = getattr(self, "_me", None)
        fld = _R.field_named(getattr(me, "field", "") or _R.ARRIVAL_FIELD)
        if fld is None:
            return spell_rwy(self.profile.runway) if self.profile.runway else "in use"
        # ASKED, NOT COMPUTED. `runway_in_use()` is a pure function of the wind,
        # so calling it here would be a SECOND author for a decision that has
        # one -- and two authors agree only while they read the same wind at the
        # same instant. The broadcast is recorded at one moment and this taxi
        # clearance issued at another; between them the recording would say 07
        # and Ground 25, both correct and both defensible, with an aeroplane
        # lined up the wrong way. See `atis/store.py`.
        from marshall.atis import store as _atis
        return spell_rwy(_atis.runway_in_use(fld))

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
                     f"{self._pro(ac).runway or 'in use'}, continue.")
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
            slot = self._free_slot(ac)
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
        if held_at is not None and not (self._in_letdown(ac) is None
                                        and self._next_up(ac) is ac):
            self.say(ac.callsign,
                     f"{self._addr(ac)}, {self._pro(ac).controller}, "
                     f"{self._hold_phrase(held_at, ac.kit)}.",
                     decided=D.Decision(kind="hold", to=ac.callsign,
                                        altitude_ft=held_at,
                                        station=self._pro(ac).controller))
        self._try_clear(requested_by=ac.callsign)

    # -- the sequencing core ----------------------------------------------
    def _next_up(self, ref=None) -> Aircraft | None:
        """Who gets the next approach AT THIS FIELD: a go-around at the front of
        the line first, otherwise the bottom of that field's stack."""
        missed = [a for a in self.aircraft.values()
                  if a.phase == Phase.MISSED and self._same_stack(a, ref)]
        if missed:
            return min(missed, key=lambda a: a.approaches)
        holders = self._holders(ref)
        return holders[0] if holders else None

    def _try_clear(self, requested_by: str | None = None, ref=None) -> None:
        """Clear the next aircraft for approach, if HIS letdown block is free.

        `ref` names which letdown -- an aeroplane on the Nellis ILS does not
        wait for the approach at Tonopah to clear.

        WITH NO REFERENCE IT TRIES EVERY STACK, one at a time, and that is not a
        convenience. Defaulting to the BRIDGE's procedure looked right and was
        the bug: the free-letdown check ran against Tonopah's key while
        `_next_up` picked an aeroplane from Nellis's stack and cleared him, so
        both arrivals at Nellis were cleared for the same approach at once. The
        question "is the letdown free" cannot be asked without saying WHICH.
        """
        ref = ref if ref is not None else (
            self.aircraft.get(self._resolve(requested_by)) if requested_by else None)
        if ref is None and not requested_by:
            seen = set()
            for a in list(self.aircraft.values()):
                k = self._key(a)
                if k in seen:
                    continue
                seen.add(k)
                self._try_clear(ref=a)
            if not seen:                    # nobody on the board at all
                self._try_clear_one(None, None)
            return
        self._try_clear_one(requested_by, ref)

    def _try_clear_one(self, requested_by: str | None, ref) -> None:
        """One stack's worth of the above. Split out so the loop cannot recurse
        into itself and so every early return below still means one thing."""
        if self._in_letdown(ref) is not None:
            # NOBODY IS NUMBER TWO BEHIND HIMSELF, and this deadlocked a live
            # sortie until the pilot declared an emergency to get out of it.
            #
            # Sockeye was cleared for the approach, which put him in the
            # letdown. Something then returned him to HOLDING while he still
            # held the slot -- so he was simultaneously the aircraft on the
            # approach and an aircraft waiting for it. Every request after that
            # reached this branch, found the letdown occupied, and told him he
            # was number two behind the only other aeroplane in the sky, which
            # was him. `_next_up` would have returned him; it is never asked.
            #
            # He held for four transmissions, 44 miles out, nineteen miles
            # outside the airspace Approach would even have taken him in, and
            # then declared a Mayday. From the cockpit it is indistinguishable
            # from being forgotten.
            #
            # So: the man in the letdown is not held behind it. He is told to
            # continue, which is the truth -- he is already cleared -- and the
            # stack is left exactly as it is for everybody else.
            if requested_by and requested_by == self._in_letdown(ref):
                ac = self.aircraft.get(self._resolve(requested_by))
                if ac is not None and ac.phase == Phase.HOLDING:
                    # THIS STATE IS NOW IMPOSSIBLE, and reaching it is a bug
                    # rather than a case to handle quietly.
                    #
                    # The cause was `check_in` resetting a CLEARED aircraft to
                    # ENROUTE on every frequency change, which let him back
                    # into the stack while he still held the letdown. That is
                    # fixed where it happened. This branch stays because the
                    # radio answer is right whatever the cause -- you never
                    # tell a man he is number two behind himself -- but it must
                    # not silently absorb the next thing that breaks the
                    # invariant, so it says so.
                    self._anomaly(
                        f"{requested_by} was HOLDING while holding the "
                        f"letdown -- something demoted a cleared aircraft")
                    ac.phase, ac.last_report_t = Phase.CLEARED, self.t
                self.say(requested_by,
                         f"{requested_by}, you are cleared for the approach, "
                         f"continue.")
                return
            if requested_by:
                ac2 = self.aircraft.get(self._resolve(requested_by))
                self.say(requested_by, f"{requested_by}, continue holding, "
                                       f"number two, expect approach shortly.",
                         decided=D.Decision(
                             kind="continue_hold", to=requested_by,
                             altitude_ft=getattr(ac2, "assigned_ft", None)))
            return
        ac = self._next_up(ref)
        if ac is None:
            return

        was_bottom_holder = ac.phase == Phase.HOLDING
        ac.phase = Phase.CLEARED
        ac.last_report_t = self.t
        self._set_letdown(ac, ac.callsign)
        self.say(ac.callsign,
                 f"{self._addr(ac)}, cleared {self._approach_name()} runway "
                 f"{self._pro(ac).runway or 'in use'}, "
                 f"{self._report_phrase(ac)}. "
                 f"Report missed approach or landing."
                 f"{self._no_acknowledgement_phrase()}",
                 decided=D.Decision(kind="cleared_approach", to=ac.callsign,
                                    runway=self._pro(ac).runway or "",
                                    note=self._approach_name()))
        if was_bottom_holder:
            self._step_down(ac)

    def _step_down(self, ref=None) -> None:
        """The bottom slot just emptied; drop the stack down to close the gap.

        Steps LEVELS, not aircraft. Under visual separation a whole flight shares
        one level, and walking the holders one at a time would hand them
        4,000 / 5,000 / 6,000 -- silently undoing the visual break-up and
        re-separating a flight that had just been told to stay together.
        """
        levels = sorted({a.assigned_ft for a in self._holders(ref)})
        # DOWN TO THE LEVELS THAT ARE ACTUALLY FREE, which is not the same as
        # the bottom of the stack. The aircraft this step-down is making room
        # for is still at the level he was cleared from, so compressing the
        # holders onto `stack_ft[0..n]` would step the bottom one straight into
        # him -- the very collision `_spoken_for` exists to prevent, arrived at
        # from the other direction.
        free = [ft for ft in getattr(self._pro(ref), "stack_ft", ()) or ()
                if ft not in self._spoken_for(ref)]
        for i, level in enumerate(levels):
            if i >= len(free):
                break                   # nowhere lower to go; leave him be
            want = free[i]
            if level == want:
                continue
            movers = [a for a in self._holders(ref) if a.assigned_ft == level]
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
        # EVERY LETDOWN, not "the" letdown. Two aerodromes have two, and a
        # missed-approach clock that only ever watched one would let an
        # aeroplane fly past the missed approach point at the other field with
        # nobody calling it.
        for cs in list(self._letdown_by.values()):
            ac = self.aircraft.get(cs)
            if ac and ac.map_t is not None and self.t >= ac.map_t:
                self._station_passage(ac)

        for key, cs in list(self._letdown_by.items()):
            if self.t - self._letdown_since_by.get(key, 0.0) <= CLEARANCE_TIMEOUT_SEC:
                continue
            ac = self.aircraft.get(cs)
            addr = self._addr(ac) if ac else callsign.parse(cs).spoken
            self.say(cs, f"{addr}, {self._pro(ac).controller}, no report, "
                         f"say intentions.")
            # ...AND HIS LEVEL WITH HIM. `_spoken_for` now reserves the
            # altitude of the aircraft in the letdown, so declaring the letdown
            # clear while leaving him holding a stack level would take that
            # level out of circulation for the rest of the sortie -- a slow leak
            # of exactly the resource this timeout exists to release.
            if ac is not None:
                ac.assigned_ft = None
            # assume clear; do not deadlock -- and only THIS field's letdown.
            self._letdown_by.pop(key, None)
            self._letdown_since_by.pop(key, None)
            self._try_clear(ref=ac)

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
