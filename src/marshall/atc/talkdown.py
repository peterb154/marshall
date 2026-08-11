"""The talkdown: telling a man where he is, in words, every mile.

    "A pilot doesn't know when he is established -- everything he gets, he gets
     from the talk down."

THE ENGINE SPEAKS HERE, deliberately, and it is the one place in the system
where that is correct rather than a compromise. It is pure geometry on a
metronome, it transmits with no model in the loop, and it is talking somebody
down to a runway in cloud. A four-second cadence cannot wait three seconds for
Bedrock, and a paraphrase of "two hundred feet left of course" is worse than
useless -- see `decision.py` on what stays prose and why.

WHAT IS HARD ABOUT IT is not the trigonometry. It is that the pilot must be
corrected RELATIVE TO WHAT HE IS FLYING rather than told an absolute truth he
cannot act on, that he must not be nagged about a speed that is merely fast,
and that two aircraft on one frequency must not both get a metronome.

Every function takes what it needs as an argument. Nothing here reaches for the
bridge, the scope or the radio, which is what makes a talkdown testable against
a script instead of against an aeroplane.
"""

from __future__ import annotations

import re
import time

def spoken_deviation(g) -> str:
    """How far off, not just which side.

    "Left of course" is an assertion a pilot can disagree with, and on a live
    approach he did -- repeatedly, while two and a half miles left of the
    centreline and certain he was lined up. He was not being difficult: from
    the cockpit of a Mustang with no navaid there is nothing to disagree WITH,
    so a bare direction is one man's word against another's.

    A distance ends the argument. "Two miles left of course" is a number he can
    act on, and it tells him the size of the correction as well as its
    direction, which is most of what the call is for.
    """
    if not g.deviation or g.deviation == "on course":
        return g.deviation
    off = abs(g.xtk_nm)
    if off < 0.4:
        return f"slightly {g.deviation}"
    if off < 1.5:
        return f"about a mile {g.deviation}"
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine"]
    n = round(off)
    return f"{words[n] if n < len(words) else n} miles {g.deviation}"


def relative_correction(g, pos) -> str:
    """"Turn left ten degrees" -- a correction against what he is FLYING.

    Hoover's, and it removes a whole class of error at a stroke:

        "when in the final phases they say left 10 right 5 and don't bother with
         headings... this would avoid all dg drift and mag compass problems"

    An absolute heading is only as good as the gyro he sets it on, and a
    directional gyro DRIFTS -- his read seven degrees off the compass on the
    runway, and the compass read sixteen off the map. Every absolute heading we
    give is computed in true, converted to magnetic, and then flown against an
    instrument that is wrong by an unknown amount.

    A relative correction needs none of that. It is the difference between two
    headings, so every constant frame offset -- grid convergence, magnetic
    variation, a mis-set gyro -- cancels. The controller watches the track on
    radar; the pilot just turns.

    Rounded to five, because "turn left seven degrees" is not something anybody
    flies, and returns "" when there is nothing worth saying.
    """
    from marshall.atc.geometry import angle_diff
    delta = angle_diff(g.heading_true, pos.heading_deg)
    step = int(round(delta / 5.0)) * 5
    if step == 0:
        return ""
    # Words, not digits. Everything here reaches Polly as text and a bare "10"
    # is read out as a digit; a controller says "ten degrees".
    words = {5: "five", 10: "ten", 15: "fifteen", 20: "twenty",
             25: "twenty five", 30: "thirty", 35: "thirty five",
             40: "forty", 45: "forty five"}
    n = min(abs(step), 45)          # more than forty five is a vector, not a nudge
    return f"turn {'right' if step > 0 else 'left'} {words[n]} degrees"


