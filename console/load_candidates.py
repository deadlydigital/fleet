"""Turning a producer's ```fleet-candidates block into rows, without a person.

WHY THIS EXISTS, IN ONE ROW OF THE DATABASE
--------------------------------------------
`candidate_batches.note` on batch 9:

    "Loaded by hand: there is no loader, and batch 8 was loaded the same way."

The producer emits a validated block. contracts/checks/candidate_block_shape.py
requires `hib_signal` on every candidate, requires at least one `probes:`
predicate, and RE-EXECUTES every one of them against the tree before the task
may pass. Then a person read the markdown and retyped a subset of it into an
INSERT -- and the band, the signal and the probes had nowhere to go, so they
were dropped. Two batches, thirty-two probes and four signals, lost between a
check that verified them and a table that had no column for them.

025 made the columns. This makes the retyping unnecessary.

WHAT THIS VALIDATES, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------------
It checks the SHAPE: the required keys, the forbidden ones, the probe
vocabulary, the hib_signal pair, the band prefix. Every one of those is a
statement about the block itself and is as true tonight as it was when the
producer wrote it.

IT DOES NOT RE-EXECUTE THE PROBES, and that is not an oversight. A block is
loaded from a document that was verified at some sha, and the tree has moved
since -- batch 9 was verified at platform 4619a76 and HEAD is past it. A loader
that refused a batch whose claims had aged would refuse to record the finding
that the claims HAD aged, which is exactly the fact worth keeping. Re-execution
belongs at the approval, against the sha about to be spent money on:
specs/auto-approval.md §2.2 gate 5, in console/rank.py.

So: this writes rows. It does not judge them, it cannot approve them, and 013's
trigger means it could not pre-approve one if it tried.

NO SECOND PARSER
----------------
BLOCK_RE, REQUIRED, FORBIDDEN and PROBE_KINDS are imported from the contract
check rather than restated. A loader with its own copy of the vocabulary is a
loader that accepts what the check refuses, one edit later.
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

from . import config, db


@functools.lru_cache(maxsize=1)
def _shape_check():
    """The contract check, imported as a module rather than copied.

    It lives under contracts/checks/ and is not a package, so it is loaded by
    path. The alternative is restating its constants here, which is the drift
    this indirection exists to avoid.
    """
    path = config.PROJECT_ROOT / "contracts" / "checks" / "candidate_block_shape.py"
    spec = importlib.util.spec_from_file_location("candidate_block_shape", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LoadRefused(Exception):
    """Nothing was written. The message names every problem, not the first."""


#: The band vocabulary, matching 025's CHECK constraint. Lower-cased here
#: because the column stores one spelling of one fact and the document uses
#: title case in a heading.
BANDS = ("daily", "weekly", "monthly", "rarely")

#: The gap document's headings are "<Band> — <what>", with an em dash. A hyphen
#: is accepted too: the separator is the document's typography and the band is
#: the fact, and a heading retyped with a hyphen should not silently produce an
#: unranked row.
_BAND_RE = re.compile(r"^\s*(" + "|".join(BANDS) + r")\s*[—–-]", re.I)


def band_of(cand: Dict[str, Any]) -> str | None:
    """The frequency word from the evidence section heading, or None.

    None means THE SECTION NAMED NO BAND. An unrecognised word is not None --
    it raises -- because the two are different facts and only one of them is a
    document the producer is allowed to write. specs/auto-approval.md §7.4 is
    the open question of whether the shape check should require the prefix; it
    does not today, so a legal block may carry no band at all and that row must
    still load.

    Where a candidate cites several sections, they must agree. Two bands on one
    candidate is the document disagreeing with itself, and picking the first is
    a way of not noticing.
    """
    seen: set[str] = set()
    unrecognised: List[str] = []
    for e in cand.get("evidence") or []:
        section = str((e or {}).get("section") or "").strip()
        if not section:
            continue
        m = _BAND_RE.match(section)
        if m:
            seen.add(m.group(1).lower())
        elif "—" in section or "–" in section:
            # Shaped like a banded heading, and the word is not one of ours.
            unrecognised.append(section.split("—")[0].split("–")[0].strip())
    if unrecognised:
        raise LoadRefused(
            f"evidence section begins {unrecognised[0]!r}, which is not one of "
            f"{BANDS}. The band is derived from the heading and stored, so an "
            f"unrecognised word is the convention changing -- which is worth an "
            f"error at the load rather than a row that ranks wrongly every "
            f"night afterwards.")
    if len(seen) > 1:
        raise LoadRefused(
            f"evidence sections name more than one band ({sorted(seen)}). A "
            f"candidate has one frequency; picking the first would be a way of "
            f"not noticing that the document disagrees with itself.")
    return seen.pop() if seen else None


def parse_block(document: Path) -> Dict[str, Any]:
    """The one ```fleet-candidates block in a document, as data."""
    mod = _shape_check()
    text = document.read_text()
    blocks = mod.BLOCK_RE.findall(text)
    if len(blocks) != 1:
        raise LoadRefused(
            f"{document} carries {len(blocks)} ```fleet-candidates blocks; "
            f"exactly one is required, which is what the producer's own check "
            f"enforces on the way in")
    try:
        block = yaml.safe_load(blocks[0])
    except yaml.YAMLError as exc:
        raise LoadRefused(f"the fleet-candidates block is not valid YAML: {exc}")
    if not isinstance(block, dict):
        raise LoadRefused("the fleet-candidates block is not a mapping")
    return block


