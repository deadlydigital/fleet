"""Connections and contracts for the task runner.

Four DSNs, because the track rests on four identities that must not be one:

  FLEET_CONSOLE_DSN       writes the queue and records every reviewed state.
                          The CLI is this, and only this.
  FLEET_TASK_RUNNER_DSN   claims tasks and moves them between machine states.
                          It cannot insert a task and cannot review one.
  FLEET_AGENT_DSN         writes PATCH_PROPOSED.
  FLEET_VERIFIER_DSN      writes VERIFICATION_RUN.

The last two are separate for the reason 001's step_authority table exists:
the thing that proposes a diff must not be the thing that certifies it. The
runner process holds both, but not on the same connection, so the database
records which identity wrote which step.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

import yaml

from detectors import config as base_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = PROJECT_ROOT / "contracts"


def console_dsn() -> str:
    """The queue is written by a person. This is that person's identity."""
    return base_config.require("FLEET_CONSOLE_DSN")


def task_runner_dsn() -> str:
    return base_config.require("FLEET_TASK_RUNNER_DSN")


def agent_dsn() -> str:
    return base_config.require("FLEET_AGENT_DSN")


def verifier_dsn() -> str:
    return base_config.require("FLEET_VERIFIER_DSN")


REQUIRED_CONTRACT_KEYS = ("work_type", "repo", "base_branch", "writable_paths",
                          "protected_paths", "verification", "max_diff_lines")


def glob_prefix(glob: str) -> str:
    """The fixed leading part of a glob.

    The same derivation as glob_prefix() in 003_tasks.sql, because the two
    must agree: the database refuses a contract whose writable and protected
    sets overlap, and the runner matches a derived diff against the same
    prefixes. Two different notions of "does this path fall under that glob"
    would let a file be writable to one and protected to the other.
    """
    return re.sub(r"\*.*$", "", glob).rstrip("/")


