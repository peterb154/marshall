"""One frequency, one thing, within a theatre. And every station cites itself.

    "a) make sure that there is no in theater conflicts in the database and
     b) indicate that these are fictional, rather than factual frequencies"

WHY A DUPLICATE IS NOT A TIDINESS PROBLEM. `stations.on_frequency` answers "who
the controller IS on this frequency" by returning the FIRST station that hears
it -- so two facilities sharing a number means one of them can never be reached
and the other answers in his name. It is the same first-match fault as
`station_for("tower")` before the second aerodrome arrived, on the frequency
axis instead of the role axis.

It bites navaids too. The SCR-522 tunes a channel and the ARA-8 HOMES on
whatever it is tuned to, so a controller channel that collides with a beacon
sends a warbird to the wrong field while he is talking to the right controller.
That is exactly what 124.0 was doing: Batumi Approach's warbird channel and
`MG`, Kobuleti's invented 1944 homer, undeclared, in one theatre.

`mission/build.py` had already found the same collision from the other end and
stopped placing the transmitter -- "a pilot on Approach heard a beacon instead
of a controller, and could not be heard by anybody" -- while the theatre file
went on declaring the beacon. Fixed in the mission, still true in the data, and
nothing compared the two lists. Kobuleti has no fictional beacon now. #217
"""
from __future__ import annotations

import unittest

from marshall.core import catalogue

THEATRES = ("caucasus", "nevada")


def _claimed(theatre: str) -> dict[float, list[str]]:
    """Everything in this theatre that owns a frequency, and who owns it."""
    out: dict[float, list[str]] = {}
    for c in catalogue.controllers(theatre):
        out.setdefault(float(c.freq_mhz), []).append(f"{c.name} (primary)")
        for ch in c.channels:
            out.setdefault(float(ch), []).append(f"{c.name} (channel)")
    for f in catalogue.published_fixes(theatre):
        if getattr(f, "freq_mhz", None):
            out.setdefault(float(f.freq_mhz), []).append(
                f"beacon {f.ident or f.name}")
    return out


class AFrequencyNamesOneFacility(unittest.TestCase):

    def test_nothing_in_a_theatre_shares_a_frequency(self):
        for t in THEATRES:
            with self.subTest(theatre=t):
                clash = {k: v for k, v in _claimed(t).items() if len(v) > 1}
                self.assertEqual(
                    clash, {},
                    f"in {t}, one frequency is claimed by more than one thing. "
                    f"`on_frequency` returns the FIRST match, so one of them "
                    f"can never be reached and the other answers in his name.")

    def test_no_two_STATIONS_ever_share_one(self):
        """The hard half, with no baseline. Two facilities on one frequency is
        the `on_frequency` first-match fault and is never acceptable."""
        for t in THEATRES:
            with self.subTest(theatre=t):
                seen: dict[float, str] = {}
                for c in catalogue.controllers(t):
                    for hz in (float(c.freq_mhz), *(float(x) for x in c.channels)):
                        self.assertNotIn(
                            hz, seen,
                            f"{c.name} and {seen.get(hz)} both answer on {hz}")
                        seen[hz] = c.name

    def test_the_check_is_not_vacuous(self):
        """It passes trivially if nothing is loaded. Both maps must be there
        and must actually own frequencies."""
        for t in THEATRES:
            with self.subTest(theatre=t):
                self.assertGreaterEqual(len(_claimed(t)), 10)


class EveryStationSaysWhereItCameFrom(unittest.TestCase):
    """`Fix.source` has been required since #163 -- "a fix nobody can cite is
    one somebody invented" -- and frequencies were left out of it. Batumi APP
    and TWR are published Georgian eAIP values; the Ground seat beside them is
    ours, because the AIP says Batumi HAS no ground controller. Nothing in the
    file said which was which."""

    def test_every_station_cites_something(self):
        for t in THEATRES:
            for c in catalogue.controllers(t):
                with self.subTest(theatre=t, station=c.name):
                    self.assertTrue(
                        (c.source or "").strip(),
                        "a frequency nobody can cite is one somebody invented")

    def test_invented_ones_say_so_in_a_word_you_can_grep_for(self):
        """A reader has to be able to find them. The word is the interface."""
        known = ("PUBLISHED", "FICTION", "UNCITED")
        for t in THEATRES:
            for c in catalogue.controllers(t):
                with self.subTest(theatre=t, station=c.name):
                    self.assertTrue(
                        any(w in c.source for w in known),
                        f"{c.name} does not begin with one of {known}")

    def test_the_published_ones_are_the_two_that_really_are(self):
        """Guards the other direction: if everything drifts to saying
        PUBLISHED the field stops meaning anything. Only Batumi APP and TWR
        appear in the Georgian eAIP."""
        pub = {c.name for c in catalogue.controllers("caucasus")
               if c.source.startswith("PUBLISHED")}
        self.assertEqual(pub, {"Batumi Approach", "Batumi Tower"})


if __name__ == "__main__":
    unittest.main()
