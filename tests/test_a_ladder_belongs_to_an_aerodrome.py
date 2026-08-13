"""Who works Tower is a question about an AERODROME, and it was asked of a
constant. [#162]

    src/marshall/core/approach.py    fld = ARRIVAL_FIELD

`ladder_station` answers "who works this phase of the arrival". The arrival
happens at one specific aerodrome, the procedure has been holding that
aerodrome all along in `self.aerodrome`, and the field it asked about was
whichever one `config/theatres/<map>.toml` happens to call the arrival. The
comment directly above the line made the correct argument -- "AT THE ARRIVAL
FIELD, and the qualifier is not decoration" -- and then supplied the wrong
aerodrome. A comment that corrects its own code.

What it cost, measured on the tree before the fix:

    Caucasus   KOBULETI_ILS.station() -> ('Batumi Tower', 118.6)
               and on the air, to an aeroplane recovering at KOBULETI:

                 Sockeye, Kobuleti Departure, report INITIAL.
                 At INITIAL contact Batumi Tower one one eight decimal six.

               Perfect phraseology, a real controller, a real frequency, forty
               miles up the coast from the runway he is landing on.

    Nevada     no field is named Batumi, so `station_for` matched nothing and
               the `or seats[0]` fallback fired. BOTH procedures answered
               ('Nellis Clearance', 120.9) -- every landing clearance on the
               map stamped with a GROUND DELIVERY position's frequency, and
               Tonopah's arrivals given a facility 124 nm away.

The wrong answer is never nonsense in this failure shape, which is why it needs
a test rather than a reading: it is a real seat on a real frequency belonging
to the wrong airport.

THE TESTS THAT MATTER ARE THE ONES ABOUT AN EMPTY FIELD. Removing the constant
only moves the fault if something else quietly supplies a default, so the
contract is that no aerodrome means NO ANSWER -- #109's rule, that a picture
with no origin renders nothing rather than a guess.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.atc import controller as C
from marshall.core import catalogue
from marshall.core import route as R
from marshall.core import theatre as TH
from marshall.core.approach import ladder_station


def _laddered(theatre: str = ""):
    """Every procedure on this map whose controllers live on the LADDER.

    The 1944 letdown is excluded by `theatre_stations`, and correctly: there
    the man you talk to IS the beacon you are homing, so his frequency comes
    off the fix and not off a comms ladder at all (#152).
    """
    return {k: p for k, p in TH.approaches_now(theatre).items()
            if p.theatre_stations}


class TestAProcedureNamesItsOwnFieldsTower(unittest.TestCase):
    """The headline. Every procedure, on whichever map is configured."""

    def test_the_landing_station_sits_at_the_procedures_own_aerodrome(self):
        for key, p in sorted(_laddered().items()):
            with self.subTest(procedure=key, aerodrome=p.aerodrome.name):
                name, freq = p.station()
                seat = TH.station_on(freq)
                self.assertIsNotNone(seat, f"{name} is on nobody's frequency")
                # The fix catalogue shouts its names ('BATUMI') and the
                # aerodrome rows do not ('Batumi'); `field_named` is the join.
                fld = TH.current().field_named(p.aerodrome.name)
                self.assertIsNotNone(fld, "a procedure arrives somewhere")
                self.assertEqual(fld.name, seat.field,
                                 "a real controller at the wrong airport is "
                                 "the whole failure shape")

    def test_and_he_works_the_runway_rather_than_the_paperwork(self):
        """`or seats[0]` is what read a clearance-delivery position out as the
        tower to call at the missed approach point. Whoever is listed first is
        not a fact about who works an arrival."""
        for key, p in sorted(_laddered().items()):
            with self.subTest(procedure=key):
                seat = TH.station_on(p.station()[1])
                self.assertIn("tower", (seat.role, *seat.also),
                              f"{seat.name} does not own the runway")

    def test_the_enroute_seat_is_the_region_controller_wherever_he_is(self):
        """The other half, and it must NOT move: a Center owns a region and is
        reachable from any field on the map, so qualifying the lookup by
        aerodrome is not allowed to lose him."""
        for key, p in sorted(_laddered().items()):
            for phase in ({"enroute": True}, {"banished": True}):
                with self.subTest(procedure=key, **phase):
                    seat = TH.station_on(p.station(**phase)[1])
                    self.assertEqual("", seat.field,
                                     "a Center belongs to no aerodrome")


class TestNoAerodromeMeansNoAnswer(unittest.TestCase):
    """The contract that stops the constant coming back as a default."""

    def test_an_unnamed_field_is_not_answered_at_all(self):
        for phase in ({}, {"enroute": True}, {"banished": True}):
            with self.subTest(**phase):
                self.assertIsNone(ladder_station("", **phase))

    def test_nor_is_a_field_this_map_has_never_heard_of(self):
        """Not with somebody else's Tower, which is what first-match gives.
        A name no station carries must match no station."""
        self.assertIsNone(ladder_station("Farnborough"))

    def test_a_field_that_exists_is_answered_with_its_own_seats(self):
        for fld in TH.fields_now():
            with self.subTest(field=fld.name):
                got = ladder_station(fld.name)
                if got is None:
                    continue            # a field this map staffs no Tower at
                self.assertEqual(fld.name, TH.station_on(got[1]).field)

    def test_the_aerodromes_own_spelling_is_not_required(self):
        """The two catalogues disagree about case -- the fixes are shouted and
        the aerodrome rows are not -- and `Station.field` is matched exactly.
        Handing the fix's spelling straight through matched no seat at all,
        which is the same wrong answer arrived at from the other side."""
        for fld in TH.fields_now():
            with self.subTest(field=fld.name):
                self.assertEqual(ladder_station(fld.name),
                                 ladder_station(fld.name.upper()))


class TestTheRecoveryFieldIsNamedOnTheAir(unittest.TestCase):
    """The transmission, not the lookup. This is what a pilot heard."""

    def _greeting(self, profile, seat):
        c = C.Controller(profile)
        c._me = seat
        c.get("Sockeye").sortie_phase = "arrival"
        c.check_in("Sockeye")
        return " ".join(t.text for t in c.take_out())

    @unittest.skipUnless(TH.current().field_named("Kobuleti"),
                         "the Kobuleti recovery is a Caucasus sortie")
    def test_a_kobuleti_recovery_is_not_sent_to_batumi_tower(self):
        """Measured before the fix, word for word:

            Sockeye, Kobuleti Departure, report INITIAL.
            At INITIAL contact Batumi Tower one one eight decimal six.
        """
        p = dataclasses.replace(R.KOBULETI_ILS, arrival_fix=R.INITIAL)
        said = self._greeting(p, R.station_for("departure", field="Kobuleti"))
        self.assertIn("report INITIAL", said)
        self.assertIn("At INITIAL contact Kobuleti Tower", said)
        self.assertNotIn("Batumi", said)

    def test_the_landing_clearance_goes_out_on_his_own_towers_channel(self):
        """`Controller.say` picks the channel off this same answer, so the
        wrong field here is not a mis-phrasing -- the aeroplane on short final
        does not hear it at all."""
        for key, p in sorted(_laddered().items()):
            with self.subTest(procedure=key):
                c = C.Controller(p)
                c.check_in("Sockeye")
                c.report_landed("Sockeye")
                tx = [t for t in c.out if "cleared to land" in t.text]
                self.assertTrue(tx, "he is cleared to land")
                fld = TH.current().field_named(p.aerodrome.name)
                self.assertEqual(fld.name, TH.station_on(tx[-1].freq_mhz).field)


class TestTheOtherMapWasWorseAndSilent(unittest.TestCase):
    """Nevada, where nothing is named Batumi so the fallback fired instead.

    Switched here rather than left to `MARSHALL_THEATRE`, because the whole
    point is that this was invisible on the map the suite is run on.
    """

    def setUp(self):
        self._env = mock.patch.dict(os.environ,
                                    {"MARSHALL_THEATRE": "nevada"})
        self._env.start()
        catalogue.reload()
        self.addCleanup(catalogue.reload)
        self.addCleanup(self._env.stop)

    def test_neither_nevada_procedure_answers_with_clearance_delivery(self):
        """Both used to return ('Nellis Clearance', 120.9) -- the seat that
        reads you a clearance on the ramp, named as the man to call at the
        missed approach point, on both procedures at once."""
        for key, p in sorted(_laddered("nevada").items()):
            with self.subTest(procedure=key):
                self.assertNotEqual("Nellis Clearance", p.station()[0])

    def test_tonopah_is_answered_by_silverbow_and_nellis_by_nellis(self):
        """124 nm apart. The named numbers are the published ones."""
        want = {"nellis-ils": ("Nellis Tower", 132.55),
                "tonopah-ils": ("Silverbow Tower", 124.75)}
        got = {k: p.station() for k, p in _laddered("nevada").items()}
        self.assertEqual(want, {k: v for k, v in got.items() if k in want})


if __name__ == "__main__":
    unittest.main()
