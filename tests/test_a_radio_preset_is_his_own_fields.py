"""The Mustang on the Batumi ramp had four Kobuleti frequencies and none of
his own. [#162]

    src/marshall/mission/build.py
        presets = [s.freq_mhz for s in R.STATIONS]
        ...
        for i, f in enumerate(presets[:5])

This is `stations[:4]` alive in a second place -- the fault `channels_for` was
written to end, in the one file still slicing the raw theatre table. The table
begins at the DEPARTURE field, and `PRESET_PATHS` covers only the P-51 and the
P-47, which are exactly the airframes parked at BATUMI. Measured:

    write_presets buttons 1..5        channels_for(limit=5, home="Batumi")
      125.100 Kobuleti Clearance        124.425 Batumi Approach
      121.800 Kobuleti Ground           118.600 Batumi Tower
      133.000 Kobuleti Tower            121.900 Batumi Ground
      123.300 Kobuleti Departure        139.000 Georgia Center
      139.000 Georgia Center            125.100 Kobuleti Clearance

So the pilot pressed A, B, C and D and reached four controllers forty miles up
the coast; there was no Batumi frequency on his set at all. The docstring above
the slice said "The presets are the CONTROLLERS now... Center, Approach,
Tower", which is another comment correcting its own code.

WHAT THE FIX IS. A slot carries the FIELD the aeroplane is standing on -- the
unit id says where the avionics file goes and the type says whether we know how
to write one, and neither of them says which four controllers are worth a
button. Then `channels_for` chooses, which is the one function the mission, the
kneeboard and the tests all read.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.core import route as R
from marshall.core import theatre as TH

# Imported flat, with no guard. It used to need one on the second map --
# `radio_frequency = R.TOWER.freq_mhz` in a class body -- and that is fixed by
# `test_the_map_is_chosen_before_a_module_binds_it`, which is where a failure
# to import belongs. A skip here would hide it.
from marshall.mission import build as MB

A_WARBIRD = sorted(MB.PRESET_PATHS)[0]


def _written(home: str) -> list[float]:
    """The frequencies `write_presets` actually puts in the aeroplane, read
    back out of a real zip rather than out of the function that made them."""
    with tempfile.TemporaryDirectory() as td:
        miz = Path(td) / "t.miz"
        with zipfile.ZipFile(miz, "w") as zf:
            zf.writestr("mission", "x")
        MB.write_presets(miz, [(1, A_WARBIRD, home)])
        with zipfile.ZipFile(miz) as zf:
            name = next(n for n in zf.namelist() if n.endswith("SETTINGS.lua"))
            hz = re.findall(r"=(\d{9}),", zf.read(name).decode())
    return [int(h) / 1e6 for h in hz]


class TestTheCardIsTheFieldHeIsStandingOn(unittest.TestCase):

    def test_every_button_this_set_has_reaches_his_field_or_the_region(self):
        """An SCR-522 has FOUR crystal channels, labelled A to D, and those are
        the buttons a pilot can actually press. All four used to be the other
        aerodrome's; all four are now his own or the region controller's.

        The fifth slot in the file is a DCS preset the period set cannot
        select, and it is where `_short_card`'s last rule lands: another
        field's controllers come after his and after the region, rather than
        instead of them."""
        buttons = len(R.PRESET_LETTERS)
        for fld in TH.fields_now():
            for mhz in _written(fld.name)[:buttons]:
                seat = TH.station_on(mhz)
                with self.subTest(field=fld.name, mhz=mhz):
                    self.assertIsNotNone(seat, "a button nobody is on")
                    self.assertIn(seat.field, (fld.name, ""))

    def test_and_no_foreign_seat_outranks_one_of_his(self):
        """The ordering rule stated over the whole card, so the fifth slot is
        checked too rather than merely excused."""
        for fld in TH.fields_now():
            fields = [TH.station_on(m).field for m in _written(fld.name)]
            foreign = [i for i, f in enumerate(fields)
                       if f not in (fld.name, "")]
            mine_or_region = [i for i, f in enumerate(fields)
                              if f in (fld.name, "")]
            with self.subTest(field=fld.name, card=fields):
                if foreign and mine_or_region:
                    self.assertGreater(min(foreign), max(mine_or_region))

    def test_his_own_aerodrome_gets_the_first_button(self):
        for fld in TH.fields_now():
            with self.subTest(field=fld.name):
                first = TH.station_on(_written(fld.name)[0])
                self.assertEqual(fld.name, first.field)

    def test_the_region_controller_keeps_a_button(self):
        """He is reachable from anywhere, which is precisely what makes him
        worth one of only five. A warbird who loses him has nobody at all once
        he leaves the circuit."""
        for fld in TH.fields_now():
            with self.subTest(field=fld.name):
                fields = [TH.station_on(m).field for m in _written(fld.name)]
                self.assertIn("", fields)

    def test_two_fields_get_two_different_cards(self):
        """The assertion the old code could not pass by construction: one body
        was built once, from the theatre's table, and written to every slot in
        the mission."""
        cards = {f.name: tuple(_written(f.name)) for f in TH.fields_now()}
        self.assertEqual(len(cards), len(set(cards.values())),
                         f"one card for two aerodromes: {cards}")

    def test_it_is_still_five_buttons(self):
        for fld in TH.fields_now():
            with self.subTest(field=fld.name):
                self.assertEqual(MB.PRESET_BUTTONS, len(_written(fld.name)))

    def test_and_it_is_what_channels_for_says(self):
        """One function, not two. The whole reason this was wrong is that the
        mission had its own idea of what is on button two."""
        for fld in TH.fields_now():
            want = [mhz for _, mhz in
                    MB.channels_for(limit=MB.PRESET_BUTTONS, home=fld.name)]
            with self.subTest(field=fld.name):
                self.assertEqual(want, _written(fld.name))


class TestASlotWithoutAFieldIsRefused(unittest.TestCase):
    """Loudly, and by name. The failure being replaced looked exactly like a
    working comms card until a pilot keyed the mic, so the one thing this must
    not do is carry on with a plausible default."""

    def test_a_two_tuple_slot_raises_and_says_why(self):
        with tempfile.TemporaryDirectory() as td:
            miz = Path(td) / "t.miz"
            with zipfile.ZipFile(miz, "w") as zf:
                zf.writestr("mission", "x")
            with self.assertRaises(ValueError) as caught:
                MB.write_presets(miz, [(1, A_WARBIRD)])
        self.assertIn("names no aerodrome", str(caught.exception))


class TestTheOtherFieldsFirstFiveIsNoLongerReachable(unittest.TestCase):
    """The specific wrong answer, named, so the test says what it is about."""

    def test_the_raw_table_order_is_not_anybodys_card(self):
        raw = [s.freq_mhz for s in R.STATIONS][:MB.PRESET_BUTTONS]
        for fld in TH.fields_now():
            got = _written(fld.name)
            if TH.station_on(raw[0]).field == fld.name:
                continue        # the table happens to start at HIS field
            with self.subTest(field=fld.name):
                self.assertNotEqual(raw, got,
                                    "the theatre's first five belong to "
                                    "whichever field the file lists first")


if __name__ == "__main__":
    unittest.main()
