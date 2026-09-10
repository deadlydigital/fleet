"""What code this process is RUNNING, which is not what is on disk.

WHY THIS EXISTS, AND IT IS NOT HOUSEKEEPING
--------------------------------------------
`fleet-console.service` is a long-lived uvicorn process. Python loads a module
once; editing the file afterwards changes nothing about the running process.
So the console enforces the rules of WHENEVER IT WAS LAST RESTARTED, and
everything else about it looks current -- the database is read fresh on every
request, the contract comes out of the task row, the page renders, the
timestamps are now.

That produced a confidently worded, entirely wrong refusal on 10 Sep 2026. The
process had started at 09-09 10:05:32. `creatable_paths` support landed in
`runner/boundary.py` at 09-09 14:08:03, four hours later. Task 53 added a test
file under a `creatable_paths` glob, and the console refused it:

    platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx
    is protected by platform/__tests__/**

which was true of the code the process held and false of the code in the tree.
The same reverification, run from the current tree, was clean. Nothing on the
page, in the log, or in `/healthz` said which of those two the answer came
from.

THE DANGEROUS DIRECTION IS THE OTHER ONE. A stale console refusing a good
branch costs an afternoon and is loud. A stale console holding a LAXER boundary
than the tree -- because the tightening landed after it booted -- accepts
something the current rules refuse, and is silent. `023_platform_floor.sql` and
`024_paired_paths.sql` are both tightenings of exactly that kind.

WHAT IS COMPARED
----------------
(path, size, mtime_ns) over every `.py` in the trees the console imports,
captured at import and recomputed on demand. Not the git sha: HEAD moving is
neither necessary (an uncommitted edit changes behaviour too) nor sufficient (a
commit touching only `specs/` changes nothing here). The question is whether
the FILES BACKING THE LOADED MODULES have moved, and that is what this asks.

The same (path, size, mtime_ns) trade `runner/worktree.Untouched` documents: an
edit preserving both would slip through. Here the consequence of a false
positive is a restart, which is cheap, so the trade is easy.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from console import config

#: The trees whose modules this process holds in memory. `detectors` is here
#: because console/config.py imports it for the DSNs. `contracts/checks/` is
#: deliberately ABSENT: those are executed as subprocesses and read from disk
#: every time, so they are never stale in this sense -- which is also why the
#: bite check and the shape checks are not implicated in any of this.
CODE_ROOTS = ("console", "runner", "detectors")


@dataclass(frozen=True)
class Code:
    digest: str
    #: rel path -> (size, mtime_ns). Kept, not only hashed, so a stale process
    #: can NAME what moved rather than assert that something did -- the same
    #: reason runner/worktree.Untouched keeps its entries after task 49's
    #: "63395 files before, 63395 after". Forty-odd files; the memory is free.
    entries: tuple[tuple[str, int, int], ...]
    head: str

    def short(self) -> str:
        return f"{self.digest[:12]} ({len(self.entries)} files) at {self.head[:12]}"


def _entries() -> list[tuple[str, int, int]]:
    root = config.PROJECT_ROOT
    out: list[tuple[str, int, int]] = []
    for name in CODE_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            # __pycache__ holds compiled copies whose mtimes move when Python
            # writes them, which would report drift the moment anything ran.
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for fn in sorted(f for f in filenames if f.endswith(".py")):
                p = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                out.append((os.path.relpath(p, root), st.st_size, st.st_mtime_ns))
    return out


def _head() -> str:
    try:
        r = subprocess.run(("git", "-C", str(config.PROJECT_ROOT),
                            "rev-parse", "HEAD"),
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def snapshot() -> Code:
    entries = _entries()
    h = hashlib.sha256()
    for rel, size, mtime in entries:
        h.update(f"{rel}\0{size}\0{mtime}\n".encode("utf-8", "surrogateescape"))
    return Code(digest=h.hexdigest(), entries=tuple(entries), head=_head())


#: Captured when this module is imported, which is process start. Everything
#: below compares against it.
LOADED = snapshot()


def status() -> dict:
    """One dict for a template, a health check and a refusal message."""
    now = snapshot()
    if now.digest == LOADED.digest:
        return {"stale": False, "loaded": LOADED.short(),
                "on_disk": now.short(), "changed": []}

    was = {rel: (size, mtime) for rel, size, mtime in LOADED.entries}
    has = {rel: (size, mtime) for rel, size, mtime in now.entries}
    changed = sorted(
        [f"{r} (added)" for r in has.keys() - was.keys()]
        + [f"{r} (removed)" for r in was.keys() - has.keys()]
        + [r for r in was.keys() & has.keys() if was[r] != has[r]])
    return {"stale": True, "loaded": LOADED.short(), "on_disk": now.short(),
            "changed": changed}


def is_stale() -> bool:
    return snapshot().digest != LOADED.digest


REFUSAL = (
    "This console is running code that is no longer what is on disk, so what "
    "it would enforce is not what the repository says to enforce. On 10 Sep "
    "2026 a process three days old refused a good branch under a boundary rule "
    "the codebase had retired four hours after it booted, and the refusal was "
    "indistinguishable from a real one. The opposite -- accepting under rules "
    "looser than the tree's -- is the same defect and is silent.\n\n"
    "Nothing has been decided. Restart the console and try again:\n"
    "    sudo systemctl restart fleet-console.service"
)
