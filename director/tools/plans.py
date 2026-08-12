"""Which filed plan does he mean? Matched on how a pilot actually says it.

Civil practice is callsign plus DESTINATION -- "IFR to Kutaisi, ready to copy"
-- and ATC finds the one plan on file. That works because destinations differ.

Here they do not. A sortie leaves Batumi, does something, and comes back to
Batumi, so every plan on file shares an origin and a destination and the civil
key separates nothing:

    Samovar  to Batumi   CAS over Tsutsnvati
    Kettle   to Batumi   CAS over Tsutsnvati, beacon letdown on return
    Lantern  to Batumi   Weather reconnaissance out to Ingress
    Marlin   to Batumi   Night patrol of the coastline
    Anvil    to Batumi   Escort a transport as far as Kobuleti

What separates them is what a pilot would say anyway -- WHAT he is doing and
WHERE. "The weather run out to Ingress" names one of those five and nothing
else, without anybody being taught a syntax. And where two really are alike --
Samovar and Kettle are the same sortie flown two ways -- the answer is a
question, not the better-scoring guess.

So the match runs over the task, the places in the route, the label and the
destination, in that order of usefulness. The label stays as the unambiguous
escape hatch for a night when two plans really are alike, and for taking
somebody else's plan -- which is a thing here and not a thing in the civil
world.

**Ambiguity is answered by asking.** Nothing here picks the first, the newest or
the best-scoring when two plans match: a controller who cannot tell says so, the
same rule as a formation that has broken up.
"""

from __future__ import annotations

import re

# Words that carry no signal about WHICH plan. Without these, "request" and
# "clearance" match a task field containing either.
#
# The list is long on purpose and it earns its length twice. It stops a plan
# being matched on the words every request contains -- and it is also what tells
# "request clearance" (he named nothing, offer him what is on file) apart from
# "request clearance to Vaziani" (he named somewhere nobody filed for, and the
# answer is that nothing matches, not a menu).
_NOISE = {
    "request", "requesting", "clearance", "cleared", "ready", "copy", "ifr",
    "vfr", "flight", "plan", "filed", "file", "the", "a", "an", "for", "to",
    "over", "on", "at", "and", "with", "my", "our", "is", "am", "we", "i",
    "please", "approach", "tower", "ground", "center", "centre", "delivery",
    # ordinary connective English, which arrives in every transmission
    "as", "of", "in", "by", "from", "this", "that", "it", "us", "you", "he",
    "his", "have", "has", "had", "be", "been", "will", "can", "could", "do",
    "does", "did", "are", "was", "were", "not", "no", "yes", "or", "but", "if",
    "then", "so", "just", "now", "like", "want", "need", "looking", "take",
    "get", "got", "give", "say", "how", "what", "which", "where", "when",
    "re", "ve", "ll", "sir", "good", "day", "morning", "afternoon", "evening",
    "thanks", "thank", "affirm", "roger", "wilco", "standby", "stand", "again",
    # WHAT HE WANTS DONE WITH A PLAN, which is never WHICH plan. "We'd like to
    # open the flight plan" is the standard way of asking for the one on file,
    # and `open` not being here made it read as naming something -- so the
    # no-name branch that offers what is filed never ran, and a pilot asking
    # the ordinary question was told nothing on file matched.
    "open", "opening", "activate", "activating", "pick", "pickup", "up",
    "close", "amend", "start",
    # spoken digits. A plan is never identified by a number, and these arrive
    # inside every callsign, altitude and frequency he says.
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "niner", "ten", "hundred", "thousand",
}


