"""I sign into the sim, get in a jet, and the system already knows who I am.

    "The sim knows that I am 362nd_Sockeye, knows what im in, where im at and
     what my as/gs/alt is. The sim even knows what my callsign will be
     'Sockeye' - because the process of stripping a squad off a name should be
     deterministic and instant."

It is deterministic and instant. `identity.handle` is a pure function over a
string the sim publishes on every radar poll, and it has been right the whole
time:

    handle("362nd_Sockeye") -> "Sockeye"

Nothing calls it at poll time. `handle` is reachable only through
`Registry.resolve(guid, ...)`, which is the TRANSMISSION path -- so a name the
sim hands us for free is not derived until the pilot keys a microphone, and the
untracked table prints the raw label instead.

WHY THIS IS NOT COSMETIC. Every name-join bug in this system is two subsystems
deriving the same aeroplane's name by two different routes and then matching the
results as strings -- `track_of` keyed on a handle against a board keyed on a
canonical, `release_stale` comparing a board key to a scope label. Derive it ONCE,
from the sim, at the poll, and the join stops existing: it becomes the same
function over the same input.

So the untracked table shows BOTH, side by side --

    "I want untracked to show the dcs callsign and the derived callsign - so
     that I can see the translation."

-- because a translation you can see is one that can be wrong in front of you
rather than eight layers down.

UNTRACKED MEANS NOBODY IS WORKING HIM. It does not mean we do not know who he
is. Those are two facts and the whole identity model depends on their staying
apart: "falcon 1-1 I dont have you on the board" is a sentence a controller says
about a man he can name perfectly well.
"""

import json
import tempfile
import unittest
from pathlib import Path

from marshall import config
from marshall.atc import agent_atc as A
from marshall.atc import callsign as C
from marshall.atc import identity

# EXACTLY WHAT THE SIM REPORTS for a pilot who has just taken the slot and not
# touched anything: cold on the ramp at Batumi, no callsign correlated to him by
# anybody, zero groundspeed.
#
# All four names differ, on purpose. `tests/test_scope.py` documents why that
# matters -- its fixtures defaulted `label` to `name`, so the distinction could
# not fail and 831 green tests sat either side of a live identity break.
JUST_SLOTTED_IN = {
    "name": "Viper 1-4",            # the sim's slot name
    "label": "362nd_Sockeye",       # what the radar picture prints
    "callsign": "",                 # nothing has correlated him -- he has not spoken
    "type": "F-16C_50",
    "category": "airplane",
    "manned": True,
    "player": "362nd_Sockeye",
    "on_ground": True,
    "lat": 41.60646, "lon": 41.60827,
    "alt_ft": 39.0, "heading": 215.3, "speed_kt": 0.0,
    "coalition": 3, "formation": "",
}

BATUMI = (41.609594, 41.600234)
BULLSEYE = {"blue": {"lat": 42.186548, "lon": 41.678934}}


def poll(contacts=(JUST_SLOTTED_IN,), board=()):
    """One radar tick with nobody on the radio. The bridge publishes; we read.

    No SRS, no Whisper, no LLM, no network -- which is the point. Everything
    asserted below is available to the system before anyone transmits.
    """

    class Ctl:
        def board(self):
            return list(board)

    scope = A.Scope("", contacts=list(contacts), origin=BATUMI,
                    bullseye=BULLSEYE)
    old = config.BUILD_DIR
    with tempfile.TemporaryDirectory() as d:
        config.BUILD_DIR = Path(d)
        try:
            A.publish_state(A.Bridge(), Ctl(), scope, "s")
            return json.loads((Path(d) / "control" / "state.json").read_text())
        finally:
            config.BUILD_DIR = old


