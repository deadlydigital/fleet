"""Ordering open candidates, and refusing to order them when nothing separates.

specs/auto-approval.md §2.2. A pure `rank()` over five gates, and the gates are
not part of the ranking: a candidate that fails one is not rejected and not
marked -- it is simply not approved by the machine, stays PENDING, and appears
in the morning brief with the rule that held it. That is the shape
specs/unattended-operation.md §5.2 already chose for the repeat stop: withhold
the automatic approval, never the candidate.

WHAT RANKS, AND WHAT DELIBERATELY DOES NOT
-------------------------------------------
Three keys: the work class read off the probes, the band, the candidate id.

COST DOES NOT RANK. Every draft-spec task reserves the same £2.50 from
contracts/draft-spec.yaml and `est_cost_gbp` is NULL on every row. Cost is a
CEILING here -- the credit check, the per-task cap, the pace -- and a ceiling is
not a rank. Ranking on a number that is identical for every row is a way of
looking like a decision was made.

hib_signal DOES NOT RANK. It is displayed. Its value is free text, and two of
the four say opposite things about whether the work is worth doing:

    "payment_method populated on 2,782,530 of 2,844,177 orders"
    "refund_total non-zero on 1 of 2,844,177 orders"

The second is the net-revenue candidate and it is an argument AGAINST building
it: a net figure over refunds that were never captured is a confident wrong
number, which is worse than no figure. No sort key extracts that from a
sentence, and a ranker scoring "has a signal" as a positive would rank net
revenue UP on the strength of the fact that argues it down. So the signal is
carried into the decision record and printed verbatim in the brief, where the
reader who can judge it sees it.
"""
from __future__ import annotations

import fnmatch
import functools
import importlib.util
import re
import subprocess
from pathlib import Path

import yaml
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import config
# The threshold is console/approve.py's and stays there: approve.py is what
# ENFORCES it inside the approving transaction, and a second literal here would
# be the drift where the gate holds at one number and the ceiling refuses at
# another. This gate is the same rule, applied early enough that the ranking
# can pass over the row instead of the night dying on a refusal.
from .approve import REPEAT_FAILURE_STOP

#: Bumped when any key changes meaning or order. Recorded on every decision, so
#: last week's batches stay attributable to the ranking that made them instead
#: of being silently re-explained by this week's.
#:
#: v2 (10 Sep 2026): coverage inserted as key 2, band moves to key 3. 028.
RANK_VERSION = 2

#: Key 1's three classes, lower first.
FRONTEND_ONLY, MODIFY, CREATE = 0, 1, 2

CLASS_NAMES = {FRONTEND_ONLY: "frontend-only", MODIFY: "modify", CREATE: "create"}

#: Key 3 since v2. A NULL band sorts last and does not gate.
BAND_ORDER = {"daily": 0, "weekly": 1, "monthly": 2, "rarely": 3}
NO_BAND = 4

#: KEY 2, and the three values are not a scale -- they are three different
#: STATEMENTS, and the middle one is why this is not a ratio sort.
#:
#:   DATA_PRESENT   the signal says the column this would report on is
#:                  populated, at or above fleet_hib_coverage_floor()
#:   NO_FIGURE      the signal states no population fraction, or there is no
#:                  signal. NOT zero: "the document declared no figure" and
#:                  "the column is empty" are different facts and ordering
#:                  them together is how a ranker gets net revenue wrong
#:   DATA_ABSENT    the signal says the column is effectively empty. A report
#:                  over an empty column is not a feature -- specs/metorik-
#:                  gap.md's own words -- so it sorts BELOW a row that made no
#:                  claim either way
#:
#: That ordering is the whole point and it is worth stating plainly: a
#: candidate that supplied a bad number ranks below one that supplied none.
#: The alternative rewards silence, and the producer is required to state the
#: figure precisely so that silence is not the cheap option.
COVERAGE_PRESENT, COVERAGE_NONE, COVERAGE_ABSENT = 0, 1, 2

COVERAGE_NAMES = {COVERAGE_PRESENT: "data-present",
                  COVERAGE_NONE: "no-figure",
                  COVERAGE_ABSENT: "data-absent"}

#: Gate 3 looks at every task that is not terminal. A task in any of these
#: states may still write the files it declared.
LIVE_TASK_STATES = ("QUEUED", "CLAIMED", "RUNNING", "READY_FOR_REVIEW")

SPEC_BLOCK_RE = re.compile(r"```fleet-spec\s*\n(.*?)\n```", re.S)