# WHO HE IS TALKING TO IS NOT WHAT HE IS ASKING FOR.
#
# A transmission opens by naming a station -- "Kobuleti Clearance, Viper one
# one, request IFR clearance to Batumi" -- and that field name is a form of
# ADDRESS. It says where the pilot is standing, not where his sortie goes.
#
# Scored as content it is poison, because the aerodrome a pilot departs from is
# exactly the aerodrome another plan is likely to mention. That request resolved
# to Anvil: "Escort a transport as far as Kobuleti", Batumi to Batumi. The word
# "Kobuleti" came out of the callsign line and hit Anvil's task, which is the
# heaviest field there is; "Batumi" hit its route and its destination. A pilot
# on the Kobuleti ramp says the name of his field in the first two words of
# every transmission he makes, so this fires on all of them.
#
# The ROLES are a closed set and none of them is ever a plan's name, so an
# address can be recognised without this module knowing the station table.
_ADDRESS = re.compile(
    r"\b[a-z]+\s+(?:clearance|delivery|ground|tower|approach|departure|"
    r"centre|center|control|radar|director|arrival)\b", re.I)


def _spoken(said: str) -> str:
    """His request with the station he is addressing taken out of it."""
    return _ADDRESS.sub(" ", said or "")


def _addressed_field(said: str) -> str:
    """The aerodrome he is CALLING, which is the aerodrome he is standing on.

    Dropping the address outright was the first fix and it threw away real
    information: "Kobuleti Clearance" is not a description of his sortie, but it
    does say where he is, and where he is IS his origin. Stripped completely,
    "request IFR clearance to Batumi" stopped matching the one plan that departs
    Kobuleti and offered him the five that do not -- asking a question with the
    right answer missing, which is worse than asking a plain one.

    So the address is read for exactly one thing and scored against exactly one
    field. It cannot reach a task or a route, which is where the poison was.
    """
    m = _ADDRESS.search(said or "")
    return m.group(0).split()[0].lower() if m else ""


def _words(text: str, drop: set[str] = frozenset()) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _NOISE and w not in drop and len(w) > 1}


def score(said: str, plan: dict) -> tuple[int, list[str]]:
    """How well this plan answers what he said, and on what grounds.

    The grounds are returned because the controller should be able to say WHY
    he thinks it is that one -- "the CAS to Tsutsnvati" reads as a controller
    who knows the plan, where "Samovar One" reads as a database.
    """
    want = _words(_spoken(said))
    if not want:
        return 0, [], 0
    pts, why, context = 0, [], 0

    label = (plan.get("label") or "").lower()
    if label and label in (said or "").lower():
        pts += 100                       # he named it outright
        why.append(f"named {plan['label']}")

    task_hits = want & _words(plan.get("task"))
    if task_hits:
        pts += 10 * len(task_hits)
        why.append("task: " + ", ".join(sorted(task_hits)))

    route_hits = want & _words(plan.get("route"))
    if route_hits:
        pts += 6 * len(route_hits)
        why.append("route: " + ", ".join(sorted(route_hits)))

    dest_hits = want & _words(plan.get("destination"))
    if dest_hits:
        # Deliberately weak. Everything comes home to the same field, so a
        # destination match is nearly free and must not outweigh a task.
        pts += 1
        why.append("destination")

    # WHERE HE IS LEAVING FROM, which only started carrying information when a
    # plan appeared that does not depart Batumi.
    #
    # Every plan used to share an origin as well as a destination, so scoring it
    # would have added a point to all of them and changed nothing -- which is
    # why it was never scored, and the note at the top of this file says as
    # much. The Kobuleti departure makes it the single most discriminating field
    # on the board: it is the only row whose origin is not Batumi.
    #
    # THIS REPLACES THE WRONG FIX. The same request resolved by putting the
    # place names into that plan's TASK -- "transit from Kobuleti to Batumi" --
    # and the task is scored at ten a word. That gave one plan triple credit for
    # "Batumi" (task, route, destination) and turned "IFR to Batumi, ready to
    # copy" -- a request every plan on the board answers equally -- into a
    # confident clearance onto somebody else's sortie. A task says what he is
    # DOING; the endpoints have their own fields and must be read from them.
    #
    # Weighted above a destination and below a task: an origin is worth more
    # than "everyone lands there" and less than what he is going to do.
    # HIS OWN WORDS FIRST, then where he is calling from -- either is evidence
    # of an origin and they are worth the same, so a pilot who says "the transit
    # out of Kobuleti" and one who simply calls Kobuleti Clearance are read the
    # same way. Counted once: saying both is not twice the evidence.
    orig = _words(plan.get("origin"))
    if want & orig:
        pts += 4
        why.append("origin")
    elif orig and _addressed_field(said) in orig:
        # THE ADDRESS IS CONTEXT, NOT A REQUEST, and the difference only shows
        # on a board trimmed to one plan.
        #
        # Every transmission opens by naming a station, so this fires on all of
        # them -- which meant the local plan carried a standing four points that
        # had nothing to do with what the pilot asked for. "Kobuleti Clearance,
        # request clearance to VAZIANI" scored those four, was the only plan on
        # the board, and won: a man who asked for an aerodrome nobody filed for
        # was read back a clearance to Batumi.
        #
        # So it is banked separately. It breaks ties between plans his own words
        # already point at, and it can never BE the match -- see `pick`, where
        # "did he name anything on file" now asks about his words alone.
        context += 4
        why.append("origin (from who he called)")
    return pts + context, why, pts


