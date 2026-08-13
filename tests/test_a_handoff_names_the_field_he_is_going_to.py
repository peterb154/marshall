"""A Center is fieldless on purpose, and it was the field the handoff read.
[#162 #51]

    src/marshall/atc/handoff.py
        nxt = _route.station_for(rule.to, field=getattr(me, "field", ""), ...)

`me` is the controller the pilot is with NOW, and a role is unique only within
an aerodrome -- which is why `station_for` takes a field at all. Center and
Sentry carry no field, deliberately: `test_two_fields` asserts it and calls it
correct, because owning a region is not owning an aerodrome. So the one row
this whole table exists for,

    Rule("center", "approach", "inbound_within", CENTER_NM)

-- the row added after a pilot sat at 44 nm with nothing able to move him off
Center and declared an emergency to get out of it (#51) -- was the one row
asked with no field at all, and fell out to first-match.

Measured on the tree before the fix:

    Nevada     inbound to TONOPAH at 20 nm
                 -> "contact Nellis Approach one one eight decimal one two five"
               Nellis is 124 nm away. He changes frequency and talks to nobody
               who can see him.

    Caucasus   inbound to KOBULETI at 20 nm
                 -> "contact Batumi Approach one two four decimal four two five"
               correct: Kobuleti Departure 123.300, who wears the approach hat
               at his own field.

The Caucasus half is invisible on the default sortie for a reason worth
remembering: Batumi Approach is the only seat on that map whose PRIMARY role is
`approach`, so `role_at`'s primary-first search happens to return the right man.
An accident, and the second recovery field is what turns it back into a bug.

The destination was never missing. `due` is handed the profile, and a
procedure's `aerodrome` is the field it arrives at. It simply was not consulted.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.atc import handoff as H
from marshall.core import catalogue
from marshall.core import route as R
from marshall.core import theatre as TH

INBOUND = H.State(on_ground=False, range_nm=20.0, inbound=True)


def _field_of(profile):
    return TH.current().field_named(profile.aerodrome.name)


def _laddered(theatre: str = ""):
    """The procedures whose controllers live on the comms ladder.

    The 1944 letdown staffs no seats at all -- there the man you talk to IS the
    beacon you are homing -- so `station_for` yields nothing for it and no
    handoff is due. That is #152 and is correct; it is excluded here rather
    than asserted about.
    """
    return {k: p for k, p in TH.approaches_now(theatre).items()
            if p.theatre_stations}


class TestCenterHandsHimToHisOwnDestination(unittest.TestCase):
    """Over every procedure the configured map publishes."""

    def setUp(self):
        self.center = R.station_for("center")
        self.assertEqual("", self.center.field,
                         "a Center owns a region, and that is not a defect")

    def test_the_approach_he_is_given_works_the_field_he_is_landing_at(self):
        for key, p in sorted(_laddered().items()):
            with self.subTest(procedure=key, arriving=p.aerodrome.name):
                v = H.due(p, self.center, INBOUND)
                self.assertTrue(v, "twenty-five miles out is Approach's")
                self.assertEqual(_field_of(p).name, v.station.field)

    def test_and_it_is_a_seat_that_actually_works_approaches(self):
        """At a field where Approach and Departure are one man, asking for
        `approach` must find him by his `also` rather than not at all."""
        for key, p in sorted(_laddered().items()):
            with self.subTest(procedure=key):
                seat = H.due(p, self.center, INBOUND).station
                self.assertIn("approach", (seat.role, *seat.also))


class TestASeatWithAFieldStillWins(unittest.TestCase):
    """The destination is the FALLBACK, not the answer. A departing aeroplane
    is not handed to the arrival field's controller because that is where he is
    eventually going -- his current seat names his aerodrome and it wins."""

    def test_a_departure_is_handed_on_by_his_own_field(self):
        out = H.State(on_ground=False, range_nm=40.0, inbound=False)
        for key, p in sorted(_laddered().items()):
            for me in TH.stations_now():
                if not me.field or "tower" not in (me.role, *me.also):
                    continue
                with self.subTest(procedure=key, seat=me.name):
                    v = H.due(p, me, out)
                    if not v:
                        continue
                    self.assertIn(v.station.field, (me.field, ""),
                                  "his own field's next rung, or the region")

    def test_nothing_is_invented_when_neither_names_a_field(self):
        """No seat, no procedure, no aerodrome. The lookup goes back to being
        unqualified rather than acquiring a default from somewhere."""
        self.assertEqual("", H._at(R.station_for("center"), None))
        self.assertEqual("", H._at(None, None))

    def test_a_name_no_aerodrome_carries_resolves_to_no_field(self):
        """Rather than to itself, which would match no seat and fire no
        handoff at all -- #51 again, arrived at from the safe-looking side."""
        class _Nowhere:
            aerodrome = type("F", (), {"name": "Farnborough"})()
        self.assertEqual("", H._at(R.station_for("center"), _Nowhere()))


class TestTheTwoCataloguesDisagreeAboutCapitals(unittest.TestCase):
    """`field_named` is the join between a Fix and an aerodrome, and there were
    two of it. The module function matched exactly and `Theatre.field_named`
    folded case, so which answer you got depended on which one you called --
    and a procedure's datum is a Fix, so on the Caucasus it was None."""

    def test_a_shouted_fix_name_finds_its_aerodrome(self):
        for f in TH.fields_now():
            with self.subTest(field=f.name):
                self.assertIs(f, R.field_named(f.name.upper()))
                self.assertIs(f, R.field_named(f.name.lower()))

    def test_and_the_two_joins_now_agree(self):
        for name in ("BATUMI", "Batumi", "NELLIS", "Tonopah", "", "nowhere"):
            with self.subTest(name=name):
                self.assertIs(TH.current().field_named(name),
                              R.field_named(name))


class TestTonopahIsNotWorkedFromNellis(unittest.TestCase):
    """The map where it is live today, switched here rather than left to
    `MARSHALL_THEATRE` -- being invisible on the map the suite runs on is the
    whole reason this survived."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"MARSHALL_THEATRE": "nevada"})
        self._env.start()
        catalogue.reload()
        self.addCleanup(catalogue.reload)
        self.addCleanup(self._env.stop)

    def test_an_arrival_at_tonopah_is_given_silverbow(self):
        v = H.due(TH.approaches_now("nevada")["tonopah-ils"],
                  R.station_for("center"), INBOUND)
        self.assertEqual(("Silverbow Approach", 119.45),
                         (v.station.name, v.station.freq_mhz))

    def test_and_nellis_still_keeps_its_own(self):
        """The half that was right by accident must stay right."""
        v = H.due(TH.approaches_now("nevada")["nellis-ils"],
                  R.station_for("center"), INBOUND)
        self.assertEqual(("Nellis Approach", 118.125),
                         (v.station.name, v.station.freq_mhz))


if __name__ == "__main__":
    unittest.main()
