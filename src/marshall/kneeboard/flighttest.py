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

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs"

# Stable GUIDs -- OpenKneeboard remembers the page a pilot was on, so these must
# not change between builds or he loses his place mid-sortie.
GUIDS = {
    "ISSUES": "{1a7c9e30-5b42-4f81-9d63-0e5a24c71b90}",
    "A": "{2b8d0f41-6c53-4092-ae74-1f6b35d82ca1}",
    "B": "{3c9e1052-7d64-41a3-bf85-2a7c46e93db2}",
    "C": "{4daf2163-8e75-42b4-c096-3b8d57fa4ec3}",
    "D": "{5eb03274-9f86-43c5-d1a7-4c9e68ab5fd4}",
    "E": "{6fc14385-a097-44d6-e2b8-5daf79bc60e5}",
    "F": "{70d25496-b1a8-45e7-f3c9-6eb08acd71f6}",
    "G": "{81e365a7-c2b9-46f8-a4da-7fc19bde82a7}",
}

# Tab labels. OpenKneeboard's tab strip is narrow and the pilot is reading it
# at a glance, so these are hand-short rather than a truncated heading.
SHORT = {"A": "PREFLT", "B": "APPROACH", "C": "NEW", "D": "RADIO",
         "E": "KNOWN", "F": "2-SHIP", "G": "CLNC"}

_SECTION = re.compile(r"^## ([A-Z]) — (.+)$", re.M)
_ROW = re.compile(r"^\|\s*([A-Z]\d+[a-z]?)\s*\|(.+)$")
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
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(card)
        rows = []
        for line in card[m.end():end].splitlines():
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
            rows.append({"id": ident, "prio": prio, "what": what,
                         "expect": expect, "issue": issue,
                         "why": notes.get(ident, "")})
        out.append((m.group(1), m.group(2), rows))
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


def build_section(letter: str) -> str:
    for ltr, title, rows in sections():
        if ltr != letter:
            continue
        warn = ""
        if letter == "E":
            warn = ('<div class="warn"><b>Known broken — do not report these as '
                    'new.</b> A reversal that is <b>not</b> listed here is the '
                    'interesting one.</div>')
        return (f"<title>{letter}</title><style>{CSS}</style>"
                f'<div class="ft"><h1>{letter} &mdash; {_md(title)}</h1>'
                f'<div class="sub">say the ID and the issue number on the radio'
                f'</div>{warn}{_rows_html(rows)}</div>')
    return f"<title>{letter}</title><style>{CSS}</style>" \
           f'<div class="ft"><h1>{letter}</h1><p>no rows</p></div>'


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
    out = [(GUIDS["ISSUES"], "ISSUES", "ft-issues", build_issues)]
    # A to F, whatever order the card happens to be written in -- a pilot flies
    # them in order and the tabs should match the card, not the file.
    for letter, _title, _rows in sorted(sections(), key=lambda s: s[0]):
        guid = GUIDS.get(letter)
        if not guid:
            # LOUD, not silent. A section with no GUID simply does not appear on
            # the kneeboard, and a page that is missing looks exactly like a page
            # the pilot has not scrolled to -- he flies the sortie without ever
            # knowing there were tests on it.
            print(f"!! flight test section {letter} has no GUID and will NOT "
                  f"appear on the kneeboard -- add one to GUIDS", flush=True)
            continue
        out.append((guid, f"{letter} {SHORT.get(letter, '')}",
                    f"ft-{letter.lower()}",
                    (lambda l: (lambda: build_section(l)))(letter)))
    return out


if __name__ == "__main__":
    from marshall.kneeboard import site
    print(site.build(pages())[:400])
