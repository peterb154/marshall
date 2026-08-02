"""The ATIS: one recording, a letter, and a loop.

    "We need to build atis so that it generates one weather recording and loops
     it. Clearance and approach should validate that you have correct atis."

WHY IT IS ONE RECORDING and not a sentence assembled per transmission. That is
what an ATIS IS -- a controller records it, it plays until the weather moves,
and the letter is how a pilot knows whether the one in his head is the one on
the air. Re-rendering it every thirty seconds would be a different thing that
happens to say the same words, and it would cost a network round trip on a loop
that must not fail. `radio/tts.py` caches it, so the render happens once per
letter.

THE LETTER IS THE POINT. "Information Bravo" is a version number a pilot can
say back, and it only works if it means something -- so it rotates on a
MATERIAL change and not on the wind wandering a degree. See
`Observation.same_as`. A letter that changed every minute would train pilots to
ignore it, and then the one time it mattered nobody would notice.

ONE VOICE FOR THE WHOLE THEATRE, on the standard engine.

    "Let's use one voice for all atis to make it cheaper."

Worth being straight about where the saving actually is: one voice rather than
one per field saves almost nothing, because the text differs per aerodrome and
renders per aerodrome either way. The saving is the ENGINE -- standard is four
times cheaper than neural -- and with the cache it is fractions of a cent a
sortie regardless. What one voice really buys is that every field's recording
sounds like the same recording, which is what a synthetic ATIS sounds like.
"""

from __future__ import annotations

from marshall.core import say

# ICAO, and the whole alphabet rather than the first few: a long session with
# changeable weather will walk further down it than you would think, and
# wrapping at F would put two different recordings on the same letter.
LETTERS = (
    "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel",
    "India", "Juliett", "Kilo", "Lima", "Mike", "November", "Oscar", "Papa",
    "Quebec", "Romeo", "Sierra", "Tango", "Uniform", "Victor", "Whiskey",
    "Xray", "Yankee", "Zulu",
)

# A voice nobody controls with, on the cheap engine. Salli is US English and
# standard-tier; every controller voice is spoken for, and an ATIS that sounds
# like one of them is a pilot hearing Tower where there is no Tower.
ATIS_VOICE = "Salli"
ATIS_ENGINE = "standard"


def next_letter(previous: str | None) -> str:
    """The letter after this one, wrapping at Zulu."""
    if not previous:
        return LETTERS[0]
    try:
        return LETTERS[(LETTERS.index(previous) + 1) % len(LETTERS)]
    except ValueError:
        return LETTERS[0]


def spoken(obs, letter: str, zulu: str) -> str:
    """The words. One paragraph, in the order an ATIS says them.

    `zulu` is the observation time as four digits, passed in rather than read
    from a clock: the recording is a fact about a moment, and a function that
    looks up "now" cannot be tested and cannot be regenerated identically.
    """
    parts = [f"{obs.field} information {letter}.",
             f"Time {_digits(zulu)} Zulu."]

    # WIND. Calm is a word, not zero at zero -- "wind zero zero zero at zero"
    # is not something anybody says, and a pilot listening for a runway does
    # not need three noughts first.
    if obs.wind_kt < 1:
        parts.append("Wind calm.")
    else:
        parts.append(f"Wind {say.spell_hdg(obs.wind_from_deg)} at "
                     f"{say.spell_count(obs.wind_kt)}.")

    parts.append(f"Visibility {_vis(obs.visibility_m)}.")

    # SKY. A ceiling is only ever broken or overcast -- see `observation.SKY`.
    # Few and scattered are reported as cover with no height attached, because
    # a height there reads as a ceiling and sends a pilot for an instrument
    # approach he does not need.
    if obs.is_ceiling:
        parts.append(f"Ceiling {say.spell_alt(_round100(obs.ceiling_ft_agl))} "
                     f"{obs.sky}.")
    else:
        parts.append(f"{obs.sky.capitalize()}.")

    parts.append(f"Temperature {_signed(obs.temp_c)}, "
                 f"dewpoint {_signed(obs.dewpoint_c)}.")
    parts.append(f"Altimeter {_inhg(obs.qfe_inhg)}.")
    parts.append(f"Runway {say.spell_rwy(obs.runway)} in use.")
    parts.append(f"Advise on initial contact you have information {letter}.")
    return " ".join(parts)


def _digits(s: str) -> str:
    """"1450" -> "one four five zero". A time is read digit by digit."""
    return " ".join(say.DIGITS[c] for c in s if c.isdigit())


def _signed(c: int) -> str:
    """Temperatures below zero are said as "minus", not as a sign nobody
    hears. Above zero the word is omitted, as on a real broadcast."""
    return f"minus {say.spell_count(abs(c))}" if c < 0 else say.spell_count(c)


def _round100(ft: int) -> int:
    """Ceilings are reported to the nearest hundred feet. "Ceiling one thousand
    one hundred and forty three" is a number nobody wrote down."""
    return int(round(ft / 100.0)) * 100


def _vis(m: int) -> str:
    """Kilometres, and "one zero or more" above ten -- the distinction between
    40 km and 45 is not something a pilot acts on."""
    km = m / 1000.0
    if km >= 10:
        return "one zero kilometres or more"
    if km >= 1:
        return f"{say.spell_count(int(round(km)))} kilometres"
    return f"{_digits(str(int(round(m / 100.0)) * 100))} metres"


def _inhg(inhg: float) -> str:
    """"2989" said as four digits, which is how an altimeter setting is read."""
    return _digits(f"{int(round(inhg * 100)):04d}")


def matches(said: str, letter: str) -> bool:
    """Did the pilot report the current information?

        "Clearance and approach should validate that you have correct atis."

    Deliberately forgiving about everything except WHICH LETTER. A pilot says
    "with Bravo", "information Bravo", "I have Bravo", or just "Bravo", and a
    controller who only accepts one of those is a controller nobody can check
    in with. What must not be forgiving is the letter itself -- accepting Alpha
    for Bravo is the whole failure this exists to catch.
    """
    if not said or not letter:
        return False
    words = said.lower().replace(".", " ").replace(",", " ").split()
    return letter.lower() in words


def said_letter(said: str) -> str | None:
    """Which letter he claimed, if any. None means he did not mention one,
    which is a different thing from claiming the wrong one and gets a different
    answer on the radio."""
    words = said.lower().replace(".", " ").replace(",", " ").split()
    for letter in LETTERS:
        if letter.lower() in words:
            return letter
    return None
