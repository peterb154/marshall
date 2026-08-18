"""The flight-test kneeboard: what to test, and the issue number to report it as.

A second OpenKneeboard site, at /flighttest/, built from `docs/TEST_PLAN.md` and
`docs/ISSUES.md`. One tab per section of the card, plus an index of the open
issues.

The point is the loop it closes. A pilot flies a row, sees the issue number
beside it, and calls engineering with *"issue eleven failed, he turned me back
at four miles"* -- and that lands on the right GitHub issue with the acceptance
criteria already written down. Before this, a finding was a sentence in a log
that somebody had to place afterwards.

**Parsed, never re-authored.** The markdown is the source: written for a human,
reviewed in a diff, and already what the issues were filed from. A second copy
of the test plan living in Python would drift from it within a week, and the
copy the pilot reads in the cockpit is exactly the one that must not.

Deliberately plain. This is read at a glance, one-handed, in a moving aeroplane:
big type, the ID first because that is what gets said on the radio, and the
expectation in the pilot's own words wherever the card has them.
"""

from __future__ import annotations

import uuid

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs"

# Stable GUIDs -- OpenKneeboard remembers the page a pilot was on, so these must
# not change between builds or he loses his place mid-sortie.
GUIDS = {
    "ISSUES": "{1a7c9e30-5b42-4f81-9d63-0e5a24c71b90}",
    "A": "{2b8d0f41-6c53-4092-ae74-1f6b35d82ca1}",
    # E IS RETIRED, 13 August -- "known broken, do not report these as new"
    # emptied when its last two entries (#19, #20) were fixed, and the
    # section went the way B, C, D and F went. The GUID stays and is NEVER
    # reused: OpenKneeboard remembers the page a pilot was on, and handing
    # an old identifier to a new document drops him somewhere he did not
    # choose. The special-cases below (`m.group(1) == "E"`, `letter == "E"`)
    # stay with it -- that section had a shape of its own, two cells and no
    # test IDs, and if it ever comes back it comes back the same way.
    "E": "{6fc14385-a097-44d6-e2b8-5daf79bc60e5}",
    "G": "{81e365a7-c2b9-46f8-a4da-7fc19bde82a7}",
    "PLANS": "{92f476b8-d3ca-4709-b5eb-8ad2acef930b}",
    "H": "{a3b587c9-e4db-481a-c6fc-9be23acf041c}",
    # Section J, added 28 July: who the controller thinks you are.
    # A fresh GUID, never one recycled from a retired section --
    # OpenKneeboard remembers the page a pilot was on, and reusing an
    # identifier drops him somewhere he did not choose.
    "J": "{c5d2916a-7e48-4b3f-91ac-2d06f8b4e77c}",
    # ELEVEN SECTIONS HAD NO GUID AND SO DID NOT EXIST IN THE COCKPIT.
    #
    # The card opens by telling a pilot to fly Q FIRST -- the two-aerodrome
    # ladder, fifteen rows, the reason the card was rewritten -- and Q was not
    # on the kneeboard at all. Nor were R, S, T, or D, F, K, L, M, N and P.
    # Six pages of fifteen were reaching the aeroplane.
    #
    # The tool said so on every build: "section Q has no GUID and will NOT
    # appear". It prints into a container's start-up log, which nobody reads,
    # so a loud warning in a place nobody looks is a silent one. That is the
    # same lesson as the frequency table and the runway in use: being right in
    # a log is not the same as being reachable.
    #
    # Derived from a fixed namespace and the section letter (uuid5) rather than
    # rolled at random, so regenerating this table cannot hand a pilot a
    # different identifier for the same page and drop him somewhere he did not
    # choose.
    "D": "{ab69f853-6119-5365-a027-b8636e683b07}",
    "F": "{f02f089b-77c7-532b-a89b-ce4970c88089}",
    "K": "{a11164c8-98db-50e5-a813-c9df7a66c5c3}",
    "L": "{e14ceaf1-ecb4-5674-9fec-f3811a8142e2}",
    "M": "{c190d23a-3483-5d03-a4ec-ad60ccc6fbc7}",
    "N": "{6b469f68-f0b5-535b-967b-6bcbb3c48730}",
    "P": "{b2ab0ee5-938a-543f-ae4d-416b15694118}",
    "Q": "{d6a34be0-ca2a-5c21-a6cd-5d780cada813}",
    "R": "{51e91239-722a-59e1-83e0-b5c61ccb1589}",
    "S": "{911a0a23-a5b8-58ca-91f0-a4ba16a94a9f}",
    "T": "{f70ee367-2201-53fa-85b7-c0f74a483eef}",
    "U": "{b5a2d5b8-0933-5b38-88ff-358d9bdcfb5c}",
    # V ONWARDS IS `guid_for`'s, and is still WRITTEN DOWN here. The recipe
    # below is how a new one is computed; this table is the registry, and a
    # test asserts every section is in it. A derivable identifier that is not
    # recorded cannot be checked for a collision, and a collision hands a pilot
    # a page he did not choose -- which is the reason the retired sections'
    # GUIDs are never reused either.
    "V": "{89cd3cb6-560f-5972-83c5-5bbd01dd3084}",   # == guid_for("V")
}

