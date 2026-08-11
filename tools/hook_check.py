"""Ask the controller to call you back, then see whether he does.

#25 triage. The machinery exists -- the agent has a `set_hook` tool, the
director holds pending hooks, the bridge polls `/hooks/due` every couple of
seconds and re-invokes the agent with the reason -- and nothing in a full day of
live sorties exercised it. So the first question is not "is it broken" but "does
it work at all", and a pilot asking for a callback is the shortest path to an
answer:

    "Batumi Approach, Hoover one one, I will be busy for a minute --
     can you call me back in about a minute?"

    uv run python tools/hook_check.py

Three things can go wrong and they are worth telling apart, because each has a
different fix:

  the agent never sets one   it acknowledged and promised nothing. A prompt
                             problem: it does not know the tool applies here.
  set but never fired        the scheduler or the endpoint. A wiring problem.
  fired but said nothing     it woke and decided not to speak. A judgement
                             problem, and the hardest to see from the cockpit --
                             indistinguishable from the first.

Reads the bridge log alongside the radio for exactly that reason.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# HOSTS AND PORTS COME FROM `marshall.config`, which reads the .env files
# the rest of the system reads. This is a public repo: a LAN address
# written down here is both a leak and a second opinion.
sys.path.insert(0, str(ROOT / "src"))
from marshall import config as _config

sys.path.insert(0, str(ROOT / "src"))


LOG = os.environ.get("MARSHALL_BRIDGE_LOG", "/tmp/marshall-bridge-live.log")
HZ = float(os.environ.get("MARSHALL_FREQ", "124.0")) * 1e6
WAIT = int(os.environ.get("HOOK_WAIT", "150"))


def main() -> int:
    from marshall import config
    from marshall.radio import stt, tts
    from marshall.radio.client import AM, SRSClient, radio

    model = stt.load_model()
    voice = tts.Voice(voice_id="Joey")
    c = SRSClient(_config.SRS_HOST, name="Hoover",
                  eam_password=config.SRS_EAM_PASSWORD).connect([radio(HZ, AM)])
    time.sleep(7)
    mark = os.path.getsize(LOG) if os.path.exists(LOG) else 0

    ask = ("Batumi Approach, Hoover one one, I am going to be busy for a "
           "minute. Can you call me back in about a minute?")
    print(f"PILOT: {ask}")
    c.transmit(voice.frames(ask), HZ, AM)
    pcm, _ = c.recv_utterance(max_wait=32, silence=1.6)
    ack = stt.transcribe(model, pcm) if pcm is not None and pcm.size else ""
    print(f"   <- {ack.strip() or '<silence>'}\n")

    print(f"saying nothing for {WAIT}s, listening for an unprompted call...")
    heard, t0 = [], time.monotonic()
    while time.monotonic() - t0 < WAIT:
        pcm, _ = c.recv_utterance(max_wait=WAIT - (time.monotonic() - t0),
                                  silence=1.6)
        if pcm is None or not pcm.size:
            break
        said = stt.transcribe(model, pcm)
        if said.strip():
            heard.append((int(time.monotonic() - t0), said.strip()))
            print(f"   +{heard[-1][0]:>3}s  {heard[-1][1]}")

    with open(LOG, encoding="utf-8", errors="replace") as fh:
        after = fh.read()[mark:]
    # The agent's tool return lives in the DIRECTOR's log, not the bridge's, so
    # looking for it here reports "never promised anything" even when a callback
    # arrives. The signal that matters is on the radio: an unprompted
    # transmission after the pilot stopped talking.
    set_it = "hook" in ack.lower() or "call you back" in ack.lower()
    fired = "ATC[hook" in after or "hook/" in after

    print("\n--- where it stands ---")
    print(f"  agent set a hook      : {'yes' if set_it else 'NO'}")
    print(f"  a hook fired          : {'yes' if fired else 'no'}")
    print(f"  unprompted call heard : {'yes' if heard else 'NO'}")
    if not set_it:
        print("\n  VERDICT: it never promised anything. A PROMPT problem -- the\n"
              "  agent does not know set_hook applies to a request like this.")
    elif not heard:
        print("\n  VERDICT: promised and did not deliver. Wiring or judgement --\n"
              "  check the bridge scheduler and whether the wake produced a call.")
    else:
        print("\n  VERDICT: promised and delivered.")
    try:
        c.close()
    except Exception:
        pass
    return 0 if heard else 1


if __name__ == "__main__":
    raise SystemExit(main())
