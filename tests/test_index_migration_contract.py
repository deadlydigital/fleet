"""The one crack in the migration floor, and what keeps it a crack.

`contracts/dd-index-migration.yaml` is the only contract in this repository
that can write under `api/analytics/migrations/`. Everything that makes that
safe lives in `contracts/checks/index_migration_only.py`, so these tests are
mostly about what it REFUSES. A whitelist nobody tested against the things it
excludes is a whitelist by assertion.

The floor exists because a task that can alter the schema can drop a column.
The crack exists because the alternative was measured on 14 Sep 2026: the
dashboard's dominant query sequentially scans 2,887,010 orders to remove 2,063
of them, and no task this system has ever run could add the index.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

FLEET = Path.home() / "fleet"
CHECK = FLEET / "contracts" / "checks" / "index_migration_only.py"
CONTRACT = FLEET / "contracts" / "dd-index-migration.yaml"
PY = FLEET / ".venv" / "bin" / "python"

GOOD = '''\
"""0013 — ix_analytics_orders_customer_created."""

from ..migration import CreateIndexStep, Migration

migration = Migration(
    version=13,
    name="orders_customer_created_index",
    steps=[
        CreateIndexStep(
            table="orders",
            index="ix_analytics_orders_customer_created",
            columns="customer_id, created_at, id",
        ),
    ],
    transactional=False,
    note="Index build over 2,887,844 rows on analytics_2.",
)
'''


def run(tmp_path, body, name="api/analytics/migrations/versions/v0013_idx.py",
        base=""):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    env = {**os.environ, "FLEET_CHANGED_FILES": name, "FLEET_BASE_SHA": base,
           "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run((str(PY), str(CHECK)), cwd=tmp_path, env=env,
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ---- what it admits --------------------------------------------------------

def test_an_index_migration_passes(tmp_path):
    code, out = run(tmp_path, GOOD)
    assert code == 0, out
    assert "CreateIndexStep" in out


def test_several_indexes_in_one_migration_are_fine(tmp_path):
    two = GOOD.replace(
        "    ],\n    transactional=False,",
        '        CreateIndexStep(table="orders", index="ix_b", columns="status"),\n'
        "    ],\n    transactional=False,")
    code, out = run(tmp_path, two)
    assert code == 0, out


# ---- the whitelist, which is the whole safety argument ---------------------

class TestOnlyCreateIndexStepIsAdmitted:
    """migration.py defines SQLStep, DataStep and CreateIndexStep. Two of the
    three can express changes an index migration must not make, and they are
    refused by TYPE rather than by inspecting the SQL they carry."""

    def test_a_sql_step_is_refused(self, tmp_path):
        body = GOOD.replace(
            'CreateIndexStep(\n            table="orders",\n'
            '            index="ix_analytics_orders_customer_created",\n'
            '            columns="customer_id, created_at, id",\n        )',
            'SQLStep(sql="DROP TABLE {s}.orders")')
        code, out = run(tmp_path, body)
        assert code == 1, out
        assert "SQLStep" in out

    def test_a_data_step_is_refused(self, tmp_path):
        body = GOOD.replace("CreateIndexStep(", "DataStep(", 1)
        code, out = run(tmp_path, body)
        assert code == 1 and "DataStep" in out

    def test_a_unique_index_is_refused(self, tmp_path):
        """A unique index is a constraint: it can fail on existing data and
        reject future inserts. That is a change to what the system accepts,
        not to how fast it answers."""
        body = GOOD.replace('columns="customer_id, created_at, id",',
                            'columns="customer_id, created_at, id",\n'
                            "            unique=True,")
        code, out = run(tmp_path, body)
        assert code == 1 and "unique=True" in out


class TestTheModuleCannotRunCode:
    """The runner imports this file. Anything at the top level runs."""

    def test_a_function_definition_is_refused(self, tmp_path):
        code, out = run(tmp_path, GOOD + "\n\ndef helper():\n    return 1\n")
        assert code == 1 and "runner imports this file" in out

    def test_a_bare_call_is_refused(self, tmp_path):
        code, out = run(tmp_path, GOOD + "\n\nprint('hello')\n")
        assert code == 1

    def test_an_unexpected_import_is_refused(self, tmp_path):
        code, out = run(tmp_path, "import os\n" + GOOD)
        assert code == 1 and "os" in out


class TestTheShapeOfTheMigration:

    def test_transactional_must_be_false(self, tmp_path):
        """CREATE INDEX CONCURRENTLY cannot run inside a transaction block."""
        code, out = run(tmp_path, GOOD.replace("transactional=False",
                                               "transactional=True"))
        assert code == 1 and "transactional=False" in out

    def test_a_missing_transactional_is_refused(self, tmp_path):
        code, out = run(tmp_path, GOOD.replace("    transactional=False,\n", ""))
        assert code == 1 and "transactional=False" in out

    def test_an_empty_step_list_is_refused(self, tmp_path):
        body = GOOD.split("    steps=[")[0] + "    steps=[],\n    transactional=False,\n)\n"
        code, out = run(tmp_path, body)
        assert code == 1 and "migrates nothing" in out


class TestWhereItMayWrite:

    def test_a_file_outside_versions_is_refused(self, tmp_path):
        code, out = run(tmp_path, GOOD, name="api/analytics/services/x.py")
        assert code == 1 and "not a migration under" in out

    def test_two_files_are_refused(self, tmp_path):
        path = tmp_path / "api/analytics/migrations/versions/v0013_idx.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(GOOD)
        (tmp_path / "other.py").write_text("x = 1\n")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
               "FLEET_CHANGED_FILES":
                   "api/analytics/migrations/versions/v0013_idx.py\nother.py"}
        r = subprocess.run((str(PY), str(CHECK)), cwd=tmp_path, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 1
        assert "One index migration is one new file" in r.stdout + r.stderr

    def test_nothing_changed_is_could_not_run_not_a_pass(self, tmp_path):
        env = {**os.environ, "FLEET_CHANGED_FILES": "",
               "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run((str(PY), str(CHECK)), cwd=tmp_path, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 2, "an empty change establishes nothing"


# ---- and the contract that points at it ------------------------------------

class TestTheContractItself:

    @pytest.fixture
    def contract(self):
        return yaml.safe_load(CONTRACT.read_text())

    def test_alembic_stays_floored(self, contract):
        assert "api/alembic/**" in contract["protected_paths"]
        assert not any("alembic" in p for p in contract["writable_paths"])

    def test_it_may_write_only_migration_versions(self, contract):
        assert contract["writable_paths"] == [
            "api/analytics/migrations/versions/v*.py"]

    def test_the_migration_machinery_itself_is_floored(self, contract):
        """A task that can edit migration.py can redefine CreateIndexStep, and
        the whitelist would then be a whitelist of a word."""
        for p in ("api/analytics/migrations/migration.py",
                  "api/analytics/migrations/runner.py",
                  "api/analytics/migrations/predicates.py"):
            assert p in contract["protected_paths"], p

    def test_it_runs_the_check_that_makes_it_safe(self, contract):
        assert any("index_migration_only.py" in v
                   for v in contract["verification"])

    def test_it_does_not_merge_unattended(self, contract):
        """It cannot deploy unattended either -- console/autodeploy refuses a
        range containing a migration -- so auto-merging would remove the one
        review this path has and buy nothing."""
        assert contract["auto_merge"] is False

    def test_it_has_no_shell(self, contract):
        assert "Bash" not in (contract.get("agent_tools") or [])
