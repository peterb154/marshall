"""The bridge may only call functions that exist.

An AttributeError in the SRS thread is not an ordinary bug. The bridge IS the
radio: when it dies, the frequency goes silent, the pilot has no way to tell
whether he was heard, and the only symptom is that ATC stopped existing.

    AttributeError: module 'marshall.atc.flights' has no attribute
    'parse_adopting'. Did you mean: 'parse_joining'?

`parse_adopting` was removed when the flight model was simplified -- a pilot
joins HIMSELF, on his own radio, because that is the transmission radar can
corroborate, and rejoining after a break-out is joining rather than a case of
its own. The function went. Its call site did not.

WHY NO TEST CAUGHT IT, which is the part worth keeping. The dead call needed
`_who`, `_who` needs a resolved TRACK, and both routes to a track were blocked:
a pilot identified from a filed strip has a callsign and no track, and every
aeroplane in a formation resolved to nothing at all until that was fixed. So
the line was unreachable in practice and reachable the moment identity was
repaired -- the flight rehearsal created Apex and the bridge died on the very
next transmission.

That is the shape to guard: a call site whose module is imported at start-up
but whose LINE only runs deep inside a live sortie. Importing the module proves
nothing, and the unit suite never runs the SRS loop. Reading the source does.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# module alias in agent_atc.py -> the module it actually refers to
WATCHED = {
    "fl": "marshall/atc/flights.py",
    "identity": "marshall/atc/identity.py",
}


def _public(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


class TestTheBridgeOnlyCallsWhatExists(unittest.TestCase):
    def test_every_watched_attribute_is_real(self):
        src = (ROOT / "src" / "marshall" / "atc" / "agent_atc.py").read_text()
        tree = ast.parse(src)
        have = {alias: _public(ROOT / "src" / rel)
                for alias, rel in WATCHED.items()}

        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if not isinstance(base, ast.Name) or base.id not in have:
                continue
            if node.attr not in have[base.id]:
                missing.append(f"{base.id}.{node.attr} "
                               f"(line {node.lineno}) -> {WATCHED[base.id]}")

        self.assertEqual(missing, [], "the bridge calls things that do not "
                                      "exist; each one is a silent radio the "
                                      "first time that line is reached:\n  "
                                      + "\n  ".join(missing))


if __name__ == "__main__":
    unittest.main()
