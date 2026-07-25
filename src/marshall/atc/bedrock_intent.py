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

MODEL_ID = os.environ.get(
    "MARSHALL_INTENT_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
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
        intents.IntentKind(data["kind"]),
        intents.normalize_callsign(data.get("callsign", "")),
        data.get("altitude_ft"),
        confidence=0.9,
        transcript=transcript,
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
