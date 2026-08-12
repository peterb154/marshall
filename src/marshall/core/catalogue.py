"""Configuration, loaded from files. Not authored in Python.

    "all of that should be configuration stored in the database, not code ...
     You keep going to code to implement some fix"
    "I could be convinced that configuration can be structured files/objects
     that are loaded into memory rather than stored in the database - just not
     intermixed with code."

`docs/CONFIG.md` has the rule and the reasoning; this is the machinery. The
short version:

    Would a different map, era, pilot or flight plan change this value?
    Then it is DATA, and it does not live in a .py file.

WHY FILES AND NOT ROWS, for the reference half. A table has no `git blame`, no
diff, no review and no way to reproduce last week's deployment -- and a
catalogue that can change without anybody seeing the change is how a glidepath
angle or a frequency drifts silently. So the source of record is a file under
version control, and anything that needs SQL (PostGIS geometry, mostly) is
PUSHED from here at start-up, the way `push_fixes` and `push_sectors` already
do. Files are the origin; Postgres is the runtime copy.

THREE SCOPES, and conflating them is the bug this module exists to prevent:

    universal   aviation English. "niner", "reed back". True in 1944 at
                Batumi and today at Nellis            -> config/speech.toml
    theatre     the names on THIS map                 -> config/theatres/<map>.toml
    sortie      whoever is flying today -- his callsign, his steerpoints, his
                flight plan                           -> the board, not a file

The old pronunciation table had all three in one dict, so "Sockeye" -- one
pilot's callsign on one evening -- sat beside "niner" as though it were a fact
about aviation. A new pilot with a new callsign was mispronounced on the air
until somebody edited Python and restarted the bridge, which is #97.

LOUD ON A BAD FILE. A missing or malformed config is raised, not defaulted
past: a controller running on silently-empty configuration says numbers that
are merely plausible, and this project has spent a month on faults of exactly
that shape. The one exception is documented on `speech` itself.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

# The repo's own config directory, overridable for tests and for a deployment
# that keeps its theatres somewhere else. Resolved at call time rather than at
# import, so a test can point it somewhere and not fight import order.
_DEFAULT = Path(__file__).resolve().parents[3] / "config"


# --- the shape of a configuration file --------------------------------------
#
# `extra="forbid"` IS THE WHOLE POINT, and it is worth more than the typing.
# Valid TOML is not valid configuration, and the gap between them is exactly
# this project's oldest failure: a plausible file that silently does nothing.
# Before this, both of these parsed clean and were ignored --
#
#     [recognizer]        the American spelling
#     [pronounciation]    a misspelling nobody would see
#
# -- and the bridge came up with no pronunciation table and an unprimed
# recogniser, saying not one word about either. A controller running on
# silently-empty configuration is the shape of every foundational bug this
# month: a real-looking answer belonging to nothing.
#
# WHY PYDANTIC RATHER THAN A HAND-ROLLED CHECK. It reports EVERY fault in the
# file at once with the path to each, so fixing a theatre is one pass instead
# of one restart per typo -- and the same models describe what crosses to
# Postgres, so the file and the table cannot drift without a test noticing.
# See docs/CONFIG.md.


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Terms(_File):
    """Respellings. Free-form keys -- the WORDS are data, the sections are not."""
    model_config = ConfigDict(extra="allow")


class Phrases(_File):
    phrases: list[str] = []


class SpeechFile(_File):
    terms: Terms = Terms()
    recogniser: Phrases = Phrases()


class PublishedFix(_File):
    """One fix anybody can look up: on a plate, in an AIP, or an aerodrome.

    BOTH FRAMES, and neither is derived from the other. `x`/`z` are the DCS
    grid metres the mission builder and the engine work in; `lat`/`lon` are the
    SIM'S OWN projection of them, taken through `coord.LOtoLL` and stored.

    Storing the projection rather than asking for it at every start is the
    point: Caucasus is a transverse Mercator, a flat-earth offset from the
    field was 7.6 nm wrong at the target area, and until now the only thing
    that could turn a fix into a position was a running sim. So "does this
    terminal area contain its own approach" (#139) could not be answered
    offline at all -- not in a test, not in a tool, not without the server up.
    """
    name: str
    x: float
    z: float
    lat: float
    lon: float
    ident: str = ""
    freq_mhz: float = 0.0
    navaid: str = ""
    # WHERE IT CAME FROM, and it is required. Reference data is seeded, never
    # authored: a fix nobody can cite is one somebody invented, which is the
    # whole of #133 and of FEET WET. Writing the source down is what stops the
    # next person adding a convenient name.
    source: str
    note: str = ""


class TheatreFile(_File):
    pronunciation: Terms = Terms()
    recogniser: Phrases = Phrases()
    fix: list[PublishedFix] = []


class CallsignsFile(_File):
    pronunciation: Terms = Terms()


def root() -> Path:
    return Path(os.environ.get("MARSHALL_CONFIG_DIR") or _DEFAULT)


def theatre_name() -> str:
    """Which map we are configured for. One reader, so nothing can disagree."""
    return (os.environ.get("MARSHALL_THEATRE") or "caucasus").strip().lower()


def _read(path: Path, model: type[BaseModel] | None = None):
    """Parse and VALIDATE one configuration file.

    Two separate failures, reported separately, because they have different
    fixes: TOML that will not parse is a syntax error, and TOML that parses
    into the wrong shape is a typo in a section name -- and the second used to
    be silent.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"no configuration at {path}. A map with no file is far more "
            f"likely to be a typo in MARSHALL_THEATRE than a map that needs "
            f"no configuration -- write an empty table rather than leaving it "
            f"absent. See docs/CONFIG.md")
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        # NAMED, because "invalid config" three layers down a start-up trace is
        # the same amount of information as no message at all.
        raise ValueError(f"{path} is not valid TOML: {e}") from e
    if model is None:
        return raw
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        # EVERY FAULT AT ONCE, with the key that caused it. One pass to fix a
        # theatre, rather than one restart per typo.
        faults = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
            for err in e.errors())
        raise ValueError(f"{path} is not valid configuration -- {faults}") from e


