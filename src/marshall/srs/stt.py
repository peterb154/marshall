"""Shared speech-to-text: one Whisper config, one domain prompt, one transcribe.

The ATC bridge, the synthetic pilot, and the older loops each grew their own copy
of the Whisper model setup and the domain-priming prompt. They live here now so a
vocabulary fix (or a model-size change) happens in one place.

`domain_prompt` builds the priming text from what is actually in play -- the
stations on the ladder, the fixes on the route, the callsigns that have keyed a
mic -- because the mangling lands squarely on the proper nouns and the proper
nouns are knowable. A squadron night produced "Century" and "Sensory" for
Sentry, "in-grass" for ingress, and one garble that bound a radio to "Waypoint
3" and filled the separation stack with aeroplanes that did not exist.

WHISPER_PROMPT remains as the static fallback for callers with no profile to
hand (the synthetic pilot, the rehearsal harness).
"""

from __future__ import annotations

WHISPER_PROMPT = (
    "Radio calls to Batumi Approach. Mustang callsigns: Pony one one, Pony two, "
    "Pony three, Pony four (the number is spoken as digits, e.g. 'Pony two', not "
    "'Pony do'). Terms: checking in, request approach, holding, over the beacon, "
    "established on the beam, platform, missed approach, going around, field in "
    "sight, thousand feet, DME, Oscar Sierra, Batumi, Kobuleti, do you copy, how "
    "do you read.")


def domain_prompt(stations=(), fixes=(), callsigns=(), field: str = "Batumi",
                  plans=()) -> str:
    """Prime Whisper with the proper nouns that are actually on the air.

    Priming is not a spell-checker: it biases the decoder toward words it has
    just been shown, which is why it works so well on exactly the tokens that
    matter here -- names. Everything else in a radio call is ordinary English
    that Whisper already handles.

    Kept SHORT and front-loaded with names. The prompt window is small (a few
    hundred tokens) and anything past it is silently dropped, so a long list of
    phraseology would push out the callsigns it exists to protect.
    """
    # SPOKEN forms, not canonical ones. Whisper is decoding speech, so priming
    # it with "Pony 1-1" teaches it nothing about the sound a pilot makes --
    # "Pony one one" does. Same for the fixes: a chart says FEET WET and a pilot
    # says "feet wet".
    bits = [f"Radio calls at {field.title()}."]
    if callsigns:
        bits.append("Callsigns: " + ", ".join(dict.fromkeys(callsigns)) + ".")
    if stations:
        bits.append("Controllers: " + ", ".join(dict.fromkeys(stations)) + ".")
    if fixes:
        bits.append("Fixes: "
                    + ", ".join(dict.fromkeys(f.title() for f in fixes)) + ".")
    if plans:
        # The spoken name of a filed plan -- "Samovar One". It is said early in a
        # transmission and it is the whole key to which plan he wants, so a
        # mangled one does not cost a word, it clears him on somebody else's
        # route.
        bits.append("Flight plans: " + ", ".join(dict.fromkeys(plans)) + ".")
    bits.append(
        "Numbers are spoken as digits. Terms: checking in, request approach, "
        "holding, established, platform, missed approach, going around, field "
        "in sight, cleared to land, altimeter, steerpoint, waypoint, ingress, "
        "egress, say again, how do you read.")
    return " ".join(bits)


def load_model(size: str = "base.en"):
    """The CPU Whisper model the whole voice stack shares."""
    from faster_whisper import WhisperModel
    return WhisperModel(size, device="cpu", compute_type="int8")


def transcribe(model, pcm, prompt: str = WHISPER_PROMPT) -> str:
    """int16 PCM -> text, primed with the domain prompt. '' if nothing was said."""
    import numpy as np

    segs, _ = model.transcribe(pcm.astype(np.float32) / 32768.0, language="en",
                               initial_prompt=prompt)
    return " ".join(s.text for s in segs).strip()
