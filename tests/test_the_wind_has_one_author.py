"""The wind a controller SAYS and the wind that chose his runway are one wind.

    "The runway in use is a LIVE fact and the wind spoken beside it is a
     HARD-CODED CONSTANT, in the same sentence."

The runway has had one author since `atis/store.py` was written: ATIS measures
the sim's wind over each field, decides the active end, writes it down, and a
controller ASKS rather than recomputing. The WIND was never rewired. It stayed
`units.WIND_FROM_DEG = 90.0`, a module constant, and it is what got said:

    f"{self._runway_in_use()}, {self._wind_phrase()}"

-- the runway from the observation, the wind from the constant, in one breath.
So Tower could clear an aircraft to land on the runway the measured wind chose
while naming a wind that did not choose it, and the ATIS broadcast and the
landing clearance would disagree about one number at one field on the same
afternoon.

THE SHAPE IS `test_two_fields.py`'s. The wrong answer is always plausible: a
real wind, in the right phraseology, from the right controller, that simply is
not the wind that is blowing. Nothing in the transmission marks it, and reading
the code does not show it either -- it only appears when the weather has moved
since the constant was written, which is a per-mission setting away.

It survived because the declared Caucasus wind has never been far enough off to
flip a runway. That is luck, and this file is what replaces it. See #148.
"""

import unittest
import unittest.mock as mock

from marshall.atc import controller as atc
from marshall.atis import broadcast as B
from marshall.atis import observation as O
from marshall.atis import store
from marshall.core import route as R
from marshall.core import theatre as TH
from marshall.core import units

from tests import theatre as T

# `K = R.KOBULETI_FIELD` at module scope is what took this file down on the
# second map -- the guard for "a wind is a field's and not a theatre's", unable
# to be loaded at the field it would be about.


def K():
    """The departure field, on whichever map is loaded."""
    return T.departure()


def BAT():
    """The arrival field."""
    return T.arrival()


def broadcasting(field=None, runway=None, wind=270, kt=20):
    """An ATIS on the air with weather that is NOT the declared weather.

    Every number here disagrees with the theatre file, which is the whole
    method: if a controller quotes the declaration he is quoting the declared
    wind and the divergence is visible in the transcript. The RUNWAY defaults to
    whichever end this field uses in the westerly above, so the fixture stays a
    fixture about a disagreement rather than about Georgia.
    """
    f = K() if field is None else field
    if isinstance(f, str):
        name, rwy = f, runway
    else:
        name = f.name
        rwy = f.runway_in_use(wind) if runway is None else runway
    return mock.patch.object(
        store, "current",
        return_value=store.Current(field=name, letter="Bravo", runway=rwy,
                                   wind_from_deg=wind, wind_kt=kt,
                                   on_the_air=True))


def tower_at(field_station):
    ctl = atc.Controller(T.the_arrival())
    ctl._me = field_station
    ctl.working = "tower"
    return ctl


class TestOneSentenceCannotCarryTwoWinds(unittest.TestCase):
    """The sharp end, and it has to be behavioural.

    Reading the code shows a runway asked for and a wind read from a constant,
    which looks like two lines rather than a fault. Put weather on the air that
    the constant does not describe and the two halves of one sentence come from
    two different afternoons.
    """

    def test_the_spoken_wind_is_the_one_on_the_air(self):
        ctl = tower_at(T.station("tower", K()))
        with broadcasting():
            said = ctl._wind_phrase()
        self.assertEqual(said, "wind two seven zero at twenty.")
        declared = atc.spell_hdg(int(TH.declared_wind()[0]))
        self.assertNotIn(declared, said,
                         "the controller read the declared wind, not the ATIS")

    def test_the_landing_clearance_names_one_weather(self):
        """The runway and the wind, in one transmission, out of one row."""
        f = K()
        ctl = tower_at(T.station("tower", f))
        ctl.report_beacon("Hoover 1-1", 4000)
        ctl.out.clear()
        with broadcasting():
            ctl.report_landed("Hoover 1-1")
        said = " ".join(t.text for t in ctl.out).lower()
        rwy = atc.spell_rwy(f.runway_in_use(270))
        self.assertIn(f"cleared to land runway {rwy}", said)
        self.assertIn("wind two seven zero at twenty", said)

    def test_the_take_off_clearance_does_too(self):
        f = K()
        ctl = tower_at(T.station("tower", f))
        with broadcasting():
            ctl.request_takeoff("Hoover 1-1")
        said = " ".join(t.text for t in ctl.out).lower()
        self.assertIn(f"runway {atc.spell_rwy(f.runway_in_use(270))}", said)
        self.assertIn("wind two seven zero", said)

    def test_a_wind_is_a_field_and_not_a_theatre(self):
        """A role is only unique within an aerodrome and so is the weather.

        Kobuleti Tower quoting Batumi's observation is the two-fields fault
        wearing weather: a real measurement, from a real ATIS, forty miles from
        the aeroplane he is clearing.
        """
        here, there = K(), BAT()
        if here.name == there.name:
            here, there = T.arrival(), T.other()
        winds = {here.name: (270, 20), there.name: (120, 8)}

        def at(field, fallback_wind_deg=None):
            deg, kt = winds[field.name]
            return store.Current(field=field.name, letter="Bravo",
                                 runway=field.runway_in_use(deg),
                                 wind_from_deg=deg, wind_kt=kt, on_the_air=True)

        with mock.patch.object(store, "current", side_effect=at):
            a = tower_at(T.station("tower", here))._wind_phrase()
            b = tower_at(T.station("tower", there))._wind_phrase()
        self.assertIn("two seven zero", a)
        self.assertIn("one two zero", b)