# THE RECIPE, WRITTEN DOWN. The comment above says these are "derived from a
# fixed namespace and the section letter (uuid5)" and the namespace itself was
# never recorded anywhere -- so the next person to add a section (me, adding U)
# could not reproduce one, and tried eight candidate seeds before giving up. A
# derivation nobody can perform is a table of magic numbers with a story
# attached to it.
#
# The letters above predate this and KEEP their identifiers: OpenKneeboard
# remembers which page a pilot was on, and reissuing one would drop him
# somewhere he did not choose. From U onwards this function is the source.
_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "flighttest.marshall.invalid")


def guid_for(section: str) -> str:
    """The stable tab identifier for a card section."""
    return "{" + str(uuid.uuid5(_NS, section)) + "}"

# NO PER-LETTER TAB LABELS ANY MORE. `SHORT` mapped a section letter to a tab
# name -- "H" to "APPROACH" -- and `build_section` rendered one page per letter.
# Both are gone: a tab is a FLIGHT now, and `_tab_label` names those instead.
#
#     "Maybe each tab should be a flight with things we should test top to
#      bottom."
#
# The section GUIDS above are kept and are NEVER reused, which is the same rule
# section E retired under. OpenKneeboard remembers which page a pilot was on,
# and handing an old identifier to a new document drops him somewhere he did
# not choose -- so a retired identifier is a gravestone, not a spare.
_SECTION = re.compile(r"^## ([A-Z]) — (.+)$", re.M)
# A cockpit row. THE BOLD AND STRUCK FORMS ARE NOT DECORATION -- this pattern
# matched only a bare `| H4 |`, so every section written since 2 August was
# invisible ON THE KNEEBOARD ITSELF: Q, R, S and T rendered ZERO rows between
# them -- the two-field ladder, ATIS, the phraseology checks and the Kobuleti
# ILS. The card opens by telling a pilot to fly Q FIRST, and Q was not there.
#
# This is exactly #60, in a second tool. That issue fixed the same blindness in
# `tools/issue_sync.py`, which reports on the card; nobody looked at the page a
# pilot actually reads. A check and a display reading one document with two
# different ideas of what a row is.
_ROW = re.compile(r"^\|\s*(?:~~)?\**([A-Z]\d+[a-z]?)\**(?:~~)?\s*\|(.+)$")


def _row_id(cell: str) -> str:
    """The ID as it should be SPOKEN, with the markup taken off.

    A pilot says "S10 failed", not "asterisk asterisk S 10". The cell carries
    the emphasis the table uses; the identifier does not.
    """
    return cell.strip().strip("*").strip("~").strip("*").strip()
