"""Two controllers, two channels, one sortie -- the test that could not exist.

    tests/fakeradio.py:97   return Pcm(), None      # heard_hz None
    tests/fakeradio.py:170  def __init__(self, ..., freq_mhz=124.0)

`heard_hz` is the SOLE input to "which aerodrome is this". Eleven places in
`agent_atc` read it: which seat is speaking (`seat_on`), which voice answers
(`voice_for`), which frequencies the reply goes out on (`channels_of`), which
station the flight recorder writes, which agent the director builds, and which
channel a hook is kept on. Every one of them collapsed to 124.0 in every loop
test in this repo, because the fake radio returned `None` unconditionally and
nothing ever overrode the primary frequency.

So a controller who answered on the wrong frequency passed all of them. The
regression `radio/client.py:401-430` records as having ACTUALLY HAPPENED --

    "a pilot transmitting on Ground 121.800 was logged, answered and
     STATION-RESOLVED as though he were on Clearance 125.100"

-- could not fail a single test in this repo. Neither could findings 1, 2 and D3
of the 13 August inventory, all three of which are a real controller on a real
frequency belonging to the wrong aerodrome.

WHAT IS NEW HERE IS ONE PARAMETER. `Sortie.say(..., on=<MHz>)`. Everything else
was already built: the loop resolves the seat from the frequency, and it has
been right for a while. Nothing checked, which is a different thing from nothing
working -- and the difference only shows up the day somebody changes it.

WHY THE SEATS ARE ASKED FOR AND NOT NAMED. A role is unique only within an
aerodrome, so this file wants "the Ground at the departure field" and "the
Approach at the arrival field" rather than two Georgian names. It then runs on
both maps: Kobuleti Ground 121.800 against Batumi Approach 124.425, and
Silverbow Ground 127.250 against Nellis Approach 118.125.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakeradio import Sortie

from tests import theatre as T


def seats():
    """A Ground seat and an Approach seat, at TWO DIFFERENT aerodromes, on two
    different channels. Skips -- loudly -- rather than quietly proving nothing
    if a map ever staffs them on one number."""
    gnd = T.station("ground", T.other())
    app = T.station("approach", T.arrival())
    if gnd is None or app is None:
        raise unittest.SkipTest(f"{T.name()} does not staff both a Ground at "
                                f"{T.other().name} and an Approach at "
                                f"{T.arrival().name}")
    if abs(gnd.freq_mhz - app.freq_mhz) < 0.001:
        raise unittest.SkipTest(f"{gnd.name} and {app.name} share "
                                f"{gnd.freq_mhz}; there is one channel here")
    return gnd, app


def sortie(primary):
    """A bridge started on ONE channel, as the live one is."""
    return Sortie(profile=T.the_arrival(), freq_mhz=primary.freq_mhz)


def you_are(message: str) -> str:
    """The line of the prompt that says which seat the agent is."""
    for line in message.split("\n"):
        if line.startswith("YOU ARE:"):
            return line
    return ""


class EachChannelIsAnsweredByItsOwnSeat(unittest.TestCase):
    """The transmission the pilot actually hears, on the button he is holding.

    Two aeroplanes, forty miles apart (a hundred and twenty on Nevada), one
    bridge. One asks his own Ground for taxi; the other calls Approach inbound.
    """

    def flown(self):
        gnd, app = seats()
        s = (sortie(app)
             .say("viper", "viper-1", f"{gnd.name}, Viper one one, request taxi",
                  on=gnd.freq_mhz)
             .say("pony", "pony-1", f"{app.name}, Pony one one, ten miles",
                  on=app.freq_mhz)
             .replies("RADIO: Viper one one, taxi to runway zero seven, "
                      "hold short.")
             .replies("RADIO: Pony one one, radar contact.")
             .fly())
        return gnd, app, s

    def test_both_calls_arrived_on_the_channel_they_were_sent_on(self):
        """The premise. Without it the rest of this file asserts nothing --
        which is exactly the state the harness was in."""
        gnd, app, s = self.flown()
        self.assertEqual(s.heard_on(), [gnd.freq_mhz, app.freq_mhz])

    def test_each_reply_goes_out_on_the_channel_it_came_in_on(self):
        gnd, app, s = self.flown()
        self.assertEqual(s.answers_on(), [gnd.freq_mhz, app.freq_mhz],
                         "a controller answered on somebody else's frequency")

    def test_the_ground_call_is_not_answered_on_the_approach_channel(self):
        """The concrete wrong answer: the taxi clearance goes out on the
        arrival frequency, forty miles away, and the jet on the ramp hears
        nothing at all. That is finding D3 of the inventory, from the outside.
        """
        gnd, app, s = self.flown()
        on_app = s.said_on(app.freq_mhz)
        self.assertNotIn("taxi to runway", " ".join(on_app),
                         f"a taxi clearance was transmitted on {app.freq_mhz}")
        self.assertIn("taxi to runway", " ".join(s.said_on(gnd.freq_mhz)))

    def test_the_director_is_told_which_seat_it_is_each_time(self):
        """The prompt seam. `seat_on(heard_hz)` decides which agent the director
        builds and which tools it is given (#81) -- so a wrong frequency here is
        a Ground controller holding Approach's tool set."""
        gnd, app, s = self.flown()
        first, second = (you_are(m) for m in s.asked()[:2])
        self.assertIn(gnd.name, first)
        self.assertNotIn(app.name, first)
        self.assertIn(app.name, second)
        self.assertNotIn(gnd.name, second)

    def test_and_the_frequency_in_that_line_is_his_own(self):
        """"YOU ARE: Kobuleti Ground on 124.425" is a controller who will
        confidently tell a pilot to stay on a channel he is not on."""
        gnd, app, s = self.flown()
        self.assertIn(str(gnd.freq_mhz), you_are(s.asked()[0]))
        self.assertIn(str(app.freq_mhz), you_are(s.asked()[1]))


class TheSeatComesFromTheFrequencyAndNothingElse(unittest.TestCase):
    """A role is unique only within an aerodrome; the button is not.

    The transcript cannot decide this and neither can the profile. The button
    the pilot pressed is the one fact about a transmission that nobody can get
    wrong by mumbling, which is why `station_on` owns the answer.
    """

    def test_the_same_words_on_two_channels_reach_two_controllers(self):
        """Identical text, twice. Only the channel differs, and only the channel
        should decide who answers."""
        gnd, app = seats()
        s = (sortie(app)
             .say("pony", "pony-1", "go ahead", on=gnd.freq_mhz)
             .say("pony", "pony-1", "go ahead", on=app.freq_mhz)
             .replies("RADIO: one").replies("RADIO: two")
             .fly())
        self.assertEqual([you_are(m).split(" on ")[0] for m in s.asked()],
                         [f"YOU ARE: {gnd.name}", f"YOU ARE: {app.name}"])

    def test_two_seats_at_ONE_field_are_still_told_apart(self):
        """The regression `radio/client.py` records: a pilot on Ground 121.800
        answered as though he were on Clearance 125.100. Same aerodrome, same
        ladder, adjacent rungs -- so nothing about the field can save it and the
        frequency is the whole of the evidence."""
        here = T.other()
        gnd = T.station("ground", here)
        clr = T.station("clearance", here)
        if gnd is None or clr is None or gnd is clr:
            raise unittest.SkipTest(
                f"{here.name} does not staff a separate Ground and Clearance, "
                f"so the two cannot be confused there")
        s = (sortie(clr)
             .say("viper", "viper-1", "ready to taxi", on=gnd.freq_mhz)
             .replies("RADIO: Viper one one, taxi to runway zero seven.")
             .fly())
        self.assertIn(gnd.name, you_are(s.asked()[0]))
        self.assertNotIn(clr.name, you_are(s.asked()[0]))
        self.assertEqual(s.answers_on(), [gnd.freq_mhz])

    def test_a_call_on_the_bridges_own_channel_is_unchanged(self):
        """The half that must not be lost. Every script written before the
        parameter existed says nothing about a frequency and means "the one the
        bridge was started on"; that is still what it means."""
        _gnd, app = seats()
        s = (sortie(app)
             .say("pony", "pony-1", f"{app.name}, Pony one one, ten miles")
             .replies("RADIO: Pony one one, radar contact.")
             .fly())
        self.assertEqual(s.heard_on(), [app.freq_mhz])
        self.assertEqual(s.answers_on(), [app.freq_mhz])
        self.assertIn(app.name, you_are(s.asked()[0]))


class OneControllerThinkingDoesNotSilenceAnother(unittest.TestCase):
    """CLAUDE.md: *"Serialisation is per FREQUENCY -- two controllers at two
    aerodromes talk at once, two transmissions on one channel wait."*

    The model call is the slow part: a median of 3.3 s and a worst case of 13.5.
    While Approach composes, a jet on another aerodrome's ramp asking for taxi
    must still be answered -- and finding D4 of the inventory is that the
    director's busy-lock is keyed on the SESSION rather than on the frequency,
    so his transmission comes back `{"response": "", "busy": true}` and is
    dropped in silence with nothing in his log.

    THAT LOCK IS IN `director/`, WHICH THIS FILE CANNOT REACH. What is asserted
    here is the bridge's half of the contract, which is the half that would
    have to be right anyway: a slow turn on one channel does not lose, misroute
    or re-channel the next turn on another. If it ever does, this fails before
    anybody flies.
    """

    def test_a_slow_turn_on_one_channel_does_not_lose_the_next_on_another(self):
        """Approach takes a quarter of a second to compose. The man on the ramp
        is answered anyway, on his own channel, in full."""
        gnd, app = seats()
        s = (sortie(app)
             .say("pony", "pony-1", f"{app.name}, Pony one one, ten miles",
                  on=app.freq_mhz)
             .say("viper", "viper-1", f"{gnd.name}, Viper one one, request taxi",
                  on=gnd.freq_mhz)
             .replies("RADIO: Pony one one, radar contact.", after=0.25)
             .replies("RADIO: Viper one one, taxi to runway zero seven.")
             .fly())
        self.assertEqual(len(s.asked()), 2,
                         "the second controller's transmission never reached "
                         "the director")
        self.assertEqual(s.answers_on(), [app.freq_mhz, gnd.freq_mhz])
        self.assertIn("taxi to runway", " ".join(s.said_on(gnd.freq_mhz)))

    def test_and_the_second_seat_is_still_his_own(self):
        """Not the seat of whoever spoke last, which is what a module-global
        `_me` mutated per received transmission gives you (finding 1.1)."""
        gnd, app = seats()
        s = (sortie(app)
             .say("pony", "pony-1", f"{app.name}, Pony one one, ten miles",
                  on=app.freq_mhz)
             .say("viper", "viper-1", "request taxi", on=gnd.freq_mhz)
             .replies("RADIO: Pony one one, radar contact.")
             .replies("RADIO: Viper one one, taxi to runway zero seven.")
             .fly())
        self.assertIn(gnd.name, you_are(s.asked()[1]))
        self.assertNotIn(app.name, you_are(s.asked()[1]))


if __name__ == "__main__":
    unittest.main()