class TestCalmIsAWordInBothMouths(unittest.TestCase):
    """The broadcast has always known this. The clearance now says it too,
    because both of them ask `Wind.spoken` for the words."""

    def test_the_clearance_says_calm(self):
        ctl = tower_at(T.station("tower", K()))
        with broadcasting(wind=0, kt=0):
            said = ctl._wind_phrase()
        self.assertEqual(said, "wind calm.")

    def test_the_broadcast_and_the_clearance_phrase_one_measurement_alike(self):
        obs = O.observe(K(), 270, 20, 300, 0, 80000, 20.0, 29.92, 29.83)
        spoken = B.spoken(obs, "Bravo", "1200")
        ctl = tower_at(T.station("tower", K()))
        with broadcasting(wind=obs.wind_from_deg, kt=obs.wind_kt):
            said = ctl._wind_phrase()
        self.assertIn(said.rstrip(".").capitalize(), spoken)


class TestWhereTheTrueWindLives(unittest.TestCase):
    """One fact, one author -- and the fallback says that it IS one."""

    def test_the_code_no_longer_declares_a_wind(self):
        """`units.py` is conversions and the atmosphere. A wind is a fact about
        a map, and a map is configuration."""
        self.assertFalse(hasattr(units, "WIND_FROM_DEG"))
        self.assertFalse(hasattr(units, "WIND_MPH"))

    def test_the_published_names_resolve_to_the_theatres_declaration(self):
        """Some three hundred call sites read `R.WIND_*`; they now read the
        theatre file, which is also what `mission/build.py` writes into the
        .miz weather -- so the declared wind is the one the sim then has and
        the one ATIS measures back."""
        deg, mph = TH.declared_wind()
        self.assertEqual(R.WIND_FROM_DEG, deg)
        self.assertEqual(R.WIND_MPH, mph)

    def test_no_broadcast_falls_back_and_says_which_wind_it_is(self):
        """A field with no ATIS is an arrangement, not an error. Presenting the
        declaration as an observation is the error."""
        f = K()
        with mock.patch.object(
                store, "current",
                return_value=store.Current(field=f.name, letter=None,
                                           runway=f.ends[0], on_the_air=False)):
            got = store.wind(f)
        self.assertFalse(got.observed)
        self.assertEqual(got.from_deg, int(TH.declared_wind()[0]))

    def test_an_observed_wind_says_it_was_observed(self):
        with broadcasting():
            got = store.wind(K())
        self.assertTrue(got.observed)
        self.assertEqual((got.from_deg, got.kt), (270, 20))

    def test_a_controller_with_no_field_still_gets_a_wind(self):
        """The engine is blind by design: nobody told it who is speaking. It
        must not answer with an exception on the radio."""
        self.assertFalse(store.wind(None).observed)
        self.assertIn("wind", atc.Controller(T.the_arrival())._wind_phrase())


class TestTheChartAndTheRadioAgree(unittest.TestCase):
    """The failure this project exists to prevent, in its own subject.

    The kneeboard is drawn before anybody starts the sim, so it can only ever
    show the declared wind -- and that is exactly the wind the mission is built
    with, so ATIS measures it back and the broadcast says the same numbers the
    pilot has on his knee.
    """

    @T.skip_unless("caucasus", why="`card.for_caucasus()` is the only card "
                                   "builder there is; the declared wind of "
                                   "another map has no page to be printed on")
    def test_the_card_carries_the_declared_wind(self):
        from marshall.kneeboard import card as C
        got = C.for_caucasus()
        self.assertEqual((got.wind_from_deg, got.wind_mph), TH.declared_wind())

    def test_the_chart_and_the_broadcast_name_one_runway(self):
        deg, mph = TH.declared_wind()
        for f in T.fields():
            obs = O.observe(f, deg, mph / R.MPH_PER_KT, 300, 0, 80000, 20.0,
                            29.92, 29.83)
            with self.subTest(field=f.name):
                self.assertEqual(obs.runway, f.runway_in_use())
                self.assertIn(f"Runway {atc.spell_rwy(f.runway_in_use())} in use",
                              B.spoken(obs, "Alpha", "1200"))

    def test_the_printed_wind_and_the_measured_one_are_the_same_speed(self):
        """Knots on the air, mph on the paper, ONE conversion between them --
        `Wind.mph`. Two of them is how a card and a controller come to disagree
        about a number neither of them got wrong."""
        deg, mph = TH.declared_wind()
        self.assertAlmostEqual(store.wind(None).mph, mph, delta=R.MPH_PER_KT)
        self.assertEqual(store.wind(None).from_deg, int(deg))


class TestTheRunwayInUseHasNoConstantLeft(unittest.TestCase):
    """`runway_in_use()` with no wind given used to mean the Caucasus, on every
    map. Nevada's fields picked their end in a Georgian easterly."""

    def test_an_unasked_wind_is_the_maps_own(self):
        """Every field on the map, and a wind from each end of its own runway --
        the declaration is what an unasked `runway_in_use()` must consult, so
        moving it must move every field."""
        for f in T.fields():
            head = f.ends[0] * 10
            back = (head + 180) % 360
            with (self.subTest(field=f.name, wind=back),
                  mock.patch.object(TH, "declared_wind",
                                    return_value=(float(back), 20.0))):
                self.assertEqual(f.runway_in_use(), f.ends[1])
            with (self.subTest(field=f.name, wind=head),
                  mock.patch.object(TH, "declared_wind",
                                    return_value=(float(head), 5.0))):
                self.assertEqual(f.runway_in_use(), f.ends[0])


if __name__ == "__main__":
    unittest.main()