def altitude_instruction(g, profile) -> str:
    """What to SAY about his altitude -- an instruction, not an observation.

        "this is an anticipatory call so I can be there on time rather than a
         reactive call"

    "Altitude should be twelve hundred" describes where he ought to already be.
    By the time he has heard it, started down and got there, he is a mile
    further in and behind the profile again -- permanently chasing it from
    above, which is what "I was always too high" partly was.

    So the call carries the NEXT mile's altitude as an instruction he has a mile
    to fly. "Descend to" when it is a step down, "maintain" when it is not, and
    "minimums" at the bottom rather than an odd number nobody sets on a
    subscale.
    """
    from marshall.atc import controller as ctl
    want = g.descend_to_ft
    if not want:
        return (f", altitude should be {ctl.spell_alt(g.altitude_ft)}"
                if g.altitude_ft else "")
    if want <= profile.mda_ft:
        return ", descend to minimums"
    if g.altitude_ft and want < g.altitude_ft:
        return f", descend to {ctl.spell_alt(want)}"
    return f", maintain {ctl.spell_alt(want)}"


# SPEED CONTROL.
#
#     "An airplane going any speed should get sequenced. If that's not
#      reasonable, have the controller tell the aircraft to slow down. It's not
#      reasonable to fly an approach at 500 kts anyway."
#
# Both halves of that are right, and the second is the one that was missing.
# route.py has always known what speed each leg wants -- `speed_kt_at`, which
# the descent planner and the mission's AI tasking both read -- and the
# controller had no way to SAY it. So an F-16 arriving at three hundred knots
# was flown as though it were a Mustang at a hundred and fifty, and the base
# turn to final that works at pattern speed overshoots at twice it (#39).
#
# Speed is the cheapest instrument a controller has. It is also the realistic
# one: real approach control assigns speed on nearly every vector, and a pilot
# who is asked to slow down is being helped rather than corrected.
SPEED_TOLERANCE_KT = 30.0     # below this he is fast, not wrong -- do not nag
SPEED_REPEAT_SEC = 75.0       # ...and do not say it again every radar sweep

# Callsign -> (speed we asked for, when). Repetition is the failure mode here:
# the guidance is recomputed on every transmission, so an unguarded instruction
# is repeated in every single call and reads as the controller not listening.


def speed_instruction(bridge, g, pos=None, cs: str = "", now: float | None = None,
                      aircraft_type: str = "") -> str:
    """"reduce speed to one eight zero" -- when, and only when, it is needed.

    Silent unless the sim gives a real groundspeed AND the leg wants one AND he
    is meaningfully faster than it. Guessing at a speed he might be doing would
    be worse than saying nothing: an instruction to slow down issued to an
    aeroplane already at approach speed is a controller who cannot see.

    TWO THINGS KEEP IT SAFE, and the second matters more than the first.

    The floor is per-airframe, because the published profile's 174 knots is the
    P-51's and an F-16 is on the back side of the drag curve there. See
    equipment.MIN_VECTOR_KT.

    And on FINAL the controller stops assigning speed at all. This is not a
    concession, it is how it is done: the pilot knows his aeroplane's approach
    speed, its fuel state and what it is carrying, and the controller knows
    none of those. Speed control exists to fix the geometry of the turn onto
    final, and once he is on final there is no geometry left to fix. "Resume
    normal speed" is a real instruction and this is the moment for it.
    """
    from marshall.atc import controller as ctl, equipment as E
    phase = str(getattr(g, "phase", "") or "")
    if phase in ("final", "map", "missed"):
        # Release him ONCE, and only if we actually had him restricted --
        # "resume normal speed" to a pilot who was never given a speed is a
        # controller answering a question nobody asked.
        if bridge.speed_asked.pop(cs, None):
            return ", resume normal speed"
        return ""
    want = float(getattr(g, "speed_kt", 0.0) or 0.0)
    have = float(getattr(pos, "speed_kt", 0.0) or 0.0) if pos is not None else 0.0
    if want > 0:
        want = E.safe_speed_kt(want, aircraft_type)
    if want <= 0 or have <= 20 or have <= want + SPEED_TOLERANCE_KT:
        return ""
    t = time.time() if now is None else now
    asked, when = bridge.speed_asked.get(cs, (0.0, 0.0))
    if abs(asked - want) < 10 and t - when < SPEED_REPEAT_SEC:
        return ""                       # already told him, and it still stands
    bridge.speed_asked[cs] = (want, t)
    return f", reduce speed to {ctl.spell_speed(want)} knots"


