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

WHAT IT CANNOT PROVE, and must not be read as proving:

  * that the FEED works. The sim's stream, the projection, the unit naming and
    the reconcile are all upstream of the row this writes, and a ghost flies
    straight past every one of them. This checks the bridge, not the pipe.
  * anything about flying. A ghost has no aerodynamics: it holds a heading and
    a speed because it is told to, so a rung that depends on how an aeroplane
    actually behaves needs a real one.

Both limits are printed at the end, for the same reason `check.py` names what it
skipped: a check that quietly does not run reads exactly like one that passed.

    uv run --extra voice python tools/ghost_flight.py --srs <host>
    uv run --extra voice python tools/ghost_flight.py --srs <host> --to 40 --quiet
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
    somebody else's sortie, which is exactly what cost a real one on 11 August."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{base}/flights?callsign={name}",
                                     method="DELETE")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", default=config.SRS_HOST)
    ap.add_argument("--session", default=os.environ.get("MARSHALL_SESSION", "hooks"))
    ap.add_argument("--voice", default="Joey")
    ap.add_argument("--name", default="")
    ap.add_argument("--from-nm", type=float, default=3.0,
                    help="where he starts, in miles from the departure field")
    ap.add_argument("--to", type=float, default=32.0,
                    help="how far out to fly him")
    ap.add_argument("--speed", type=float, default=420.0, help="knots")
    ap.add_argument("--tick", type=float, default=2.0,
                    help="seconds between radar updates")
    ap.add_argument("--settle", type=float, default=14.0,
                    help="seconds to let the controller answer a check-in")
    ap.add_argument("--from-tower", action="store_true",
                    help="check in with TOWER first, so the sortie has already "
                         "had one handoff before the Center rung is due -- "
                         "which is what the pilot's 11 August flight did, and "
                         "the case a set of callsigns could not survive")
    ap.add_argument("--quiet", action="store_true",
                    help="do not speak at all -- reuses whoever is already on "
                         "the board under this name")
    args = ap.parse_args(argv)
    if not args.name:
        args.name = _a_name_nobody_has_flown()
    if not args.srs and not args.quiet:
        print("!! --srs is required (or SRS_HOST), or pass --quiet",
              file=sys.stderr)
        return 2

    _dsn_from_compose()
    from marshall.core import theatre as _theatre
    th = _theatre.current()
    field = next((f for f in th.fields
                  if f.name.lower() == (th.departure or "").lower()), None)
    if field is None:
        print(f"!! {th.departure} is not a field in {th.name}", file=sys.stderr)
        return 2

    # OUT ON THE DEPARTURE RUNWAY'S HEADING, which is the direction a jet
    # leaving this field actually goes -- and direction is half the rule.
    # `outbound_beyond` needs "far out AND going further", so a ghost drifting
    # sideways would be a test of nothing.
    out_hdg = float(field.runway)
    track = f"362nd_{args.name}"
    recorder = config.BUILD_DIR / "logs" / f"flight-{args.session}.jsonl"

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
    print("\n  What this run did NOT check: the sim's feed (a ghost is written "
          "straight into `tracks` and skips the stream, the projection and the "
          "reconcile), and anything about how an aeroplane actually flies.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
