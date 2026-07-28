"""The GUID -> name roster, and the silent death that froze it.

The strongest identity evidence in the system is the RADIO'S NAME matched
against the name radar prints -- a chain with no microphone in it (identity.py,
[ARCH-2] / #40). It only works if the bridge knows what the radios are called.

It did not. `create_connection(host, port, timeout=10)` leaves that timeout on
the socket, `_drain_tcp` blocks on recv, and a frequency with nobody joining is
quiet for far longer than ten seconds. The timeout raised, the loop caught it as
an OSError and exited, and from that moment every client was a six-character
GUID stub forever.

Nothing failed. Calls kept working, the controller kept talking, and identity
quietly fell through to weaker evidence on every single transmission. Measured
before the fix: a fresh client learned a late joiner in two seconds, and one
that had been quiet for twenty never learned it at all. After: the live bridge
records "Hoover" where it used to record "395CQc".
"""

import threading
import unittest

from marshall.srs.client import SRSClient


class FakeSocket:
    """Enough of a socket to drive the drain loop, and nothing more."""

    def __init__(self, script):
        self.script = list(script)
        self.reads = 0

    def recv(self, _n):
        self.reads += 1
        if not self.script:
            return b""
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def drain(script, stop_after=None):
    c = SRSClient("localhost", name="test")
    c.tcp = FakeSocket(script)
    if stop_after is not None:
        # Let the loop run, then ask it to stop, so a script that never ends
        # cannot hang the suite.
        threading.Timer(stop_after, c._stop.set).start()
    c._drain_tcp()
    return c


class TestQuietIsNotAFailure(unittest.TestCase):
    def test_a_timeout_does_not_end_roster_tracking(self):
        """A quiet frequency is the NORMAL state, not a reason to stop
        listening. Treating it as one is what killed this for a fortnight."""
        line = b'{"Clients":[{"ClientGuid":"abc","Name":"Sockeye"}]}\n'
        c = drain([TimeoutError(), TimeoutError(), line])
        self.assertEqual(c.roster.get("abc"), "Sockeye")

    def test_names_learned_after_a_quiet_spell_still_arrive(self):
        """The late joiner: the case that decides whether a second pilot is
        ever identified by his radio."""
        first = b'{"Clients":[{"ClientGuid":"a","Name":"Hoover"}]}\n'
        later = b'{"Clients":[{"ClientGuid":"b","Name":"Andre"}]}\n'
        c = drain([first] + [TimeoutError()] * 5 + [later])
        self.assertEqual(sorted(c.roster.values()), ["Andre", "Hoover"])


class TestItNeverStopsSILENTLY(unittest.TestCase):
    """When it does stop, the system does not fail -- it keeps working with
    worse evidence, which is the failure mode nobody catches."""

    def test_a_closed_connection_is_recorded(self):
        c = drain([b""])
        self.assertIn("closed", c.roster_ended)

    def test_a_real_error_is_recorded_with_its_reason(self):
        c = drain([ConnectionResetError("reset by peer")])
        self.assertIn("ConnectionResetError", c.roster_ended)

    def test_a_healthy_client_reports_nothing(self):
        c = SRSClient("localhost", name="test")
        self.assertEqual(c.roster_ended, "")


class TestAStubIsNotAName(unittest.TestCase):
    def test_an_unknown_guid_falls_back_to_a_stub(self):
        c = SRSClient("localhost", name="test")
        self.assertEqual(c.name_for("QZmPRAxxxxxxxxxxxxxxxx"), "QZmPRA")

    def test_a_known_guid_gives_the_name(self):
        c = SRSClient("localhost", name="test")
        c.roster["g"] = "Hoover"
        self.assertEqual(c.name_for("g"), "Hoover")


class TestTheConnectTimeoutIsCleared(unittest.TestCase):
    def test_the_source_clears_it(self):
        """A static check, because exercising it needs a live SRS server.

        create_connection's timeout is meant to bound the CONNECT; leaving it on
        the socket turns every quiet spell into an exception in the drain loop.
        """
        import inspect

        src = inspect.getsource(SRSClient.connect)
        self.assertIn("settimeout(None)", src,
                      "the connect timeout must be cleared or a quiet "
                      "frequency raises in _drain_tcp")


if __name__ == "__main__":
    unittest.main()