def pick(said: str, plans: list[dict], callsign: str | None = None) -> dict:
    """Resolve a spoken request to one plan, or say why it cannot be.

    Returns {"plan": ..., "why": [...]} on a clean match,
            {"ambiguous": [...]} when more than one fits,
            {"none": True} when nothing does.
    """
    if not plans:
        return {"none": True}

    graded = [(p, score(said, p)) for p in plans]
    scored = [(s, w, p) for p, (s, w, _) in graded]
    best = max((s for s, _, _ in scored), default=0)

    # NOTHING HE SAID POINTS AT A PLAN. Measured on his WORDS, with the standing
    # bonus every plan at this aerodrome collects from being addressed taken
    # back out -- otherwise the local plan always looks like a match and a
    # request nobody filed for is answered with whatever is nearest.
    if max((words for _, (_, _, words) in graded), default=0) == 0:
        # He NAMED something and nothing on file is it. "Request clearance to
        # Vaziani" is not an ambiguous request, it is a request that cannot be
        # filled, and offering him a menu of three plans that all go somewhere
        # else answers a question he did not ask.
        #
        # Only when his callsign is known, because that is what lets his own name
        # be taken out of what he said -- without it "Hoover" is a word that
        # matches no plan, and every request would read as a request for
        # somewhere nobody filed for. Asking is the safe way to be wrong.
        # `_spoken`, not `said`: the station he is calling is not something he
        # NAMED. Left in, "Kobuleti Clearance, Viper one one, request clearance"
        # -- the plainest request there is -- read as a pilot who had asked for
        # something specific, so instead of being offered the board he was told
        # nothing on file matched. The address has to come out here for the same
        # reason it comes out of the scoring.
        if callsign and _words(_spoken(said), drop=_words(callsign)):
            return {"none": True}

        # Nothing in what he said points at a plan.
        #
        # THERE IS NO "THE ONE ON FILE FOR YOU" HERE, and there used to be: if
        # exactly one plan carried his callsign it was handed to him as the
        # civil "as filed" case. That read as the safest branch in the file and
        # was the least safe, because it made a plan belong to a pilot before
        # anybody was cleared for anything.
        #
        # A plan on file belongs to NOBODY. It becomes his at the moment a
        # clearance is issued, by being copied into `assigned_plans` against his
        # flight_id, and not one instant earlier. The callsign a template
        # carried was typed by whoever built the mission and matches a live
        # pilot only by coincidence -- the same coincidence that would have
        # given the man who asked to "open the flight plan" a sortie he had
        # never heard of, and told him it was on file for him.
        #
        # So when he has named nothing, the answer is the whole list. Asking is
        # the safe way to be wrong.
        if len(plans) == 1:
            return {"plan": plans[0], "why": ["the only one on file"]}
        return {"ambiguous": plans}

    top = [(s, w, p) for s, w, p in scored if s == best]
    if len(top) > 1:
        return {"ambiguous": [p for _, _, p in top]}
    return {"plan": top[0][2], "why": top[0][1]}


