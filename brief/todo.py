"""Reading `docs/TODO.md`, which is the real issue tracker and is prose.

WHY PARSE IT AT ALL
--------------------
It is where `CI-002`, `TEST-003`, `DATA-002` and `BUG-020` actually live, with
dates and statuses. Ignoring it loses the largest record of known problems in
either repo. `fleet.issues` holds one row; this file holds dozens.

WHY THE PARSER REPORTS ITS OWN FAILURES
----------------------------------------
It is hand-written markdown that grew over months, and it does not have one
shape. Measured 7 Sep 2026: 58 `##` headers, of which 41 match the
`CODE-NNN — title (date)` form the rest of the file implies; and ten distinct
`**Status:**` spellings, of which four are prose the pattern happened to catch
("**Status:** A wrong baseline is worse than...").

So the parser recognises a narrow, declared shape and **counts everything it
could not classify as uncounted, reporting the count and examples**. It never
infers a status from position, from nearby words, or from a heading it did not
recognise. A tracker summary that quietly drops the entries it found confusing
is worse than no summary: the entries it drops are the badly-written ones, and
those are disproportionately the ones nobody has looked at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

#: The only statuses this parser will assign. Anything else is UNRECOGNISED and
#: is reported as such — the vocabulary is not widened to make the number look
#: tidier.
KNOWN_STATUSES = {"OPEN", "DONE", "FIXED", "IMPLEMENTED", "RESOLVED", "PARKED"}

#: `## CODE-123 — title (date)`. An em-dash or a hyphen; both appear.
_ENTRY = re.compile(r"^##\s+([A-Z]{2,10}-\d{1,4})\b\s*[—-]?\s*(.*)$")
_STATUS = re.compile(r"^\*\*Status:\*\*\s*([A-Za-z_]+)")


@dataclass
class TodoReading:
    path: str
    as_of: Optional[datetime] = None
    entries: int = 0
    open_entries: int = 0
    by_status: dict = field(default_factory=dict)

    #: Headers that look like sections rather than entries, and entries whose
    #: status this parser will not guess at. Both are REPORTED, never dropped.
    unrecognised_headers: List[str] = field(default_factory=list)
    unrecognised_statuses: List[str] = field(default_factory=list)
    entries_without_status: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def uncounted(self) -> int:
        return len(self.unrecognised_statuses) + len(self.entries_without_status)


def read_todo(path: str) -> TodoReading:
    """Parse what is parseable and enumerate what is not. Never raises."""
    p = Path(path)
    r = TodoReading(path=path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        # as_of is the file's mtime — the instant the CONTENT describes, not the
        # instant it was read.
        r.as_of = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except Exception as exc:
        r.error = f"{type(exc).__name__}: {exc}"
        return r

    current: Optional[str] = None
    seen_status_for: set = set()

    for line in text.splitlines():
        if line.startswith("## "):
            m = _ENTRY.match(line)
            if m:
                current = m.group(1)
                r.entries += 1
            else:
                current = None
                # A section heading, or an entry in a shape this parser does not
                # know. It does not try to tell the two apart.
                r.unrecognised_headers.append(line[3:].strip()[:70])
            continue

        if current and current not in seen_status_for:
            sm = _STATUS.match(line)
            if sm:
                raw = sm.group(1).upper()
                seen_status_for.add(current)
                if raw in KNOWN_STATUSES:
                    r.by_status[raw] = r.by_status.get(raw, 0) + 1
                    if raw == "OPEN":
                        r.open_entries += 1
                else:
                    # Almost always prose the pattern caught, e.g.
                    # "**Status:** A wrong baseline is worse than a red test".
                    # Recorded verbatim rather than mapped to something plausible.
                    r.unrecognised_statuses.append(f"{current}: {raw}")

    r.entries_without_status = sorted(
        set() if r.entries == 0 else
        {e for e in _all_codes(text)} - seen_status_for)
    return r


def _all_codes(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        m = _ENTRY.match(line)
        if m:
            out.append(m.group(1))
    return out
