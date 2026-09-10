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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from runner.boundary import git, GitError


class PushRefused(RuntimeError):
    """Raised rather than pushing something that would not be a task branch."""


@dataclass
class Untouched:
    """A checkout's state, so that "the runner did not touch it" is checkable.

    The snapshot covers EVERY file, not only tracked ones. A write to an
    untracked path -- inside node_modules, into a gitignored directory, a new
    file nobody added -- shows in neither `rev-parse HEAD` nor `status
    --porcelain`, so a comparison built on those two would report a repository
    as untouched while something had been written into it.

    It records (path, size, mtime_ns) per file rather than hashing contents:
    63,395 files and 1.3 GB in the platform checkout, walked in 0.65s, where
    hashing the bytes would take minutes on every tick. A write that preserved
    a file's size AND its nanosecond mtime would slip through; that is a
    deliberate trade and it is written down rather than left to be discovered.

    WHAT IS DELIBERATELY NOT WATCHED, AND WHY IT HAD TO BECOME AN ARGUMENT
    ----------------------------------------------------------------------
    `exclude` takes the SOURCE paths of the contract's `worktree_links`, and
    task 49 is why. That task passed every check it had -- tsc, vitest, the
    bite check, paired_paths -- pushed its branch, and was then failed by this
    guard because vitest had written 131 bytes to

        platform/node_modules/.vite/vitest/results.json

    inside the very checkout being watched. `link_dependencies` had pointed the
    worktree's `platform/node_modules` at the real one, because copying
    gigabytes per task is not an option, and verification then ran THROUGH that
    link. Its docstring argues "timing is the safety property... the agent
    never sees them", which is true of the agent and silent about verification,
    which runs after the links exist.

    The two features had been in collision since 30 Aug 13:35, when the task's
    own repo joined the watch list four hours after the only previous frontend
    task finished. Task 49 was the first task to meet both.

    So a write to a linked dependency tree is EXPECTED rather than tampering:
    the runner put the link there and pointed a test runner at it. Excluding it
    keeps the guard's real job -- catching a write the AGENT made outside its
    worktree, where the derived diff would show nothing at all.

    The exclusions are recorded on the snapshot and reused by
    assert_unchanged, so before and after are always compared over the same
    ground, and they are NAMED IN THE ERROR: an exclusion that hides a real
    write must be visible to whoever reads the failure.
    """
    head: str
    porcelain: str
    tree_digest: str
    file_count: int
    #: rel path -> (size, mtime_ns). Kept, not only hashed, so a failure can
    #: say WHICH file moved. Task 49's error said "63395 files before, 63395
    #: after" -- two identical numbers offered as evidence, because the count
    #: is incidental to a digest over size and mtime. That is a reporting
    #: defect independent of the guard, and it is why the failure sat unread
    #: for a day. The map costs 0.65s and ~2 MiB, the same walk as the hash.
    entries: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Absolute, resolved. Recorded so the check cannot use a different set
    #: from the snapshot, which would be a guard that reports its own drift.
    excluded: tuple[str, ...] = ()

    @staticmethod
    def _digest(repo: Path, excluded: tuple[str, ...] = ()
                ) -> tuple[str, int, dict[str, tuple[int, int]]]:
        """One os.walk. Streamed into the map; nothing is collected and sorted
        afterwards, which is what would cost seconds on a 63k-file checkout."""
        h = hashlib.sha256()
        entries: dict[str, tuple[int, int]] = {}
        root = str(repo.resolve())
        skip = set(excluded)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # .git is excluded, and not as an optimisation. Taking a snapshot
            # runs `git status`, which refreshes .git/index and changes its
            # mtime -- so two consecutive snapshots of an untouched repository
            # would differ and every tick would report tampering. Git's own
            # state is already covered by HEAD and porcelain; this digest is
            # about the working tree.
            if ".git" in dirnames:
                dirnames.remove(".git")
            # Pruned by full path, and only ever a CHILD -- os.walk yields the
            # root before its children, so an exclusion naming the repo root
            # matches nothing and cannot silently switch the whole guard off.
            dirnames[:] = [d for d in sorted(dirnames)
                           if os.path.join(dirpath, d) not in skip]
            rel_dir = os.path.relpath(dirpath, root)
            for name in sorted(filenames):
                try:
                    st = os.lstat(os.path.join(dirpath, name))
                except OSError:
                    continue
                if not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
                    continue
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                entries[rel] = (st.st_size, st.st_mtime_ns)
                h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n"
                         .encode("utf-8", "surrogateescape"))
        return h.hexdigest(), len(entries), entries

    @classmethod
    def of(cls, repo: Path, exclude: Sequence[str | Path] = ()) -> "Untouched":
        excluded = tuple(sorted({str(Path(p).resolve()) for p in exclude or ()}))
        digest, count, entries = cls._digest(repo, excluded)
        return cls(head=git(repo, "rev-parse", "HEAD").strip(),
                   porcelain=git(repo, "status", "--porcelain").strip(),
                   tree_digest=digest, file_count=count,
                   entries=entries, excluded=excluded)

    def _what_moved(self, now: "Untouched", limit: int = 5) -> str:
        """The filenames, which is what a person needs to act on this."""
        added = sorted(set(now.entries) - set(self.entries))
        removed = sorted(set(self.entries) - set(now.entries))
        changed = sorted(p for p in set(self.entries) & set(now.entries)
                         if self.entries[p] != now.entries[p])
        parts = []
        for label, paths in (("added", added), ("removed", removed),
                             ("modified", changed)):
            if not paths:
                continue
            shown = paths[:limit]
            detail = []
            for p in shown:
                if label == "modified":
                    was, now_ = self.entries[p], now.entries[p]
                    how = (f"{was[0]} -> {now_[0]} bytes" if was[0] != now_[0]
                           else f"{was[0]} bytes, mtime moved")
                    detail.append(f"{p} ({how})")
                else:
                    detail.append(p)
            more = f" and {len(paths) - limit} more" if len(paths) > limit else ""
            parts.append(f"{len(paths)} {label}: {'; '.join(detail)}{more}")
        return ". ".join(parts) if parts else "no file differs, which should be impossible here"

    def assert_unchanged(self, repo: Path, what: str) -> None:
        now = Untouched.of(repo, self.excluded)
        if now.head != self.head:
            raise GitError(f"{what} moved from {self.head[:12]} to {now.head[:12]}")
        if now.porcelain != self.porcelain:
            raise GitError(f"{what} has uncommitted changes it did not have before")
        if now.tree_digest != self.tree_digest:
            # NAMED, not counted. The count is incidental to a digest over size
            # and mtime, and printing it as though it were the evidence is what
            # made task 49's failure unreadable.
            skipped = (f" Not watched, because the contract links them and "
                       f"verification runs through them: "
                       f"{', '.join(self.excluded)}." if self.excluded else "")
            raise GitError(
                f"{what} changed on disk without git seeing it. "
                f"{self._what_moved(now)}. Something was written to an "
                f"untracked or ignored path.{skipped}")


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


