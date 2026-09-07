"""Reading the sources, and recording which ones answered.

EVERY SOURCE IS PROBED, AND THE ANSWER IS RECORDED PER RUN
-----------------------------------------------------------
Not read off a roster. A source reachable yesterday and unreachable today is
the finding, and it is only visible if each run records what it actually found.
A pass that assumes its source list is a pass that reports a shorter brief on
the day something breaks and says nothing about why.

A source that fails does not abort the pass. Its claims become UNCOMPUTED with
the reason, and the rest of the brief is still produced -- because a real outage
is exactly when the brief matters, and a pass that dies is a pass that stays
silent about the thing worth knowing.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    name: str
    role: str
    ok: bool
    as_of: Optional[datetime] = None
    detail: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "role": self.role, "ok": self.ok,
                "as_of": self.as_of.isoformat() if self.as_of else None,
                "detail": self.detail}


class Reader:
    """One read-only connection, and a record of what it managed to read."""

    def __init__(self, conn, role: str):
        self._conn = conn
        self.role = role
        self.results: List[SourceResult] = []

    def probe(self, name: str, fn: Callable[[Any], Any]) -> Optional[Any]:
        """Run one read. Record whether it worked. Never raise.

        A savepoint per probe: one failing query must not poison the connection
        for the rest of the pass. The reconciliation detector does the same for
        the same reason -- a failed query must never be reported as a zero.
        """
        try:
            with self._conn.transaction():
                value = fn(self._conn)
            self.results.append(SourceResult(name, self.role, True,
                                             as_of=_now()))
            return value
        except Exception as exc:
            detail = str(exc).strip().split("\n")[0][:200]
            log.warning("source %s unreadable: %s", name, detail)
            self.results.append(SourceResult(name, self.role, False,
                                             detail=detail))
            return None

    def failed(self, name: str) -> Optional[str]:
        for r in self.results:
            if r.name == name and not r.ok:
                return r.detail
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def scalar(sql: str, params: Optional[Dict] = None):
    """A probe body returning one value."""
    def _run(conn):
        return conn.execute(sql, params or {}).fetchone()[0]
    return _run


def row(sql: str, params: Optional[Dict] = None):
    def _run(conn):
        return conn.execute(sql, params or {}).fetchone()
    return _run


# ---------------------------------------------------------------------------
# git, which needs no grant and is the only measure of engineering time
# ---------------------------------------------------------------------------

def git(repo: str, *args: str) -> Optional[str]:
    """Run one git command. None on any failure, never raises."""
    try:
        out = subprocess.run(["git", "-C", repo, *args],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except Exception:
        return None


def head_sha(repo: str) -> Optional[str]:
    return git(repo, "rev-parse", "--short", "HEAD")


def commits_since(repo: str, since: datetime) -> Optional[int]:
    out = git(repo, "rev-list", "--count",
              f"--since={since.isoformat()}", "HEAD")
    return int(out) if out and out.isdigit() else None


def last_commit_at(repo: str) -> Optional[datetime]:
    """The instant HEAD was committed — the `as_of` for every git claim."""
    out = git(repo, "log", "-1", "--format=%cI")
    if not out:
        return None
    try:
        return datetime.fromisoformat(out)
    except ValueError:
        return None
