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

# The radar approach, which is a different conversation and not the letdown with
# words changed. On an ASR the controller navigates and the pilot flies headings,
# so almost everything the pilot says is a readback -- the calls he originates
# are the request, the position report that gets him identified, and the field in
# sight. Reading back is the point: it is what proves the numbers arrived, and
# the two-brain seam lives exactly here, since a controller who paraphrases the
# engine's altitudes rather than voicing them is a controller the readback cannot
# catch.
ASR_SCRIPT = [
    "Batumi Approach, Pony one one, request the radar approach, runway one three.",
    "Pony one one, three thousand, one five miles northwest of the field.",
    "Pony one one, say again the heading?",
    "Heading one six nine, Pony one one.",
    "Pony one one, established on the final approach course.",
    "Pony one one, leaving two thousand.",
    "Pony one one, say my distance to the runway?",
    "Pony one one has the runway in sight.",
]

SCRIPTS = {"ndb": DEFAULT_SCRIPT, "asr": ASR_SCRIPT}


def live_script(group: str, profile=None) -> list[str]:
    """A script that says TRUE things, read off the aircraft's actual position.

    The fixed scripts are a tape recorder, and a tape recorder makes a useless
    test subject. Run against a real aeroplane, one of them announced
    "established on the final approach course" while the aircraft was five miles
    the wrong side of the field flying its missed approach. The controller
    correctly said "negative, not established" -- and that is the problem: with
    a pilot who lies, a right answer and a wrong one look identical, so the
    transcript proves nothing about the ATC.

    So the position report comes from the sim, and the calls a pilot only makes
    when something is true -- established, runway in sight -- are only made when
    it is. What stays scripted is the part that is genuinely the pilot's choice:
    what he asks for.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "tools"))
    from asr_autopilot import lead_of, position_of      # the same radar we vector on
    import grpc
    import os

    from marshall.atc import asr
    from marshall.core import route as R
    profile = profile or R.BATUMI_ASR

    addr = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
    with grpc.insecure_channel(addr) as ch:
        unit = lead_of(ch, group)
        if unit is None:
            return [f"Batumi Approach, {group}, no joy on my own position, "
                    "request radar contact."]
        pos = position_of(unit, profile)

    g = asr.guide(pos, profile)
    compass = ["north", "north east", "east", "south east",
               "south", "south west", "west", "north west"]
    where = compass[int((pos.radial_deg + 22.5) % 360 // 45)]
    alt = int(round(pos.alt_ft / 100.0) * 100)

    lines = [
        f"Batumi Approach, Pony one one, request the radar approach, runway "
        f"{profile.runway}.",
        f"Pony one one, {_spoken_alt(alt)}, {_spoken_num(round(pos.range_nm))} "
        f"miles {where} of the field.",
        "Pony one one, say the altimeter?",
    ]
    if g.established:
        lines.append("Pony one one, established on the final approach course.")
    else:
        lines.append("Pony one one, not established yet, say my position?")
    lines.append("Pony one one, say my distance to the runway?")
    return lines


def _spoken_num(n: int) -> str:
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine"]
    return " ".join(words[int(d)] for d in str(int(n)))


def _spoken_alt(ft: int) -> str:
    if ft >= 1000 and ft % 1000 == 0:
        return f"{_spoken_num(ft // 1000)} thousand"
    return f"{_spoken_num(ft // 100)} hundred" if ft < 1000 else str(ft)


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
        name = sys.argv[5] if len(sys.argv) > 5 else "Sockeye"
        which = sys.argv[6] if len(sys.argv) > 6 else "asr"
        # "live:<group>" reads the aeroplane and tells the truth about it.
        script = (live_script(which.split(":", 1)[1])
                  if which.startswith("live:") else SCRIPTS.get(which))
        run(sys.argv[2], float(sys.argv[3]), v, name, script)
    else:
        print("usage: pilot.py --srs <host> <freq_mhz> [voice] [srs_name] [asr|ndb]")
