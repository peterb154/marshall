"""The seats reach the director because somebody sends them, not by accident.

    batumi-asr  | 9 stations   <- written 25 July
    batumi-ils  | 9
    batumi-ndb  | 0            <- written after #162
    nellis-ils  | 9
    tonopah-ils | 8

Four fossils and one honest row. `look_up_frequency` was built over
`approaches.data->'stations'` on the argument that the profile carries the whole
station list, which was true while `ApproachProfile` had a `stations` field:
`profile_to_dict` is `asdict`, so pushing the profile pushed the seats. #162
took the field off the profile -- correctly, a station belongs to the MAP and
not to an arrival procedure -- and removed the only channel they had. Nothing
replaced it. `batumi-ndb` is what every row looks like from now on, so a reset
database answers "no station list is published" to every question about every
field on both maps, and the controller goes back to inventing a plausible number
in correct phraseology.

WHY THE BRIDGE SENDS IT. The director container has no `config/`:
`catalogue.maps()` is `[]` in there and `route.STATIONS` raises
FileNotFoundError. THE BRIDGE KNOWS WHICH MAP IS LOADED AND THE DIRECTOR DOES
NOT -- `push_sectors` is written under that sentence, and a first version of
`/atis` ignored it, walked `theatre.current().fields` inside the container and
confidently reported Batumi on a Nevada sortie.

WHAT IS GUARDED HERE, and each of the three is a way this has already failed
somewhere in this repo:

    the push carries the LOADED map's seats and no other map's
    a second push REPLACES, so last map's controllers do not survive it
    it is CALLED at bridge start -- `tools/unwired.py` exists because a correct
        thing nothing reaches is this project's dominant failure mode

`sectors` is not a substitute for any of it: it is a table of VOLUMES, so it has
no Ground, no Clearance and no Sentry, and "say again Kobuleti ground" is the
question a pilot actually asks.
"""

import ast
import json
import unittest
import unittest.mock as mock
from pathlib import Path

from marshall.atc import agent_atc as A
from marshall.core import theatre as TH
from tests import theatre as T

SRC = Path(A.__file__)
TRACKS = Path(A.__file__).resolve().parents[1] / "feed" / "tracks.py"


def _lift(name: str):
    """One function out of `feed/tracks.py`, compiled on its own.

    THE MODULE CANNOT BE IMPORTED HERE and that is not a defect to work around.
    It is the director's deployable: `import grpc` at module scope, then the
    generated DCS protobufs through `feed/dcs.py`, which want protobuf. Those
    are that container's dependencies and not the suite's, which is why
    `tests/test_director_sql.py` reads this same file as SOURCE rather than
    importing it.

    Reading is not enough here. "The push replaces the table" is a thing the
    code DOES -- a DELETE with the right predicate, reached in the right cases
    and skipped in the others -- and asserting that a DELETE appears in the text
    is asserting the wrong noun. `set_stations` touches no gRPC and no sim; it
    takes a list and talks to `marshall.core.db`, which imports cleanly. So it
    is lifted out and RUN, against a pool that records what it was asked to do.

    If this ever fails to find the function, the fix is to move the function,
    not to weaken the test into a grep.
    """
    tree = ast.parse(TRACKS.read_text(encoding="utf-8"))
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if fn is None:                                  # pragma: no cover - guard
        raise AssertionError(f"{name} is not a top-level function in {TRACKS}")
    ns: dict = {"json": json, "__name__": "marshall.feed.tracks"}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(TRACKS), "exec"), ns)
    return ns[name]