# A talkdown call the AGENT should never have made: a range, or a heading, while
# the engine owns the approach.
_TALKDOWN_WORDS = re.compile(
    r"\b(miles? from the runway|of course|come (?:left|right)|"
    r"turn (?:left|right) heading|fly heading|heading (?:one|two|three|zero|"
    r"four|five|six|seven|eight|niner)\b|descend (?:and maintain |to )|"
    r"altitude should be)", re.I)


# What we last TOLD each aeroplane to fly. Not what we want him to fly now --
# those are different things and confusing them is a bug with a name.
# "one four zero" becomes "1 4 0" once the spoken digits are converted, so the
# number to compare is a RUN of single digits, not a word-bounded integer.
# Matching \b\d{2,4}\b against "heading 1 4 0" finds nothing at all, which is
# how the first version of this quietly never fired.
_DIGIT_RUN = re.compile(r"\d(?:\s*\d){1,3}")


def _callsign_numbers(cs: str) -> set[str]:
    """The digits in his own callsign, in every form they arrive in.

    Stored canonically as "Falcon 1-1", said as "Falcon one one". The hyphen
    form defeats a digit-run match, so the SPOKEN form is what gets compared --
    without this, "Falcon one one, say again" counted as a correct read-back of
    an instruction containing 11.
    """
    from marshall.atc import callsign as C
    try:
        spoken = C.parse(cs).spoken
    except Exception:
        spoken = cs
    return _spoken_numbers(spoken) | _spoken_numbers((cs or "").replace("-", " "))


def _spoken_numbers(said: str) -> set[str]:
    """Every number in a transmission, however it was said.

    "one four zero", "140" and "one forty" all have to come out as 140, because
    a controller says one, a pilot reads back another, and a transcriber writes
    the third.
    """
    from marshall.atc import callsign as C
    text = C._digits(said or "")
    out = {m.group(0).replace(" ", "") for m in _DIGIT_RUN.finditer(text)}
    # An altitude spoken as "two thousand" survives _digits as "2 thousand".
    for n, word in ((1000, "thousand"), (100, "hundred")):
        for m in re.finditer(rf"(\d)\s*{word}", text):
            out.add(str(int(m.group(1)) * n))
    return {o for o in out if len(o) >= 2}


def note_issued(bridge, cs: str, said: str) -> None:
    """Remember the numbers in an instruction, so a read-back can be judged
    against what he was ACTUALLY given."""
    if not cs or not said:
        return
    # HIS OWN CALLSIGN IS NOT AN INSTRUCTION. "Falcon one one" carries a 11,
    # and without removing it every transmission he makes "matches" the last
    # thing we said, including "say again".
    got = _spoken_numbers(said) - _callsign_numbers(cs)
    if got:
        bridge.issued[cs] = got
    # AND THE WORDS, AND WHEN. The numbers alone cannot tell a read-back from a
    # report, because a genuine report shares them: "hold short of runway zero
    # seven" is what we SAID and also what he does when he gets there. See
    # `is_read_back`, which needs both.
    import time as _t
    bridge.said_to[cs] = (said, _t.monotonic())


# A read-back follows its instruction. Twenty seconds is one exchange on a
# radio -- long enough for a slow pilot and a slow transcription, far short of
# the time it takes to taxi anywhere.
READ_BACK_WINDOW_SEC = 20.0
_NUMWORD = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
            "tree": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
            "eight": "8", "niner": "9", "nine": "9"}