_ISSUE = re.compile(r"^## \[([A-Z]+-\d+)\]\s+(.*?)(?:\s+—\s+#(\d+))?\s*$", re.M)
# "**A1** — what this row is actually checking." The table has to stay terse to
# be readable as a table; the sentence is what makes it flyable by somebody who
# was not in the room when the bug was found.
# Runs to the NEXT why-line or the end of the block, not to the end of the line:
# the rows that need explaining most need more than one sentence, and a
# single-line capture silently drops everything after the first paragraph --
# which it did, losing the half of B3 that says what to actually report.
_WHY = re.compile(
    r"^\*\*([A-Z]\d+[a-z]?)\*\*\s+—\s+(.*?)"
    r"(?=\n\*\*[A-Z]\d+[a-z]?\*\*\s+—|\n---|\n## |\Z)", re.M | re.S)


def _read(name: str) -> str:
    try:
        return (DOCS / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _md(text: str) -> str:
    """The little bit of markdown the card actually uses. Not a parser."""
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return re.sub(r"\[#(\d+)\]", r'<span class="iss">#\1</span>', text)


def why() -> dict[str, str]:
    """{test id: the sentence saying what it is really checking}."""
    return {m.group(1): m.group(2) for m in _WHY.finditer(_read("TEST_PLAN.md"))}


def sections() -> list[tuple[str, str, list[dict]]]:
    """(letter, title, rows) for each section of the card, in card order."""
    card = _read("TEST_PLAN.md")
    notes = why()
    found = list(_SECTION.finditer(card))
    # ...AND STOPS AT THE NEXT HEADING OF ANY KIND. Slicing to the next LETTERED
    # section made the last one run to end of file, so section E -- "known
    # broken, do not report these as new" -- swallowed "Already flown, and kept
    # as the regression record" and the closing notes. Invisible while the row
    # pattern could not see a struck ID; the moment it could, twelve retired
    # rows appeared on the page that tells a pilot what NOT to report.
    heads = [mm.start() for mm in re.finditer(r"(?m)^## ", card)]
    out = []
    for m in found:
        after = [h for h in heads if h > m.start()]
        end = after[0] if after else len(card)
        rows = []
        for line in card[m.end():end].splitlines():
            # A STRUCK ROW IS RETIRED. Striking the ID through is what takes a
            # row off the cockpit list once a pilot has flown it -- the script
            # stays as the regression record, but a pilot's attention is the
            # scarcest thing here and it must not be spent on finished work.
            # See #60 for the two things a row's `[#n]` can mean.
            if line.lstrip().startswith("| ~~"):
                continue
            rm = _ROW.match(line)
            if not rm or set(rm.group(2)) <= set("-| "):
                # Section E is a different animal: a list of things you WILL see
                # and must not report, with no test IDs. Keep it -- it is the
                # page that saves a pilot a sortie -- and mark it so the
                # renderer knows not to look for an ID.
                cells = _cells(line)
                if (m.group(1) == "E" and len(cells) == 2 and cells[0]
                        and not set(cells[0]) <= set("-: ")
                        and not cells[0].startswith("What you")):
                    rows.append({"id": "", "prio": "", "what": cells[0],
                                 "expect": cells[1], "issue": "", "why": ""})
                continue
            cells = _cells(line)
            if len(cells) < 3:
                continue
            # Section A has no priority column; the rest do. Normalise so one
            # renderer draws both rather than two nearly-identical ones.
            if len(cells) >= 5:
                ident, prio, what, expect, issue = cells[:5]
            else:
                ident, what, expect, issue = cells[:4]
                prio = ""
            ident = _row_id(ident)
            rows.append({"id": ident, "prio": prio, "what": what,
                         "expect": expect, "issue": issue,
                         "why": notes.get(ident, "")})
        out.append((m.group(1), m.group(2), rows))
    return out


_FLIGHT = re.compile(r"^### (.+?)$\n(.*?)(?=\n### |\n## |\Z)", re.M | re.S)


def flights() -> list[tuple[str, str, list[str]]]:
    """(name, blurb, [row id]) for each flight, in the order they are written.

    A TAB IS A FLIGHT. The sections are the LIBRARY -- one copy of each row --
    and this is the running order over them, which is what the cockpit renders.

    The card grew by THEME, which is the right axis for writing tests and the
    wrong one for flying them: a pilot does not fly section H, he flies from
    the ramp to the parking spot and passes through six sections on the way.

        "Maybe each tab should be a flight with things we should test top to
         bottom."

    `a..b` is an inclusive run over that section's LIVE rows IN CARD ORDER --
    not arithmetic on the number, because the numbers are not contiguous and
    never have been: section H runs H18, H19, H11, H13, H10, H9, H4... in the
    order somebody found the faults. Expanding `H4..H28` by counting would
    invent rows that do not exist and skip ones that do.
    """
    card = _read("TEST_PLAN.md")
    m = re.search(r"^## Flights$(.*?)(?=\n## )", card, re.M | re.S)
    if not m:
        return []
    live = {}
    for letter, _title, rows in sections():
        live[letter] = [r["id"] for r in rows if r["id"]]
    out = []
    for fm in _FLIGHT.finditer(m.group(1)):
        name = fm.group(1).strip()
        body = fm.group(2)
        blurb = " ".join(x.lstrip("> ").strip()
                         for x in body.splitlines() if x.startswith(">"))
        ids: list[str] = []
        for tok in " ".join(x for x in body.splitlines()
                            if x.startswith("    ")).split():
            if ".." in tok:
                lo, hi = tok.split("..", 1)
                sect = re.match(r"[A-Z]+", lo)
                pool = live.get(sect.group(0), []) if sect else []
                if lo in pool and hi in pool:
                    ids += pool[pool.index(lo):pool.index(hi) + 1]
                else:
                    # LOUD, NOT SILENT. A range naming a row that does not
                    # exist would otherwise render as a shorter flight, and a
                    # missing row looks exactly like one the pilot has not
                    # scrolled to -- he flies the sortie never knowing it was
                    # meant to be there. Same failure as a section with no GUID.
                    print(f"!! flight {name!r}: range {tok} names a row that "
                          f"is not live in the card", flush=True)
            else:
                ids.append(tok)
        out.append((name, blurb, ids))
    return out


def issues() -> list[dict]:
    """Every issue, with its number and status, in the order it is written."""
    text = _read("ISSUES.md")
    out = []
    marks = list(_ISSUE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        sm = re.search(r"^\*\*Status:\*\*\s*([A-Z/]+)", body, re.M)
        out.append({"slug": m.group(1), "title": m.group(2),
                    "number": m.group(3) or "", "status": sm.group(1) if sm else ""})
    return out


CSS = """
  .ft { font: 15px/1.35 "Courier New", monospace; color: #1d1a14;
        background: #e8dfc4; padding: 14px 16px; }
  .ft h1 { font-size: 20px; margin: 0 0 2px; letter-spacing: 1.5px; }
  .ft .sub { font-size: 13px; color: #5a5142; margin-bottom: 10px; }
  .ft .row { border-top: 1px solid #b9ad8c; padding: 7px 0; }
  .ft .hd { display: flex; align-items: baseline; gap: 8px; }
  .ft .id { font-size: 19px; font-weight: bold; min-width: 58px; }
  .ft .iss { background: #1b3fa0; color: #fff; padding: 1px 6px;
             border-radius: 3px; font-weight: bold; font-size: 14px; }
  .ft .p1 { background: #b03024; color: #fff; padding: 1px 5px;
            border-radius: 3px; font-size: 11px; }
  .ft .p2, .ft .p3 { color: #5a5142; font-size: 11px; }
  .ft .what { margin: 2px 0 0 66px; }
  .ft .exp { margin: 2px 0 0 66px; color: #2f4a24; }
  .ft .exp:before { content: "→ "; }
  .ft .why { margin: 4px 0 0 66px; font-size: 13px; color: #4a4335;
             border-left: 2px solid #b9ad8c; padding-left: 8px; }
  .ft .why + .why { margin-top: 5px; }
  .ft code { background: #ded3b2; padding: 0 3px; }
  .ft .warn { background: #f2e3c4; border-left: 4px solid #b03024;
              padding: 6px 9px; margin: 8px 0; }
  .ft table { border-collapse: collapse; width: 100%; font-size: 14px; }
  .ft td { border-top: 1px solid #b9ad8c; padding: 4px 3px; vertical-align: top; }
  .ft .st { font-size: 11px; color: #5a5142; }
"""


def _issue_only(cell: str) -> str:
    """Just the issue reference. The card also names the function under test,
    which is the right thing in a diff and noise in a cockpit -- a pilot reports
    "issue eleven", never "flying_the_missed"."""
    m = re.search(r"\[#\d+\]", cell)
    if m:
        return _md(m.group(0))
    return _md(re.sub(r"`[^`]*`", "", cell).strip(" —·-"))


def _why_html(text: str) -> str:
    """The explanation, one block per paragraph. Blank lines are how the card
    separates 'what the bug is' from 'what to tell me about it', and running
    them together is how a cockpit page becomes a wall."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join(f'<div class="why">{_md(p)}</div>' for p in paras)


def _rows_html(rows: list[dict]) -> str:
    out = []
    for r in rows:
        prio = ""
        if "P1" in r["prio"]:
            prio = '<span class="p1">P1 first flight</span>'
        elif r["prio"]:
            prio = f'<span class="p2">{_md(r["prio"])}</span>'
        if r["id"]:
            out.append(
                f'<div class="row"><div class="hd"><span class="id">{r["id"]}'
                f'</span>{_issue_only(r["issue"])} {prio}</div>'
                f'<div class="what">{_md(r["what"])}</div>'
                f'<div class="exp">{_md(r["expect"])}</div>'
                + (_why_html(r["why"]) if r.get("why") else "")
                + '</div>')
        else:
            out.append(
                f'<div class="row"><div class="what" style="margin-left:0">'
                f'{_md(r["what"])}</div>'
                f'<div class="exp" style="margin-left:0">{_md(r["expect"])}'
                f'</div></div>')
    return "".join(out)


def build_flight(name: str) -> str:
    """One flight, top to bottom, with each row's own section shown beside it.

    The section letter stays VISIBLE because it is half the identifier a pilot
    says on the radio and because it tells him which part of the system a
    failure belongs to. What it no longer does is decide which page he is on.
    """
    want = None
    for nm, blurb, ids in flights():
        if nm == name:
            want = (blurb, ids)
    if want is None:
        return (f"<title>{name}</title><style>{CSS}</style>"
                f'<div class="ft"><h1>{_md(name)}</h1><p>no such flight</p></div>')
    blurb, ids = want
    known = {}
    for _letter, _title, rows in sections():
        for r in rows:
            if r["id"]:
                known[r["id"]] = r
    rows, missing = [], []
    for rid in ids:
        if rid in known:
            rows.append(known[rid])
        else:
            missing.append(rid)
    if missing:
        # A ROW NAMED IN A FLIGHT AND ABSENT FROM THE LIBRARY. Said out loud
        # for the same reason a section with no GUID was: a page that silently
        # renders one row short reads exactly like a page a pilot has not
        # finished scrolling.
        print(f"!! flight {name!r} names rows that do not exist: "
              f"{', '.join(missing)}", flush=True)
    warn = ""
    if name.startswith("PARKED"):
        warn = ('<div class="warn"><b>Do not fly these.</b> They exercise work '
                'that is being removed. Kept so it does not vanish silently.'
                '</div>')
    return (f"<title>{name}</title><style>{CSS}</style>"
            f'<div class="ft"><h1>{_md(name)}</h1>'
            f'<div class="sub">{_md(blurb) if blurb else ""}</div>'
            f'<div class="sub">{len(rows)} rows &middot; in the order you meet '
            f'them &middot; say the ID and the issue number on the radio</div>'
            f'{warn}{_rows_html(rows)}</div>')


def build_issues() -> str:
    """What is still open, and therefore worth a radio call.

    VALIDATED drops off the list on purpose. Leaving a signed-off issue on a
    cockpit page invites a pilot to spend a sortie re-testing something already
    finished, which is the same waste as section E existing at all.
    """
    all_ = issues()
    live = [i for i in all_ if i["status"] not in ("TODO", "VALIDATED")]
    rows = "".join(
        f'<tr><td><span class="iss">#{i["number"] or "--"}</span></td>'
        f'<td>{_md(i["title"])}<div class="st">{i["slug"]} &middot; '
        f'{i["status"] or "-"}</div></td></tr>'
        for i in live)
    todo = sum(1 for i in all_ if i["status"] == "TODO")
    done = sum(1 for i in all_ if i["status"] == "VALIDATED")
    return (f"<title>ISSUES</title><style>{CSS}</style>"
            f'<div class="ft"><h1>OPEN ISSUES</h1>'
            f'<div class="sub">what a failure gets reported against &middot; '
            f'{len(live)} live &middot; {done} signed off &middot; '
            f'{todo} not yet built</div>'
            f"<table>{rows}</table></div>")


def pages() -> list[tuple[str, str, str, object]]:
    """Tabs for the flight-test kneeboard, in the order they are flown."""
    from marshall.kneeboard import plans as fp

    # The board a pilot is asking FROM, first, because section G asks him to
    # request a plan by name and he cannot do that from memory. Temporary: it
    # comes off when a pilot is handed the plan he is flying instead of
    # shopping from a list.
    out = [(GUIDS["PLANS"], "PLANS", "ft-plans", fp.build),
           (GUIDS["ISSUES"], "ISSUES", "ft-issues", build_issues)]
    # A to F, whatever order the card happens to be written in -- a pilot flies
    # them in order and the tabs should match the card, not the file.
    # IN THE ORDER HE FLIES THEM, which is the order the card is written in --
    # ramp, clearance, approach, then the known-broken reference. Sorting them
    # alphabetically put the approach before the clearance that precedes it.
    # ONE TAB PER FLIGHT, not one per section. A pilot does not fly section H;
    # he flies from the ramp to the parking spot and passes through six
    # sections on the way, and the tab strip used to make him find them.
    #
    # THE SECTION TABS ARE GONE AND THEIR GUIDS ARE NOT REUSED -- the same rule
    # section E retired under. OpenKneeboard remembers which page a pilot was
    # on, and handing an old identifier to a new document drops him somewhere
    # he did not choose. `guid_for` is namespaced on "flight:" so a flight can
    # never collide with the letter of a section that once existed.
    for name, _blurb, _ids in flights():
        out.append((guid_for(f"flight:{name}"), _tab_label(name),
                    "ft-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                    (lambda n: (lambda: build_flight(n)))(name)))
    return out


def _tab_label(name: str) -> str:
    """The strip is narrow and the pilot reads it at a glance.

    "FLIGHT 2 -- the VFR arrival" becomes "2 VFR". Hand-shortened where the
    card gives a name worth keeping, derived otherwise, because a tab with no
    label is a page nobody opens.
    """
    short = {"FLIGHT 1": "1 RECOVERY", "FLIGHT 2": "2 VFR",
             "FLIGHT 3": "3 TWO-SHIP", "FLIGHT 4": "4 NEVADA",
             "FLIGHT 5": "5 KOB ILS", "EARS ONLY": "EARS",
             "PARKED": "PARKED"}
    head = name.split("—")[0].strip()
    if head in short:
        return short[head]
    print(f"!! flight {name!r} has no tab label; add one to `_tab_label`",
          flush=True)
    return head[:12] or "?"


if __name__ == "__main__":
    from marshall.kneeboard import site
    print(site.build(pages())[:400])