class Captured:
    """The PUT the bridge would have made, without a director to make it to."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, obj, *a, **kw):
        self.calls.append((url, obj))

    @property
    def stations(self):
        for url, obj in self.calls:
            if url.endswith("/stations"):
                return obj["stations"]
        return None


def push(profile=None):
    cap = Captured()
    with mock.patch.object(A, "_put_json", cap):
        n = A.push_stations("http://director")
    return n, cap


class TestThePushCarriesThisMapsSeats(unittest.TestCase):

    def test_every_seat_the_loaded_theatre_publishes(self):
        n, cap = push()
        self.assertEqual(n, len(TH.stations_now()))
        self.assertEqual([s["name"] for s in cap.stations],
                         [s.name for s in TH.stations_now()])

    def test_including_the_seats_that_own_no_airspace(self):
        """The half `push_sectors` cannot carry. A sector is a volume, so
        Ground, Clearance and Sentry are not in it -- and ground is the seat a
        pilot most often asks another field's frequency for."""
        got = {s["role"] for s in push()[1].stations}
        self.assertIn("ground", got)
        self.assertIn("clearance", got)

    def test_and_no_other_maps(self):
        """The exact fault the push exists to prevent, and the one a container
        that read the theatre itself would commit: a real controller with a real
        frequency, belonging to the wrong continent."""
        here = TH.current().name.lower()
        elsewhere = [m for m in ("caucasus", "nevada") if m != here]
        self.assertTrue(elsewhere, "no second map to be confused with")
        sent = {s["name"] for s in push()[1].stations}
        for m in elsewhere:
            theirs = {s.name for s in TH.published_stations(m)}
            self.assertTrue(theirs, f"{m} publishes no seats to check against")
            self.assertEqual(sent & theirs, set(),
                             f"{m}'s controllers are in {here}'s push")

    def test_a_seat_carries_what_the_lookup_reads(self):
        # Every key `frequencies._stations` builds a row out of. A push missing
        # one of them is a lookup that answers with a blank where a number goes.
        for s in push()[1].stations:
            self.assertEqual(set(s), {"name", "field", "role", "freq_mhz",
                                      "also"})
            self.assertTrue(s["name"])
            self.assertIsNotNone(s["freq_mhz"])

    def test_a_letdown_s_BEACONS_reach_the_EAR_and_not_the_role_table(self):
        """The mode switch moved, and where it moved to is the whole point.

        This used to assert that `push_stations` published the LETDOWN's own
        beacon seats rather than the modern ladder -- right while the process
        ran one arrival, and unanswerable without one: with four procedures
        published and no singular, "which procedure's seats" has no subject.

        The tempting answer is to publish the union, and it is wrong. This
        table backs `look_up_frequency`, which is asked BY ROLE AND FIELD, and
        a beacon seat and a ladder seat share a name at one aerodrome --
        "Batumi Tower" is 118.6 on the ladder and 132.0 on the letdown. A union
        answers one of them by row order, which is a real controller on a real
        frequency, and the wrong one.

        So the split is by HOW THE SEAT IS LOOKED UP:

            by role and field   the ladder            `push_stations`
            by frequency        ladder + beacons      `seats_on_the_air`

        A frequency is unique across the union, so the ear can open every
        channel anybody might call on without any lookup becoming ambiguous.
        And the one reader who has to tell them apart -- the controller -- is
        told in words, in the letdown's own plate section. [#140, #162]
        """
        p = T.letdown()
        if p is None or getattr(p, "theatre_stations", True):
            self.skipTest("this map publishes no letdown off the ladder, so "
                          "there is no mode switch here to exercise")
        # THE ROLE TABLE IS THE LADDER, and nothing else.
        _n, cap = push()
        self.assertEqual([s["name"] for s in cap.stations],
                         [s.name for s in TH.stations_now()])

        # THE EAR OPENS BOTH. Every beacon frequency this letdown is worked on
        # is a channel the radio listens to -- without it a Mustang homing
        # 132.0 calls into silence and neither end can tell.
        heard = {round(s.freq_mhz, 3) for s in TH.seats_on_the_air()}
        beacons = TH.beacon_seats(p)
        self.assertTrue(beacons, "the letdown derives no seats from its fixes")
        for s in beacons:
            with self.subTest(s.name):
                self.assertIn(round(s.freq_mhz, 3), heard,
                              f"{s.name} on {s.freq_mhz} is a frequency this "
                              f"procedure is worked on and nobody is listening")

        # ...AND THE UNION IS STILL UNAMBIGUOUS BY FREQUENCY, which is the
        # property that makes it safe to open. Two seats on one channel would
        # put the wrong man's name on a transmission.
        freqs = [round(s.freq_mhz, 3) for s in TH.seats_on_the_air()]
        self.assertEqual(len(freqs), len(set(freqs)),
                         "two seats claim one frequency in the union")

    def test_and_the_letdown_s_PLATE_says_its_seats_are_not_the_ladder(self):
        """The words that stop the one contradiction the split leaves behind.

        The combined plate lists the map's ladder once, for every procedure,
        and the letdown's section describes controllers on other frequencies.
        Both are true and only one applies to any given aeroplane; without a
        sentence saying so the controller has to guess, and the wrong guess
        sends a Mustang to a frequency his ARA-8 cannot tune.
        """
        from marshall.atc import briefing
        p = T.letdown()
        if p is None or getattr(p, "theatre_stations", True):
            self.skipTest("this map publishes no letdown off the ladder")
        # ON THE TURN, NOT IN THE STATIC PLATE. #176 moved every
        # procedure's detail out of the system prompt and onto the
        # transmission of the aeroplane cleared for it, so this sentence
        # now reaches exactly the controller working the Mustang -- which
        # is better targeting of the same correction, not a weaker one.
        said = briefing.procedure_brief(p)
        self.assertIn("THE SEATS ON THIS PROCEDURE ARE ITS BEACONS", said)
        for s in TH.beacon_seats(p):
            with self.subTest(s.name):
                self.assertIn(f"{s.name}", said)
        # ...AND THE STATIC PLATE STILL LISTS THE LADDER, which is what the
        # sentence above exists to contradict. Both halves must be present
        # or the contradiction it resolves is not there to resolve.
        static = briefing.plates(T.approaches())
        self.assertIn("Controllers:", static)
        self.assertNotIn("THE SEATS ON THIS PROCEDURE ARE ITS BEACONS",
                         static)