class TestTheSimAlreadyKnowsMyCallsign(unittest.TestCase):
    """The derivation, standing alone. This half has always worked."""

    def test_the_handle_falls_out_of_the_label(self):
        self.assertEqual(identity.handle("362nd_Sockeye"), "Sockeye")

    def test_and_it_is_the_key_the_board_would_use(self):
        """The end of the chain is the board's own primary key, which is why
        deriving it here removes a join rather than adding a field."""
        got = C.parse(identity.handle("362nd_Sockeye")).canonical
        self.assertEqual(got, "Sockeye")

    def test_it_needs_nothing_but_the_string(self):
        """No radio, no GUID, no scope, no clock. If this ever needs an
        argument it does not have, the instant answer has stopped being one."""
        self.assertEqual(identity.handle("362nd_Sockeye"),
                         identity.handle("362nd_Sockeye"))


class TestSittingOnTheRampBeforeAnybodySpeaks(unittest.TestCase):
    """What the untracked table must say about a man who has not transmitted."""

    def setUp(self):
        self.state = poll()
        self.assertEqual(len(self.state["scope"]), 1, "one contact, one row")
        self.row = self.state["scope"][0]

    def test_the_dcs_name_is_shown(self):
        """The left half of the translation: what the sim called him."""
        self.assertEqual(self.row["name"], "362nd_Sockeye")

    def test_the_derived_callsign_is_shown(self):
        """The right half, and the one that is missing today.

        This is the assertion the whole file exists for. The value is one
        function call away from data already in the row.
        """
        self.assertEqual(self.row["derived"], "Sockeye")

    def test_he_is_named_without_having_said_a_word(self):
        """Nobody keyed a microphone in this test. That is the requirement:
        naming him is not a reward for transmitting."""
        self.assertNotIn("unidentified", [r for r in self.state["unidentified"]])
        self.assertTrue(self.row["derived"],
                        "named from the sim alone, with no radio in the chain")

    def test_the_sim_facts_come_through_with_him(self):
        """Type and ground state, because a controller deciding whether to say
        'radar contact' needs to know he is parked."""
        self.assertEqual(self.row["type"], "F-16C_50")
        self.assertIn("on the ground", self.row["tags"])
        self.assertIn("manned", self.row["tags"])

    def test_nobody_is_working_him(self):
        """UNTRACKED is about ownership, not about knowledge. He is fully
        named and no controller has him."""
        self.assertFalse(self.row["controlled"])
        self.assertEqual(self.row["level"], "warn")

    def test_and_he_is_on_no_board(self):
        """Taking a slot does not admit an aeroplane. The board is entered by
        checking in, which he has not done."""
        self.assertEqual(self.state["board"], [])


class TestTheTranslationIsVisibleWhenTheTwoDisagree(unittest.TestCase):
    """The reason to print both rather than just the derived one.

    A label the rule handles badly is a thing to SEE, not to discover from a
    controller using the wrong name on the radio.
    """

    def test_a_label_with_no_squadron_tag_still_translates(self):
        row = poll([{**JUST_SLOTTED_IN, "label": "Andre", "player": "Andre"}]
                   )["scope"][0]
        self.assertEqual(row["name"], "Andre")
        self.assertEqual(row["derived"], "Andre")

    def test_a_digit_in_the_name_is_dropped_by_the_rule(self):
        """`handle` drops any chunk containing a digit, so "Hoover 1-1-1"
        becomes "Hoover". Whether that is right is a judgement -- the table
        exists so it is a visible one."""
        row = poll([{**JUST_SLOTTED_IN, "label": "362nd_Hoover 1-1-1"}]
                   )["scope"][0]
        self.assertEqual(row["name"], "362nd_Hoover 1-1-1")
        self.assertEqual(row["derived"], "Hoover")


def controller(*callsigns):
    from marshall.atc.controller import Controller
    from marshall.core import route as R
    c = Controller(R.BATUMI_ASR)
    for cs in callsigns:
        c.get(cs)
    return c


def airborne(**kw):
    """The same man, up and away, so the board has something to work."""
    return {**JUST_SLOTTED_IN, "on_ground": False, "alt_ft": 4000.0,
            "speed_kt": 250.0, "lat": 41.75, "lon": 41.45, **kw}


