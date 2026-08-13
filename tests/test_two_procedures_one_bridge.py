"""Two aircraft, two procedures, one bridge -- and each gets his own rule.

`tests/test_two_fields.py` is the sibling of this file and made the same
argument about AERODROMES: a role is unique only within one, so anything
resolving a controller takes a field. This is the same shape one level in. A
guidance rule is a property of a PROCEDURE, so anything asking one takes an
aeroplane -- and five call sites in the bridge were asking the profile the
bridge happened to be started with.

    agent_atc.asr_context          may_vector, the geometry and its datum
    agent_atc.separation_context   asr.guide -- is he established on final
    agent_atc.next_controller      handoff.due, and leaving_my_airspace
    agent_atc.settle               the phase guidance, the missed approach
    handoff._inbound_within        "a talkdown makes LANDING the trigger"

THE WRONG ANSWER IS A REAL ANSWER, which is why none of this showed up. A
Mustang on the 1944 beacon letdown beside a Viper on the ILS was handed to
Tower at five miles because the Viper's rule applied -- a real transition, to a
real controller, at a plausible range, taking a pilot off the frequency in the
middle of the procedure that was flying him down.

The accessor is `controller.procedure_of` / `Controller.procedure_for`, and its
docstring carries the line between the two questions. This file is the check
that the line holds. [#150]
"""

from __future__ import annotations

import dataclasses
import pathlib
import unittest

from marshall.core.approach import may_vector as _may_vector
from marshall.atc import controller as C
from marshall.atc import handoff as H
from tests import theatre as TH


def two_procedures():
    """An ILS, and the SAME procedure guided as a talkdown.

    Built by `dataclasses.replace` rather than taken from the map, and that is
    the honest choice rather than the lazy one. `TH.letdown()` returns Caucasus'
    published 1944 beacon letdown, which differs from an ILS in every field it
    has -- including `theatre_stations=False`, so it staffs no ladder at all and
    `handoff.due` returns None for it whatever the guidance says.

    A test using it here would have PASSED, for the wrong reason, and gone on
    passing if the talkdown rule were deleted outright. It did: that is how this
    function came to look like this.

    So guidance is varied and nothing else is. Then a difference in the verdict
    can only have come from the guidance rule, which is the claim being made.
    """
    ils = TH.the_ils(TH.arrival())
    if ils is None:
        raise unittest.SkipTest(f"{TH.name()} publishes no ILS at its arrival")
    if ils.guidance == "talkdown":
        raise unittest.SkipTest("this map's ILS is already a talkdown")
    return ils, dataclasses.replace(ils, guidance="talkdown")


class TestTheAccessorAnswersForTheAEROPLANE(unittest.TestCase):

    def setUp(self):
        self.ils, self.talkdown = two_procedures()
        self.ctl = C.Controller(self.ils)          # the bridge is on the ILS
        self.ctl._me = TH.station("approach", TH.arrival())

    def test_an_aeroplane_with_a_procedure_gets_his_own(self):
        self.ctl.bind("Mustang 1", track="Mustang 1")
        self.ctl.get("Mustang 1").profile = self.talkdown
        self.assertIs(self.ctl.procedure_for("Mustang 1"), self.talkdown)

    def test_and_one_without_falls_back_to_the_bridge(self):
        """The behaviour every call site had before. An aeroplane nobody has
        cleared for a recovery has no procedure, and that is not an error --
        it is the ordinary state of a man taxiing out."""
        self.ctl.bind("Viper 2", track="Viper 2")
        self.assertIs(self.ctl.procedure_for("Viper 2"), self.ils)

    def test_a_callsign_nobody_knows_is_the_blind_case_not_a_crash(self):
        self.assertIs(self.ctl.procedure_for("Nobody 9"), self.ils)

    def test_and_so_is_no_callsign_at_all(self):
        self.assertIs(self.ctl.procedure_for(""), self.ils)

    def test_the_free_function_needs_no_controller(self):
        """`procedure_of` is deliberately outside the class: the bridge's own
        functions hold an aircraft and a fallback and no Controller."""
        self.assertIs(C.procedure_of(None, self.ils), self.ils)

        class Ac:
            profile = self.talkdown
        self.assertIs(C.procedure_of(Ac(), self.ils), self.talkdown)


