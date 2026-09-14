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

    WHAT EACH COMPARISON IS FOR
    ---------------------------
    Two are made, and a third thing is recorded and deliberately not compared.

    `head` -- THE DEPLOYMENT POINTER. specs/deploy-from-a-ref.md: the units run
    from this working tree, so a moved HEAD means the run's tree is not the
    tree it started on.

    `tree_digest` and `entries` -- EVERY FILE, whether tracked, untracked or
    IGNORED. This is the guard's real job. A write into a gitignored directory
    shows in neither `rev-parse HEAD` nor `status --porcelain` -- measured: a
    file planted under an ignored `build/` leaves porcelain byte-identical and
    changes the digest -- so a check built on git's own view would report a
    repository as untouched while something had been written into it.

    `porcelain` -- RECORDED FOR THE READER, NOT COMPARED, SINCE 14 Sep 2026.

    IT USED TO BE COMPARED AND IT COST A RUN. `git status --porcelain`
    describes the INDEX as well as the tree, and staging is not a write: `git
    add` on an already-modified file rewrites its entry from " M path" to
    "M  path" while every byte of the tree stays where it was. On 14 Sep task
    91's agent exited 0, its check passed, its branch was pushed, and the run
    was then failed over that one space -- with `tree_digest` identical either
    side, which is to say the comparison that was right said nothing had
    happened and the comparison that was wrong overruled it.

    It contributed no class of true positive the walk lacks. A write is a
    write: the walk sees it in tracked, untracked and ignored paths alike,
    where porcelain is blind to the third. What porcelain alone could see was
    index state -- `git add`, `git reset`, `git rm --cached`, `git stash` --
    and none of those is the thing this class exists to catch. It is still
    recorded, because when the digest fires it is worth knowing what git
    thought at the time, and it costs 9ms to ask.

    THE RESIDUE, STATED RATHER THAN DISCOVERED LATER: git re-hashes entries
    whose mtime matches the index's own, so in that narrow window porcelain
    could catch a write that preserved both size and nanosecond mtime. The
    walk cannot. That gap was already accepted below and is not closed by
    either check; closing it means hashing contents.

    WHAT IT COSTS, MEASURED 14 Sep 2026 ON THIS HOST
    ------------------------------------------------
    It records (path, size, mtime_ns) per file rather than hashing contents:

                                          files     size   walk    hash
        ~/fleet                            6,388  0.13 GB  0.09s   4.26s
        platform, node_modules excluded   17,883  0.44 GB  0.26s  13.90s
        platform, everything              63,420  1.13 GB  0.74s      --

    THE FIGURE THIS REPLACED WAS WRONG BY TWO ORDERS OF MAGNITUDE. It read
    "hashing the bytes would take minutes on every tick", which predates the
    `worktree_links` exclusion below: during a run node_modules is not walked
    at all, and hashing what remains is 14s, not minutes. The trade still
    stands -- ~50x for a gap the racy case above describes -- but it should be
    argued from 14s rather than from a number nobody re-measured.

    A write that preserved a file's size AND its nanosecond mtime slips
    through; that is a deliberate trade and it is written down rather than
    left to be discovered.

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
            # would differ and every tick would report tampering. HEAD is
            # compared separately and is the part of git's own state that
            # decides anything here; this digest is about the working tree.
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
        # NO PORCELAIN COMPARISON. It described the index as well as the tree,
        # and staging is not a write -- see the class docstring and task 91.
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


def create(repo: Path, root: Path, branch: str, base_branch: str,
           remote: str = "origin") -> tuple[Path, str]:
    """A fresh branch off the base, in its own worktree.

    The base sha is resolved once and returned. Everything downstream compares
    against that sha rather than against the branch name, so a base that moves
    mid-run cannot silently change what "the diff" means.

    FROM THE REMOTE'S BASE, NOT THE CHECKOUT'S, and 13 Sep 2026 is why.

    `console.merge.publish` pushes the merge to the REMOTE, and
    specs/merge-outside-the-checkout.md §2.2 makes the checkout a follower
    that nothing fast-forwards -- the console cannot write there at all. So
    every merge this system makes leaves the local base one merge behind, and
    the next branch was cut from that stale ref. Measured that night: task 76
    was published at 09:10, nobody pulled, and tasks 83, 85 and 86 were each
    cut from a base two commits behind, verified for a combined 22 minutes,
    and refused at the push for a divergence that was true before the first
    branch existed.

    A FETCH AND NOT A FAST-FORWARD. Moving the local `main` would rewrite the
    checkout's working tree, and `console/autodeploy.py` reads that tree's
    HEAD as the deploy target -- so fast-forwarding it here would make every
    build tick a deployment decision. Fetching touches remote-tracking refs
    only: not HEAD, not the working tree, not `git status`, which is what
    keeps `Untouched` (taken before this runs) from reporting tampering.

    THE FALLBACK IS SAFE RATHER THAN SILENT. With no remote, or with the
    network down, this cuts from the local ref exactly as it always did. That
    is no longer fatal: `console.reverify` now builds its trial at the base
    read from the remote, so a branch cut from a stale base is verified
    against the base it will really land on, and a moved base is a
    re-verification rather than a refusal.
    """
    base_sha = ""
    if has_remote(repo, remote):
        try:
            git(repo, "fetch", "--quiet", remote, base_branch)
            base_sha = git(repo, "rev-parse",
                           f"refs/remotes/{remote}/{base_branch}").strip()
        except GitError:
            base_sha = ""
    if not base_sha:
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

    A research task can produce a document on a local branch and that IS the
    artifact; treating an absent remote as a failure would report a
    successful run as a broken one.

    THIS SAID "~/fleet has no remote" UNTIL 10 SEP 2026 AND IT DOES NOW
    (`git@github-fleet:deadlydigital/fleet.git`), so the branch that reads
    this takes the push path for fleet-repo tasks where the comment said it
    would not. Nothing here decides anything on the strength of the comment
    -- the answer comes from `git remote` -- but the sentence was load-bearing
    for a reader, and tasks 34 and 50 were both diagnosed against it.
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