class TestHeIsNotDroppedWhileRadarCanSeeHim(unittest.TestCase):
    """The serious half of `HANDOFF-board.md`, with the names that broke it.

    It happened NINE TIMES in the 30 July sortie, to a live aeroplane at 0.4 nm.
    The guard asked whether the board's key -- "Sockeye" -- was among the scope's
    labels -- "362nd_Sockeye" -- and those are never equal, so nothing ever
    accounted for him and he aged off the board under a live approach.

    The old test could not fail. Its scope named the contact "Falcon 1-1", the
    same string the board was keyed on, so the comparison was between a name and
    itself.
    """

    def scope(self):
        return A.Scope("", contacts=[airborne()], origin=BATUMI,
                       bullseye=BULLSEYE)

    def test_the_board_key_and_the_scope_label_are_not_equal(self):
        """The premise, asserted so the rest of the class cannot go vacuous the
        way its predecessor did."""
        u = identity.units_on(self.scope())[0]
        self.assertEqual(u.name, "362nd_Sockeye")
        self.assertNotEqual(u.name, "Sockeye")

    def test_he_stays_on_the_board(self):
        ctl, bridge, scope = controller("Sockeye"), A.Bridge(), self.scope()
        A.release_stale(bridge, ctl, scope, now=0.0)
        gone = A.release_stale(bridge, ctl, scope, now=A.STALE_BOARD_SEC + 1)
        self.assertEqual(gone, [], "radar is painting him")
        self.assertIn("Sockeye", ctl.aircraft)

    def test_a_release_keeps_the_evidence_that_would_condemn_it(self):
        """A release destroys its own evidence -- the row is gone and nothing
        can be asked afterwards why. So the scope is recorded WITH it.

        There is no automatic guard for this and writing one taught me why: the
        entries dropped wrongly are exactly the ones our matcher failed to
        relate to a contact, and asking the same matcher a second time fails the
        same way. A human reading "released Ghost 1-1; the scope held
        362nd_Sockeye" is the only detector that works.
        """
        ctl, bridge, scope = controller("Ghost 1-1"), A.Bridge(), self.scope()
        A.release_stale(bridge, ctl, scope, now=0.0)
        A.release_stale(bridge, ctl, scope, now=A.STALE_BOARD_SEC + 1)
        self.assertEqual(len(bridge.releases), 1)
        self.assertEqual(bridge.releases[0]["callsign"], "Ghost 1-1")
        self.assertEqual(bridge.releases[0]["scope"], ["362nd_Sockeye"])

    def test_a_man_radar_cannot_see_still_goes(self):
        """The leftover this function exists to remove is still removed --
        broadening the evidence must not make every entry immortal."""
        ctl, bridge = controller("Sockeye", "Ghost 1-1"), A.Bridge()
        A.release_stale(bridge, ctl, self.scope(), now=0.0)
        gone = A.release_stale(bridge, ctl, self.scope(),
                               now=A.STALE_BOARD_SEC + 1)
        self.assertEqual(gone, ["Ghost 1-1"])


