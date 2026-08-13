"""One in the letdown: nobody is vectored until somebody is cleared.

D4 and F4 on the card -- #15, and the safety-relevant one. With traffic on
frequency a vector is not information, it is an INVITATION to start the
approach, so issuing one to two aircraft that have not been sequenced puts two
aeroplanes on the same intercept, at the same fix, at the same altitude.

    uv run python tools/letdown_check.py

The case that was broken is the ordinary one: a full stack with nobody cleared
yet. The guard only applied when somebody DID own the approach, so with nobody
cleared it switched itself off and vectored the lot -- and a bridge restart
empties the blind engine, which is how it happened live.

No sim needed. The question is what the sequencer decides, and it decides from
the controller's own state plus whether radar sees traffic.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc import agent_atc as A

# One store per test module -- see agent_atc.Bridge. These used to be
# module globals and every case had to remember to clear them.
_BRIDGE = A.Bridge()
from marshall.atc import controller as atc
from marshall.core import route as R


def main() -> int:
    p = R.BATUMI_ASR
    # QUALIFIED -- a role is unique only within an aerodrome. See
    # tests/test_two_fields.py; unqualified this was right by luck.
    hz = R.station_for("approach", field=R.ARRIVAL_FIELD).freq_mhz * 1e6
    ok = True

    def check(name: str, got: bool, expect: bool) -> None:
        nonlocal ok
        good = got is expect
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {name}")
        print(f"        expected {'vectored' if expect else 'left alone'}, "
              f"got {'vectored' if got else 'left alone'}")

    # Two known, neither cleared -- the case that was broken.
    ctl = atc.Controller(p)
    ctl.check_in("Pony 1-1")
    ctl.check_in("Pony 1-2")
    for ac in ctl.aircraft.values():
        ac.phase = atc.Phase.HOLDING
    _BRIDGE.heard_on.update({"Pony 1-1": hz, "Pony 1-2": hz})
    check("two holding, nobody cleared: Pony 1-1",
          A.may_be_vectored(_BRIDGE, ctl, "Pony 1-1", freq_hz=hz), False)
    check("two holding, nobody cleared: Pony 1-2",
          A.may_be_vectored(_BRIDGE, ctl, "Pony 1-2", freq_hz=hz), False)

    # And the same when the blind engine has been emptied by a restart but the
    # SCOPE still sees two. This is what made it fire live.
    fresh = atc.Controller(p)
    check("stack emptied by a restart, radar still sees two",
          A.may_be_vectored(_BRIDGE, fresh, "Pony 1-1", traffic=True, freq_hz=hz), False)

    # One cleared: he is worked, the other hears only his hold.
    ctl2 = atc.Controller(p)
    ctl2.report_beacon("Pony 1-1", 4000)
    ctl2.report_beacon("Pony 1-2", 5000)
    _BRIDGE.heard_on.update({"Pony 1-1": hz, "Pony 1-2": hz})
    check("one cleared: the one who owns the approach",
          A.may_be_vectored(_BRIDGE, ctl2, "Pony 1-1", freq_hz=hz), True)
    check("one cleared: the one holding behind him",
          A.may_be_vectored(_BRIDGE, ctl2, "Pony 1-2", freq_hz=hz), False)

    # A single ship is worked normally -- the guard must not strand him.
    solo = atc.Controller(p)
    solo.report_beacon("Pony 1-1", 4000)
    _BRIDGE.heard_on["Pony 1-1"] = hz
    check("a single ship is unaffected",
          A.may_be_vectored(_BRIDGE, solo, "Pony 1-1", freq_hz=hz), True)

    print("\nall cases behaved" if ok else "\nSOME CASES FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
