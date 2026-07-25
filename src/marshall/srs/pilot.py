"""A synthetic SRS pilot -- a scripted voice on the radio so the whole ATC loop
can be tested end to end with no human and no cockpit.

It is the mirror of the ATC bridge: Polly SPEAKS the pilot's calls onto the same
frequency, and Whisper TRANSCRIBES whatever the controller says back. Point it at
the same SRS server + frequency the agent bridge is listening on and it will hold
a conversation with the controller by itself.

    uv run --extra voice python -m marshall.srs.pilot --srs $SRS_HOST 132.0

The default script flies the Batumi letdown; pass your own lines to probe an edge.
"""

from __future__ import annotations

import time

from marshall import config

# A full letdown, the way a pilot actually talks (sloppy, out of order, asking for
# things the plate doesn't have) -- the exact input the rigid parser choked on.
DEFAULT_SCRIPT = [
    "Batumi Approach, Pony one one, request approach.",
    "Pony one one, four thousand, five miles north of the field, inbound.",
    "Pony one one, can I get a DME to the field?",
    "Batumi Approach, Pony one one, station passage, turning outbound three zero zero.",
    "Pony one one, level platform two thousand.",
    "Pony one one, established inbound on the beam, starting my clock.",
    "Pony one one has the field, runway in sight.",
    "Pony one one is down and stopped.",
]


def run(host: str, freq_mhz: float, voice_id: str = "Joey",
        srs_name: str = "Sockeye", script: list[str] | None = None,
        reply_wait: float = 25.0) -> None:
    from marshall.srs import stt, tts
    from marshall.srs.client import AM, SRSClient, radio

    # srs_name is the SRS client identity ("Sockeye"); the *voice* still calls
    # itself whatever the script says ("Pony 1-1"). Deliberately different, to
    # exercise the three-way SRS / callsign / radar correlation.
    script = script or DEFAULT_SCRIPT
    freq_hz = freq_mhz * 1_000_000
    voice = tts.Voice(voice_id=voice_id)                 # a different mouth than ATC
    model = stt.load_model()
    client = SRSClient(host, name=srs_name, eam_password=config.SRS_EAM_PASSWORD).connect(
        [radio(freq_hz, AM)])
    print(f"synthetic pilot: SRS '{srs_name}', voicing its script, on "
          f"{freq_mhz:.3f} (voice {voice_id})", flush=True)
    time.sleep(2)                                         # let registration settle

    for line in script:
        print(f"PILOT(tx): {line}", flush=True)
        client.transmit(voice.frames(line), freq_hz, AM)
        # Listen for the controller's reply, transcribe it, then key the next call.
        pcm, _f = client.recv_utterance(max_wait=reply_wait, silence=1.5)
        if pcm is None or not pcm.size:
            print("  ATC(heard): <no reply>", flush=True)
        else:
            # stt.transcribe, not a hand-rolled call: it carries the domain prompt
            # that keeps Whisper from turning "Batumi" into "But to me".
            print(f"  ATC(heard): {stt.transcribe(model, pcm)}", flush=True)
        time.sleep(1.5)                                   # brief beat between calls
    print("synthetic pilot: script complete", flush=True)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--srs":
        v = sys.argv[4] if len(sys.argv) > 4 else "Joey"
        run(sys.argv[2], float(sys.argv[3]), v)
    else:
        print("usage: pilot.py --srs <host> <freq_mhz> [voice]")
