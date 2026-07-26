"""Multi-ship rehearsal: two synthetic pilots vs the ATC, no human.

Two SRS clients with distinct identities take turns on one frequency (so they
never step on each other); each transmits its line, then listens for the
controller's reply. This exercises the two-brain separation end to end — the
deterministic engine sequences the holding stack, the agent voices it — the way a
real two-ship arrival would.

    uv run --extra voice python -m marshall.srs.rehearsal --srs $SRS_HOST 132.0
"""

from __future__ import annotations

import time

from marshall import config

# (SRS identity, Polly voice, spoken line). Two ships arrive: Pony 1-1 lands
# while Pony 2 holds behind it, then Pony 2 is cleared once the letdown frees.
SCRIPT = [
    ("Sockeye", "Joey", "Batumi Approach, Pony one one, checking in."),
    ("Bandit", "Justin", "Batumi Approach, Pony two, checking in."),
    ("Sockeye", "Joey", "Pony one one, over the beacon, four thousand, inbound."),
    ("Bandit", "Justin", "Pony two, over the beacon, four thousand, request approach."),
    ("Sockeye", "Joey", "Pony one one, field in sight, landing."),
    ("Bandit", "Justin", "Pony two, request approach."),
]

# A four-ship recovery. Lead does the talking while they are together, then each
# wingman speaks for himself once they are broken up -- from his OWN SRS client,
# because four aeroplanes are four radios. That is deliberately the case that
# used to make the controller challenge a wingman as an impostor.
FORMATION = [
    ("Sockeye", "Joey",    "Batumi Approach, Pony one one, flight of four, checking in."),
    ("Sockeye", "Joey",    "Pony one one, flight of four, over the beacon, six thousand, inbound."),
    ("Bandit",  "Justin",  "Pony one two, level four thousand."),
    ("Ranger",  "Stephen", "Pony one three, level five thousand."),
    ("Sockeye", "Joey",    "Pony one one, established inbound on the beam, starting my clock."),
    ("Sockeye", "Joey",    "Pony one one has the field, runway in sight."),
    ("Bandit",  "Justin",  "Pony one two, request approach."),
    ("Ranger",  "Stephen", "Pony one three, say my altitude."),
]

# THE BREAK-UP IDENTIFICATION CASE, and the reason it needs real radios.
#
# Live, a two-ship split for individual approaches and the controller went on
# calling one of them "Pony 1" -- the FLIGHT -- and the other "Pony 1-1".
# Adjacent, confusable, and the first of those names did not refer to an
# aeroplane at all: it referred to a formation that had just stopped existing.
#
# Lead deliberately identifies as the FLIGHT while they are together, which is
# correct and is what a real lead does. The whole test is what happens after the
# split: each aeroplane must end up on its own member callsign, from its own
# radio, and the controller must stop using the flight name for anybody.
#
# It cannot be tested any other way. One process with one SRS client is one
# radio, and a radio is the thing identity is anchored to -- so two aeroplanes
# sharing a client would pass a test that a real pair would fail.
BREAKUP_ID = [
    ("Hoover", "Joey",    "Batumi Approach, Pony one, flight of two, checking in."),
    ("Hoover", "Joey",    "Pony one, flight of two, request the radar approach."),
    ("Hoover", "Joey",    "Pony one, request break-up for individual approaches."),
    # The controller has now asked them to check in individually, in order.
    ("Hoover", "Joey",    "Pony one one, checking in."),
    ("Shooter", "Justin", "Pony one two, checking in."),
    # ...and from here each must be addressed as himself.
    ("Shooter", "Justin", "Pony one two, say my altitude."),
    ("Hoover", "Joey",    "Pony one one, request the approach."),
]

SCRIPTS = {"pair": SCRIPT, "formation": FORMATION, "breakup": BREAKUP_ID}


def run(host: str, freq_mhz: float, script=None, reply_wait: float = 30.0) -> None:
    from marshall.srs import stt, tts
    from marshall.srs.client import AM, SRSClient, radio

    script = script or SCRIPT
    freq_hz = freq_mhz * 1_000_000
    model = stt.load_model()
    voices: dict[str, tts.Voice] = {}
    clients: dict[str, SRSClient] = {}

    def pilot(name: str, voice_id: str):
        if name not in clients:
            voices[name] = tts.Voice(voice_id=voice_id)
            clients[name] = SRSClient(host, name=name, eam_password=config.SRS_EAM_PASSWORD).connect(
                [radio(freq_hz, AM)])
            print(f"[{name}] up ({voice_id})", flush=True)
            time.sleep(1.5)
        return clients[name], voices[name]

    def drain(client):
        # Both clients receive every ATC reply; a pilot waiting its turn buffers
        # the reply meant for someone else. Discard that stale audio right before
        # this pilot transmits, so it only hears its OWN reply.
        client.udp.settimeout(0.0)
        try:
            while True:
                client.udp.recvfrom(4096)
        except OSError:
            pass

    for name, voice_id, line in script:
        client, voice = pilot(name, voice_id)
        drain(client)
        print(f"{name}(tx): {line}", flush=True)
        client.transmit(voice.frames(line), freq_hz, AM)
        pcm, _f = client.recv_utterance(max_wait=reply_wait, silence=1.6)
        heard = stt.transcribe(model, pcm) if (pcm is not None and pcm.size) else "<no reply>"
        print(f"   ATC: {heard}", flush=True)
        time.sleep(2.5)              # let the frequency settle before the next ship
    print("rehearsal complete", flush=True)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--srs":
        which = sys.argv[4] if len(sys.argv) > 4 else "pair"
        run(sys.argv[2], float(sys.argv[3]), SCRIPTS[which])
    else:
        print("usage: rehearsal.py --srs <host> <freq_mhz> [pair|formation]")