@functools.lru_cache(maxsize=1)
def _shape_check():
    """contracts/checks/candidate_block_shape.py, imported rather than copied.

    run_probe() is the whole reason gate 5 is cheap: it exists, it is pure
    pathlib and `re`, and nothing is shelled out -- so a probe cannot become an
    arbitrary command no matter what a producer writes.

    Cached: gate() calls this once per candidate, and re-executing the module
    twelve times a night to get the same three functions is work for nothing.
    """
    path = config.PROJECT_ROOT / "contracts" / "checks" / "candidate_block_shape.py"
    spec = importlib.util.spec_from_file_location("candidate_block_shape", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- key 1 -----------------------------------------------------------------

def _asserts_presence(kind: str, arg: Any) -> bool:
    """Does this probe say something is ALREADY THERE?"""
    if kind == "path_exists":
        return True
    if kind == "grep_count" and isinstance(arg, dict):
        return isinstance(arg.get("expected"), int) and arg["expected"] >= 1
    return False


def _creates_a_file(kind: str, arg: Any) -> bool:
    """Does this probe say a FILE does not exist?

    THE DISTINCTION KEY 1 TURNS ON, and it is finer than "absence".

        path_absent: platform/.../orders/export/route.ts
            the file is not there. The work creates it.

        grep_count: {glob: platform/.../orders/route.ts, expected: 0}
            the file IS there and does not do the thing. The work edits it.

    Both are absence. Only the first is a new file, and that is what separates
    the three specs that failed on invented paths from the two that passed --
    the agent invented a filename exactly when the candidate gave it nothing to
    read.

    A `grep_count: {expected: 0}` over a GLOB counts as creation too: "nothing
    anywhere under api/analytics/routes/*.py mentions digests" is a statement
    that the feature has no home yet, not that one file is missing a line.
    """
    if kind == "path_absent":
        return True
    if kind == "grep_count" and isinstance(arg, dict):
        if arg.get("expected") != 0:
            return False
        glob = str(arg.get("glob") or "")
        return "*" in glob or "?" in glob
    return False


def _absent_feature_in_existing_file(kind: str, arg: Any) -> bool:
    """A named file that exists and lacks the thing. The modify signal."""
    if kind != "grep_count" or not isinstance(arg, dict):
        return False
    if arg.get("expected") != 0:
        return False
    glob = str(arg.get("glob") or "")
    return bool(glob) and "*" not in glob and "?" not in glob


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def work_class(probes: Sequence[dict]) -> tuple[int, Dict[str, Any]]:
    """Key 1, with the evidence that produced it.

    Returns (class, why). `why` goes into the decision record: a key that
    cannot say what it read is a key nobody can check.
    """
    api_presence: List[str] = []
    platform_feature_absent: List[str] = []
    creates: List[str] = []
    presence_any = False

    for probe in probes or []:
        if not isinstance(probe, dict) or len(probe) != 1:
            continue
        kind, arg = next(iter(probe.items()))
        target = arg if isinstance(arg, str) else str((arg or {}).get("glob") or "")

        if _asserts_presence(kind, arg):
            presence_any = True
            if _under(target, "api"):
                api_presence.append(target)
        if _creates_a_file(kind, arg):
            creates.append(target)
        if _absent_feature_in_existing_file(kind, arg):
            if _under(target, "platform"):
                platform_feature_absent.append(target)

    # Deduplicated, order kept. A candidate commonly asserts the same file
    # twice -- a path_exists and a grep_count over it -- and the raw list puts
    # the filename in the generated reason twice, which reads as two pieces of
    # evidence where there is one.
    def _uniq(xs: List[str]) -> List[str]:
        return list(dict.fromkeys(xs))

    why = {
        "api_presence": _uniq(api_presence),
        "platform_feature_absent": _uniq(platform_feature_absent),
        "creates": _uniq(creates),
    }

    if creates:
        return CREATE, why
    if api_presence and platform_feature_absent:
        # THE STRONGEST CASE, and it sorts at the top of the class: the value is
        # computed, returned, and dropped one layer from a person. The
        # producer's own document is what found it -- "the API gained the
        # capability and the Next.js layer did not carry it to a person".
        return FRONTEND_ONLY, why
    if presence_any:
        return MODIFY, why
    return CREATE, why


def coverage_ratio(candidate: Dict[str, Any]) -> float | None:
    """How much of the data this row would report on exists, or None.

    Read from the STRUCTURED half of hib_signal, never from the sentence. 025
    refused to parse the sentence and was right to; 028 is why there is
    something else to read.
    """
    cov = (candidate.get("hib_signal") or {}).get("coverage")
    if not isinstance(cov, dict):
        return None
    try:
        populated = float(cov["populated"])
        total = float(cov["total"])
    except (KeyError, TypeError, ValueError):
        return None
    return populated / total if total > 0 else None


def coverage_class(candidate: Dict[str, Any],
                   coverage_floor: float | None) -> tuple[int, float | None]:
    """Key 2, and the ratio that produced it.

    `coverage_floor` is passed IN, from fleet_hib_coverage_floor(), for the
    reason prior_failures is: this stays pure, and a literal here would be the
    second copy of a ceiling that drifts from the one in the database.

    A floor of None means THE KEY IS OFF -- every row scores NO_FIGURE and the
    order is v1's. That is the safe direction for a caller that has not been
    taught to read the floor: it loses the discriminator rather than inventing
    a threshold.
    """
    ratio = coverage_ratio(candidate)
    if coverage_floor is None or ratio is None:
        return COVERAGE_NONE, ratio
    return (COVERAGE_PRESENT if ratio >= coverage_floor
            else COVERAGE_ABSENT), ratio


def rank(candidate: Dict[str, Any], *,
         coverage_floor: float | None = None) -> tuple:
    """The sort key. Lower sorts first. PURE -- no database, no filesystem.

    Pure so that a dry run means something: the same inputs give the same
    order, every night, and a change in the output is a change in the inputs
    rather than in the weather.
    """
    klass, _ = work_class(candidate.get("probes") or [])
    cov, _ratio = coverage_class(candidate, coverage_floor)
    band = BAND_ORDER.get(candidate.get("band"), NO_BAND)
    return (klass, cov, band, candidate["id"])


def key_values(candidate: Dict[str, Any], *,
               coverage_floor: float | None = None) -> Dict[str, Any]:
    """The keys, named, for the record and the dry run."""
    klass, why = work_class(candidate.get("probes") or [])
    cov, ratio = coverage_class(candidate, coverage_floor)
    return {
        "key1_class": CLASS_NAMES[klass],
        "key1_why": why,
        "key2_coverage": COVERAGE_NAMES[cov],
        # The ratio AND the floor it was read against, because "data-absent"
        # is a verdict and the morning should be able to see the number and
        # the line it fell under rather than take the word for it.
        "key2_ratio": ratio,
        "key2_floor": coverage_floor,
        "key3_band": candidate.get("band"),
        "key4_id": candidate["id"],
        "sort_key": [klass, cov,
                     BAND_ORDER.get(candidate.get("band"), NO_BAND),
                     candidate["id"]],
    }


# ---- the gates -------------------------------------------------------------

def _norm(p: str) -> str:
    return str(p).strip().strip("/")


def paths_overlap(a: str, b: str) -> bool:
    """Could work on `a` touch `b`?

    Deliberately generous. A missed overlap queues a second task against a file
    another task is already writing; a spurious one holds a candidate for a
    night and prints why. Those costs are not symmetrical.
    """
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # `**` is a directory wildcard in these declarations; fnmatch treats * as
    # matching separators too, which is the generous direction.
    for x, y in ((a, b), (b, a)):
        if ("*" in y or "?" in y) and fnmatch.fnmatch(x, y.replace("**", "*")):
            return True
    return _under(a, b) or _under(b, a)


def declared_paths(task: Dict[str, Any]) -> tuple[List[str], str]:
    """What a live task says it will write, and WHICH SOURCE said it.

    The spec block first: it is what the task actually declared for itself. The
    contract only as a fallback, because contract paths are deliberately wide --
    task 49's contract claims the whole analytics frontend, twenty-seven globs,
    while its fleet-spec block names two files. A fallback match is a much
    weaker statement than a spec match, so which one matched is recorded rather
    than flattened into "overlapped".
    """
    import yaml
    md = task.get("spec_md") or ""
    m = SPEC_BLOCK_RE.search(md)
    if m:
        try:
            block = yaml.safe_load(m.group(1))
            paths = (block or {}).get("writable_paths")
            if isinstance(paths, list) and paths:
                return [str(p) for p in paths], "spec"
        except yaml.YAMLError:
            pass
    contract = task.get("acceptance_contract") or {}
    return [str(p) for p in (contract.get("writable_paths") or [])], "contract"


def platform_head(repo: str) -> str | None:
    """The sha gate 5 re-executes against. Recorded on every decision."""
    mod = _shape_check()
    path = mod.REPOS.get(repo)
    if path is None:
        return None
    try:
        r = subprocess.run(("git", "-C", str(path), "rev-parse", "HEAD"),
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def check_probes(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """GATE 5. Re-execute the stored predicates against the tree as it is now.

    The most valuable gate here and the cheapest. The producer verified batch 9
    at platform 4619a76; HEAD moves nightly, and a claim that has stopped being
    true does not get built.

    AN EMPTY LIST FAILS. Zero probes all holding is a check that cannot fail,
    which 024's header names as this codebase's recurring defect -- and a row
    with no probes has no key 1 either, since key 1 is read off them.
    """
    mod = _shape_check()
    probes = candidate.get("probes") or []
    repo_path = mod.REPOS.get(candidate.get("repo"))

    if repo_path is None:
        return {"ok": False, "run": 0, "held": 0,
                "why": f"repo {candidate.get('repo')!r} is not one this host has"}
    if not probes:
        return {"ok": False, "run": 0, "held": 0,
                "why": ("carries no probes, so there is nothing to re-execute; "
                        "zero probes holding is a check that cannot fail")}

    results = []
    for probe in probes:
        held, desc = mod.run_probe(repo_path, probe)
        results.append({"held": bool(held), "probe": desc})
    held = sum(1 for r in results if r["held"])
    failed = [r["probe"] for r in results if not r["held"]]
    return {
        "ok": held == len(results), "run": len(results), "held": held,
        "results": results,
        "why": None if held == len(results) else
               f"{len(failed)} probe(s) no longer hold at HEAD: {'; '.join(failed[:3])}",
    }


def check_premise(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """GATE 6. Re-execute what the work RESTS ON, not what it fills.

    specs/auto-approval.md §9.9.1, and candidate 38 is the whole argument.
    c38's four probes held at 14:11 on 10 Sep and the work was still a
    different piece of work from the one described, because every probe tested
    the GAP -- the filter box exists, no cell is wired to it, the API takes the
    parameter -- and the sentence its rationale actually rested on was that the
    Payment, Country and Coupon values were on screen. They were not columns of
    that table and never had been. £2.25, and an agent that correctly added
    three columns nobody had specified.

    A FAILING PREMISE IS NOT A FAILING PROBE, and they get different rules so
    the brief can say which happened. They point a reader in opposite
    directions:

        probes_failed    the gap closed. Somebody built it, or the document
                         was stale. Drop the row.
        premise_failed   the ground is not there. The row may still be worth
                         doing and it is NOT the work the rationale describes,
                         so what it needs is re-proposing, not re-running.

    AN EMPTY PREMISE FAILS HERE, SINCE 13 Sep 2026, AND THAT CLOSES A HOLE
    THIS DOCSTRING HAS BEEN CARRYING SINCE 10 Sep. It used to pass, because
    every row in the pool predated the column and refusing them would have
    stopped unattended approval dead for rows whose producers were never
    asked. The exit condition was written down at the time -- "once the
    pending pool is rows that were emitted under that rule, an empty premise
    should join an empty probe list as ineligible" -- and removing gate 2 is
    what forced it, EARLIER THAN THE POOL TURNED OVER.

    The reason it could not wait: gate 2 was the only thing keeping the
    pre-030 rows away from approval, and every one of them is silent here.
    Dropping gate 2 while this still returned ok would have released 16 rows
    whose ground nothing has ever checked, and c38 is what that costs -- four
    probes held, the premise was never stated, and the £2.25 bought three
    columns nobody had specified. Gate 8 would have been vacuous on exactly
    the rows the change released, which is the worst possible arrangement:
    a check that reports a pass for the population it cannot see.

    A MISSING PREMISE IS A DIFFERENT RULE FROM A FAILING ONE -- `premise_missing`
    rather than `premise_failed` -- on the same argument gate 5 and gate 6 are
    two rules. They send a reader to different repairs:

        premise_missing  nobody ever stated the ground. Re-produce the row;
                         the producer is required to state one now.
        premise_failed   the ground was stated and is no longer there. The
                         row needs re-proposing, not re-running.

    And there is a counting reason as well as a repair reason. Sixteen rows in
    the pool declare no premise; the gates short-circuit, so on the day this
    ships only TWO of them get as far as here -- c21 and c37, the only two
    whose probes still hold -- against exactly one real `premise_failed`, c46.
    Under one rule name the brief would report three of the same thing, and the
    one row whose ground actually moved would be the one a reader could not
    pick out.
    """
    mod = _shape_check()
    premise = candidate.get("premise") or []
    repo_path = mod.REPOS.get(candidate.get("repo"))

    if repo_path is None:
        return {"ok": False, "declared": len(premise), "held": 0,
                "why": f"repo {candidate.get('repo')!r} is not one this host has"}
    if not premise:
        return {"ok": False, "missing": True, "declared": 0, "held": 0,
                "results": [],
                "why": ("declares no premise, so nothing about the ground this "
                        "work stands on can be re-executed. Zero premises "
                        "holding is a check that cannot fail, which is what "
                        "024's header names as the recurring defect here")}

    results = []
    for entry in premise:
        if not isinstance(entry, dict) or not isinstance(entry.get("probe"), dict):
            results.append({"held": False, "claim": str((entry or {}).get("claim", ""))[:120],
                            "probe": "unreadable premise entry"})
            continue
        held, desc = mod.run_probe(repo_path, entry["probe"])
        results.append({"held": bool(held),
                        "claim": str(entry.get("claim", ""))[:120],
                        "probe": desc})
    held = sum(1 for r in results if r["held"])
    failed = [r for r in results if not r["held"]]
    return {
        "ok": held == len(results), "declared": len(results), "held": held,
        "results": results,
        "why": None if held == len(results) else
               f"{len(failed)} premise(s) no longer hold at HEAD: "
               + "; ".join(f"{r['claim']!r} -- {r['probe']}" for r in failed[:2]),
    }


def contract_writables(repo: str,
                       contracts_dir: Optional[Path] = None
                       ) -> List[Tuple[str, List[str]]]:
    """(contract file, writable globs) for every contract on a repo.

    Read here and passed INTO gate() rather than read inside it, on the same
    argument the docstring below makes about `prior_failures`: the gate stays
    pure, so a dry run and the real decision cannot answer differently
    because one of them happened to read the directory at a different moment.

    The same yaml the work would actually run under. `console/autoqueue.py`
    resolves a contract from the draft's declared paths at accept time and
    refuses when they fall outside it; this reads the same files so that the
    refusal happens before the money rather than after it.
    """
    root = contracts_dir or (Path(__file__).resolve().parent.parent
                             / "contracts")
    out: List[Tuple[str, List[str]]] = []
    for y in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(y.read_text()) or {}
        except Exception:                                     # noqa: BLE001
            continue
        if data.get("repo") != repo:
            continue
        out.append((y.name, [str(g) for g in
                             (data.get("writable_paths") or [])]))
    return out


def _glob_prefix(g: str) -> str:
    return g.split("*", 1)[0].rstrip("/")


def _inside(path: str, globs: Sequence[str]) -> bool:
    """The same prefix test console/autoqueue.py refuses with.

    Copied deliberately rather than imported: autoqueue imports db and would
    drag a writer-side module into the ranker. Eight lines, and a test asserts
    the two agree on the paths that matter -- which is the only property that
    makes a copy acceptable.
    """
    for g in globs:
        pre = _glob_prefix(g)
        if pre and (path == pre or path.startswith(pre + "/")):
            return True
    return False


def gate(candidate: Dict[str, Any], *,
         live_tasks: Sequence[Dict[str, Any]],
         prior_failures: int = 0,
         writables: Optional[Sequence[Tuple[str, Sequence[str]]]] = None,
         floor: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The seven gates, in order, ahead of the sort.

    NUMBERED 1, 3, 4, 5, 6, 7, 8. Gate 2 was removed on 13 Sep 2026 and the
    others keep their numbers, so a rule this file has not changed cannot
    read as a behaviour change in the brief -- the same argument gate 4 makes
    for staying behind gate 3. What gate 2 was reaching for now lives in
    supersede(), below, and runs AFTER these rather than among them.

    Returns {"eligible": bool, "rule": str|None, "detail": str|None, ...}.
    The first failure stops: the rule that held a row is the one printed in the
    brief, and reporting five of them for one row would bury it.

    `prior_failures`, `writables` and `floor` are all passed IN rather than
    read here, so this stays pure: the same inputs give the same answer, which
    is the property that makes a dry run worth reading.
    console/autoapprove.plan() reads `prior_failures` from
    `candidate_prior_failures(id)` -- the same function console/approve.py
    enforces with, so the dry run and the real decision cannot drift into two
    predicates that agree only until somebody edits one.

    `writables` and `floor` DEFAULT TO NONE AND THAT SKIPS GATES 5 AND 6.
    Not a convenience: a caller that does not supply them is asking a
    narrower question, and silently reading the contracts directory instead
    would make the answer depend on when it was asked.
    """
    # THE ARGUMENTS ARE CHECKED BEFORE THE GATES, and this is not defensive
    # programming for its own sake.
    #
    # On 11 Sep 2026 console/autoapprove.plan() passed the COVERAGE floor --
    # a float -- as `floor`, because two unrelated values in that function
    # were both called `floor`. Nothing noticed until gate 5 reached a
    # candidate that had paths: `[p for p in mine if _inside(p, floor)]`
    # evaluates `_inside` ZERO TIMES when `mine` is empty, so every test and
    # every earlier sweep ran the wrong argument all the way through and said
    # nothing. The first row with a path crashed the first live sweep.
    #
    # A wrong argument that is only wrong for some inputs is a wrong argument
    # every time it is passed. Checked HERE, once, at the boundary, so it
    # fails on the call rather than on the candidate.
    if floor is not None and isinstance(floor, (str, bytes, int, float)):
        raise TypeError(
            f"floor must be a sequence of globs from protected_path_floor, "
            f"not {type(floor).__name__} ({floor!r}). The coverage floor is a "
            f"different thing with a similar name; see "
            f"console/autoapprove.plan.")
    if writables is not None and isinstance(writables, (str, bytes, int, float)):
        raise TypeError(
            f"writables must be a sequence of (name, globs) pairs, not "
            f"{type(writables).__name__}")

    # 1. PENDING only, never NOT_NOW. A NOT_NOW is the only record of a human
    #    judgement about one specific candidate, and a machine that can overrule
    #    it leaves no veto short of editing code. It is also the cheapest
    #    correction available: one click, no deploy.
    if candidate.get("disposition") != "PENDING":
        return {"eligible": False, "rule": "not_pending",
                "detail": f"disposition is {candidate.get('disposition')}; "
                          f"NOT_NOW is a person's veto and the machine does not "
                          f"overrule it",
                "prior_failures": prior_failures}

    # 2. GONE, 13 Sep 2026. It held a candidate that was not in the newest
    #    producer batch, on the argument that "the newer batch re-verified
    #    these claims against a later sha".
    #
    #    THE ARGUMENT WAS FALSE FOR MOST OF THE ROWS IT HELD. On 13 Sep it
    #    held 16 of the 18 open rows, and SIX of those sixteen had never been
    #    superseded by any later row at all: c18, c24, c25, c26, c27, c30 name
    #    work no newer batch has ever mentioned. The gate told the brief that
    #    those claims had been re-verified. Nothing had re-verified them. The
    #    chain then ran four passes in a row approving nothing, because batch
    #    13 had six rows, five were already approved, and the sixth failed its
    #    premise -- so the newest batch was drained and everything else was
    #    shut behind it.
    #
    #    §9.11 found the same defect from the other side on 10 Sep and
    #    proposed the narrow fix: supersede on the SOURCE DOCUMENT rather than
    #    the batch id. THAT WOULD NOT HAVE WORKED EITHER, and it is worth
    #    writing down because it looks right. Every producer run writes its
    #    own findings file -- research/candidates-metorik-gap-2026-09-09.md,
    #    -09-10.md, -09-11.md -- so no two batches share a `source_document`
    #    and nothing would ever have superseded anything. The stable document
    #    is in `candidates.evidence` (specs/metorik-gap.md), not on the batch,
    #    which is exactly what console/work_key.py already resolves against.
    #
    #    BATCH AGE WAS ALWAYS A PROXY FOR "HAS THIS WORK BEEN DONE?", AND
    #    GATE 7 MEASURES THAT DIRECTLY. A probe re-executed at HEAD answers
    #    the question about this row, today. The proxy got it wrong in both
    #    directions on the live pool: c17, c23 and c32 were held as stale and
    #    their probes agree they are stale, so nothing was gained there; while
    #    c21 and c37 were held as superseded although BOTH gaps were still
    #    open in the platform checkout. Each of those two had a newer sibling
    #    approved -- c31 and c50 -- and in neither case did the work land:
    #    c31's tasks established refund coverage rather than surfacing net
    #    revenue, and c50's spec task 66 FAILED.
    #
    #    WHAT SUPERSESSION MEANS NOW: supersede(), applied after every gate.
    #    Two rows are a duplicate of one piece of work only once BOTH have
    #    proved themselves; until then the older one is not superseded, it is
    #    unexamined, and those are not the same thing.

    # 3. No overlap with a task that is not terminal.
    mine = [p for p in (candidate.get("suggested_paths") or [])]
    for task in live_tasks:
        theirs, source = declared_paths(task)
        hits = [(a, b) for a in mine for b in theirs if paths_overlap(a, b)]
        if hits:
            return {"eligible": False, "rule": "path_overlap",
                    "detail": f"names {hits[0][0]}, which {task['status'].lower()} "
                              f"task {task['id']} declares"
                              f"{'' if source == 'spec' else ' (via its contract, which is wide)'}",
                    "task_id": task["id"], "matched_via": source,
                    "paths": [list(h) for h in hits],
                    "prior_failures": prior_failures}

    # 4. THE REPEAT-FAILURE STOP, and it is a ceiling rather than a
    #    measurement. specs/unattended-operation.md §5.2 and 022: the same work
    #    has already been attempted unsuccessfully twice, and approving it
    #    again buys the same failure at the same price.
    #
    #    AHEAD OF THE PROBES because it is free and they are not -- gate 5
    #    re-executes predicates against two checkouts -- and BEHIND the overlap
    #    check because that is where it was: a row held by gate 3 today must
    #    keep reporting gate 3, or a rule change reads as a behaviour change in
    #    the brief. The count is attached to every result either way, including
    #    rows held earlier, so a reader can see it for a row this gate never
    #    reached.
    #
    #    IT WITHHOLDS THE AUTOMATIC APPROVAL, NEVER THE CANDIDATE. The row
    #    stays PENDING, appears in the brief with this rule, and a person may
    #    still tick it through the console by naming it in repeat_overrides
    #    with a reason. console/approve.py refuses those on the unattended
    #    path: an override is a person saying it is different this time, and
    #    there is no such sentence when nobody is there.
    if prior_failures >= REPEAT_FAILURE_STOP:
        return {"eligible": False, "rule": "repeat_failure",
                "detail": (f"materially the same work has already had "
                           f"{prior_failures} unsuccessful attempt(s), and the "
                           f"stop is {REPEAT_FAILURE_STOP}; approving it again "
                           f"buys the same failure at the same price"),
                "prior_failures": prior_failures}

    #: Set by gate 6 when the work needs more than one contract. Carried onto
    #: the result rather than refused: §12's chain is what makes it safe, and
    #: a reader still wants to know the row was split.
    spans: Dict[str, Any] = {}

    # 5. NO PATH THE FLEET MAY NEVER WRITE.
    #
    #    c35 is why this is a rule of its own rather than a case of gate 6.
    #    It names `api/analytics/migrations/versions/v0008_product_categories.py`,
    #    and `api/analytics/migrations/**` is on protected_path_floor. That is
    #    not "no single contract covers this work" -- it is work no contract
    #    can ever cover, and it is the same path class console/autodeploy.py
    #    refuses third, because deploy.sh migrates before the code swap and a
    #    migration is the one action here git does not make reversible.
    #
    #    Reported separately so the brief says which of the two it is. A row
    #    held for "spans two contracts" might be split into two candidates
    #    tomorrow; a row held for this one needs a person however it is cut.
    if floor is not None:
        mine = [p for p in (candidate.get("suggested_paths") or [])]
        blocked = [p for p in mine if _inside(p, floor)]
        if blocked:
            return {"eligible": False, "rule": "protected_path",
                    "detail": f"names {blocked[0]}, which is on the protected "
                              f"floor for {candidate.get('repo')}; no contract "
                              f"can make it writable, so this is not "
                              f"unattended work however it is scoped",
                    "paths": blocked,
                    "prior_failures": prior_failures}

    # 6. THE WORK MUST FIT INSIDE ONE CONTRACT.
    #
    #    A draft spec produces ONE task under ONE contract --
    #    console/autoqueue.from_accepted_draft reads a single `fleet-spec`
    #    block and resolves a single contract for it. The two contracts that
    #    matter here are strictly disjoint: dd_api writes only `api/**`, and
    #    dd_frontend writes only `platform/**`.
    #
    #    So a candidate whose work spans them cannot be built by one task, and
    #    nothing queues the second half. `tasks` has no dependency column,
    #    `claim_task` orders by (priority, id) alone, `work_key` identifies the
    #    GAP ROW rather than the half, and gate 3 releases the sibling the
    #    moment the first half reaches MERGED -- which is terminal -- so it
    #    returns to the pool as an ordinary row with no marker that it is now
    #    the missing half of something in production.
    #
    #    THIS HAPPENED. Task 28 merged the comparison-window backend on 9 Sep;
    #    task 49, the half that would have made it reachable, was queued BY
    #    HAND six hours later and failed; candidates 22 and 30 are still
    #    PENDING. It was caught by a person opening a page. Under the
    #    unattended chain the backend half would merge at 03:30 and deploy at
    #    04:15, and the morning page would render the thread ending "Running
    #    in production".
    #
    #    So this WITHHOLDS THE AUTOMATIC APPROVAL AND NOTHING ELSE, exactly as
    #    gate 4 does. The row stays PENDING and a person can still tick it in
    #    the console, having seen both halves. Twelve of the twenty open
    #    candidates are in this class on 10 Sep 2026; the fix that would let
    #    them run unattended is two tasks with an order between them, which is
    #    a real feature and is not this.
    if writables is not None:
        mine = [p for p in (candidate.get("suggested_paths") or [])]
        if mine:
            fits = [n for n, globs in writables
                    if all(_inside(p, globs) for p in mine)]
            if not fits:
                covered = {p: sorted(n for n, globs in writables
                                     if _inside(p, globs)) for p in mine}
                homeless = [p for p, n in covered.items() if not n]
                if homeless:
                    # A DIFFERENT FINDING AND SO A DIFFERENT RULE. "No
                    # contract covers this path" is not "the work spans two
                    # contracts": the first is usually a producer naming a
                    # directory (`api/analytics/routes`) or a file outside
                    # every boundary, and it is fixed by rewriting the
                    # candidate. The second is fixed by splitting the work or
                    # by giving tasks an order. Reporting them under one name
                    # would send the reader to the wrong repair.
                    return {"eligible": False, "rule": "unwritable_path",
                            "detail": (
                                f"names {homeless[0]}, which no contract on "
                                f"{candidate.get('repo')} makes writable"
                                + (f" (and {len(homeless) - 1} more)"
                                   if len(homeless) > 1 else "")
                                + ", so no task can be queued for it at all"),
                            "paths": homeless, "covered_by": covered,
                            "prior_failures": prior_failures}
                # SPANNING TWO CONTRACTS IS NO LONGER A REFUSAL, since
                # 11 Sep 2026 and specs/auto-approval.md §12.
                #
                # It was one because a draft spec produced ONE task under ONE
                # contract, so one half would ship and nothing would queue the
                # other -- task 28. A draft may now declare one fleet-spec
                # block per link, and console/automerge.eligible refuses to
                # merge any link until every link has verified, so the half
                # that used to ship alone cannot.
                #
                # WHAT STILL HAS TO GO RIGHT, AND WHERE IT IS CHECKED: the
                # draft must actually declare the chain.
                # contracts/checks/draft_spec_shape.py refuses a draft whose
                # blocks do not cover every path this candidate suggested, so
                # that failure lands on the DRAFT's verification -- before the
                # build money -- rather than here or at queue time.
                #
                # The split is recorded either way, so the brief can still say
                # what the work was cut into.
                best, left = None, mine
                for n, globs in writables:
                    rest = [p for p in mine if not _inside(p, globs)]
                    if len(rest) < len(left):
                        best, left = n, rest
                # RECORDED AND FALLEN THROUGH, NOT RETURNED. Returning
                # eligible here would skip gates 7 and 8 -- the probes and the
                # premise -- so a spanning candidate would be the one kind of
                # row whose claims were never re-executed. Caught by reading
                # the first draft of this change back; it is the shape of
                # every other gate that an early return is a REFUSAL.
                spans = {"spans_contracts": True, "paths": mine,
                         "covered_by": covered, "best_contract": best,
                         "not_covered": left}

    # 7. The probes still hold at the current HEAD.
    probes = check_probes(candidate)
    if not probes["ok"]:
        return {"eligible": False, "rule": "probes_failed",
                "detail": probes["why"], "probes": probes,
                "prior_failures": prior_failures, **spans}

    # 8. AND THE GROUND IS STILL THERE. Behind the probes rather than ahead of
    #    them, though both cost the same: a row whose gap has closed is not
    #    work at all, and reporting the premise for it would name the less
    #    important of two true things.
    premise = check_premise(candidate)
    if not premise["ok"]:
        return {"eligible": False,
                "rule": "premise_missing" if premise.get("missing")
                        else "premise_failed",
                "detail": premise["why"], "probes": probes,
                "premise": premise, "prior_failures": prior_failures, **spans}

    return {"eligible": True, "rule": None, "detail": None, "probes": probes,
            "premise": premise, "prior_failures": prior_failures, **spans}


def supersede(passed: Sequence[Dict[str, Any]]) -> Dict[int, str]:
    """Which rows that PASSED every gate are the same work as a newer row.

    Returns {candidate id: detail} for the rows to hold. An id absent from the
    result is kept. Pure, on the same argument gate() is: the dry run and the
    real decision must not be two predicates.

    NOT A GATE, AND THE POSITION IS THE WHOLE POINT. Gate 2 held a row because
    a newer BATCH existed, which said nothing about whether this work had been
    done -- see the note where gate 2 used to be. This runs last, over rows
    that have already proved themselves: probes re-executed at HEAD, ground
    still there, no live task on the path, under the repeat ceiling. Two rows
    that have each survived all of that and name the same row of the same
    findings document are a genuine duplicate, and approving both would buy
    the same work twice in one sweep.

    Before that point they are not duplicates. They are one examined row and
    one unexamined row, and shelving the unexamined one on the strength of the
    other is precisely the inference that shut the pool for four passes.

    ONLY `#row:` KEYS DEDUPLICATE. console/work_key.py returns a weaker
    `topic:` key when a heading is ambiguous, and is explicit about which way
    to fail: "Merging genuinely different work is the failure mode that costs
    money quietly; failing to merge is the failure mode that costs a ceiling
    one night and prints why." A topic key is stable only while the producer
    keeps quoting the heading the same way, so it does not get to call two
    rows the same work. The live pool has the pair this protects: c25 keys
    `topic:segment-any-resource-by-any-attribute-and-or-groups` and c33 keys
    `row:segment-any-resource-orders-customers-products-...`, which are almost
    certainly one gap row and are not provably one.

    NEWEST WINS, BY (batch, id). Not by rank: the two rows describe the same
    work, so whichever the producer wrote most recently is the one whose
    title, paths and probes were written against the most recent tree.
    """
    by_work: Dict[str, List[Dict[str, Any]]] = {}
    for row in passed:
        key = row.get("work_identity") or ""
        if "#row:" not in key:
            continue
        by_work.setdefault(key, []).append(row)

    held: Dict[int, str] = {}
    for key, group in by_work.items():
        if len(group) < 2:
            continue
        newest = max(group, key=lambda r: (r["batch_id"], r["id"]))
        for row in group:
            if row["id"] == newest["id"]:
                continue
            held[row["id"]] = (
                f"candidate {newest['id']} (batch {newest['batch_id']}) is the "
                f"same work -- {key.split('#', 1)[-1]} -- and is newer. Both "
                f"passed every gate, so this one is a duplicate rather than an "
                f"unexamined row; approving both would buy it twice")
    return held
