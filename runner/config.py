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
from typing import Any

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

    # The database refuses this too. Catching it here means the message names
    # the file rather than the trigger.
    clashes = [
        f"{w} overlaps {p}"
        for w in contract["writable_paths"]
        for p in contract["protected_paths"]
        if glob_prefix(w) and glob_prefix(p)
        and (glob_prefix(w) == glob_prefix(p)
             or glob_prefix(p).startswith(glob_prefix(w) + "/")
             or glob_prefix(w).startswith(glob_prefix(p) + "/"))
    ]
    if clashes:
        raise RuntimeError(f"{path} contradicts itself: {'; '.join(clashes)}")

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