class TestEachAircraftGetsHisOwnGuidanceRule(unittest.TestCase):
    """Criterion 3, and the failure it describes, through one controller."""

    NM = 4.0        # inside the final, where the two rules disagree

    def setUp(self):
        self.ils, self.talkdown = two_procedures()
        self.me = TH.station("approach", TH.arrival())
        self.st = H.State(on_ground=False, range_nm=self.NM, inbound=True,
                          phase="arrival")

    def test_the_ils_is_handed_to_tower_inside_the_final(self):
        v = H.due(self.ils, self.me, self.st)
        self.assertIsNotNone(v, "an ILS arrival is handed over at ARRIVAL_NM")
        self.assertEqual(v.role, "tower")

    def test_the_talkdown_keeps_him(self):
        """"The final controller obtains the landing clearance from Tower and
        relays it, and the pilot never changes frequency inside the final."
        Handing him over here abandons him at the moment the procedure starts;
        it did, live, at ten miles in cloud."""
        self.assertIsNone(H.due(self.talkdown, self.me, self.st))

    def test_and_the_talkdown_IS_handed_over_once_he_is_down(self):
        """The half that stops the rule being a brake, and the half that makes
        the test above mean something.

        A talkdown does not SUPPRESS the handoff, it moves the trigger from a
        distance to a landing -- `handoff.py` says exactly that. Without this
        assertion the test above would pass just as well against a procedure
        that is handed over to nobody ever, which is the trap this file already
        fell into once; see `two_procedures`.
        """
        down = H.State(on_ground=True, range_nm=0.1, inbound=False, phase="")
        v = H.due(self.talkdown, self.me, down)
        self.assertIsNotNone(v, "a talkdown that has landed is never handed on")
        self.assertEqual(v.role, "tower")

    def test_one_bridge_gives_both_answers_in_the_same_breath(self):
        """The whole issue in one assertion. Before the fix both aircraft got
        whichever answer the BRIDGE's profile produced, so these two calls --
        which differ in nothing but the aeroplane -- returned the same thing."""
        ctl = C.Controller(self.ils)
        ctl._me = self.me
        ctl.bind("Viper 1", track="Viper 1")
        ctl.bind("Mustang 2", track="Mustang 2")
        ctl.get("Mustang 2").profile = self.talkdown

        viper = H.due(ctl.procedure_for("Viper 1"), self.me, self.st)
        mustang = H.due(ctl.procedure_for("Mustang 2"), self.me, self.st)
        self.assertIsNotNone(viper, "the Viper on the ILS was not handed over")
        self.assertIsNone(mustang, "the Mustang on the talkdown was taken off "
                                   "the frequency flying him down")


class TestTheRADARPICTUREIsHisToo(unittest.TestCase):
    """`asr_context`'s first question, and the second thing that must be his.

    `may_vector` is the one question asked before any geometry is computed, and
    it returns "" for the whole approach when the answer is no. So a Mustang on
    the letdown whose profile came from the bridge was not merely handed to the
    wrong controller -- he was eligible to be given HEADINGS, which destroys
    the only reference a homing adapter has, since the adapter points the nose
    at the beacon.

    It reads three things in order -- the capability, `vectored`, then guidance
    -- because it was once asked three ways that disagreed. Both pairs below
    part on it, by different routes, and that is worth asserting separately:
    the map's real letdown answers on `vectored`, the controlled pair falls
    through to guidance.
    """

    def test_the_controlled_pair_parts_on_guidance(self):
        ils, talkdown = two_procedures()
        self.assertTrue(_may_vector(ils), "an ILS controller vectors to "
                                          "intercept and then stops")
        self.assertFalse(_may_vector(talkdown))

    def test_and_the_maps_real_letdown_parts_on_vectored(self):
        """A different route to the same answer, so a change to either branch
        of `may_vector` cannot pass here by satisfying the other."""
        letdown = TH.letdown()
        if letdown is None:
            self.skipTest(f"{TH.name()} publishes no letdown")
        self.assertFalse(_may_vector(letdown))
        self.assertNotEqual(getattr(letdown, "guidance", ""), "intercept")

    def test_the_bridge_asks_it_of_a_profile_it_is_HANDED(self):
        """`asr_context(profile, ...)` takes the procedure as its first
        argument and asks `may_vector` of that -- so the fix for this call site
        is entirely in what the caller passes, and the caller is `decide`."""
        import inspect

        from marshall.atc import agent_atc as A
        self.assertEqual(
            next(iter(inspect.signature(A.asr_context).parameters)), "profile")
        src = inspect.getsource(A.decide)
        self.assertIn("asr_context(profile", src,
                      "decide no longer forwards its profile to asr_context")


