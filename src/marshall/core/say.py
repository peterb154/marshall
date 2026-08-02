"""How a number is said out loud.

    "We need to keep things as low as possible. For example, GIS vector
     functions -- those need to be shared. There is no reason an ASR approach
     module is doing any of that math."

Same rule, different maths. These were in `atc/controller.py`, which was right
while the controller was the only thing that spoke -- and ATIS is a sibling of
`atc`, not something underneath it, so it could not reach them without either
importing sideways or growing a second speller. A second speller is how you end
up with a runway said one way by the tower and another way by the recording.

PURE TEXT, no domain in it: a heading is three digits said singly, a speed is
not, a frequency has a decimal in it, a count is a word. Every one of these
exists because Polly said something wrong once -- "one hundred twenty seven"
for a heading, "runway seven" for 07, "at zero five" for a wind speed.
"""

from __future__ import annotations


# PLAIN ENGLISH, and the ICAO words are applied later. This is deliberate and
# it was argued the other way first:
#
#     "If we always regex swap nine for niner before it goes to Polly, wouldn't
#      that make it easier to write phrases in other modules without concern
#      for phraseology like that?"
#
# Yes, and there is a stronger reason than convenience. The AGENT writes its
# own prose and says "five thousand"; no prompt makes that reliable. So the
# transcript and the audio diverge whatever we do here -- the only question is
# whether they diverge CONSISTENTLY. Putting the ICAO words in this table gives
# "fife" from the engine and "five" from the model in the same sortie, which is
# the worst of both.
#
# So: every module writes plain English, and `radio/tts.SAY_AS` turns it into
# "tree", "fife" and "niner" on the way to the radio. One rule, applied to
# everything that reaches a pilot, including prose nobody here wrote.
#
# It also makes phraseology ERA-SWAPPABLE. A 1944 controller says "five", not
# "fife". That is one table rather than a rewrite of every speller.
#
# ONE TABLE ALL THE SAME. There were SIX copies of this in this file -- five of
# them local to a function and written out inline -- so changing a digit was
# six edits and forgetting one was silent.
DIGITS = {c: w for c, w in zip("0123456789",
          ["zero", "one", "two", "three", "four", "five", "six", "seven",
           "eight", "nine"])}


def spell_speed(kt: float) -> str:
    """180 -> 'one eight zero'. A speed, not a heading.

    Its own function rather than borrowing spell_hdg, which pads to three
    figures: a heading of ninety is "zero nine zero" and a speed of ninety is
    "nine zero", and a controller who pads a speed sounds like he is reading a
    heading. Rounded to the nearest ten, because nobody assigns 183 knots.
    """
    d = DIGITS
    return " ".join(d[c] for c in str(int(round(kt / 10.0)) * 10))


def spell_alt(ft: int) -> str:
    """7000 -> 'seven thousand', 3500 -> 'three thousand five hundred'.

    Five figures and up are read digit by digit -- "one zero thousand", the way
    a controller says it, not "10 thousand". Reachable since the stack's ceiling
    became the P-51's oxygen limit rather than a four-element list.
    """
    # ONE SOURCE FOR THE WORDS. An altitude is said with the same digits
    # as a heading -- "tree thousand", not "three thousand" -- and this
    # had its own list, so a change to the ICAO words would have moved
    # every number in the system except the ones a pilot flies at.
    words = {0: ""} | {i: DIGITS[str(i)] for i in range(1, 10)}
    th, hu = divmod(ft, 1000)
    # Under a thousand there is no "thousand" to say. This used to emit a
    # leading empty word -- " thousand seven hundred" for 700 -- which was
    # unreachable while every altitude in the system was a stack level, and
    # appeared the moment the approach started advising heights on final.
    if th == 0:
        return f"{words[hu // 100]} hundred" if hu else "zero"
    thousands = (words[th] if th < 10
                 else " ".join(words[int(c)] or "zero" for c in str(th)))
    out = f"{thousands} thousand"
    if hu:
        out += f" {words[hu // 100]} hundred"
    return out


