"""The monitor picked one transmit channel and used it for everybody.

`asr_monitor` computed this once, at thread start:

    _final = (role_at(seats, "approach", arrival_field)
              if profile.guidance == "talkdown"
              else role_at(seats, "tower", arrival_field))
    final_hz = _final.freq_mhz * 1_000_000

`profile` is the bridge's and `arrival_field` is the loaded theatre's -- and
that number was then used inside a loop that runs PER AIRCRAFT, for the mile
calls, the landing-clearance relay, the goodbye, and every free-channel check
ahead of them.

So the question "which frequency does this man's final controller work on" had
one answer for everybody on the board. The wrong one is a real frequency
belonging to a real controller: a Viper recovering to one field hears his mile
calls on the other field's approach channel, or hears nothing at all because
the 1944 letdown the bridge happened to be started on staffs no ladder.

THE SAME FAULT AS #150's OTHER SEVEN SITES and deliberately not fixed with
them, because it is a different shape -- a transmit channel chosen before any
aeroplane is in scope, rather than a lookup handed the wrong argument. It got
its own issue and its own criteria instead of being folded in. [#173]
"""

from __future__ import annotations

import dataclasses
import unittest

from marshall.atc import agent_atc as A
from marshall.atc import controller as C
from marshall.core import theatre as T
from tests import theatre as TH


class Bridge:
    """Just enough of one: who was heard on which frequency."""

    def __init__(self, heard=None):
        self.heard_on = dict(heard or {})


def controller_on(profile):
    c = C.Controller(profile)
    c._me = TH.station("approach", TH.arrival())
    return c


def hz_of(role: str, field) -> float:
    st = TH.station(role, field)
    return st.freq_mhz * 1_000_000


class TestTheChannelIsTheAEROPLANES(unittest.TestCase):

    def setUp(self):
        self.ils = TH.the_ils(TH.arrival())
        if self.ils is None:
            self.skipTest(f"{TH.name()} publishes no ILS at its arrival")
        self.talkdown = dataclasses.replace(self.ils, guidance="talkdown")

    def test_an_ILS_goes_out_on_TOWERS_channel(self):
        """He has his own aid and Tower genuinely takes him at the intercept."""
        ctl = controller_on(self.ils)
        ctl.bind("Viper 1", track="Viper 1")
        b = Bridge({ctl._resolve("Viper 1"): hz_of("approach", TH.arrival())})
        self.assertEqual(A.final_channel(b, ctl, self.ils, "Viper 1", 0.0),
                         hz_of("tower", TH.arrival()))

    def test_a_TALKDOWN_goes_out_on_APPROACHS(self):
        """The radar controller flies the approach, so his channel carries the
        conversation, the vectors and the mile calls. Splitting them was
        reported as "two personalities" -- two halves of one controller across
        two radios."""
        ctl = controller_on(self.ils)
        ctl.bind("Mustang 2", track="Mustang 2")
        ctl.get("Mustang 2").profile = self.talkdown
        b = Bridge({ctl._resolve("Mustang 2"): hz_of("approach", TH.arrival())})
        self.assertEqual(A.final_channel(b, ctl, self.ils, "Mustang 2", 0.0),
                         hz_of("approach", TH.arrival()))

    def test_ONE_BRIDGE_GIVES_BOTH_ANSWERS(self):
        """The issue in one assertion. Before this, both aircraft got whichever
        channel the thread computed at start-up."""
        ctl = controller_on(self.ils)          # the bridge is on the ILS
        for cs in ("Viper 1", "Mustang 2"):
            ctl.bind(cs, track=cs)
        ctl.get("Mustang 2").profile = self.talkdown
        app = hz_of("approach", TH.arrival())
        b = Bridge({ctl._resolve("Viper 1"): app,
                    ctl._resolve("Mustang 2"): app})
        viper = A.final_channel(b, ctl, self.ils, "Viper 1", 0.0)
        mustang = A.final_channel(b, ctl, self.ils, "Mustang 2", 0.0)
        self.assertNotEqual(viper, mustang,
                            "two aircraft on two procedures share one channel")
        self.assertEqual(viper, hz_of("tower", TH.arrival()))
        self.assertEqual(mustang, app)


class TestAndItIsHisFIELDToo(unittest.TestCase):
    """The other half, and the one a single-aerodrome map cannot show.

    The old code asked for a seat at `theatre.current().arrival` whatever the
    aeroplane was doing -- so on a two-field map a departure recovering to the
    OTHER aerodrome had his mile calls put on the arrival field's channel. A
    real controller, a real frequency, the wrong airport: the shape
    `station_for`, `channels_for` and `field_origin` all had.
    """

    def setUp(self):
        if len(list(T.fields_now())) < 2:
            self.skipTest(f"{TH.name()} works one aerodrome")
        self.ils = TH.the_ils(TH.arrival())
        if self.ils is None:
            self.skipTest("no ILS at the arrival field")

    def test_a_man_worked_at_the_OTHER_field_gets_that_fields_channel(self):
        other = TH.other()
        tower_there = TH.station("tower", other)
        if tower_there is None:
            self.skipTest(f"{other.name} publishes no tower")
        ctl = controller_on(self.ils)
        ctl.bind("Away 1", track="Away 1")
        # He checked in on the OTHER field's approach frequency, which is the
        # only thing that says whose aeroplane he is.
        st = TH.station("approach", other) or TH.station("departure", other)
        if st is None:
            self.skipTest(f"{other.name} publishes no terminal seat")
        b = Bridge({ctl._resolve("Away 1"): st.freq_mhz * 1_000_000})
        got = A.final_channel(b, ctl, self.ils, "Away 1", 0.0)
        self.assertEqual(got, tower_there.freq_mhz * 1_000_000)
        self.assertNotEqual(got, hz_of("tower", TH.arrival()),
                            "he got the arrival field's tower while being "
                            "worked at the other aerodrome")


