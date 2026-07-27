"""Does the controller wait for a check-in before he starts working you?

B1a on the card, and the complaint behind it:

    "when we got a handoff from center to approach, by the time I switched
     over, approach was already half done with the first instruction"

The metronome worked anyone the deterministic controller knew about, and it knew
him from CENTER's frequency. So the pilot arrived on the new channel mid-sentence,
having missed a heading and an altitude, with no way of knowing what he missed.

    uv run python tools/checkin_check.py

Asked of the real predicate with a real controller state, three ways:

  never spoken here       not worked. He has not checked in with anybody.
  spoken on ANOTHER freq  not worked. The handoff has been issued and he has not
                          switched yet -- this is the case that was broken.
  spoken on THIS freq     worked normally, from the start of the instruction.

No sim needed: the question is about which channel a radio was last heard on,
and that is a fact the bridge already keeps.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc import agent_atc as A
from marshall.atc import controller as atc
from marshall.core import route as R


def main() -> int:
    p = R.BATUMI_ASR
    approach = p.station_for("approach").freq_mhz * 1e6
    center = p.station_for("center").freq_mhz * 1e6

    ctl = atc.Controller(p)
    ctl.report_beacon("Pony 1-1", 4000)          # known, cleared, being worked
    ctl.out.clear()

    cases = [
        ("never spoken on any frequency", None, False),
        ("still on Center's frequency after the handoff", center, False),
        ("checked in here", approach, True),
    ]
    ok = True
    for name, heard_on, expect in cases:
        A._heard_on.clear()
        if heard_on is not None:
            A._heard_on["Pony 1-1"] = heard_on
        got = A.may_be_vectored(ctl, "Pony 1-1", freq_hz=approach)
        good = got is expect
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {name}")
        print(f"        expected {'worked' if expect else 'left alone'}, "
              f"got {'worked' if got else 'left alone'}")

    # And the rule must not fire where no frequency is in play, or every caller
    # that does not care about channels would go silent.
    A._heard_on.clear()
    got = A.may_be_vectored(ctl, "Pony 1-1")
    print(f"  {'PASS' if got else 'FAIL'}  no frequency given: rule is off")
    ok = ok and got

    print("\nall cases behaved" if ok else "\nSOME CASES FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