def validate(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every problem in the block, or the candidates ready to write.

    Reports all of them rather than the first: a load run by hand at midnight
    that fails nine times in a row, once per fix, is the reason the person
    stops running it.
    """
    mod = _shape_check()
    problems: List[str] = []

    source = block.get("source") or {}
    if not source.get("document") or not source.get("sha"):
        problems.append("the block's source must name the findings document "
                        "and the sha it was read at")

    candidates = block.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LoadRefused(
            "the block declares no candidates. A producer that ran and found "
            "nothing is a batch with zero rows, which is a different thing "
            "from a block with no list -- and this loader will not invent "
            "either one.")

    out: List[Dict[str, Any]] = []
    for n, c in enumerate(candidates, start=1):
        where = f"candidate {n} ({str(c.get('title') or 'untitled')[:40]})"
        if not isinstance(c, dict):
            problems.append(f"{where} is not a mapping")
            continue

        for field in mod.REQUIRED:
            if field not in c:
                problems.append(f"{where} is missing the required field {field!r}")
        for field in mod.FORBIDDEN:
            if field in c:
                problems.append(
                    f"{where} sets {field!r}; a producer that could set a "
                    f"disposition or name a task is the autonomy the surface "
                    f"refuses, and 013's trigger would refuse the INSERT anyway")

        if "hib_signal" not in c:
            problems.append(
                f"{where} omits hib_signal. The KEY is required and the value "
                f"may be null: 'the document declares none' is a fact, and it "
                f"is not the same fact as a signal that went missing at load "
                f"-- which is the defect this loader exists to end.")
        sig = c.get("hib_signal")
        if sig is not None:
            if not isinstance(sig, dict) or not sig.get("value") or not sig.get("as_of"):
                problems.append(
                    f"{where} has an hib_signal without both value and as_of. "
                    f"The age of the figure is what decides whether it can be "
                    f"leaned on.")

        probes = c.get("probes")
        if not isinstance(probes, list) or not probes:
            problems.append(
                f"{where} declares no probes. Zero probes passing is a check "
                f"that cannot fail, and rank.py treats such a row as "
                f"ineligible -- so loading one silently would create a "
                f"candidate that can never be approved unattended and never "
                f"says why.")
        else:
            for probe in probes:
                if not isinstance(probe, dict) or len(probe) != 1:
                    problems.append(
                        f"{where} has a probe that is not one key from the "
                        f"vocabulary: {probe!r}")
                elif next(iter(probe)) not in mod.PROBE_KINDS:
                    problems.append(
                        f"{where} has a probe {next(iter(probe))!r}, which is "
                        f"not in the vocabulary ({', '.join(mod.PROBE_KINDS)})")

        try:
            band = band_of(c)
        except LoadRefused as exc:
            problems.append(f"{where}: {exc}")
            band = None

        # THE SECOND FACT READ OFF THE SAME HEADING. band_of() takes the
        # frequency word; work_key.derive() resolves the rest of it to the row
        # of the findings document this candidate IS, which is what lets the
        # repeat-failure ceiling see a repeat the producer is forbidden to
        # deduplicate. Derived here, at the load, for the reason the band is:
        # once, in the code that is allowed to refuse the row, rather than
        # every night in a ranker that cannot.
        #
        # A candidate that cannot be keyed is NOT refused. The key is a safety
        # ceiling's input, not a producer contract, and 027 falls back to
        # (title, repo) for a NULL -- so an unkeyable row loads and counts the
        # way it did before this existed. It is reported instead.
        from . import work_key as _work_key
        keyed = _work_key.derive({"repo": c.get("repo"),
                                  "evidence": c.get("evidence") or []})

        out.append({
            "title": str(c.get("title") or "").strip(),
            "rationale": str(c.get("rationale") or "").strip(),
            "repo": c.get("repo"),
            "objective_ref": c.get("objective_ref"),
            "evidence": c.get("evidence") or [],
            "suggested_paths": [str(p) for p in (c.get("suggested_paths") or [])],
            "band": band,
            "hib_signal": sig,
            "probes": probes if isinstance(probes, list) else [],
            "work_key": keyed["key"],
            "work_key_kind": keyed["kind"],
            "work_key_why": keyed.get("why"),
        })

    if problems:
        raise LoadRefused(
            f"{len(problems)} problem(s) in the block; nothing was written:\n"
            + "\n".join(f"  - {p}" for p in problems))
    return out


def load(document: Path, *, source_sha: str, note: str | None = None,
         dry_run: bool = False) -> Dict[str, Any]:
    """One batch and its rows, in one transaction.

    The transaction is the same argument approve.py makes: a batch row with
    half its candidates is a state nobody tracks and nobody would notice,
    because the surface would render it as a complete batch.
    """
    block = parse_block(document)
    rows = validate(block)

    # Recorded relative to the project root where it lives there, because that
    # is how batches 8 and 9 recorded it and a batch is found again by that
    # string. A document outside the tree is stored as given rather than
    # refused: choosing to load one is a decision, and it is not this
    # function's to second-guess.
    try:
        rel = str(document.resolve().relative_to(config.PROJECT_ROOT))
    except ValueError:
        rel = str(document)
    summary = {
        "document": rel, "source_sha": source_sha,
        "candidates": len(rows),
        "probes": sum(len(r["probes"]) for r in rows),
        "signals": sum(1 for r in rows if r["hib_signal"]),
        "bands": {b: sum(1 for r in rows if r["band"] == b)
                  for b in BANDS + (None,) if any(r["band"] == b for r in rows)},
        # PRINTED, NOT SWALLOWED. A batch where nothing keyed is a batch the
        # repeat-failure ceiling will count by title again, which is the
        # failure 027 exists to end and which went unnoticed for two batches
        # precisely because nothing said so at the load.
        "work_keys": {
            "row": sum(1 for r in rows if r["work_key_kind"] == "row"),
            "topic": sum(1 for r in rows if r["work_key_kind"] == "topic"),
            "none": sum(1 for r in rows if not r["work_key"]),
        },
        "unkeyed": [{"title": r["title"], "why": r["work_key_why"]}
                    for r in rows if not r["work_key"]],
    }
    if dry_run:
        summary["batch_id"] = None
        summary["candidate_ids"] = []
        return summary

    with db.writer() as conn:
        conn.execute(
            "INSERT INTO candidate_batches (source_document, source_sha,"
            " source_repo, note) VALUES (%s,%s,'fleet',%s)",
            (rel, source_sha, note))
        batch_id = conn.execute(
            "SELECT currval('candidate_batches_id_seq') AS id").fetchone()["id"]
        ids = []
        for r in rows:
            conn.execute(
                "INSERT INTO candidates (batch_id, title, rationale, repo,"
                " objective_ref, evidence, suggested_paths, band, hib_signal,"
                " probes, work_key) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (batch_id, r["title"], r["rationale"], r["repo"],
                 r["objective_ref"], json.dumps(r["evidence"]),
                 r["suggested_paths"], r["band"],
                 json.dumps(r["hib_signal"]) if r["hib_signal"] else None,
                 json.dumps(r["probes"]), r["work_key"]))
            ids.append(conn.execute(
                "SELECT currval('candidates_id_seq') AS id").fetchone()["id"])
    summary["batch_id"] = batch_id
    summary["candidate_ids"] = ids
    return summary


def backfill(document: Path, batch_id: int, *, dry_run: bool = False) -> Dict[str, Any]:
    """Fill 025's three columns on rows that were loaded before they existed.

    A ONE-TIME REPAIR, AND NARROWER THAN IT LOOKS. It writes band, hib_signal
    and probes and NOTHING else: not the title, not the rationale, not the
    paths, not the disposition. Those were loaded by hand and are the record of
    what a person decided to write down; this only fills what had nowhere to go.

    THIS IS NOT A RECONCILE, and contracts/candidate-producer.yaml is emphatic
    that a batch is re-run rather than reconciled -- "a candidate that reappears
    is signal, and quietly refreshing it erases that". That rule is about
    CONTENT: a claim that has changed must arrive as a new batch so the
    repetition is visible. These three fields never arrived at all. Filling
    them completes a load that was interrupted by a missing column; it does not
    refresh a candidate.

    It refuses unless every title in the block matches exactly one row in the
    batch and every row is matched, because a partial match means the document
    is not the one this batch came from -- and it refuses to overwrite a value
    that is already there.
    """
    block = parse_block(document)
    rows = validate(block)

    with db.connect() as conn:
        existing = conn.execute(
            "SELECT id, title, band, hib_signal, probes FROM candidates"
            " WHERE batch_id=%s ORDER BY id", (batch_id,)).fetchall()
    if not existing:
        raise LoadRefused(f"batch {batch_id} has no candidates")

    by_title: Dict[str, list] = {}
    for e in existing:
        by_title.setdefault(e["title"], []).append(e)

    problems: List[str] = []
    plan = []
    for r in rows:
        matches = by_title.get(r["title"], [])
        if len(matches) != 1:
            problems.append(
                f"{len(matches)} row(s) in batch {batch_id} match the title "
                f"{r['title'][:60]!r}")
            continue
        row = matches[0]
        occupied = [f for f in ("band", "hib_signal")
                    if row[f] is not None] + (["probes"] if row["probes"] else [])
        if occupied:
            problems.append(
                f"candidate {row['id']} already carries {occupied}; this "
                f"repair fills empty columns and does not overwrite a value")
            continue
        plan.append((row["id"], r))

    unmatched = [e["id"] for e in existing
                 if e["title"] not in {r["title"] for r in rows}]
    if unmatched:
        problems.append(
            f"candidate(s) {unmatched} in batch {batch_id} are not in this "
            f"document; a partial match means this is not the document the "
            f"batch was loaded from")

    if problems:
        raise LoadRefused(
            f"{len(problems)} problem(s); nothing was written:\n"
            + "\n".join(f"  - {p}" for p in problems))

    if not dry_run:
        with db.writer() as conn:
            for cid, r in plan:
                conn.execute(
                    "UPDATE candidates SET band=%s, hib_signal=%s, probes=%s"
                    " WHERE id=%s AND band IS NULL AND hib_signal IS NULL"
                    " AND probes='[]'::jsonb",
                    (r["band"], json.dumps(r["hib_signal"]) if r["hib_signal"]
                     else None, json.dumps(r["probes"]), cid))

    return {
        "batch_id": batch_id, "filled": [cid for cid, _ in plan],
        "probes": sum(len(r["probes"]) for _, r in plan),
        "signals": sum(1 for _, r in plan if r["hib_signal"]),
        "bands": {b: sum(1 for _, r in plan if r["band"] == b)
                  for b in BANDS if any(r["band"] == b for _, r in plan)},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Load a producer's fleet-candidates block into the database.")
    ap.add_argument("document", type=Path)
    ap.add_argument("--source-sha", help="the fleet commit the document is at; "
                                         "required unless --backfill-batch")
    ap.add_argument("--note", help="candidate_batches.note")
    ap.add_argument("--backfill-batch", type=int, metavar="N",
                    help="fill 025's three columns on an existing hand-loaded "
                         "batch instead of creating a new one")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse, validate and print; write nothing")
    args = ap.parse_args(argv)

    try:
        if args.backfill_batch is not None:
            out = backfill(args.document, args.backfill_batch,
                           dry_run=args.dry_run)
            what = (f"would fill {len(out['filled'])}" if args.dry_run
                    else f"filled {len(out['filled'])}")
            print(f"{what} row(s) in batch {out['batch_id']}: "
                  f"{out['probes']} probe(s), {out['signals']} signal(s), "
                  f"bands {out['bands']}")
            print(f"  candidates: {out['filled']}")
        else:
            if not args.source_sha:
                ap.error("--source-sha is required: a batch attributable to a "
                         "document without a commit is attributable to a morning")
            out = load(args.document, source_sha=args.source_sha,
                       note=args.note, dry_run=args.dry_run)
            what = "would load" if args.dry_run else f"loaded batch {out['batch_id']}:"
            print(f"{what} {out['candidates']} candidate(s), {out['probes']} "
                  f"probe(s), {out['signals']} signal(s), bands {out['bands']}")
            wk = out["work_keys"]
            print(f"  work keys: {wk['row']} resolved to a document row, "
                  f"{wk['topic']} keyed by heading only, {wk['none']} not keyed")
            for u in out["unkeyed"]:
                print(f"    NOT KEYED {u['title'][:50]!r}: {u['why']}")
            if out["candidate_ids"]:
                print(f"  candidates: {out['candidate_ids']}")
    except LoadRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
