"""Test harness.

Two throwaway databases on a local cluster, rebuilt from templates for every
test:

  fleet_test   every migration, 001 through 010, unmodified, plus the same
               registry and routing rows the deployed fleet database carries
  dd_test      a stand-in for deadly_digital with a hand-counted gap

Tests connect as fleet_test_detector (member of fleet_detector, nothing else)
and dd_test_reader (SELECT only), so every trigger and grant that constrains
the real process constrains the tests too. Track 2 adds three more:
fleet_test_reader, fleet_test_proposer and fleet_test_console, which are the
read side, the write side and the deciding side of the proposal layer, kept
apart here exactly as they are kept apart in production. Nothing here touches
production.

A FIXTURE THAT IS MORE PERMISSIVE THAN PRODUCTION IS NOT A FIXTURE
------------------------------------------------------------------
Added 10 Sep 2026, after a test asserted that a draft spec may merge
unattended, passed, and was wrong: `tests/test_automerge._contract()` defaults
carry `creatable_paths`, `contracts/draft-spec.yaml` does not and never will,
and the gate the change turned on reads exactly that field. The real path was
refused; the test could not fail for the reason it existed.

So: when a test is about a contract, a grant, a ceiling or any other value
that DECIDES something, read the real artefact -- `yaml.safe_load` the
contract, ask the database for the function, glob the migrations. The
template list below is derived rather than typed for the same reason, and its
comment records the same failure arriving by a different route.

"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# RUNNING THE SUITE IS A WRITE INTO A WATCHED CHECKOUT.
#
#     PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
#
# `runner/worktree.Untouched` walks EVERY file under ~/fleet, ignored paths
# included -- that is the class it exists to catch -- so the `.pyc` pytest
# leaves under `__pycache__` fail whatever task the runner is building. It
# fails it at the END, after the agent has been paid for and the branch pushed.
#
# THIS LINE IS A BACKSTOP AND NOT THE FIX, and the difference is measured.
# 14 Sep 2026, same tree, one changed module:
#
#     plain run                                  3 .pyc written
#     PYTHONDONTWRITEBYTECODE=1                  0
#     this line, env var not set                 1   <- conftest's own
#
# Its own bytecode is written before it can run, so a first run after this
# file changes still writes one file, and one file is enough to fail a build.
# Steady state is 0. Set the environment variable; this only narrows the
# damage for a run that forgot.
#
# AND `python -m py_compile` IGNORES BOTH OF THESE. The variable and the flag
# govern the IMPORT system; explicit compilation is a request to write, and it
# writes. Using it as a syntax check -- which is the obvious thing to reach for
# -- puts a .pyc in the tree while a build is watching. Measured here on
# 14 Sep 2026 with the variable exported. `python -c "import ast, pathlib;
# ast.parse(pathlib.Path(p).read_text())"` checks syntax and writes nothing.
#
# COUNTING .pyc FILES IS THE WRONG MEASURE, which is how this was nearly
# reported as fixed when it was not: an overwrite leaves the count identical
# and changes the mtime, and the digest is over (path, size, mtime_ns). Check
# with `find . -name '*.pyc' -newermt <when>`.
sys.dont_write_bytecode = True

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


def _login_dsn(role: str) -> str:
    return f"postgresql://{role}:{role}@{HOST}:{PORT}/{FLEET_DB}"


READER_TEST_DSN = _login_dsn("fleet_test_reader")
PROPOSER_TEST_DSN = _login_dsn("fleet_test_proposer")
CONSOLE_TEST_DSN = _login_dsn("fleet_test_console")
RUNNER_TEST_DSN = _login_dsn("fleet_test_task_runner")
AGENT_TEST_DSN = _login_dsn("fleet_test_agent")
VERIFIER_TEST_DSN = _login_dsn("fleet_test_verifier")
GATEWAY_TEST_DSN = _login_dsn("fleet_test_model_gateway")
CONSOLE_READER_TEST_DSN = _login_dsn("fleet_test_console_reader")
EVALUATOR_TEST_DSN = _login_dsn("fleet_test_evaluator")


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
    # DERIVED, NOT TYPED. This was a hand-maintained list of eleven filenames
    # and it had gone stale: 012 (the daily brief) and 013 (the approval
    # surface) were both applied to the deployed database and neither was here,
    # so the suite was building a template two migrations behind and passing
    # against a schema that no longer existed anywhere else.
    #
    # A green suite that never loaded the migration proves nothing about it,
    # and the failure is silent in the direction nobody checks — the tests go
    # green, so the missing file reads as "nothing to do".
    #
    # Same defect as the executed-step tally in test_migrations.py and the
    # analytics EXPECTED_TABLE_COUNT, both of which drifted the same way for
    # the same reason. Globbed and sorted so a new migration is picked up by
    # existing, not by remembering.
    #
    # `_assertions.sql` and `_fixtures.sql` are excluded deliberately:
    # assertions are run against a built schema by the operator, and 001's
    # fixtures are applied below with the other seeds.
    migrations = sorted(
        p for p in PROJECT_ROOT.glob("[0-9][0-9][0-9]_*.sql")
        if not p.name.endswith(("_assertions.sql", "_fixtures.sql"))
    )
    if not migrations:
        raise RuntimeError(
            "no migrations found to build the fleet template; the glob or the "
            "project root is wrong, and an empty template would make every "
            "test fail for a reason that has nothing to do with the test")
    for m in migrations:
        _psql(FLEET_TEMPLATE, m)
    _psql(FLEET_TEMPLATE, FIXTURES / "fleet_seed.sql")
    _psql(FLEET_TEMPLATE, FIXTURES / "proposals_seed.sql")
    _psql(FLEET_TEMPLATE, FIXTURES / "tasks_seed.sql")
    # 049 refuses a claim when no window target is in effect. Seeded here
    # rather than per-test because every claiming test needs it and none of
    # them is about it.
    _psql(FLEET_TEMPLATE, FIXTURES / "window_target_seed.sql")

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
    monkeypatch.setenv("FLEET_READER_DSN", READER_TEST_DSN)
    monkeypatch.setenv("FLEET_PROPOSER_DSN", PROPOSER_TEST_DSN)
    monkeypatch.setenv("FLEET_CONSOLE_DSN", CONSOLE_TEST_DSN)
    monkeypatch.setenv("FLEET_TASK_RUNNER_DSN", RUNNER_TEST_DSN)
    monkeypatch.setenv("FLEET_AGENT_DSN", AGENT_TEST_DSN)
    monkeypatch.setenv("FLEET_VERIFIER_DSN", VERIFIER_TEST_DSN)
    monkeypatch.setenv("FLEET_MODEL_GATEWAY_DSN", GATEWAY_TEST_DSN)
    monkeypatch.setenv("FLEET_CONSOLE_READER_DSN", CONSOLE_READER_TEST_DSN)
    return {"fleet": FLEET_TEST_DSN, "dd": DD_TEST_DSN,
            "reader": READER_TEST_DSN, "proposer": PROPOSER_TEST_DSN,
            "console": CONSOLE_TEST_DSN, "runner": RUNNER_TEST_DSN,
            "agent": AGENT_TEST_DSN, "verifier": VERIFIER_TEST_DSN,
            "gateway": GATEWAY_TEST_DSN,
            "console_reader": CONSOLE_READER_TEST_DSN,
            "evaluator": EVALUATOR_TEST_DSN}


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


@pytest.fixture
def reader(dsns):
    """The proposal layer's read side: SELECT on track 1, nothing else."""
    with psycopg.connect(dsns["reader"], row_factory=dict_row) as conn:
        conn.read_only = True
        yield conn


@pytest.fixture
def proposer(dsns):
    """The proposal layer's write side: INSERT on proposals and evidence."""
    with psycopg.connect(dsns["proposer"], row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def console(dsns):
    """The only role the database accepts a decision from."""
    with psycopg.connect(dsns["console"], row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def runner(dsns):
    """The orchestrator: claims tasks and moves them between machine states."""
    with psycopg.connect(dsns["runner"], row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def agent_conn(dsns):
    """Writes PATCH_PROPOSED. Cannot write VERIFICATION_RUN."""
    with psycopg.connect(dsns["agent"], row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def evaluator(dsns):
    """The other role that may record a verdict, holding no ownership."""
    with psycopg.connect(dsns["evaluator"], row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def verifier_conn(dsns):
    """Writes VERIFICATION_RUN. Cannot write PATCH_PROPOSED."""
    with psycopg.connect(dsns["verifier"], row_factory=dict_row) as conn:
        yield conn