class TestTheBoardRowIsNotEmpty(unittest.TestCase):
    """The other half: every derived column went blank on one failed lookup.

    `track_of` was keyed on the identity's handle, "sockeye"; the board is keyed
    on the canonical, "Sockeye". `.get("Sockeye")` missed, so the row lost its
    track -- and with no track there is no type, no position, no plan, and
    `confirmed` degraded from `radar` to `claimed`.
    """

    def publish(self, ctl, bridge, contacts=None):
        scope = A.Scope("", contacts=contacts or [airborne()], origin=BATUMI,
                        bullseye=BULLSEYE)
        old = config.BUILD_DIR
        with tempfile.TemporaryDirectory() as d:
            config.BUILD_DIR = Path(d)
            try:
                A.publish_state(bridge, ctl, scope, "s")
                return json.loads(
                    (Path(d) / "control" / "state.json").read_text())
            finally:
                config.BUILD_DIR = old

    def registered(self):
        """Identity as the registry actually holds it: a lowercase handle."""
        bridge = A.Bridge()
        bridge.identity.by_guid["g"] = identity.Identity(
            callsign="sockeye", track="362nd_Sockeye", authority="radar", why="")
        return bridge

    def test_the_row_finds_its_track_across_the_case_difference(self):
        row = self.publish(controller("Sockeye"), self.registered())["board"][0]
        self.assertEqual(row["callsign"], "Sockeye")
        self.assertEqual(row["track"], "362nd_Sockeye")

    def test_and_therefore_carries_what_the_sim_knows(self):
        row = self.publish(controller("Sockeye"), self.registered())["board"][0]
        self.assertEqual(row["type"], "F-16C_50")
        self.assertEqual(row["alt_ft"], 4000.0)
        self.assertEqual(row["confirmed"], "radar")

    def test_a_bound_track_needs_no_join_at_all(self):
        """The route that removes the question. Once `bind` has run the row
        carries its own key and nothing downstream derives anything."""
        ctl = controller("Sockeye")
        ctl.bind("Sockeye", track="362nd_Sockeye", owner="approach")
        row = self.publish(ctl, A.Bridge())["board"][0]   # empty registry
        self.assertEqual(row["track"], "362nd_Sockeye")
        self.assertEqual(row["owner"], "approach")
        self.assertEqual(row["confirmed"], "radar")

    def test_the_sim_state_rides_along(self):
        ctl = controller("Sockeye")
        ctl.bind("Sockeye", track="362nd_Sockeye")
        self.assertEqual(self.publish(ctl, A.Bridge())["board"][0]["state"],
                         "airborne")

    def test_and_on_the_ramp_he_is_parked(self):
        ctl = controller("Sockeye")
        ctl.bind("Sockeye", track="362nd_Sockeye")
        got = self.publish(ctl, A.Bridge(), contacts=[JUST_SLOTTED_IN])
        self.assertEqual(got["board"][0]["state"], "parked")

    def test_intent_is_blank_until_he_says(self):
        """Which is the useful part: a blank here means nobody has asked him."""
        ctl = controller("Sockeye")
        self.assertEqual(self.publish(ctl, A.Bridge())["board"][0]["intent"], "")
        ctl.note_intent("Sockeye", "asr approach")
        self.assertEqual(self.publish(ctl, A.Bridge())["board"][0]["intent"],
                         "asr approach")


class TestAFlightIsKeyedOnNobodysHandle(unittest.TestCase):
    """The case a case-insensitive join would still have missed.

    In a flight the board key is the FLIGHT's name -- "Apex" -- and the identity
    callsign is a member's handle -- "sockeye". No amount of case folding relates
    those two strings, so the fix prescribed in the handoff note would have left
    every formation's row blank while looking correct for a single ship.
    """

    def test_the_flights_row_gets_the_leads_track(self):
        from marshall.atc import flights as fl
        bridge = A.Bridge()
        bridge.identity.by_guid["g"] = identity.Identity(
            callsign="sockeye", track="362nd_Sockeye", authority="radar", why="")
        bridge.flights.flights["Apex"] = fl.Flight(
            name="Apex", lead="sockeye", members=["sockeye"])
        scope = A.Scope("", contacts=[airborne()], origin=BATUMI,
                        bullseye=BULLSEYE)
        old = config.BUILD_DIR
        with tempfile.TemporaryDirectory() as d:
            config.BUILD_DIR = Path(d)
            try:
                A.publish_state(bridge, controller("Apex"), scope, "s")
                got = json.loads(
                    (Path(d) / "control" / "state.json").read_text())
            finally:
                config.BUILD_DIR = old
        self.assertEqual(got["board"][0]["callsign"], "Apex")
        self.assertEqual(got["board"][0]["track"], "362nd_Sockeye")


