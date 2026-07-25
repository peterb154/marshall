"""The SRS bridge's text handling -- what actually reaches Polly.

No network: these are the pure functions between the agent's reply and the
radio. They exist because both failures below were found on the air, in the
controller's voice, mid-sortie.
"""

import unittest

from marshall.atc import agent_atc


class TestForVoice(unittest.TestCase):
    def test_reasoning_above_the_marker_is_not_transmitted(self):
        # Seen live: with extended thinking disabled the model reasons in the
        # OUTPUT, and every word of it was spoken to the pilot.
        reply = ("This is a different transmitter, a wingman, reporting his "
                 "level. He's holding, not yet identified individually.\n"
                 "RADIO: Pony one two, roger, level four thousand.")
        self.assertEqual(agent_atc.for_voice(reply),
                         "Pony one two, roger, level four thousand.")

    def test_marker_alone(self):
        self.assertEqual(agent_atc.for_voice("RADIO: Pony one flight, roger."),
                         "Pony one flight, roger.")

    def test_last_marker_wins(self):
        self.assertEqual(agent_atc.for_voice("a RADIO: b RADIO: c"), "c")

    def test_reply_without_a_marker_is_still_spoken(self):
        # The marker is a safety net, not a requirement -- a model that forgets
        # it must not produce silence on the frequency.
        self.assertEqual(agent_atc.for_voice("Pony one one, cleared approach."),
                         "Pony one one, cleared approach.")

    def test_markdown_is_stripped(self):
        self.assertEqual(
            agent_atc.for_voice("**Pony one one**, `cleared` approach."),
            "Pony one one, cleared approach.")

    def test_newlines_collapse_to_one_line(self):
        self.assertEqual(agent_atc.for_voice("Pony one one,\ncleared\napproach."),
                         "Pony one one, cleared approach.")

    def test_bullets_are_stripped(self):
        self.assertEqual(agent_atc.for_voice("- Pony one one, cleared approach."),
                         "Pony one one, cleared approach.")


class TestCountContacts(unittest.TestCase):
    """The bridge engages the separation engine on contact count, so this
    decides whether a formation gets deterministic sequencing at all."""

    def test_empty_sky(self):
        self.assertEqual(agent_atc.count_contacts(""), 0)
        self.assertEqual(agent_atc.count_contacts("no contacts"), 0)

    def test_single(self):
        self.assertEqual(agent_atc.count_contacts(
            "Enfield11 (P-51D): 6.0 nm on the 332 radial, 4,000 ft, heading 151"), 1)

    def test_two_singles(self):
        self.assertEqual(agent_atc.count_contacts(
            "A (P-51): 6.0 nm on the 332 radial, 4,000 ft, heading 151 | "
            "B (P-51): 8.0 nm on the 300 radial, 5,000 ft, heading 120"), 2)

    def test_a_formation_counts_its_ships_not_its_line(self):
        # The regression this exists for: radar collapses a four-ship into ONE
        # line, so counting lines left the engine switched off for the arrival
        # that most needs sequencing.
        self.assertEqual(agent_atc.count_contacts(
            "Enfield11 (P-51D) IN FORMATION with Enfield12, Enfield13, Enfield14 "
            "— 4 ships, lead 12.3 nm on the 332 radial, 6,004 ft, heading 151"), 4)

    def test_formation_plus_a_single(self):
        self.assertEqual(agent_atc.count_contacts(
            "E11 (P-51D) IN FORMATION with E12 — 2 ships, lead 12.3 nm on the "
            "332 radial, 6,004 ft, heading 151 | "
            "Hawk (P-51D): 8.0 nm on the 300 radial, 5,000 ft, heading 120"), 3)


