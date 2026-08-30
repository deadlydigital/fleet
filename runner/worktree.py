"""Worktrees, and the guards around the one outward-facing thing this does.

A worktree rather than a clone, so the repository is not duplicated per task
and the working tree you have open is never touched. The runner asserts that
second part rather than assuming it: `Untouched` snapshots the main checkout
before the agent runs and compares afterwards, because an agent with a shell
is an agent that can leave the worktree.

Pushing is the only action here that leaves the machine. It refuses to push
the base branch, refuses to force, and names an explicit refspec, so the
worst outcome of a bug in this file is a branch nobody asked for rather than
a rewritten main.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from runner.boundary import git, GitError


class PushRefused(RuntimeError):
    """Raised rather than pushing something that would not be a task branch."""


@dataclass
class Untouched:
    """A checkout's state, so that "the runner did not touch it" is checkable."""
    head: str
    porcelain: str

    @classmethod
    def of(cls, repo: Path) -> "Untouched":
        return cls(head=git(repo, "rev-parse", "HEAD").strip(),
                   porcelain=git(repo, "status", "--porcelain").strip())

    def assert_unchanged(self, repo: Path, what: str) -> None:
        now = Untouched.of(repo)
        if now.head != self.head:
            raise GitError(f"{what} moved from {self.head[:12]} to {now.head[:12]}")
        if now.porcelain != self.porcelain:
            raise GitError(f"{what} has uncommitted changes it did not have before")


def branch_name(task_id: int, attempt: int) -> str:
    return f"fleet/task-{task_id}" + (f".{attempt}" if attempt > 1 else "")


def create(repo: Path, root: Path, branch: str, base_branch: str) -> tuple[Path, str]:
    """A fresh branch off the base, in its own worktree.

    The base sha is resolved once and returned. Everything downstream compares
    against that sha rather than against the branch name, so a base that moves
    mid-run cannot silently change what "the diff" means.
    """
    base_sha = git(repo, "rev-parse", base_branch).strip()
    path = root / branch.replace("/", "-")
    if path.exists():
        shutil.rmtree(path)
    git(repo, "worktree", "add", "--quiet", "-b", branch, str(path), base_sha)
    return path, base_sha


def remove(repo: Path, path: Path, keep_branch: bool = True) -> None:
    git(repo, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git(repo, "worktree", "prune", check=False)


def delete_branch(repo: Path, branch: str) -> None:
    git(repo, "branch", "-D", branch, check=False)


def push(repo: Path, branch: str, base_branch: str, remote: str = "origin") -> str:
    """Push the task branch, and nothing else.

    Three refusals rather than one, because each is a different mistake:
    pushing the base branch is a merge by another name, force is a rewrite,
    and an empty branch name is a bug that would otherwise become a refspec
    the remote interprets generously.
    """
    # Base branch first: it is the refusal that matters most, and checking
    # the name shape first would report "main" as a malformed branch name
    # rather than as the thing this runner must never push.
    if branch == base_branch:
        raise PushRefused(
            f"refusing to push {branch}: that is the base branch, and this "
            f"runner never merges")
    if not branch or "/" not in branch:
        raise PushRefused(f"{branch!r} is not a task branch name")
    out = git(repo, "push", "--set-upstream", remote,
              f"refs/heads/{branch}:refs/heads/{branch}")
    return out.strip()