class TestASecondPushReplacesTheTable(unittest.TestCase):
    """`set_sectors`' bargain, taken verbatim: whatever the push no longer has,
    the table no longer has. A table added to rather than reconciled keeps the
    LAST map's answers, and that is not a stale row hiding a failure, it is a
    stale row CAUSING one."""

    NEVADA = [{"name": "Nellis Tower", "field": "Nellis", "role": "tower",
               "freq_mhz": 132.55, "also": []},
              {"name": "Nellis Ground", "field": "Nellis", "role": "ground",
               "freq_mhz": 121.8, "also": ()}]

    def _pushed(self, rows):
        sql: list = []

        class Conn:
            def connection(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, s, *args):
                sql.append((" ".join(s.split()), args))
                return self

        with mock.patch("marshall.core.db.pool", lambda: Conn()):
            n = _lift("set_stations")(rows)
        return n, sql

    def test_it_deletes_what_the_push_did_not_carry(self):
        n, sql = self._pushed(self.NEVADA)
        self.assertEqual(n, 2)
        deletes = [s for s, _ in sql if s.startswith("DELETE")]
        self.assertEqual(len(deletes), 1, "no reconciliation: this is an "
                                          "accumulating table, and the last "
                                          "map's controllers survive it")
        self.assertIn("DELETE FROM stations WHERE NOT (name = ANY(%s))",
                      deletes[0])

    def test_and_the_delete_spares_exactly_what_it_carried(self):
        """The Caucasus ladder does not survive a Nevada push. This is the
        assertion, and everything else in this class is scaffolding for it."""
        _n, sql = self._pushed(self.NEVADA)
        kept = next(a for s, a in sql if s.startswith("DELETE"))[0][0]
        self.assertEqual(sorted(kept), ["Nellis Ground", "Nellis Tower"])
        for georgian in ("Batumi Approach", "Kobuleti Ground", "Georgia Center"):
            self.assertNotIn(georgian, kept)

    def test_the_insert_carries_every_column_the_lookup_reads(self):
        _n, sql = self._pushed(self.NEVADA)
        ins = [(s, a) for s, a in sql if s.startswith("INSERT")]
        self.assertEqual(len(ins), 2)
        self.assertIn("INSERT INTO stations (name, field, role, freq_mhz, also)",
                      ins[0][0])
        # `also` is a jsonb column, so it is serialised rather than handed a
        # Python list -- and a tuple is what a `Station` actually carries.
        self.assertEqual(json.loads(ins[1][1][0][4]), [])

    def test_an_empty_push_is_not_a_replacement(self):
        """A bridge that could not build a list must leave the last good one
        alone. Failing safe here means failing SILENT, which is why the reader
        answers only a seat the published list names."""
        set_stations = _lift("set_stations")
        with mock.patch("marshall.core.db.pool",
                        lambda: self.fail("an empty push touched the table")):
            self.assertEqual(set_stations([]), 0)
            self.assertEqual(set_stations(None), 0)

    def test_a_row_with_no_name_is_not_a_station(self):
        set_stations = _lift("set_stations")
        with mock.patch("marshall.core.db.pool",
                        lambda: self.fail("a nameless row reached the table")):
            self.assertEqual(set_stations([{"freq_mhz": 118.6}]), 0)


