"""A paused sim, and why it is the quietest failure this system has.

    "Joining the server doesn't unpause it. We've experienced this before."

Correct, and the repo had the fact written in two places while nothing could
act on it: `deploy_mission.sh` ended by PRINTING "now unpause" at a human, and
the private notes said `SetPaused(false)`. The capability had been sitting in
the vendored proto the whole time. Same shape as every other unwired system
here -- a correct thing nothing reaches.

WHAT MAKES IT NASTY is that a paused server does not look down. There are two
Eval services and only one of them stops:

    HookService.Eval     hook Lua -- DCS, net, Export       answers when paused
    CustomService.Eval   mission Lua -- coord, timer, world HANGS when paused

So `GetMissionName` answers, `GetPaused` answers, the log looks healthy, and
every question Marshall actually asks -- `theatre.verify`, the ATIS weather
observation -- times out. Twice I explained those timeouts as something else
(off-map coordinates; a scripting environment that had not started). Both wrong.

These tests are the cheap half: no sim, no network. They pin the REASONING --
that a timeout gets blamed on a pause when the sim says it is paused, and
explicitly not blamed on the map -- because that is the part that misled a
human reader, and prose in a docstring is not a check.
"""

import unittest

from marshall.core import theatre as T


class _Silent:
    """An eval that never answers, like a paused sim."""

    def __init__(self, delay=30.0):
        self.delay = delay

    def __call__(self, lua):
        import time
        time.sleep(self.delay)
        return ""


class TimeoutIsNotAboutTheMap(unittest.TestCase):
    """A sim that says nothing is not a sim that says the wrong thing."""

    def test_it_actually_gives_up_at_the_timeout(self):
        # THE REGRESSION THIS FILE FOUND. `verify` used a ThreadPoolExecutor in
        # a `with` block, whose exit calls shutdown(wait=True) -- so having given
        # up at `timeout` it then waited for the abandoned call to finish anyway,
        # a full 25 s against a paused sim on every bridge start. The wall clock
        # is the only thing that catches this; the return value was always right.
        import time
        t0 = time.monotonic()
        T.verify(T.nevada(), _Silent(30.0), timeout=0.3)
        took = time.monotonic() - t0
        self.assertLess(took, 5.0,
                        f"verify must abandon a silent sim, not await it "
                        f"(took {took:.1f}s for a 0.3s timeout)")

    def test_timeout_does_not_refuse_the_theatre(self):
        # A controller who cannot reach the sim must still come up and work.
        # Refusing to start on silence would ground the ATC every time the
        # server was paused -- which is after every single deploy.
        ok, why = T.verify(T.nevada(), _Silent(), timeout=0.3)
        self.assertTrue(ok, f"a silent sim must not veto the theatre: {why}")

    def test_timeout_blames_the_pause_when_the_sim_is_paused(self):
        ok, why = T.verify(T.nevada(), _Silent(), timeout=0.3,
                           is_paused=lambda: True)
        self.assertTrue(ok)
        self.assertIn("PAUSED", why)
        # It must say what to DO. The whole failure of the old line was that it
        # described a state and offered no action.
        self.assertIn("unpause", why.lower())

    def test_timeout_says_so_when_the_sim_is_not_paused(self):
        # Not paused and still silent is a different fault, and must not be
        # mislabelled as a pause -- that sends the reader to the wrong place.
        ok, why = T.verify(T.nevada(), _Silent(), timeout=0.3,
                           is_paused=lambda: False)
        self.assertTrue(ok)
        self.assertNotIn("PAUSED", why)
        self.assertIn("running", why)

    def test_a_broken_pause_probe_never_takes_the_bridge_down(self):
        def explode():
            raise RuntimeError("gRPC is unhappy")
        ok, why = T.verify(T.nevada(), _Silent(), timeout=0.3, is_paused=explode)
        self.assertTrue(ok)
        self.assertTrue(why)

    def test_the_map_verdict_still_works_and_still_refuses(self):
        # The pause wiring must not have softened the check it sits next to: a
        # real answer in the wrong place is still a refusal.
        wrong = lambda lua: "36.2910,-107.9750"          # noqa: E731
        ok, why = T.verify(T.caucasus(), wrong, timeout=5.0)
        self.assertFalse(ok)
        self.assertIn("NOT the loaded map", why)

    def test_a_right_answer_confirms(self):
        c = T.caucasus()
        f = next(x for x in c.fields if x.lat or x.lon)
        ok, why = T.verify(c, lambda lua: f"{f.lat:.4f},{f.lon:.4f}", timeout=5.0)
        self.assertTrue(ok)
        self.assertIn("confirmed", why)