class TestHeIsBoundOnHisFirstCallNotHisSecond(unittest.TestCase):
    """Becoming tracked and recording who owns you are the same moment.

    THE ORDER WAS WRONG AND EVERYTHING WAS GREEN. The bind sat eighty lines up
    the receive loop from `decide`, and admission happens INSIDE `decide` --
    `intents.dispatch` is what first reaches `Controller.get`. So the guard
    looked at an empty board on a pilot's first transmission, correctly declined
    to mint an aeroplane, and he went onto the board with no track and no owner.
    He was bound on his SECOND call.

    The first call is "with you, request the approach". That is the whole window
    that matters, and nothing could see it: `_run_srs` is 1,167 lines and no
    test executes any of them, which is how a line can be in the wrong place and
    the suite can be green about it.

    So the binding now lives in the same function as the admission, and this
    test drives that function rather than trusting a line's position in a loop.
    """

    def setUp(self):
        from marshall.core import route as R
        from marshall.atc.controller import Controller
        self.ctl = Controller(R.BATUMI_ASR)
        self.ctl.working = "approach"
        self.scope = A.Scope("", contacts=[airborne()], origin=BATUMI,
                             bullseye=BULLSEYE)
        # THE CLASSIFIER IS NETWORK. This suite is the cheap one -- "pure
        # stdlib, no LLM/network/sim, milliseconds" -- and `decide` now calls
        # Bedrock for anybody on the board. Left unstubbed it took the suite
        # from 5.7 seconds to 54, which is how a fast test suite quietly stops
        # being one.
        self._real = A.classify_intent
        A.classify_intent = lambda t: None
        self.addCleanup(lambda: setattr(A, "classify_intent", self._real))

    def admit(self):
        """What `intents.dispatch` does when it first hears from him -- the
        engine deciding he is an aeroplane, with no idea what a track is."""
        self.ctl.get("sockeye")

    def test_the_engine_admits_him_knowing_nothing_about_a_track(self):
        """The premise. The engine is blind, so admission cannot bind."""
        self.admit()
        ac = self.ctl.aircraft["Sockeye"]
        self.assertEqual((ac.track, ac.owner), ("", ""))

    def test_decide_binds_him_in_the_same_breath(self):
        A.decide(A.Bridge(), self.ctl, "with you, request the approach",
                 self.scope, "sockeye", "362nd_Sockeye",
                 engaged=False, profile=self.ctl.profile)
        self.admit()                      # the engine, later in the same turn
        A.decide(A.Bridge(), self.ctl, "level five thousand", self.scope,
                 "sockeye", "362nd_Sockeye", engaged=False,
                 profile=self.ctl.profile)
        ac = self.ctl.aircraft["Sockeye"]
        self.assertEqual(ac.track, "362nd_Sockeye")
        self.assertEqual(ac.owner, "approach")

    def test_a_voice_with_no_track_is_never_admitted(self):
        """THE GUARD THAT MATTERS MORE THAN THE BINDING, and the rule changed
        under it -- so this now states the real one.

        Becoming tracked requires a TRACK: the sim saying this radio is sitting
        in that aeroplane. That is what "only from untracked" means in code, and
        it is why no transcript can mint an aeroplane -- there is no route from
        words to a track. On the live sortie that ran this hour, Whisper turned
        the pilot's name into "362 and D. Underscore Sockeye" on the very call
        that identified him correctly, because the words identify nobody.

        A well-formed callsign with nothing behind it is exactly the ghost class
        [#40] measured: 37 distinct names bound from 846 real transmissions.
        """
        A.decide(A.Bridge(), self.ctl, "Pony one one, request the approach",
                 self.scope, "Pony 1-1", "", engaged=False,
                 profile=self.ctl.profile)
        self.assertEqual(list(self.ctl.aircraft), [], "no ghost was minted")

    def test_nor_can_an_intention_put_him_on_the_board(self):
        """`note_intent` went through `get`, which is a `setdefault` -- so a
        display feature quietly reopened the ghost door. A man nobody has
        admitted has no row for his intentions to be written on."""
        self.ctl.note_intent("Pony 1-1", "asr approach")
        self.assertEqual(list(self.ctl.aircraft), [])

    def test_but_a_real_track_does_admit_him(self):
        """The other half: contacting a controller from an aeroplane the sim can
        see IS how you become tracked. That is the whole transition."""
        A.decide(A.Bridge(), self.ctl, "Batumi Approach, with you", self.scope,
                 "sockeye", "362nd_Sockeye", engaged=False,
                 profile=self.ctl.profile)
        self.assertIn("Sockeye", self.ctl.aircraft)
        self.assertEqual(self.ctl.aircraft["Sockeye"].owner, "approach")


