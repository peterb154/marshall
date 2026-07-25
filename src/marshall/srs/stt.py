"""Shared speech-to-text: one Whisper config, one domain prompt, one transcribe.

The ATC bridge, the synthetic pilot, and the older loops each grew their own copy
of the Whisper model setup and the domain-priming prompt. They live here now so a
vocabulary fix (or a model-size change) happens in one place.

The prompt is still Batumi-specific -- callsigns and proper nouns to keep Whisper
from mangling "Batumi" into "But to me". Longer term it should be generated from
route.py (the field's callsigns and beacon names), the same de-hardcoding the
agent prompt needs; for now it's one shared constant instead of three.
"""

from __future__ import annotations

WHISPER_PROMPT = (
    "Radio calls to Batumi Approach. Mustang callsigns: Pony one one, Pony two, "
    "Pony three, Pony four (the number is spoken as digits, e.g. 'Pony two', not "
    "'Pony do'). Terms: checking in, request approach, holding, over the beacon, "
    "established on the beam, platform, missed approach, going around, field in "
    "sight, thousand feet, DME, Oscar Sierra, Batumi, Kobuleti, do you copy, how "
    "do you read.")


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
