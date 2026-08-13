"""`look_up_frequency` reads the map the controller is sitting on.

    tool  "There is no Tonopah tower position on the published list. Fields
           published: Batumi, Kobuleti."

Asked by NELLIS TOWER, on Nevada, about an aerodrome twenty minutes up the road.
`approaches` accumulates a row per procedure per theatre and nothing ever clears
them, and the query took ONE of them -- `ORDER BY name`, `fetchone` -- which is
`batumi-asr`, written 25 July. Ask the same seat for `position="ground"` and he
was read two Georgian frequencies in correct phraseology.

A profile is a PROCEDURE; the station list is the MAP's. So "which of these
lists is mine" has an exact answer and it is not alphabetical: the one that
names the seat doing the asking. The seat comes from the bridge, which resolved
it from the frequency, which is the one fact about a transmission no pilot can
influence.

AND THE SOURCE WAS GONE, which was the other half. #162 took the station list
off `ApproachProfile` and gave it to the theatre; `profile_to_dict` is `asdict`,
so no row written after it carried one. The writer is `push_stations` now and
the reader is the `stations` table, which a push REPLACES -- so the several
lists this file was written against are one list, and the question changes shape
without changing answer:

    was    which of these accumulated lists is mine?  (the alphabetically first
           is `batumi-asr`, and that is how Nevada got Georgia)
    is     does the one published list name me at all?

The second is not ceremony. `set_stations` refuses an EMPTY push, deliberately,
so a bridge that could not build a list leaves the last good one alone -- which
means the table can still hold the previous run's map, and the check is the only
thing between that and a Nevada controller reading Georgian frequencies again.

The fixtures are the live seats, trimmed to the fields the tool reads.
"""

import unittest
import unittest.mock as mock
from pathlib import Path

from marshall.atc import frequencies as F


def _st(name, field, role, mhz, also=()):
    return {"name": name, "field": field, "role": role, "freq_mhz": mhz,
            "also": list(also)}


CAUCASUS = [
    _st("Kobuleti Clearance", "Kobuleti", "clearance", 125.1, ("delivery",)),
    _st("Kobuleti Ground", "Kobuleti", "ground", 121.8),
    _st("Kobuleti Tower", "Kobuleti", "tower", 133.0),
    _st("Kobuleti Departure", "Kobuleti", "departure", 123.3, ("approach",)),
    _st("Georgia Center", "", "center", 139.0),
    _st("Batumi Approach", "Batumi", "approach", 124.425, ("departure",)),
    _st("Batumi Tower", "Batumi", "tower", 118.6),
    _st("Batumi Ground", "Batumi", "ground", 121.9),
    _st("Sentry", "", "overlord", 131.0),
]

NEVADA = [
    _st("Nellis Clearance", "Nellis", "clearance", 120.9, ("delivery",)),
    _st("Nellis Ground", "Nellis", "ground", 121.8),
    _st("Nellis Tower", "Nellis", "tower", 132.55),
    _st("Nellis Departure", "Nellis", "departure", 135.1),
    _st("Nellis Approach", "Nellis", "approach", 118.125),
    _st("Silverbow Approach", "Tonopah", "approach", 119.45),
    _st("Silverbow Tower", "Tonopah", "tower", 124.75),
    _st("Silverbow Ground", "Tonopah", "ground", 127.25),
    _st("Los Angeles Center", "", "center", 133.4),
]

# WHAT THE TABLE HOLDS IS ONE MAP'S, because the push replaces it. Nevada here,
# so every test below is asking a Nevada question of a Nevada table -- and the
# stale case, which is the one that bit, gets Caucasus explicitly.
LIVE = NEVADA


class FakePool:
    """Just enough of psycopg to answer the `stations` SELECT."""

    def __init__(self, stations):
        self.rows = [(s["name"], s["field"], s["role"], s["freq_mhz"],
                      list(s["also"])) for s in stations]

    def connection(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, *args):
        self.sql = sql
        return self

    def fetchall(self):
        return list(self.rows)


def look_up(seat, rows=LIVE, **kw):
    with mock.patch.object(F, "get_pool", lambda: FakePool(rows)):
        (tool,) = F.frequency_tools(seat)
        return tool(**kw)


def stations(seat, rows=LIVE):
    with mock.patch.object(F, "get_pool", lambda: FakePool(rows)):
        return F._stations(seat)


class TestNobodyIsReadAnotherMapsFrequencies(unittest.TestCase):
    """The live symptom: a Nevada controller answering out of Georgia."""

    def test_a_nellis_seat_gets_the_nevada_list(self):
        self.assertEqual([s["name"] for s in stations("Nellis Tower")],
                         [s["name"] for s in NEVADA])

    def test_a_batumi_seat_gets_the_caucasus_list(self):
        self.assertEqual([s["name"] for s in stations("Batumi Approach",
                                                      rows=CAUCASUS)],
                         [s["name"] for s in CAUCASUS])

    def test_tonopah_tower_exists_when_nellis_tower_asks(self):
        # The exact question, and the exact wrong answer it used to get.
        said = look_up("Nellis Tower", place="Tonopah", position="tower")
        self.assertIn("Silverbow Tower", said)
        self.assertIn("one two four decimal seven five", said)
        self.assertNotIn("no Tonopah", said)

    def test_a_seat_everywhere_never_crosses_the_map(self):
        """`position` with no `place` reads that seat EVERYWHERE, which is the
        call that handed a Nevada controller two Georgian frequencies."""
        said = look_up("Nellis Tower", position="ground")
        self.assertIn("Nellis Ground", said)
        self.assertIn("Silverbow Ground", said)
        for georgian in ("Kobuleti Ground", "Batumi Ground"):
            self.assertNotIn(georgian, said)

    def test_the_fields_it_offers_are_his_own(self):
        """The not-found line names the map, so a controller reading it out is
        not offering a pilot two aerodromes on another continent."""
        said = look_up("Nellis Tower", place="Kutaisi", position="tower")
        self.assertIn("Nellis", said)
        self.assertIn("Tonopah", said)
        self.assertNotIn("Batumi", said)
        self.assertNotIn("Kobuleti", said)

    def test_the_query_no_longer_takes_one_row(self):
        # `fetchone` cannot be right here: the old rows were per PROCEDURE and
        # the station list is per MAP, so the row count is not the answer's.
        src = Path(F.__file__).read_text(encoding="utf-8")
        self.assertNotIn("fetchone()", src)


