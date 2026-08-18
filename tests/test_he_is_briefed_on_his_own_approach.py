"""One aeroplane, one approach — and the other three are a tool call away.

    "Why would the controller get briefed on multiple procedures rather than
     just the one that is requested/assigned?"

He would not. #162 put a full section for EVERY published procedure into the
static `plate` prompt part, and that was a workaround for the prompt
architecture rather than a design: the plate is assembled once per agent
(`SYSTEM_PROMPT_PARTS`) and pushed at start, so a static block can only satisfy
"the radio must work any approach" by containing all of them. Measured on the
Caucasus: 10,601 characters, of which about 4,800 described approaches nobody
on the frequency was flying.

THE SPLIT, which is what this file pins:

    what the field OFFERS   a list -- key, kind, runway, field. 154 characters,
                            genuinely static, and what lets Approach ISSUE one
                            or refuse a request for one the field has not got
    what HE is flying       the detail. A property of his CLEARANCE, resolved
                            deterministically before the model is called, and
                            injected on the turn by `compose_message`
    everything else         `look_up_approach`, the same bargain
                            `look_up_frequency` makes one axis over

WHY THE DETAIL IS INJECTED AND NOT FETCHED, since the tool exists. Two reasons
and the second is the one that matters:

1. We already know the answer -- `Controller.procedure_for` resolved it off the
   board. A tool round trip roughly doubles the turn (`services/app.py`), and
   the model call is a median 3.3 s with a worst case of 13.5.
2. **A tool call can fail, or simply not happen.** The model decides whether to
   make it. The injected procedure is the one he is being talked DOWN, and a
   surveillance approach is the one procedure that never stops talking. An
   injected block cannot fail to arrive; a tool call at three miles on final
   can.

And the tool's latency lands where it is affordable: "what else have you got"
is a conversational turn, not a vectoring one. Nobody is waiting on a heading.
[#176]
"""

from __future__ import annotations

import unittest

from marshall.atc import assembly, briefing
from marshall.atc.agent import capability

import tests.theatre as T


class TheStaticPlateOffersWithoutBriefing(unittest.TestCase):
    """It names every approach and describes none of them."""

    def setUp(self):
        self.published = T.approaches()
        self.plate = briefing.plates(self.published)

    def test_every_published_approach_is_NAMED(self):
        """He cannot issue what he has not been told exists, and he must be
        able to refuse a request for something this field has not got."""
        for key in self.published:
            with self.subTest(key):
                self.assertIn(key, self.plate)

    def test_and_none_of_them_is_DESCRIBED(self):
        """The numbers are the per-turn half. A minimum in the static prompt is
        a minimum carried on every push-to-talk for approaches nobody is
        flying — and, worse, one the controller may read to the wrong man."""
        for key, p in self.published.items():
            detail = briefing.procedure_brief(p, heading=False)
            # A LINE AT A TIME, because the two share a heading and a field
            # name by construction; what must not leak is the guidance.
            for line in detail.splitlines():
                line = line.strip()
                if len(line) < 60:          # short lines are shared furniture
                    continue
                with self.subTest(key=key, line=line[:50]):
                    self.assertNotIn(line, self.plate)

    def test_it_says_where_the_detail_comes_from(self):
        """A controller who is not told he will be handed his approach will
        assume the absence means there is nothing to fly."""
        self.assertIn("look_up_approach", self.plate)
        self.assertIn("CLEARED FOR", self.plate)

    def test_and_it_got_materially_smaller(self):
        """The measurement, not a vibe. Asserted as a RATIO against the sum of
        what it used to carry, so it survives the prose being edited."""
        detail = sum(len(briefing.procedure_brief(p, heading=False))
                     for p in self.published.values())
        self.assertLess(len(self.plate), len(self.plate) + detail,
                        "the plate carries no less than everything")
        # The static part must be smaller than the detail it stopped carrying.
        self.assertLess(len(self.plate) - 3000, detail,
                        "the offer list is not cheaper than the four plates")


