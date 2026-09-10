#!/usr/bin/env python3
"""Acceptance check for a CANDIDATE PRODUCER task.

Run from the root of the worktree. Reads FLEET_CHANGED_FILES, which the runner
derived from git.

WHY A LIVE PROBE AND NOT A FORMAT GUARD

A parser over `specs/metorik-gap.md` yields rows that read as current and are
not. Measured against platform HEAD `ebe016c` on 8 Sep 2026, four Daily-band
rows the document calls Missing or Partial:

    Order filtering "nothing else"      WRONG -- payment_method, country,
                                        coupon and has_discount all present
    Location reports "no page"          WRONG -- geography/page.tsx exists
    CSV export "only /segments/export"  still true
    Net revenue "no aggregate nets it"  still true

Two of four, and they are exactly the two a person caught by hand when batch 8
was assembled. The document is 11 days old and the staleness is invisible in
its text. So this check does not validate the SHAPE of a claim about the
repository -- it RE-EXECUTES the claim. Every candidate declares predicates
from a closed vocabulary and they are re-run here, against the tree as it is
now. A candidate whose predicate no longer holds fails the branch.

WHAT THE VOCABULARY IS, AND WHY IT IS CLOSED

    path_exists: <path>
    path_absent: <path>
    grep_count: {glob: <glob>, pattern: <regex>, expected: <int>}

Evaluated with pathlib and re. Nothing is shelled out, so a probe cannot
become an arbitrary command, and the agent that writes one has no shell to
test it with anyway.

WHAT THIS CANNOT ESTABLISH

It proves presence and absence in a repository. It cannot prove a claim about
the world -- whether Metorik still ships a feature, whether merchants want
one, whether the agency-use band is right. It cannot prove a feature is
COMPLETE: `payment_method` appearing in `orders.py` is not the filter working.
It cannot tell whether a row marked Missing is missing for a good reason, nor
whether a candidate's probes test the claim it actually made rather than
something adjacent. Those are a read, and this check exists to make that read
smaller rather than to replace it.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

FLEET = Path.home() / "fleet"
PLATFORM = Path.home() / "deadly-digital-platform"
REPOS = {"fleet": FLEET, "deadly-digital-platform": PLATFORM}

BLOCK_RE = re.compile(r"```fleet-candidates\s*\n(.*?)\n```", re.S)

#: §7's six. `objective_ref` and `suggested_paths` may be null/empty, but the
#: KEY must be present -- "the producer did not consider it" and "the producer
#: considered it and found none" are different facts, and only a required key
#: keeps them apart.
REQUIRED = ("title", "rationale", "repo", "evidence", "suggested_paths",
            "objective_ref")

#: §7's prohibitions, enforced in the SHAPE so a producer cannot express
#: pre-approval even by accident. `work_type` is here for the reason
#: draft_spec_shape.py records: `candidates` has no work_type column, because
#: a producer reading a findings document would be guessing at what the
#: draft-spec step exists to determine.
FORBIDDEN = ("disposition", "disposition_reason", "work_type", "batch_id",
             "spec_task_id", "work_task_id", "approval_decision_id")

#: Carried per candidate so a batch approved a week later can be checked
#: against what moved, rather than trusted.
PER_CANDIDATE_SHA = "verified_sha"

MIN_RATIONALE_WORDS = 12
MIN_UNASKED_WORDS = 20

#: `objectives_considered`, and the two objectives a batch must have weighed.
#:
#: BATCH 9 PUT `dd-feature-parity` ON ALL NINE ROWS with no justification
#: anywhere in the block, and two of those rows are document rows a PERSON had
#: labelled `dd-trustworthy` eleven days earlier (candidates 12 and 13 became
#: 21 and 22 -- the same work, provably, since they share a work_key).
#:
#: The objectives file predicted this in its own comments, twice:
#:
#:     dd-feature-parity  "NEEDS A BASELINE ... Without that, this objective
#:                         ranks 'build another report' forever."
#:     dd-trustworthy     "Parity work must not outrank correctness work by
#:                         default."
#:
#: A producer handed the Metorik gap list and a list of objective ids will
#: infer that a gap list serves the gap objective. That inference is what
#: flattened the one field carrying principles.md's top ranking rule -- trust
#: above parity -- into a constant, and nothing anywhere noticed.
#:
#: This does NOT check that the labels are right; no check can, that is the
#: judgement the field exists to record. It checks that more than one objective
#: was WEIGHED, in writing, on the same argument `unasked_question` is required
#: on: a producer made to write the uncomfortable sentence has to look at the
#: thing the sentence is about.
MIN_OBJECTIVES_WORDS = 25
MIN_OBJECTIVES_NAMED = 2

#: The closed probe vocabulary, named once. run_probe() below dispatches on
#: these and console/load_candidates.py refuses a block carrying anything else,
#: so the loader can check the vocabulary without holding a second copy of it
#: that drifts. Adding a predicate means adding it here AND in run_probe.
PROBE_KINDS = ("path_exists", "path_absent", "grep_count")


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(("git", "-C", str(repo)) + args,
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


# ---- the probes ------------------------------------------------------------

def run_probe(repo: Path, probe: dict) -> tuple[bool, str]:
    """Re-execute one declared predicate. (held, description)."""
    if not isinstance(probe, dict) or len(probe) != 1:
        return False, f"a probe must be one key from the vocabulary, got {probe!r}"
    kind, arg = next(iter(probe.items()))

    if kind in ("path_exists", "path_absent"):
        if not isinstance(arg, str) or not arg.strip():
            return False, f"{kind} needs a path"
        target = repo / arg
        exists = target.exists()
        want = (kind == "path_exists")
        return (exists == want,
                f"{kind}: {arg} {'exists' if exists else 'does not exist'}")

    if kind == "grep_count":
        if not isinstance(arg, dict):
            return False, "grep_count needs {glob, pattern, expected}"
        glob = arg.get("glob"); pattern = arg.get("pattern")
        expected = arg.get("expected")
        if not glob or not pattern or not isinstance(expected, int):
            return False, "grep_count needs glob, pattern and an integer expected"
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return False, f"grep_count pattern is not a regex: {exc}"
        n = 0
        for p in sorted(repo.glob(glob)):
            if not p.is_file():
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            n += len(rx.findall(text))
        return n == expected, f"grep_count {glob} /{pattern}/ = {n}, expected {expected}"

    return False, (f"{kind!r} is not in the probe vocabulary "
                   f"({', '.join(PROBE_KINDS)})")


# ---- the block -------------------------------------------------------------

def objective_ids() -> set[str]:
    """From the objectives file, never a second copy of the list."""
    sys.path.insert(0, str(FLEET))
    from proposer.objectives import load
    return set(load(FLEET / "objectives-2026-Q4.yaml").by_id)


def check_coverage(where: str, sig: dict) -> list[str]:
    """`hib_signal.coverage`: the same figure as two numbers, or an explicit null.

    028 and specs/auto-approval.md §11. `value` is a SENTENCE and stays one --
    it is what the morning brief prints and what a person judges. This is the
    half a ranker can read, and until it existed the one real discriminator in
    the pool was unreachable: c20 and c21 are both frontend-only and both
    Daily, and their signals are 2,782,530 of 2,844,177 against 1 of 2,844,177.

    REQUIRED KEY, NULL PERMITTED -- the third time this table uses that shape.
    "all seven RFM buckets populated on tenant 2" is a real signal and is not a
    ratio, so `coverage: null` is a legitimate and different answer from having
    not thought about it.

    BOTH NUMBERS OR NEITHER. The source document writes "coupon_code populated
    on 146,136 orders" with the denominator two sections away, and a numerator
    alone is not a coverage figure -- it is the half-a-fact 025's constraint
    already refuses for {value, as_of}.
    """
    if "coverage" not in sig:
        return [f"{where} has an hib_signal with no `coverage` key. It may be "
                f"null -- a signal that is not a population figure is a real "
                f"signal -- but the key is required, because 'this is not a "
                f"ratio' and 'nobody worked out whether it was' are different "
                f"facts and only a required key keeps them apart."]
    cov = sig["coverage"]
    if cov is None:
        return []
    if not isinstance(cov, dict):
        return [f"{where} has a `coverage` that is not a mapping: {cov!r}"]

    problems = []
    if not str(cov.get("metric") or "").strip():
        problems.append(
            f"{where} has a `coverage` with no `metric`. A ratio that cannot "
            f"say what it counted is a number nobody can check.")
    missing = [k for k in ("populated", "total") if cov.get(k) is None]
    if missing:
        problems.append(
            f"{where} has a `coverage` missing {missing}. Both or neither: "
            f"the source document says 'coupon_code populated on 146,136 "
            f"orders' and leaves the denominator two sections away, and "
            f"'populated on 146,136' answers nothing without 'of how many'.")
        return problems
    try:
        populated = float(cov["populated"])
        total = float(cov["total"])
    except (TypeError, ValueError):
        problems.append(f"{where} has a non-numeric populated/total: "
                        f"{cov.get('populated')!r} of {cov.get('total')!r}")
        return problems
    if total <= 0:
        problems.append(f"{where} has a coverage total of {total}, and a "
                        f"denominator of zero is not a measurement")
    elif populated < 0 or populated > total:
        problems.append(
            f"{where} has coverage {populated} of {total}, which is not a "
            f"fraction of anything")
    return problems


def check_candidate(n: int, c, repo_name_ok, objectives, max_paths_missing) -> list[str]:
    problems: list[str] = []
    where = f"candidate {n}"
    if not isinstance(c, dict):
        return [f"{where} is not a mapping"]
    title = str(c.get("title") or "").strip()
    where = f"candidate {n} ({title[:40] or 'untitled'})"

    for field in REQUIRED:
        if field not in c:
            problems.append(f"{where} is missing the required field {field!r}")
    for field in FORBIDDEN:
        if field in c:
            problems.append(
                f"{where} sets {field!r}. A producer that could set a "
                f"disposition or name a task is the autonomy this refuses; "
                f"every candidate arrives PENDING and the surface decides.")

    if not title:
        problems.append(f"{where} has no title")
    rationale = str(c.get("rationale") or "")
    if len(rationale.split()) < MIN_RATIONALE_WORDS:
        problems.append(
            f"{where} has a {len(rationale.split())}-word rationale, under "
            f"{MIN_RATIONALE_WORDS}. Without one a tick is a guess.")

    repo_name = c.get("repo")
    if repo_name not in REPOS:
        problems.append(f"{where} names repo {repo_name!r}; known: {sorted(REPOS)}")
        return problems
    repo = REPOS[repo_name]

    ref = c.get("objective_ref")
    if ref is not None and ref not in objectives:
        problems.append(
            f"{where} names objective {ref!r}, which "
            f"objectives-2026-Q4.yaml does not contain")

    # §7: evidence needs the document AND the sha it was read at.
    evidence = c.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        problems.append(f"{where} carries no evidence entry")
    else:
        for e in evidence:
            if not isinstance(e, dict) or not e.get("document") or not e.get("sha"):
                problems.append(
                    f"{where} has an evidence entry without a document and the "
                    f"sha it was read at; a candidate that cannot be traced "
                    f"back to its finding is an assertion")

    # The sha this row was verified at, per row.
    sha = c.get(PER_CANDIDATE_SHA)
    if not sha:
        problems.append(f"{where} does not carry {PER_CANDIDATE_SHA}")
    elif git(repo, "cat-file", "-e", f"{sha}^{{commit}}") is None:
        problems.append(
            f"{where} carries {PER_CANDIDATE_SHA} {str(sha)[:12]}, which is "
            f"not a commit in {repo_name}")

    # hib_signal: a FACT if the source document carries one, and explicitly
    # absent if it does not. Never inferred.
    if "hib_signal" not in c:
        problems.append(
            f"{where} omits hib_signal. It is required and may be null -- "
            f"'the document declares none' is a fact worth stating, and "
            f"inferring one from what HIB has is a different claim.")
    else:
        sig = c.get("hib_signal")
        if sig is not None:
            if not isinstance(sig, dict) or not sig.get("value") or not sig.get("as_of"):
                problems.append(
                    f"{where} has an hib_signal without both value and as_of. "
                    f"The age of this signal is the thing that decides whether "
                    f"it can be leaned on.")
            else:
                problems += check_coverage(where, sig)

    paths = c.get("suggested_paths") or []
    if not isinstance(paths, list):
        problems.append(f"{where} suggested_paths is not a list")
    else:
        missing = [p for p in paths
                   if not (repo / str(p)).exists()
                   and not (repo / str(p)).parent.exists()]
        if missing:
            problems.append(
                f"{where} suggests paths whose directory does not exist in "
                f"{repo_name}: {missing}")

    probes = c.get("probes")
    if not isinstance(probes, list) or not probes:
        problems.append(
            f"{where} declares no probes. A claim about the repository that "
            f"cannot be re-executed is the staleness this check exists for.")
    else:
        for probe in probes:
            held, desc = run_probe(repo, probe)
            if not held:
                problems.append(f"{where} probe FAILED at HEAD -- {desc}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    # THE CEILING LIVES IN THE CONTRACT, not in whoever writes the next
    # findings document. A sixty-row document must not be able to flood the
    # approval surface.
    ap.add_argument("--max-candidates", type=int, default=10)
    args = ap.parse_args(argv)

    changed = [f for f in (os.environ.get("FLEET_CHANGED_FILES") or "").split()
               if f.endswith(".md")]
    if not changed:
        return fail("no markdown file in the change; a candidate producer "
                    "produces a document")
    if len(changed) > 1:
        return fail(f"the change touches {len(changed)} markdown files: "
                    f"{changed}. One document, one batch.")

    rel = changed[0]
    text = Path(rel).read_text()
    blocks = BLOCK_RE.findall(text)
    if len(blocks) != 1:
        return fail(f"{rel} carries {len(blocks)} ```fleet-candidates blocks; "
                    f"exactly one is required")
    try:
        block = yaml.safe_load(blocks[0])
    except yaml.YAMLError as exc:
        return fail(f"{rel}'s fleet-candidates block is not valid YAML: {exc}")
    if not isinstance(block, dict):
        return fail(f"{rel}'s fleet-candidates block is not a mapping")

    problems: list[str] = []

    source = block.get("source") or {}
    if not source.get("document") or not source.get("sha"):
        problems.append("the block's source must name the findings document "
                        "and the sha it was read at")
    elif not (FLEET / str(source["document"])).exists():
        problems.append(f"source document {source['document']} does not exist")

    # NOT RANKED, AND IT HAS TO SAY SO. The gap list orders by agency-use
    # frequency; principles.md ranks by what HIB's team would open and puts
    # trust above parity. Batch 8 established that candidate order IS rank
    # order, so a list that looks ranked and is not is the failure.
    if block.get("ordering") != "unranked":
        problems.append(
            "the block must declare `ordering: unranked`. The source document "
            "ranks by agency-use frequency, which is not the ranking "
            "principles.md asks for, and candidate order is read as rank "
            "order -- so the producer must not appear to have ranked.")

    unasked = str(block.get("unasked_question") or "")
    if len(unasked.split()) < MIN_UNASKED_WORDS:
        problems.append(
            "the block must carry `unasked_question`: nobody has asked HIB's "
            "team what they need, so a candidate justified by hib_signal is "
            "justified by what HIB HAS rather than what its team WANTS. Said "
            "once, on the block, so a batch approved off it does not read as "
            "evidence-backed when it is inference-backed.")

    # THE OBJECTIVE HAS TO BE WEIGHED, NOT INFERRED FROM THE DOCUMENT'S TITLE.
    #
    # Loaded here rather than at the bottom because this check needs the ids
    # and the per-candidate loop below needs the same set; one read, one
    # answer.
    objectives = objective_ids()
    considered = str(block.get("objectives_considered") or "")
    named = sorted(o for o in objectives
                   if re.search(rf"(?<![\w-]){re.escape(o)}(?![\w-])", considered))
    if len(considered.split()) < MIN_OBJECTIVES_WORDS:
        problems.append(
            f"the block must carry `objectives_considered`: at least "
            f"{MIN_OBJECTIVES_WORDS} words naming which objectives were "
            f"weighed for these rows and why they landed where they did. "
            f"objectives-2026-Q4.yaml says of dd-feature-parity that without "
            f"a baseline it 'ranks build another report forever', and of "
            f"dd-trustworthy that 'parity work must not outrank correctness "
            f"work by default'. Batch 9 put dd-feature-parity on all nine "
            f"rows, two of which a person had labelled dd-trustworthy eleven "
            f"days earlier, and the block said nothing about it.")
    elif len(named) < MIN_OBJECTIVES_NAMED:
        problems.append(
            f"`objectives_considered` names {len(named)} objective(s) "
            f"({', '.join(named) or 'none'}) and must name at least "
            f"{MIN_OBJECTIVES_NAMED} by id. Weighing one objective is not "
            f"weighing. principles.md ranks trust above parity, and the field "
            f"that carries which of the two a row serves is the one this "
            f"producer flattened to a constant -- so the comparison has to be "
            f"written down, even when the answer is that every row is parity. "
            f"Known ids: {', '.join(sorted(objectives))}.")

    candidates = block.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return fail(f"{rel} declares no candidates. A producer that ran and "
                    f"found nothing is a batch with zero rows, which is a "
                    f"different thing from a block with no list.")
    if len(candidates) > args.max_candidates:
        problems.append(
            f"{rel} emits {len(candidates)} candidates, over the contract's "
            f"ceiling of {args.max_candidates}. Listing is cheap and ticking "
            f"is the work, but a findings document must not be able to flood "
            f"the surface.")

    titles = [str(c.get("title") or "").strip().lower()
              for c in candidates if isinstance(c, dict)]
    dupes = {t for t in titles if t and titles.count(t) > 1}
    if dupes:
        problems.append(f"{rel} emits duplicate titles: {sorted(dupes)}")

    for n, c in enumerate(candidates, start=1):
        problems += check_candidate(n, c, REPOS, objectives, None)

    if problems:
        print(f"FAIL: {rel} -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1

    probes = sum(len(c.get("probes") or []) for c in candidates)
    signals = sum(1 for c in candidates if c.get("hib_signal"))
    ratios = sum(1 for c in candidates
                 if isinstance((c.get("hib_signal") or {}).get("coverage"), dict))
    print(f"ok: {rel} -- {len(candidates)} candidate(s), {probes} probe(s) "
          f"re-executed at HEAD and all holding, {signals} carrying an "
          f"hib_signal ({ratios} of them a coverage ratio), none setting a "
          f"disposition, ordering declared unranked.")

    # PRINTED WHETHER OR NOT IT IS A PROBLEM. A batch where every row serves
    # one objective may be perfectly honest, and it is also the exact shape of
    # the defect -- so the tally goes in front of whoever reads the run rather
    # than being inferred from nine identical lines further down the file.
    spread: dict = {}
    for c in candidates:
        spread[c.get("objective_ref")] = spread.get(c.get("objective_ref"), 0) + 1
    flat = " -- EVERY ROW, which objectives_considered had to argue for" \
        if len(spread) == 1 and len(candidates) > 1 else ""
    print(f"    objectives: "
          f"{', '.join(f'{k or 'none'}={v}' for k, v in sorted(spread.items(), key=lambda kv: str(kv[0])))}"
          f"{flat}; considered: {', '.join(named)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
