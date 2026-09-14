"""A waiver is granted by the floor and named by the contract, and both must hold.

040 opened one crack in the migration floor. 041 closed the hole it left --
a contract could NAME a waiver nothing had granted, and be stored, because 040
consulted the declaration only when excusing a clash. That was harmless until
something read the declaration, and `runner/config.effective_contract` was
about to: `floor_waiver: api/tests/**` would have exempted a task from the
suite that judges it.

`effective_contract` is pure and takes the floor as an argument, on
console/rank.gate's precedent. These are its two questions, and the database's
answer to the same two.
"""
from __future__ import annotations

import copy
import json

import psycopg
import pytest
import yaml

from runner import config

FLOOR = [("deadly-digital-platform", "api/analytics/migrations/**",
          "dd_index_migration"),
         ("deadly-digital-platform", "api/tests/**", None),
         ("deadly-digital-platform", "api/alembic/**", None)]

CONTRACT = {
    "work_type": "dd_index_migration",
    "repo": "deadly-digital-platform",
    "floor_waiver": "api/analytics/migrations/**",
    "writable_paths": ["api/analytics/migrations/versions/v*.py"],
    "protected_paths": ["api/analytics/migrations/**",
                        "api/analytics/migrations/migration.py",
                        "api/tests/**", "api/alembic/**"],
}


# ---- the pure function ------------------------------------------------------

class TestTheEffectiveContract:

    def test_a_granted_waiver_removes_that_glob_and_nothing_else(self):
        out = config.effective_contract(CONTRACT, FLOOR)
        assert "api/analytics/migrations/**" not in out["protected_paths"]
        for kept in ("api/tests/**", "api/alembic/**",
                     "api/analytics/migrations/migration.py"):
            assert kept in out["protected_paths"], kept

    def test_the_machinery_survives_the_glob_being_removed(self):
        """It is listed in its own right, not inherited from the glob. A task
        that can edit migration.py can redefine CreateIndexStep, and the
        index check's whitelist becomes a whitelist of a word."""
        out = config.effective_contract(CONTRACT, FLOOR)
        assert "api/analytics/migrations/migration.py" in out["protected_paths"]

    def test_it_records_what_it_applied(self):
        """The verdict turns on a table the boundary check never reads. If the
        run does not say so, nobody can reconstruct why a path was allowed."""
        out = config.effective_contract(CONTRACT, FLOOR)
        assert out["floor_waiver_applied"] == "api/analytics/migrations/**"

    def test_a_contract_with_no_waiver_is_returned_unchanged(self):
        plain = {k: v for k, v in CONTRACT.items() if k != "floor_waiver"}
        assert config.effective_contract(plain, FLOOR) == plain

    def test_the_declared_contract_is_not_mutated(self):
        before = copy.deepcopy(CONTRACT)
        config.effective_contract(CONTRACT, FLOOR)
        assert CONTRACT == before, "the row's contract must survive untouched"


class TestADeclarationIsNotAGrant:

    def _raises(self, contract, floor=FLOOR):
        with pytest.raises(config.WaiverNotGranted) as exc:
            config.effective_contract(contract, floor)
        return str(exc.value)

    def test_a_waiver_the_floor_does_not_grant_at_all(self):
        """floor_waiver: api/tests/** is the one that matters -- it would
        exempt a task from the suite that judges it."""
        forged = {**CONTRACT, "floor_waiver": "api/tests/**"}
        assert "api/tests/**" in self._raises(forged)

    def test_a_waiver_granted_to_a_different_work_type(self):
        forged = {**CONTRACT, "work_type": "dd_api"}
        assert "dd_api" in self._raises(forged)

    def test_a_waiver_granted_on_a_different_repo(self):
        forged = {**CONTRACT, "repo": "fleet"}
        self._raises(forged)

    def test_a_glob_on_the_floor_but_waived_for_nobody(self):
        forged = {**CONTRACT, "floor_waiver": "api/alembic/**"}
        assert "api/alembic/**" in self._raises(forged)

    def test_it_raises_rather_than_ignoring_the_declaration(self):
        """Ignoring it would mean a contract stored declaring one thing and
        judged under another, with the difference invisible in both."""
        forged = {**CONTRACT, "floor_waiver": "api/tests/**"}
        with pytest.raises(config.WaiverNotGranted):
            config.effective_contract(forged, FLOOR)


# ---- and the database, which must refuse it first ---------------------------

class TestTheDatabaseRefusesAnUngrantedDeclaration:
    """041. The runner refusing it is the weaker answer: it would mean a wrong
    contract could be stored, queued, and reach a build before anything
    objected."""

    def _insert(self, console, contract):
        console.execute(
            "INSERT INTO tasks (title, spec_md, repo, base_branch,"
            " acceptance_contract, max_cost_gbp)"
            " VALUES ('probe','# p',%s,%s,%s,%s)",
            (contract["repo"], contract.get("base_branch", "main"),
             json.dumps(contract), 1.00))

    @pytest.fixture
    def api_contract(self):
        return yaml.safe_load(
            (config.CONTRACT_DIR / "deadly-digital-platform-api.yaml").read_text())

    def test_an_ungranted_waiver_is_refused(self, console, api_contract):
        forged = {**api_contract, "floor_waiver": "api/tests/**"}
        with pytest.raises(psycopg.errors.RaiseException, match="not granted"):
            self._insert(console, forged)

    def test_a_waiver_for_another_work_type_is_refused(self, console):
        index = yaml.safe_load(
            (config.CONTRACT_DIR / "dd-index-migration.yaml").read_text())
        forged = {**index, "work_type": "dd_api"}
        with pytest.raises(psycopg.errors.RaiseException):
            self._insert(console, forged)

    def test_the_granted_one_is_accepted(self, console):
        index = yaml.safe_load(
            (config.CONTRACT_DIR / "dd-index-migration.yaml").read_text())
        self._insert(console, index)          # must not raise