def load_contract(repo: str, path: Path | None = None) -> dict[str, Any]:
    """The contract for a repo: an explicit file, or the repo's default.

    THERE IS NO LONGER A DEFAULT FOR deadly-digital-platform, AND THAT IS THE
    POINT. contracts/deadly-digital-platform.yaml was it, and it declared
    platform/app/**, platform/components/** and platform/lib/** writable --
    reaching lib/auth.ts, lib/roles.ts, lib/csrf.ts, the impersonation route
    and the billing checkout route. It was deleted rather than narrowed in the
    same change as 023_platform_floor.sql.

    A default contract is the one nobody has to choose, so it is the one a task
    gets by omission. The narrow contracts are per-piece-of-work and each is
    named on the command line; falling back to a wide one when no name is given
    is the opposite of that. So the fallback is kept -- a repo may still have a
    <repo>.yaml -- and its absence is reported as a thing to decide rather than
    as a missing file.
    """
    default = path is None
    path = path or CONTRACT_DIR / f"{repo}.yaml"
    if not path.exists():
        if default:
            available = sorted(
                p.name for p in CONTRACT_DIR.glob("*.yaml")
                if (yaml.safe_load(p.read_text()) or {}).get("repo") == repo)
            raise RuntimeError(
                f"{repo} has no default contract at {path}, and that is "
                f"deliberate: the wide one was deleted with 023_platform_floor"
                f".sql. Name the contract this task is scoped to with "
                f"--contract. For this repo: "
                + (", ".join(available) if available else "none found"))
        raise RuntimeError(f"no acceptance contract at {path}")
    contract = yaml.safe_load(path.read_text())
    if not isinstance(contract, dict):
        raise RuntimeError(f"{path} is not a mapping")

    missing = [k for k in REQUIRED_CONTRACT_KEYS if k not in contract]
    if missing:
        raise RuntimeError(f"{path} is missing {', '.join(missing)}")
    if contract["repo"] != repo:
        raise RuntimeError(
            f"{path} declares repo {contract['repo']!r}, asked for {repo!r}")
    if not contract["verification"]:
        raise RuntimeError(f"{path} declares no verification commands")

    # A CONTRACT THAT MANDATES A TEST MUST BUDGET FOR IT
    #
    # creatable_paths is what lets the agent add a test, and new_test_bites.sh
    # is what makes that test mean something. Before 11 Sep 2026 the lines it
    # costs came out of max_diff_lines, so the two ceilings competed and the
    # test lost: both dd_api tasks refused on size were ordinary changes whose
    # mandated test pushed them over. Declaring the permission without the
    # allowance recreates that exactly, and silently, so it is refused here
    # rather than discovered again in a run that has already been paid for.
    if contract.get("creatable_paths") and not contract.get("max_test_diff_lines"):
        raise RuntimeError(
            f"{path} declares creatable_paths but no max_test_diff_lines. A "
            f"contract that requires an added test must give it its own "
            f"budget, or the test competes with the change it is testing for "
            f"room under max_diff_lines.")

    # AND THE FIGURE THE AGENT IS ACTUALLY TOLD.
    #
    # 12 Sep 2026: max_test_diff_lines stopped being the number in the prompt
    # and became a runaway bound sitting far above any plausible test. What
    # shapes the test now is test_diff_target, and a contract that mandates a
    # test without one sends the agent at that bound -- an anchor three times
    # the figure anyone wants, which is the failure this whole pair of fields
    # exists to have stopped happening. Same shape as the rule above, for the
    # same reason: the combination IS the defect, so it is refused here rather
    # than found in a run that has already been paid for.
    # A LINK DECLARED READ-ONLY MUST BE A LINK.
    #
    # `read_only_links` opts a worktree_link out of the write probe by naming
    # its target. A typo names nothing, the opt-out silently does not apply, and
    # the contract is back to refusing an accept for a write nobody makes --
    # with a file that says it should not. Refused here, where the message can
    # name both lists, rather than found in a run that has been paid for.
    unknown = (set(contract.get("read_only_links") or [])
               - set(contract.get("worktree_links") or {}))
    if unknown:
        raise RuntimeError(
            f"{path} declares read_only_links {sorted(unknown)} which are not "
            f"worktree_links. The names must match exactly: an entry that "
            f"matches nothing is an opt-out that does not apply.")

    if contract.get("creatable_paths") and not contract.get("test_diff_target"):
        raise RuntimeError(
            f"{path} declares creatable_paths but no test_diff_target. "
            f"max_test_diff_lines is a runaway bound and is never shown to the "
            f"agent; test_diff_target is the figure the prompt carries, and "
            f"without it the prompt would anchor on the bound.")

    # The database refuses this too. Catching it here means the message names
    # the file rather than the trigger.
    #
    # `floor_waiver` IS THE ONE EXCEPTION, AND IT IS NOT SELF-AUTHORISING.
    #
    # 040 lets exactly one floor row be waived for exactly one work_type, so
    # that an index migration can be written where nothing else may write. The
    # contract names the glob it is exempt from, HERE, so the hole is visible
    # in the file that has it rather than only in a column of a table.
    #
    # Naming it grants nothing. `enforce_contract_floor()` refuses the contract
    # unless `protected_path_floor` really does waive that glob for this
    # work_type, so a contract that declares a waiver it was not given is
    # refused at the database with the declaration as the evidence. This mirror
    # exists to name the file, exactly as the comment above says; it is not the
    # authority and must not be read as one.
    waived = contract.get("floor_waiver")
    clashes = [
        f"{w} overlaps {p}"
        for w in contract["writable_paths"]
        for p in contract["protected_paths"]
        if p != waived
        and glob_prefix(w) and glob_prefix(p)
        and (glob_prefix(w) == glob_prefix(p)
             or glob_prefix(p).startswith(glob_prefix(w) + "/")
             or glob_prefix(w).startswith(glob_prefix(p) + "/"))
    ]
    if clashes:
        raise RuntimeError(f"{path} contradicts itself: {'; '.join(clashes)}")

    if waived and waived not in contract["protected_paths"]:
        raise RuntimeError(
            f"{path} declares floor_waiver {waived!r} and does not carry it in "
            f"protected_paths. The waiver narrows a protected glob; dropping "
            f"the glob would exempt the contract from everything under it "
            f"rather than from the one path its writable_paths names.")

    return contract