class TestRoster(unittest.TestCase):
    """The SRS name lookup, which is the free identity anchor on every packet."""

    def roster_of(self, *lines):
        from marshall.srs.client import SRSClient
        c = SRSClient.__new__(SRSClient)
        c.roster = {}
        for line in lines:
            c._harvest_roster(line)
        return c.roster

    def test_full_client_list(self):
        self.assertEqual(
            self.roster_of(b'{"MsgType":2,"Clients":['
                           b'{"ClientGuid":"aaa","Name":"Sockeye"},'
                           b'{"ClientGuid":"bbb","Name":"Bandit"}]}'),
            {"aaa": "Sockeye", "bbb": "Bandit"})

    def test_single_client_update(self):
        # How a late-joining wingman becomes known to an already-connected bridge.
        self.assertEqual(
            self.roster_of(b'{"MsgType":3,"Client":{"ClientGuid":"ccc","Name":"Ranger"}}'),
            {"ccc": "Ranger"})

    def test_malformed_messages_are_survivable(self):
        # A live sortie logged two wingmen as raw GUID stubs because this thread
        # had died on an earlier line -- silently, while everything else kept
        # working. Nothing here may raise.
        for bad in (b"null", b"[]", b"not json", b'{"Clients":"nope"}',
                    b'{"Client":5}', b"", b'{"Clients":[1,2]}'):
            with self.subTest(bad=bad):
                self.assertEqual(self.roster_of(bad), {})

    def test_a_bad_message_does_not_lose_a_good_one(self):
        self.assertEqual(
            self.roster_of(b"not json",
                           b'{"MsgType":3,"Client":{"ClientGuid":"ddd","Name":"Hawk"}}'),
            {"ddd": "Hawk"})


class TestSimpleResponse(unittest.TestCase):
    def test_radio_check_is_answered_without_the_agent(self):
        out = agent_atc.simple_response("Batumi Approach, Pony one one, radio check")
        self.assertIsNotNone(out)
        self.assertIn("loud and clear", out.lower())

    def test_substance_goes_to_the_agent(self):
        self.assertIsNone(
            agent_atc.simple_response("Pony one one, over the beacon, four thousand"))

class TestTransmitterIdentity(unittest.TestCase):
    """The radio is the anchor: its NAME is irrelevant, its stability is not."""

    def setUp(self):
        agent_atc._transmitters.clear()

    def test_learns_the_callsign_a_radio_uses(self):
        self.assertEqual(
            agent_atc.transmitter_callsign("g1", "Batumi Approach, Pony one one, "
                                           "flight of four, checking in."),
            "Pony 1-1")

    def test_remembers_it_when_the_callsign_is_missing(self):
        # The whole point: Whisper drops or mangles callsigns constantly, and
        # the controller should still know who is talking.
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        self.assertEqual(
            agent_atc.transmitter_callsign("g1", "uhh, level four thousand"),
            "Pony 1-1")

    def test_a_numbered_phrase_does_not_steal_the_identity(self):
        # "level four thousand" must not rebind the radio to an aircraft called
        # "Level 4" -- a false positive silently reassigns a transmitter.
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        for noise in ("descending to four thousand",
                      "heading three zero four",
                      "runway one two in sight",
                      "passing five thousand"):
            with self.subTest(noise=noise):
                self.assertEqual(agent_atc.transmitter_callsign("g1", noise),
                                 "Pony 1-1")

    def test_a_radio_can_re_identify(self):
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        self.assertEqual(
            agent_atc.transmitter_callsign("g1", "Pony one two, level five thousand"),
            "Pony 1-2")

    def test_radios_are_kept_apart(self):
        agent_atc.transmitter_callsign("g1", "Pony one one, checking in.")
        agent_atc.transmitter_callsign("g2", "Pony one three, level five thousand.")
        self.assertEqual(agent_atc.transmitter_callsign("g1", "say again"), "Pony 1-1")
        self.assertEqual(agent_atc.transmitter_callsign("g2", "say again"), "Pony 1-3")

    def test_an_unheard_radio_is_honestly_unknown(self):
        self.assertEqual(agent_atc.transmitter_callsign("g9", "mumble"), "")

    def test_no_guid_is_harmless(self):
        self.assertEqual(agent_atc.transmitter_callsign(None, "Pony one one"), "")

if __name__ == "__main__":
    unittest.main()
