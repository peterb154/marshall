"""One aeroplane has four names. This is the only place that reconciles them.

    Viper 1-4        the sim's unit name -- the slot he took
    362nd_Sockeye    the scope label -- what the radar picture prints
    sockeye          his handle -- the human, out of the label
    Sockeye          the board key -- what the separation engine files him under

They are one fact and three derivations, and every join bug this project has had
lived in the gap between two copies of one of them.

WHY THIS FILE EXISTS. `_key` was written three times -- `atc/identity.py`,
`atc/agent_atc.py`, `kneeboard/diag.py` -- plus a fourth in the diagnostics
page's JavaScript. Two of the three were not the same function:

    identity._key   re.sub(r"[^a-z0-9]", "", s.lower())
    diag._key       "".join(c for c in s.lower() if c.isalnum())

`isalnum()` is Unicode-aware and the character class is not, so they agree on
ASCII and disagree on everything else:

    Jörg     -> "jrg"  vs "jörg"
    Соколов  -> ""     vs "соколов"

An empty key is below `unit_for_radio`'s three-character floor, so a
Cyrillic-named pilot was never identified by the physical chain -- the strongest
evidence in the system -- and fell through to identification by ELIMINATION,
which works with one aeroplane up and fails with two. Nobody wrote that bug. It
grew in the gap between two copies of one idea.

BELOW EVERYTHING, AND IMPORTED BY BOTH DEPLOYABLES. The bridge and the director
could not import each other, which is the structural reason the copies kept
appearing: duplicating was the only thing available. A module may only implement
what is specific to its own subject, and "what do we call this contact" is not
specific to a radar picture, a diagnostics page, or an approach.
"""

from __future__ import annotations

import re
import unicodedata

# The three-character floor `unit_for_radio` applies. Below this a name is not
# evidence of anything -- "AB" matches half a roster.
MIN_EVIDENCE = 3


def squash(s: str) -> str:
    """A name reduced to what two systems can agree on.

    "362nd_sockeye" and "Sockeye" are the same human; "362nd Shooter" and
    "Shooter" likewise. Case, spaces, underscores and squadron numbers are
    decoration, and DCS and SRS decorate differently.

    UNICODE SURVIVES, and that is the fix rather than an embellishment. The old
    ASCII-only version reduced "Соколов" to the empty string, which is not a
    weaker answer than "соколов" -- it is a different one, and it silently
    disqualified the pilot from the identity chain entirely.

    Accents are FOLDED rather than dropped, so "Jörg" and "Jorg" are the same
    man. They are the same man: SRS takes its client name from the DCS export
    on one path and from a typed setting on another, and a pilot who typed his
    own name without the umlaut is not a different person.
    """
    # NFKD splits "ö" into "o" + combining diaeresis; dropping the combining
    # marks leaves "o". Letters with no decomposition (Cyrillic, CJK) pass
    # through untouched, which is the point -- they are kept, not stripped.
    folded = unicodedata.normalize("NFKD", s or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return "".join(c for c in folded.lower() if c.isalnum())


def label_for(player_name: str, callsign: str, unit_name: str) -> str:
    """The name for a track, and it must identify ONE aeroplane.

    The feed had this inline as `player_name or callsign or name`, and the
    middle term does not identify anybody. DCS gives an AI unit its INDEX
    within its group, so two aircraft in the world at once came back as:

        label='1'  name='Traffic 1-1'
        label='1'  name='Traffic 2-1'

    -- reproduced live on 29 August. `label` is what `Scope.of` matches FIRST
    and the key `contacts()` looks bindings up by, so one aeroplane's binding
    reached the other and a lookup for either returned whichever the poll
    listed first. It is the failure the feed's own history already names: "two
    AI groups both labelled themselves 'Enfield11', so the scope showed one
    name at four miles and the same name at fifteen".

    A player name identifies a human. A unit name is the `tracks` PRIMARY KEY,
    so it identifies an aeroplane by construction. A callsign is neither: at
    best it names a FLIGHT, which is several aircraft, and at worst it is an
    index. It is kept only when it is not a bare number -- a real word is
    better prose for an AI flight than a slot name -- and `Scope.of` refuses it
    when two tracks answer to it, which is the guarantee this cannot give
    alone.

    IT LIVES HERE AND NOT IN THE FEED because it is a rule about names and
    nothing else, and the feed cannot be imported without the gRPC stubs, whose
    `dcs` package shadows pydcs's. Putting a pure rule behind that import made
    twelve unrelated tests fail by import ORDER the first time it was written
    there.
    """
    if player_name:
        return player_name
    cs = (callsign or "").strip()
    if cs and not cs.isdigit():
        return cs
    return unit_name


def same(a: str, b: str) -> bool:
    """Do these two names refer to one aeroplane?

    Never `==` on the raw strings, and never `in`. Substring matching is how
    "Hoover" and "Hoover2" each matched both units and neither pilot was
    identified -- see `identity.unit_for_radio`, which refuses ambiguity rather
    than tie-breaking it.
    """
    ka, kb = squash(a), squash(b)
    return bool(ka) and ka == kb


def handle(name: str) -> str:
    """The human out of a squadron name: "362nd_Sockeye" -> "Sockeye".

        "Let's use the srs/dcs suffix -- the chunk after a space, dash or
         underscore. Look at shooter, Andre and sockeye. All have unique names
         already."

    Right, and it is the missing half of the real-world rule. Formation
    procedure says each aeroplane reverts to THE CALLSIGN IT ALREADY HAD when
    the flight splits -- the one assigned at the duty desk, before the sortie.
    We had no such thing, so a split had nothing to fall back to and the engine
    let a wingman take the flight's name.

    The handle is that pre-existing identity, and it costs nothing because every
    pilot already has one. It is unique per person, never spoken, and survives a
    slot change, a callsign change and a mis-transcription.

    THE RULE DROPS WHAT IS STRUCTURALLY A TAG OR A SLOT, not anything with a
    digit in it. Both readings survive "Hoover 1-1-1" -- which is the case that
    rules out the naive "take what follows the first separator" -- and they part
    company on a human whose own name carries a number:

        362nd_Sockeye-1    ->  Sockeye     both
        Hoover 1-1-1       ->  Hoover      both
        362nd_Nomad29-1    ->  Nomad29     this one only

    The older rule dropped "Nomad29" for having a 2 and a 9 in it, found nothing
    left, and fell back to the WHOLE raw string -- squadron tag, slot number and
    all. That became the callsign on the board, so a pilot could not be found by
    the name he says: clearance delivery answered "I do not have you on the
    board, you are three six two nd nomad two nine one, use that callsign",
    which is a sim unit's name and nothing a pilot would ever say. [#128]

    Its own docstring already knew about this pilot -- "a pilot calling himself
    Viper2 is still somebody" -- and the fallback it offered him was his unit
    name rather than his name.

    So: a chunk goes if it is ALL digits (a slot: "1", "11") or an ordinal
    squadron tag ("362nd", "1st"). Anything else is a person.

    Falls back to the whole string when that would leave nothing, which is now
    reachable only by a name that is nothing but digits.
    """
    parts = [p for p in re.split(r"[ _-]+", name or "")
             if p and not re.fullmatch(r"\d+(?:st|nd|rd|th)?", p, re.I)]
    return " ".join(parts) or (name or "")


def is_evidence(name: str) -> bool:
    """Is this name long enough to identify anybody?

    Its own function because the floor used to be an inline `len(k) < 3` beside
    one caller, so nothing else applied it and nothing tested it.
    """
    return len(squash(name)) >= MIN_EVIDENCE