RUNNER_CONFIG_PATH = PROJECT_ROOT / "runner.yaml"


def model_gateway_dsn() -> str:
    """reserve_model_budget / settle_model_budget are granted to
    fleet_model_gateway and to nothing else. The runner invoking a model is
    acting as that gateway, so it connects as one."""
    return base_config.require("FLEET_MODEL_GATEWAY_DSN")


def load_runner_config(path: Path | None = None) -> dict[str, Any]:
    import os
    path = path or Path(os.environ.get("FLEET_RUNNER_CONFIG", RUNNER_CONFIG_PATH))
    if not path.exists():
        raise RuntimeError(f"runner configuration missing: {path}")
    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} is not a mapping")
    for key in ("worktree_root", "repo_root", "remote", "agent_tools",
                "usd_to_gbp"):
        if key not in loaded:
            raise RuntimeError(f"{path} is missing {key}")
    return loaded


class WaiverNotGranted(RuntimeError):
    """A contract named a floor waiver the floor did not grant it."""


def effective_contract(contract: dict[str, Any],
                       floor: Sequence[tuple[str, str, str | None]]) -> dict[str, Any]:
    """The contract as the boundary check must see it, given the floor.

    `floor` is (repo, glob, except_work_type) rows from `protected_path_floor`,
    passed in rather than fetched. This is console/rank.gate's argument, and
    the same one: a checker that reaches for a table decides what it can reach,
    and it cannot then be exercised without one.

    WHAT THIS RESOLVES. 040 lets one floor row be waived for one work_type, so
    that an index migration can be written where nothing else may. The contract
    still CARRIES that glob in `protected_paths` -- dropping it would exempt
    the task from everything under the tree rather than from the one path its
    `writable_paths` names -- so `boundary.enforce`, which reads only the
    contract, sees a protected path and refuses. That was task 98.

    So the waived glob is removed HERE, once, and `boundary.enforce` stays a
    pure function over (change, contract) that needs to know nothing about any
    of this.

    WHAT STILL BOUNDS IT, because removing a protected glob sounds wider than
    it is: `writable_paths`. The index contract may write
    `api/analytics/migrations/versions/v*.py` and nothing else, so a write to
    `migrations/__init__.py` falls through to `outside_writable` and is
    refused. The machinery -- migration.py, runner.py, predicates.py -- is
    listed in `protected_paths` in its own right, not inherited from the glob,
    so it stays protected after the glob is gone. A contract that relied on the
    glob to protect the machinery would be widened by this; that is why the
    index contract does not.

    BOTH QUESTIONS, NEITHER ASSUMED. Is this row waived for this work_type, and
    does the contract name it. A declaration the floor does not grant raises
    rather than being ignored: ignoring it would mean a contract could be
    stored declaring one thing and judged under another, and the difference
    would be invisible in both places.
    """
    declared = contract.get("floor_waiver")
    if not declared:
        return contract

    wtype = contract.get("work_type")
    repo = contract.get("repo")
    granted = any(f_repo == repo and glob == declared
                  and except_wt is not None and except_wt == wtype
                  for f_repo, glob, except_wt in floor)
    if not granted:
        raise WaiverNotGranted(
            f"contract for {repo} declares floor_waiver {declared!r}, which the "
            f"floor does not grant to work_type {wtype!r}. A waiver is granted "
            f"by protected_path_floor and named by the contract, and both must "
            f"be true. The database refuses this too since 041; reaching here "
            f"means the row predates it or the floor has changed under a task "
            f"already queued.")

    effective = dict(contract)
    effective["protected_paths"] = [p for p in contract.get("protected_paths", [])
                                    if p != declared]
    #: Recorded so a verdict that depended on the floor can be reconstructed
    #: from the run alone. A check whose answer turns on a table it did not
    #: read, and did not record reading, is a check nobody can audit
    #: afterwards -- see principles.md.
    effective["floor_waiver_applied"] = declared
    return effective