def spell_minutes(mins: float) -> str:
    """"one minute", "two minutes", "one and a half minutes".

    Words, because everything here reaches Polly as text and a bare "1" is read
    out as a digit. Halves because a minute and a half is a real leg length and
    "one point five minutes" is not something a controller says.
    """
    if abs(mins - round(mins)) < 0.01:
        n = int(round(mins))
        names = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        return f"{names.get(n, str(n))} minute" + ("" if n == 1 else "s")
    if abs(mins - 1.5) < 0.01:
        return "one and a half minutes"
    return f"{mins:g} minutes"


def spell_hdg(deg: float) -> str:
    """A heading, digit by digit: 127 -> 'one two seven'. Polly reads a bare
    127 as 'one hundred twenty seven', which is not a heading.

    North is THREE SIX ZERO. No controller says "zero zero zero" -- it is not a
    heading anyone flies, and a pilot hearing it wonders what was garbled.
    """
    d = DIGITS
    hdg = int(round(deg)) % 360 or 360
    return " ".join(d[c] for c in f"{hdg:03d}")




def spell_rwy(rwy) -> str:
    """A runway designator, digit by digit and TWO of them: 7 -> 'zero seven'.

    Not `spell_hdg`, which pads to three because a heading is three digits. A
    runway is two, and "runway zero zero seven" is not a thing anybody says.
    Written out because it went over the air as "runway 07", which Polly reads
    as "runway seven" -- one digit short of the number painted on it.
    """
    try:
        n = int(rwy)
    except (TypeError, ValueError):
        return str(rwy)
    return " ".join(DIGITS[c] for c in f"{n % 100:02d}")


def spell_count(n) -> str:
    """A small number as a WORD: 6 -> 'six'.

    A wind speed is a quantity, not a bearing, and spelling it digit by digit
    gives "wind zero nine zero at zero five" -- five knots dressed as a
    heading. Above twenty it is left alone; Polly reads "25" correctly and
    nobody needs "two five knots".
    """
    # The first ten come off DIGITS so a wind of nine knots is said the same
    # way as a heading of nine zero. Above nine they are ordinary words: "one
    # zero knots" is a heading habit that reads as a bearing.
    words = [DIGITS[str(i)] for i in range(10)] + [
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
    try:
        i = int(round(float(n)))
    except (TypeError, ValueError):
        return str(n)
    return words[i] if 0 <= i < len(words) else str(i)


def spell_time(t: float) -> str:
    """Minutes past the hour, spoken as digits: 'at four five'."""
    d = DIGITS
    return " ".join(d[c] for c in f"{(int(t) // 60) % 60:02d}")


def spell_freq(mhz: float) -> str:
    """132.0 -> 'one three two decimal zero', 128.5 -> 'one two eight decimal five'.

    Digit by digit, the way a controller reads a frequency, and ALWAYS with the
    decimal.

    This used to drop a trailing .0, on the reasoning that nobody says "one
    three two decimal zero". They do, and the pilot asked for it twice --
    first as a debug note in the middle of an approach, then plainly:

        "when the controllers give me frequencies, they should give it to me
         with full decimal, like 134.00"

        "Make frequency instructions include decimal always."

    The reason is that a bare "one two four" has to be RECOGNISED as a
    frequency from context, and a pilot reaching for a radio while flying an
    approach in cloud should not have to do that work. The decimal makes it
    unambiguous the moment it is heard, which is the whole job of the
    phraseology. Consistency also means he can read it back the same way every
    time, and a read-back that is always the same shape is one a controller can
    check at a glance.
    """
    d = DIGITS
    whole, _, frac = f"{mhz:.3f}".rstrip("0").rstrip(".").partition(".")
    out = " ".join(d[c] for c in whole)
    return out + " decimal " + " ".join(d[c] for c in (frac or "0"))


def spell_dur(sec: float) -> str:
    """A duration as aviation timing: 204 -> 'three plus two four'."""
    d = DIGITS
    m, s = divmod(int(round(sec)), 60)
    minutes = d[str(m)] if m < 10 else str(m)
    return f"{minutes} plus " + " ".join(d[c] for c in f"{s:02d}")
