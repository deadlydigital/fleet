"""The numbered requirements in a spec, for the one person who reads it.

WHY THIS EXISTS
---------------
specs/auto-approval.md §9.9. Task 53 shipped §2.5 of its own spec unbuilt --
the order table's cells were to set the filters and the diff does not touch row
rendering at all -- and all four contract checks passed, because none of them
reads the spec. `auto_merge: false` is the only reader in the path.

That reader is a person with a 250-line spec on one side and a 300-line diff on
the other, and they missed one item out of seven. This does not check anything.
It turns the prose into a list so that walking it is systematic rather than
attentive.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not tick anything, guess anything, or match requirements to hunks.
§9.12 measured the cheap version of that: grepping the diff for the requirement
number, on task 53's real diff, scored 1 for §2.1 and §2.5 (both stray digits)
and 0 for §2.2 and §2.3, which were implemented. It would have refused working
changes and passed the missing one, and been believed. A list that makes no
claim is worth more than a matcher that makes a wrong one.

Nothing is recorded either. A tick here is a scroll position, not a state, and
`decision_log.reason` is where a reviewer says what they checked.

WHAT COUNTS AS A REQUIREMENT
----------------------------
Two shapes, both taken from specs that exist rather than invented:

    ### 2. The page sends them                    a numbered section heading
    **2.5 The table cells set the filters.**      a numbered bold lead

Nothing else. Prose that reads like an instruction is not promoted to a
requirement: a checklist that includes things the spec did not number is a
checklist a reviewer learns to distrust, and the first item they dismiss is the
one that mattered.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: `### 2. The page sends them` -- two to four hashes, an integer id (possibly
#: dotted), a full stop, then the title.
_HEADING = re.compile(r"^\s{0,3}#{2,4}\s+(\d+(?:\.\d+)*)\.\s+(\S.*?)\s*$")

#: `**2.5 The table cells set the filters.** Exact matching is only ...`
#: The id must be dotted here. A bold `**1. Something**` at the start of a line
#: is how ordinary emphasis often begins a paragraph, and promoting those would
#: fill the list with things the author never numbered.
_BOLD_LEAD = re.compile(r"^\s{0,3}\*\*(\d+\.\d+(?:\.\d+)*)\s+(\S.*?)\*\*")

#: Inside a fenced block the same shapes are examples, not requirements.
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")

#: Long enough to be a sentence, short enough to sit in a column.
_MAX_TITLE = 110


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    line: int

    @property
    def depth(self) -> int:
        """0 for `2`, 1 for `2.5`. The list indents by this and nothing else."""
        return self.id.count(".")


def _clean(title: str) -> str:
    """Markdown emphasis and code ticks out; the sentence itself left alone.

    UNDERSCORES STAY. Stripping them as emphasis turned `has_discount` into
    `hasdiscount` and `refund_total` into `refundtotal` -- mangling the exact
    identifiers a reviewer is about to look for in the diff, which is the one
    job this list has. Markdown _emphasis_ is rare in these specs and legible
    when it survives; a broken identifier is not.
    """
    t = re.sub(r"[`*]", "", title).strip()
    t = re.sub(r"\s+", " ", t)
    if len(t) > _MAX_TITLE:
        t = t[:_MAX_TITLE - 1].rstrip() + "…"
    return t


def parse(spec_md: str | None) -> list[Requirement]:
    """Every numbered requirement, in the order the spec states them.

    Deduplicated on the id, first occurrence winning: a spec that refers back
    to `2.5` in a later section is citing it, not restating it, and a list with
    the same item twice reads as two things to check.
    """
    out: list[Requirement] = []
    seen: set[str] = set()
    fenced = False
    for n, raw in enumerate((spec_md or "").splitlines(), start=1):
        if _FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _HEADING.match(raw) or _BOLD_LEAD.match(raw)
        if not m:
            continue
        rid, title = m.group(1), _clean(m.group(2))
        if not title or rid in seen:
            continue
        seen.add(rid)
        out.append(Requirement(id=rid, title=title, line=n))
    return out
