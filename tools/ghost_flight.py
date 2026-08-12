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
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
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
          heading: float, speed_kt: float, kind: str = "F-16C_50") -> None:
    """Put him on the scope, or move him. One row, upserted.

    `player` is set because that is what makes the picture print him as manned,
    and a manned contact is what the identity chain correlates an SRS client
    against. An unmanned ghost would be a different test.
    """
    from marshall.core import db
    with db.pool().connection() as c:
        c.execute(
            "INSERT INTO tracks (name, label, type, coalition, geog, alt_ft, "
            "                    heading, speed_kt, player, category, in_air, "
            "                    last_seen) "
            "VALUES (%s, %s, %s, 2, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, "
            "        %s, %s, %s, %s, 'Airplane', true, now()) "
            "ON CONFLICT (name) DO UPDATE SET "
            "  geog = EXCLUDED.geog, alt_ft = EXCLUDED.alt_ft, "
            "  heading = EXCLUDED.heading, speed_kt = EXCLUDED.speed_kt, "
            "  last_seen = now()",
            (name, label, kind, lon, lat, alt_ft, heading, speed_kt, label))


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
        self.marks: list[tuple[float, float]] = []

    def at(self, t: float, nm: float) -> None:
        self.marks.append((t, nm))

    def nm(self, t: float) -> float | None:
        best = None
        for mt, mnm in self.marks:
            if mt <= t + 0.5:
                best = mnm
            else:
                break
        return best


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
        nm = line.nm(t)
        where = "  ? nm" if nm is None else f"{nm:5.1f} nm"
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
    profile = th.approach
    radial, hdg = arrival_geometry(field, profile)
    track = f"362nd_{args.name}"
    apr = profile.station_for("approach", field=field.name)
    twr = profile.station_for("tower", field=field.name)
    ctr = profile.station_for("center", field=field.name)
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
    args = ap.parse_args(argv)
    # A DIRECTION IS EITHER DECLARED OR IMPLIED, and implying it from the ranges
    # is the reading that cannot be got wrong: "to 2 from 32" is an arrival in
    # any language, and a flag saying otherwise would be a contradiction with a
    # default in it.
    inbound = flying_inbound(args.inbound, args.from_nm, args.to)
    if args.from_nm is None:
        args.from_nm = 32.0 if inbound else 3.0
    if args.to is None:
        args.to = 2.0 if inbound else 32.0
    if args.speed is None:
        args.speed = 300.0 if inbound else 420.0
    if inbound and args.to >= args.from_nm:
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
            # HIS FIELD'S DEPARTURE, asked of the profile -- a role is only
            # unique within an aerodrome, and Kobuleti and Batumi both have one.
            from marshall.core import route as _r
            dep = _r.BATUMI_ASR.station_for("departure", field=field.name)
            mhz = getattr(dep, "freq_mhz", 0.0) or 123.3
            if args.from_tower:
                # THE RUNG BEFORE THE ONE UNDER TEST. Tower hands him to
                # Departure, and only then does the Center rung become due --
                # so this run asks whether the SECOND handoff of a sortie can
                # happen at all, which is the question the pilot's flight
                # answered "no" to for three minutes.
                twr = _r.BATUMI_ASR.station_for("tower", field=field.name)
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