class TestTheTHEATREQuestionIsNotThisQuestion(unittest.TestCase):
    """Criterion 2: the two must not be answerable from the same argument.

    `station_for` takes a `procedure`, which looks like the very confusion this
    issue is about. It is not, and the distinction is worth pinning down
    because it is what would make the fix WRONG if it were fumbled: a
    per-aircraft station table hands an aeroplane another theatre's
    controllers, which is a worse bug than the one being fixed.

    The procedure is asked exactly one boolean about ITSELF -- does it staff
    the ladder at all -- and never yields a Station.
    """

    def test_the_seats_come_from_the_map_not_the_procedure(self):
        from marshall.core import theatre as T
        ils, talkdown = two_procedures()
        self.assertEqual([s.name for s in T.seats_now(ils)],
                         [s.name for s in T.seats_now(talkdown)],
                         "two procedures on one map produced different "
                         "controllers -- a station belongs to the THEATRE")

    def test_a_procedure_carries_no_stations_of_its_own(self):
        """The attribute whose existence caused #162. If it comes back,
        `procedure_of` becomes a way to reach a station and this separation is
        gone."""
        ils, _ = two_procedures()
        self.assertFalse(hasattr(ils, "stations"),
                         "an ApproachProfile is carrying a station list again")

    def test_and_the_accessor_says_so_where_somebody_will_read_it(self):
        """A rule that lives only in a test is one the next person breaks
        before the test tells them. It belongs on the accessor."""
        self.assertIn("theatre_stations", C.procedure_of.__doc__ or "")


class TestTheFiveCallSitesAskForTheAEROPLANE(unittest.TestCase):
    """The sites themselves, pinned in source -- and that is a compromise.

    Everything above tests a leaf: `handoff.due` given a procedure returns the
    right verdict. What it cannot reach is whether the BRIDGE hands it the
    right one, because all five sites live inside the receive loop or the
    monitor thread, behind a radio, a model call and a socket.

    That gap is exactly how #150 survived #2 and #111. Both fixed the leaves.

    `tests/test_a_restart_is_a_restart.py` had the same problem -- "order
    matters and cannot be asserted by running it" -- and answered it the same
    way. A source check is weaker than a behavioural one and is not nothing: it
    fails on the day somebody reverts a site to `ctl.profile`, which is the
    regression this issue is about, and it names which one.
    """

    def source(self, fn):
        import inspect
        return inspect.getsource(fn)

    def test_decide_is_handed_his_procedure(self):
        from marshall.atc import agent_atc as A
        src = self.source(A._run_srs)
        self.assertIn("ctl.procedure_for(known)", src,
                      "decide is being handed the bridge's profile again")
        self.assertIn("ctl._pro(_ac)", src,
                      "next_controller or settle is back on the bridge's")

    def test_separation_context_resolves_his(self):
        from marshall.atc import agent_atc as A
        src = self.source(A.separation_context)
        # Three questions in this one function, all of them the procedure's:
        # whether he is established on final, whether a beacon is flown at all,
        # and the DATUM his radar range is measured from. The last two were not
        # on #150's list of five and were found by the sweep below.
        self.assertEqual(src.count("ctl.procedure_for(intent.callsign)"), 3,
                         "a question in separation_context went back to the "
                         "bridge's profile")

    def test_the_proactive_monitor_asks_the_aircraft_it_already_has(self):
        from marshall.atc import agent_atc as A
        src = self.source(A.watching_him)
        self.assertIn("procedure_of(who", src)

    def test_and_no_site_left_reads_ctl_profile_for_a_PROCEDURE(self):
        """The sweep, so a sixth site added tomorrow is caught rather than
        joining a list nobody re-derives.

        `ctl.profile` is not banned -- it is the fallback `procedure_of` uses
        and `Controller` legitimately holds it. What is banned is passing it
        somewhere that decides guidance, geometry or a handoff.
        """
        import re
        src = (pathlib.Path("src/marshall/atc/agent_atc.py").read_text()
               if pathlib.Path("src/marshall/atc/agent_atc.py").exists()
               else "")
        if not src:
            self.skipTest("not running from the repo root")
        bad = [ln.strip() for ln in src.splitlines()
               if re.search(r"\bctl\.profile\b", ln)
               and not ln.lstrip().startswith("#")]
        # Seven sites when this sweep was written: the five #150 enumerated
        # plus two more it found inside `separation_context` -- the beacon
        # claim and the radar datum. Neither was on the list, which is the
        # argument for sweeping rather than ticking off.
        self.assertEqual(bad, [], "these pass the bridge's profile where a "
                                  "procedure is decided")


if __name__ == "__main__":
    unittest.main()