#: Link targets built as a REAL directory of symlinks rather than as one
#: symlink to the whole tree. Only `node_modules`: it is the only linked tree
#: that tools write into, and farming a whole repository checkout -- which is
#: what contracts/draft-spec.yaml links -- would turn its `.git` into a
#: symlink and change what git does inside it.
FARMED = ("node_modules",)

#: Names inside a farmed tree that are tool caches rather than dependencies.
#: Created empty and writable in the worktree instead of linked, so the write
#: lands in the tree that gets deleted. `.bin` is deliberately NOT here: it
#: holds the executables the checks invoke and must resolve to the real ones.
WRITABLE_INSIDE = (".vite", ".cache", ".turbo")


def link_path(worktree: Path, target: str) -> Path:
    """Where a `worktree_links` target LIVES. Never where it points.

    LEXICAL, AND THAT IS THE WHOLE POINT. `(worktree / target).resolve()` reads
    the filesystem, so it answers differently depending on whether the link has
    been made yet: before `symlink_to` it returns the path inside the worktree,
    after it returns the source. Two functions computed exactly that expression
    for exactly this value -- link_dependencies before creating, writable_links
    after -- and got different answers, which is why a refusal that had named

        <trial>/reference/deadly-digital-platform

    all morning started naming /home/ubuntu/deadly-digital-platform in the
    afternoon, for the same probe writing to the same place. The write never
    moved; only the name did, because the link had come into existence between
    the two readings.

    normpath is purely textual: no stat, no symlink, no dependence on when it
    is called. Anything that wants to know where a link POINTS asks for that
    separately and says so -- see `inside`.
    """
    return Path(os.path.normpath(worktree / target))


