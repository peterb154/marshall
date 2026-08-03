"""The broadcast loop: observe, decide, record once, play until it changes.

    "Atis should be its own module probably. But I think it should use the
     bridge to transmit."

WHAT "USE THE BRIDGE" MEANS HERE, and it is a distinction with teeth. This runs
inside the bridge process and uses its SRS connection code -- but NOT its radio.
The bridge serialises every transmission on one `radio_lock`, and paced Opus
frames take real time: a twenty-two second ATIS holding that lock is twenty-two
seconds in which a controller cannot answer anybody. On final, in cloud.

So the ATIS gets its own SRS client. That is what the server expects anyway --
`SRSClient` generates a fresh GUID and unit id per instance precisely because
reusing one makes the server collide stale registrations -- and it is honest
about what is happening: the recording and the controller are two things on the
air, not one thing taking turns.

NOTHING IS INJECTED FOR PURITY. `transmit`, `eval_lua` and `clock` are
parameters because this module must not import the bridge, the gRPC stubs, or a
wall clock. That is the same rule that keeps `atis` a sibling of `atc` rather
than something underneath it, and it is what makes the loop testable without a
sim, a radio or an hour of waiting.

IT RENDERS ONCE PER LETTER. `radio/tts.py` caches on (voice, engine, text), and
the text only changes when the letter does -- so a broadcast repeating every
thirty seconds costs one Polly call an hour rather than one hundred and twenty.
That is not the reason to cache it (a network call on a loop that must not fail
is), but it is the reason the sums are not worth arguing about.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field as _field

from marshall.atis import broadcast, store, weather

# How often the recording goes out. Real ATIS is continuous; this is a
# compromise with a radio that other people are using -- long enough that a
# pilot who tunes in never waits absurdly, short enough not to be a nuisance if
# somebody has the frequency up by mistake.
REPEAT_SEC = 30.0
# How often the weather is re-read. Cheap, and it is what notices the hour
# turning over.
POLL_SEC = 10.0


@dataclass
class Airwave:
    """One field's current broadcast, as the loop holds it in memory."""

    letter: str = ""
    text: str = ""
    frames: list = _field(default_factory=list)
    recorded_at: float = 0.0
    last_played: float = 0.0


def rerecord(field, obs, was, now_sec: float, previous_obs=None) -> tuple[str, bool]:
    """(letter, did it change). The rotation decision, and nothing else.

    Split out so the policy can be tested without a radio: given what is on the
    air and what the weather is, does this get a new letter?
    """
    if not was.letter:
        return broadcast.LETTERS[0], True          # first recording is Alpha
    age = now_sec - was.recorded_at
    if broadcast.due_for_rotation(obs, previous_obs, age):
        return broadcast.next_letter(was.letter), True
    return was.letter, False


def serve(fields, transmit, voice, eval_lua, clock=time.monotonic,
          mission_clock=None, stop=None, sleep=time.sleep,
          repeat_sec: float = REPEAT_SEC, poll_sec: float = POLL_SEC,
          log=print) -> None:
    """Run the broadcast until `stop` is set.

    `fields` are `Field_`s; any without an `atis_mhz` is skipped, which is the
    normal case for an aerodrome that does not broadcast.

    `transmit(frames, mhz)` puts audio on the air. `voice.frames(text)` renders
    it. Neither is imported here -- see the module docstring.
    """
    on_air = {f.name: Airwave() for f in fields if getattr(f, "atis_mhz", 0)}
    live = [f for f in fields if getattr(f, "atis_mhz", 0)]
    if not live:
        log("  atis: no field broadcasts; nothing to do")
        return
    log("  atis: " + ", ".join(f"{f.name} {f.atis_mhz:.3f}" for f in live))
    seen: dict = {}

    while stop is None or not stop.is_set():
        now = clock()
        try:
            observed = weather.observe_fields(live, eval_lua)
        except Exception as e:
            # A weather read that fails must not take the broadcast off the
            # air. The last recording keeps playing, which is exactly what a
            # real ATIS does between observations.
            log(f"  !! atis weather read failed, still playing the last "
                f"recording: {type(e).__name__}: {e}")
            observed = {}

        for f in live:
            obs = observed.get(f.name)
            was = on_air[f.name]
            if obs is not None:
                letter, changed = rerecord(f, obs, was, now, seen.get(f.name))
                if changed:
                    zulu = weather.zulu(mission_clock() if mission_clock else 0)
                    text = broadcast.spoken(obs, letter, zulu)
                    try:
                        frames = voice.frames(text)
                    except Exception as e:
                        log(f"  !! atis render failed for {f.name}: {e}")
                        frames = was.frames          # keep the old recording
                        text, letter = was.text, was.letter
                    was.letter, was.text = letter, text
                    was.frames, was.recorded_at = frames, now
                    try:
                        store.publish(obs, letter, text)
                    except Exception as e:
                        # THE DATABASE MATTERS MORE THAN THE AUDIO HERE. Every
                        # controller reads the runway in use from that row, so
                        # a failed publish is not cosmetic -- it means the
                        # broadcast and the taxi clearance can disagree. Loud.
                        log(f"  !! atis PUBLISH FAILED for {f.name} -- "
                            f"controllers may name a different runway: {e}")
                    log(f"  atis: {f.name} information {letter} "
                        f"({'first' if not seen.get(f.name) else 'new'})")
                seen[f.name] = obs

            if was.frames and now - was.last_played >= repeat_sec:
                was.last_played = now
                try:
                    transmit(was.frames, f.atis_mhz)
                except Exception as e:
                    log(f"  !! atis transmit failed on {f.atis_mhz:.3f}: {e}")

        sleep(poll_sec)
