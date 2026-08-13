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

AND THE SOURCE IS GONE, which is the other half and is not fixed here. #162 took
the station list off `ApproachProfile` and gave it to the theatre;
`profile_to_dict` is `asdict`, so no row written from now on carries one. The
rows below are the real ones out of the live database -- two of them fossils
from before the move -- and `TestTheApproachRowIsNotTheStationTable` is what
says so out loud. The tool must fail closed and SAY it cannot look one up, never
reach for whatever list is left.

The fixtures are the live rows, trimmed to the fields the tool reads.
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

# Alphabetical, which is what the old query sorted by: the Caucasus rows come
# first and there is no third answer to the question it was asking.
LIVE = [("batumi-asr", CAUCASUS), ("batumi-ils", CAUCASUS),
        ("batumi-ndb", None), ("nellis-ils", NEVADA), ("tonopah-ils", NEVADA)]


class FakePool:
    """Just enough of psycopg to answer one SELECT."""

    def __init__(self, rows):
        self.rows = [(n, s) for n, s in rows if s is not None]

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


def look_up(seat, **kw):
    with mock.patch.object(F, "get_pool", lambda: FakePool(LIVE)):
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
        self.assertEqual([s["name"] for s in stations("Batumi Approach")],
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
        # `fetchone` cannot be right here: the rows are per PROCEDURE and the
        # station list is per MAP, so the row count is not the answer's count.
        src = Path(F.__file__).read_text(encoding="utf-8")
        self.assertNotIn("fetchone()", src)


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

    def test_a_fresh_database_publishes_nothing(self):
        """#162 stopped the writer, so this is every database from now on."""
        self.assertEqual(stations("Batumi Approach", rows=[("batumi-ndb", None)]),
                         [])

    def test_an_older_bridge_that_names_no_seat_is_given_the_only_list(self):
        one = [("batumi-asr", CAUCASUS)]
        self.assertEqual([s["name"] for s in stations("", rows=one)],
                         [s["name"] for s in CAUCASUS])

    def test_but_never_the_first_of_several(self):
        # This is the bug in one line: with no seat and more than one map on
        # the table, there is no answer, and picking one is how Batumi's list
        # ended up in a Nevada cockpit.
        self.assertEqual(stations(""), [])


class TestTheApproachRowIsNotTheStationTable(unittest.TestCase):
    """The source is gone, and the docstring must not claim otherwise.

    This tool was built as #67 over `approaches.data->'stations'`, on the
    argument that "the profile carries the whole station list". #162 moved the
    station table onto the THEATRE and took the field off the profile. Nothing
    has written a `stations` list since; the rows that have one are fossils.
    """

    def test_a_profile_carries_no_station_list(self):
        from dataclasses import fields

        from marshall.core.approach import ApproachProfile
        self.assertNotIn("stations", {f.name for f in fields(ApproachProfile)},
                         "the writer is back — say so in tools/frequencies.py")

    def test_what_the_bridge_pushes_has_none_either(self):
        from marshall.core import route as R
        self.assertNotIn("stations", R.profile_to_dict(R.BATUMI_ASR))

    def test_the_module_says_the_writer_is_missing(self):
        src = Path(F.__file__).read_text(encoding="utf-8")
        self.assertIn("push_stations", src,
                      "the missing half must be named, or it is a tool that "
                      "quietly stops working on a fresh database")


class TestTheDirectorBindsItToTheSeat(unittest.TestCase):

    def test_frequency_tools_is_given_the_station(self):
        src = (Path(__file__).resolve().parent.parent
               / "director" / "app.py").read_text(encoding="utf-8")
        self.assertIn("frequency_tools(station)", src)


if __name__ == "__main__":
    unittest.main()
