"""Every contract's base branch is a branch that exists.

specs/auto-approval.md §2.5 fixed this once, on 10 Sep 2026, for
console/approve.py and contracts/draft-spec.yaml — and wrote down that
contracts/research.yaml and contracts/research-metorik-gap.yaml still carried
`track-2-foundation`, left deliberately because "the local refs are the same
commit today".

That was true when it was written. By 11 Sep master was **53 commits ahead** of
track-2-foundation and the branch was 0 ahead of master, and the cost had
arrived: task 60 was built against a stale tree, the console could not accept
it because the base kept moving underneath, and two tasks were merged by hand.

A NOTE IS NOT A MECHANISM. The earlier sweep knew about these two and said so
in prose, in a spec section about a different fix. This asks git instead, of
every contract, so the next branch rename fails here rather than in a run.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
REPOS = ROOT.parent          # /home/ubuntu — fleet and the platform sit here

CONTRACTS = sorted((ROOT / "contracts").glob("*.yaml"))


def _contract(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _branch_exists(repo: Path, branch: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
         f"refs/heads/{branch}"],
        capture_output=True).returncode == 0


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.name)
def test_the_base_branch_exists_in_the_repo_it_names(path):
    d = _contract(path)
    base, repo = d.get("base_branch"), d.get("repo")
    if not base or not repo:
        pytest.skip(f"{path.name} names no base_branch or repo")
    checkout = REPOS / repo
    if not (checkout / ".git").exists():
        pytest.skip(f"{repo} is not a checkout on this host")
    assert _branch_exists(checkout, base), (
        f"{path.name} names base_branch '{base}', which does not exist in "
        f"{repo}. A task's base branch is immutable once the row exists, so a "
        f"wrong one here cannot be edited out — the task has to be abandoned.")


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.name)
def test_the_base_branch_is_not_behind_the_trunk(path):
    """Existing is not enough, and this is the half the note got wrong.

    `track-2-foundation` existed the whole time. What changed is that master
    moved and it did not, so a task cutting from it built against a tree four
    commits stale and the console refused the merge because the base kept
    moving underneath. A branch that is behind the trunk is a base that will
    produce exactly that.
    """
    d = _contract(path)
    base, repo = d.get("base_branch"), d.get("repo")
    if not base or not repo:
        pytest.skip(f"{path.name} names no base_branch or repo")
    checkout = REPOS / repo
    if not (checkout / ".git").exists() or not _branch_exists(checkout, base):
        pytest.skip(f"{repo}/{base} is not readable here")
    trunks = [t for t in ("master", "main") if _branch_exists(checkout, t)]
    assert trunks, f"{repo} has neither master nor main"
    trunk = trunks[0]
    if base == trunk:
        return
    behind = subprocess.run(
        ["git", "-C", str(checkout), "rev-list", "--count", f"{base}..{trunk}"],
        capture_output=True, text=True).stdout.strip()
    assert behind == "0", (
        f"{path.name} bases work on '{base}', which is {behind} commit(s) "
        f"behind '{trunk}' in {repo}. Work cut from it is stale before it "
        f"starts, and its merge is judged against a base that keeps moving.")


def test_no_contract_still_names_the_retired_branch():
    """Named rather than left to the general rule, because this one has now
    cost a rebuild, a refused accept and two hand merges."""
    stale = [p.name for p in CONTRACTS
             if _contract(p).get("base_branch") == "track-2-foundation"]
    assert stale == [], (
        f"{stale} still base work on track-2-foundation, retired 9 Sep 2026 "
        f"when master became the trunk")