def ask_which(plans: list[dict]) -> str:
    """What the controller says when he cannot tell. Describes them by what
    they ARE, then offers the labels -- a pilot recognises "the CAS to
    Tsutsnvati" faster than he recognises a name he was given yesterday."""
    bits = []
    for p in plans[:4]:
        task = (p.get("task") or "").strip()
        label = (p.get("label") or p.get("name") or "").strip()
        # "filed as" rather than a bare name. Handed the label on its own, the
        # controller reached for the only word he had for a name on a radio and
        # called it a CALLSIGN -- which is a specific thing that this is not, and
        # a pilot hearing "callsign Kettle" has been told there is an aeroplane
        # out there called Kettle.
        bits.append(f"{task}, filed as {label}" if task else f"filed as {label}")
    return "I have " + "; or ".join(bits) + ". Say which."


# --- the clearance ----------------------------------------------------------

# Codes a controller never assigns, whatever the sim models. 7500 is hijack,
# 7600 radio failure, 7700 emergency; 7000 and 1200 mean "VFR, not talking to
# anybody" in Europe and the US. DCS has no transponder at all, so these numbers
# are decoration -- but decoration that reads 7700 would have a pilot's squadron
# mate wondering, and getting it right costs one tuple.
RESERVED_SQUAWKS = {"7500", "7600", "7700", "7000", "1200", "0000", "7777"}


def squawk_for(seed: int) -> str:
    """A plausible discrete code, stable for a given flight.

    Octal, so no digit above 7 -- a squawk with an 8 in it is the sort of detail
    that is invisible until somebody who knows notices, and this is a project
    where somebody who knows is the tester.

    Deterministic on purpose: asking for the clearance twice must not produce a
    different code, or a pilot reading back what he wrote down is wrong through
    no fault of his own.
    """
    # Spread the seed across the range before converting. Straight modulo gave
    # flight 1 the code 0001 and flight 2 the code 0002, which is deterministic,
    # legal, and looks exactly like something a computer made up.
    n = (abs(int(seed)) * 2654435761 + 1013904223) % 4096
    for _ in range(4096):
        code = f"{n // 512 % 8}{n // 64 % 8}{n // 8 % 8}{n % 8}"
        if code not in RESERVED_SQUAWKS:
            return code
        n = (n + 1) % 4096
    return "4271"


def _spell(digits: str) -> str:
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "niner"}
    return " ".join(words.get(d, d) for d in str(digits))


def _spell_alt(ft: int) -> str:
    if not ft:
        return ""
    if ft % 1000 == 0:
        return f"{_spell(str(ft // 1000))} thousand"
    return f"{_spell(str(ft // 1000))} thousand {_spell(str((ft % 1000) // 100))} hundred"


def clearance(plan: dict, *, flight_id: int, departure_freq: float,
              initial_ft: int, amended_route: str | None = None) -> str:
    """CRAFT, in the order a pilot writes it down.

        Clearance limit, Route, Altitude, Frequency, Transponder

    "As filed" is the load-bearing phrase and is only used when the route is
    genuinely the filed one. An amendment is read out in full, because a pilot
    who hears "as filed" and got something else is exactly the failure that
    phrase exists to prevent -- which also makes it checkable: the words "as
    filed" must never appear beside an amended route.
    """
    dest = plan.get("destination") or "the field"
    cruise = plan.get("cruise_ft") or 0
    route = amended_route or plan.get("route") or ""

    parts = [f"cleared to {dest}"]
    if amended_route:
        parts.append("routing amended, " + ", ".join(
            p.strip().title() for p in route.split(",") if p.strip()))
    else:
        parts.append("as filed")
    if initial_ft:
        parts.append(f"maintain {_spell_alt(initial_ft)}")
    if cruise and cruise != initial_ft:
        parts.append(f"expect {_spell_alt(cruise)} one zero minutes "
                     f"after departure")
    if departure_freq:
        whole, _, frac = f"{departure_freq:.1f}".partition(".")
        parts.append(f"departure frequency {_spell(whole)} decimal {_spell(frac)}")
    parts.append(f"squawk {_spell(squawk_for(flight_id))}")
    return ", ".join(parts) + "."