class TestAVanishedAeroplaneIsNotFlying(unittest.TestCase):
    """An aircraft radar has stopped seeing must not read as "airborne".

    CAUGHT LIVE. `is_on_the_ground` returns False for a track that is not on the
    scope -- it finds no unit, the position is None, so the geometry fallback is
    false too -- and the obvious reading of that (false means flying) put a board
    entry for an aeroplane that had LEFT THE WORLD into state "airborne".

    Absence of evidence read as evidence, which is the shape of every bug in
    `test_tonight.py`. The board already has a column for "we cannot see him"
    and it is `confirmed`; `state` should say nothing at all.
    """

    def empty_scope(self):
        return A.Scope("", contacts=[], origin=BATUMI, bullseye=BULLSEYE)

    def test_off_the_scope_has_no_state(self):
        self.assertEqual(A.sim_state(self.empty_scope(), "362nd_Gone-1"), "")

    def test_on_the_scope_still_reports_normally(self):
        scope = A.Scope("", contacts=[airborne()], origin=BATUMI,
                        bullseye=BULLSEYE)
        fix = A.radar_fix_by_track(scope, "362nd_Sockeye")
        self.assertEqual(A.sim_state(scope, "362nd_Sockeye", fix), "airborne")

    def test_and_a_parked_one_says_parked(self):
        """The case the whole change exists for: he is on the scope, he is not
        moving, and the sim's `on_ground` EVENT flag says nothing useful."""
        scope = A.Scope("", contacts=[JUST_SLOTTED_IN], origin=BATUMI,
                        bullseye=BULLSEYE)
        fix = A.radar_fix_by_track(scope, "362nd_Sockeye")
        self.assertEqual(A.sim_state(scope, "362nd_Sockeye", fix), "parked")


class TestOneAeroplaneGetsOneRow(unittest.TestCase):
    """A track already on the board must not open a second entry.

    CAUGHT LIVE, 31 July, minutes after the door it came through was built. The
    pilot said "established ON the final approach course"; the flight parser
    took "on" for a name; `speaking_as` reported he was called "On"; and
    `become_tracked` -- seeing a perfectly real track -- admitted him. One
    Mustang, two rows:

        SEPARATION: Andre unknown -; On cleared 5000 ft

    TWO ENTRIES ARE WHAT MAKES THE ENGINE ENGAGE, so a duplicate turns a single
    ship into a sequencing problem between a pilot and himself. That is the
    outage `release_stale` was written about, arriving by a new route.

    The parser is fixed too, but the guard belongs HERE: parsers will keep
    mishearing, because the supply of English words is unbounded ([#40] bound 37
    of them as names across 846 real transmissions). What must never follow from
    a misheard name is a second aeroplane -- and the track is the one identifier
    no transcript can reach.
    """

    def setUp(self):
        from marshall.core import route as R
        from marshall.atc.controller import Controller
        self.ctl = Controller(R.BATUMI_ASR)
        self.ctl.working = "approach"

    def test_the_second_name_for_one_track_is_refused(self):
        self.assertTrue(A.become_tracked(self.ctl, "Andre", "362nd_Andre-1"))
        self.assertFalse(A.become_tracked(self.ctl, "On", "362nd_Andre-1"))
        self.assertEqual(list(self.ctl.aircraft), ["Andre"])

    def test_the_same_man_calling_again_is_not_a_duplicate(self):
        """The guard must not refuse him on his own second transmission."""
        A.become_tracked(self.ctl, "Andre", "362nd_Andre-1")
        self.assertTrue(A.become_tracked(self.ctl, "Andre", "362nd_Andre-1"))
        self.assertEqual(list(self.ctl.aircraft), ["Andre"])

    def test_a_genuinely_different_aeroplane_is_still_admitted(self):
        """Refusing duplicates must not refuse traffic -- the whole system
        exists for the case where there are two of them."""
        A.become_tracked(self.ctl, "Andre", "362nd_Andre-1")
        self.assertTrue(A.become_tracked(self.ctl, "Sockeye", "362nd_Sockeye-1"))
        self.assertEqual(sorted(self.ctl.aircraft), ["Andre", "Sockeye"])