class TestTheBridgeActuallySendsIt(unittest.TestCase):
    """A writer nothing calls is the shape `tools/unwired.py` was written for:
    `phrasebook.render`, `phases.guide`, `Controller._me` -- built, correct,
    unreached, and each one green in its own tests."""

    def _startup(self) -> ast.FunctionDef:
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "load_and_push_plates"):
                return node
        self.fail("load_and_push_plates is gone — find where the bridge starts")

    def _called(self, fn) -> set:
        return {n.func.id for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

    def test_bridge_start_pushes_the_stations(self):
        called = self._called(self._startup())
        self.assertIn("push_stations", called)
        # Beside the pushes it belongs with, so a reader finds all four in one
        # place rather than discovering the fourth by its absence.
        for sibling in ("push_fixes", "push_sectors"):
            self.assertIn(sibling, called)

    def test_a_failed_push_does_not_stop_the_bridge(self):
        """Same bargain as the fixes and the volumes: a controller with no
        frequency directory still controls. It says so and carries on."""
        src = SRC.read_text(encoding="utf-8")
        i = src.index("n = push_stations(")
        self.assertIn("except", src[i:i + 600])


class TestTheDirectorHasTheDoor(unittest.TestCase):
    """The director is not importable here -- PostGIS, strands, the gRPC stubs
    -- and the endpoint is four lines. The source is the cheapest honest check,
    which is `tests/test_director_sql.py`'s argument for the same thing."""

    def test_there_is_a_put_and_a_get(self):
        src = (Path(__file__).resolve().parent.parent
               / "services" / "app.py").read_text(encoding="utf-8")
        self.assertIn('@app.put("/stations")', src)
        self.assertIn('@app.get("/stations")', src)
        self.assertIn("set_stations(body.get(\"stations\") or [])", src)

    def test_the_table_is_created_by_a_migration(self):
        """Not lazily, at first use, inside the running agent -- which is what
        `fixes`, `approaches` and `flight_plans` do, and why an empty volume
        used to kill the container at boot (docs/AUDIT-2026-07-29)."""
        d = Path(__file__).resolve().parent.parent / "services" / "migrations"
        ddl = [p for p in d.glob("*.sql")
               if "CREATE TABLE IF NOT EXISTS stations" in
               p.read_text(encoding="utf-8")]
        self.assertEqual(len(ddl), 1, "the stations table wants exactly one "
                                      "author")

    def test_the_migration_leaves_the_fossils_alone(self):
        """The four old rows are what makes the lookup work TODAY, on a database
        no bridge carrying the push has started against yet. Dropping the key in
        the same migration turns a regression into an outage."""
        d = Path(__file__).resolve().parent.parent / "services" / "migrations"
        for p in d.glob("032_*.sql"):
            body = "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines()
                             if not ln.strip().startswith("--"))
            self.assertNotIn("data - 'stations'", body)
            self.assertNotIn("UPDATE approaches", body)


if __name__ == "__main__":
    unittest.main()
