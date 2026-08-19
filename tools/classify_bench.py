"""Bench the intent classifier against the phrasing pilots actually use.

The classifier sits on the separation-critical path: it decides check-in from
beacon report from break-up request, and it is the ONLY way the controller
learns a flight is a formation. A model that reads "flight of four" as one
aeroplane produces a four-ship that never breaks up, in silence.

So measure it rather than trusting it. Runs the same cases through any number of
Bedrock models and prints a per-model scorecard.

    uv run --extra voice python tools/classify_bench.py
    uv run --extra voice python tools/classify_bench.py us.anthropic.claude-sonnet-4-5-20250929-v1:0
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marshall.atc import bedrock_intent, intents

K = intents.IntentKind

# (transcript, expected kind, expected callsign, expected flight size,
#  expected visual answer or None).
# Callsign None = don't care. Drawn from what Whisper actually returned in
# flight plus the formation phrasing we are adding.
CASES = [
    # --- formations: the new, load-bearing cases ------------------------
    ("Batumi Approach, Pony one one, flight of four, checking in.",
     K.CHECK_IN, "Pony 1-1", 4, None),
    # --- THE RADIO CHECK, split out of check_in in #194 so that the fast
    # path is decided by the classifier instead of by a regex. Both
    # directions matter and the second more: calling a check-in a radio
    # check answers it instantly and throws the transmission away, which is
    # what the regex did on 18 August with the word "parking".
    # No callsign at all -- the classifier says so with its own sentinel
    # rather than an empty string, and a controller answers "station
    # calling, loud and clear".
    ("Batumi Approach, radio check.", K.RADIO_CHECK, "<UNKNOWN>", 1, None),
    ("Sockeye, how do you read?", K.RADIO_CHECK, "Sockeye", 1, None),
    ("Kobuleti Departure, this is Sockeye on 124.0, how do you read?",
     K.CHECK_IN, "Sockeye", 1, None),
    ("Sockeye, how do you read, request taxi.", K.REQUEST_TAXI, "Sockeye", 1, None),
    # --- THE VISUAL-SEPARATION CASES ARE GONE, and this file did not run for
    # weeks because of it. `REPORT_CONDITIONS` was deleted by [ARCH-4] "Toss
    # the visual-separation negotiation" -- the question was never the
    # controller's to ask -- and the four cases naming it stayed here, so the
    # bench raised `AttributeError` on import.
    #
    # CLAUDE.md sends you here after touching the schema or the system prompt,
    # "the taxonomy wording moves the score more than the model does". That
    # advice has been unenforceable since, and nothing said so: this is a tool,
    # not a check, so `tools/check.py` never ran it and never reported it
    # skipped. [#194]
    ("Batumi Approach, Pony one flight, four ship, with you.",
     K.CHECK_IN, "Pony 1", 4, None),
    ("Pony one one, flight of two, over the beacon, six thousand.",
     K.REPORT_BEACON, "Pony 1-1", 2, None),
    ("Pony one flight requesting break-up for individual approaches.",
     K.REQUEST_BREAKUP, "Pony 1", 1, None),
    ("Batumi, Pony one one, we'd like to split up for singles.",
     K.REQUEST_BREAKUP, "Pony 1-1", 1, None),
    ("Pony one two, level five thousand.", K.REPORT_BEACON, "Pony 1-2", 1, None),
    ("Pony one three is established inbound.", K.REPORT_BEACON, "Pony 1-3", 1, None),
    ("Pony one four, going around.", K.REPORT_MISSED, "Pony 1-4", 1, None),
    # A single ship must NOT be read as a formation.
    ("Batumi Approach, Pony one one, checking in.", K.CHECK_IN, "Pony 1-1", 1, None),
    ("Sockeye, request approach.", K.REQUEST_APPROACH, "Sockeye", 1, None),

    # --- the real transcripts from the first flight ---------------------
    ("Kobuleti Departure, this is Sockeye on 124.00, how do you read?",
     K.CHECK_IN, "Sockeye", 1, None),
    ("Batumi Approach is a Sockeye, 9,000 level over Kobuleti and bound for the "
     "approach.", K.REPORT_BEACON, "Sockeye", 1, None),
    ("Batumi Tower, Sockeye's turning inbound.", K.REPORT_BEACON, "Sockeye", 1, None),
    ("The Tumi Tower Sockeye is going missed.", K.REPORT_MISSED, "Sockeye", 1, None),
    ("Batumi Tower, Sockeye has the runway.", K.REPORT_LANDED, "Sockeye", 1, None),
    ("pony two, passing four grand at the beacon", K.REPORT_BEACON, "Pony 2", 1, None),
    ("uhh Batumi Pony 3 is, uh, established", K.REPORT_BEACON, "Pony 3", 1, None),
]


def bench(model_id: str) -> tuple[int, float]:
    bedrock_intent.MODEL_ID = model_id
    bedrock_intent._client = None
    good, elapsed = 0, 0.0
    print(f"\n=== {model_id} ===")
    for text, kind, cs, size, visual in CASES:
        t0 = time.monotonic()
        try:
            it = bedrock_intent.classify(text)
        except Exception as e:
            print(f"  ERROR  {type(e).__name__}: {e}")
            continue
        elapsed += time.monotonic() - t0
        bad = []
        if it.kind is not kind:
            bad.append(f"kind={it.kind.value} want {kind.value}")
        if cs is not None and it.callsign != cs:
            bad.append(f"cs={it.callsign!r} want {cs!r}")
        if it.flight_size != size:
            bad.append(f"size={it.flight_size} want {size}")
        if visual is not None and it.visual is not visual:
            bad.append(f"visual={it.visual} want {visual}")
        good += not bad
        print(f"  {'ok  ' if not bad else 'FAIL'} {text[:58]:60} "
              + ("; ".join(bad) if bad else ""))
    n = len(CASES)
    print(f"  -> {good}/{n} correct, {elapsed / max(1, n):.2f}s per call")
    return good, elapsed / max(1, n)


if __name__ == "__main__":
    models = sys.argv[1:] or [
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    ]
    results = [(m, *bench(m)) for m in models]
    print("\n=== scorecard ===")
    for m, good, avg in results:
        print(f"  {good:2}/{len(CASES)}  {avg:.2f}s  {m}")
