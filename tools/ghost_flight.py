"""An aeroplane that flies, with no sim -- so the RANGE rungs of the ladder can
be checked at all.

    "had to end that flight early. left several debug logs. Never got handed to
     center.."

That rung -- Kobuleti Departure handing a climbing jet to Georgia Center at
twenty-five miles -- had never been tested by anything, and could not be. The
reason is written into `ladder_rehearsal.py`'s own docstring, which says
honestly that anything gated on RADAR "reports SKIPPED rather than passing
quietly": a synthetic pilot has a voice and no aeroplane.

The harness CAN spawn a real jet through DCS-gRPC. What it cannot do is make one
TRAVEL. `departure -> center` is not a state, it is a journey from four miles to
thirty, and a fixture parked on a bearing proves nothing about a threshold it
never crosses.

WHAT THIS IS. `tracks` is the radar picture -- one row per aeroplane, reconciled
against the sim on every sweep -- and everything downstream of it is ours: the
board, the guidance, the handoff decision, the transmission. So a row written by
hand and marched along a heading exercises the whole chain from radar to radio
with no DCS at all:

    tracks -> fetch_radar -> radar_fixes -> ctl.board() -> watching_him -> SRS

It is safe precisely BECAUSE the feed owns that table. Whatever the sim no
longer has, the table no longer has: start DCS and the next sweep deletes the
ghost without anyone remembering to. That is the same property that makes
`tracks` the one part of this system nobody has ever had to clean by hand -- see
docs/STATE.md -- and it is why this cannot leave litter in a real sortie.

AND IT ONLY EVER FLEW OUTBOUND, which is the half of the ladder that has not
been going wrong. Every rehearsal in this repo departs: `--from-nm 3 --to 32`,
marching out along the runway heading, and the loop was written as `while nm <
args.to`. So the four rungs an ARRIVAL climbs -- center to approach, the
approach clearance, approach to tower, and Tower not giving him back -- had
never been flown by anything, and both of the last two real sorties broke on
exactly those:

    "he just tried to transfer me back to approach when I was within five
     miles on the final"
    "approach, never actually cleared me for the approach"

AND IT NEVER SPOKE FROM THE GROUND, which is the other half. `--inbound` and
the outbound run both begin with an aeroplane already flying, so the four rungs
BEFORE the wheels leave -- Clearance, the read-back, Ground, Tower -- belonged
to `ladder_rehearsal.py`, whose own docstring says what it cannot do: its
fixture is parked and departs in words, so "the RECOVERY rungs need an
aeroplane that has actually flown". Between the two tools every rung had been
flown and no SORTIE had, and the faults of the last week live in the joins: a
read-back that never terminates is only visible if somebody then asks Ground for
taxi, and `landed` is only reachable from `approach`, which is only reachable
from a jet that took off somewhere.

`--sortie` flies the join. One ghost, one callsign, one run: a stand at
Kobuleti, the eight rungs, and a stand at Batumi. It is the only mode that can
answer whether `sortie_phase` ever reaches `landed`, because that is not a
state a fixture can be put into -- it is the end of a journey.

`--inbound` flies the other way, and the direction is the whole difficulty.
Range is ambiguous by design -- `handoff.py` says so in its own docstring --
because five miles outbound climbing and five miles inbound descending are the
same number and opposite events. What separates them is the TREND, and the
trend is read off the heading: `_handoff_state` calls him inbound when his
heading is within a quadrant of the reciprocal of the radial he sits on. An
arrival therefore needs both halves moved, not one:

    range      DECREASING towards the field, so `nm` counts down
    heading    the RECIPROCAL of his radial, so he points at the field

Get the second wrong and the tool is testing an outbound flight with a smaller
number on it, which is the failure mode this paragraph exists to prevent.

WHAT IT CANNOT PROVE, and must not be read as proving:

  * that the FEED works. The sim's stream, the projection, the unit naming and
    the reconcile are all upstream of the row this writes, and a ghost flies
    straight past every one of them. This checks the bridge, not the pipe.
  * anything about flying. A ghost has no aerodynamics: it holds a heading and
    a speed because it is told to, so a rung that depends on how an aeroplane
    actually behaves needs a real one.
  * whether it SOUNDS like one person, whether a seam is audible, or whether a
    transmission arrived at a moment that made sense. Those are the pilot's,
    permanently -- see CLAUDE.md, which draws that line, and card row S11.

All three limits are printed at the end, for the same reason `check.py` names
what it skipped: a check that quietly does not run reads exactly like one that
passed.

    uv run --extra voice python tools/ghost_flight.py --srs <host>
    uv run --extra voice python tools/ghost_flight.py --srs <host> --to 40 --quiet
    uv run --extra voice python tools/ghost_flight.py --srs <host> --inbound
    uv run --extra voice python tools/ghost_flight.py --srs <host> --inbound \
        --from-nm 35 --to 2 --from-center
    uv run --extra voice python tools/ghost_flight.py --srs <host> --sortie
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall import config


def _dsn_from_compose() -> None:
    """Point at the director's Postgres, the way the bridge launcher does.

    NOT A FIFTEENTH READ OF THE CREDENTIALS. `tools/bridge.py` already derives
    the DSN from `director/docker-compose.yml`, where the user, the password and
    the published port are declared -- and its own comment says why it is done
    there rather than copied: a second copy is how two files come to disagree,
    and this repo is public so they may not be pasted into it at all.
    """
    if os.environ.get("MARSHALL_PG_DSN") or os.environ.get("STRANDS_PG_DSN"):
        return
    sys.path.insert(0, str(ROOT / "tools"))
    from bridge import _compose_dsn
    got = _compose_dsn()
    if got:
        os.environ["MARSHALL_PG_DSN"] = got


# --- the ghost ---------------------------------------------------------------

def _step(lat: float, lon: float, heading_deg: float, nm: float
          ) -> tuple[float, float]:
    """`nm` further along `heading_deg`, in degrees of latitude and longitude.

    Flat earth, deliberately. The projection error over the forty miles this
    tool covers is a few hundred yards -- see docs/GOTCHAS.md, where the SAME
    approximation is called out as wrong at fifty miles for a CONTROLLER, and it
    is: a controller's ranges are spoken to a pilot and must agree with his
    instruments. Nothing here is spoken. The ghost only has to cross a
    twenty-five mile threshold convincingly, and it does.
    """
    d = math.radians(heading_deg)
    dlat = nm * math.cos(d) / 60.0
    dlon = nm * math.sin(d) / (60.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def paint(name: str, label: str, lat: float, lon: float, alt_ft: float,
          heading: float, speed_kt: float, kind: str = "F-16C_50",
          in_air: bool = True) -> None:
    """Put him on the scope, or move him. One row, upserted.

    `player` is set because that is what makes the picture print him as manned,
    and a manned contact is what the identity chain correlates an SRS client
    against. An unmanned ghost would be a different test.

    `in_air` WAS HARDCODED TRUE, and it is the one column that decides the whole
    ground half of a sortie. `feed.tracks.contacts` builds `on_ground` from it,
    `is_on_the_ground` reads that before anything else, and everything gated on
    down follows: the ramp guard, the phase branch of `handoff.due`, the silence
    of the approach guidance. A ghost could therefore be flown and could not be
    PARKED -- so no ghost had ever been on a stand, which is where a sortie
    starts and ends.
    """
    from marshall.core import db
    with db.pool().connection() as c:
        c.execute(
            "INSERT INTO tracks (name, label, type, coalition, geog, alt_ft, "
            "                    heading, speed_kt, player, category, in_air, "
            "                    last_seen) "
            "VALUES (%s, %s, %s, 2, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, "
            "        %s, %s, %s, %s, 'Airplane', %s, now()) "
            "ON CONFLICT (name) DO UPDATE SET "
            "  geog = EXCLUDED.geog, alt_ft = EXCLUDED.alt_ft, "
            "  heading = EXCLUDED.heading, speed_kt = EXCLUDED.speed_kt, "
            "  in_air = EXCLUDED.in_air, last_seen = now()",
            (name, label, kind, lon, lat, alt_ft, heading, speed_kt, label,
             bool(in_air)))


class Ghost:
    """One aeroplane, kept on the scope while the pilot is talking.

    EVERY PREVIOUS GHOST MARCHED AND NEVER STOPPED, so nothing ever had to hold
    one still. `tracks` filters every read on `last_seen` -- fifteen seconds,
    `feed.tracks.STALE_POS_SEC` -- and one rung of the ladder takes twenty: the
    pilot transmits, the model answers, the settle runs. A sortie parks him on a
    stand for four transmissions before he moves an inch, and a fixture that
    goes stale between rungs is a voice with no aeroplane, which the engine
    correctly declines to work.

    So the row is repainted on a clock of its own, in the background, from
    whatever state the sortie has last set. Movement and presence are two
    different jobs and only one of them can be allowed to stop.
    """

    def __init__(self, track: str, label: str, *, lat: float, lon: float,
                 alt_ft: float, heading: float, speed_kt: float,
                 in_air: bool, tick: float = 2.0) -> None:
        self.track, self.label = track, label
        self.lat, self.lon, self.alt_ft = lat, lon, alt_ft
        self.heading, self.speed_kt, self.in_air = heading, speed_kt, in_air
        self.tick = tick
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def put(self, **kw) -> None:
        """Move him, or change what he is doing. Painted immediately, so a
        transmission never races the repaint clock."""
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)
        self.paint()

    def paint(self) -> None:
        with self._lock:
            args = (self.track, self.label, self.lat, self.lon, self.alt_ft,
                    self.heading, self.speed_kt)
            in_air = self.in_air
        paint(*args, in_air=in_air)

    def start(self) -> Ghost:
        self.paint()
        self._thread = threading.Thread(target=self._keep_alive, daemon=True)
        self._thread.start()
        return self

    def _keep_alive(self) -> None:
        while not self._stop.wait(self.tick):
            try:
                self.paint()
            except Exception as e:                # a lost tick is not a crash
                print(f"  !! repaint: {type(e).__name__}: {e}")

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        erase(self.track)


def erase(name: str) -> None:
    """Off the scope. The feed would do this on its next sweep anyway; doing it
    here means a run that is interrupted does not leave a contact behind for
    whoever flies next."""
    from marshall.core import db
    try:
        with db.pool().connection() as c:
            c.execute("DELETE FROM tracks WHERE name = %s", (name,))
    except Exception as e:
        print(f"  !! could not erase {name}: {type(e).__name__}: {e}")


# --- reading what the bridge decided -----------------------------------------

def size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def events_since(path: Path, mark: int) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        fh.seek(mark)
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def handed_to_center(events: list[dict]) -> tuple[bool, str]:
    """Did anything hand him to Center, and what did it say?

    THE RECORD, NOT THE AUDIO -- the same bargain the ladder rehearsal makes.
    `atc/handoff` is written by both the monitor and the receive path, and it
    carries the role, so this does not have to guess from prose.
    """
    for e in events:
        if str(e.get("kind", "")) != "atc/handoff":
            continue
        if str(e.get("to", "")).lower() == "center" or \
                "center" in str(e.get("text", "")).lower():
            return True, str(e.get("text", ""))
    return False, ""


def why_not(events: list[dict]) -> list[str]:
    """Every reason the monitor gave for keeping him.

    This is the whole point of the exercise. Before #122 the thread transmitted
    when it acted and said NOTHING when it did not, so a rung that failed to
    fire left an empty log and the fault could only be guessed at from reading.
    """
    return [str(e.get("text", "")) for e in events
            if str(e.get("kind", "")) == "handoff/none"]


def handoffs(events: list[dict]) -> list[dict]:
    """Every AUTHORISED handoff, in order.

    `atc/handoff` is written by both paths -- the proactive monitor and the
    receive path -- and both carry `to` as the ROLE, so an arrival can be judged
    on roles rather than on prose. A sentence the agent wrote that nobody
    authorised is deliberately not here; that is the distinction the record
    exists to keep, and the one #51 turned on.
    """
    return [e for e in events if str(e.get("kind", "")) == "atc/handoff"]


def to_role(e: dict, role: str) -> bool:
    """Was this handoff to that role -- by the field it records, or by the words.

    `to` is authoritative and the text is the fallback, because the receive path
    fills `to` from whichever of the verdict or the station has a role and
    either may be blank on an older line.
    """
    if str(e.get("to", "")).lower() == role.lower():
        return True
    return role.lower() in str(e.get("text", "")).lower()


# --- an arrival, which is a direction and not a smaller number ---------------

def arrival_geometry(field, profile) -> tuple[float, float]:
    """Where an arrival sits and what he is pointing at: (radial, heading).

    HE IS INBOUND WHEN HIS HEADING IS THE RECIPROCAL OF HIS RADIAL, which is
    exactly what `_handoff_state` measures and therefore exactly what a fixture
    has to reproduce. So: put him on the radial the final approach course comes
    FROM, and fly him down it. Straight in, from the direction the plate brings
    an aeroplane in from -- for Batumi's runway 13 that is the north-west, which
    is also the direction Kobuleti is in, so the ghost arrives the way the
    sortie does.

    TRUE, NOT MAGNETIC. `_step` walks degrees of latitude and longitude and the
    radial the radar computes is true, so a magnetic course here would put him
    six degrees off his own final -- still inbound, but no longer a straight-in,
    and the number would look right in the log. `final_crs_true` is the profile's
    own answer to that question; the runway designation is the fallback for a
    field with no published procedure.
    """
    crs = float(getattr(profile, "final_crs_true", 0.0) or 0.0)
    if not crs:
        crs = float(getattr(field, "runway", 0.0) or 0.0)
    return (crs + 180.0) % 360.0, crs


def flying_inbound(flag: bool, from_nm: float | None, to: float | None) -> bool:
    """Is this an arrival? Declared, or implied by the two ranges.

    A separate function because it is the one decision in this tool that can be
    silently wrong: an arrival flown outbound satisfies every distance in the
    handoff table and is inbound to none of them, and the log looks identical.
    So it is a thing a test can hold, rather than three clauses inside `main`.
    """
    return bool(flag or (from_nm is not None and to is not None
                         and to < from_nm))


def arrival_alt(nm: float) -> float:
    """A plausible descent: three hundred feet a mile, capped and floored.

    Not aerodynamics -- see the docstring, which says a ghost has none. It is
    here because ALTITUDE IS AN INPUT TO THE DECISION: Tower's volume has a
    4,000 ft ceiling and the airspace branch reads it, so an arrival parked at
    twenty thousand feet over the threshold is a different question from one on
    a normal profile, and the four rungs under test are the normal one.
    """
    return max(1_200.0, min(12_000.0, 300.0 * nm))


class Timeline:
    """When he was where, so a transmission can be reported at a RANGE.

    A log with a wall clock in it answers "what did he say"; the question a
    ladder turns on is "at what distance", and the two are only connected by
    the fixture that moved him. It keeps the mapping rather than reconstructing
    it, because the reconstruction would assume a constant speed the run does
    not have -- he stops dead for fourteen seconds every time he transmits.
    """

    def __init__(self) -> None:
        self.marks: list[tuple[float, float, str]] = []

    def at(self, t: float, nm: float, ref: str = "") -> None:
        """`ref` NAMES WHAT THE RANGE IS FROM, and a sortie needs it. A single
        run now crosses two aerodromes, so "24.0 nm" is not a position -- it is
        two of them, and the wrong one is always plausible. Empty for the
        single-field runs, which is what they have always printed."""
        self.marks.append((t, nm, ref))

    def _mark(self, t: float) -> tuple[float, str] | None:
        best = None
        for mt, mnm, ref in self.marks:
            if mt <= t + 0.5:
                best = (mnm, ref)
            else:
                break
        return best

    def nm(self, t: float) -> float | None:
        got = self._mark(t)
        return None if got is None else got[0]

    def where(self, t: float) -> str:
        got = self._mark(t)
        if got is None:
            return "    ? nm"
        nm, ref = got
        return f"{nm:5.1f} {ref or 'nm'}"


TRANSCRIPT_KINDS = ("pilot", "controller", "handoff/none", "not_voiced",
                    "repaired", "atc/misnamed")


def transcript(events: list[dict], line: Timeline, t0: float) -> None:
    """Print what was said, at what range, in the order it happened.

    THE RECORD, NOT THE AUDIO -- the same bargain `ladder_rehearsal.py` makes,
    and the reason a machine may judge this at all.
    """
    print("\n  transcript (mm:ss, range):")
    for e in events:
        kind = str(e.get("kind", ""))
        if not (kind.startswith("atc/") or kind in TRANSCRIPT_KINDS):
            continue
        text = str(e.get("transcript") or e.get("text") or "").strip()
        if not text:
            continue
        t = float(e.get("t", 0.0))
        where = line.where(t)
        who = {"pilot": "PILOT"}.get(kind, kind.upper())
        mhz = e.get("freq_mhz")
        chan = f" [{float(mhz):.3f}]" if mhz else ""
        print(f"    {int(t - t0) // 60:02d}:{int(t - t0) % 60:02d} {where}"
              f"  {who}{chan}: {text}")


# --- judging an arrival ------------------------------------------------------
#
# WHAT A MACHINE MAY SAY, and nothing beyond it. CLAUDE.md draws the line and it
# is not fuzzy: a handoff fired, a phase moved, a number reached the air, the
# right field's frequency. Whether the controller SOUNDED like one person is a
# pilot's, so none of these claims it.

def a_verdict(name: str, ok: bool | None, why: str) -> tuple[str, str, str]:
    """PASS, FAIL or NOT EXERCISED -- and the third is a real answer.

    `None` means the run never put the system in a position to be wrong, which
    is more useful than a guess and much more useful than a PASS: a check that
    quietly did not run reads exactly like one that did.
    """
    return (name, "PASS" if ok else ("FAIL" if ok is False else "NOT EXERCISED"),
            why)


def kept_inbound(events: list[dict], after: float) -> tuple[bool | None, str]:
    """#138 -- nobody pushed an inbound aeroplane back down the ladder.

    The single most important assertion in an arrival, and the one the 12 August
    sortie failed twice over: handed BACK to Georgia Center at 27 nm inbound,
    then offered Approach four times by Tower at four, two and one miles on
    final. `leaving_my_airspace` declines to move an inbound aircraft now, so
    what this looks for is the absence -- with the handoffs that DID fire named,
    because "nothing happened" is not evidence unless something else did.
    """
    seen = [e for e in handoffs(events) if float(e.get("t", 0.0)) >= after]
    back = [e for e in seen if to_role(e, "center")]
    if back:
        return False, ("handed back to Center: "
                       + " | ".join(str(e.get("text", "")) for e in back))
    if not seen:
        return None, ("no handoff of any kind after he was with Approach -- "
                      "nothing was decided, so nothing was declined")
    return True, ("Approach kept him; the only handoffs were "
                  + ", ".join(str(e.get("to", "?")) for e in seen))


def refused_the_approach(events: list[dict], mhz: float
                         ) -> tuple[bool | None, str]:
    """#138b -- an approach clearance is Approach's, and Center says so.

    A refusal that is SILENT is the fault this fix replaced: a controller who
    does nothing is indistinguishable from one who agreed. So the refusal has to
    be AUDIBLE and it has to carry the frequency, which is what makes it a
    redirect rather than a hint.

    `mhz` is Center's channel, handed in rather than written down: which
    frequency a seat sits on is configuration, and a number copied into a
    judging function is a second opinion waiting to disagree with it.
    """
    on_his = [e for e in events
              if abs(float(e.get("freq_mhz", 0.0) or 0.0) - mhz) < 0.01]
    if not any(str(e.get("kind", "")) == "pilot" for e in on_his):
        return None, "he never asked Center for the approach"
    for e in events:
        if str(e.get("kind", "")).startswith("atc/") and "cleared" in \
                str(e.get("text", "")).lower() and "approach" in \
                str(e.get("text", "")).lower() and \
                abs(float(e.get("freq_mhz", 0.0) or 0.0) - mhz) < 0.01:
            return False, f"Center issued a clearance: {e.get('text', '')}"
    # TWO EVENTS, BECAUSE IT IS TWO FACTS. The ENGINE refusing is `controller`
    # -- the deterministic directive, in its own words -- and what reached the
    # air is `atc/*`, which is the agent's rendering of it. Judging only the
    # second reported NOT EXERCISED on a run where the refusal plainly
    # happened: the engine said "the approach clearance is Approach's" and the
    # agent voiced "that clearance belongs to Batumi Approach, contact them one
    # two four decimal four two five", which is the same refusal in a person's
    # mouth. Demanding the engine's exact phrase on the radio would be teaching
    # the controller to be unnatural to stay green -- see
    # `ladder_rehearsal.named_no_other_field`, which makes the same argument.
    #
    # So: the engine REFUSED, and the air carried a REDIRECT with a frequency.
    # Both are structure; neither is a judgement about how it sounded.
    refused = [e for e in events if str(e.get("kind", "")) == "controller"
               and "approach's" in str(e.get("text", "")).lower()]
    voiced = [e for e in events if str(e.get("kind", "")).startswith("atc/")
              and "approach" in str(e.get("text", "")).lower()
              and "decimal" in str(e.get("text", "")).lower()]
    if refused and voiced:
        return True, f"engine: {refused[0].get('text', '')} | "\
                     f"air: {voiced[0].get('text', '')}"
    if refused:
        return False, ("the engine refused and the air did not carry it: "
                       f"{refused[0].get('text', '')}")
    return None, "Center neither refused nor cleared -- nothing to judge"


def a_readback_loop(events: list[dict]) -> tuple[bool | None, str]:
    """#134 -- the read-back correction had no exit, and fired eight times.

    On an ARRIVAL there is no departure clearance to be judged against, so the
    correct number of these is zero and any at all is the loop having found a
    new way in. Counted rather than merely detected: one is a controller asking
    a fair question, eight is the bug.
    """
    spoke = [e for e in events if str(e.get("kind", "")).startswith("atc/")]
    hits = [str(e.get("text", "")) for e in spoke
            if "say again" in str(e.get("text", "")).lower()
            and "negative" in str(e.get("text", "")).lower()]
    if not spoke:
        # NOTHING SAID IS NOT NOTHING WRONG. A silent run passes this check for
        # the same reason a dead controller passes it, which is no reason.
        return None, "the controller said nothing at all -- nothing to judge"
    if not hits:
        return True, (f"none in {len(spoke)} transmissions, which is right for "
                      f"an arrival -- there is no departure clearance to judge "
                      f"a read-back against")
    return False, f"{len(hits)} read-back correction(s): " + " | ".join(hits[:3])


def handed_to_tower(events: list[dict], line: Timeline
                    ) -> tuple[bool | None, str]:
    """Approach -> Tower fired inbound, and Tower did not give him back.

    Two halves of one rung, and the second is the one that went wrong: the
    handoff itself has fired for months, and then Tower offered him back to
    Approach at a mile on final because an aeroplane there is inside Approach's
    volume for ever.
    """
    to_twr = [e for e in handoffs(events) if to_role(e, "tower")]
    if not to_twr:
        return None, "he was never handed to Tower"
    when = float(to_twr[0].get("t", 0.0))
    nm = line.nm(when)
    where = "?" if nm is None else f"{nm:.1f}"
    back = [e for e in handoffs(events)
            if float(e.get("t", 0.0)) > when and to_role(e, "approach")]
    if back:
        return False, (f"handed to Tower at {where} nm and then back to "
                       f"Approach {len(back)}x: "
                       + " | ".join(str(e.get("text", "")) for e in back))
    return True, f"Approach -> Tower at {where} nm, and Tower kept him"


def other_fields_numbers(events: list[dict], mine: str,
                         profile) -> tuple[bool | None, str]:
    """Did a controller name another aerodrome's station or frequency.

    THE WRONG ANSWER IS ALWAYS PLAUSIBLE -- a real controller, a real frequency,
    belonging to the wrong airport -- which is why this asks about the OTHER
    field rather than demanding he name his own. Silence about which aerodrome
    you are is correct on a frequency only one of them uses. Lifted, deliberately,
    from `ladder_rehearsal.named_no_other_field`; the frequencies are added
    because a spoken number is the half a name check cannot see, and the wrong
    field's departure frequency is precisely what the pilot logged on 12 August.
    """
    from marshall.atc.controller import spell_freq
    bad_freq = {}
    for s in getattr(profile, "stations", ()) or ():
        fld = getattr(s, "field", "")
        if fld and fld.lower() != mine.lower():
            bad_freq[spell_freq(s.freq_mhz).lower()] = s.name
    roles = ("ground", "tower", "approach", "clearance", "delivery",
             "departure", "atis")
    spoke = [e for e in events if str(e.get("kind", "")).startswith("atc/")]
    if not spoke:
        return None, "the controller said nothing at all -- nothing to judge"
    for e in spoke:
        text = str(e.get("text", "")).lower()
        for spoken, who in bad_freq.items():
            if spoken in text:
                return False, f"named {who}'s frequency: {e.get('text', '')}"
        for r in roles:
            for other in {getattr(s, "field", "").lower()
                          for s in getattr(profile, "stations", ()) or ()}:
                if other and other != mine.lower() and f"{other} {r}" in text:
                    return False, (f"answered for {other.title()} {r.title()}: "
                                   f"{e.get('text', '')}")
    return True, "nobody named the other field's station or frequency"


# --- the run -----------------------------------------------------------------

def check_in(args, mhz: float, line: str) -> None:
    """Say one thing over real SRS, so the bridge has heard from him.

    HE MUST SPEAK, and it is not a formality. The board is populated by radios,
    not by radar: `radar_fixes` walks `ctl.board()`, and `watching_him` reads
    `bridge.heard_on` to find out which controller he is with. A ghost that
    never transmits is an untracked blip nobody is working, correctly ignored.
    """
    from marshall.radio import tts
    from marshall.radio.client import AM, SRSClient, radio
    print(f"   PILOT ({mhz:.3f}): {line}")
    client = SRSClient(args.srs, name=args.name,
                       eam_password=config.SRS_EAM_PASSWORD).connect(
        [radio(mhz * 1e6, AM)])
    try:
        client.transmit(tts.Voice(voice_id=args.voice).frames(line),
                        mhz * 1e6, AM)
        time.sleep(args.settle)
    finally:
        client.close()


def _a_name_nobody_has_flown() -> str:
    """A fresh identity per run -- see `ladder_rehearsal.py`, which explains at
    length why a harness that always flies one callsign proves the ladder works
    for that callsign."""
    import random
    first = ("Anvil", "Bishop", "Cobalt", "Dagger", "Ember", "Granite",
             "Ironside", "Jackal", "Kestrel", "Lancer", "Nomad", "Osprey",
             "Panther", "Quiver", "Rampart", "Saber", "Talon")
    return f"{random.choice(first)}{random.randint(10, 99)}"


def forget_him(name: str, base: str) -> None:
    """Take the fixture's row off the board and out of the table. It made it;
    it clears it -- a rehearsal that leaves a flight behind is a ghost in
    somebody else's sortie, which is exactly what cost a real one on 11 August.

    AND IT NEVER ONCE WORKED. It asked for `DELETE /flights?callsign=X`; the
    director's route is `DELETE /flights/{id}`, so every call was a 405 into a
    bare `except: pass` and every ghost this tool has ever flown is still on the
    board. The second arrival flown tonight found the first one there, holding
    the letdown -- so it was sequenced number two and told to hold at five
    thousand instead of being cleared, and Tower then asked it to say its
    position again. A harness that changes the next run's answer is worse than
    no cleanup at all.

    The ID is the thing the API wants and the callsign is the thing we have, so
    the row is looked up first. The DELETE goes through the director rather than
    into the table, because freeing a flight is his bookkeeping and not ours.

    LOUD ON FAILURE, which is the half that was missing: a swallowed exception
    reads exactly like a successful clean-up.
    """
    import urllib.request
    from marshall.core import db
    try:
        with db.pool().connection() as c:
            rows = list(c.execute(
                "SELECT id FROM flights WHERE lower(callsign) = lower(%s) "
                "   OR track_name = %s", (name, f"362nd_{name}")))
    except Exception as e:
        print(f"  !! could not look up {name}'s flight row: "
              f"{type(e).__name__}: {e}")
        return
    if not rows:
        return
    for (fid,) in rows:
        try:
            req = urllib.request.Request(f"{base}/flights/{fid}",
                                         method="DELETE")
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            print(f"  !! {name} is still on the board (flight {fid}): "
                  f"{type(e).__name__}: {e} -- the NEXT run will meet him")


def _inbound(args, th, field, recorder) -> int:
    """Fly him AT the field, and judge the four rungs an arrival climbs.

    THE HEADING IS THE TEST. `_handoff_state` derives `inbound` from the trend --
    his heading against the reciprocal of his radial -- so this puts him on the
    radial the final approach course comes from and flies him down it. A ghost
    marched outbound with a shrinking number would satisfy every range in the
    table and be inbound in none of them.
    """
    from marshall.core import route as _r
    profile = th.approach
    radial, hdg = arrival_geometry(field, profile)
    track = f"362nd_{args.name}"
    apr = _r.station_for("approach", field=field.name)
    twr = _r.station_for("tower", field=field.name)
    ctr = _r.station_for("center", field=field.name)
    if apr is None or twr is None:
        print(f"!! {field.name} has no approach or tower to arrive at",
              file=sys.stderr)
        return 2

    print(f"ghost arrival: {args.name} inbound to {field.name} on the "
          f"{radial:03.0f} radial, heading {hdg:03.0f}, "
          f"{args.from_nm:.0f} down to {args.to:.0f} nm")
    print(f"  track {track}, recorder {recorder.name}")
    print(f"  {getattr(ctr, 'name', 'center')} {getattr(ctr, 'freq_mhz', 0):.3f}"
          f" / {apr.name} {apr.freq_mhz:.3f} / {twr.name} {twr.freq_mhz:.3f}")

    mark = size(recorder)
    line = Timeline()
    t0 = time.time()
    nm = args.from_nm
    lat, lon = _step(field.lat, field.lon, radial, nm)
    paint(track, args.name, lat, lon, arrival_alt(nm), hdg, args.speed)
    line.at(time.time(), nm)
    with_approach_at = 0.0
    said_hello, asked_center, on_tower = False, False, False

    try:
        if not args.quiet and args.from_center and ctr is not None:
            # #138b -- AND HE ASKS THE WRONG MAN ON PURPOSE. Georgia Center
            # issued an approach clearance twice on 12 August while Batumi
            # Approach issued none, so the question this leg asks is whether a
            # Center seat now refuses AND redirects. A silent refusal is the
            # same fault: a controller who does nothing is indistinguishable
            # from one who agreed.
            asked_center = True
            check_in(args, ctr.freq_mhz,
                     f"Georgia Center, {args.name}, {int(nm)} miles northwest "
                     f"of {field.name}, request the I-L-S approach runway one "
                     f"three.")
            line.at(time.time(), nm)

        while nm > args.to:
            if not said_hello and nm <= args.approach_nm and not args.quiet:
                # ON APPROACH'S FREQUENCY, which is what makes him Approach's
                # aeroplane: `watching_him` reads `heard_on` and nothing else.
                # A ghost handed to Approach who never speaks to Approach is
                # still Center's as far as every later decision is concerned.
                said_hello = True
                check_in(args, apr.freq_mhz,
                         f"{field.name} Approach, {args.name}, {int(nm)} miles "
                         f"northwest, descending eight thousand, information "
                         f"alpha, request the I-L-S runway one three.")
                with_approach_at = time.time()
                line.at(with_approach_at, nm)
            time.sleep(args.tick)
            flown = args.speed * (args.tick / 3600.0)
            nm -= flown
            lat, lon = _step(field.lat, field.lon, radial, nm)
            paint(track, args.name, lat, lon, arrival_alt(nm), hdg, args.speed)
            line.at(time.time(), nm)
            got = events_since(recorder, mark)
            if not on_tower and not args.quiet and \
                    any(to_role(e, "tower") for e in handoffs(got)):
                # HE GOES WHEN HE IS SENT, because the last rung is only under
                # test from Tower's frequency. The four offers back to Approach
                # on 12 August were made to an aeroplane on Tower's channel at
                # one to four miles, and a fixture that stays with Approach can
                # never provoke them.
                on_tower = True
                check_in(args, twr.freq_mhz,
                         f"{field.name} Tower, {args.name}, {max(int(nm), 1)} "
                         f"miles on final, gear down.")
                line.at(time.time(), nm)
            print(f"  .. {nm:5.1f} nm, {arrival_alt(nm):6.0f} ft",
                  end="\r", flush=True)
        print(f"\n  he arrived at {nm:.1f} nm.")
    finally:
        erase(track)
        forget_him(args.name, "http://localhost:8000")

    got = events_since(recorder, mark)
    transcript(got, line, t0)
    print("\n  every handoff the bridge AUTHORISED:")
    for e in handoffs(got):
        _nm = line.nm(float(e.get("t", 0.0)))
        print(f"    {'?' if _nm is None else f'{_nm:.1f}'} nm -> "
              f"{e.get('to', '?')}: {e.get('text', '')}")
    if not handoffs(got):
        print("    (none)")
    for why in why_not(got):
        print(f"  monitor: {why}")

    verdicts = [
        a_verdict("#138  the ladder does not run backwards",
                  *kept_inbound(got, with_approach_at or t0)),
        a_verdict("#138b an approach clearance is Approach's",
                  *refused_the_approach(got, getattr(ctr, "freq_mhz", 0.0))),
        a_verdict("#134  no read-back correction loop",
                  *a_readback_loop(got)),
        a_verdict("      approach -> tower, and Tower keeps him",
                  *handed_to_tower(got, line)),
        a_verdict("      nobody named the other field's numbers",
                  *other_fields_numbers(got, field.name, profile)),
    ]
    print()
    for name, how, why in verdicts:
        print(f"{how:<14} {name}\n               {why}")
    if not asked_center:
        print("\n  (--from-center was not passed, so the Center seat was never "
              "asked for a clearance it does not own.)")
    _limits()
    return 1 if any(h == "FAIL" for _, h, _ in verdicts) else 0


# --- the whole sortie, stand to stand ----------------------------------------
#
# THE JOINS ARE WHERE THE FAULTS LIVE, and no harness could reach them. Each of
# these was unit-tested and none had been heard on a radio, because each needs
# the rung BEFORE it to have really happened:
#
#   #134  a read-back that terminates -- needs a clearance actually issued to
#         this callsign, and then a second and a third transmission judged
#         against the same one
#   #135  Ground refusing an unagreed clearance -- needs a read-back that was
#         deliberately left incomplete, which no fixture had ever produced
#   #154  `sortie_phase` reaching `landed` -- needs an aeroplane that took off,
#         was cleared for an approach and then stopped, because `landed`
#         follows `approach` and nothing else
#
# So the rungs are flown in order, by one aeroplane, and what is judged is the
# record: which handoffs were authorised, which phases the board went through,
# and whether a number reached the air. Nothing here judges how it sounded.


def _st(th, role: str, field: str = ""):
    """The station working that role AT THAT FIELD.

    A ROLE IS ONLY UNIQUE WITHIN AN AERODROME -- there are two Towers and two
    Grounds on this route -- so every lookup takes a field and the fallback is
    only for the seats that belong to no field at all, which is Center.
    """
    got = next((s for s in th.stations
                if s.role == role and (s.field or "") == field), None)
    return got or next((s for s in th.stations if s.role == role), None)


def _bearing_range(lat1: float, lon1: float, lat2: float, lon2: float
                   ) -> tuple[float, float]:
    """Where that point is from this one: (true bearing, nautical miles).

    The same flat earth `_step` walks, and the same justification: nothing here
    is spoken to a pilot. It is used to point a ghost at a place and to say how
    far he still is from it.
    """
    dlat = (lat2 - lat1) * 60.0
    dlon = (lon2 - lon1) * 60.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.degrees(math.atan2(dlon, dlat)) % 360.0, math.hypot(dlat, dlon)


def fly_to(ghost: Ghost, lat: float, lon: float, *, speed_kt: float,
           alt_for, tick: float, watch=None) -> None:
    """Fly him from where he is to a point, one radar sweep at a time.

    HE POINTS AT WHERE HE IS GOING, every tick, and that is not decoration:
    `coming_towards_us` reads the heading against the reciprocal of the radial
    to decide whether he is an arrival, so a ghost dragged towards a field on
    the wrong heading is inbound in range and outbound to every rule that
    matters. Recomputing it each step is what makes a turn a turn.

    `watch(remaining_nm)` is the caller's chance to speak, to read the recorder
    or to give up; returning True from it ends the leg early, which is how a leg
    that exists to provoke a handoff stops as soon as the handoff fires.
    """
    while True:
        hdg, remaining = _bearing_range(ghost.lat, ghost.lon, lat, lon)
        if remaining <= 0.05:
            return
        step = min(remaining, speed_kt * (tick / 3600.0))
        nlat, nlon = _step(ghost.lat, ghost.lon, hdg, step)
        ghost.put(lat=nlat, lon=nlon, heading=hdg, speed_kt=speed_kt,
                  alt_ft=alt_for(remaining - step), in_air=True)
        if watch is not None and watch(remaining - step):
            return
        time.sleep(tick)


def climb_out(cruise_ft: float, field_elev_ft: float, leg_nm: float):
    """A departure profile, as a function of distance still to run.

    Not aerodynamics -- a ghost has none, and the docstring says so. It is here
    for the same reason `arrival_alt` is: ALTITUDE IS AN INPUT TO THE DECISION.
    Tower's volume has a ceiling and the airspace branch reads it, so a jet that
    leaves the runway already at cruise is a different question from one
    climbing through it, and the rung under test is the second.
    """
    def alt(remaining_nm: float) -> float:
        flown = max(0.0, leg_nm - remaining_nm)
        return min(cruise_ft, field_elev_ft + 250.0 + 600.0 * flown)
    return alt


class Sortie:
    """The run in progress: what was said, when, and where he was.

    A class rather than a pile of locals because the judging happens at the end
    and needs the same three things the transcript does -- the byte offset the
    run started at, the timeline, and which rung was being flown when each
    transmission went out.
    """

    def __init__(self, args, recorder: Path) -> None:
        self.args, self.recorder = args, recorder
        self.mark = size(recorder)
        self.line = Timeline()
        self.t0 = time.time()
        self.rungs: list[tuple[str, str, float]] = []   # id, note, t
        self.phases: list[tuple[str, str]] = []         # rung id, sortie_phase
        self.tries: dict[str, int] = {}                 # rung id -> attempts
        self.misheard: list[str] = []

    def here(self, nm: float, ref: str) -> None:
        self.line.at(time.time(), nm, ref)

    def events(self) -> list[dict]:
        return events_since(self.recorder, self.mark)

    def done(self, rid: str) -> bool:
        """Is this run over? `--stop-after` names the last rung to fly.

        A WHOLE SORTIE TAKES TWENTY MINUTES and the ground rungs take three, so
        without this every change to the read-back exchange costs a lap of the
        entire ladder. It stops the run where a rung ends rather than where a
        signal lands, so the ghost is still erased and the flight still freed.
        """
        want = getattr(self.args, "stop_after", "") or ""
        return bool(want) and rid.upper() == want.upper()

    def say(self, rid: str, mhz: float, line: str, note: str = "") -> list[dict]:
        """One transmission, and the turn it produced.

        Borrowed from `ladder_rehearsal.say_it` rather than reimplemented: it
        already knows the one thing that is easy to get wrong here, which is
        that the step ends when the CONTROLLER has answered and gone quiet
        rather than when the recorder stops growing -- the pilot's own line and
        the board are written immediately and the reply is a model call several
        seconds behind them, so a harness that waits for the file measures
        itself.
        """
        from marshall.radio import tts
        from marshall.radio.client import AM, SRSClient, radio
        _lr = _ladder()
        print(f"\n── {rid}  on {mhz:.3f}   {note}")
        print(f"   PILOT: {line}")
        self.rungs.append((rid, note, time.time()))
        # SAY IT AGAIN IF IT DID NOT ARRIVE, which is what a pilot does when he
        # is stepped on -- and the ladder rehearsal has done since it became a
        # gate. One retry: a second mishearing of the same audio is a fact about
        # Polly and Whisper rather than bad luck, and repeating for ever hides
        # it. Measured on the first sortie run: "maintain one zero thousand,
        # Marlin31" came back as "May", so the read-back genuinely was missing
        # its level and the controller was RIGHT to ask again.
        for attempt in (1, 2):
            self.tries[rid] = attempt
            ev, intact, why = _lr.say_it(self.args, mhz, line, self.recorder,
                                         SRSClient, radio, AM, tts, first=False)
            if intact or attempt == 2:
                break
            print(f"   MISHEARD ({why}) -- saying it again")
        if not intact:
            # MISHEARD IS NOT FAILED, and saying which is the difference between
            # a bug report and a fact about Whisper. The rung goes on -- a real
            # pilot's next transmission follows a mangled one too -- but the
            # verdicts print it, because a controller answering a half sentence
            # must not be scored for the answer.
            print(f"   MISHEARD: {why}")
            self.misheard.append(rid)
        for e in ev:
            if str(e.get("kind", "")).startswith("atc/") and e.get("text"):
                print(f"   ATC:   {e['text'][:150]}")
        self.phases.append((rid, board_phase(ev, self.args.name)))
        if self.done(rid):
            raise _Enough(rid)
        return ev


class _Enough(Exception):
    """`--stop-after` fired. Raised rather than returned so it unwinds through
    the flying legs, which are callbacks several frames down and have no way to
    say "we are finished" -- and so the `finally` that erases the ghost runs,
    which a signal would not have let happen."""


def _ladder():
    """`ladder_rehearsal`, as a module.

    IMPORTED RATHER THAN COPIED. Waiting for a controller, deciding whether the
    bridge heard what the pilot actually said, and spelling an altitude the way
    a radio does are all solved there, carefully, with the measurements that
    justify each choice written beside them. A second copy is how two harnesses
    come to disagree about what a number sounds like -- which is the same
    argument `_dsn_from_compose` makes one screen above for the DSN.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import ladder_rehearsal
    return ladder_rehearsal


