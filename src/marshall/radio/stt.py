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

def default_prompt() -> str:
    """What to prime Whisper with when nobody has said whose sortie this is.

    THIS USED TO BE A 1944 MUSTANG SORTIE, as a module constant:

        "Radio calls to Batumi Approach. Mustang callsigns: Pony one one,
         Pony two ... over the beacon, ... Oscar Sierra, Batumi, Kobuleti"

    -- the default argument of `transcribe`, so every caller that did not pass
    a prompt primed the recogniser for Mustangs in the circuit at Batumi while
    an F-16 flew out of Kobuleti. Priming with another sortie's names is worse
    than not priming: it biases the transcript toward words that cannot occur.

    Now it is the configured phrases for whatever map is loaded, and nothing
    else -- no aerodrome, no callsigns, no era. See config/speech.toml, the
    theatre files, and docs/CONFIG.md. #137.
    """
    from marshall.core import catalogue
    got = catalogue.recogniser_phrases()
    return "Radio calls. Terms: " + ", ".join(got) + "." if got else ""


def domain_prompt(stations=(), fixes=(), callsigns=(), field: str = "",
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
    # NO DEFAULT AERODROME. This parameter used to default to "Batumi", so a
    # caller who did not know the field primed the recogniser for one -- a
    # Caucasus fact leaking into a theatre-neutral path. Empty primes nothing,
    # which is the honest answer and strictly better than the wrong name.
    bits = [f"Radio calls at {field.title()}." if field else "Radio calls."]
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
    # THE PHRASEOLOGY IS CONFIGURED, not written here. It was a sentence in
    # this file listing "ingress, egress" -- two turning points of one 1944
    # strike sortie -- as though they were aviation terms every pilot says.
    from marshall.core import catalogue
    terms = catalogue.recogniser_phrases()
    if terms:
        bits.append("Numbers are spoken as digits. Terms: "
                    + ", ".join(terms) + ".")
    return " ".join(bits)


def load_model(size: str = "base.en"):
    """The CPU Whisper model the whole voice stack shares."""
    from faster_whisper import WhisperModel
    return WhisperModel(size, device="cpu", compute_type="int8")


def transcribe(model, pcm, prompt: str = "") -> str:
    """int16 PCM -> text, primed with the domain prompt. '' if nothing was said.

    An empty prompt means "you did not tell me who is flying", and the answer
    is the configured phrases for this map -- never another sortie's callsigns.
    See `default_prompt`.
    """
    import numpy as np

    segs, _ = model.transcribe(pcm.astype(np.float32) / 32768.0, language="en",
                               initial_prompt=prompt or default_prompt())
    return " ".join(s.text for s in segs).strip()
