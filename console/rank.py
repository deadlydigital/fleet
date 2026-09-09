"""Ordering open candidates, and refusing to order them when nothing separates.

specs/auto-approval.md §2.2. A pure `rank()` over four gates, and the gates are
not part of the ranking: a candidate that fails one is not rejected and not
marked -- it is simply not approved by the machine, stays PENDING, and appears
in the morning brief with the rule that held it. That is the shape
specs/unattended-operation.md §5.2 already chose for the repeat stop: withhold
the automatic approval, never the candidate.

WHAT RANKS, AND WHAT DELIBERATELY DOES NOT
-------------------------------------------
Three keys: the work class read off the probes, the band, the candidate id.

COST DOES NOT RANK. Every draft-spec task reserves the same £2.00 from
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
from typing import Any, Dict, List, Sequence

from . import config

#: Bumped when any key changes meaning or order. Recorded on every decision, so
#: last week's batches stay attributable to the ranking that made them instead
#: of being silently re-explained by this week's.
RANK_VERSION = 1

#: Key 1's three classes, lower first.
FRONTEND_ONLY, MODIFY, CREATE = 0, 1, 2

CLASS_NAMES = {FRONTEND_ONLY: "frontend-only", MODIFY: "modify", CREATE: "create"}

#: Key 2. A NULL band sorts last and does not gate.
BAND_ORDER = {"daily": 0, "weekly": 1, "monthly": 2, "rarely": 3}
NO_BAND = 4

#: Gate 3 looks at every task that is not terminal. A task in any of these
#: states may still write the files it declared.
LIVE_TASK_STATES = ("QUEUED", "CLAIMED", "RUNNING", "READY_FOR_REVIEW")

SPEC_BLOCK_RE = re.compile(r"```fleet-spec\s*\n(.*?)\n```", re.S)


@functools.lru_cache(maxsize=1)
def _shape_check():
    """contracts/checks/candidate_block_shape.py, imported rather than copied.

    run_probe() is the whole reason gate 4 is cheap: it exists, it is pure
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


def rank(candidate: Dict[str, Any]) -> tuple:
    """The sort key. Lower sorts first. PURE -- no database, no filesystem.

    Pure so that a dry run means something: the same inputs give the same
    order, every night, and a change in the output is a change in the inputs
    rather than in the weather.
    """
    klass, _ = work_class(candidate.get("probes") or [])
    band = BAND_ORDER.get(candidate.get("band"), NO_BAND)
    return (klass, band, candidate["id"])


def key_values(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """The keys, named, for the record and the dry run."""
    klass, why = work_class(candidate.get("probes") or [])
    return {
        "key1_class": CLASS_NAMES[klass],
        "key1_why": why,
        "key2_band": candidate.get("band"),
        "key3_id": candidate["id"],
        "sort_key": [klass, BAND_ORDER.get(candidate.get("band"), NO_BAND),
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
    """The sha gate 4 re-executes against. Recorded on every decision."""
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
    """GATE 4. Re-execute the stored predicates against the tree as it is now.

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


def gate(candidate: Dict[str, Any], *, newest_batch: int,
         live_tasks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The four gates, in order, ahead of the sort.

    Returns {"eligible": bool, "rule": str|None, "detail": str|None, ...}.
    The first failure stops: the rule that held a row is the one printed in the
    brief, and reporting four of them for one row would bury it.
    """
    # 1. PENDING only, never NOT_NOW. A NOT_NOW is the only record of a human
    #    judgement about one specific candidate, and a machine that can overrule
    #    it leaves no veto short of editing code. It is also the cheapest
    #    correction available: one click, no deploy.
    if candidate.get("disposition") != "PENDING":
        return {"eligible": False, "rule": "not_pending",
                "detail": f"disposition is {candidate.get('disposition')}; "
                          f"NOT_NOW is a person's veto and the machine does not "
                          f"overrule it"}

    # 2. The newest batch only. Batch 9 re-verified batch 8's rows against a
    #    newer sha, so an older row is superseded by construction -- and rows
    #    left behind from an older batch are exactly the repetition
    #    specs/approval-surface.md §5 wants a person to look at.
    if candidate.get("batch_id") != newest_batch:
        return {"eligible": False, "rule": "older_batch",
                "detail": f"batch {candidate.get('batch_id')}, and the newest "
                          f"is {newest_batch}; the newer batch re-verified "
                          f"these claims against a later sha"}

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
                    "paths": [list(h) for h in hits]}

    # 4. The probes still hold at the current HEAD.
    probes = check_probes(candidate)
    if not probes["ok"]:
        return {"eligible": False, "rule": "probes_failed",
                "detail": probes["why"], "probes": probes}

    return {"eligible": True, "rule": None, "detail": None, "probes": probes}