# --- the route on the ground, and how much help he needs with it -------------

def route_fixes(plan: dict, fixes: dict) -> tuple[list[dict], list[str]]:
    """The plan's route as places, and anything that could not be found.

    Coordinates are NOT stored on the plan. They live in the fix table, which is
    projected by the sim from route.py -- one source of truth for where a point
    is, so a plan and a chart cannot disagree about INGRESS. A plan names fixes;
    this turns the names into positions.

    The unresolved list is returned rather than dropped. A route with a fix
    nobody can find is a plan that will strand a pilot halfway, and the
    controller should refuse it at clearance delivery rather than discover it at
    the third leg.
    """
    # A PLAN DEFINES ITS OWN PRIVATE FIXES, and they are looked up first.
    #
    #     "there are public fixes that are known to everybody because they're on
    #      a plate, and private fixes that are in a Flight plan. But ATC should
    #      be able to get and refer to my private fixes when I open a plan with
    #      those fixes and the names in there."
    #
    # `legs` carries them with their positions, so opening the plan is what
    # makes FOO resolvable -- which is exactly what "private" means. The public
    # catalogue is still the authority for everything on a plate; a plan may
    # not redefine DIOMI.
    own = {(l.get("fix") or "").lower(): l for l in (plan.get("legs") or [])
           if l.get("lat") is not None and l.get("lon") is not None}
    out, missing = [], []
    for raw in (plan.get("route") or "").split(","):
        name = raw.strip()
        if not name:
            continue
        ll = fixes.get(name.lower())
        mine = own.get(name.lower())
        if ll:
            out.append({"name": name, "lat": ll[0], "lon": ll[1]})
        elif mine:
            out.append({"name": name, "lat": mine["lat"], "lon": mine["lon"],
                        "private": True})
        else:
            missing.append(name)
    return out, missing


# What the aeroplane can do about navigation, which decides how much the
# controller needs to do FOR him.
#
#   ins   he knows where he is to the foot. Naming the fix is enough, and a
#         running commentary is noise over somebody who is already there.
#   adf   he can home a beacon. The AN/ARA-8 exists on the P-51D-30 and nothing
#         else in this hangar, which is why the beacon letdown was locked to one
#         airframe.
#   dr    a compass, a watch and a map. He needs position reports going out and
#         vectors coming back, and he is the reason the radar approach exists.
#
# Keyed on the type the SIM reports, because that is what radar already carries
# -- "362nd_sockeye [Hoover 1-1] (P-51D-30-NA)" -- so nobody has to declare it.
NAV_BY_TYPE = {
    "P-51D-30-NA": "adf",
    "P-51D": "dr",
    "P-47D-30": "dr",
    "SpitfireLF Mk IX": "dr",
    "SpitfireLFMkIX": "dr",
    "F4U-1D": "dr",
    "Bf-109K-4": "dr",
    "FW-190D9": "dr",
}


def nav_of(aircraft_type: str | None) -> str:
    """How he navigates. Anything modern is assumed to know where it is.

    The default matters and is deliberately the GENEROUS one: a type nobody has
    listed is far more likely to be a jet with an inertial platform than a 1944
    fighter, and treating an F-16 like a Mustang produces a controller reading
    ranges to a man watching a moving map -- chatter over somebody busy, which
    is the failure this project keeps finding.
    """
    if not aircraft_type:
        return "dr"          # unknown and in this hangar: assume he needs help
    return NAV_BY_TYPE.get(aircraft_type.strip(), "ins")


def help_level(nav: str) -> str:
    """One line the controller's prompt can act on."""
    return {
        "ins": "He has an inertial platform and knows his position exactly. "
               "Name the fix and leave him alone; do not read him ranges.",
        "adf": "He can home a beacon but has no position fix of his own. Give "
               "him the beacon and expect a report over it.",
        "dr": "Dead reckoning only -- a compass, a watch and a map. He needs "
              "position reports outbound and vectors home, and he cannot tell "
              "you where he is more precisely than a landmark.",
    }.get(nav, "")
