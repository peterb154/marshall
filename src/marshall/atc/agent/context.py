"""What the controller is HANDED, and what he REMEMBERS. [CTX-1] / #43

    "should we have a conversation history maintained that doesnt include all
     that telemetry data, so that the controller can maintain a conversation
     AND do the job at hand?"

Measured on two real sessions before this existed: the average user message sent
to Sonnet was **2,522 characters, of which 74 were the pilot's actual words**.
The other 2,448 were the situation block -- RADAR, TRANSMITTER, STRIP, YOU ARE,
VISUAL APPROACHES -- and it was not merely sent, it was KEPT. Every turn in the
window carried the radar picture as it stood when that turn happened.

Two costs, and the second is worse than the money:

  MEMORY.    `SlidingWindowConversationManager` counts MESSAGES. At 2.56
             messages per transmission a window of 16 held about six calls --
             and fewer exactly when the controller was busy, because that is
             when he reaches for `identify`, `vector` and `set_hook` and each
             tool call costs two more messages. His memory shortened under load.

  STALENESS. An old turn carries an old scope. The model could see
             `RADAR: no contacts` from five minutes ago sitting beside a current
             picture with four aircraft in it, and had no way to tell which was
             now. That is contradictory state in the context, paid for by the
             token.

THE RULE THIS ESTABLISHES, and it is one line: everything that is STATE is
injected fresh on every call and never stored; only DIALOGUE is remembered.

    SITUATION      radar, strip, phase, who you are     re-derived, never kept
    CONVERSATION   the pilot's words and the replies    kept, and only this

Which is the pattern `marshall-atc` already used for RADAR and CONTROLLER, extended
one step further: it re-derives them per call anyway, so keeping the old copies
was never buying anything.

WHY THIS IS NOT A REWRITE OF THE WINDOW. The obvious move is to count exchanges
rather than messages. It is the wrong move: `SlidingWindowConversationManager`
preserves tool-use/tool-result PAIRS and refuses invalid window states, and an
orphaned `toolResult` is a hard API error -- a dead radio, not a tidier unit. So
the trimming is inherited untouched and only the SIZE of what it trims is
changed. Scrubbing is what makes that safe: the reason a message count was a bad
unit is that messages varied 6x in size, and after this they do not.

THE ONE HAZARD, and it is subtle. `apply_management` runs after every event loop
cycle -- including between the tool calls WITHIN a single turn. Scrub too
eagerly and the model composes its final answer having lost the radar picture it
was handed at the start of that same turn, which is a guidance bug that would
look like the model ignoring the scope. So the newest situation-bearing message
is never scrubbed: while a turn is in flight that is the turn's own message, and
it only becomes eligible once the next transmission arrives.
"""

from __future__ import annotations

import logging
import re

try:
    from strands.agent.conversation_manager import SlidingWindowConversationManager
except ImportError:                     # importable without strands (tests),
    class SlidingWindowConversationManager:   # the same shim hooks.py uses
        def __init__(self, window_size: int = 40, **kwargs):
            self.window_size = window_size

        def apply_management(self, agent, **kwargs) -> None:
            pass

        def restore_from_session(self, state):
            # The real class has one and validates the persisted class name
            # against its own. The shim has nothing to validate, so it accepts
            # whatever it is given -- and having the METHOD at all is the point:
            # without it the subclass's `super()` call raises AttributeError,
            # which is a different failure from the one it is there to absorb.
            self.removed_message_count = (
                (state or {}).get("removed_message_count", 0)
                if isinstance(state, dict) else 0)
            return None

# Where the pilot's words start in a message assembled by `marshall-atc`. Everything
# before it is situation, re-derived on the next call and worthless afterwards.
_PILOT = "PILOT:"

# A hook firing is the other shape `marshall-atc` sends. Its RADAR line is situation
# for exactly the same reason; the promise itself is the part worth keeping.
_EVENT_RADAR = re.compile(r"\nRADAR:.*?(?=\nMake the radio call now|\Z)", re.S)

