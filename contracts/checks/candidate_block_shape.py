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

THE PREMISE, WHICH IS A DIFFERENT CLAIM FROM THE PROBES

    premise:
      - claim: <the sentence the work rests on, in words>
        probe: {grep_count: {...}}      one predicate, same vocabulary

`probes` say what is MISSING -- the gap is real and still open. A `premise`
says what must ALREADY BE TRUE for the work to be the work described. Required
since 10 Sep 2026, and candidate 38 is why.

c38 proposed making the Payment, Country and Coupon cells of the order table
set the matching filter, and its rationale said those values "are inert". They
were not in the table at all: the page rendered wc_order_id, created_at,
billing_email, status and total, and never those three. Its four probes all
held -- the filter box exists, nothing wires a cell to it, the API accepts the
parameter, the file exists -- because every one of them tested the GAP and none
tested the GROUND. The task cost £2.25 and the agent, correctly on the facts it
found, added three columns nobody had specified. See specs/auto-approval.md
§9.9.1.

A premise is re-executed here, exactly like a probe, and again at the approval
in console/rank.py against the sha about to be spent on.

WHAT THIS CANNOT ESTABLISH

It proves presence and absence in a repository. It cannot prove a claim about
the world -- whether Metorik still ships a feature, whether merchants want
one, whether the agency-use band is right. It cannot prove a feature is
COMPLETE: `payment_method` appearing in `orders.py` is not the filter working.
It cannot tell whether a row marked Missing is missing for a good reason.

AND IT STILL CANNOT TELL WHETHER A PREDICATE TESTS THE CLAIM IT IS FILED
UNDER, which is the whole of what the premise key moves rather than solves. A
producer may write `claim: the columns are rendered` over a probe that greps
for something adjacent, and this will run the probe, find it holds, and pass.
What changed is that the sentence now has to be WRITTEN DOWN beside the
predicate, in the row, on the decision record -- so the question a reader has
to ask is one specific sentence rather than the whole rationale. Those are a
read, and this check exists to make that read smaller rather than to replace
it.
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
#: Short enough that one clause satisfies it, long enough that `the columns
#: exist` does not. The claim is prose because a reader checks the predicate
#: against it; see check_premise().
MIN_PREMISE_WORDS = 6

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


#: The one unit a figure may be in, and the same closed set 045's CHECK
#: constraint and console/rank.IMPACT_UNITS enforce.
IMPACT_UNITS = ("ms",)