def create_trial_clone(repo: Path, root: Path, name: str, at: str) -> tuple[Path, str]:
    """A throwaway CLONE at a commit, for a merge that must leave no trace.

    A CLONE AND NOT A WORKTREE, which is the opposite of the choice this
    module makes everywhere else, so the reason is worth stating.

    `git worktree add` writes into the repository it links FROM, in two
    places, and only one of them is the worktree's own directory:

      * an admin directory at `<repo>/.git/worktrees/<name>/`, holding HEAD,
        the index, ORIG_HEAD and MERGE_* -- created before any file of the
        worktree is written; and
      * every object the trial merge creates, into `<repo>/.git/objects`,
        which is SHARED with the source. `git worktree remove` does not
        delete them, so each trial left an unreferenced merge commit and tree
        behind in the real repository, for as long as it went uncollected.

    Both are fatal to what the trial is for. The first is why Accept failed
    outright on a task in a repository the console may only read. The second
    is quieter and worse: "the trial leaves nothing" was simply not true on
    the path where the trial did run.

    A clone reads the source and writes only to the destination, so both go
    away. Measured under the console's own sandbox: 0.13s and 42 MB for the
    platform checkout, 0.27s and 6 MB for the fleet one, per Accept, into a
    directory systemd destroys when the service stops.

    `--no-hardlinks` because the source may be on a read-only mount: linking
    an object would change the link count on the source inode, which is a
    write to that filesystem. Git falls back to copying on its own, but the
    fallback is not the thing being relied on -- and a full copy is what
    makes the clone self-contained, with no alternates pointing at objects
    the source could garbage-collect out from under a running trial.

    Returns the clone and the resolved sha, so everything downstream compares
    against a sha rather than a name that could move mid-trial.
    """
    sha = git(repo, "rev-parse", at).strip()
    path = root / name
    if path.exists():
        shutil.rmtree(path)
    root.mkdir(parents=True, exist_ok=True)
    git(repo, "clone", "--quiet", "--no-checkout", "--no-hardlinks",
        str(repo), str(path))
    git(path, "checkout", "--quiet", "--detach", sha)
    return path, sha


def discard_trial_clone(path: Path) -> None:
    """Delete a trial clone.

    Deliberately not `remove()`: that runs `git worktree remove` and `git
    worktree prune` against the SOURCE repository, which is both unnecessary
    for a clone -- the source has no registration to prune -- and a write the
    console may not be allowed to make. A clone is a directory and nothing
    else, so removing it is removing the directory.
    """
    shutil.rmtree(path, ignore_errors=True)


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
