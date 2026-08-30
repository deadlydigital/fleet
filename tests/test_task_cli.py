"""The queue as a person drives it.

The CLI connects as fleet_console and nothing else. These tests drive the
real entry point against a throwaway database, so the grants and triggers
that constrain the deployed command constrain these runs too.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = PROJECT_ROOT / "contracts" / "deadly-digital-platform.yaml"


def load_cli():
    spec = importlib.util.spec_from_loader(
        "fleet_cli",
        importlib.machinery.SourceFileLoader("fleet_cli", str(PROJECT_ROOT / "fleet")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli(dsns, monkeypatch):
    monkeypatch.setenv("FLEET_CONSOLE_DSN", dsns["console"])
    return load_cli()


@pytest.fixture
def spec_file(tmp_path) -> Path:
    p = tmp_path / "spec.md"
    p.write_text("# A task\n\nDo the thing, concretely.\n")
    return p


def test_add_queues_a_task(cli, spec_file, console, capsys):
    assert cli.main(["task", "add", "--title", "Refund reporting",
                     "--spec", str(spec_file), "--max-cost", "3.00",
                     "--objective", "dd-feature-parity"]) == 0
    row = console.execute(
        "SELECT title, status, repo, base_branch, objective_ref, max_cost_gbp,"
        " timeout_seconds, acceptance_contract FROM tasks").fetchone()
    assert row["status"] == "QUEUED"
    assert row["repo"] == "deadly-digital-platform"
    assert row["base_branch"] == "main"
    assert row["objective_ref"] == "dd-feature-parity"
    assert "api/tests/**" in row["acceptance_contract"]["protected_paths"]
    assert row["timeout_seconds"] <= 3600


def test_the_shipped_contract_matches_the_repo_it_names(cli):
    """A spec written from memory contains wrong paths. This is the check that
    the shipped contract does not."""
    contract = yaml.safe_load(CONTRACT.read_text())
    repo = Path.home() / "deadly-digital-platform"
    if not repo.exists():
        pytest.skip("deadly-digital-platform not checked out")
    missing = [g for g in contract["writable_paths"] + contract["protected_paths"]
               if not (repo / cli.config.glob_prefix(g)).exists()]
    assert missing == [], f"contract names paths that do not exist: {missing}"


def test_add_refuses_a_contract_that_leaves_the_suite_writable(cli, spec_file,
                                                               tmp_path, console):
    contract = yaml.safe_load(CONTRACT.read_text())
    contract["protected_paths"] = [g for g in contract["protected_paths"]
                                   if g != "api/tests/**"]
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(contract))
    assert cli.main(["task", "add", "--title", "sneaky", "--spec", str(spec_file),
                     "--contract", str(bad), "--max-cost", "1.00"]) == 1
    assert console.execute("SELECT count(*) AS n FROM tasks").fetchone()["n"] == 0


def test_add_refuses_a_self_contradictory_contract(cli, spec_file, tmp_path):
    contract = yaml.safe_load(CONTRACT.read_text())
    contract["writable_paths"] = ["api/**"]
    bad = tmp_path / "wide.yaml"
    bad.write_text(yaml.safe_dump(contract))
    assert cli.main(["task", "add", "--title", "wide", "--spec", str(spec_file),
                     "--contract", str(bad), "--max-cost", "1.00"]) == 2


def test_add_refuses_an_empty_spec(cli, tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("")
    assert cli.main(["task", "add", "--title", "x", "--spec", str(empty),
                     "--max-cost", "1.00"]) == 2


def test_add_refuses_a_timeout_over_the_ceiling(cli, spec_file, console):
    assert cli.main(["task", "add", "--title", "forever", "--spec", str(spec_file),
                     "--timeout", "99999", "--max-cost", "1.00"]) == 1
    assert console.execute("SELECT count(*) AS n FROM tasks").fetchone()["n"] == 0


def test_list_orders_by_status_then_priority(cli, spec_file, capsys):
    cli.main(["task", "add", "--title", "low", "--spec", str(spec_file),
              "--priority", "200", "--max-cost", "1.00"])
    cli.main(["task", "add", "--title", "urgent", "--spec", str(spec_file),
              "--priority", "10", "--max-cost", "1.00"])
    capsys.readouterr()
    assert cli.main(["task", "list"]) == 0
    out = capsys.readouterr().out
    assert out.index("urgent") < out.index("low")


def test_status_shows_the_contract_and_what_may_happen_next(cli, spec_file,
                                                            capsys):
    cli.main(["task", "add", "--title", "t", "--spec", str(spec_file),
              "--max-cost", "1.00"])
    capsys.readouterr()
    assert cli.main(["task", "status", "1"]) == 0
    out = capsys.readouterr().out
    assert "api/tests/**" in out
    assert "no run yet" in out
    # the runner may claim it; only the console may withdraw it
    assert "RUNNING" in out and "fleet_task_runner" in out
    assert "fleet_console" in out


def test_status_of_a_missing_task(cli, capsys):
    assert cli.main(["task", "status", "999"]) == 2


def test_the_cli_cannot_reach_a_reviewed_state_it_has_no_command_for(cli,
                                                                     spec_file,
                                                                     console):
    """There is no `fleet task merge`, and the database would refuse one from
    QUEUED anyway. Both halves matter: the missing command is convention, the
    refusal is enforcement."""
    cli.main(["task", "add", "--title", "t", "--spec", str(spec_file),
              "--max-cost", "1.00"])
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException, match="may not move"):
        console.execute("UPDATE tasks SET status='MERGED' WHERE id=1")
