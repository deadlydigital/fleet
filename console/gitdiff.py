"""The diff, read from git on disk.

The branch is the artifact and the database records what happened to it, so
the diff is never stored. It is read at render time, which also means the
page cannot show a diff for a branch that has since been deleted -- and
saying so is better than showing a stale copy of one.

Branch and base names reach `git` as argv, never through a shell, and both
are checked against a pattern first. The runner composes branch names itself
(`fleet/task-<id>[.<attempt>]`) so nothing hostile is expected here; the
check is because "expected" is not a property this module can verify, and a
name from a database column reaching a subprocess is worth one regex.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DiffLexer

BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
FORMATTER = HtmlFormatter(nowrap=False, cssclass="diff")


@dataclass
class Diff:
    ok: bool
    reason: str = ""
    stat: str = ""
    body_html: str = ""
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    merge_base: str = ""
    merged: bool = False
    command: str = ""

    @property
    def empty(self) -> bool:
        return self.ok and not self.body_html.strip()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=30)


def diff_css() -> str:
    return FORMATTER.get_style_defs(".diff")


def for_branch(repo_root: Path, repo: str, base: str, branch: str | None) -> Diff:
    """What the branch changed, highlighted, or why it could not be read.

    THREE DOTS, NOT TWO, AND THE DIFFERENCE IS NOT COSMETIC
    -------------------------------------------------------
    `git diff main..branch` compares the two trees, so it also reports
    everything `main` gained after the branch was cut -- as deletions. Task 1
    was cut before a 137-line commit landed on main, and its two-dot diff
    reads "1 file changed, 137 deletions" for a change that touched three
    lines of one unrelated file. A reviewer opening that sees a diff the
    agent did not write.

    `main...branch` compares against the merge base, which is what the branch
    actually did. That is what is rendered, and `command` carries the same
    form so the copyable line and the page agree.
    """
    if not branch:
        return Diff(False, "this task has no branch")
    for name, label in ((branch, "branch"), (base, "base branch")):
        if not BRANCH_RE.match(name or ""):
            return Diff(False, f"{label} name {name!r} is not a valid ref name")

    path = repo_root / repo
    if not (path / ".git").exists():
        return Diff(False, f"no git repository at {path}")

    if _git(path, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}").returncode:
        return Diff(False, f"branch {branch} is not in {path} -- deleted, or never "
                           f"pushed to this checkout")

    merge_base = _git(path, "merge-base", base, branch).stdout.strip()
    merged = _git(path, "merge-base", "--is-ancestor", branch, base).returncode == 0
    spec = f"{base}...{branch}"

    numstat = _git(path, "diff", "--numstat", spec)
    if numstat.returncode:
        return Diff(False, f"git diff failed: {numstat.stderr.strip()[:200]}")

    files = insertions = deletions = 0
    for line in numstat.stdout.splitlines():
        added, removed, *_ = line.split("\t")
        files += 1
        insertions += int(added) if added != "-" else 0
        deletions += int(removed) if removed != "-" else 0

    stat = _git(path, "diff", "--stat", spec).stdout
    body = _git(path, "diff", spec).stdout

    return Diff(
        ok=True,
        stat=stat.strip(),
        body_html=highlight(body, DiffLexer(), FORMATTER) if body.strip() else "",
        files_changed=files, insertions=insertions, deletions=deletions,
        merge_base=merge_base[:12], merged=merged,
        command=f"git diff {spec}",
    )
