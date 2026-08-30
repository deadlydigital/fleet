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

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from runner.boundary import git, GitError


class PushRefused(RuntimeError):
    """Raised rather than pushing something that would not be a task branch."""


@dataclass
class Untouched:
    """A checkout's state, so that "the runner did not touch it" is checkable.

    `tree_digest` covers EVERY file, not only tracked ones. A write to an
    untracked path -- inside node_modules, into a gitignored directory, a new
    file nobody added -- shows in neither `rev-parse HEAD` nor `status
    --porcelain`, so a comparison built on those two would report a repository
    as untouched while something had been written into it.

    It is a digest of (path, size, mtime_ns) rather than of contents: 65,767
    files and 1.3 GB in the platform checkout, walked in about a tenth of a
    second, where hashing the bytes would take minutes on every tick. A write
    that preserved a file's size AND its nanosecond mtime would slip through;
    that is a deliberate trade and it is written down rather than left to be
    discovered.
    """
    head: str
    porcelain: str
    tree_digest: str
    file_count: int

    @staticmethod
    def _digest(repo: Path) -> tuple[str, int]:
        """Streamed, not collected: rglob into a sorted list costs seconds on a
        65k-file checkout and this runs twice per tick."""
        h = hashlib.sha256()
        n = 0
        root = str(repo)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # .git is excluded, and not as an optimisation. Taking a snapshot
            # runs `git status`, which refreshes .git/index and changes its
            # mtime -- so two consecutive snapshots of an untouched repository
            # would differ and every tick would report tampering. Git's own
            # state is already covered by HEAD and porcelain; this digest is
            # about the working tree.
            if ".git" in dirnames:
                dirnames.remove(".git")
            dirnames.sort()
            rel_dir = os.path.relpath(dirpath, root)
            for name in sorted(filenames):
                try:
                    st = os.lstat(os.path.join(dirpath, name))
                except OSError:
                    continue
                if not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
                    continue
                n += 1
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n"
                         .encode("utf-8", "surrogateescape"))
        return h.hexdigest(), n

    @classmethod
    def of(cls, repo: Path) -> "Untouched":
        digest, count = cls._digest(repo)
        return cls(head=git(repo, "rev-parse", "HEAD").strip(),
                   porcelain=git(repo, "status", "--porcelain").strip(),
                   tree_digest=digest, file_count=count)

    def assert_unchanged(self, repo: Path, what: str) -> None:
        now = Untouched.of(repo)
        if now.head != self.head:
            raise GitError(f"{what} moved from {self.head[:12]} to {now.head[:12]}")
        if now.porcelain != self.porcelain:
            raise GitError(f"{what} has uncommitted changes it did not have before")
        if now.tree_digest != self.tree_digest:
            raise GitError(
                f"{what} changed on disk without git seeing it: "
                f"{self.file_count} files before, {now.file_count} after. "
                f"Something was written to an untracked or ignored path.")


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


def has_remote(repo: Path, remote: str = "origin") -> bool:
    """Whether there is anywhere to push.

    ~/fleet has no remote. A research task produces a document on a local
    branch and that IS the artifact; treating the absent remote as a failure
    would report a successful run as a broken one.
    """
    return bool(git(repo, "remote", check=False).split())


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


def link_dependencies(worktree: Path, links: dict[str, str]) -> list[Path]:
    """Symlink installed dependencies into the worktree, for verification only.

    `node_modules` and `.venv` are gitignored, so a fresh worktree has
    neither, and the frontend's tsc and vitest cannot run without the first.
    Copying gigabytes per task is not an option and `npm ci` per task is
    slower than the tests it enables, so the runner points at the checkout's
    own installed tree.

    **Timing is the safety property, not the symlink.** The caller creates
    these AFTER the diff has been derived and the boundary judged, so the
    agent never sees them. That matters: a write through this link would land
    outside the worktree's git index entirely -- not merely in an ignored
    path -- and the derived diff would show nothing at all. Creating it before
    the agent ran would open a hole no later check could close.

    Refuses a target outside the worktree, and refuses to replace anything
    that already exists.
    """
    created: list[Path] = []
    root = worktree.resolve()
    for target, source in (links or {}).items():
        dest = (worktree / target).resolve()
        if not str(dest).startswith(str(root) + "/"):
            raise GitError(f"worktree link {target!r} resolves outside the worktree")
        src = Path(source)
        if not src.exists():
            raise GitError(f"worktree link source {source} does not exist")
        if dest.exists() or dest.is_symlink():
            raise GitError(f"worktree link {target!r} already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(src)
        created.append(dest)
    return created


def unlink_dependencies(created: list[Path]) -> None:
    """Remove what link_dependencies made, and only that.

    Each entry is unlinked rather than deleted recursively: following one of
    these into the checkout's real node_modules with rmtree would delete the
    dependencies of the repository itself.
    """
    for path in created:
        if path.is_symlink():
            path.unlink()
