"""Test harness.

Two throwaway databases on a local cluster, rebuilt from templates for every
test:

  fleet_test   001_v1_core.sql, unmodified, plus the same registry and
               routing rows the deployed fleet database carries
  dd_test      a stand-in for deadly_digital with a hand-counted gap

Tests connect as fleet_test_detector (member of fleet_detector, nothing else)
and dd_test_reader (SELECT only), so every trigger and grant that constrains
the real process constrains the tests too. Nothing here touches production.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(PROJECT_ROOT))

SOCKET_DIR = os.environ.get("PGHOST", "/var/run/postgresql")
ADMIN_DSN = f"postgresql:///postgres?host={SOCKET_DIR}"
HOST = os.environ.get("FLEET_TEST_HOST", "127.0.0.1")
PORT = os.environ.get("PGPORT", "5432")

FLEET_TEMPLATE, FLEET_DB = "fleet_test_tmpl", "fleet_test"
DD_TEMPLATE, DD_DB = "dd_test_tmpl", "dd_test"

FLEET_TEST_DSN = f"postgresql://fleet_test_detector:fleet_test_detector@{HOST}:{PORT}/{FLEET_DB}"
DD_TEST_DSN = f"postgresql://dd_test_reader:dd_test_reader@{HOST}:{PORT}/{DD_DB}"


def _admin(sql: str) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql)


def _psql(dbname: str, path: Path) -> None:
    result = subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-h", SOCKET_DIR, "-p", PORT,
         "-d", dbname, "-f", str(path)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{path.name} failed on {dbname}:\n{result.stderr}")


def _rebuild(name: str, template: str) -> None:
    _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')


@pytest.fixture(scope="session", autouse=True)
def templates() -> None:
    """Build both template databases once. The migration is applied verbatim."""
    _admin(f'DROP DATABASE IF EXISTS "{FLEET_DB}" WITH (FORCE)')
    _admin(f'DROP DATABASE IF EXISTS "{FLEET_TEMPLATE}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{FLEET_TEMPLATE}"')
    _psql(FLEET_TEMPLATE, PROJECT_ROOT / "001_v1_core.sql")
    _psql(FLEET_TEMPLATE, FIXTURES / "fleet_seed.sql")

    _admin(f'DROP DATABASE IF EXISTS "{DD_DB}" WITH (FORCE)')
    _admin(f'DROP DATABASE IF EXISTS "{DD_TEMPLATE}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{DD_TEMPLATE}"')
    _psql(DD_TEMPLATE, FIXTURES / "dd_source.sql")


@pytest.fixture
def dsns(templates, monkeypatch) -> dict[str, str]:
    """Fresh databases, and an environment pointed at them and only them."""
    _rebuild(FLEET_DB, FLEET_TEMPLATE)
    _rebuild(DD_DB, DD_TEMPLATE)
    monkeypatch.setenv("FLEET_DSN", FLEET_TEST_DSN)
    monkeypatch.setenv("DD_DSN", DD_TEST_DSN)
    return {"fleet": FLEET_TEST_DSN, "dd": DD_TEST_DSN}


@pytest.fixture
def fleet(dsns):
    """A connection with exactly the privileges the detector process has."""
    from detectors import base
    with base.connect_fleet(dsns["fleet"]) as conn:
        yield conn


@pytest.fixture
def admin(dsns):
    """Superuser connection, for arranging history the detector cannot write."""
    dsn = f"postgresql:///{FLEET_DB}?host={SOCKET_DIR}&port={PORT}"
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        yield conn