class TestALeftoverListIsNotHisMap(unittest.TestCase):
    """The push replaces the table, and one case still leaves the wrong map on
    it: `set_stations` REFUSES AN EMPTY PUSH, so a bridge that could not build a
    list -- or a 1944 letdown, which staffs no ladder at all -- leaves the last
    run's seats in place rather than wiping them.

    That is deliberate and it is why the reader still checks. Without the check
    the fix would restore the exact fault it is replacing: a real controller
    with a real frequency, over the wrong desert.
    """

    def test_a_nevada_seat_is_refused_a_caucasus_list(self):
        self.assertEqual(stations("Nellis Tower", rows=CAUCASUS), [])

    def test_and_he_is_told_to_say_he_cannot_look_it_up(self):
        said = look_up("Nellis Tower", rows=CAUCASUS, place="Tonopah",
                       position="tower")
        self.assertIn("cannot look it up", said)
        # Not one Georgian number, and not one Georgian aerodrome offered as a
        # near miss. Either would be read out in correct phraseology.
        self.assertNotIn("decimal", said)
        for georgian in ("Batumi", "Kobuleti", "Georgia"):
            self.assertNotIn(georgian, said)

    def test_the_seat_that_owns_the_table_still_gets_it(self):
        # The check must not be a blanket refusal: the whole point is that the
        # man the list names reads it.
        said = look_up("Batumi Approach", rows=CAUCASUS, place="Kobuleti",
                       position="ground")
        self.assertIn("Kobuleti Ground", said)
        self.assertIn("one two one decimal eight", said)


class TestItSaysItCannotRatherThanGuessing(unittest.TestCase):
    """The whole reason the tool exists. Asked for a frequency it had not been
    given, the controller invented one -- confidently, in correct phraseology,
    with a plausible number."""

    def test_an_unknown_seat_gets_no_list_at_all(self):
        self.assertEqual(stations("Vaziani Tower"), [])

    def test_and_the_tool_says_so(self):
        said = look_up("Vaziani Tower", place="Batumi")
        self.assertIn("cannot look it up", said)
        self.assertNotIn("decimal", said)

    def test_a_database_no_bridge_has_pushed_to_publishes_nothing(self):
        """A fresh table until a bridge starts, which is 027's bargain: with no
        bridge there is no controller, and no list is honest."""
        self.assertEqual(stations("Batumi Approach", rows=[]), [])

    def test_an_older_bridge_that_names_no_seat_is_given_the_published_list(self):
        self.assertEqual([s["name"] for s in stations("", rows=CAUCASUS)],
                         [s["name"] for s in CAUCASUS])


class TestTheApproachRowIsNotTheStationTable(unittest.TestCase):
    """The tool reads the `stations` table, and must never go back.

    Built as #67 over `approaches.data->'stations'`, on the argument that "the
    profile carries the whole station list". #162 moved the station table onto
    the THEATRE and took the field off the profile, so nothing has written a
    `stations` key since and the rows that have one are fossils. Four of them
    are the only reason the tool answered anything at all between #162 and this.
    """

    def test_a_profile_carries_no_station_list(self):
        from dataclasses import fields

        from marshall.core.approach import ApproachProfile
        self.assertNotIn("stations", {f.name for f in fields(ApproachProfile)},
                         "the writer is back — say so in atc/frequencies.py")

    def test_what_the_bridge_pushes_has_none_either(self):
        # WHICHEVER MAP IS LOADED. This named `R.BATUMI_ASR`, which does not
        # exist on Nevada -- so the guard on the regression that broke Nevada
        # could not be run there.
        from marshall.core import route as R
        from tests import theatre as T
        self.assertNotIn("stations", R.profile_to_dict(T.the_arrival()))

    def test_the_module_names_its_writer(self):
        src = Path(F.__file__).read_text(encoding="utf-8")
        self.assertIn("push_stations", src,
                      "the writing half must be named, or this is a tool that "
                      "quietly stops working on a fresh database")

    def test_it_does_not_read_the_fossils(self):
        # The fossils outlive this change on purpose -- dropping them before the
        # push is deployed would break the lookup for real -- so the guard is
        # that nothing here reaches for them any more.
        src = Path(F.__file__).read_text(encoding="utf-8")
        self.assertNotIn("FROM approaches", src)
        self.assertIn("FROM stations", src)


class TestTheDirectorBindsItToTheSeat(unittest.TestCase):

    def test_frequency_tools_is_given_the_station(self):
        src = (Path(__file__).resolve().parent.parent
               / "director" / "app.py").read_text(encoding="utf-8")
        self.assertIn("frequency_tools(station)", src)


if __name__ == "__main__":
    unittest.main()
