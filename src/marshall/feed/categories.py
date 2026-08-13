"""What the sim calls a thing, and the one question everybody asks about it.

    Does this return fly?

Five places asked it, each by writing the answer out again:

    identity.units_on    c["category"] in ("airplane", "helicopter")
    picture._marks       cat not in ("airplane", "helicopter", "")
    picture._other_ship  cat not in ("airplane", "helicopter", "")
    tracks._render       row[9] not in ("airplane", "helicopter", "")
    tracks._wingman      row[9] not in ("airplane", "helicopter", "")

Five copies of a vocabulary that was defined in a sixth place -- `tracks._CATEGORY`,
which turns the sim's category numbers into words -- and every one of them
compared case-sensitively against the spelling that mapping happens to use.

THAT IS WHY THIS MODULE EXISTS AND NOT IN `tracks.py`. The words belong beside
`_CATEGORY`, and `tracks.py` imports grpc and the DCS stubs at module scope, so
nothing in the ordinary suite can import it -- the vocabulary was therefore
untestable in the one place it was defined. A pure module below it is importable
by everybody who needs the answer, which is the whole map.

`tracks` is not the only writer of that column. `tools/ghost_flight.py` paints a
row directly, and it wrote `Airplane`. One capital letter, and:

    is_aircraft   false, so the untracked panel -- the surface built to show a
                  manned aeroplane nobody is working -- could never show one
    derived       blank, so nobody could see 362nd_Sockeye -> Sockeye
    state         blank
    level         "", so a manned uncontrolled contact never went amber
    count_contacts   0, so the separation engine never engaged for him

That is [#156], and its filed diagnosis names the wrong layer: it reads
`agent_atc._contact`'s `"is_aircraft": not u.category` as "the feed's category is
truthy, so every aeroplane is false". `_contact` never sees the feed's word.
`units_on` has already blanked it -- `Unit.category` means *the category if it is
NOT an aeroplane's*, and that expression is correct under that contract. The
comparison that blanks it is what was case-sensitive.

CASE IS FOLDED AND NOTHING ELSE IS GUESSED. An unrecognised word is not silently
made to fly: `is_aircraft` says no to anything it does not know, because the one
mistake that costs a sortie is armour counted as traffic (audit #45 -- four T-55s
parked seventy miles away switching the separation engine on for a lone pilot).

THE EMPTY STRING IS THE EXCEPTION AND IT IS DELIBERATE. `feed/dcs.py`, the older
live-scan path, stamps every contact `""` because it genuinely cannot tell -- it
asks a different API that does not carry the group category. "I was not told" is
not "it is a tank", and the tolerant answer there is the right one: the scan is
used for aircraft, and treating an aeroplane as armour deletes him from the
board. It is the only case where an absence is read generously, and it is read
that way because the alternative loses a real aeroplane rather than counting a
false one.
"""

from __future__ import annotations

# THE SIM'S OWN WORDS, in the spelling `tracks._CATEGORY` writes them.
AIRPLANE = "airplane"
HELICOPTER = "helicopter"
GROUND = "ground"
SHIP = "ship"

# Everything the feed can stamp on a row. `tracks._CATEGORY` is built from this,
# so the mapping from a DCS group-category number and the vocabulary every
# reader compares against cannot drift apart.
WORDS = (AIRPLANE, HELICOPTER, GROUND, SHIP)

# The ones that fly, and are therefore traffic.
FLYING = frozenset((AIRPLANE, HELICOPTER))


def word(raw: str | None) -> str:
    """The category as the feed spells it, or `raw` folded if nobody knows it.

    Case and surrounding space are the only things normalised. A word this
    module does not recognise comes back lower-cased rather than blanked,
    because it is still the most informative thing anybody has about that
    contact -- it goes into the picture's parenthetical, and "(T-55, structure)"
    tells a controller more than "(T-55)".
    """
    return (raw or "").strip().lower()


def is_aircraft(raw: str | None) -> bool:
    """Does this category name something that flies?

    An empty category is TRUE here and that is the one generous reading in this
    module -- see the header. Every other unknown is false: a word we do not
    recognise is not promoted to traffic.
    """
    w = word(raw)
    return w == "" or w in FLYING
