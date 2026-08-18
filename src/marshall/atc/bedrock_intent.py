"""Haiku (Bedrock) intent classifier -- the LLM callable for intents.parse.

Per DESIGN.md, Haiku parses EVERY call: it turns one Whisper transcription into a
structured `Intent` via Bedrock's tool-use structured output (the model is forced
to emit the INTENT_SCHEMA). It is still only ears -- it classifies what the pilot
said and normalises the numbers/callsign; it never decides a clearance.

    uv run --extra voice python -m marshall.atc.bedrock_intent
"""

from __future__ import annotations

import os

from marshall.atc import intents

# Sonnet, not Haiku. This classifier is separation-critical -- it decides which
# leg of the approach a call belongs to and whether a flight is a formation, and
# the deterministic controller acts on the answer. Benched over the phrasing
# pilots actually use (tools/classify_bench.py): Sonnet 17/17 at 2.2s, Haiku
# 16/17 at 1.0s. The one Haiku misses is a transmission that genuinely says two
# things at once, and it resolves it as a request rather than a position report
# -- which would skip a leg of the letdown.
#
# The latency is only paid when there is traffic: the bridge runs the classifier
# only once the separation engine is engaged (>=2 contacts), so a single ship
# never sees it. Slower exactly when accuracy matters is the right trade.
MODEL_ID = os.environ.get(
    "MARSHALL_INTENT_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")

_client = None


def _bedrock():
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("bedrock-runtime", region_name=REGION)
    return _client


def bedrock_llm(transcript: str, system: str, schema: dict) -> dict:
    """(transcript, system, schema) -> dict -- the callable intents.parse expects.

    Forces the model to call one `intent` tool whose input schema IS the Intent,
    so the reply is guaranteed-shaped structured data, never free text.
    """
    resp = _bedrock().converse(
        modelId=MODEL_ID,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": transcript}]}],
        toolConfig={
            "tools": [{"toolSpec": {
                "name": "intent",
                "description": "Report the single intent of the pilot's transmission.",
                "inputSchema": {"json": schema},
            }}],
            "toolChoice": {"tool": {"name": "intent"}},
        },
        inferenceConfig={"maxTokens": 200, "temperature": 0},
    )
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise ValueError("model returned no intent tool call")


def classify(transcript: str) -> intents.Intent:
    """Transcription -> Intent, Haiku for every call (no regex)."""
    data = bedrock_llm(transcript, intents.LLM_SYSTEM, intents.INTENT_SCHEMA)
    return intents.Intent(
        intents.IntentKind.coerce(data.get("kind", "")),
        intents.normalize_callsign(data.get("callsign", "")),
        data.get("altitude_ft"),
        confidence=0.9,
        transcript=transcript,
        # Clamp: a formation is four ships at most, and a model that hallucinates
        # a size would otherwise fabricate wingmen the controller then separates.
        flight_size=max(1, min(4, int(data.get("flight_size") or 1))),
        visual=data.get("visual"),
        # WHAT HE SAYS HE WANTS, verbatim, so it can be written down and the
        # next controller inherits it instead of asking again. See
        # docs/STATE.md -- this is the field a pilot filled on every call and
        # nothing recorded.
        wants=(data.get("wants") or "").strip()[:120],
        # ASKED FOR AND THROWN AWAY. `INTENT_SCHEMA` has described this field
        # to the model since it was added, the model returns it correctly, and
        # this constructor did not read it -- so `Intent.atis_letter` was
        # always "" and the only writer of `ac.atis_letter` had nothing to
        # write. A closed loop with no source: `hydrate` restores the column,
        # the board flushes it from the field, and nothing ever put a letter
        # in. The controller could not stop asking, and on 18 August it asked
        # five times in three minutes.
        #
        # Same shape as `wants` above -- a field a pilot fills on every call
        # and nothing records. That one was found by reading `STATE.md`; this
        # one needed a sortie. See the schema-coverage test.  [#180]
        atis_letter=(data.get("atis_letter") or "").strip()[:12],
    )


if __name__ == "__main__":
    # The real, sloppy transmissions Whisper produced during the first flight,
    # plus the grand/established cases the regex grammar missed.
    samples = [
        "Kobuleti Departure, this is Sockeye on 124.00, how do you read?",
        "Kobuleti Departure, Sockeye is 10,000 level over Kobuleti, outbound heading 030.",
        "Batumi Approach is a Sockeye, 9,000 level over Kobuleti and bound for the approach.",
        "Batumi Tower, Sockeye's turning inbound.",
        "The Tumi Tower Sockeye is going missed.",
        "Batumi Tower, Sockeye has the runway.",
        "pony two, passing four grand at the beacon",
        "uhh Batumi Pony 3 is, uh, established",
    ]
    for s in samples:
        it = classify(s)
        alt = f" @{it.altitude_ft}" if it.altitude_ft else ""
        print(f"  {it.kind.value:16} {it.callsign or '?':10}{alt:8} <- {s!r}")