class HisApproachRidesWithHisTransmission(unittest.TestCase):

    def setUp(self):
        self.ils = T.the_ils()
        if self.ils is None:                        # pragma: no cover - config
            self.skipTest(f"{T.name()} publishes no ILS")

    def test_the_brief_names_the_procedure_and_its_numbers(self):
        said = briefing.procedure_brief(self.ils)
        self.assertIn(self.ils.aerodrome.name, said)
        self.assertIn(str(self.ils.runway), said)
        self.assertIn(str(self.ils.mda_ft), said)

    def test_an_aeroplane_nobody_cleared_gets_NOTHING(self):
        """Not a default, and not another aeroplane's. He has no approach, so
        there are no approach numbers to read him — the same rule `_pro`
        follows."""
        self.assertEqual(briefing.procedure_brief(None), "")

    def test_compose_message_carries_it_and_only_his(self):
        """The seam. `compose_message` is handed `ctl.procedure_for(known)`, so
        the block a controller reads is the one aeroplane's he is answering."""
        import inspect
        src = inspect.getsource(assembly.compose_message)
        self.assertIn("procedure_brief", src)

    def test_and_carries_none_when_he_has_no_clearance(self):
        import inspect
        src = inspect.getsource(assembly.compose_message)
        self.assertIn("if profile is not None", src)


class TheOtherApproachesAreATool(unittest.TestCase):

    def test_every_seat_may_look_one_up(self):
        """A pilot asks whoever he is talking to. He asks Ground what
        approaches are in use as readily as he asks Approach, and a controller
        who cannot answer a question about his own aerodrome because of a
        capability table is a worse failure than the tokens it saves."""
        for seat in ("ground", "tower", "clearance", "approach", "departure",
                     "center", "overlord"):
            with self.subTest(seat):
                self.assertIn("procedure", capability.capabilities(seat))

    def test_the_tool_exists_and_is_named_for_the_question(self):
        from marshall.atc import procedures
        got = procedures.procedure_tools()
        self.assertEqual(len(got), 1)
        self.assertEqual(getattr(got[0], "__name__", ""), "look_up_approach")

    def test_it_refuses_rather_than_describing_from_memory(self):
        """The failure it exists to remove. An invented FREQUENCY sends a pilot
        to silence; an invented MINIMUM is an altitude somebody descends to, so
        an empty table must produce a refusal and never a plausible number."""
        from unittest import mock

        from marshall.atc import procedures
        look_up = procedures.procedure_tools()[0]
        with mock.patch.object(procedures, "_rows", lambda: []):
            said = look_up()
        self.assertIn("cannot look it up", said)

    def test_the_letdown_is_not_described_as_a_talkdown_with_headings(self):
        """The mistake I made writing `_summary`, kept as the guard.

        `batumi-ndb-12` carries `guidance="talkdown"` AND `vectored=False`,
        because the pilot is talked down a procedure he flies on his own homing
        adapter -- a HEADING destroys his only reference. Reading the guidance
        alone described it as "you navigate, continuous headings", which is the
        surveillance approach's job and is the one instruction that would break
        this one. `core.approach.may_vector` exists precisely because this
        question was being asked three different ways that disagreed; this was
        a fourth.
        """
        from unittest import mock

        from marshall.atc import procedures
        p = T.letdown()
        if p is None:
            self.skipTest(f"{T.name()} publishes no beacon letdown")
        from marshall.core import route as R
        rows = [{"key": "letdown", "field": p.aerodrome.name,
                 "data": R.profile_to_dict(p)}]
        look_up = procedures.procedure_tools()[0]
        with mock.patch.object(procedures, "_rows", lambda: rows):
            said = look_up(key="letdown")
        self.assertIn("may NOT vector", said)
        self.assertNotIn("continuous headings", said)

    def test_and_a_vectored_approach_still_says_you_navigate(self):
        """The other side, so the guard above cannot be satisfied by refusing
        to vector anybody."""
        from unittest import mock

        from marshall.atc import procedures
        from marshall.core import route as R
        asr = T.approach_of_kind("asr")
        if asr is None:
            self.skipTest(f"{T.name()} publishes no surveillance approach")
        rows = [{"key": "asr", "field": asr.aerodrome.name,
                 "data": R.profile_to_dict(asr)}]
        look_up = procedures.procedure_tools()[0]
        with mock.patch.object(procedures, "_rows", lambda: rows):
            said = look_up(key="asr")
        self.assertIn("continuous headings", said)

    def test_an_unknown_approach_is_NAMED_not_answered_with_nothing(self):
        """`look_up_frequency`'s rule, one axis over: an empty result invites
        the model to fill the silence itself."""
        from unittest import mock

        from marshall.atc import procedures
        look_up = procedures.procedure_tools()[0]
        rows = [{"key": "batumi-ils-13", "field": "Batumi",
                 "data": {"kind": "ils", "runway": "13"}}]
        with mock.patch.object(procedures, "_rows", lambda: rows):
            said = look_up(key="batumi-gca")
        self.assertIn("does not exist", said)
        self.assertIn("batumi-ils-13", said)


if __name__ == "__main__":
    unittest.main()
