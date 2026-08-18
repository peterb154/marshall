"""Told once is told. The information letter is a fact about the AEROPLANE.

    "Kobuleti Clearance is asking whether or not I have information whiskey
     over and over again, even though I've already told him. That should
     probably be something in the database to record that I have whiskey, so he
     doesn't keep asking"

It IS in the database -- `flights.atis_letter`, a column since migration 026,
carried on the `flight_state` view and restored by `hydrate`. The column was
not the problem. The WRITE was: `intents.dispatch` set `ac.atis_letter` inside
the `CHECK_IN` branch and nowhere else, so the letter only stuck if the pilot
happened to say it while checking in.

18 August, live. He said it on his first call and it took. Then, five times:

    15:12:48  PILOT  Kobuleti Clearance, sockeye, with whiskey      CHECK_IN  ok
    15:13:08  PILOT  I would like Batumi Test, IFR to Batumi        request
    15:13:11  ATC    ... Advise you have information Whiskey.
    15:13:39  PILOT  ...I do have information whiskey               request
    15:13:43  ATC    ... Advise you have information Whiskey.
    15:14:47  ATC    ... Advise you have information Whiskey.
    15:15:43  ATC    ... Advise you have information Whiskey.

Every one of the pilot's letters after the first arrived on a kind of call this
branch did not cover, so it was parsed, put on the `Intent`, and dropped.

WHY IT SURVIVED A YEAR OF TESTS. Every existing test says the letter on a
check-in, because that is where phraseology puts it -- and so did the pilot,
once. The bug needs a SECOND transmission to show, and a controller that never
gets one cannot ask twice.

The fix is a hoist, not a new mechanism: the write happens whenever the intent
carries a letter, whatever the call was about. [#180]
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as C
from marshall.atc import intents as I

import tests.theatre as T


def _clearance():
    ctl = C.Controller()
    ctl._me = T.station("clearance", field="Kobuleti")
    return ctl


class TheLetterSticksWhateverHeSaidItOn(unittest.TestCase):
    """One case per intent kind a pilot plausibly volunteers it on.

    Parameterised over kinds rather than asserting the hoist's position in the
    source, because what matters is that no kind drops it -- a future `match`
    arm that re-introduces a per-branch write would pass a structural check.
    """

    KINDS = (
        I.IntentKind.CHECK_IN,
        I.IntentKind.REQUEST_CLEARANCE,
        I.IntentKind.REQUEST_TAXI,
        I.IntentKind.READ_BACK,
        I.IntentKind.REQUEST_APPROACH,
    )

    def test_every_kind_of_call_records_it(self):
        for kind in self.KINDS:
            with self.subTest(kind.name):
                ctl = _clearance()
                ac = ctl.get("Sockeye")
                I.dispatch(ctl, I.Intent(kind, "Sockeye", atis_letter="Whiskey"))
                self.assertEqual(
                    ac.atis_letter, "Whiskey",
                    f"he said the letter on a {kind.name} and it was dropped")

    def test_and_a_call_without_one_does_not_erase_it(self):
        """The hoist must not clear what an earlier call established. He says
        it once at the start of a sortie and every transmission afterwards
        carries no letter at all."""
        ctl = _clearance()
        ac = ctl.get("Sockeye")
        I.dispatch(ctl, I.Intent(I.IntentKind.CHECK_IN, "Sockeye",
                                 atis_letter="Whiskey"))
        I.dispatch(ctl, I.Intent(I.IntentKind.REQUEST_TAXI, "Sockeye"))
        self.assertEqual(ac.atis_letter, "Whiskey")


class AndThenTheControllerStopsAsking(unittest.TestCase):
    """The end-to-end half: the pilot's actual complaint, not the field.

    `_atis_phrase` is what he heard five times. Asserting on the phrase rather
    than on `ac.atis_letter` is deliberate -- the write and the read are two
    separate mistakes this file has to rule out, and only the second one is
    audible.
    """

    def setUp(self):
        self.ctl = _clearance()
        self.ac = self.ctl.get("Sockeye")
        # WHISKEY ON THE AIR. `_atis_phrase` reads the live broadcast and with
        # no database there is none, so every branch under test collapses to
        # the same "Say your request." -- which is the correct answer to a
        # field with no ATIS and tells us nothing about the letter. Patched at
        # the module attribute because the phrase imports the store lazily.
        from marshall.atis import store as _atis
        real = _atis.current
        _atis.current = lambda field, *a, **k: _atis.Current(
            field=field.name, letter="Whiskey", runway=7,
            wind_from_deg=90, wind_kt=5, on_the_air=True)
        self.addCleanup(setattr, _atis, "current", real)

    def _said(self) -> str:
        return self.ctl._atis_phrase(self.ac)

    def test_he_is_asked_before_he_says_it(self):
        self.assertIn("advise you have information", self._said().lower())

    def test_he_is_not_asked_again_after_saying_it_on_a_request(self):
        I.dispatch(self.ctl, I.Intent(I.IntentKind.REQUEST_CLEARANCE,
                                      "Sockeye", atis_letter="Whiskey"))
        said = self._said().lower()
        self.assertNotIn("advise you have information", said,
                         "asked for a letter he has already given")
        self.assertIn("current", said)

    def test_a_stale_letter_is_still_corrected(self):
        """The fix must not go so far that the asking stops mattering. A pilot
        holding an old broadcast has to be told, and that is the same read."""
        I.dispatch(self.ctl, I.Intent(I.IntentKind.REQUEST_CLEARANCE,
                                      "Sockeye", atis_letter="Victor"))
        said = self._said().lower()
        self.assertIn("not victor", said)


class NothingWeAskTheModelForIsThrownAway(unittest.TestCase):
    """The GENERAL fault, which is what made this one invisible for so long.

    `INTENT_SCHEMA` describes seven fields to the classifier and the model
    fills them all. `classify` then hand-copies them onto an `Intent`, and
    `atis_letter` was simply not on the list -- so the model answered a
    question nobody collected, on every transmission, for as long as the field
    has existed.

    Nothing could catch it downstream. The field EXISTED, typed and defaulted
    to "", so every reader compiled, every test that constructed an `Intent`
    directly passed, and `ac.atis_letter` stayed empty for a reason no amount
    of reading the controller would show. It took a pilot being asked five
    times.

    Costs nothing to check and is the only place the two lists can be
    compared, because the copy is manual by design -- the clamps and truncation
    on `flight_size`, `wants` and this field are the reason it is not a
    `**data` splat.
    """

    def test_every_schema_field_reaches_the_intent(self):
        import ast
        import inspect

        from marshall.atc import bedrock_intent as B

        asked = set(I.INTENT_SCHEMA["properties"])
        src = inspect.getsource(B.classify)
        read = {n.args[0].value
                for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call)
                and getattr(n.func, "attr", "") == "get"
                and n.args and isinstance(n.args[0], ast.Constant)}
        dropped = sorted(asked - read)
        self.assertEqual(
            dropped, [],
            f"INTENT_SCHEMA asks the model for {dropped} and `classify` never "
            f"reads {'it' if len(dropped) == 1 else 'them'} off the response. "
            f"The field will be its default on every call and nothing "
            f"downstream can tell that apart from a pilot who said nothing.")

    def test_and_nothing_is_read_that_was_never_asked_for(self):
        """The mirror. A `data.get` for a key the schema does not describe is
        a field the model was never told to fill, so it silently reads as
        absent -- the same failure from the other end."""
        import ast
        import inspect

        from marshall.atc import bedrock_intent as B

        asked = set(I.INTENT_SCHEMA["properties"])
        src = inspect.getsource(B.classify)
        read = {n.args[0].value
                for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call)
                and getattr(n.func, "attr", "") == "get"
                and n.args and isinstance(n.args[0], ast.Constant)}
        stray = sorted(read - asked)
        self.assertEqual(
            stray, [],
            f"`classify` reads {stray} off the response and INTENT_SCHEMA "
            f"never asks for {'it' if len(stray) == 1 else 'them'}")


if __name__ == "__main__":
    unittest.main()