def _content(text: str) -> set:
    """The content of a transmission, with numbers folded to their digits.

    "runway zero seven" and "runway 07" are the same instruction spoken two
    ways, and Whisper picks whichever it likes.
    """
    out, run = set(), []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        d = _NUMWORD.get(w) or (w if w.isdigit() else None)
        if d is not None:
            run.append(d)
            continue
        if run:
            out.add("".join(run))
            run = []
        if len(w) > 2:
            out.add(re.sub(r"(ing|ed|es|s)$", "", w))
    if run:
        out.add("".join(run))
    return out


def is_read_back(bridge, cs: str, transcript: str) -> bool:
    """Is he repeating what we just told him, rather than reporting a new fact?

        PILOT: Kobuleti Ground, sockeye, taxi to runway 07, holding short of
               runway 07.
        ATC:   Sockeye, contact Kobuleti Tower one three three decimal zero.

    He read the taxi clearance back and it was heard as "I am holding short",
    so the phase moved and the ladder handed him to Tower before he had moved
    an inch. The same fault one rung on gave a pilot at three miles asking "am I
    clear to land?" the meaning "I have landed".

    TIME IS THE DISCRIMINATOR and the echo is the guard. A read-back FOLLOWS its
    instruction, within one exchange; the report of having complied with it
    comes minutes later, after he has taxied there. Word overlap alone cannot
    separate them -- a genuine "holding short of runway zero seven" is a SUBSET
    of "taxi to runway zero seven, hold short of runway zero seven", which is
    why counting shared words fails on exactly the case that matters.

    The echo is still required, so an unrelated transmission that happens to
    arrive in the window is not swallowed.
    """
    import time as _t
    said, when = (getattr(bridge, "said_to", {}) or {}).get(cs, ("", 0.0))
    if not said or not transcript:
        return False
    if _t.monotonic() - when > READ_BACK_WINDOW_SEC:
        return False
    ours = _content(said) - _content(cs)
    if not ours:
        return False
    mine = _content(transcript)
    # Two thirds of what we said, echoed back. A pilot drops the courtesies and
    # Whisper drops a word; he does not drop the instruction.
    return len(ours & mine) * 3 >= len(ours) * 2


def reads_back_what_we_said(bridge, cs: str, transcript: str) -> bool:
    """Is he correctly repeating the last instruction we gave him?

    THE BUG THIS EXISTS FOR, and it is a good one because it makes an aeroplane
    feel at fault when it is not:

        "sometimes he gives me a heading/alt -- say 140 -- then I read back 140
         and he says incorrect, 135. The reason is that he is making an
         aggressive move to get me on track... The result is that it feels like
         I misspoke it when I didn't."

    Exactly right. The engine recomputes continuously, so between issuing 140 and
    hearing the read-back it has moved on to 135 -- and the controller, holding
    the CURRENT directive, answers a perfectly correct read-back with "negative".
    The pilot is told he was wrong about something he got right.

    A read-back is judged against what was SAID TO HIM. If the engine now wants
    something different that is not a correction, it is a NEW instruction, and it
    is spoken as an amendment.
    """
    want = bridge.issued.get(cs)
    if not want or not transcript:
        return False
    return bool(want & (_spoken_numbers(transcript) - _callsign_numbers(cs)))


def hush_a_second_talkdown(reply: str, g) -> tuple[str, str]:
    """Keep the agent OFF the talkdown while the engine is flying it.

    The metronome is transmitting a range, a correction and an altitude every
    mile. The agent kept transmitting its own beside it -- "six miles from the
    runway, mile left of course, come right heading one three zero" -- and the
    brief has told it not to since the day the pilot called it "too chatty on
    final". It does it anyway, and the cost is not merely noise:

    THE AGENT'S CHATTER SUPPRESSES THE ENGINE'S CALLS. The metronome holds its
    transmission while the channel is busy, and by the time the channel clears
    the aeroplane is into the next mile -- so the 6, 5, 4 and 3 mile calls never
    went out at all, and with them the descent instructions for those miles. The
    pilot heard nothing about coming down until two miles:

        "he missed the descent call until the last 900'"

    So it stops being advice. On final the agent may acknowledge and nothing
    else; anything that looks like a talkdown call is replaced with the
    acknowledgement it should have been. Returns (reply, why) so the log can say
    what was taken out rather than silently editing the controller.
    """
    if g is None or getattr(g, "phase", "") not in ("final", "map"):
        return reply, ""
    if not reply or not _TALKDOWN_WORDS.search(reply):
        return reply, ""
    return "", "the engine is flying the talkdown"