# How many messages the window keeps. THE NUMBER IS DERIVED, not picked.
#
# The scenario it has to survive is the one the pilot wrote, where a promise
# made in the second transmission must still be true in the fifth:
#
#     "approach, sockeye, i have a question"
#     "sockeye, approach, standby"
#     "andre, approach, turn left 120 descend 2000"      <- another aeroplane
#     "descend 2000 turn 120"                            (andre)
#     "sockeye, approach, go ahead with questions"
#
# Five transmissions. A plain exchange is 2 messages, one with a tool call is 4,
# two tool calls is 6 -- and the vectoring call in the middle almost certainly
# uses one. So the scenario itself is 12 to 16 messages, which is why a window of
# 16 sat exactly on the edge of failing it and nothing would have reported it.
#
# So the scenario itself is 16 messages at its worst -- which is why a window of
# 16 sat exactly on the edge of failing it, evicting the question at about the
# moment it fell due, and nothing would have reported that.
#
# Measured by replaying a real session at each candidate. The only baseline that
# means anything is what it cost BEFORE this file existed: 6,613 tokens a call,
# at a window of 16 with the situation still in every remembered turn.
#
#     window   ~tokens   vs that   calls held
#         16     2,501      -62%          6.2
#         24     3,470      -48%          9.4     <- chosen
#         32     4,565      -31%         12.5
#         40     5,858      -11%         15.6
#
# THE WINDOW IS SHARED BY EVERYONE ON THE FREQUENCY -- one session per channel,
# which is the right model for a controller and the thing that decides this
# number. "9.4 calls" is nine calls TOTAL, so a two-ship gets about 4.7 each and
# a four-ship about 2.3. The scenario needs the question to survive three
# intervening transmissions, so 24 clears it for two pilots with roughly one
# call to spare, and 16 does not clear it at all.
#
# Starting here rather than higher because none of it has been flown. Card row K3
# is what says whether it is short; raising it is this line.
log = logging.getLogger(__name__)

WINDOW = 24


def strip_situation(text: str) -> str:
    """One message, reduced to the part worth remembering.

    Returns the text unchanged when there is no situation block in it -- an
    assistant reply, a tool result, or a message some other caller assembled.
    Never raises: this runs on the hot path and a malformed message must cost a
    little context, not the transmission.
    """
    if not text:
        return text
    cut = text.find(_PILOT)
    if cut != -1:
        return text[cut:]
    if text.startswith("EVENT --"):
        return _EVENT_RADAR.sub("", text, count=1)
    return text


def _has_situation(text: str) -> bool:
    return bool(text) and (_PILOT in text or text.startswith("EVENT --"))


def scrub(messages: list) -> int:
    """Strip the situation from every turn except the newest. Returns how many.

    Modifies in place, because that is what `apply_management` is handed and
    what strands expects to keep. The newest situation-bearing message is
    exempt: mid-turn it IS this turn's, and the model still needs it to answer.
    """
    newest = -1
    for i, m in enumerate(messages):
        for block in (m.get("content") or []):
            if isinstance(block, dict) and _has_situation(block.get("text", "")):
                newest = i
    if newest < 0:
        return 0

    n = 0
    for i, m in enumerate(messages):
        if i == newest:
            continue
        for block in (m.get("content") or []):
            if not isinstance(block, dict):
                continue
            text = block.get("text", "")
            if not _has_situation(text):
                continue
            shorter = strip_situation(text)
            if shorter != text:
                block["text"] = shorter
                n += 1
    return n


class RadioContext(SlidingWindowConversationManager):
    """The sliding window, plus: history keeps the words and drops the scope.

    Everything about WHICH messages survive is inherited -- see the note above on
    why the tool-pair handling is not worth reimplementing. This only changes
    what is left inside the ones that do.
    """

    def __init__(self, window_size: int = WINDOW, **kwargs):
        super().__init__(window_size=window_size, **kwargs)

    def apply_management(self, agent, **kwargs) -> None:
        # Scrub FIRST, so the window is applied to what will actually be sent
        # rather than to messages that are about to shrink.
        scrub(agent.messages)
        super().apply_management(agent, **kwargs)

    def restore_from_session(self, state):
        """A session written by a DIFFERENT manager must not take ATC off air.

        The base class raises `ValueError("Invalid conversation manager state.")`
        when the persisted `__name__` is not this class's -- a perfectly sound
        check, and a fatal one here. Introducing this subclass renamed the
        manager, so every session that existed beforehand became unrestorable,
        `/atc` answered 500 to every transmission, and the controller went
        silent on the radio. Measured live, 30 July: one reply on check-in and
        nothing after it, on a frequency with a pilot on it who could only
        conclude the whole system was dead.

        What the state carries is `removed_message_count` -- bookkeeping for how
        much history has already been trimmed. Losing it re-trims a few
        messages. That is the entire cost, and it is nothing set against a
        controller who does not answer.

        So: take the count when it is there, ignore the rest, and say so in the
        log rather than silently. The first turn afterwards persists our own
        state and the mismatch never recurs.
        """
        try:
            return super().restore_from_session(state)
        # AttributeError included: on a machine without strands the base is a
        # shim, and a fallback that itself throws is not a fallback. Found by
        # the regression test for this very function, which is the argument for
        # having written one.
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            got = (state or {}).get("__name__") if isinstance(state, dict) else None
            log.warning(
                "conversation state from %r cannot be restored into %s (%s); "
                "starting this session's window fresh rather than failing the "
                "turn", got, self.__class__.__name__, e)
            self.removed_message_count = (
                (state or {}).get("removed_message_count", 0)
                if isinstance(state, dict) else 0)
            return None
