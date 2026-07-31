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

    THE RULE IS "DROP ANY CHUNK WITH A DIGIT IN IT", not "take what follows the
    first separator". Squadron tags and slot numbers both carry digits and the
    human's name does not, so one test removes both -- and it is the only
    version that survives "Hoover 1-1-1", which the obvious rule turns into
    "1-1-1".

    Falls back to the whole string when that would leave nothing, because a
    pilot calling himself "Viper2" is still somebody.
    """
    parts = [p for p in re.split(r"[ _-]+", name or "")
             if p and not re.search(r"\d", p)]
    return " ".join(parts) or (name or "")


def is_evidence(name: str) -> bool:
    """Is this name long enough to identify anybody?

    Its own function because the floor used to be an inline `len(k) < 3` beside
    one caller, so nothing else applied it and nothing tested it.
    """
    return len(squash(name)) >= MIN_EVIDENCE