def asr_call(bridge, cs: str, g, pos=None, profile=None) -> str:
    """The controller's spoken range call. Deterministic on purpose.

    A talk-down is the most rote transmission in aviation -- "six miles from the
    runway, on course" -- and it has to arrive every mile, on time, with the
    right number. Routing that through a model would add a second of latency and
    a chance of drift to a sentence that has no judgement in it at all. The
    agent still handles everything a pilot actually says; this is the metronome
    underneath.
    """
    from marshall.atc import asr, callsign as C, controller as ctl
    who = C.parse(cs).spoken
    rng = asr.spoken_range(g.range_nm)
    # "one miles from the runway" is the sort of thing that is invisible in a
    # diff and unmissable over a radio.
    miles = "mile" if rng.strip() in ("one",) else "miles"
    # Spelled, not printed: "1900" reaches Polly as digits.
    alt = altitude_instruction(g, profile) if profile else (
        f"altitude should be {ctl.spell_alt(g.altitude_ft)}"
        if g.altitude_ft else "")
    # Appended to the ALTITUDE clause rather than made its own transmission:
    # a controller says "descend to two thousand, reduce speed to one eight
    # zero" in one breath, and an extra call per sweep would crowd a frequency
    # that already carries a range every mile.
    alt += speed_instruction(bridge, g, pos, cs,
                             aircraft_type=getattr(pos, "type", "") or "")
    if g.phase == "map":
        return (f"{who}, over the missed approach point. Runway in sight, land; "
                f"if not, execute missed approach.")
    if g.off_course:
        # ESTABLISHED: correct him relative to what he is flying. Absolute
        # headings belong to the vectoring phase, where he has time to set a
        # gyro; inside the final approach course they put an instrument we
        # cannot see between the controller and the aeroplane. See #37.
        turn = relative_correction(g, pos) if pos is not None else ""
        if g.phase in ("final", "map") and turn:
            return (f"{who}, {rng} {miles} from the runway, {spoken_deviation(g)}, "
                    f"{turn}{alt}.")
        return (f"{who}, {rng} {miles} from the runway, {spoken_deviation(g)}, "
                f"turn heading {ctl.spell_hdg(g.heading)}{alt}.")
    return (f"{who}, {rng} {miles} from the runway, on course"
            f"{alt}.")


def vector_call(bridge, cs: str, g, pos=None) -> str:
    """An unprompted turn, issued because he has reached the point -- not
    because he said something."""
    from marshall.atc import callsign as C, controller as ctl
    who = C.parse(cs).spoken
    turn = f"turn {g.turn} " if g.turn else "fly "
    alt = f", maintain {ctl.spell_alt(g.altitude_ft)}" if g.altitude_ft else ""
    # The turn onto base is where speed matters most: it is the leg the
    # overshoot happens on, and a man told to slow down BEFORE the turn can
    # make it. Told during it, he cannot.
    alt += speed_instruction(bridge, g, pos, cs,
                             aircraft_type=getattr(pos, "type", "") or "")
    # Rounded to five while vectoring. A pilot repositioning has to set this on
    # a gyro and read it back, and "one three zero" is easier to do both with
    # than "one two eight" -- which is also how it is issued for real.
    hdg = int(round(g.heading / 5.0)) * 5 % 360
    return f"{who}, {turn}heading {ctl.spell_hdg(hdg)}{alt}."


# What "he is on the ground" looks like on radar. Generous on altitude because
# Batumi is near sea level, and strict on speed because that is the half that