class TheDeployUnpauses(unittest.TestCase):
    """The script must DO it, not advise it.

    This is the actual regression. The line it replaces was correct, prominent,
    and inert for as long as the script has existed.
    """

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        self.deploy = (root / "tools" / "deploy_mission.sh").read_text()
        self.sim = root / "tools" / "sim.py"

    def test_deploy_actually_unpauses(self):
        self.assertIn("sim.py", self.deploy,
                      "deploy_mission.sh must unpause, not tell somebody to")
        self.assertIn("unpause", self.deploy)

    def test_the_tool_it_calls_exists(self):
        self.assertTrue(self.sim.is_file(), "deploy calls tools/sim.py; it must exist")

    def test_sim_tool_offers_the_three_verbs(self):
        text = self.sim.read_text()
        for verb in ("status", "unpause", "pause"):
            self.assertIn(f'"{verb}"', text)


class SetPausedWaits(unittest.TestCase):
    """`SetPaused` returns before the state changes, and the read-back must wait.

    The first version of `set_paused` read `GetPaused` in the next breath and
    reported "sim is now PAUSED" having just successfully unpaused the server.
    A verify that runs before the thing it verifies reports failure on success,
    which teaches the next person to distrust the check instead of the state.
    """

    def test_it_polls_until_the_state_matches(self):
        import inspect
        from marshall.feed import dcs
        src = inspect.getsource(dcs.set_paused)
        self.assertIn("while True", src, "must poll, not read once")
        self.assertIn("deadline", src, "must give up rather than hang forever")

    def test_readiness_is_the_mission_state_not_the_flag(self):
        # `is_paused` is the flag; `mission_lua_ready` is whether a controller
        # can ask the sim anything. They answer different questions and the
        # second is the one callers care about.
        from marshall.feed import dcs
        self.assertTrue(callable(dcs.is_paused))
        self.assertTrue(callable(dcs.mission_lua_ready))
        self.assertIn("custom", inspect_source(dcs.mission_lua_ready).lower())


def inspect_source(fn) -> str:
    import inspect
    return inspect.getsource(fn)


class ComposeDsnSurvivesABindAddress(unittest.TestCase):
    """The bridge finds Postgres by reading the compose file, and a bind
    address in the port mapping must not hide it.

    A SECURITY FIX BROKE THE RADIO, briefly, and this is the guard. Binding the
    database to loopback changed `"5432:5432"` to `"127.0.0.1:5432:5432"`; the
    pattern that discovers the port did not allow for an address, returned no
    match, and the bridge came up with no Postgres at all -- no ATIS letter, no
    runway in use, no board. The only symptom would have been "PUBLISH FAILED"
    on every recording, which is exactly the class of silent degradation this
    repo keeps finding.
    """

    def _dsn_from(self, mapping: str) -> str:
        import importlib.util as iu
        import tempfile
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        spec = iu.spec_from_file_location("_b", root / "tools" / "bridge.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "services").mkdir()
            (Path(d) / "services" / "docker-compose.yml").write_text(
                "services:\n  db:\n    environment:\n"
                "      POSTGRES_USER: strands\n"
                "      POSTGRES_PASSWORD: strands\n"
                "      POSTGRES_DB: strands\n"
                f"    ports:\n      - {mapping}\n")
            mod.ROOT = Path(d)
            return mod._compose_dsn()

    def test_a_loopback_bound_port_is_still_found(self):
        self.assertIn("localhost:5432", self._dsn_from('"127.0.0.1:5432:5432"'))

    def test_a_bare_mapping_still_works(self):
        self.assertIn("localhost:5432", self._dsn_from('"5432:5432"'))

    def test_a_moved_host_port_is_honoured(self):
        self.assertIn("localhost:15432", self._dsn_from('"127.0.0.1:15432:5432"'))

    def test_the_real_compose_file_yields_a_usable_dsn(self):
        # The one that would actually have caught it: read what ships.
        import importlib.util as iu
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        spec = iu.spec_from_file_location("_b2", root / "tools" / "bridge.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        dsn = mod._compose_dsn()
        self.assertTrue(dsn.startswith("postgresql://"), f"no DSN found: {dsn!r}")
        self.assertIn("@localhost:", dsn)

if __name__ == "__main__":
    unittest.main()