def inside(worktree: Path, path: Path) -> bool:
    """Does `path` land inside the worktree once every symlink is followed?

    THIS ONE FOLLOWS DELIBERATELY, and it is the opposite decision from
    link_path for the opposite reason. A containment check that did not follow
    could be walked past: the agent runs before the links are made and could
    leave `reference` as a symlink to /etc, after which a lexical check on
    `reference/sub/link` sees a path under the worktree and `mkdir(parents=True)`
    builds the rest of it in /etc.

    realpath rather than resolve so a path that does not exist yet still
    answers -- it resolves the existing prefix and appends the rest, which is
    exactly the question being asked BEFORE anything is created.
    """
    root = os.path.realpath(worktree)
    real = os.path.realpath(path)
    return real == root or real.startswith(root + os.sep)


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

    A FARMED LINK IS A REAL DIRECTORY OF SYMLINKS, and `node_modules` is one.

    One symlink for the whole tree makes every path inside it read-only when
    the source is read-only, and vitest writes inside it:

        EROFS: open '<trial>/platform/node_modules/.vite/vitest/results.json'

    Measured 11 Sep 2026 re-verifying task 53 under the accept path's own
    confinement, with `ProtectHome=read-only` and the source under /home.
    tsc passed; vitest died on that write; and because vitest exits 1 rather
    than on a signal, it was reported as the branch failing to verify.

    Farming the top level -- 529 symlinks for the platform tree, one per
    entry, made in a few milliseconds against 783 MB nobody copies -- makes
    the directory itself real and writable. `WRITABLE_INSIDE` names are then
    created as real empty directories rather than linked, so a tool's cache
    lands in the trial and is deleted with it.

    IT ALSO CLOSES THE HAZARD THIS DOCSTRING ALREADY NAMED. "A write through
    this link would land outside the worktree's git index entirely" was true
    of every farmed path before this: a tool writing into `node_modules` wrote
    into the real checkout. Now it writes into the throwaway tree.
    """
    created: list[Path] = []
    for target, source in (links or {}).items():
        dest = link_path(worktree, target)
        if not inside(worktree, dest):
            raise GitError(f"worktree link {target!r} resolves outside the worktree")
        src = Path(source)
        if not src.exists():
            raise GitError(f"worktree link source {source} does not exist")
        if dest.exists() or dest.is_symlink():
            raise GitError(f"worktree link {target!r} already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.name in FARMED and src.is_dir():
            dest.mkdir()
            for entry in src.iterdir():
                if entry.name in WRITABLE_INSIDE:
                    # Real, empty, and writable. NOT a copy of the source's
                    # cache: a stale result file carried into the trial is a
                    # verdict from another tree, and the point of the trial is
                    # that nothing arrives with one.
                    (dest / entry.name).mkdir()
                else:
                    (dest / entry.name).symlink_to(entry)
        else:
            dest.symlink_to(src)
        created.append(dest)
    return created


def writable_links(worktree: Path, contract: dict) -> list[Path]:
    """The linked trees verification is expected to WRITE through.

    THE WRITE PROBE MUST NOT ASSERT A REFERENCE IS WRITABLE, and until 12 Sep
    2026 it asserted it of every link. Accepting task 71 refused with

        /tmp/.../fleet-accept-trial-71/reference/deadly-digital-platform is
        not writable (Read-only file system)

    and the refusal was honest: the console has `ProtectHome=read-only` and no
    `ReadWritePaths`, which is correct and was made so on 11 Sep when the merge
    moved into a clone. What was wrong is that anything asked.

    NOTHING WRITES THROUGH A `reference/` LINK, and the tree says so three ways.
    The agent never sees it -- `link_dependencies` runs after the diff is
    derived, and packs.py records that "for a draft-spec task the linked
    checkout DOES NOT EXIST while the agent runs". The paths pack reads the
    link's TARGET, never the link. And draft_spec_shape.py, the only command
    that contract verifies with, resolves `REPO_ROOT / repo` directly and never
    mentions `reference/` at all.

    So the probe was the only writer. That is the mirror image of the failure
    the probe exists for: vitest made a real write into a real dependency tree
    and exited 1, indistinguishable from a failing test. Here there is no write
    to predict, and the check that predicts writes was making the only one.

    THE OPERATIVE TEST IS STRUCTURAL: A LINK THAT RESOLVES OUTSIDE THE WORKTREE
    IS NEVER PROBED.

    That is not a heuristic, it is the invariant the whole design rests on.
    Verification writes only inside the tree that gets thrown away. A farmed
    `node_modules` is a real directory of symlinks INSIDE the worktree and
    resolves inside it; a plain symlink to a checkout resolves outside. A check
    that genuinely needs to write through a link resolving outside is writing
    into a tree nobody deletes -- which is the thing the boundary forbids, and
    the answer there is to farm it, as node_modules was, not to make a
    production checkout writable.

    IT IS STRUCTURAL BECAUSE A DECLARATION COULD NOT REACH THE TASK THAT FOUND
    IT. `read_only_links` was the first fix and it was correct and useless
    here: the console freezes its contract from the task row, task 71 was
    queued at 12:38 and the key landed at about 14:15, so the contract
    governing that task has `worktree_links` and `read_only_links: null` and
    always will. guard_task_immutability permits an acceptance_contract change
    only while a task is QUEUED, and task 71 is READY_FOR_REVIEW -- so applying
    the declaration to it means REWORK -> QUEUED, which means the agent writes
    the spec again, which discards a finished branch to stop a probe that
    should not have run. A rule derived from the filesystem at probe time needs
    no declaration and reaches every task already frozen.

    `read_only_links` STAYS as documentation of intent, and can only REMOVE.
    Both tests must pass for a link to be probed, so the declaration says in
    the contract what the structure works out on disk, and a contract that
    declares one wrongly loses a probe rather than gaining one.

    THE DEFAULT FOR A LINK INSIDE THE WORKTREE IS STILL TO PROBE, and the
    direction of that error is chosen. A link wrongly assumed unwritten
    produces a tool dying on EROFS and being reported as the branch failing,
    which is the defect the probe was built after; a link probed unnecessarily
    produces a loud `could_not_run` naming the path. Noisy beats silent.
    """
    read_only = set(contract.get("read_only_links") or [])
    out: list[Path] = []
    for target in (contract.get("worktree_links") or {}):
        if target in read_only:
            continue
        dest = link_path(worktree, target)
        if inside(worktree, dest):
            out.append(dest)
    return out


def unlink_dependencies(created: list[Path]) -> None:
    """Remove what link_dependencies made, and only that.

    Each entry is unlinked rather than deleted recursively: following one of
    these into the checkout's real node_modules with rmtree would delete the
    dependencies of the repository itself.
    """
    for path in created:
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            # A FARMED LINK: a real directory holding symlinks and empty
            # cache dirs. Unlink the entries and remove the directory, rather
            # than rmtree -- the entries point INTO the real dependency tree
            # and following one would delete the repository's own packages,
            # which is the mistake this function's docstring already refuses.
            for entry in path.iterdir():
                if entry.is_symlink():
                    entry.unlink()
                elif entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink()
            path.rmdir()
