"""The fast ATC loop: transcription -> Intent (Haiku) -> deterministic controller
-> clearance, with Claude Code nowhere in the hot path.

This is the runtime the live-flight session stood in for by hand. The routine
call cycle is STT -> classify (Haiku, <1s) -> dispatch to the state machine
(instant, and it decides every clearance) -> Polly -> SRS transmit. ~2-3s, and
the invariant holds: the LLM only classifies, the machine alone clears.

    # brain only, text-driven (no sim, no SRS):
    uv run --extra voice python -m marshall.atc.fast_atc
    # live over SRS on one frequency:
    uv run --extra voice python -m marshall.atc.fast_atc --srs 192.168.0.35 128.0
"""

from __future__ import annotations

from marshall.atc import bedrock_intent, controller as atc, intents
from marshall.core import route as R


def handle(ctl: atc.Controller, transcript: str, classify=bedrock_intent.classify) -> list[str]:
    """One pilot 'over' -> the controller's replies (text). Classify, dispatch,
    drain whatever the state machine decided to say. Empty list = say-again."""
    intent = classify(transcript)
    if not intents.dispatch(ctl, intent):
        return []
    replies = [tx.text for tx in ctl.out]
    ctl.out.clear()
    return replies


def _demo() -> None:
    ctl = atc.Controller(R.BATUMI_APPROACH)
    script = [
        "Batumi Approach, Pony one one checking in",
        "Pony one one over the beacon, four thousand",
        "Pony one one established inbound on the beam",
        "Pony one one going around",
        "Pony one one field in sight, landing",
    ]
    for line in script:
        print(f"\nPILOT: {line}")
        for reply in handle(ctl, line):
            print(f"  ATC: {reply}")


def _run_srs(host: str, freq_mhz: float, voice_id: str = "Joanna") -> None:
    from marshall.srs import stt, tts
    from marshall.srs.client import AM, SRSClient, radio

    freq_hz = freq_mhz * 1_000_000
    ctl = atc.Controller(R.BATUMI_APPROACH)
    voice = tts.Voice(voice_id=voice_id)          # each ATC gets its own Polly voice
    model = stt.load_model()
    client = SRSClient(host, name=R.BATUMI_APPROACH.controller,
                       eam_password="362").connect([radio(freq_hz, AM)])
    print(f"fast ATC live on {freq_mhz:.3f} as {R.BATUMI_APPROACH.controller} "
          f"(voice {voice_id})")
    while True:
        pcm, _f = client.recv_utterance(max_wait=3600)
        if pcm is None or not pcm.size:
            continue
        transcript = stt.transcribe(model, pcm)
        if not transcript:
            continue
        print(f"PILOT: {transcript}", flush=True)
        replies = handle(ctl, transcript)
        if not replies:
            replies = ["Station calling, say again."]
        for reply in replies:
            print(f"  ATC: {reply}", flush=True)
            client.transmit(voice.frames(reply), freq_hz, AM)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--srs":
        voice = sys.argv[4] if len(sys.argv) > 4 else "Joanna"
        _run_srs(sys.argv[2], float(sys.argv[3]), voice)
    else:
        _demo()