#: The keys a stated figure must carry. `what` and `dataset` are prose because
#: a reader is the only check on this number; `as_of` is a date because a
#: figure that cannot be told from a stale one is not evidence.
IMPACT_KEYS = ("value", "unit", "what", "dataset", "as_of")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_measured_impact(where: str, c: dict) -> list[str]:
    """`measured_impact`: what the work is worth NOW, or an explicit null.

    045 and console/rank.impact_class(). Key 5 exists because four keys that
    are all properties of a row's FORM could not separate c66 from c67 -- and
    the document both were loaded from times them at 619 ms and 89 ms, twenty
    minutes before the load.

    REQUIRED KEY, NULL PERMITTED, the fourth time this file uses that shape.
    Most work has no latency figure and never will: a CSV export is worth
    building and is not worth milliseconds. `measured_impact: null` says the
    producer considered it and the document states none, which is a different
    fact from the key having been forgotten -- and only a required key keeps
    them apart.

    THIS CHECK CANNOT RE-EXECUTE THE FIGURE, AND NOTHING DOWNSTREAM CAN EITHER.
    Every other claim in a candidate block is a predicate over a source tree
    and run_probe() runs it. A latency is not: re-taking it needs a database, a
    tenant, a warm cache and a clock, and this contract grants no Bash on
    purpose. So what follows is SHAPE -- that a number was stated, in a unit
    the ranker understands, about a named thing, on a named dataset, on a
    stated date. A producer can write 619 ms over a measurement it never took
    and this will pass, exactly as spec_requirements_cited.py will pass a
    `spec:` token written over work that was not done. What it converts is a
    silent omission into a written, attributable, dated claim that a reader
    can check against the source document. That is all it converts.

    MEASURED, NOT PROJECTED, and c67 is why the rule is worth stating. Its
    figure today is 89 ms; its argument is that a two-year store holds ~730
    manifests instead of 36, which is ~1.8 s. The second number is the reason
    to build it and belongs in `rationale`, where a reader weighs it. A
    producer allowed to put it HERE would be choosing the horizon that wins,
    and no reader downstream could tell which horizon it chose.
    """
    if "measured_impact" not in c:
        return [f"{where} omits measured_impact. It is required and may be "
                f"null -- most work has no latency figure and never will, and "
                f"'the document states none' is a fact worth stating. What it "
                f"may NOT be is absent, because c66 and c67 tied for 15 sweeps "
                f"on a difference their own source document had measured."]
    fig = c["measured_impact"]
    if fig is None:
        return []
    if not isinstance(fig, dict):
        return [f"{where} has a measured_impact that is not a mapping: {fig!r}"]

    problems = []
    missing = [k for k in IMPACT_KEYS if k not in fig]
    if missing:
        problems.append(
            f"{where} has a measured_impact missing {missing}. A figure needs "
            f"all five: nothing re-executes this number, so the dataset it was "
            f"taken on and the date it was taken are the whole of what makes "
            f"it checkable.")
        return problems

    if fig.get("unit") not in IMPACT_UNITS:
        problems.append(
            f"{where} states a measured_impact in {fig.get('unit')!r}. The "
            f"vocabulary is closed to {list(IMPACT_UNITS)}: c66 is truly 619 "
            f"ms and truly 4,546,466 rows scanned, and only one of those can "
            f"be compared with c67's 89 ms. A ranker handed both would order "
            f"them anyway. A second unit is a migration that says how the two "
            f"compare.")
    raw = fig["value"]
    # A REAL NUMBER, not something that coerces to one. YAML gives `value: 619`
    # as an int and `value: "619"` as a string, and the three places that judge
    # this figure -- here, 045's CHECK constraint, and console/rank.impact_class
    # -- have to agree about which is acceptable, or a block passes the producer
    # and is refused at the INSERT.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        problems.append(
            f"{where} has a non-numeric measured_impact value: "
            f"{raw!r}. As text, '89' sorts above '619'.")
    else:
        value = float(raw)
        if value <= 0:
            problems.append(
                f"{where} states a measured_impact of {value}, and zero is not "
                f"a measurement of impact -- it is a statement that there is "
                f"none, which is a row that should not have been filed.")
    for key in ("what", "dataset"):
        if not str(fig.get(key) or "").strip():
            problems.append(
                f"{where} has a measured_impact with no `{key}` in words. "
                f"A bare number is not a figure a reader can check.")
    if not ISO_DATE.match(str(fig.get("as_of") or "")):
        problems.append(
            f"{where} has a measured_impact as_of {fig.get('as_of')!r}, which "
            f"is not an ISO date. 'recently' satisfies a non-empty test and "
            f"tells a reader nothing about whether the figure still holds.")
    return problems


class BandUncheckable(RuntimeError):
    """The band rule could not be asked, which is not the same as passing."""


def check_band(c) -> str | None:
    """One frequency per candidate, asked of the loader's own function.

    WHY THIS IS HERE AT ALL. `console.load_candidates.band_of` has always
    refused a candidate whose evidence sections name two bands, and nothing
    this producer must pass asked the same question. So a block could clear
    every gate in its contract, be verified, be merged -- and then be
    unloadable, which is what happened to batch 15 on 14 Sep 2026: candidates
    2 and 3 each cited two bands, the run cost GBP 5.50, and the refusal
    arrived after the merge with no way back except editing the document by
    hand.

    That is the shape of defect this file's own header warns about one level
    down: a gate that establishes less than the reader assumes. A producer's
    contract should refuse what the loader will refuse, at the point where
    refusing is free.

    AN IMPORT AND NOT A SECOND COPY, on spec_requirements_cited.py's
    precedent. The rule, the band vocabulary and the heading grammar all live
    in the loader; restating them here is how the gate and the loader start
    disagreeing, and a producer told one rule while judged by another is worse
    off than one told nothing.

    IMPORTED INSIDE THE FUNCTION, WHICH IS LOAD-BEARING. `load_candidates`
    already imports THIS module, by path, to avoid restating its constants --
    see its `_shape_check()`. Importing it back at module scope would close
    that loop at import time. Deferring to call time keeps the existing
    direction intact: the loader owns the rule, this file asks it.

    Returns the problem as a sentence, or None. Raises `BandUncheckable` when
    the loader cannot be imported at all -- a rule that cannot be asked must
    not read as a rule that passed.
    """
    sys.path.insert(0, str(FLEET))
    try:
        from console.load_candidates import LoadRefused, band_of
    except Exception as exc:                       # noqa: BLE001
        raise BandUncheckable(
            f"cannot import console.load_candidates ({exc}), so the band rule "
            f"could not be checked. This check refuses rather than passing: "
            f"the whole point of it is that the loader and this gate agree, "
            f"and a gate that cannot reach the loader knows nothing.") from exc
    try:
        band_of(c)
    except LoadRefused as exc:
        return str(exc)
    return None


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
        band_problem = check_band(c)
        if band_problem:
            problems.append(f"{where} {band_problem}")

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

    problems += check_measured_impact(where, c)

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

    problems += check_premise(where, repo, c)
    return problems


