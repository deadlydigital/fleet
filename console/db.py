"""Connections, and the check that the credential is the one we think it is."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from console import config

WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")


class NotReadOnly(RuntimeError):
    """The console was pointed at a credential that can write."""


@contextmanager
def writer() -> Iterator[psycopg.Connection]:
    """The write side, as fleet_console, for the two decision routes only.

    Not read_only, obviously, and deliberately not reachable from any render
    path: nothing in queries.py or app.py's GET handlers opens this.
    """
    with psycopg.connect(config.console_writer_dsn(), row_factory=dict_row) as conn:
        yield conn


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """A read-only session, as a role that could not write in any case.

    `read_only = True` is belt to the role's braces. The role is what makes
    writing impossible; the session flag makes an accidental write fail here
    rather than at the database, with a message naming the console.
    """
    with psycopg.connect(config.console_reader_dsn(), row_factory=dict_row) as conn:
        conn.read_only = True
        yield conn


def assert_read_only() -> str:
    """Refuse to start as anything that can write. Returns the role name.

    Checked at startup, not documented and hoped for. The console's entire
    safety argument is the credential it holds, and an argument nobody
    verifies is a comment.
    """
    with psycopg.connect(config.console_reader_dsn(), row_factory=dict_row) as conn:
        who = conn.execute("SELECT current_user AS u").fetchone()["u"]
        leaks = conn.execute(
            """
            SELECT c.relname, p.priv
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace,
                   unnest(%s::text[]) AS p(priv)
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
               AND has_table_privilege(current_user, c.oid, p.priv)
             ORDER BY 1, 2
            """,
            (list(WRITE_PRIVILEGES),),
        ).fetchall()
        if leaks:
            detail = ", ".join(f"{r['priv']} on {r['relname']}" for r in leaks[:8])
            raise NotReadOnly(
                f"{who} can write ({detail}). The console must hold a "
                f"credential that can only read; point "
                f"FLEET_CONSOLE_READER_DSN at fleet_console_reader_login."
            )
        return who


class NotAWriter(RuntimeError):
    """The decision routes were pointed at something that cannot record one."""


def assert_can_write() -> str:
    """The mirror of assert_read_only, and it is not symmetry for its own sake.

    Two DSNs that were accidentally the same would fail in only one direction:
    if both pointed at the reader, every page would still render and the
    failure would appear the first time somebody pressed Accept, after the
    merge had already happened. So the writer is checked at startup too --
    that it can do the two things a verdict needs, and that it is a different
    principal from the reader.
    """
    with psycopg.connect(config.console_reader_dsn(), row_factory=dict_row) as r:
        reader = r.execute("SELECT current_user AS u").fetchone()["u"]
    with psycopg.connect(config.console_writer_dsn(), row_factory=dict_row) as conn:
        who = conn.execute("SELECT current_user AS u").fetchone()["u"]
        if who == reader:
            raise NotAWriter(
                f"the reader and the writer are the same role ({who}). "
                f"FLEET_CONSOLE_DSN and FLEET_CONSOLE_READER_DSN must be "
                f"different principals or the separation is decorative.")
        checks = conn.execute(
            """
            SELECT has_table_privilege(current_user,'tasks','UPDATE')      AS can_update_task,
                   has_table_privilege(current_user,'run_steps','INSERT')  AS can_write_step,
                   pg_has_role(current_user,'fleet_console','MEMBER')      AS is_console
            """).fetchone()
        missing = [k for k, v in checks.items() if not v]
        if missing:
            raise NotAWriter(
                f"{who} cannot record a verdict ({', '.join(missing)}). The "
                f"database accepts a task verdict only from fleet_console.")
        return who


def rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        return conn.execute(sql, params or {}).fetchall()


def one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with connect() as conn:
        return conn.execute(sql, params or {}).fetchone()