@lru_cache(maxsize=8)
def _universal() -> SpeechFile:
    return _read(root() / "speech.toml", SpeechFile)


@lru_cache(maxsize=8)
def _theatre(name: str) -> TheatreFile:
    return _read(root() / "theatres" / f"{name}.toml", TheatreFile)


def reload() -> None:
    """Forget what was loaded. For the tests, and for a future reload-on-signal.

    Deliberately explicit: configuration that reloads itself under a running
    controller would let a frequency change between a clearance and its
    read-back, which is a fault nobody could reproduce.
    """
    _universal.cache_clear()
    _theatre.cache_clear()


def speech(callsigns: dict | None = None) -> dict:
    """Every respelling that applies right now, in precedence order.

    universal < theatre < the sortie's own callsigns -- so a pilot may fix how
    his own callsign is said without editing a map, and a map may not quietly
    redefine "niner".

    `callsigns` is the SORTIE scope and is passed in rather than read, because
    this module has no business knowing who is flying. Today the bridge hands
    it whatever the board holds; when pilots are rows it will come from there
    and nothing here changes.

    THE ONE PLACE A MISSING FILE IS SURVIVABLE, and it is a judgement rather
    than an oversight. A controller with no pronunciation table is a controller
    with an accent; a controller who cannot start is silence on every
    frequency. Mispronouncing "Kobuleti" is not worth an aerodrome going dark,
    so this degrades and every other loader in this module does not.
    """
    out: dict[str, str] = {}
    try:
        out.update(_universal().terms.model_dump())
        out.update(_theatre(theatre_name()).pronunciation.model_dump())
    except (FileNotFoundError, ValueError) as e:
        print(f"  !! pronunciation unavailable ({e}); the controller will "
              f"have an accent", flush=True)
    out.update(callsigns or {})
    return out


@lru_cache(maxsize=8)
def known_callsigns() -> dict:
    """Respellings for the pilots we know about. THE STOPGAP LAYER.

    A callsign is sortie scope -- it belongs to whoever is flying -- and its
    real home is his record on the board. There is no such record yet, so this
    reads `config/callsigns.toml`, which exists to keep "Sockeye" saying
    "sock eye" without putting one pilot's name back into aviation English.

    Absent is fine and silent here, unlike every other loader: a deployment
    with no pilots on file is the ordinary state of a fresh install, not a
    misconfiguration.
    """
    try:
        return _read(root() / "callsigns.toml",
                     CallsignsFile).pronunciation.model_dump()
    except FileNotFoundError:
        return {}
    except ValueError as e:
        # ABSENT IS FINE; WRONG IS NOT. A file somebody wrote and mistyped is a
        # different thing from no file at all, and the second must not
        # impersonate the first -- that is how a pilot's name goes unsaid with
        # nothing on the log to explain it.
        print(f"  !! {e}", flush=True)
        return {}


def published_fixes(theatre: str = "") -> list[PublishedFix]:
    """The fixes this map publishes -- every one citable, none invented.

    NOT THE SORTIE'S TURNING POINTS. `theatre.fixes` used to be built by
    scraping every module-level `Fix` out of `route.py`:

        fixes=tuple({f.name: f for f in vars(R).values()
                     if isinstance(f, R.Fix)}.values())

    -- so the 1944 strike's own route points (FEET WET, INGRESS, EGRESS,
    TSUTSNVATI) were published to every controller in every sortie as though
    they were navaids, and a pilot asking for a steerpoint the controller
    could not resolve was offered one of them. Whether a name is PUBLISHED is
    a fact about the name, not about which Python module it happens to sit in.
    """
    return list(_theatre(theatre or theatre_name()).fix)


def recogniser_phrases(callsigns=()) -> list[str]:
    """What Whisper should expect to hear -- universal, then this map, then who
    is actually flying.

    A recogniser primed for the wrong sortie mishears the right one, and it had
    been primed for a 1944 Mustang sortie at Batumi since long before anybody
    flew an F-16 out of Kobuleti. See #137.
    """
    got: list[str] = []
    try:
        got += list(_universal().recogniser.phrases)
        got += list(_theatre(theatre_name()).recogniser.phrases)
    except (FileNotFoundError, ValueError) as e:
        print(f"  !! recogniser hints unavailable ({e}); transcription will be "
              f"unprimed", flush=True)
    got += [c for c in callsigns if c]
    # ORDER KEPT, DUPLICATES DROPPED. A prompt is a budget -- Whisper weighs the
    # start of it more -- so universal terms first, then the map, then the man
    # on the radio, and nothing said twice.
    seen, out = set(), []
    for p in got:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out