class TestEveryContactIsInExactlyOneTable(unittest.TestCase):
    """Tracked and untracked are complements. That is what makes the two
    readable together, and it is what a controller means by the words.

    FOUND BY RENDERING IT, not by the suite. Every test in this file passed
    while a bound aeroplane appeared on the board AND in the untracked list at
    once, because `board_tracks` -- the set that decides `controlled` -- was
    built from the identity REGISTRY, which only knows a track for somebody
    whose radio has been resolved. An entry bound any other way carried a
    perfectly good track on its own row and was invisible to the set.

    The same shape as everything else here: a fact read from the wrong source.
    """

    def snapshot(self, ctl, bridge=None, contacts=None):
        scope = A.Scope("", contacts=contacts or [JUST_SLOTTED_IN, airborne(
            name="Viper 1-3", label="362nd_Andre", player="362nd_Andre")],
            origin=BATUMI, bullseye=BULLSEYE)
        old = config.BUILD_DIR
        with tempfile.TemporaryDirectory() as d:
            config.BUILD_DIR = Path(d)
            try:
                A.publish_state(bridge or A.Bridge(), ctl, scope, "s")
                return json.loads(
                    (Path(d) / "control" / "state.json").read_text())
            finally:
                config.BUILD_DIR = old

    def test_a_bound_aircraft_leaves_the_untracked_list(self):
        ctl = controller("Andre")
        ctl.bind("Andre", track="362nd_Andre", owner="approach")
        got = self.snapshot(ctl)
        tracked = {r["track"] for r in got["board"]}
        loose = {u["name"] for u in got["scope"] if not u["controlled"]}
        self.assertEqual(tracked & loose, set(), "he is in both tables")
        self.assertIn("362nd_Andre", tracked)
        self.assertIn("362nd_Sockeye", loose, "the man on the ramp is still loose")

    def test_and_it_holds_when_the_registry_is_the_only_source(self):
        """The other route to a track must keep working -- this is the one that
        was accidentally load-bearing."""
        bridge = A.Bridge()
        bridge.identity.by_guid["g"] = identity.Identity(
            callsign="andre", track="362nd_Andre", authority="radar", why="")
        got = self.snapshot(controller("Andre"), bridge)
        loose = {u["name"] for u in got["scope"] if not u["controlled"]}
        self.assertNotIn("362nd_Andre", loose)


class TestOwnershipMovesWithoutPassingThroughUntracked(unittest.TestCase):
    """A handoff is an owner change. He is never unowned in between.

    Releasing him to untracked and re-admitting him would drop his level, his
    place in the letdown and his approach count at the exact moment two
    controllers are relying on them.
    """

    def test_a_handoff_changes_the_owner_and_nothing_else(self):
        ctl = controller("Sockeye")
        ctl.bind("Sockeye", track="362nd_Sockeye", owner="approach")
        ctl.get("Sockeye").assigned_ft = 5000
        ctl.bind("Sockeye", owner="tower")
        ac = ctl.get("Sockeye")
        self.assertEqual(ac.owner, "tower")
        self.assertEqual(ac.track, "362nd_Sockeye", "still the same aeroplane")
        self.assertEqual(ac.assigned_ft, 5000, "still where he was put")

    def test_a_call_with_no_news_erases_nothing(self):
        """A transmission relayed without a radar picture must not clear the
        track an earlier one established."""
        ctl = controller("Sockeye")
        ctl.bind("Sockeye", track="362nd_Sockeye", owner="approach")
        ctl.bind("Sockeye", track="", owner="")
        ac = ctl.get("Sockeye")
        self.assertEqual(ac.track, "362nd_Sockeye")
        self.assertEqual(ac.owner, "approach")


if __name__ == "__main__":
    unittest.main()
