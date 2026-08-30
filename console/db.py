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


def rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        return conn.execute(sql, params or {}).fetchall()


def one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with connect() as conn:
        return conn.execute(sql, params or {}).fetchone()
