"""The queue as a person drives it.

The CLI connects as fleet_console and nothing else. These tests drive the
real entry point against a throwaway database, so the grants and triggers
that constrain the deployed command constrain these runs too.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The narrow frontend contract, which replaced the wide default.
#: contracts/deadly-digital-platform.yaml is GONE -- it declared
#: platform/{app,components,lib}/** writable, reaching auth, roles, csrf,
#: impersonation and billing checkout -- so this repo has no default and every
#: `task add` for it must name a contract. test_the_repo_has_no_default_contract
#: below is what keeps that true.
CONTRACT = PROJECT_ROOT / "contracts" / "dd-analytics-frontend.yaml"


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
                     "--spec", str(spec_file), "--contract", str(CONTRACT),
                     "--max-cost", "3.00",
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


CONTRACTS = sorted((PROJECT_ROOT / "contracts").glob("*.yaml"))


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.stem)
def test_every_shipped_contract_matches_the_repo_it_names(cli, path):
    """A spec written from memory contains wrong paths. This is the check that
    the shipped contracts do not."""
    contract = yaml.safe_load(path.read_text())
    repo = Path.home() / contract["repo"]
    if not repo.exists():
        pytest.skip(f"{contract['repo']} not checked out")
    # Protected paths must exist -- a floor naming a path that is not there
    # protects nothing.
    missing = [g for g in contract["protected_paths"]
               if not (repo / cli.config.glob_prefix(g)).exists()]

    # Writable paths: exists, OR it is a single new FILE in a directory that
    # does. A document-producing contract names the document it is about to
    # write, and requiring that to exist first would require the output before
    # the task that produces it.
    #
    # DERIVED, NOT A LIST OF WORK TYPES. This used to exempt
    # `work_type == "research"` by name, which silently stopped covering the
    # case the day a second document-producing work type existed
    # (candidate_producer) and failed it for being new. The rule it meant is
    # the one draft_spec_shape.py already states: a contract may create a new
    # file, but not in a directory that is not there.
    for g in contract["writable_paths"]:
        target = repo / cli.config.glob_prefix(g)
        if target.exists():
            continue
        if "*" not in g and target.suffix and target.parent.exists():
            continue
        # ... OR it names that new file by a PATTERN, which is how a contract
        # that runs more than once names its dated output.
        #
        # candidate-producer.yaml declared the literal
        # `research/candidates-metorik-gap-2026-09-09.md` and therefore worked
        # exactly once: the second run needed a contract edit before it could
        # write anything (specs/auto-approval.md §8.1). A dated pattern is the
        # fix, and this rule refused it -- not because the contract was wrong
        # but because the rule had only ever seen the two cases that existed.
        #
        # The `*` must be in the LAST segment, so the directory is still a real
        # one and `research/*/anything.md` -- a pattern that could create
        # directories -- stays refused.
        if "*" in g and target.parent.exists() and "/" not in g.split("*", 1)[1]:
            continue
        missing.append(g)

    assert missing == [], f"{path.name} names paths that do not exist: {missing}"


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.stem)
def test_every_shipped_contract_links_only_to_things_that_exist(cli, path):
    contract = yaml.safe_load(path.read_text())
    missing = [f"{t} -> {s}" for t, s in (contract.get("worktree_links") or {}).items()
               if not Path(s).exists()]
    assert missing == [], f"{path.name} links to missing sources: {missing}"


def test_the_frontend_contract_verifies_what_it_makes_writable(cli):
    """Verification scope and writable scope must match.

    A contract declaring api/** writable while verifying with vitest would
    accept a backend change on the strength of tests that never executed it.
    """
    contract = yaml.safe_load(CONTRACT.read_text())
    commands = " ".join(contract["verification"])
    assert "vitest" in commands and "tsc" in commands
    assert all(g.startswith("platform/") for g in contract["writable_paths"]), \
        "this contract verifies the frontend, so only the frontend may be writable"
    assert "api/**" in contract["protected_paths"]


def test_the_repo_has_no_default_contract(cli):
    """The wide contract is gone, and its absence is the boundary.

    contracts/deadly-digital-platform.yaml declared platform/app/**,
    platform/components/** and platform/lib/** writable -- lib/auth.ts,
    lib/roles.ts, lib/csrf.ts, app/api/auth/impersonate and
    app/api/billing/checkout. Restoring a file at that path restores all of it
    to anybody who types `task add` without --contract, which is why this test
    is about the PATH and not about the contents of a file that is not there.

    023_platform_floor.sql is the other half: those paths are on
    protected_path_floor now, so the restored file could not create a task
    either. Two independent refusals for one mistake, deliberately.
    """
    assert not (PROJECT_ROOT / "contracts" / "deadly-digital-platform.yaml").exists()
    with pytest.raises(RuntimeError, match="no default contract"):
        cli.config.load_contract("deadly-digital-platform")


def test_no_shipped_contract_makes_the_platform_floor_writable(cli):
    """Every floor glob for a repo must be protected by every contract naming
    it -- the database enforces that at INSERT, and this says which file is
    wrong before a task is queued.

    Derived from the migrations rather than typed: a hand-kept list here would
    go stale the first time the floor moved, which is the defect
    schema-drift-check.sh and tests/conftest.py were both fixed for.
    """
    floor = set()
    for sql in sorted(PROJECT_ROOT.glob("[0-9][0-9][0-9]_*.sql")):
        if sql.name.endswith(("_assertions.sql", "_fixtures.sql")):
            continue
        body = sql.read_text()
        for m in re.finditer(
                r"\('deadly-digital-platform',\s*'([^']+)'", body):
            floor.add(m.group(1))
    assert "platform/middleware.ts" in floor, \
        "023's floor did not parse out of the migrations; this test is blind"

    for path in CONTRACTS:
        contract = yaml.safe_load(path.read_text())
        if contract.get("repo") != "deadly-digital-platform":
            continue
        missing = sorted(floor - set(contract["protected_paths"]))
        assert missing == [], f"{path.name} does not protect {missing}"


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
                     "--contract", str(CONTRACT), "--max-cost", "1.00"]) == 2


def test_add_refuses_a_timeout_over_the_ceiling(cli, spec_file, console):
    assert cli.main(["task", "add", "--title", "forever", "--spec", str(spec_file),
                     "--contract", str(CONTRACT),
                     "--timeout", "99999", "--max-cost", "1.00"]) == 1
    assert console.execute("SELECT count(*) AS n FROM tasks").fetchone()["n"] == 0


def test_list_orders_by_status_then_priority(cli, spec_file, capsys):
    cli.main(["task", "add", "--title", "low", "--spec", str(spec_file),
              "--contract", str(CONTRACT), "--priority", "200",
              "--max-cost", "1.00"])
    cli.main(["task", "add", "--title", "urgent", "--spec", str(spec_file),
              "--contract", str(CONTRACT), "--priority", "10",
              "--max-cost", "1.00"])
    capsys.readouterr()
    assert cli.main(["task", "list"]) == 0
    out = capsys.readouterr().out
    assert out.index("urgent") < out.index("low")


def test_status_shows_the_contract_and_what_may_happen_next(cli, spec_file,
                                                            capsys):
    cli.main(["task", "add", "--title", "t", "--spec", str(spec_file),
              "--contract", str(CONTRACT), "--max-cost", "1.00"])
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
              "--contract", str(CONTRACT), "--max-cost", "1.00"])
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException, match="may not move"):
        console.execute("UPDATE tasks SET status='MERGED' WHERE id=1")
