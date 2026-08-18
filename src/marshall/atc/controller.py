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

from typing import ClassVar

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from marshall.atc import callsign
from marshall.core import route as R
# WHICH APPROACH HIS WORDS MEAN, and what this map publishes. Imported by
# name so the engine keeps ONE spelling of each question -- `match_spoken`
# refuses an ambiguous request by naming the candidates (#165) rather than
# resolving it by list order.
from marshall.core.approach import match_spoken as _match_spoken
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
    # HAS HE AGREED HIS IFR CLEARANCE? Three states, and they are the point:
    #
    #   None    nobody has issued him one, or nobody knows -- never blocks
    #   False   ISSUED and not yet read back correctly
    #   True    ACKNOWLEDGED
    #
    # #105 made FILED, ISSUED and ACKNOWLEDGED real so that a later rung could
    # ask. Nothing asked, so on 12 August a read-back loop that could not
    # terminate (#134) left this at False for a whole sortie and it cost
    # nothing: Ground gave him taxi, Tower cleared him off, and he flew to
    # Batumi on a clearance the board recorded as never agreed.
    #
    #     "And when I ask ground to taxi with no clearance -- why does he let
    #      me go. Talk about swallowing an error."
    #
    # See #135.
    clearance_agreed: bool | None = None
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


def _too_old(row, stale_after_sec: float) -> bool:
    """Is this flight row too old to be somebody currently flying?

    NO TIMESTAMP MEANS RESTORE IT. Every caller that hand-builds rows -- the
    tests, the rehearsals, `plan_sweep` -- omits `updated_at`, and a guard that
    treated absence as staleness would empty the board for all of them. Absence
    is "we do not know", and the safe answer to that is the behaviour we had.
    """
    got = row.get("updated_at")
    if not got:
        return False
    import datetime as _dt
    if isinstance(got, str):
        try:
            got = _dt.datetime.fromisoformat(got.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(got, _dt.datetime):
        return False
    now = _dt.datetime.now(_dt.UTC)
    if got.tzinfo is None:
        got = got.replace(tzinfo=_dt.UTC)
    return (now - got).total_seconds() > stale_after_sec


def _published_now() -> dict:
    """This map's approaches, keyed. Asked per call rather than held.

    `theatre.approaches_now` is cached per map name, so this is a dict lookup
    after the first call -- and holding the result would put a set of
    procedures on the Controller, which is a smaller version of exactly what
    #162 deleted.
    """
    from marshall.core import theatre as _t
    return _t.approaches_now()


def procedure_of(ac, fallback=None):
    """THE PROCEDURE THIS AEROPLANE IS FLYING. The one accessor. [#150]

    Free of the Controller so the bridge's own functions can ask it -- they
    hold an aircraft or a callsign and a loaded profile, and the whole of #150
    is that they were answering with the second when they had the first.

    WHAT MAY COME THROUGH HERE, and it is a shorter list than it looks: the
    guidance kind, whether the approach is vectored at all, the geometry and
    its datum, the levels, the minima, the missed approach, and the handoff
    conditions that read any of those. All of them differ between a Mustang on
    a 1944 beacon letdown and a Viper on the ILS beside him.

    WHAT MUST NOT is who works a seat. `station_for` takes a `procedure`, which
    looks like a counterexample and is not: it is asked one boolean about
    ITSELF -- `theatre_stations`, whether this procedure staffs the ladder at
    all -- and never yields a Station. The seats come from the theatre's table
    for everybody. So passing an aeroplane's procedure there is right for the
    same reason as everything above, and passing his STATIONS would be wrong;
    see `theatre.seats_now`, which says so at the only place it could matter.

    The fallback is what every caller used before -- the bridge's loaded
    profile -- so adopting this can only narrow a wrong answer, never widen it.
    """
    return getattr(ac, "profile", None) or fallback


@dataclass
class Controller:
    # THE ARRIVAL THE RADIO WAS STARTED WITH, and it is OPTIONAL because there
    # is no such thing as the theatre's approach.
    #
    #     "I don't understand what this whole business about a theater default
    #      approach is. There should be no such thing"
    #
    # A pilot flies the approach his CLEARANCE names. That is settled
    # everywhere else already -- migration 031 took `approach` out of
    # `flight_plans` because which arrival you fly is a fact about your
    # clearance and not about your route, `flights.cleared_approach` is the
    # column that holds it, and `hydrate` brings it back across a restart. A
    # field OFFERS a set of approaches and Approach issues one of them to one
    # aeroplane. Nothing in that story needs a singular "the approach", and a
    # controller who has issued none should not be holding one.
    #
    # It stays as a fallback for exactly one caller -- `_pro`, for an aeroplane
    # nobody has cleared for anything -- and #162 step 1 removes the thing that
    # fills it. Until then the important half is that it may be EMPTY: a
    # Controller built with no arrival at all still works for everything that
    # is not an approach, which is the whole ground ladder, the whole enroute
    # half, and every seat below Approach. That property is the acceptance
    # criterion #2 did not have, and it is what makes "the old path is gone"
    # checkable rather than assertable -- nothing radio-wide can be being
    # consulted if there is nothing radio-wide to consult.
    profile: R.ApproachProfile | None = None
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
    # ROWS `hydrate` DECLINED TO RESTORE, and it says so rather than quietly
    # starting a man from nothing. Skipped is reported, never silent: a board
    # that silently drops an aeroplane reads exactly like a board with no
    # aeroplane on it, which is the failure this whole cache exists to prevent.
    skipped_stale: list = field(default_factory=list)
    # HOW OLD A FLIGHT ROW MAY BE and still describe somebody who is flying.
    # Fifteen minutes: a bridge restart is seconds, a pause for coffee is not a
    # new sortie, and an hour-old row is the last thing a finished flight said.
    # See #136.
    stale_after_sec: float = 900.0
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

    def _vectored(self, ac) -> bool:
        """Does this controller steer HIM, or does he fly the procedure himself?

        ASKED OF THE CAPABILITY, and it used to be asked of the procedure's
        NAME. The obvious key -- `atc.radar` -- is wrong, and #53 exists because
        it looks right: the 1944 beacon letdown carries `radar=True` deliberately
        so the controller can read ranges off his scope, while the pilot has no
        DME and flies the published pattern himself. Seeing an aeroplane and
        steering it are different capabilities, and one flag was answering both.
        `AtcCapability.vectors` separates them; `None` means ask the procedure,
        which is what this did all along.

        ASKED OF ONE AEROPLANE, and it was a property over the radio's own
        profile -- so it answered for the bridge and every caller inherited
        that. Steering is not a property of a controller. Two aircraft on one
        frequency, one on an ILS and one on the 1944 letdown, get opposite
        answers from the same man in the same minute, and the whole of the
        phraseology below hangs off this one boolean: what he calls the
        procedure, how he phrases a hold, what he asks the pilot to report,
        and whether he tells him not to acknowledge.

        `ac` IS REQUIRED AND HAS NO DEFAULT. That is the point of the change
        rather than a detail of it -- #2 landed `Aircraft.profile` beside the
        singleton and 26 of 28 sites went on reading the singleton, because
        nothing made them stop. An argument with no default is the grep that
        acceptance criterion was missing: the interpreter enforces it. `None`
        is the honest way to say "no aeroplane in view", and it falls back to
        the radio's profile exactly as this always did.
        """
        from marshall.core.approach import may_vector
        return may_vector(self._pro(ac))

    # WHAT A CONTROLLER CALLS THE PROCEDURE, out loud. It knew exactly two --
    # "radar approach" or "beacon approach" -- so an ILS was cleared as a radar
    # approach, which a pilot holding an ILS plate reasonably queried:
    #
    #     "I should be on the ILS13. Why would he say radar approach?"
    #
    # Keyed on the PROCEDURE now rather than on whether he may be vectored,
    # because those are different questions: an ILS and a surveillance approach
    # are both vectored and are not the same thing to fly.
    _APPROACH_WORD: ClassVar[dict[str, str]] = {
        "ils": "I-L-S approach", "asr": "radar approach",
        "par": "precision approach", "ndb": "beacon approach",
        "vor": "V-O-R approach", "tacan": "TACAN approach"}

    def _approach_name(self, ac) -> str:
        """What THIS aeroplane is being cleared for, out loud.

        His procedure, not the radio's. The one sentence this appears in is the
        approach clearance, which is issued to one aeroplane about one arrival
        -- so reading the bridge's profile here is how a man on the ILS gets
        cleared for a radar approach while the aeroplane beside him, on the
        radar approach, is told the same thing and is right.

        NO PROCEDURE MEANS THE BARE WORD. The fallback below picks between a
        radar approach and a beacon approach for a procedure whose `kind` this
        table does not know, and there is a difference between a procedure that
        did not say and NO PROCEDURE AT ALL: the second was falling through to
        "beacon approach", which clears an F-16 for a 1944 letdown that does
        not exist at a field nobody named. Naming a procedure is not this
        method's to invent, and "cleared approach" commits to nothing.
        """
        pro = self._pro(ac)
        if pro is None:
            return "approach"
        kind = (getattr(pro, "kind", "") or "").lower()
        return self._APPROACH_WORD.get(
            kind, "radar approach" if self._vectored(ac) else "beacon approach")

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
            # A SORTIE THAT ENDED IS NOT A SORTIE IN PROGRESS. This restores
            # the RECENT past, which is the whole point of it -- a bridge
            # restarted mid-sortie takes seconds and a pilot should not be able
            # to tell. A row nobody has touched for an hour is not somebody
            # currently flying; it is the last thing a finished flight said.
            #
            # Restored anyway, it dressed a new aeroplane in a dead one's
            # clothes. On 12 August the pilot flew Kobuleti to Batumi on the
            # ILS, and the moment the engine engaged he acquired the 03:00
            # sortie's state -- three fields at once, off one row:
            #
            #     intent       ''      -> 'asr approach'
            #     phase        ENROUTE -> CLEARED
            #     assigned_ft  None    -> 4000
            #
            #     "why on earth is intent still ASR -- where is that coming
            #      from. Something about that stinks"
            #
            # It was not the classifier: asked that transmission it answers
            # 'ILS 13'. `flights` is keyed on (mission, callsign) and a mission
            # instance outlives every sortie flown inside it, so the row was
            # simply still there. See #136 and docs/STATE.md -- this is the
            # third question, WHEN DOES IT DIE, answered "when the mission
            # restarts" where it should say "when the sortie ends".
            #
            # A CEILING, NOT A FIX. The row still ought to be retired when the
            # sortie finishes; until it is, this stops the inheritance.
            if _too_old(row, self.stale_after_sec):
                self.skipped_stale.append(cs)
                continue
            ac = self._enter(cs, int(row.get("claimed_size") or 1))
            ac.sortie_phase = row.get("sortie_phase") or ""
            ac.on_visual = bool(row.get("on_visual"))
            ac.approaches = int(row.get("approaches_flown") or 0)
            ac.atis_letter = row.get("atis_letter") or ""
            ac.wants = row.get("intent") or ""
            # WHETHER HE HAS AGREED HIS CLEARANCE, off the durable record. A
            # row with a cruise level or a squawk has had one ISSUED; the
            # timestamp says whether he ever read it back. Absent both, nobody
            # has cleared him and the answer stays None, which never blocks.
            if row.get("clearance_ack"):
                ac.clearance_agreed = True
            elif row.get("cruise_ft") or row.get("squawk"):
                ac.clearance_agreed = False
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
        return procedure_of(ac, self.profile)

    def procedure_for(self, callsign: str):
        """`_pro`, reached by NAME, for the callers who only have one.

        The bridge's outer loop and its monitor thread hold a callsign and a
        controller, not an `Aircraft` -- and each of them was reaching for
        `ctl.profile` because resolving the callsign first was two lines nobody
        wrote. That is #150's whole list: five call sites, each one line from
        being right.

        An unknown callsign is the ordinary blind case, not an error. It
        returns the fallback, which is exactly what those sites did before, so
        adopting this accessor cannot make anything worse than it already was.
        """
        ac = self.aircraft.get(self._resolve(callsign)) if callsign else None
        return self._pro(ac)

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

    def note_clearance_agreed(self, callsign: str, agreed: bool) -> None:
        """Whether the clearance on the board has been READ BACK. Told, not decided.

        THE SAME GAP AS `note_cleared_level`, AND IT MADE #135 UNREACHABLE. This
        engine does not issue the IFR clearance -- the director's tool composes
        it -- so it cannot know one exists, and `clearance_agreed` was written
        in exactly two places: `hydrate`, which runs once when the bridge
        starts, and `clearance_read_back`, which only ever sets it TRUE. Nothing
        in a live sortie could set it False.

        So `request_taxi`'s refusal was dead code from the moment it was
        written. The unit tests set the field by hand and passed; a ghost flown
        down the ladder on 13 August asked Ground for taxi with an unagreed
        clearance and was cleared to the runway, which is the fault #135 exists
        to prevent, in the run written to prove it fixed.

        `None` is not reachable from here on purpose: the bridge calls this only
        when the board actually holds a clearance, and "nobody has cleared him"
        stays the field's own default, which never blocks.
        """
        ac = self.aircraft.get(self._resolve(callsign))
        if ac is not None:
            ac.clearance_agreed = bool(agreed)

    def may_be_sequenced(self, ac) -> bool:
        """Can this aircraft take a place in the stack?

        On a radar approach, only if radar has him. On a beacon letdown the
        controller is procedural and works position reports, so being unseen is
        the normal condition and this cannot apply.
        """
        return ac.radar_identified or not self._vectored(ac)

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

    def _hold_phrase(self, ac, alt_ft: int, kit=None) -> str:
        """Where to wait, said in a way he can actually fly.

        HIS procedure publishes the hold, not the radio's. Every one of the
        four reads below was the bridge's arrival, so an aeroplane waiting for
        Kobuleti was given Batumi's outbound heading and Batumi's leg time --
        real numbers, flyable, and describing a racetrack over the wrong
        aerodrome. Two aircraft holding for two fields is the ordinary case
        this engine exists to serve, and it is the case the numbers came out
        wrong for.

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

        pro = self._pro(ac)
        # THE NAVAID, and only a non-vectored procedure reaches here -- see
        # `_a_letdown_always_has_a_navaid` in the #163 tests, which is what
        # makes these reads safe without a guard each. `getattr` on a None
        # still answers "ndb", which is the right default at a beacon field
        # anyway.
        #
        # A CONTROLLER WITH NO PROCEDURE AT ALL cannot offer a published hold,
        # and must not invent one: `_pro` answers None on a bridge that was
        # never handed an arrival, and there is no fix to name. He falls
        # through to the racetrack, which is describable from nothing but a
        # heading and a clock -- see the default below.
        kind = getattr(getattr(pro, "navaid", None), "navaid_kind", "ndb")
        able = kit is None or equipment.can_hold_at(kit, kind)
        if (not self._vectored(ac) and able
                and getattr(pro, "navaid", None) is not None):
            return (f"hold at {pro.navaid.name} as published, "
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
        #
        # THE LEVEL IS OURS AND THE RACETRACK IS HIS PROCEDURE'S, and that is
        # what decides what a controller with no procedure may say. Separation
        # is this engine's own job and does not stop because nobody filed an
        # arrival, so he still gets a level and still gets called. The pattern
        # is published geometry -- aligned with an approach course, at a field
        # -- and there is none to read, so nothing is said about it. A heading
        # invented here is a real heading over real terrain and reads exactly
        # like a right answer, which is #109's rule and the reason the
        # dataclass defaults are NOT reached for: 180 and one minute belong to
        # a procedure that declined to say, not to the absence of one.
        if pro is None:
            return (f"hold at {spell_alt(alt_ft)}, "
                    f"expect vectors for the approach, I will call you")
        out = pro.hold_outbound_hdg
        mins = getattr(pro, "hold_leg_minutes", 1.0)
        turns = getattr(pro, "hold_turns", "right")
        leg = spell_minutes(mins)
        return (f"hold at {spell_alt(alt_ft)}, {turns} turns, "
                f"{spell_hdg(out)} outbound {leg}, then "
                f"{spell_hdg((out + 180) % 360)} inbound {leg}, "
                f"expect vectors for the approach, I will call you")

    def _report_phrase(self, ac) -> str:
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
        if self._vectored(ac):
            if getattr(pro, "guidance", "") == "talkdown":
                return "report the field in sight"
            return "report established on the final approach course"
        # NO NAVAID TO REPORT OVER, OR NOTHING ABOARD THAT CAN FIND IT.
        #
        #     "Telling a p51 to hold at the beacon or report established has
        #      always been impossible and a defect."
        #
        # This asked whether the PROCEDURE published a navaid and never whether
        # the AEROPLANE could detect one, so a Mustang was told to report over
        # a beacon it has no working receiver for -- an instruction with no
        # instrument behind it, which he can only guess at or ignore. Both look
        # from the ground like a pilot not following instructions.
        #
        # THE SAME QUESTION `_hold_phrase` ALREADY ASKS, on the other side of
        # the same exchange. It has consulted `equipment.can_hold_at` since
        # #163 and falls through to a racetrack -- a level, a turn, an outbound
        # heading, a leg time -- for exactly this aeroplane. The instruction
        # was gated and the report was not.
        #
        # The field in sight is the one trigger every pilot can detect without
        # anything published or anything fitted, which is the same argument the
        # talkdown branch makes three lines up. [#175]
        from marshall.atc import equipment
        nav = getattr(pro, "navaid", None)
        kit = getattr(ac, "kit", None)
        # `can_hold_at`, NOT `can_use`, and the difference is a real aeroplane.
        # An F-16 carries no ADF, so it cannot RECEIVE an NDB -- but it has an
        # inertial platform, so it knows where the point is and can report over
        # it perfectly well. That is the owner's own line: "in modern we can
        # instruct an aircraft to hold at a navaid or a fix on his flight
        # plan". `can_hold_at` already says exactly that -- "an inertial
        # platform is enough on its own: he can hold at a point in space
        # because he knows where he is" -- and asking `can_use` here would have
        # sent a Viper looking out of the window for the field.
        able = kit is None or equipment.can_hold_at(
            kit, getattr(nav, "navaid_kind", None))
        if nav is None or not able:
            return "report the field in sight"
        return f"report {nav.name} inbound"

    def _no_acknowledgement_phrase(self, ac) -> str:
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
        if (self._vectored(ac)
                and getattr(self._pro(ac), "guidance", "") == "talkdown"):
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
        # WHOSE ATIS. The speaking seat's, and ONLY his.
        #
        # It read `me.field or _R.ARRIVAL_FIELD`, and that fallback is the
        # defect rather than the lookup. `ARRIVAL_FIELD` is the literal
        # "Batumi", so on Nevada it named an aerodrome on the OTHER MAP,
        # `field_named` answered None, and this returned the empty string --
        # whereupon `request_clearance` returns early on a missing letter and
        # THE FIRST CONTROLLER OF THE SORTIE SAYS NOTHING AT ALL to a pilot
        # asking for his IFR clearance. Not a wrong number: silence, which from
        # the cockpit reads as a broken radio and is the harder thing to
        # diagnose. [#162, #137]
        #
        # An unnamed seat is not an aerodrome to guess at -- #109 settled that
        # a value with no owner renders nothing rather than a guess. But
        # "nothing" here is the LETTER, not the transmission: "Say your
        # request" contains no weather, no runway and no field, so it needs no
        # aerodrome to be true and the man on the radio still gets an answer.
        # That is the same wording the no-broadcast branch below uses, because
        # to the pilot the two mean the same thing -- I have no letter for you,
        # go ahead.
        me = getattr(self, "_me", None)
        mine = getattr(me, "field", "")
        fld = _R.field_named(mine) if mine else None
        if fld is None:
            # ...AND WHERE THEY DIFFER IS NOT SILENT EITHER. A seat that names
            # a field this map does not publish is a broken theatre file, not
            # a quiet sortie, and it must not look identical to a controller
            # nobody has told who he is.
            if mine:
                self._anomaly(f"{getattr(me, 'name', '?')} works {mine!r}, "
                              f"which this theatre does not publish")
            return "Say your request."
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

        THE CHANNEL IS HIS, and it was the radio's. On a beacon letdown a
        phase's controller lives on the beacon flown in that phase -- the ARA-8
        homes whatever the set is tuned to -- so which frequency an aeroplane
        can be reached on is decided by the procedure HE is flying. Reading the
        bridge's arrival here transmits to the second aeroplane on the first
        one's channel, and a transmission on the wrong frequency is not a
        mis-phrasing, it is silence.
        """
        ac = ref if ref is not None else self.aircraft.get(to)
        enroute = ac is None or ac.phase in (Phase.UNKNOWN, Phase.ENROUTE)
        banished = ac is not None and ac.phase is Phase.BANISHED
        name, freq = self._channel(ac, enroute=enroute, banished=banished)
        self.out.append(Tx(to, text, self.t, freq, name, decision=decided))

    def _channel(self, ac, enroute: bool = False,
                 banished: bool = False) -> tuple[str, float]:
        """(controller, frequency) for the phase this aeroplane is in.

        WITH NO PROCEDURE AT ALL the answer is the map's ladder, and that is
        not a fallback dressed up -- it is the same question asked of the only
        authority that can answer it. A comms ladder belongs to the THEATRE:
        who works Tower at Batumi does not change because somebody was cleared
        for an ILS, and you do not need an arrival to be told. `ladder_station`
        is the branch `ApproachProfile.station` takes for every procedure that
        does not put its controllers on the beacons, reached directly.

        Only the #152 arrangement genuinely needs a procedure here, and it
        needs it for a real reason rather than a historical one: there the
        station IS the fix being homed, so with no procedure there is no fix,
        no sector and no frequency. A map with no seats at all and no arrival
        gets ('', 0.0) -- nothing invented, and `Tx` has always carried a
        frequency of zero for "not decided".

        AND A LADDER NEEDS AN AERODROME. With a procedure the field is the one
        it arrives at; without one the only aerodrome anybody here knows about
        is the SPEAKING SEAT's, which is the honest answer for the ground half
        of a sortie -- a pilot talking to Kobuleti Tower is on Kobuleti Tower's
        frequency and on nobody else's. It used to resolve at
        `fields.ARRIVAL_FIELD` instead, so Kobuleti Tower's roll-out goodbye
        was stamped Batumi Tower 118.600. A fieldless seat (Center, Sentry) with
        no arrival either names no aerodrome at all, and gets the same ('', 0.0)
        as a map with no seats.
        """
        pro = self._pro(ac)
        if pro is not None:
            return pro.station(enroute=enroute, banished=banished)
        from marshall.core.approach import ladder_station
        mine = getattr(getattr(self, "_me", None), "field", "")
        return ladder_station(mine, enroute=enroute,
                              banished=banished) or ("", 0.0)

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

    def _introduce(self, ac) -> str:
        """"Batumi Approach, " -- or nothing at all, punctuation included.

        The controller working THIS aeroplane names himself, which is the same
        rule `report_down` was corrected to (#77): nobody speaks under another
        controller's name. Three transmissions do it -- the hold with the
        sequence number, the letdown timeout and the overdue prompt -- and all
        three read the radio's arrival until #162.

        AND AN ANONYMOUS CONTROLLER SAYS NOTHING RATHER THAN A BARE COMMA. A
        `Controller` with no procedure has no name to give; "Pony one one, ,
        report position" is what a format string does with an empty slot, and
        it reaches Polly as a stumble. The trailing separator belongs to the
        name, so the sentence closes up when there is none. [#109]
        """
        name = getattr(self._pro(ac), "controller", "")
        return f"{name}, " if name else ""

    def _key(self, ac=None) -> str:
        """Which letdown/stack this aeroplane belongs to. The AERODROME's name.

        It said "the beacon's name" and read `beacon`, which held the field
        until #163 -- so this was already keying on the aerodrome and calling
        it something else. A stack belongs to a FIELD: two aircraft recovering
        to one runway contend for the same levels whatever they are flying,
        and a beacon would have keyed the ILS arrivals to nothing at all.

        Empty for a controller with no profile at all, which is the unit-test
        and dry-run case -- one unnamed letdown, exactly as before.
        """
        return getattr(getattr(self._pro(ac), "aerodrome", None), "name", "") or ""

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
        mine = getattr(getattr(self._pro(ref), "aerodrome", None), "name", "")
        his = getattr(getattr(self._pro(a), "aerodrome", None), "name", "")
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
        #
        # AND THE FALLBACK IS HIS CHANNEL, not the radio's. With nobody named,
        # the best guess at who is speaking is the man on the frequency this
        # aeroplane is listening to, and on a beacon letdown that is decided by
        # the procedure HE is flying. Same for the Tower he is handed to at the
        # arrival fix, which is a fact about his arrival and about no other.
        me = getattr(self, "_me", None)
        pro = self._pro(ac)
        if me is not None and getattr(me, "name", ""):
            here, here_freq = me.name, me.freq_mhz
        else:
            here, here_freq = self._channel(ac, enroute=True)
        # AND AN ANONYMOUS CONTROLLER SAYS NOTHING RATHER THAN A BARE COMMA,
        # which is `_introduce`'s rule (#109) reaching the one greeting that
        # did not share it. A Controller with no arrival AND no seat has no
        # aerodrome to look a ladder up at and therefore no name to give; the
        # separator belongs to the name, so the sentence closes up when there
        # is none rather than reaching Polly as "Pony one one, , report".
        whoami = f", {here}" if here else ""
        tower, tower_freq = self._channel(ac)
        fix = getattr(pro, "arrival_fix", None)
        # A CAPABILITY IS DECLARED, NEVER INFERRED FROM THE SHAPE OF THE DATA,
        # and this branch broke that rule twice in one condition. [#53, #145]
        #
        # It read, in full, `if fix is not None and tower_freq != here_freq` --
        # and from that it concluded two things it had not been told:
        #
        #   "radar not available"     from the procedure CARRYING an arrival
        #                             fix, never from `atc.radar`
        #   he is ARRIVING            from nothing at all; it sits above the
        #                             phase-aware branches and is reached first
        #
        # Both are wrong today and one of them is wrong on the air. The 1944
        # letdown is the only profile that carries an `arrival_fix`, and it sets
        # `radar=True` ON PURPOSE -- see `SeeingHimAndSteeringHimAreTwoCapabilities`
        # one file over: "he can see him", because the controller reads ranges
        # off his own scope while the pilot flies the pattern on the beacon. So
        # the engine has been telling a pilot the radar is out while the same
        # profile tells the rest of the system it is up. `agent_atc` then string-
        # replaced the phrase back out on the way to the radio, which is a
        # correction applied by the one component that cannot know whose
        # aeroplane it is.
        #
        # It survived because that profile carries no station list (#140), so it
        # has no Clearance and no Departure seat to expose the second half. Give
        # ANY laddered procedure an arrival fix -- which is what taking INITIAL
        # out of the published catalogue does -- and a man on the ramp is told
        # to report a fix forty miles away, and a jet on climb-out is given an
        # arrival briefing. Four tests fell over at once and none of them named
        # this line.
        #
        # SO IT IS NESTED NOW, inside the guard it should always have shared.
        # These are not two greetings, they are ONE -- the arrival greeting --
        # spelled two ways, because a procedure whose enroute phase homes a fix
        # asks him to report THAT rather than the field in sight. What decides
        # whether he is greeted as an arrival at all is the same in both: is he
        # on his way in, and is this a seat that works arrivals.
        if self._arriving(ac) and (self._owns("approach")
                                   or self._owns("center")):
            if fix is not None and tower_freq and tower_freq != here_freq:
                # Report the fix he is CURRENTLY homing, and change channel when
                # he gets there. Telling him to contact Tower now would take him
                # off the arrival fix's frequency while he is still navigating to
                # it -- the set homes whatever it is tuned to, so switching early
                # does not just change who he is talking to, it removes the
                # needle he is steering on. The handoff is a trigger he owns and
                # flies to.
                #
                # The capability is the AIRCRAFT's, not the bridge's: two
                # profiles are worked at once and only one of them is his.
                blind = ("" if getattr(pro.atc, "radar", True)
                         else "radar not available, ")
                # "YOU WILL BE HOMING X" IS ONLY TRUE IF THERE IS AN X, and
                # until #163 this said it unconditionally. `pro.beacon` never
                # returned None -- it fell back to the aerodrome -- so a
                # procedure with an arrival fix and no beacon promised a pilot
                # he would be homing an AIRFIELD, which is not a thing you can
                # home. The merged answer did not prevent the bug, it printed
                # a plausible one.
                #
                # Only the letdown has an arrival fix on this map today, so
                # nothing said it wrongly in the air. The sentence is now
                # conditional on the fact it asserts, which is what it should
                # always have been.
                homing = (f" -- you will be homing {pro.navaid.name} from there"
                          if getattr(pro, "navaid", None) is not None else "")
                call = (f"{self._addr(ac)}{whoami}, {blind}"
                        f"report {fix.name}. At {fix.name} contact {tower} "
                        f"{spell_freq(tower_freq)}{homing}.")
            else:
                call = (f"{self._addr(ac)}{whoami}, "
                        f"{self._report_phrase(ac)}.")
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
            call = f"{self._addr(ac)}{whoami}, radar contact."
        else:
            # A GROUND SEAT DOES NOT ASK FOR A POSITION REPORT. "Report BATUMI
            # inbound" from Clearance, to a man who has not started his engine,
            # is a radar controller's line coming out of the wrong mouth -- and
            # it only became reachable when the ladder grew seats below
            # Approach. What Clearance and Ground want is the request, which
            # `_atis_phrase` asks for.
            call = f"{self._addr(ac)}{whoami}."
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
                     f"{self._addr(ac)}, {self._hold_phrase(ac, slot, ac.kit)}.",
                     decided=D.Decision(kind="hold", to=ac.callsign,
                                        altitude_ft=slot))
            self._try_clear()
        elif ac.phase == Phase.CLEARED:
            # Established inbound on the beam: start the station-passage clock.
            # The pilot flies the MAP on a watch; ATC times the same number and
            # calls it as backup (aural station passage does not read in the sim).
            ac.map_t = self.t + getattr(self._pro(ac), "final_approach_sec", 0.0)
            self.say(ac.callsign,
                     f"{self._addr(ac)}, roger, station passage "
                     f"{spell_dur(getattr(self._pro(ac), "final_approach_sec", 0.0))}, "
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
        # NO PROCEDURE, NO PUBLISHED LEVEL. `assigned_ft` of None is the
        # engine's own "nobody has put him anywhere", which is the truth here
        # -- an aeroplane going round off an approach he was never cleared for
        # has no missed-approach altitude, and inventing one puts a number on
        # the board that no chart supports. See `_missed_instruction`.
        pro = self._pro(ac)
        if ac.approaches >= MAX_APPROACHES:
            ac.phase, ac.assigned_ft = Phase.BANISHED, getattr(pro, "top_ft", None)
            return True
        ac.phase, ac.assigned_ft = Phase.MISSED, getattr(pro, "missed_ft", None)
        return False

    def _missed_instruction(self, ac, banished: bool) -> str:
        """THE NUMBER HE IS TOLD IS THE NUMBER HE WAS ASSIGNED, and it was not.

        `_do_missed` right above sets `assigned_ft` off `_pro(ac)` -- HIS
        procedure -- and this composed the sentence off `self.profile`, the
        radio's. Two profiles, one go-around: the board recorded one level and
        the controller read him another, in the same breath, and neither is
        wrong on its face. A missed approach is the one moment in an arrival
        when a pilot is busiest and least able to query a figure.

        Nothing on the Caucasus showed it, because one bridge loaded one
        arrival and both answers came from the same object. It needed a second
        aeroplane recovering somewhere else, which is what #2 was FOR.

        The outer hold goes the same way. `outer_hold` is where a twice-missed
        aeroplane is sent to re-sequence, and a re-sequence is at HIS field --
        being banished to the other aerodrome's escape fix, on the other
        aerodrome's frequency, is the two-field fault this project keeps
        meeting: a real fix, a real frequency, the wrong airport.
        """
        pro = self._pro(ac)
        # A GO-AROUND OFF AN APPROACH NOBODY CLEARED. Every figure below is
        # published geometry -- the missed altitude, the outer hold, its
        # frequency -- and there is none, so none is said. What survives is the
        # part that is the CONTROLLER's rather than the chart's: get him
        # climbing, and find out what he wants. #109's rule, at the moment a
        # pilot is busiest.
        if pro is None:
            return ("climb, and say your intentions."
                    if banished else
                    "climb, and say your intentions. "
                    "You are number one for the approach.")
        if banished:
            return (f"climb {spell_alt(pro.top_ft)}, proceed "
                    f"{pro.outer_hold.name}, contact "
                    f"{pro.outer_hold.sector or 'the outer hold'} "
                    f"{spell_freq(pro.outer_hold.freq_mhz or 0)}, hold, "
                    f"expect re-sequence. Traffic holding.")
        return (f"climb {spell_alt(pro.missed_ft)}, "
                f"return to the beacon. You are number one for the approach.")

    def report_missed(self, cs: str) -> None:
        ac = self.get(cs)
        banished = self._do_missed(ac)
        addr = self._addr(ac)
        prefix = f"{addr}, " if banished else f"{addr} roger, "
        self.say(ac.callsign, prefix + self._missed_instruction(ac, banished))
        self._try_clear()

    def _station_passage(self, ac: Aircraft) -> None:
        """Beam time up with no landing: ATC hears it overhead and calls the
        missed. The pilot's own watch should already be prompting this -- the
        cone of silence is unreliable in the sim, so ATC backs the timing up."""
        banished = self._do_missed(ac)
        inst = self._missed_instruction(ac, banished)
        self.say(ac.callsign, f"{self._addr(ac)}, heard a Mustang overhead, field is "
                              f"beneath you, go missed. " + inst[0].upper() + inst[1:])
        self._try_clear()

    def report_landed(self, cs: str) -> None:
        ac = self.get(cs)
        # HE IS ALREADY DOWN, so this is not a landing clearance, it is a
        # greeting. `report_down` says so in its own docstring -- "reading a
        # landing clearance to a man already stopped on the runway is a
        # controller who has not noticed the aeroplane arrive" -- and then
        # nothing enforced it, because `report_down` is reachable only from the
        # radar poll and a PILOT has no way to say it. The taxonomy sends both
        # "field in sight, landing" and "on the ground, runway one three" here
        # (`intents.py`: report_landed covers "...landing, down").
        #
        # CAUGHT LIVE, and by both rehearsal runs. Radar fired `report_down` at
        # 03:02:23 and said the right thing; the pilot reported down 8 s later
        # and this method regressed the controller a whole leg, answering a
        # stopped aeroplane with "roger, cleared to land runway one three".
        # The agent papered over it with "go ahead", which is how it stayed
        # invisible in the transcript -- the wrong sentence never reached the
        # air, so only the recorder knew the engine had lost the plot.
        #
        # The engine knows which rung he is on. That is the same argument #100
        # used one case down for the taxi request, and it applies here.
        if ac.phase is Phase.LANDED:
            self.report_down(cs)
            return
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
        twr = R.station_for(
            "tower", field=getattr(getattr(self, "_me", None), "field", ""),
            procedure=self._pro(ac))
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
                 f"{self._runway_in_use(ac)}, {self._wind_phrase()}")
        self._try_clear()

    def _ground_at(self, ac, fld: str):
        """The Ground seat at this aerodrome, or None if there is not one.

        Two ways the answer is nobody, and each is a controller declining to say
        something that is not true:

            no field        a role is unique only within an aerodrome, so an
                            unqualified lookup of the ground role answers with a
                            real controller at the wrong airport -- and a real
                            frequency, which is the kind of wrong number a pilot
                            dials before anybody notices
            no ground seat  a field where Tower works the taxiways has nobody to
                            hand to, and the old sentence is still right

        A third: `procedure` is the #152 switch and it is HIS -- see `_pro`.
        """
        if not fld:
            return None
        return R.station_for("ground", field=fld, procedure=self._pro(ac))

    def _must_be_told(self, ac, me, gnd) -> bool:
        """Is naming this station a FREQUENCY CHANGE, or is he already there?

        The rung moves either way -- he is Ground's the moment the roll is over,
        and that is what the ladder has to record -- but the transmission is
        only owed when the man changes. Telling a pilot to contact the person he
        is talking to is nonsense on the radio, and `handoff.due` returns exactly
        this case as `same_station` and says nothing.

        Two shapes of "already there": the seat covers the ground role itself
        (Batumi Ground also works clearance, and a small field may fold Tower and
        Ground into one person), or he was given the frequency on an earlier
        look -- a radar poll every four seconds, and `report_landed` routing a
        man who says "I'm down" back into here, both reach this twice.
        """
        if gnd is None:
            return False
        if (getattr(ac, "sortie_phase", "") or "").lower() == "taxi_in":
            return False
        if "ground" in (getattr(me, "role", ""), *getattr(me, "also", ())):
            return False
        return getattr(gnd, "name", None) != getattr(me, "name", None)

    def report_down(self, cs: str, me=None) -> None:
        """Radar shows him down. Get him off the runway, and give him Ground.

        Distinct from `report_landed`, which answers a pilot who has the field
        in sight and is still flying -- what he is owed there is the clearance
        and the wind. Reading a landing clearance to a man already stopped on
        the runway is a controller who has not noticed the aeroplane arrive.

        What a tower actually says once the roll is over is where to go: off the
        runway, and who to call. It is also the transmission that tells him he
        has been SEEN to land, which is the only difference between "he has me
        down" and "he has crashed" -- and it is the last thing Tower says on
        every flight.

        THE FREQUENCY CHANGE GOES OUT ON THE ROLL-OUT, and that is what closes
        #77.

            "We can just have tower say something like -- 'sockeye, batumi
             tower, welcome, exit runway and contact ground' once it's on the
             ground"

        Which is what a real tower does. The alternative was to WATCH him vacate
        and hand him over afterwards, and there is no honest observable for it:
        an aerodrome row carries a position, an elevation and a landing heading,
        and no runway polygon -- so "he is clear of the strip" comes down to a
        threshold over a cross-track measured from a point that is only
        approximately on the centreline. Tuned to fire late that is a handoff
        that never comes; tuned to fire early it is Tower losing an aeroplane on
        the active, which is the invariant this engine exists to hold. Saying it
        during the roll-out deletes the question rather than tuning it.

        `taxi_in` IS THE RUNG, not `landed`, and that is the whole handoff. A
        phase with no geometry is owned outright by the controller `phases.py`
        names, so moving into Ground's phase IS the transition -- `handoff.due`
        then reads an aeroplane who is already Ground's, and there is nothing
        after Ground to hand him to (#100). `landed` remains what it says: down,
        still on the strip, still Tower's -- and it is where this leaves him at
        a field with no ground seat to pass him to.

        ONE PLACE DECIDES THE WORDS AND THE RUNG TOGETHER. The frequency he is
        TOLD and the frequency the ladder RECORDS come from one `station_for`
        here, because a handoff spoken by one authority and booked by another is
        two answers to one question -- the class of fault #115 is about.

        `me` IS WHO IS SPEAKING, and it is an argument because the proactive
        monitor is not the receive path. `self._me` is set from the frequency of
        the last transmission the bridge HEARD, which for a landing nobody has
        spoken on is another aeroplane's controller -- possibly at the other
        aerodrome. The monitor knows whose he is (`his_station`) and hands it in;
        everything else keeps reading `_me` and behaves exactly as before.
        """
        ac = self.get(cs)
        ac.phase, ac.last_report_t = Phase.LANDED, self.t
        ac.map_t = None
        if self._in_letdown(ac) == ac.callsign:
            self._set_letdown(ac, None)
        me = me if me is not None else getattr(self, "_me", None)
        # HIS field. This welcomed a pilot who had just landed at Batumi as
        # "Kobuleti Tower" -- the last thing said on the whole sortie.
        fld = getattr(me, "field", "")
        # AND A CONTROLLER INTRODUCES HIMSELF, which this did not: it named the
        # field's TOWER whoever was speaking. Right for the ILS, where Tower is
        # who you land with, and wrong for the two seats that also reach here --
        # a talkdown keeps the radar controller to the ground (#7), so Approach
        # was introducing himself as Tower on Approach's own frequency; and a
        # man who reports himself down after switching had GROUND say "Kobuleti
        # Tower, welcome". Nobody speaks under another controller's name.
        #
        # `_me` unset is still the tower lookup, because an engine that has not
        # been told which seat it is has no better answer, and that is the case
        # every dry run and most of the unit suite is in.
        speaker = (me if me is not None
                   else R.station_for("tower", field=fld,
                                      procedure=self._pro(ac)))
        who = f"{speaker.name}, " if speaker else ""
        gnd = self._ground_at(ac, fld)
        # ASKED BEFORE THE RUNG MOVES, because one of the answers is "he is
        # already on it" -- this transmission is reachable twice.
        tell = self._must_be_told(ac, me, gnd)
        # THE RUNG MOVES BECAUSE THE ROLL IS OVER, not because anybody spoke.
        # If the field has a ground seat at all then he is Ground's from here,
        # and that is what the ladder has to record whether or not a frequency
        # change is owed with it -- otherwise a seat that covers both roles
        # leaves him on Tower's rung and hands him BACKWARDS to Tower the next
        # time anything asks, which is the fault #100 is named after.
        if gnd is not None:
            ac.sortie_phase = "taxi_in"
        elif (ac.sortie_phase or "").lower() != "taxi_in":
            ac.sortie_phase = "landed"
        # "TAXI TO PARKING" IS NOT TOWER'S TO SAY, and this said it on every
        # landing. Tower owns the runway; the taxiways are Ground's. A pilot
        # reported it from the cockpit:
        #
        #     "Batumi Tower ... just gave me clearance to taxi to parking when
        #      that's ground's job"
        #
        # Exactly the fault that made Ground clear an aircraft for take-off, in
        # the other direction -- a seat answering for something it does not own.
        # What Tower owes him is the runway and the next frequency: get off it,
        # and here is the man who owns where you go afterwards.
        if not tell:
            self.say(ac.callsign,
                     f"{self._addr(ac)}, {who}welcome. Exit the runway when able.")
        else:
            self.say(ac.callsign,
                     f"{self._addr(ac)}, {who}welcome. Exit the runway and "
                     f"contact {gnd.name} {spell_freq(gnd.freq_mhz)}.",
                     decided=D.Decision(kind="handoff", to=ac.callsign,
                                        role="ground", station=gnd.name,
                                        frequency_mhz=gnd.freq_mhz))
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
        runway = getattr(self._pro(ac), "runway", "") or "in use"
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
            ac.assigned_ft = self._free_slot(ac) or getattr(self._pro(ac), "bottom_ft", None)
        place = len(self._holders(ac))
        words = ["", "one", "two", "three", "four", "five", "six"]
        self.say(ac.callsign,
                 f"{self._addr(ac)}, {self._hold_phrase(ac, ac.assigned_ft, ac.kit)}. "
                 f"Expect the visual, you are number "
                 f"{words[place] if place < len(words) else place}.",
                 decided=D.Decision(kind="hold", to=ac.callsign,
                                    altitude_ft=ac.assigned_ft))

    def _wind_phrase(self) -> str:
        """The wind, on the clearance that ends with a landing or a take-off.

        ASKED OF THE BROADCAST, exactly as `_runway_in_use` is, and it is the
        same sentence that asks both:

            f"{self._runway_in_use()}, {self._wind_phrase()}"

        The runway came from the measurement and the wind from
        `units.WIND_FROM_DEG`, a module constant, so Tower could clear an
        aircraft to land on the runway the measured wind chose while naming a
        wind that did not choose it -- the ATIS broadcast and the landing
        clearance disagreeing about one number at one field, which is this
        project's own failure shape one field over (#148). It survived because
        the declared Caucasus wind has never been far enough off to flip a
        runway, and the sim's weather is a per-mission setting.

        HIS FIELD, not the profile's, for the same reason the runway is: the
        profile describes the arrival at the other end of the route, and
        Kobuleti Tower reading Batumi's weather is a real controller quoting a
        real observation from forty miles away.

        A DIRECTION IS THREE DIGITS AND A SPEED IS NOT -- see `Wind.spoken`,
        which is where those words are made, so a broadcast and a clearance
        cannot phrase one measurement two ways.
        """
        from marshall.atis import store as _atis
        from marshall.core import route as _R
        me = getattr(self, "_me", None)
        fld = _R.field_named(getattr(me, "field", ""))
        return f"{_atis.wind(fld).spoken}."

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

        AND NO LETTER IS NOT NOTHING TO SAY. This returned early whenever
        `_atis_phrase` produced no letter, which folded three different
        situations into one silence: no broadcast at this field, and -- once
        `_atis_phrase` stopped falling back to the Caucasus literal
        `ARRIVAL_FIELD` -- a controller nobody has told which aerodrome he
        works. The pilot has asked for an IFR clearance either way, and from
        the cockpit a controller who says nothing is a broken radio, which is
        much harder to diagnose than a wrong number.

        So the WORDS go out whenever there are any, and the DECISION is
        attached only when there is a letter to check him against. That split
        is the point: a decision asserts a fact the agent must voice and
        `decision.verify` will catch it dropping, and "say your request" is
        not a fact.
        """
        ac = self.get(cs)
        ac.sortie_phase, ac.last_report_t = "clearance", self.t
        extra = self._atis_phrase(ac)
        if not extra:
            return                      # not his seat, or not his phase
        letter = _atis_letter_in(extra)
        self.say(ac.callsign, f"{self._addr(ac)}, {extra}",
                 decided=(D.Decision(kind="advise_atis", to=ac.callsign,
                                     atis_letter=letter) if letter else None))

    def clearance_read_back(self, cs: str, correct: bool | None = True,
                            missed: tuple = (), facts: dict | None = None) -> None:
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
            # AGREED, AND THE ENGINE REMEMBERS IT AGREED. FILED, ISSUED and
            # ACKNOWLEDGED became three real states in #105 so that the next
            # rung could ask which one he was in; nothing asked. See
            # `request_taxi` and #135.
            ac.clearance_agreed = True
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
            # THE NUMBERS RIDE ON THE DECISION, not only in the sentence.
            #
            # This carried `note=what` and nothing else, and `Decision.facts()`
            # excludes `note` on purpose -- prose is not a fact. So the one
            # transmission in the system whose entire job is to name numbers
            # was the one transmission with no numbers in it, and `verify` had
            # nothing to check. On 13 August the engine decided two items and
            # one reached the air:
            #
            #   decided: negative -- say again one zero thousand,
            #                        one two three decimal three
            #   spoken:  negative -- say again the altitude, one zero thousand
            #
            # The frequency he had never read back was now a thing he had not
            # been ASKED for, so no answer of his could end the exchange
            # however carefully he replied -- #134 arriving through a door that
            # fix did not close.
            #
            # `facts` comes from `decision.unspoken`, which names the FIELD
            # rather than how it sounded. With them here the ordinary
            # verify-and-repair path does the rest, exactly as it does for
            # every other decision. [#157]
            self.say(ac.callsign,
                     f"{self._addr(ac)}, negative — say again {what}.",
                     decided=D.Decision(kind="say_again", to=ac.callsign,
                                        note=what, **(facts or {})))

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
            gnd = R.station_for(
                "ground", field=getattr(getattr(self, "_me", None),
                                        "field", ""),
                procedure=self._pro(ac))
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
        # AND HE DOES NOT MOVE ON A CLEARANCE HE HAS NOT AGREED.
        #
        # `clearance_agreed` is False only when one was ISSUED and the read-back
        # has not been accepted -- None, the ordinary case for VFR and for
        # anybody nobody has cleared, passes straight through. So this refuses
        # exactly the situation that has no other exit, and says which it is:
        # "not read back" is a different problem from "not filed", and a pilot
        # can only fix the one he is told about.
        #
        # Silence here is what the pilot actually objected to. An error that
        # changes nothing is indistinguishable from no error, and he flew a
        # whole sortie -- taxi, take-off, two aerodromes -- before anything
        # noticed his clearance had never been agreed. See #135 and #134.
        if ac.clearance_agreed is False:
            # AND HE IS NOT TAXIING, so the phase must not say he is.
            #
            # The line at the top of this method moves him to `taxi` whatever
            # happens, on the reasoning that he IS ready to taxi and saying so
            # on the wrong frequency does not make it untrue. That is right for
            # the `_owns` case above and wrong here, because the PHASE IS THE
            # HANDOFF: `handoff.due` owns a phase with no geometry outright, so
            # `taxi` means Ground has him -- and a man who has just been sent
            # back to Clearance was handed on to Ground in the same breath as
            # being refused. Measured on the first end-to-end sortie:
            #
            #     ATC  your IFR clearance has not been read back, contact
            #          Kobuleti Clearance one two five decimal one
            #     ATC  readback correct, contact Kobuleti Ground one two one
            #          decimal eight            <- the refused taxi, authorised
            #
            # That is #135's own complaint back again -- "why does he let me
            # go" -- with the refusal audible and changing nothing. He is on
            # Clearance's rung until Clearance is finished with him. [#82]
            ac.sortie_phase = "clearance"
            who = R.station_for(
                "clearance", field=getattr(getattr(self, "_me", None),
                                           "field", ""),
                procedure=self._pro(ac))
            where = (f", contact {who.name} {spell_freq(who.freq_mhz)}"
                     if who is not None else "")
            self.say(ac.callsign,
                     f"{self._addr(ac)}, your IFR clearance has not been read "
                     f"back{where}.",
                     decided=D.Decision(
                         kind="refuse", to=ac.callsign, role="clearance",
                         station=getattr(who, "name", ""),
                         frequency_mhz=getattr(who, "freq_mhz", None)))
            return
        rwy = self._runway_in_use(ac)
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
        who = R.station_for(role, field=getattr(me, "field", ""),
                            procedure=self._pro(ac))
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

    def _on_the_runway(self, ac=None) -> str | None:
        """Who is physically on the strip at this aeroplane's field, if anybody.

        NO GEOMETRY, AND THAT IS WHY THIS IS BUILDABLE. `report_down`'s
        docstring records why runway occupancy was never built -- an aerodrome
        row carries a position and a landing heading and no runway length or
        thresholds, so there is no polygon to test a point against. That is
        true and it is not the question. `phases.py` already DEFINES the state:

            landed    "Down and still on the runway, which is Tower's."
            taxi_in   "Off the runway, to a stand."

        A phase is an observable that needs no survey, and the ladder already
        moves an aeroplane between those two on facts the sim reports. So the
        answer is a scan of the board, not a computation.

        SCOPED TO HIS FIELD, via `_key`, because a man on the runway at
        Kobuleti says nothing whatever about the runway at Batumi -- and a
        check that ignored the field would refuse every take-off on the map
        the moment anybody landed anywhere. [#170]
        """
        want = self._key(ac)
        for other in self.aircraft.values():
            if other is ac or self._key(other) != want:
                continue
            if (getattr(other, "sortie_phase", "") or "").lower() == "landed":
                return other.callsign
        return None

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
        # NOBODY IS CLEARED ONTO AN OCCUPIED RUNWAY. This asked exactly one
        # question -- do I own Tower -- and never whether anybody was on the
        # strip, so two aeroplanes on one runway was a thing the engine would
        # do without noticing. The invariant says an LLM never invents
        # separation between aircraft; it does not say somebody else does it
        # instead, and here nobody did. [#170]
        #
        # A REFUSAL, NOT A DELAY. He is told what is on the runway and told to
        # hold, which is what a controller says; the engine does not remember
        # the request and issue it later, because a clearance that arrives
        # without being asked for is one a pilot is not braced for.
        occupied = self._on_the_runway(ac)
        if occupied:
            self.say(ac.callsign,
                     f"{self._addr(ac)}, hold short runway "
                     f"{self._runway_in_use(ac)}, traffic on the runway.",
                     decided=D.Decision(kind="hold_short", to=ac.callsign,
                                        runway=self._runway_in_use(ac)))
            return
        ac.sortie_phase = "departure"
        rwy = self._runway_in_use(ac)
        self.say(ac.callsign,
                 f"{self._addr(ac)}, runway {rwy}, cleared for take-off, "
                 f"{self._wind_phrase()}",
                 decided=D.Decision(kind="cleared_takeoff", to=ac.callsign,
                                    runway=rwy))

    def _runway_in_use(self, ac=None) -> str:
        """Two digits, ASKED OF THE BROADCAST -- see `atis/store.py`.

        Read here rather than remembered so a ground instruction and a take-off
        clearance cannot name different runways, and asked rather than computed
        so neither of them can disagree with the recording.

        THE SPEAKING CONTROLLER'S FIELD decides this, which is why `ac` is
        optional here and required on the phraseology helpers: the runway in
        use at Kobuleti is the same runway for every aeroplane on the ramp, and
        it is not a property of anybody's arrival. The aeroplane is wanted only
        for the last resort below.
        """
        from marshall.core import route as _R
        # HIS field, not the profile's. A ground instruction at Kobuleti must
        # name Kobuleti's runway; the profile describes the approach at the
        # other end of the route and its runway is 13.
        me = getattr(self, "_me", None)
        fld = _R.field_named(getattr(me, "field", ""))
        if fld is None:
            # NO FIELD AND NO BROADCAST -- the map does not publish the
            # aerodrome this seat claims to be at. The last thing left is the
            # runway HIS approach lands on, which is a real answer for the man
            # being spoken to and was the RADIO's answer for everybody. With no
            # arrival either it is "in use", which commits to nothing and is
            # what a controller says when the runway is not his to name.
            rwy = getattr(self._pro(ac), "runway", "")
            return spell_rwy(rwy) if rwy else "in use"
        # ASKED, NOT COMPUTED. `runway_in_use()` is a pure function of the wind,
        # so calling it here would be a SECOND author for a decision that has
        # one -- and two authors agree only while they read the same wind at the
        # same instant. The broadcast is recorded at one moment and this taxi
        # clearance issued at another; between them the recording would say 07
        # and Ground 25, both correct and both defensible, with an aeroplane
        # lined up the wrong way. See `atis/store.py`.
        from marshall.atis import store as _atis
        return spell_rwy(_atis.runway_in_use(fld))

    def offer_approaches(self, ac, candidates=()) -> bool:
        """Ask him WHICH approach he would like, naming what this field has.

            "A field has a set of approaches available to it. When a pilot
             approaches the field -- on a flight plan or not (just coming into
             the airspace vfr) the approach should ask which approach he would
             like and assign it to him, and support him in that approach"

        The half #162 left out. It established that a field OFFERS a set and
        Approach ISSUES one, and wired the issuing to a FILED plan only -- so a
        VFR arrival, an air start, or anybody not on the frag could never be
        given one. He then had no procedure, an empty holding stack, and
        `request_approach` fell through saying NOTHING. Asking is what a
        controller does, and it is also the only thing that turns "he has no
        approach" from a dead end into a conversation. [#177]

        `candidates` narrows the offer to a genuine ambiguity -- "the ILS" at a
        field with one to each end -- which is #165's rule: an ambiguous
        request is refused by NAMING the candidates, never resolved by list
        order. Empty offers everything published at his field.

        Returns True when something was said, so the caller can stop.
        """
        offer = tuple(candidates) or self.published_approaches(ac)
        if not offer:
            return False
        said = ", ".join(self._approach_words(p) for p in offer)
        if len(offer) == 1:
            # ONE ON OFFER IS NOT A QUESTION. Reading a list of one to a pilot
            # and asking him to choose is the kind of politeness that costs a
            # transmission and tells him nothing.
            self.say(ac.callsign,
                     f"{self._addr(ac)}, expect the {said}. Advise when ready.")
            return True
        self.say(ac.callsign,
                 f"{self._addr(ac)}, we have the {said}. Say which you want.")
        return True

    def published_approaches(self, ac=None) -> tuple:
        """What THIS controller's field offers. A fact about the map.

        Read from the theatre rather than held, for the reason the whole of
        #162 is about: a set of approaches belongs to an aerodrome and nothing
        in this process may hold a singular one. Scoped to the field of the
        seat that is speaking, because a role is unique only within an
        aerodrome and so is a procedure -- offering Kobuleti's ILS to a man
        recovering at Batumi is the same error one axis over.
        """
        from marshall.core import theatre as _t
        # HIS SEAT'S FIELD FIRST -- `_me` is set by the radio from the frequency
        # the transmission arrived on, which is the one fact a pilot cannot
        # influence. Then the aeroplane's own, for a caller that has an
        # aircraft and no seat (the dry run, the tests). Empty searches the map,
        # which is honest rather than wrong: a controller nobody has placed
        # should offer everything rather than one aerodrome's by accident.
        fld = getattr(self._me, "field", "") or ""
        if not fld and ac is not None:
            fld = self._key(ac)
        rows = _t.approaches_now()
        return tuple(p for _k, p in sorted(rows.items())
                     if not fld
                     or (getattr(getattr(p, "aerodrome", None), "name", "")
                         or "").lower() == str(fld).lower())

    def _approach_words(self, p) -> str:
        """One approach, as a controller names it on the air."""
        kind = (getattr(p, "kind", "") or "").lower()
        spoken = {"ils": "I-L-S", "asr": "radar approach",
                  "ndb": "beacon approach", "gca": "G-C-A",
                  "vor": "V-O-R"}.get(kind, kind.upper() or "approach")
        rwy = getattr(p, "runway", "") or ""
        return f"{spoken} runway {rwy}" if rwy else spoken

    def request_approach(self, cs: str, wants: str = "") -> None:
        # A pilot who calls up asking for the approach directly (no prior check-in
        # or beacon report) should still be worked, not ignored. Enter a new
        # arrival into the stack bottom-up, then let the sequencer clear them.
        ac = self.get(cs)
        # THE APPROACH CLEARANCE IS APPROACH'S, and this is the same invariant
        # `request_takeoff` has enforced since the ground procedure was written
        # -- the terminal end of it simply never got the line.
        #
        #     04:52:00  Sockeye, cleared I-L-S approach runway 13, report
        #               established on the final approach course.
        #     04:56:33  Sockeye, cleared I-L-S approach runway 13, continue.
        #
        # Georgia Center, twice, on 12 August; and Batumi Approach never cleared
        # him at all, which is what the pilot logged:
        #
        #     "approach, never actually cleared me for the approach, and never
        #      asked if I have information alpha"
        #
        # It is not a phrasing fault. An approach clearance puts an aeroplane
        # into the letdown, which holds ONE aircraft, so a controller who issues
        # one for a runway that is not his has put a second aeroplane somewhere
        # the man responsible for it cannot see. That is the accident this
        # engine exists to prevent, arrived at by an unguarded method rather
        # than by anything a pilot did. See #138.
        #
        # DEPARTURE COUNTS AS APPROACH -- `_owns` reads `Station.also`, and at a
        # field with one radar room they are the same man under two names.
        if not self._owns("approach"):
            # Lower case: `_not_mine` drops it mid-sentence after the
            # callsign, so a capitalised phrase reads as a title and Polly
            # gives it the wrong stress.
            self._not_mine(ac, "approach", "the approach clearance")
            return
        if ac.phase == Phase.CLEARED:
            # Already cleared (e.g. the aircraft ahead just landed and freed the
            # letdown for him) -- re-affirm, don't send him back to the hold.
            self.say(ac.callsign,
                     f"{self._addr(ac)}, cleared {self._approach_name(ac)} runway "
                     f"{getattr(self._pro(ac), 'runway', '') or 'in use'}, continue.")
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
        # WHICH APPROACH IS HE ASKING FOR, AND HAS ANYBODY GIVEN HIM ONE.
        #
        #     "When a pilot approaches the field -- on a flight plan or not
        #      (just coming into the airspace vfr) the approach should ask
        #      which approach he would like and assign it to him, and support
        #      him in that approach"
        #
        # Until this block, ISSUING an approach had one caller and it read a
        # FILED plan (`assigned_plans.approach`). A pilot who asked on the
        # radio -- VFR, air-started, or simply not on the frag -- was never
        # given one, so `_pro` stayed None, his holding stack was empty,
        # `_free_slot` returned None, and this method fell through in SILENCE.
        # Measured: radar-identified, asking plainly, and the engine said
        # nothing at all. That is worse than the wrong answer it replaced,
        # because a controller who does not answer is indistinguishable from a
        # dead radio.
        #
        # THE ASSIGNMENT IS THE ENGINE'S, and that is not bureaucracy: an
        # approach clearance puts an aeroplane into a letdown that holds ONE,
        # so which procedure he is on decides who contends with whom. It may
        # not be a thing the language half remembers having said. [#177]
        if self._pro(ac) is None:
            want, maybe = _match_spoken(
                wants, _published_now(), field=getattr(self._me, "field", ""))
            if want is not None:
                self.assign_approach(ac.callsign, want)
            elif self.offer_approaches(ac, maybe):
                # ASKED, AND NOT STACKED. He has no procedure, so there is no
                # stack of his to enter and nothing to sequence him against --
                # putting him in one before he has chosen would be inventing
                # the contention the choice decides.
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
                     f"{self._addr(ac)}, {self._introduce(ac)}"
                     f"{self._hold_phrase(ac, held_at, ac.kit)}.",
                     decided=D.Decision(kind="hold", to=ac.callsign,
                                        altitude_ft=held_at,
                                        station=getattr(self._pro(ac), "controller", "")))
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
                 f"{self._addr(ac)}, cleared {self._approach_name(ac)} runway "
                 f"{getattr(self._pro(ac), 'runway', '') or 'in use'}, "
                 f"{self._report_phrase(ac)}. "
                 f"Report missed approach or landing."
                 f"{self._no_acknowledgement_phrase(ac)}",
                 decided=D.Decision(kind="cleared_approach", to=ac.callsign,
                                    runway=getattr(self._pro(ac), 'runway', '') or "",
                                    note=self._approach_name(ac)))
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
            self.say(cs, f"{addr}, {self._introduce(ac)}no report, "
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
            # THE MAN WORKING HIM introduces himself, and this named the
            # radio's. Two aeroplanes go quiet in two stacks and both were
            # prompted by the same controller, one of whom is not working that
            # field. The letdown timeout eight lines up already asked `_pro`.
            self.say(ac.callsign, f"{self._addr(ac)}, {self._introduce(ac)}"
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