def check_premise(where: str, repo: Path, c: dict) -> list[str]:
    """The ground the work stands on, stated and then re-executed.

    REQUIRED, AND AN EMPTY LIST IS NOT A PREMISE. "This work needs nothing to
    be true first" is not a thing a candidate can say: every candidate that
    describes work on an existing file asserts something about that file, and
    c38's whole failure was that the assertion lived in the rationale where
    nothing could run it.

    ONE ENTRY IS ENOUGH and no maximum is imposed. The point is not coverage
    of every sentence in the rationale -- that is unbounded and would produce
    probes written to satisfy a count. It is that the LOAD-BEARING sentence,
    the one whose falseness changes what the work is, exists as a predicate.
    """
    problems: list[str] = []
    premise = c.get("premise")
    if "premise" not in c:
        problems.append(
            f"{where} omits premise. State what must ALREADY be true for this "
            f"work to be the work you are describing, as a claim in words and "
            f"a probe that establishes it. Candidate 38's rationale rested on "
            f"the order table rendering three columns it had never rendered, "
            f"and its four probes all held because every one of them tested "
            f"the gap rather than the ground.")
        return problems
    if not isinstance(premise, list) or not premise:
        problems.append(
            f"{where} has an empty premise. A candidate that needs nothing to "
            f"be true first is one nothing can be wrong about, and zero "
            f"predicates holding is a check that cannot fail.")
        return problems

    for i, entry in enumerate(premise, 1):
        at = f"{where} premise {i}"
        if not isinstance(entry, dict):
            problems.append(f"{at} is not a mapping of claim and probe")
            continue
        claim = str(entry.get("claim") or "").strip()
        if len(claim.split()) < MIN_PREMISE_WORDS:
            problems.append(
                f"{at} has a {len(claim.split())}-word claim, under "
                f"{MIN_PREMISE_WORDS}. The sentence is what a reader checks "
                f"the predicate AGAINST; without it there is only the "
                f"predicate, and the open question is whether the predicate "
                f"tests the claim or something adjacent.")
        probe = entry.get("probe")
        if not isinstance(probe, dict) or len(probe) != 1:
            problems.append(
                f"{at} has no single probe from the vocabulary "
                f"({', '.join(PROBE_KINDS)}); a claim with nothing to run is "
                f"the rationale sentence that cost c38 a run.")
            continue
        # THE KIND BEFORE THE RUN. run_probe() reports an unknown kind as a
        # predicate that did not hold, which is true and reads as "the claim
        # has stopped being true at HEAD" -- a producer told that will go and
        # adjust a claim that was never executable. Named as a vocabulary
        # problem here, where it is one.
        if next(iter(probe)) not in PROBE_KINDS:
            problems.append(
                f"{at} has a probe {next(iter(probe))!r}, which is not in the "
                f"vocabulary ({', '.join(PROBE_KINDS)}). A premise is executed "
                f"by the same run_probe() as a probe and cannot become "
                f"anything else by being filed under a different key.")
            continue
        held, desc = run_probe(repo, probe)
        if not held:
            problems.append(
                f"{at} FAILED at HEAD -- {desc}\n"
                f"      claim: {claim}\n"
                f"      The ground this candidate stands on is not there. That "
                f"is not a probe to adjust: it means the work is a different "
                f"piece of work from the one described.")
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
        try:
            problems += check_candidate(n, c, REPOS, objectives, None)
        except BandUncheckable as exc:
            # EXIT 2, WHICH IS NOT EXIT 1. runner/verify.py reads 2 as COULD
            # NOT RUN, and the distinction is the one this whole file is built
            # on: "the loader is unreachable" and "this block is wrong" send a
            # reader to different places, and only the second is about the
            # producer's work.
            print(f"COULD NOT RUN: {exc}")
            return 2

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