def _squash(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def board_phase(events: list[dict], name: str) -> str:
    """What the board last said THIS aeroplane was doing.

    `sortie_phase`, NOT `phase` -- the board carries both and they answer
    different questions. See `ladder_rehearsal.phase_is`, which explains why the
    separation enum is the wrong one to read here.

    AND HIS ROW, NOT THE FIRST ROW, which is the fault the first run of this
    tool reported against itself. The board is a list; the engine keeps an
    aeroplane for eight minutes after anything last accounted for it; two
    arrivals from an earlier run were still on it. So a ghost that had not left
    the ramp was reported `landed` at every rung -- somebody else's phase, and
    it would have been read as #154 failing on the run written to test it.

    Matched on the TRACK, which is the one string the harness owns at both ends:
    the label radar prints is the name the pilot flies under. The callsign is
    the fallback and has to be squashed, since the board says "Marlin 3-1" for a
    man the fixture calls Marlin31.
    """
    for e in reversed(events):
        if e.get("kind") != "board":
            continue
        for ac in e.get("board") or []:
            if _squash(ac.get("track", "")) == _squash(name) or \
                    _squash(ac.get("callsign", "")) == _squash(name):
                return (ac.get("sortie_phase") or "").lower()
    return ""


def flight_row(name: str) -> dict:
    """His row on the director's board, or an empty one.

    The durable half of the answer. `clearance_ack` is the whole of #134 -- a
    read-back exchange that TERMINATES is one after which this column is
    filled, and no amount of agreeable prose on the radio is evidence of it.
    """
    import urllib.parse
    import urllib.request
    try:
        _lr = _ladder()
        q = urllib.parse.urlencode({"mission": _lr._mission_key()})
        with urllib.request.urlopen(f"http://localhost:8000/flights?{q}",
                                    timeout=8) as r:
            rows = json.loads(r.read().decode("utf-8", "replace"))["flights"]
    except Exception as e:
        print(f"  !! could not read the board: {type(e).__name__}: {e}")
        return {}
    for f in rows:
        if (f.get("srs_name") or "").lower() == name.lower() or \
                (f.get("callsign") or "").replace(" ", "").replace("-", "").lower() \
                == name.lower():
            return f
    return {}


def read_backs(row: dict, dep_mhz: float, who: str) -> tuple[str, str]:
    """A deliberately PARTIAL read-back, and then the correction.

    THIS IS THE POINT OF THE RUN. #134 was three faults stacked, and two of them
    only exist between transmissions: the exchange was judged against the WHOLE
    clearance every time, so reading back the two items he had been asked for
    failed on the three he did not repeat -- and there is no transmission that
    ends that loop. A single correct read-back cannot show it. It needs an
    incomplete one, a correction naming what is missing, and then only the
    missing items said back.

    AND HE SAYS THEM THE WAY A HUMAN DOES. The second fault was Whisper: a
    pilot's spoken digits come back as `1,000, 1, 0` and `3, 3, 5, 0`, matching
    neither the word form nor a single digit token. The unit tests use a
    transcription of what Whisper produced; this says it out loud and finds out
    what Whisper produces today. So the correction is phrased loosely, with the
    numbers embedded in a sentence, which is what cost the eight corrections.

    Returns ("", "") when nothing has been assigned, because a read-back of a
    clearance that was never issued is a test of the harness.
    """
    from marshall.core import say
    alt = row.get("cruise_ft")
    squawk = (row.get("squawk") or "").strip()
    dest = (row.get("destination") or "").strip()
    if not alt and not squawk:
        return "", ""
    partial = (f"Cleared to {dest.title() or 'destination'} as filed, "
               f"maintain {say.spell_alt(int(alt))}, {who}.") if alt else ""
    rest = []
    if dep_mhz:
        rest.append(f"the departure frequency is {say.spell_freq(dep_mhz)}")
    if squawk:
        rest.append(f"and we're going to squawk {say.spell_squawk(squawk)}")
    correction = f"{who}, {', '.join(rest)}." if rest else ""
    return partial, correction


# --- judging a sortie --------------------------------------------------------

def corrections(events: list[dict]) -> list[str]:
    """Every "negative, say again" the controller transmitted.

    The shape of #134 on the air. One is a controller doing his job; eight is
    the loop, and the number is the whole diagnosis -- which is why they are
    counted and quoted rather than merely detected.
    """
    return [str(e.get("text", "")) for e in events
            if str(e.get("kind", "")).startswith("atc/")
            and "say again" in str(e.get("text", "")).lower()
            and ("negative" in str(e.get("text", "")).lower()
                 or "incorrect" in str(e.get("text", "")).lower())]


def the_read_back_terminated(events: list[dict], row: dict, allowed: int
                             ) -> tuple[bool | None, str]:
    """#134 -- the exchange ENDED, and the board wrote it down.

    Two facts, and the durable one is the test. A controller who stops saying
    "negative" has either accepted the read-back or given up, and only
    `clearance_ack` tells them apart -- it is what everything downstream asks,
    and on 12 August it was never written for a whole sortie.

    `allowed` IS THE NUMBER OF INCOMPLETE READ-BACKS THE RUN ACTUALLY MADE, not
    a constant. The fixture makes one on purpose, and says it again when Whisper
    drops half of it -- and a correction for each of those is a controller doing
    his job. Counting them from the run rather than assuming one is what keeps
    this from failing on a bad-audio night and passing on a real loop.
    """
    hits = corrections(events)
    if not row:
        return None, "he was never cleared, so nothing was read back"
    if not row.get("clearance_ack"):
        return False, (f"clearance_ack is still empty after "
                       f"{len(hits)} correction(s): " + " | ".join(hits[:3]))
    if len(hits) > allowed:
        return False, (f"{len(hits)} corrections for {allowed} incomplete "
                       f"read-back(s): " + " | ".join(hits[:4]))
    return True, (f"agreed at {row.get('clearance_ack')} after {len(hits)} "
                  f"correction(s), which is what was asked for")


def ground_refused_an_unagreed_clearance(ev: list[dict], clr
                                         ) -> tuple[bool | None, str]:
    """#135 -- Ground does not move an aeroplane on a clearance nobody agreed.

    Three things, and the third is what makes it a refusal rather than a
    brush-off: he must decline, he must say WHY -- "not read back" is a
    different problem from "not filed" and a pilot can only fix the one he is
    told about -- and he must name the man who can fix it, with the frequency.
    """
    from marshall.core import say
    spoke = [e for e in ev if str(e.get("kind", "")).startswith("atc/")]
    said = " ".join(str(e.get("text", "")) for e in spoke).lower()
    if not spoke:
        return None, "Ground said nothing at all -- nothing to judge"
    if "taxi to runway" in said:
        return False, f"he cleared him to the runway anyway: {said[:150]}"
    if "read back" not in said and "readback" not in said:
        return False, f"he declined without saying why: {said[:150]}"
    want = say.spell_freq(clr.freq_mhz).lower()
    if want not in said and f"{clr.freq_mhz:.3f}".rstrip("0") not in said:
        return False, (f"he never named {clr.name} {want}: {said[:150]}")
    return True, f"refused and sent him back to {clr.name}: {said[:150]}"


def phases_reached(sortie: Sortie) -> list[str]:
    """The rungs the board actually went through, in order, without repeats."""
    out: list[str] = []
    for _rid, phase in sortie.phases:
        if phase and (not out or out[-1] != phase):
            out.append(phase)
    return out


def he_landed(sortie: Sortie) -> tuple[bool | None, str]:
    """#154 -- `sortie_phase` reached `landed`, and then `taxi_in`.

    THE LEAST EXERCISED CODE IN THE BUILD. `phase_now` answered "has he been
    airborne" with a count of GO-AROUNDS, so every pilot who flew one approach
    and landed off it -- every normal recovery -- reported never having flown,
    and `landed` was unreachable. Everything downstream followed: nothing handed
    a landed aeroplane to Ground (#77), and Ground answered a parked pilot as
    though he were departing (#100).

    Judged on the board rather than on the words, and on the rung that is the
    END of the ladder rather than on the pair, which is what this used to demand
    and what #77 made wrong.

    `landed` IS NO LONGER A RUNG THE BOARD CAN BE SAMPLED ON, at a field with a
    Ground seat. `report_down` composes the roll-out goodbye and moves him to
    `taxi_in` in the same call (df38ae1), so the two are one step: the board
    goes `approach -> taxi_in` and `landed` is passed straight through.
    `phases.derive` then refuses `taxi_in -> landed` for ever, so nothing brings
    it back. Measured on the first `--sortie` run after that commit, 13 August:

        clearance -> taxi -> holding_short -> departure -> arrival -> approach
          -> taxi_in

    -- a perfect recovery, reported FAIL by this function on the absence of a
    state the fix had deliberately made transient. `landed` keeps its meaning at
    a field with no Ground seat to pass him to, which is why it is REPORTED
    when it appears rather than forbidden.

    So what is asserted is the thing #154 was actually about: the last rung of
    the ladder was reached, and reached FROM THE AIR. The second half is not
    decoration -- `taxi_in` is a ground phase, and a fixture that never flew
    could sit on it all day. Demanding an airborne phase before it is what makes
    this a recovery rather than a parked aeroplane.
    """
    got = phases_reached(sortie)
    if "taxi_in" not in got:
        return False, ("he never reached `taxi_in`, so nobody parked him -- "
                       "the board went " + " -> ".join(got or ["(nothing)"]))
    before = got[:got.index("taxi_in")]
    from marshall.atc import phases as _ph
    if not any(_ph.has_flown(p) for p in before):
        return False, ("he reached `taxi_in` without ever being airborne, "
                       "which is a parked aeroplane and not a recovery -- "
                       + " -> ".join(got))
    how = ("via `landed`" if "landed" in got else
           "straight off `%s`, which is #77's roll-out goodbye moving him and "
           "`landed` in one step" % (before[-1] if before else "?"))
    return True, f"{' -> '.join(got)}   ({how})"


def the_eight_rungs(events: list[dict]) -> list[tuple[float, str, str]]:
    """Every handoff the bridge AUTHORISED, in order: (t, role, what was said).

    `atc/handoff` and nothing else. A sentence the agent wrote that nobody
    authorised is deliberately absent -- that is the distinction the record
    exists to keep, and the one #51 turned on.
    """
    return [(float(e.get("t", 0.0)), str(e.get("to", "") or "?"),
             str(e.get("text", ""))) for e in handoffs(events)]


def ladder_order(th) -> list[str]:
    """The stations a sortie is handed to, in order. NAMES, not roles.

    A ROLE IS ONLY UNIQUE WITHIN AN AERODROME and this is where that bites
    hardest, because the ladder visits `tower` twice and `ground` twice. Judged
    on roles, Kobuleti Ground handing BACKWARDS to Kobuleti Tower is
    indistinguishable from Batumi Tower handing forwards to Batumi Ground: same
    two words, opposite events, and the wrong one is a pilot sent to a
    controller who has finished with him. So the sequence is built out of the
    station table, by name, and every rung knows which airport it belongs to.
    """
    def name(role: str, field: str = "") -> str:
        s = _st(th, role, field)
        return getattr(s, "name", "")
    return [n for n in (name("ground", th.departure),
                        name("tower", th.departure),
                        name("departure", th.departure),
                        name("center"),
                        name("approach", th.arrival),
                        name("tower", th.arrival),
                        name("ground", th.arrival)) if n]


def handed_to_station(text: str, role: str, th) -> str:
    """Which STATION that handoff named -- by his name, or by his role.

    The text is authoritative here and the role is the fallback, which is the
    other way round from `to_role`. `to` carries a role and the role is the
    ambiguous half; the transmission says "contact Kobuleti Tower one three
    three decimal zero" and there is no doubt in it at all.
    """
    low = (text or "").lower()
    for s in th.stations:
        if s.name.lower() in low:
            return s.name
    got = _st(th, (role or "").lower())
    return getattr(got, "name", "") if got else ""


def the_ladder_ran_forwards(events: list[dict], th) -> tuple[bool | None, str]:
    """The rungs happened in the order the ladder has them, and never back.

    NOT "ALL EIGHT FIRED" -- two of the eight are not handoffs at all. Clearance
    to Ground and Ground to Tower are phase transitions with no geometry (see
    `handoff.due`, which owns them by phase and needs no row), and the ladder's
    first seat is nobody handing over. What a machine can say is that the
    AUTHORISED ones came in the published order and that none ran backwards --
    which is the fault that has actually happened twice: Center given an
    inbound aeroplane back at 27 nm, and Tower offering Approach at one mile.
    """
    seen = [handed_to_station(text, role, th)
            for _t, role, text in the_eight_rungs(events)]
    if not seen:
        return None, "nothing was handed over at all"
    order = ladder_order(th)
    at = -1
    repeats = 0
    for station in seen:
        if station not in order:
            continue
        # THE SAME MAN TWICE IS NOT BACKWARDS, and calling it so cost a run.
        # `at` rather than `at + 1`: being sent to the controller you were just
        # sent to is at worst chatter, and the fault this predicate is for is a
        # pilot pushed DOWN the ladder to somebody who has finished with him --
        # Center given an inbound aeroplane at 27 nm, Tower offering Approach at
        # a mile. Counted, because two is a fixture that wandered and eight is
        # #138.
        # `max(at, 0)`, because `range(-1, 7)` starts at -1 and `order[-1]` is
        # the LAST rung -- so the first handoff of the sortie would be matched
        # against the arrival's Ground, and the ladder would read as complete
        # before it began.
        nxt = next((i for i in range(max(at, 0), len(order))
                    if order[i] == station), None)
        if nxt is None:
            return False, (f"the ladder ran backwards to {station}: "
                           + " -> ".join(seen))
        repeats += 1 if nxt == at else 0
        at = nxt
    missing = [s for s in order if s not in seen]
    got = " -> ".join(seen)
    if missing:
        got += f"   (never fired: {', '.join(missing)})"
    if repeats:
        got += f"   ({repeats} repeated handoff(s))"
    return True, got


def right_fields_numbers(events: list[dict], th) -> tuple[bool | None, str]:
    """On a KOBULETI frequency, nobody answered for Batumi -- and the reverse.

    `other_fields_numbers` CANNOT BE USED ON A SORTIE and it is worth saying
    why, because reusing it would have been the obvious thing to do. It asks
    whether any transmission named the other aerodrome, which is exactly right
    for a run that visits one field and meaningless for a run that visits two:
    Kobuleti Clearance NAMING Kobuleti Departure's frequency is the ladder
    working, and on this run both fields are legitimately spoken of.

    What survives the second aerodrome is the question per FREQUENCY. A
    controller is only ever one field's man on one channel, so a reply going out
    on Kobuleti's Ground frequency that names a Batumi station is the 12 August
    fault -- a real controller, a real frequency, belonging to the wrong
    airport. Center is exempt because he belongs to no field and legitimately
    hands people to both.
    """
    from marshall.core import say
    mine = {}
    for s in th.stations:
        if s.field:
            mine[round(float(s.freq_mhz), 3)] = s.field.lower()
            for ch in getattr(s, "channels", ()) or ():
                mine[round(float(ch), 3)] = s.field.lower()
    roles = ("ground", "tower", "approach", "clearance", "delivery",
             "departure", "atis")
    spoke = [e for e in events if str(e.get("kind", "")).startswith("atc/")]
    if not spoke:
        return None, "the controller said nothing at all -- nothing to judge"
    checked = 0
    for e in spoke:
        field = mine.get(round(float(e.get("freq_mhz", 0.0) or 0.0), 3))
        if not field:
            continue                    # Center, or a channel nobody owns
        checked += 1
        text = str(e.get("text", "")).lower()
        for s in th.stations:
            other = (s.field or "").lower()
            if not other or other == field:
                continue
            if any(f"{other} {r}" in text for r in roles):
                return False, (f"on {field.title()}'s {e.get('freq_mhz')}: "
                               f"{e.get('text', '')}")
            if say.spell_freq(s.freq_mhz).lower() in text:
                return False, (f"named {s.name}'s frequency on "
                               f"{field.title()}'s {e.get('freq_mhz')}: "
                               f"{e.get('text', '')}")
    if not checked:
        return None, "nothing was said on a frequency belonging to a field"
    return True, (f"{checked} transmissions, each on its own field's frequency "
                  f"and naming nobody else's")


def join_range(field, lat: float, lon: float, radial: float, want_nm: float,
               keep_out_nm: float) -> float:
    """How far down the radial to join, so the TRANSIT never cuts the corner.

    THE FIRST SORTIE FLEW THROUGH THE TERMINAL AREA ON ITS WAY AROUND IT. The
    leg from twenty-seven miles off Kobuleti to a join at thirty-two on Batumi's
    final approach radial is a chord, and the chord passes 24.6 nm from Batumi
    -- inside the boundary Center gives him up at. So Center handed him to
    Approach at 24.9 nm, he carried on out to 31, and was handed to Approach
    again at 24.3. Both handoffs were CORRECT: he really was inside, inbound,
    and then he really did leave. The fixture had flown a shape no arrival
    flies.

    A run that provokes a real rule with a fake situation is worse than one that
    does not provoke it -- it reads as a bug in the ladder. So the join is
    pushed out until the whole leg stays clear, which is what a routing to
    intercept a final approach course does anyway.
    """
    from marshall.core import geo as _geo
    for nm in [want_nm, *[float(x) for x in range(int(want_nm) + 2, 71, 2)]]:
        jlat, jlon = _step(field.lat, field.lon, radial, nm)
        if _closest_nm(field, lat, lon, jlat, jlon, _geo) >= keep_out_nm:
            return nm
    return want_nm


def _closest_nm(field, alat, alon, blat, blon, _geo) -> float:
    """How near the field a straight leg from A to B ever gets, in miles.

    Walked rather than solved. The closed form is a projection onto a chord in
    a flat plane and this is a fixture: sampling is obviously right at a glance,
    a quadratic is obviously right only after you have checked it.
    """
    best = 1e9
    for i in range(101):
        f = i / 100.0
        lat, lon = alat + (blat - alat) * f, alon + (blon - alon) * f
        nm, _brg = _geo.range_bearing_true((field.lat, field.lon), lat, lon)
        best = min(best, nm)
    return best


def _round_k(ft: float) -> int:
    """An altitude to the nearest thousand, because a pilot rounds one.

    AND BECAUSE A COMPOUND ONE IS NOT SAFELY COMPARABLE. `ladder_rehearsal._words`
    rejoins a spoken number by CONCATENATION -- "seven thousand two hundred"
    becomes `7000200`, while Whisper writes `7,200` -- so a perfectly delivered
    transmission is reported MISHEARD and said again. Measured on the first
    sortie run, at twenty-four miles. Rounding is the honest fix at this end:
    "descending seven thousand" is what a pilot says, and the harness stops
    testing its own arithmetic.
    """
    return max(1000, int(round(ft / 1000.0)) * 1000)


def sent_to(s: Sortie, station: str, th, after: float) -> bool:
    """Has the bridge AUTHORISED a move to that station since `after`?

    The question a pilot asks himself before changing frequency, and the reason
    the sortie asks it rather than switching on a distance: which controller has
    him is decided by `heard_on`, so a fixture that arrives on the next man's
    channel uninvited has made the handoff unnecessary and unscoreable.

    `after` is not optional. A sortie visits two Towers and two Grounds, so
    "was he sent to a Tower" is true from twenty minutes and one aerodrome ago.
    """
    return any(float(e.get("t", 0.0)) > after
               and handed_to_station(str(e.get("text", "")),
                                     str(e.get("to", "")), th) == station
               for e in handoffs(s.events()))


def _sortie(args, th, recorder: Path) -> int:
    """One aeroplane, one callsign, a stand at Kobuleti to a stand at Batumi."""
    from marshall.core import say
    kob = th.field_named(th.departure)
    bat = th.field_named(th.arrival)
    clr = _st(th, "clearance", kob.name)
    gnd = _st(th, "ground", kob.name)
    twr = _st(th, "tower", kob.name)
    dep = _st(th, "departure", kob.name)
    ctr = _st(th, "center")
    apr = _st(th, "approach", bat.name)
    btwr = _st(th, "tower", bat.name)
    bgnd = _st(th, "ground", bat.name)
    if None in (clr, gnd, twr, dep, ctr, apr, btwr, bgnd):
        print("!! this theatre has no eight-rung ladder to fly", file=sys.stderr)
        return 2
    out_rwy = say.spell_rwy(kob.runway_in_use(th.wind_from_deg))
    in_rwy = say.spell_rwy(bat.runway_in_use(th.wind_from_deg))
    profile = th.approach
    radial, final_hdg = arrival_geometry(bat, profile)
    who = args.name
    track = f"362nd_{who}"
    s = Sortie(args, recorder)

    print(f"a whole sortie: {who}, {kob.name} to {bat.name}, "
          f"runway {out_rwy} off and runway {in_rwy} on")
    print(f"  track {track}, recorder {recorder.name}")
    print(f"  {clr.name} {clr.freq_mhz:.3f} / {gnd.name} {gnd.freq_mhz:.3f} / "
          f"{twr.name} {twr.freq_mhz:.3f} / {dep.name} {dep.freq_mhz:.3f}")
    print(f"  {ctr.name} {ctr.freq_mhz:.3f} / {apr.name} {apr.freq_mhz:.3f} / "
          f"{btwr.name} {btwr.freq_mhz:.3f} / {bgnd.name} {bgnd.freq_mhz:.3f}")
    print(f"  he asks for the plan by its label: {args.plan}")

    ghost = Ghost(track, who, lat=kob.lat, lon=kob.lon,
                  alt_ft=float(getattr(kob, "elevation_ft", 0) or 0),
                  heading=float(kob.runway), speed_kt=0.0, in_air=False,
                  tick=args.tick).start()
    s.here(0.0, "KOB")
    refused_ev: list[dict] = []
    row: dict = {}
    agreed: dict = {}
    try:
        # ---- on the stand -------------------------------------------------
        s.say("R1", clr.freq_mhz,
              f"{clr.name}, {who}, on the ramp with information alpha, "
              f"request IFR clearance to {th.arrival}, {args.plan} please.",
              "the clearance, asked for by the PLAN'S LABEL")
        row = flight_row(who)
        partial, correction = read_backs(row, dep.freq_mhz, who)
        if partial:
            s.say("R2", clr.freq_mhz, partial,
                  "a DELIBERATELY incomplete read-back: the level and the "
                  "destination, no frequency and no squawk (#134)")
        else:
            print("\n── R2  SKIPPED: nothing was assigned to read back")
        # THE REFUSAL, ASKED FOR ON PURPOSE, and asked for HERE rather than
        # anywhere else in the run: Ground refuses an unagreed clearance, and
        # the only moment a clearance is issued-and-not-agreed is between an
        # incomplete read-back and its correction. On 12 August that window was
        # the whole sortie because nothing could close it.
        refused_ev = s.say("R3", gnd.freq_mhz,
                           f"{gnd.name}, {who}, ready to taxi.",
                           "taxi asked for on a clearance nobody has agreed "
                           "(#135)")
        if correction:
            s.say("R4", clr.freq_mhz, correction,
                  "the correction -- ONLY the missing items, said the sloppy "
                  "way a human says them (#134)")
        # READ BEFORE HE LANDS, because the row will not be there afterwards:
        # `flights.working` excludes anything the engine has marked `landed`, so
        # asking at the end of a successful sortie returns nothing and the
        # read-back verdict would report NOT EXERCISED on a run that exercised
        # it perfectly.
        agreed = flight_row(who) or row
        s.say("R5", gnd.freq_mhz, f"{gnd.name}, {who}, ready to taxi.",
              "and now he may move")
        s.say("R6", gnd.freq_mhz,
              f"{gnd.name}, {who}, holding short of runway {out_rwy}.",
              "holding short is Tower's cue")
        s.say("R7", twr.freq_mhz,
              f"{twr.name}, {who}, holding short runway {out_rwy}, "
              f"ready for departure.",
              "only Tower puts an aeroplane on the runway")

        # ---- and he goes --------------------------------------------------
        cruise = float(agreed.get("cruise_ft") or row.get("cruise_ft") or 8_000)
        alt = climb_out(cruise, float(getattr(kob, "elevation_ft", 0) or 0),
                        args.out_nm)
        out_to = _step(kob.lat, kob.lon, float(kob.runway), args.out_nm)
        said_dep = [False]
        rolled_at = time.time()

        def outbound(remaining: float) -> bool:
            nm = args.out_nm - remaining
            s.here(nm, "KOB")
            # HE GOES WHEN HE IS SENT, and only changes channel on his own if
            # nobody sends him. A fixture that switches to Departure on a
            # distance takes the rung away from the rule under test: `heard_on`
            # is what decides who is working him, so arriving on Departure's
            # frequency unasked makes the Tower -> Departure handoff
            # unnecessary, and a handoff that never had to fire cannot be
            # scored. The fallback exists so a rung that is BROKEN stalls the
            # run for a leg rather than for ever, and it says which it was.
            if not said_dep[0] and (sent_to(s, dep.name, th, rolled_at)
                                    or nm >= args.dep_nm):
                said_dep[0] = True
                how = ("as sent" if sent_to(s, dep.name, th, rolled_at)
                       else f"UNSENT, at {args.dep_nm:.0f} nm")
                s.say("R8", dep.freq_mhz,
                      f"{dep.name}, {who}, airborne off {out_rwy}, passing "
                      f"{say.spell_alt(_round_k(alt(remaining)))} "
                      f"for {say.spell_alt(int(cruise))}.",
                      f"checking in with the radar man who has him now ({how})")
            print(f"  .. {nm:5.1f} nm from {kob.name}, "
                  f"{alt(remaining):6.0f} ft", end="\r", flush=True)
            return False

        ghost.put(in_air=True, speed_kt=args.speed, alt_ft=300.0)
        fly_to(ghost, out_to[0], out_to[1], speed_kt=args.speed, alt_for=alt,
               tick=args.tick, watch=outbound)
        print(f"\n  he is {args.out_nm:.0f} miles off {kob.name}.")
        s.say("R9", ctr.freq_mhz,
              f"{ctr.name}, {who}, level {say.spell_alt(int(cruise))}, "
              f"inbound {th.arrival}.",
              "the enroute leg, such as it is on a twenty-mile sortie "
              + ("(as sent)" if sent_to(s, ctr.name, th, rolled_at)
                 else "(UNSENT -- nobody gave him to Center)"))

        # ---- round onto the final approach course --------------------------
        # THE TURN IS FLOWN, NOT TELEPORTED. A ghost put down on the final
        # approach course would be an arrival that never arrived, and the trend
        # -- which is what makes an arrival an arrival -- is exactly what a jump
        # destroys. So he flies the join: out on the runway heading, round to
        # the radial the procedure brings him in on, and down it.
        from marshall.core import airspace as _air
        join_nm = join_range(bat, ghost.lat, ghost.lon, radial, args.from_nm,
                             float(_air.TERMINAL_NM) + 5.0)
        if join_nm != args.from_nm:
            print(f"  joining at {join_nm:.0f} nm rather than "
                  f"{args.from_nm:.0f}: the direct leg would have cut inside "
                  f"the terminal area and provoked the Center rung twice")
        join = _step(bat.lat, bat.lon, radial, join_nm)

        def transit(remaining: float) -> bool:
            _b, nm = _bearing_range(ghost.lat, ghost.lon, bat.lat, bat.lon)
            s.here(nm, "BAT")
            print(f"  .. {nm:5.1f} nm from {bat.name}, joining the "
                  f"{radial:03.0f} radial", end="\r", flush=True)
            return False

        fly_to(ghost, join[0], join[1], speed_kt=args.speed,
               alt_for=lambda _r: cruise, tick=args.tick, watch=transit)
        print(f"\n  established on the {radial:03.0f} radial at "
              f"{join_nm:.0f} miles.")

        # ---- and down it ---------------------------------------------------
        said_apr, said_twr = [False], [False]
        # THE ARRIVAL'S TOWER, AND ONLY AFTER HE TURNED FOR HOME. "Was he handed
        # to a tower" is the wrong question on a sortie: he was, twenty minutes
        # ago, by Kobuleti Ground -- so a fixture asking it would have called
        # Batumi Tower at thirty-two miles, on the strength of a handoff at the
        # other aerodrome. A role is only unique within one, and a rung is only
        # meaningful within a leg.
        turned_at = time.time()

        def inbound(remaining: float) -> bool:
            s.here(remaining, "BAT")
            if not said_apr[0] and (sent_to(s, apr.name, th, turned_at)
                                    or remaining <= args.approach_nm):
                said_apr[0] = True
                how = ("as sent" if sent_to(s, apr.name, th, turned_at)
                       else f"UNSENT, at {args.approach_nm:.0f} nm")
                s.say("R10", apr.freq_mhz,
                      f"{apr.name}, {who}, {int(remaining)} miles out, "
                      f"descending {say.spell_alt(_round_k(arrival_alt(remaining)))},"
                      f" information alpha, request the I-L-S runway {in_rwy}.",
                      f"the arrival, on the frequency that makes him "
                      f"Approach's ({how})")
            if not said_twr[0] and sent_to(s, btwr.name, th, turned_at):
                said_twr[0] = True
                s.say("R11", btwr.freq_mhz,
                      f"{btwr.name}, {who}, {max(int(remaining), 1)} miles on "
                      f"final, gear down.",
                      "he goes when he is sent -- the last rung is only under "
                      "test from Tower's frequency")
            print(f"  .. {remaining:5.1f} nm from {bat.name}, "
                  f"{arrival_alt(remaining):6.0f} ft", end="\r", flush=True)
            return False

        touchdown = _step(bat.lat, bat.lon, radial, 0.3)
        # AT CRUISE UNTIL THE DESCENT BEGINS. `arrival_alt` is a profile for the
        # last thirty miles and returns twelve thousand beyond forty, so a jet
        # levelled at ten would CLIMB to join his own approach.
        fly_to(ghost, touchdown[0], touchdown[1], speed_kt=args.in_speed,
               alt_for=lambda nm: min(cruise, arrival_alt(nm)),
               tick=args.tick, watch=inbound)

        # ---- and he stops --------------------------------------------------
        # WHICH IS THE WHOLE OF #154. `landed` is not a place a fixture can be
        # put; it is what `derive` concludes about an aeroplane that HAS FLOWN
        # and is now stopped, and it follows `approach` and nothing else.
        ghost.put(lat=bat.lat, lon=bat.lon,
                  alt_ft=float(getattr(bat, "elevation_ft", 0) or 0),
                  speed_kt=0.0, heading=final_hdg, in_air=False)
        s.here(0.0, "BAT")
        print(f"\n  down at {bat.name}.")
        time.sleep(args.tick * 2)
        s.say("R12", btwr.freq_mhz,
              f"{btwr.name}, {who}, on the ground, runway {in_rwy}.",
              "the runway is Tower's and he says to get off it")
        s.say("R13", btwr.freq_mhz, f"{who}, request taxi to parking.",
              "parking is not Tower's; he names Ground (#100)")
        s.say("R14", bgnd.freq_mhz,
              f"{bgnd.name}, {who}, request taxi to parking.",
              "Ground parks him, and there is nobody after Ground")
    except _Enough as e:
        print(f"\n  stopped after {e}, as asked.")
    except KeyboardInterrupt:
        print("\n  interrupted.")
    finally:
        ghost.close()
        forget_him(who, "http://localhost:8000")

    got = s.events()
    transcript(got, s.line, s.t0)

    print("\n  every handoff the bridge AUTHORISED:")
    for t, role, text in the_eight_rungs(got):
        print(f"    {s.line.where(t)}  -> {role}: {text}")
    if not the_eight_rungs(got):
        print("    (none)")
    print("\n  the rung he was on, transmission by transmission:")
    for rid, phase in s.phases:
        print(f"    {rid:<4} {phase or '(nothing on the board)'}")

    verdicts = [
        a_verdict("#134  the read-back exchange terminates",
                  *the_read_back_terminated(got, agreed,
                                            s.tries.get("R2", 0))),
        a_verdict("#135  Ground refuses an unagreed clearance",
                  *ground_refused_an_unagreed_clearance(refused_ev, clr)),
        a_verdict("#154  he reaches `landed`, and then `taxi_in`",
                  *he_landed(s)),
        a_verdict("      the ladder ran forwards, never back",
                  *the_ladder_ran_forwards(got, th)),
        a_verdict("      every reply on its own field's frequency",
                  *right_fields_numbers(got, th)),
    ]
    print()
    for name, how, why in verdicts:
        print(f"{how:<14} {name}\n               {why}")
    if s.misheard:
        # WHOSE FAULT A ROW IS. A controller answering half a sentence must not
        # be scored for the answer, and this is the only place that can say so
        # -- the verdicts above read the record and cannot tell a bad reply from
        # a good reply to a bad question.
        print(f"\n  MISHEARD even after a second attempt: "
              f"{', '.join(s.misheard)} -- our Polly against our Whisper, and "
              f"a rung whose question did not arrive answers nothing.")
    _limits()
    return 1 if any(h == "FAIL" for _, h, _ in verdicts) else 0


# --- the touch-and-go, which nothing had ever flown -------------------------
#
# THE GOODBYE MADE A NEW FAULT REACHABLE. #77 has Tower name Ground in the
# roll-out transmission, unprompted, off the radar poll -- and the poll runs
# every four seconds against a roll that takes ten to twenty. So on a
# touch-and-go it fires: he is told to call Ground and put on `taxi_in`, and
# then he flies. Before #164 nothing could retrieve him -- there was no row out
# of a ground seat at all, `handoff_on_the_event` covers only approach and
# tower, and `phases.derive` refuses `taxi_in -> landed`.
#
# It is enforced in TWO places and so it has to be provoked in two, which is
# why this mode gets airborne twice off one arrival:
#
#   the phase guard   he is still on TOWER's frequency, and his PHASE says
#                     Ground. `due` gives a phase whose `aims_at` is "none"
#                     outright ownership, so without the guard the phase hands
#                     a flying aeroplane to Ground before the rule table is
#                     consulted at all. What a machine can judge is the
#                     ABSENCE: no ground seat was named while he was airborne.
#   the rule rows     he has complied -- checked in with Ground -- and THEN
#                     gets airborne. Now he really is a ground seat's aeroplane
#                     and `Rule("ground", "tower", "airborne")` is the only
#                     thing that can move him. Here a machine can judge a
#                     PRESENCE: an authorised handoff back to Tower.
#
# Only the second half is the invariant proving itself. The first half is the
# half that fails silently, and a run that only flew the second would pass with
# the guard deleted.


def wait_for(s: Sortie, want, seconds: float, tick: float = 1.0):
    """Poll the recorder until something appears, or give up and say so.

    THE RECORD, NOT THE AUDIO -- the same bargain every other judgement in this
    file makes. `want(events)` returns whatever it found or a falsy value, and
    the timeout is a real answer: a transmission that had not arrived after a
    minute did not arrive.
    """
    end = time.time() + seconds
    while True:
        got = want(s.events())
        if got:
            return got
        if time.time() >= end:
            return None
        time.sleep(tick)


def _after(events: list[dict], t: float, kinds: tuple[str, ...]) -> list[dict]:
    return [e for e in events if float(e.get("t", 0.0)) > t
            and str(e.get("kind", "")) in kinds]


def get_airborne(ghost: Ghost, bat, heading: float, *, speed: float,
                 seconds: float, tick: float, s: Sortie, why: str) -> None:
    """Off the runway again, climbing away, for as long as it takes to be seen.

    HE HAS TO BE POSITIVELY FLYING, because the rule says so. `_airborne` is
    `not on_ground and range_nm is not None` and `is_on_the_ground` falls back
    to altitude-above-the-FIELD under two hundred feet AND under sixty knots,
    since a ghost is in `tracks` and never in the sim's unit list. So a fixture
    that lifts off at forty knots is still on the ground to every rule that
    matters, and the run would prove nothing.

    And he must stay up for several POLLS. The monitor's clock is its own, not
    ours; one repaint is a frame the poll can miss entirely.
    """
    elev = float(getattr(bat, "elevation_ft", 0) or 0)
    print(f"\n── he gets airborne again -- {why}")
    ghost.put(in_air=True, speed_kt=speed, alt_ft=elev + 400.0,
              heading=heading)
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(tick)
        nlat, nlon = _step(ghost.lat, ghost.lon, heading,
                           speed * (tick / 3600.0))
        ghost.put(lat=nlat, lon=nlon,
                  alt_ft=min(elev + 4_000.0, ghost.alt_ft + 250.0))
        _b, nm = _bearing_range(bat.lat, bat.lon, ghost.lat, ghost.lon)
        s.here(nm, "BAT")
        print(f"  .. airborne, {nm:5.1f} nm from {bat.name}, "
              f"{ghost.alt_ft:6.0f} ft", end="\r", flush=True)
    print()


def put_him_down(ghost: Ghost, bat, heading: float) -> None:
    """Stopped, on the field. `on_ground` is a speed and an altitude here."""
    ghost.put(lat=bat.lat, lon=bat.lon,
              alt_ft=float(getattr(bat, "elevation_ft", 0) or 0),
              speed_kt=0.0, heading=heading, in_air=False)


def _ground_names(th, field: str) -> set[str]:
    """Every seat at this aerodrome that cannot have a flying aeroplane.

    `_GROUND_SEATS` IS THE AUTHORITY and is read rather than copied -- the whole
    substance of #164 is that the list is named once so its two enforcement
    points cannot drift, and a harness with its own third copy would be the
    same mistake one level out.
    """
    from marshall.atc.handoff import _GROUND_SEATS
    return {s.name.lower() for s in th.stations
            if s.role in _GROUND_SEATS
            and (s.field or "").lower() == field.lower()}


def nobody_sent_a_flying_man_to_ground(events: list[dict], th, field: str,
                                       after: float, provoked: bool
                                       ) -> tuple[bool | None, str]:
    """#164, the half that fails silently -- the phase-ownership guard.

    `after` is the moment he left the ground with `taxi_in` on him. Every
    handoff from then on is judged, and a ground seat named at all is the fault:
    before the guard the phase branch fired one every four seconds.
    """
    if not provoked:
        return None, ("the goodbye never came, so he was never on `taxi_in` "
                      "-- the situation the guard exists for did not arise")
    seats = _ground_names(th, field)
    bad = []
    for e in handoffs(events):
        if float(e.get("t", 0.0)) <= after:
            continue
        text = str(e.get("text", "")).lower()
        if str(e.get("to", "")).lower() in ("ground", "clearance") or \
                any(n in text for n in seats):
            bad.append(e)
    if bad:
        return False, ("a flying aeroplane was handed to a ground seat: "
                       + " | ".join(str(e.get("text", "")) for e in bad))
    seen = [str(e.get("to", "?")) for e in handoffs(events)
            if float(e.get("t", 0.0)) > after]
    return True, ("no ground seat was named while he was flying"
                  + (f"; what did fire: {', '.join(seen)}" if seen
                     else "; nothing was handed over at all"))


def tower_took_him_back(events: list[dict], th, twr, after: float
                        ) -> tuple[bool | None, str]:
    """#164, the half that can be seen -- `Rule("ground", "tower", "airborne")`.

    He is a ground seat's aeroplane by the only measure that decides it --
    `heard_on`, the frequency he last spoke on -- and he is flying. The one
    thing that may move him is the rule row, and it names Tower.
    """
    got = [e for e in handoffs(events) if float(e.get("t", 0.0)) > after
           and handed_to_station(str(e.get("text", "")),
                                 str(e.get("to", "")), th) == twr.name]
    if got:
        return True, f"{twr.name} took him back: {got[0].get('text', '')}"
    other = [f"{e.get('to', '?')}: {e.get('text', '')}"
             for e in handoffs(events) if float(e.get("t", 0.0)) > after]
    if other:
        return False, (f"he was moved, but not to {twr.name} -- "
                       + " | ".join(other))
    why = [str(e.get("text", "")) for e in _after(events, after,
                                                  ("handoff/none",))]
    return False, ("nothing retrieved him; he is still a ground seat's "
                   "aeroplane, airborne"
                   + (f" -- the monitor said: {' | '.join(why[:3])}" if why
                      else " -- and the monitor said nothing at all"))


def the_goodbye_named_ground(events: list[dict], gnd, after: float
                             ) -> tuple[bool | None, str]:
    """#77 criterion 1 -- unprompted, and with the RIGHT number in it.

    Two facts and #115's point is the second: the frequency he is told to dial
    must be the frequency the handoff was booked against, or the words and the
    record are two answers to one question.
    """
    from marshall.core import say
    bye = _after(events, after, ("atc/landed",))
    if not bye:
        return None, "nothing was said on the roll-out at all"
    text = str(bye[0].get("text", ""))
    low = text.lower()
    if gnd.name.lower() not in low:
        return False, f"the roll-out named no Ground: {text}"
    want = say.spell_freq(gnd.freq_mhz).lower()
    if want not in low:
        return False, (f"named {gnd.name} without his frequency "
                       f"({want}): {text}")
    ho = [e for e in _after(events, after, ("atc/handoff",))
          if str(e.get("to", "")).lower() == "ground"]
    if not ho:
        return False, (f"the words carried the handoff and the record did "
                       f"not book it: {text}")
    return True, f"{text}"


def _touch_and_go(args, th, recorder: Path) -> int:
    """An arrival, a landing, and then he flies -- twice, for two enforcements."""
    from marshall.core import say
    bat = th.field_named(th.arrival)
    apr = _st(th, "approach", bat.name)
    twr = _st(th, "tower", bat.name)
    gnd = _st(th, "ground", bat.name)
    if None in (bat, apr, twr, gnd):
        print(f"!! {th.arrival} has no approach, tower and ground to fly this",
              file=sys.stderr)
        return 2
    profile = th.approach
    radial, final_hdg = arrival_geometry(bat, profile)
    in_rwy = say.spell_rwy(bat.runway_in_use(th.wind_from_deg))
    who, track = args.name, f"362nd_{args.name}"
    s = Sortie(args, recorder)

    print(f"a touch-and-go: {who} into {bat.name}, runway {in_rwy}, on the "
          f"{radial:03.0f} radial from {args.from_nm:.0f} miles")
    print(f"  track {track}, recorder {recorder.name}")
    print(f"  {apr.name} {apr.freq_mhz:.3f} / {twr.name} {twr.freq_mhz:.3f} / "
          f"{gnd.name} {gnd.freq_mhz:.3f}")

    start = _step(bat.lat, bat.lon, radial, args.from_nm)
    ghost = Ghost(track, who, lat=start[0], lon=start[1],
                  alt_ft=arrival_alt(args.from_nm), heading=final_hdg,
                  speed_kt=args.in_speed, in_air=True, tick=args.tick).start()
    s.here(args.from_nm, "BAT")
    said_apr, said_twr = [False], [False]
    began = time.time()
    touched, first_up, checked_in, second_up = 0.0, 0.0, 0.0, 0.0
    bye = None
    try:
        def inbound(remaining: float) -> bool:
            s.here(remaining, "BAT")
            if not said_apr[0] and (sent_to(s, apr.name, th, began)
                                    or remaining <= args.approach_nm):
                said_apr[0] = True
                s.say("T1", apr.freq_mhz,
                      f"{apr.name}, {who}, {int(remaining)} miles northwest, "
                      f"descending {say.spell_alt(_round_k(arrival_alt(remaining)))}"
                      f", information alpha, request the I-L-S runway {in_rwy}.",
                      "the arrival, on the frequency that makes him Approach's")
            if not said_twr[0] and sent_to(s, twr.name, th, began):
                said_twr[0] = True
                s.say("T2", twr.freq_mhz,
                      f"{twr.name}, {who}, {max(int(remaining), 1)} miles on "
                      f"final, gear down.",
                      "he goes when he is sent")
            print(f"  .. {remaining:5.1f} nm from {bat.name}, "
                  f"{arrival_alt(remaining):6.0f} ft", end="\r", flush=True)
            return False

        touchdown = _step(bat.lat, bat.lon, radial, 0.3)
        fly_to(ghost, touchdown[0], touchdown[1], speed_kt=args.in_speed,
               alt_for=arrival_alt, tick=args.tick, watch=inbound)

        # ---- he touches down, and says nothing --------------------------
        put_him_down(ghost, bat, final_hdg)
        touched = time.time()
        s.here(0.0, "BAT")
        print(f"\n  down at {bat.name}, and he does not key the mic.")
        print(f"  waiting up to {args.goodbye_wait:.0f}s for the roll-out "
              f"transmission (#77 criterion 1)")
        bye = wait_for(s, lambda ev: _after(ev, touched, ("atc/landed",)),
                       args.goodbye_wait)
        if bye:
            print(f"   ATC[down]: {bye[0].get('text', '')}")
        else:
            print("   (nothing -- the goodbye never came)")

        # ---- and then he flies. The phase says Ground; he is on Tower ----
        first_up = time.time()
        get_airborne(ghost, bat, final_hdg, speed=args.tg_speed,
                     seconds=args.tg_watch, tick=args.tick, s=s,
                     why="a TOUCH-AND-GO, still on Tower's frequency, with "
                         "`taxi_in` on him (#164, the phase guard)")

        # ---- round again, and this time he COMPLIES before he flies ------
        put_him_down(ghost, bat, final_hdg)
        s.here(0.0, "BAT")
        print(f"\n  stopped again at {bat.name}.")
        time.sleep(args.tick * 2)
        s.say("T3", gnd.freq_mhz,
              f"{gnd.name}, {who}, clear of runway {in_rwy}, "
              f"request taxi to parking.",
              "he does as he was told, so now he really is Ground's")
        checked_in = time.time()
        second_up = time.time()
        get_airborne(ghost, bat, final_hdg, speed=args.tg_speed,
                     seconds=args.tg_watch, tick=args.tick, s=s,
                     why="airborne off a GROUND frequency -- nothing but "
                         "`Rule(ground, tower, airborne)` can move him (#164)")
    except _Enough as e:
        print(f"\n  stopped after {e}, as asked.")
    except KeyboardInterrupt:
        print("\n  interrupted.")
    finally:
        ghost.close()
        forget_him(who, "http://localhost:8000")

    got = s.events()
    transcript(got, s.line, s.t0)
    print("\n  every handoff the bridge AUTHORISED:")
    for t, role, text in the_eight_rungs(got):
        print(f"    {s.line.where(t)}  -> {role}: {text}")
    if not the_eight_rungs(got):
        print("    (none)")
    print("\n  every reason the monitor gave for keeping him:")
    for e in got:
        if str(e.get("kind", "")) == "handoff/none":
            print(f"    {s.line.where(float(e.get('t', 0.0)))}  "
                  f"{e.get('text', '')}")

    verdicts = [
        a_verdict("#77   the roll-out named Ground, unprompted, with his number",
                  *the_goodbye_named_ground(got, gnd, touched)),
        a_verdict("#164  a flying aeroplane is never sent to Ground",
                  *nobody_sent_a_flying_man_to_ground(got, th, bat.name,
                                                      first_up, bool(bye))),
        a_verdict("#164  and Tower takes him back off a ground frequency",
                  *tower_took_him_back(got, th, twr, second_up)),
        a_verdict("      every reply on its own field's frequency",
                  *right_fields_numbers(got, th)),
    ]
    print()
    for name, how, why in verdicts:
        print(f"{how:<14} {name}\n               {why}")
    if s.misheard:
        print(f"\n  MISHEARD even after a second attempt: "
              f"{', '.join(s.misheard)}")
    print(f"\n  (he checked in with {gnd.name} at "
          f"{int(checked_in - s.t0) if checked_in else 0}s.)")
    _limits()
    return 1 if any(h == "FAIL" for _, h, _ in verdicts) else 0


def _limits() -> None:
    print("\n  What this run did NOT check: the sim's feed (a ghost is written "
          "straight into `tracks` and skips the stream, the projection and the "
          "reconcile); anything about how an aeroplane actually flies; and "
          "whether any of it SOUNDED like one controller, which is a pilot's "
          "and stays a pilot's.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", default=config.SRS_HOST)
    ap.add_argument("--session", default=os.environ.get("MARSHALL_SESSION", "hooks"))
    ap.add_argument("--voice", default="Joey")
    ap.add_argument("--name", default="")
    # NO DEFAULT UNTIL THE DIRECTION IS KNOWN. 3 to 32 is a departure and 32 to
    # 2 is an arrival, and a single pair of numbers cannot be both -- so they
    # are filled in below, after the direction has been settled.
    ap.add_argument("--from-nm", type=float, default=None,
                    help="where he starts, in miles from the field "
                         "(default 3 outbound, 32 inbound)")
    ap.add_argument("--to", type=float, default=None,
                    help="where he stops (default 32 outbound, 2 inbound). "
                         "Smaller than --from-nm IS an arrival, and implies "
                         "--inbound")
    ap.add_argument("--inbound", action="store_true",
                    help="fly him AT the arrival field instead of out of the "
                         "departure one: range decreasing and heading pointed "
                         "at the field, which is what makes him an arrival to "
                         "every rule that reads the trend")
    ap.add_argument("--approach-nm", type=float, default=24.0,
                    help="inbound: where he checks in with Approach")
    ap.add_argument("--speed", type=float, default=None,
                    help="knots (default 420 outbound, 300 inbound)")
    ap.add_argument("--tick", type=float, default=2.0,
                    help="seconds between radar updates")
    ap.add_argument("--settle", type=float, default=14.0,
                    help="seconds to let the controller answer a check-in")
    ap.add_argument("--from-tower", action="store_true",
                    help="check in with TOWER first, so the sortie has already "
                         "had one handoff before the Center rung is due -- "
                         "which is what the pilot's 11 August flight did, and "
                         "the case a set of callsigns could not survive")
    ap.add_argument("--from-center", action="store_true",
                    help="inbound: start with GEORGIA CENTER and ask HIM for "
                         "the approach -- the seat that issued one twice on 12 "
                         "August and does not own it (#138b)")
    ap.add_argument("--quiet", action="store_true",
                    help="do not speak at all -- reuses whoever is already on "
                         "the board under this name")
    ap.add_argument("--sortie", action="store_true",
                    help="fly the WHOLE ladder in one run: a stand at the "
                         "departure field, the eight rungs, and a stand at the "
                         "arrival one. The only mode that can reach `landed`, "
                         "which follows `approach` and nothing else")
    ap.add_argument("--plan", default="Domino",
                    help="the flight plan he asks for BY LABEL, which is the "
                         "half of the plan-to-clearance seam that had only "
                         "ever been tested over HTTP")
    ap.add_argument("--out-nm", type=float, default=27.0,
                    help="sortie: how far out he flies before the enroute leg "
                         "-- past CENTER_NM, or Departure never lets go")
    ap.add_argument("--in-speed", type=float, default=330.0,
                    help="sortie: knots on the arrival")
    ap.add_argument("--dep-nm", type=float, default=9.0,
                    help="sortie: where he calls Departure if NOBODY sent him "
                         "-- past the tower->departure distance, so the rule "
                         "has had its chance and the fallback is evidence "
                         "rather than a shortcut")
    ap.add_argument("--wait", type=float, default=22.0,
                    help="seconds to allow for a reply before calling it "
                         "silence")
    ap.add_argument("--touch-and-go", action="store_true",
                    help="fly an ARRIVAL, land, and then get airborne again -- "
                         "twice, because #164 is enforced in two places: once "
                         "with the roll-out's `taxi_in` on him and Tower still "
                         "his (the phase guard, which fails SILENTLY), and once "
                         "after he has checked in with Ground (the rule row, "
                         "which fails visibly)")
    ap.add_argument("--goodbye-wait", type=float, default=60.0,
                    help="touch-and-go: seconds to allow for the roll-out "
                         "transmission before calling it silence. The radar "
                         "poll is on its own clock, not ours")
    ap.add_argument("--tg-watch", type=float, default=45.0,
                    help="touch-and-go: seconds to stay airborne and watch "
                         "after each lift-off -- several polls, not one")
    ap.add_argument("--tg-speed", type=float, default=200.0,
                    help="touch-and-go: knots on the climb-out. Must be well "
                         "over GROUND_SPEED_KT or he is still 'down' to every "
                         "rule that reads it")
    ap.add_argument("--stop-after", default="",
                    help="sortie: the last rung to fly (R1..R14). The ground "
                         "rungs are three minutes and the whole ladder is "
                         "twenty, so this is how the read-back exchange is "
                         "iterated on without re-flying the aeroplane")
    args = ap.parse_args(argv)
    # A DIRECTION IS EITHER DECLARED OR IMPLIED, and implying it from the ranges
    # is the reading that cannot be got wrong: "to 2 from 32" is an arrival in
    # any language, and a flag saying otherwise would be a contradiction with a
    # default in it.
    # A SORTIE IS BOTH DIRECTIONS, so it settles its own numbers first: it flies
    # out to `--out-nm` and comes back from `--from-nm`, and asking
    # `flying_inbound` which of those it is has no answer.
    # A TOUCH-AND-GO IS AN ARRIVAL that does not stay arrived, so it settles
    # its own direction the way a sortie does rather than asking two ranges.
    inbound = (True if args.touch_and_go else
               False if args.sortie
               else flying_inbound(args.inbound, args.from_nm, args.to))
    if (args.sortie or args.touch_and_go) and args.from_nm is None:
        args.from_nm = 32.0
    if args.from_nm is None:
        args.from_nm = 32.0 if inbound else 3.0
    if args.to is None:
        args.to = 2.0 if inbound else 32.0
    if args.speed is None:
        args.speed = 300.0 if inbound else 420.0
    if inbound and not args.touch_and_go and args.to >= args.from_nm:
        print("!! an arrival ends closer than it starts", file=sys.stderr)
        return 2
    if not args.name:
        args.name = _a_name_nobody_has_flown()
    if not args.srs and not args.quiet:
        print("!! --srs is required (or SRS_HOST), or pass --quiet",
              file=sys.stderr)
        return 2

    _dsn_from_compose()
    from marshall.core import theatre as _theatre
    th = _theatre.current()
    # HIS OWN FIELD, and which one that is depends on which way he is going. An
    # arrival measured from the departure aerodrome is the fault `field_origin`
    # was given a field for: every range real, and every one belonging to the
    # wrong airport.
    want = (th.arrival if inbound else th.departure) or ""
    field = next((f for f in th.fields
                  if f.name.lower() == want.lower()), None)
    if field is None:
        print(f"!! {want} is not a field in {th.name}", file=sys.stderr)
        return 2
    recorder = config.BUILD_DIR / "logs" / f"flight-{args.session}.jsonl"
    if args.touch_and_go:
        return _touch_and_go(args, th, recorder)
    if args.sortie:
        return _sortie(args, th, recorder)
    if inbound:
        return _inbound(args, th, field, recorder)

    # OUT ON THE DEPARTURE RUNWAY'S HEADING, which is the direction a jet
    # leaving this field actually goes -- and direction is half the rule.
    # `outbound_beyond` needs "far out AND going further", so a ghost drifting
    # sideways would be a test of nothing.
    out_hdg = float(field.runway)
    track = f"362nd_{args.name}"

    print(f"ghost flight: {args.name} out of {field.name} on {out_hdg:03.0f}, "
          f"{args.from_nm:.0f} to {args.to:.0f} nm")
    print(f"  track {track}, recorder {recorder.name}")

    mark = size(recorder)
    nm = args.from_nm
    lat, lon = _step(field.lat, field.lon, out_hdg, nm)
    alt = 2_000.0
    paint(track, args.name, lat, lon, alt, out_hdg, args.speed)

    try:
        if not args.quiet:
            # ON DEPARTURE'S FREQUENCY, because who he is talking to is what
            # decides which rung of the ladder he is on. Checking in with
            # Approach would be a different test.
            # HIS FIELD'S DEPARTURE, asked of the THEATRE -- a role is only
            # unique within an aerodrome, and Kobuleti and Batumi both have one.
            from marshall.core import route as _r
            dep = _r.station_for("departure", field=field.name)
            mhz = getattr(dep, "freq_mhz", 0.0) or 123.3
            if args.from_tower:
                # THE RUNG BEFORE THE ONE UNDER TEST. Tower hands him to
                # Departure, and only then does the Center rung become due --
                # so this run asks whether the SECOND handoff of a sortie can
                # happen at all, which is the question the pilot's flight
                # answered "no" to for three minutes.
                twr = _r.station_for("tower", field=field.name)
                check_in(args, getattr(twr, "freq_mhz", 0.0) or 133.0,
                         f"{field.name} Tower, {args.name}, airborne off zero "
                         f"seven, passing one thousand.")
            check_in(args, mhz,
                     f"{field.name} Departure, {args.name}, checking in, "
                     f"passing two thousand for eight thousand.")

        # AND NOW HE FLIES. Every tick moves the row; the bridge's monitor polls
        # it on its own clock and decides for itself.
        while nm < args.to:
            time.sleep(args.tick)
            flown = args.speed * (args.tick / 3600.0)
            nm += flown
            lat, lon = _step(field.lat, field.lon, out_hdg, nm)
            alt = min(24_000.0, alt + 1_500.0 * (args.tick / 60.0))
            paint(track, args.name, lat, lon, alt, out_hdg, args.speed)
            got = events_since(recorder, mark)
            done, said = handed_to_center(got)
            if done:
                print(f"\n  HANDED at {nm:.0f} nm: {said}")
                break
            print(f"  .. {nm:5.1f} nm, {alt:6.0f} ft", end="\r", flush=True)
        else:
            print(f"\n  he reached {nm:.0f} nm and nobody handed him over.")
    finally:
        erase(track)
        forget_him(args.name, "http://localhost:8000")

    got = events_since(recorder, mark)
    ok, said = handed_to_center(got)
    print()
    for line in why_not(got):
        print(f"  monitor: {line}")
    if ok:
        print(f"\nPASS  departure -> center: {said}")
    else:
        print("\nFAIL  departure -> center never fired.")
        if not why_not(got):
            print("      AND THE MONITOR SAID NOTHING, which is its own fault "
                  "and is #122 -- the thread is not reaching the decision at "
                  "all. Look upstream of `watching_him`: the board, the radar "
                  "fix, or the loop itself.")
    _limits()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