class TestTheBlindCasesAreHonest(unittest.TestCase):
    """What it answers when it cannot answer, which is most of a sortie."""

    def setUp(self):
        self.ils = TH.the_ils(TH.arrival())
        if self.ils is None:
            self.skipTest("no ILS at the arrival field")

    def test_a_man_on_a_frequency_NOBODY_WORKS_gets_it_back(self):
        """Not another aerodrome's. A guess that names a real controller at the
        wrong airport is worse than the frequency in front of you.

        The frequency has to be one no station holds, and the first version of
        this test used 124.0 -- which IS Batumi Approach. So the fallback never
        ran: `his_field` resolved a real field from it and the answer was that
        field's tower, correctly. The test was wrong and the code was right,
        which is the only way round worth having.
        """
        ctl = controller_on(self.ils)
        want = 199_900_000.0
        from marshall.core import theatre as _t
        if _t.station_on(want / 1_000_000) is not None:
            self.skipTest("199.9 is a real station on this map")
        self.assertEqual(A.final_channel(Bridge(), ctl, self.ils, "Ghost 9",
                                         want), want)

    def test_a_procedure_that_staffs_no_ladder_falls_back(self):
        """A 1944 letdown answers None for every role -- `theatre_stations` is
        False -- and the honest answer is the channel he called on rather than
        a seat from a ladder his procedure does not use."""
        letdown = TH.letdown()
        if letdown is None or getattr(letdown, "theatre_stations", True):
            self.skipTest("this map's letdown is on the ladder")
        ctl = controller_on(self.ils)
        ctl.bind("Mustang 3", track="Mustang 3")
        ctl.get("Mustang 3").profile = letdown
        want = 124_000_000.0
        b = Bridge({ctl._resolve("Mustang 3"): hz_of("approach", TH.arrival())})
        self.assertEqual(
            A.final_channel(b, ctl, self.ils, "Mustang 3", want), want)


class TestTheMonitorNoLongerHoldsOneChannelForEverybody(unittest.TestCase):
    """The source-level claim, because the loop itself needs a radio to run.

    `asr_monitor` transmits, polls radar and holds a lock; the per-aircraft
    branch cannot be reached in a unit test. So this pins the shape that would
    silently regress -- a `final_hz` computed once and closed over.
    """

    def monitor(self):
        """`asr_monitor` is a CLOSURE inside `_run_srs`, not a module
        attribute -- it needs the radio, the pool and the session that enclose
        it. So it is found by parsing the module file.

        THE FILE, not `inspect.getsource` of the parent. The first version ran
        the parent's source through `inspect.cleandoc`, which strips leading
        whitespace from every line after the first -- that is what it is for,
        on DOCSTRINGS -- and flattened the body into an IndentationError.
        """
        import ast
        import pathlib
        src = pathlib.Path(A.__file__).read_text()
        return next(n for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.FunctionDef) and n.name == "asr_monitor")

    def test_nothing_binds_a_thread_wide_final_channel(self):
        """ASSERTED ON THE TREE, not on the text.

        The first version searched the source for `final_hz = ` and failed --
        because that is a substring of `_final_hz = `, which is the per-aircraft
        binding this whole change introduces. Three naive substring checks have
        misfired in this session for the same reason: a string that appears in
        the fix as well as in the fault cannot tell them apart.

        What is actually meant is structural: no statement in the function's
        OWN body -- outside the per-aircraft loop -- may bind a transmit
        channel for everybody.
        """
        import ast
        fn = self.monitor()
        bound = set()
        for node in fn.body:        # direct children only: the thread's scope
            if isinstance(node, ast.Assign):
                bound |= {x.id for x in node.targets if isinstance(x, ast.Name)}
        self.assertNotIn("final_hz", bound,
                         "asr_monitor binds one transmit channel for the whole "
                         "thread again")
        self.assertNotIn("_final_hz", bound)

    def test_the_per_aircraft_one_is_asked_inside_the_loop(self):
        import ast
        fn = self.monitor()
        loop = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
                    and [e.id for e in n.target.elts
                         if isinstance(e, ast.Name)] == ["cs", "pos", "scope"])
        first = ast.unparse(loop.body[0])
        self.assertIn("final_channel(bridge, ctl, profile, cs, freq_hz)", first,
                      "the channel is not resolved at the TOP of the "
                      "per-aircraft loop, so something above it may transmit "
                      "on the thread's own guess")


if __name__ == "__main__":
    unittest.main()
