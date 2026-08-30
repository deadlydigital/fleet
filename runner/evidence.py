"""The evidence pack: the runner reads the databases, the agent reads a file.

A research task needs data. The obvious way to give it data is a shell and a
psql, and that is exactly what must not happen: the absence of Bash is the
property that keeps the agent inside its worktree, and a credential in its
environment is a credential it can carry anywhere it can reach.

So the reading happens here, before the agent starts, as a role that holds
SELECT and nothing else. The task's contract names the queries; the database
freezes that contract the moment the task leaves QUEUED, so the agent cannot
change what was asked. The results land in the worktree as a markdown file
and the agent reads them like any other file.

WHAT THIS COSTS, stated rather than discovered: the agent cannot follow a
hunch into a query nobody wrote. It gets the pack it was given. When that is
the wrong pack the task is reworked with more queries, which is the loop that
already exists.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from detectors import config as base_config

#: The read-only logins a query may name. Not arbitrary DSNs: a contract that
#: could name a connection string could name a writing one.
READERS = {
    "fleet": "FLEET_CONSOLE_READER_DSN",       # SELECT on the fleet database
    "deadly_digital": "DD_DSN",                # SELECT on deadly_digital
}

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 30_000


@dataclass
class QueryResult:
    key: str
    reader: str
    sql: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str = ""
    ran_at: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _connect(reader: str) -> psycopg.Connection:
    if reader not in READERS:
        raise ValueError(
            f"unknown reader {reader!r}; a contract may name only "
            f"{', '.join(sorted(READERS))}")
    conn = psycopg.connect(base_config.require(READERS[reader]),
                           row_factory=dict_row, connect_timeout=20)
    conn.read_only = True
    return conn


def run_queries(queries: list[dict[str, Any]]) -> list[QueryResult]:
    """Every declared query, each in its own read-only session.

    A failing query is recorded and does not stop the pack: a research task
    whose third query has a typo should still get the first two, and the
    document should be able to say which reading it could not obtain.
    """
    results: list[QueryResult] = []
    by_reader: dict[str, list[dict[str, Any]]] = {}
    for q in queries or []:
        by_reader.setdefault(q.get("reader", "fleet"), []).append(q)

    for reader, group in by_reader.items():
        try:
            conn = _connect(reader)
        except Exception as exc:                                  # noqa: BLE001
            for q in group:
                results.append(QueryResult(q["key"], reader, q["sql"],
                                           error=f"cannot reach {reader}: {exc}"))
            continue
        with conn:
            conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            for q in group:
                r = QueryResult(q["key"], reader, q["sql"],
                                ran_at=datetime.now(timezone.utc).isoformat())
                try:
                    rows = conn.execute(q["sql"]).fetchall()
                    r.row_count = len(rows)
                    r.truncated = len(rows) > MAX_ROWS
                    r.rows = rows[:MAX_ROWS]
                except Exception as exc:                          # noqa: BLE001
                    conn.rollback()
                    r.error = str(exc).splitlines()[0][:300]
                results.append(r)
    return results


def render(results: list[QueryResult], task: dict[str, Any]) -> str:
    """The pack, as a markdown file the agent reads.

    Every reading carries the SQL that produced it and the moment it ran, so a
    number in the finished document can be traced to a query rather than to a
    recollection. A query that failed says so in the pack: a reading that is
    missing and a reading that is zero are different facts.
    """
    out = [
        f"# Evidence pack for task {task['id']}: {task['title']}",
        "",
        "Produced by the fleet runner before the agent started, as read-only",
        "roles. **The agent did not run these and cannot run others.** If the",
        "question you need answered is not below, say so in the document under",
        "what you could not verify -- do not guess at the number.",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
        "",
    ]
    for r in results:
        out += [f"## {r.key}", "", f"Reader: `{r.reader}`. Ran at {r.ran_at}.", "",
                "```sql", textwrap.dedent(r.sql).strip(), "```", ""]
        if not r.ok:
            out += [f"**This query FAILED and produced no reading:** `{r.error}`",
                    "", "A missing reading is not a zero. Say so rather than "
                    "inferring one.", ""]
            continue
        if not r.rows:
            out += ["_No rows._ This is a real answer: the query ran and matched "
                    "nothing.", ""]
            continue
        cols = list(r.rows[0].keys())
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + "|".join(["---"] * len(cols)) + "|")
        for row in r.rows:
            out.append("| " + " | ".join(
                "" if row[c] is None else str(row[c]).replace("|", "\\|")
                for c in cols) + " |")
        out.append("")
        out.append(f"{r.row_count} row{'' if r.row_count == 1 else 's'}"
                   + (f", showing the first {MAX_ROWS}." if r.truncated else "."))
        if r.truncated:
            out.append("**Truncated.** Do not describe this as the whole set.")
        out.append("")
    return "\n".join(out)


def write_pack(worktree: Path, relpath: str, results: list[QueryResult],
               task: dict[str, Any]) -> Path:
    path = worktree / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(results, task))
    return path
