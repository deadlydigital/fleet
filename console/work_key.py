"""What work a candidate IS, in a string that survives the producer rewriting it.

specs/auto-approval.md §9.2, and 027's header carries the argument. In short:

    c14  "Coupon and discount performance report"                 batch 8
    c28  "Coupon and discount performance report, over a column
          that is already populated"                              batch 9

are one row of one findings document, re-verified eleven days apart. 022's
repeat-failure ceiling keyed on the TITLE, so each scored 0 against a stop that
fires at 2, and the counter restarted every time the producer ran. It has to
restart: specs/approval-surface.md §7 forbids the producer to deduplicate,
because "a candidate that reappears is a signal". The repetition is designed.
Only the ceiling's inability to SEE it was not.

THE IDENTITY, AND WHY IT IS NOT PROSE
-------------------------------------
A candidate is a row of somebody else's document, and it says so:
`candidates.evidence` carries the document, the sha it was read at, and the
section heading the row came from. contracts/checks/candidate_block_shape.py
requires the document and the sha on every entry, and
console/load_candidates.band_of() already reads the band out of that same
heading — this is the same field, read for a second fact.

The producer writes its own titles and rewrites them every run. It does NOT
write the document or the heading; it quotes them. That is the whole reason
this is a stable key and the title is not.

RESOLUTION, WHICH IS NOT FUZZY MATCHING
---------------------------------------
The two producers quote the heading at different lengths — batch 8 wrote
"Weekly — coupon and discount performance", batch 9 wrote the cell verbatim.
So the heading is not compared to another heading. It is RESOLVED AGAINST THE
DOCUMENT, at the sha the candidate cites, to the table row it names, and the
key is that row. One candidate, one document row, decided by the document
rather than by a similarity between two candidates:

    c14 topic  coupon-and-discount-performance
    c28 topic  coupon-and-discount-performance-usage-discount-...
    both  ->   row:coupon-and-discount-performance-usage-discount-total-...

An ambiguous heading — one that prefixes two rows — resolves to NOTHING rather
than to the longer one. Merging genuinely different work is the failure mode
that costs money quietly; failing to merge is the failure mode that costs a
ceiling one night and prints why.

WHAT IT DOES WHEN IT CANNOT
---------------------------
Returns a `topic:` key from the heading alone, or None if there is no heading
at all. 027's candidate_work_identity() falls back to 022's (title, repo) for a
NULL, so nothing here can make the ceiling weaker than the one it replaces. A
key that could not be derived is printed by the loader and by --backfill, not
swallowed: a pool where nothing keys is a ceiling that has quietly stopped
counting again, and that is exactly what went unnoticed for two batches.
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from . import config, db
# The band vocabulary lives with the column it fills, in the loader. Imported
# rather than restated for the reason load_candidates.py imports the probe
# vocabulary from the contract check: a second copy is a second answer, one
# edit later. load_candidates imports THIS module from inside its functions,
# so the dependency runs one way only.
from .load_candidates import BANDS

#: "Weekly — Coupon and discount performance: ...". The band is a separate fact
#: with its own column (025) and its own rank key, and a document that moves a
#: row from Weekly to Daily has not made it different work — so the band comes
#: OFF before the key is made. A hyphen is accepted beside the em dash for the
#: reason load_candidates._BAND_RE accepts one: the separator is the document's
#: typography and the band is the fact.
_BAND_PREFIX_RE = re.compile(r"^\s*(?:" + "|".join(BANDS) + r")\s*[—–-]\s*", re.I)

#: A markdown table row, which is how the gap document holds its rows.
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")

#: A resolved row must be a phrase, not a word. "Has" and "Missing" are cells in
#: the document's own legend table, and a one-word heading prefix-matching one
#: of those would key real work to a table of definitions.
MIN_ROW_WORDS = 2


# ---- the pure part ---------------------------------------------------------

def slug(text: str) -> str:
    """Lower-case, punctuation to hyphens. Deterministic and lossy on purpose.

    The two producers differ on capitalisation, on "incl." versus "including",
    and on whether a slash has spaces round it. None of that is a different
    row of the document.
    """
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def topic_of(section: str) -> str:
    """The heading with its band prefix removed, slugged. '' if there is none."""
    return slug(_BAND_PREFIX_RE.sub("", str(section or "").strip()))


def document_rows(text: str) -> List[str]:
    """Every table row's FIRST CELL in a markdown document, slugged.

    The gap list holds one feature per table row and names it in column one.
    Separator rows and empty cells are dropped; nothing else is judged here,
    because a filter that decides which rows are "real" is a second opinion
    about a document this code does not own.
    """
    out: List[str] = []
    for line in (text or "").splitlines():
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        first = m.group(1).split("|")[0].strip()
        if not first or set(first) <= set("-: "):
            continue
        s = slug(first)
        if s:
            out.append(s)
    return out


def resolve(topic: str, rows: Sequence[str]) -> str | None:
    """Which document row this heading names, or None.

    Exact match first and outright: a heading quoted verbatim is not a guess
    and must not be able to lose to a longer row that contains it.

    Otherwise a prefix in either direction, ON A WORD BOUNDARY, and ONLY IF
    EXACTLY ONE ROW MATCHES. Batch 8 quoted headings short ("CSV export"), and
    batch 9 quoted two rows into one heading ("CSV export of orders /
    customers / products; Export with chosen columns"), so both directions
    occur in the real pool. Two matches means the document itself does not
    distinguish them from this heading, and picking the longer would be the
    kind of quiet merge that buys the wrong work.
    """
    if not topic:
        return None
    if topic in rows:
        return topic
    hits = {r for r in rows
            if len(r.split("-")) >= MIN_ROW_WORDS
            and (r.startswith(topic + "-") or topic.startswith(r + "-"))}
    return hits.pop() if len(hits) == 1 else None


def key_for(*, candidate_repo: str, document_repo: str, document: str,
            kind: str, value: str) -> str:
    """The stored string. One shape, so an eyeball can read a key off a row."""
    return f"{candidate_repo}::{document_repo}/{document}#{kind}:{value}"


# ---- the part that reads git -----------------------------------------------

@functools.lru_cache(maxsize=1)
def _repos() -> Dict[str, Path]:
    """contracts/checks/candidate_block_shape.REPOS, imported not copied.

    The same indirection console/rank.py and console/load_candidates.py use,
    and for the same reason: the map from a repo NAME to a checkout on this
    box has one owner.
    """
    path = config.PROJECT_ROOT / "contracts" / "checks" / "candidate_block_shape.py"
    spec = importlib.util.spec_from_file_location("candidate_block_shape", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.REPOS)


@functools.lru_cache(maxsize=64)
def _document_at(repo: str, sha: str, document: str) -> tuple[str, ...] | None:
    """The document's rows AT THE SHA THE CANDIDATE CITES, or None.

    At the sha and never at HEAD. A candidate is a claim about a document as it
    was on a day, the document moves, and resolving batch 8's headings against
    today's copy would make the key depend on when it was computed. A key that
    changes under a row is not a key.
    """
    root = _repos().get(repo)
    if root is None or not sha or not document:
        return None
    try:
        r = subprocess.run(("git", "-C", str(root), "show", f"{sha}:{document}"),
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return tuple(document_rows(r.stdout))


def _citations(candidate: Dict[str, Any]) -> List[Dict[str, str]]:
    """Every evidence entry that names a document AND a section heading.

    Both key spellings are accepted. contracts/checks/candidate_block_shape.py
    requires `document` and `sha`; batch 8 was loaded by hand, before the
    loader existed, and used `path` and `read_at_sha`. Reading only the current
    spelling would key batch 9 and leave the batch it is a repeat OF unkeyed,
    which is the one thing this must not do.
    """
    out = []
    for e in candidate.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        document = e.get("document") or e.get("path")
        section = e.get("section")
        if not document or not section:
            continue
        out.append({
            "document": str(document),
            "sha": str(e.get("sha") or e.get("read_at_sha") or ""),
            "repo": str(e.get("repo") or "fleet"),
            "section": str(section),
        })
    return out


def derive(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """The key for one candidate, and everything that went into it.

    Returns {"key": str|None, "kind": ..., "why": ...}. `why` is not decoration:
    a NULL key means the ceiling falls back to matching titles for this row, and
    a pool of rows that all fell back is the defect returning unannounced.
    """
    repo = str(candidate.get("repo") or "")
    cites = _citations(candidate)
    if not cites:
        return {"key": None, "kind": None, "citations": 0,
                "why": ("no evidence entry names both a document and a section, "
                        "so there is no document row to key to")}

    derived: Dict[str, Dict[str, Any]] = {}
    for c in cites:
        topic = topic_of(c["section"])
        if not topic:
            continue
        rows = _document_at(c["repo"], c["sha"], c["document"])
        row = resolve(topic, rows) if rows else None
        kind = "row" if row else "topic"
        key = key_for(candidate_repo=repo, document_repo=c["repo"],
                      document=c["document"], kind=kind, value=row or topic)
        derived[key] = {"kind": kind, "topic": topic, "section": c["section"],
                        "document": c["document"], "sha": c["sha"],
                        "readable": rows is not None}

    if not derived:
        return {"key": None, "kind": None, "citations": len(cites),
                "why": "every cited section is empty once its band is removed"}
    if len(derived) > 1:
        # The same argument band_of() makes for two bands on one candidate:
        # picking the first is a way of not noticing that the candidate cites
        # two different pieces of work.
        return {"key": None, "kind": None, "citations": len(cites),
                "why": (f"cites {len(derived)} different document rows "
                        f"({', '.join(sorted(derived))}); one candidate is one "
                        f"row, and choosing between them here would be a guess")}

    key, meta = next(iter(derived.items()))
    why = None
    if meta["kind"] == "topic":
        why = ("the cited document could not be read at that sha"
               if not meta["readable"] else
               f"{meta['topic']!r} names no single row of {meta['document']}")
    return {"key": key, "kind": meta["kind"], "citations": len(cites),
            "topic": meta["topic"], "document": meta["document"],
            "sha": meta["sha"], "why": why}


# ---- the backfill ----------------------------------------------------------

def backfill(*, dry_run: bool = False) -> Dict[str, Any]:
    """Fill work_key on rows that predate the column. ONLY WHERE IT IS NULL.

    NARROWER THAN IT LOOKS, and deliberately: it writes one column, never
    overwrites a key that exists, touches no other column on `candidates`, and
    goes nowhere near `tasks`, `decision_log` or any artefact. The corrected
    count is DERIVED from history rather than manufactured in it — no row is
    edited to make a number come out, which is the line specs/auto-approval.md
    §5 draws round the undo and the same one applies here.

    Idempotent: run it twice and the second run writes nothing.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, repo, evidence FROM candidates"
            " WHERE work_key IS NULL ORDER BY id").fetchall()

    plan = []
    for r in rows:
        d = derive(dict(r))
        plan.append({"candidate_id": r["id"], "title": r["title"], **d})

    writable = [p for p in plan if p["key"]]
    if not dry_run and writable:
        with db.writer() as conn, conn.transaction():
            for p in writable:
                conn.execute(
                    "UPDATE candidates SET work_key=%s"
                    " WHERE id=%s AND work_key IS NULL",
                    (p["key"], p["candidate_id"]))

    return {
        "considered": len(plan),
        "written": 0 if dry_run else len(writable),
        "would_write": len(writable) if dry_run else None,
        "resolved_to_a_document_row": sum(1 for p in plan if p["kind"] == "row"),
        "keyed_by_heading_only": sum(1 for p in plan if p["kind"] == "topic"),
        "unkeyed": [{"candidate_id": p["candidate_id"], "why": p["why"]}
                    for p in plan if not p["key"]],
        "plan": plan,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Derive candidates.work_key from the evidence citations.")
    ap.add_argument("--backfill", action="store_true",
                    help="write work_key on rows where it is NULL")
    ap.add_argument("--dry-run", action="store_true",
                    help="derive and print, write nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    out = backfill(dry_run=args.dry_run or not args.backfill)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    for p in out["plan"]:
        mark = {"row": "  ", "topic": "~ ", None: "x "}[p["kind"]]
        print(f"{mark}c{p['candidate_id']:<3} {p['title'][:46]:46} "
              f"{p['key'] or 'NO KEY'}")
        if p.get("why"):
            print(f"       {p['why']}")
    print()
    print(f"{out['considered']} unkeyed candidate(s): "
          f"{out['resolved_to_a_document_row']} resolved to a document row, "
          f"{out['keyed_by_heading_only']} keyed by heading only, "
          f"{len(out['unkeyed'])} not keyed at all")
    if out["written"]:
        print(f"WROTE work_key on {out['written']} row(s)")
    else:
        print("wrote nothing" + (" (--backfill not given)"
                                 if not args.backfill else " (dry run)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
