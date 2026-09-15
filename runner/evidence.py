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
import re
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

#: Task-authored packs are capped harder than contract ones: a contract is a
#: considered, reviewed file and a task's block is written by an agent in one
#: pass.
MAX_TASK_QUERIES = 12
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


#: Tables a TASK-AUTHORED query may not touch, matched on the query text.
#:
#: WHY THERE IS A DENYLIST AT ALL, AND WHY IT IS ONE NAME. Contract-level
#: queries are written by a person into contracts/**, which is on the fleet
#: floor for every task -- editing one is a human act. Task-level queries are
#: written by the draft-spec AGENT, and a draft-spec task merges unattended, so
#: the SQL reaches production with nobody in the loop.
#:
#: The containment is already strong: the session is read-only, the role holds
#: SELECT and nothing else, the statement timeout is 30 s and the pack keeps
#: 200 rows. What that does not stop is READING something it should not, and
#: the pack is written INTO the worktree at a path the contract declares --
#: research-metorik-gap.yaml points it at `research/EVIDENCE-metorik.md`, which
#: is inside writable_paths and therefore COMMITTED.
#:
#: Measured 15 Sep 2026, `dd_detector_login` can SELECT exactly nine tables:
#: analytics_{1,2}.orders, analytics_{1,2}.order_items,
#: analytics_{1,2}.reconciliation_manifests, public.orders, public.tenants and
#: public.utm_source_alias. Of those, ONE carries a secret: `public.tenants`
#: has `api_key` and `api_key_hash`. So the denylist is one name, and it covers
#: the whole of the sensitive surface rather than guessing at it.
#:
#: A contract-level query may still read tenants -- research-metorik-gap.yaml's
#: `dd_tenants` reads id, name and created_at and is the reason the grant
#: exists. This rule is about who WROTE the query, not about what the role can
#: reach.
TASK_QUERY_DENIED_TABLES = ("tenants",)

#: Belt and braces, because the rule above depends on a list of what is
#: sensitive staying current and lists go stale. Values shaped like a tenant
#: API key are replaced in the RESULT of a task-authored query, whatever table
#: they came from -- so a table granted to this role next month, carrying a
#: secret nobody thought to add above, does not reach a committed file.
_SECRET_SHAPED = re.compile(r"\bdd_[A-Za-z0-9_-]{20,}\b")

REDACTED = "[redacted by runner/evidence.py: shaped like a credential]"


class QueryRefused(ValueError):
    """A declared query this will not run, with the reason."""


def validate_task_queries(queries: Any) -> list[dict[str, Any]]:
    """Check a TASK-AUTHORED `evidence_queries` block and return it.

    Raises QueryRefused with a sentence. One definition, three readers: the
    draft check refuses the block at draft time, console/autoqueue refuses it
    at queue time, and this module is where both of them ask -- the same
    arrangement spec_requirements_cited.py has with console.requirements, and
    for the same reason.
    """
    if queries is None:
        return []
    if not isinstance(queries, list):
        raise QueryRefused("evidence_queries must be a list of queries")
    if len(queries) > MAX_TASK_QUERIES:
        raise QueryRefused(
            f"{len(queries)} queries declared and the ceiling is "
            f"{MAX_TASK_QUERIES}. The pack is read before the agent starts and "
            f"is the agent's whole view of the database; a pack nobody can "
            f"read is not evidence.")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for n, q in enumerate(queries, start=1):
        where = f"evidence_queries[{n}]"
        if not isinstance(q, dict):
            raise QueryRefused(f"{where} is not a mapping of key, reader and sql")
        key, reader, sql = q.get("key"), q.get("reader"), q.get("sql")
        if not key or not str(key).strip():
            raise QueryRefused(
                f"{where} has no key. The key names the reading in the pack "
                f"and in the document that cites it.")
        key = str(key).strip()
        if key in seen:
            raise QueryRefused(
                f"{where} repeats the key {key!r}; two readings under one name "
                f"cannot be told apart afterwards")
        seen.add(key)
        if reader not in READERS:
            raise QueryRefused(
                f"{where} names reader {reader!r}; a task may name only "
                f"{', '.join(sorted(READERS))}")
        if not sql or not str(sql).strip():
            raise QueryRefused(f"{where} has no sql")
        text = str(sql)
        low = text.lower()
        for denied in TASK_QUERY_DENIED_TABLES:
            if re.search(rf"\b{re.escape(denied)}\b", low):
                raise QueryRefused(
                    f"{where} references {denied!r}. A task-authored query may "
                    f"not read it: the evidence pack is written to a path the "
                    f"contract declares writable and is therefore COMMITTED, "
                    f"and public.tenants carries api_key and api_key_hash. A "
                    f"contract-level query may read it -- a person wrote that "
                    f"one into a protected file.")
        out.append({"key": key, "reader": reader, "sql": text,
                    # Marks the result for redact() in run_queries. A
                    # contract-level query carries no such flag and is
                    # passed through untouched.
                    "task_authored": True})
    return out


def redact(value: Any) -> Any:
    """Replace credential-shaped values on their way into the pack."""
    if not isinstance(value, str):
        return value
    return _SECRET_SHAPED.sub(REDACTED, value)


#: Where a task's evidence pack is written, and — since the boundary must
#: permit exactly the file the runner wrote — the one definition both of them
#: ask. runner/cycle.py uses it to decide where to write; console/reverify.py
#: uses it to decide what to allow in the merge's diff. Two readers, one
#: expression, for the reason spec_requirements_cited.py imports
#: console.requirements rather than copying its regexes: a boundary that
#: permitted a different path from the one the runner wrote is a refusal
#: nobody can act on.
#:
#: PER TASK, AND THAT IS THE POINT OF THE DEFAULT. It used to be a bare
#: `EVIDENCE.md` at the repository root, which was harmless while the only
#: contract carrying queries was pinned to a single task:
#: research-metorik-gap.yaml names `research/EVIDENCE-metorik.md` and only one
#: task ever ran under it.
#:
#: Per-task `evidence_queries` (15 Sep 2026) made research.yaml a SHARED
#: contract that can carry queries, and a fixed path under a shared contract
#: collides: task 115's pack overwrites task 114's on master, so task 114's
#: document cites readings that are no longer at the path it names. The pack
#: exists so the readings travel with the document that rests on them, and a
#: filename two documents share defeats exactly that.
#:
#: A contract or a fleet-spec block may still name one explicitly, and
#: research-metorik-gap.yaml's is unaffected.
PACK_DIR = "evidence"


def pack_path(contract: dict[str, Any], task_id: Any) -> str:
    """The pack's path for this task, relative to the worktree."""
    named = (contract or {}).get("evidence_pack")
    if named and str(named).strip():
        return str(named).strip()
    return f"{PACK_DIR}/task-{task_id}.md"


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
                    rows = rows[:MAX_ROWS]
                    # REDACTED ON THE WAY IN, not on the way out. The pack is
                    # written to a committed path, so a credential that reaches
                    # `r.rows` has already reached the thing that matters.
                    # Only for task-authored queries: a contract-level one was
                    # written by a person into a protected file, and silently
                    # rewriting their reading would be the worse surprise.
                    if q.get("task_authored"):
                        rows = [{k: redact(v) for k, v in row.items()}
                                for row in rows]
                    r.rows = rows
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
