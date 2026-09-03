"""The decision log as a person drives it.

Same harness as `test_task_cli.py`: the real entry point, against a throwaway
database, as fleet_console -- so the triggers and grants that constrain the
deployed command constrain these runs too.

The backfill has its own class because it is the one command that writes rows
nobody typed, and the two things that make that safe are that it invents
nothing and that running it twice adds nothing.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

from test_decision_log import PRODUCT, add_issue, add_task, add_run, merge_task

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def rows(console) -> list[dict]:
    return console.execute(
        "SELECT * FROM decision_outcomes ORDER BY id").fetchall()


# ---- record ----------------------------------------------------------------

def test_record_writes_a_decision_with_its_reason(cli, console, capsys):
    assert cli.main(["decision", "record", "--decision", "APPROVED",
                     "--reason", "cheap, reversible, and it unblocks the page",
                     "--product", PRODUCT, "--subject", "Ship the sources page"]) == 0
    (row,) = rows(console)
    assert row["decision"] == "APPROVED"
    assert row["reason"].startswith("cheap, reversible")
    assert row["origin"] == "RECORDED"
    assert "derived, not stored" in capsys.readouterr().out


def test_a_rejection_is_recorded_as_readily_as_an_approval(cli, console):
    """The asymmetry this log exists to remove: nothing here is harder."""
    assert cli.main(["decision", "record", "--decision", "REJECTED",
                     "--reason", "right diagnosis, but the fix is a product "
                                 "call I am not making this quarter",
                     "--product", PRODUCT, "--subject", "Rework the AOV card"]) == 0
    (row,) = rows(console)
    assert row["decision"] == "REJECTED"
    assert "product call" in row["reason"]


def test_a_deferral_is_a_decision_not_a_silence(cli, console):
    assert cli.main(["decision", "record", "--decision", "DEFERRED",
                     "--reason", "waiting on the HIB sync window to clear",
                     "--product", PRODUCT, "--subject", "Churn snapshots"]) == 0
    assert rows(console)[0]["decision"] == "DEFERRED"


def test_the_reason_is_required_by_the_parser_too(cli):
    """Not only by the database. A missing reason should not reach a connection."""
    with pytest.raises(SystemExit):
        cli.main(["decision", "record", "--decision", "REJECTED",
                  "--product", PRODUCT, "--subject", "x"])


def test_the_cli_refuses_the_backfill_sentinel_with_a_sentence(cli, console, capsys):
    """The database refuses it too. This refuses it in words a person reads."""
    assert cli.main(["decision", "record", "--decision", "REJECTED",
                     "--reason", "UNRECORDED", "--product", PRODUCT,
                     "--subject", "x"]) == 2
    assert "reserved to backfilled rows" in capsys.readouterr().err
    assert rows(console) == []


def test_product_defaults_to_the_cited_issues_product(cli, console, admin):
    issue = add_issue(admin)
    admin.execute("COMMIT")
    assert cli.main(["decision", "record", "--decision", "APPROVED",
                     "--reason", "the gap is real and it is ours",
                     "--issue", str(issue)]) == 0
    (row,) = rows(console)
    assert row["product"] == PRODUCT
    assert "MISSING_ANALYTICS_ORDER" in row["subject"]   # captured, not typed
    assert row["evidence"][0]["kind"] == "issue"


def test_a_decision_citing_nothing_needs_a_product(cli, console, capsys):
    assert cli.main(["decision", "record", "--decision", "APPROVED",
                     "--reason", "because", "--subject", "x"]) == 2
    assert "no --product" in capsys.readouterr().err


# ---- list and show ---------------------------------------------------------

def test_list_shows_the_derived_outcome(cli, console, admin, capsys):
    task = add_task(console, title="Refund reporting")
    add_run(admin, task, "3.75", status="AWAITING_HUMAN")
    merge_task(console, admin, task)
    admin.execute("COMMIT")
    cli.main(["decision", "record", "--decision", "APPROVED", "--reason",
              "parity with Metorik", "--product", PRODUCT, "--task", str(task)])

    assert cli.main(["decision", "list"]) == 0
    out = capsys.readouterr().out
    assert "DELIVERED" in out and "£3.75" in out


def test_list_filters_by_issue_and_by_product(cli, console, admin, capsys):
    issue = add_issue(admin)
    admin.execute("COMMIT")
    cli.main(["decision", "record", "--decision", "APPROVED", "--reason", "a",
              "--issue", str(issue), "--subject", "cited the issue"])
    cli.main(["decision", "record", "--decision", "REJECTED", "--reason", "b",
              "--product", "fleet", "--subject", "cited nothing"])
    capsys.readouterr()

    cli.main(["decision", "list", "--issue", str(issue)])
    out = capsys.readouterr().out
    assert "cited the issue" in out and "cited nothing" not in out

    cli.main(["decision", "list", "--product", "fleet"])
    out = capsys.readouterr().out
    assert "cited nothing" in out and "cited the issue" not in out


def test_show_prints_the_evidence_and_the_derived_outcome(cli, console, admin,
                                                          capsys):
    issue = add_issue(admin)
    admin.execute("UPDATE issues SET current_magnitude=29603 WHERE id=%s",
                  (issue,))
    admin.execute("COMMIT")
    cli.main(["decision", "record", "--decision", "APPROVED", "--reason",
              "the reconciliation gap is real", "--issue", str(issue)])
    capsys.readouterr()

    assert cli.main(["decision", "show", "1"]) == 0
    out = capsys.readouterr().out
    assert "29603" in out
    assert "STILL_OPEN" in out
    assert "recomputed now" in out


def test_show_on_a_missing_decision_says_so(cli, capsys):
    assert cli.main(["decision", "show", "99"]) == 2
    assert "no decision 99" in capsys.readouterr().err


# ---- backfill --------------------------------------------------------------

class TestBackfill:
    """Reconstructed rows, and the two properties that make that safe."""

    def test_a_dry_run_is_the_default_and_writes_nothing(self, cli, console,
                                                         capsys):
        add_task(console, title="Refund reporting")
        assert cli.main(["decision", "backfill"]) == 0
        assert "Dry run" in capsys.readouterr().out
        assert rows(console) == []

    def test_execute_writes_one_decision_per_task(self, cli, console):
        add_task(console, title="Refund reporting")
        add_task(console, title="Order list filters")
        assert cli.main(["decision", "backfill", "--execute"]) == 0
        written = rows(console)
        assert len(written) == 2
        assert {r["subject"] for r in written} == {"Refund reporting",
                                                  "Order list filters"}

    def test_no_reason_is_invented(self, cli, console):
        """The whole rule for this command."""
        add_task(console, title="Refund reporting")
        cli.main(["decision", "backfill", "--execute"])
        (row,) = rows(console)
        assert row["reason"] == "UNRECORDED"
        assert row["decided_by"] == "UNRECORDED"

    def test_backfilled_rows_are_marked_on_both_axes(self, cli, console):
        add_task(console)
        cli.main(["decision", "backfill", "--execute"])
        (row,) = rows(console)
        assert row["origin"] == "BACKFILLED"
        assert row["confidence"] == "INFERRED"

    def test_the_decision_is_dated_when_the_work_was_chosen(self, cli, console):
        """Not when it merged. The merge is an outcome and the view derives it."""
        task = add_task(console)
        created = console.execute("SELECT created_at FROM tasks WHERE id=%s",
                                  (task,)).fetchone()["created_at"]
        cli.main(["decision", "backfill", "--execute"])
        assert rows(console)[0]["decided_at"] == created

    def test_the_outcome_is_still_derived_for_a_backfilled_row(
            self, cli, console, admin):
        task = add_task(console, attempts=2)
        add_run(admin, task, "1.00")
        add_run(admin, task, "2.50", status="AWAITING_HUMAN")
        merge_task(console, admin, task)
        admin.execute("COMMIT")
        cli.main(["decision", "backfill", "--execute"])
        (row,) = rows(console)
        assert row["task_outcome"] == "DELIVERED"
        assert float(row["total_cost_gbp"]) == 3.50
        assert row["attempts_to_green"] == 2

    def test_running_it_twice_adds_nothing(self, cli, console, capsys):
        add_task(console)
        cli.main(["decision", "backfill", "--execute"])
        capsys.readouterr()
        assert cli.main(["decision", "backfill", "--execute"]) == 0
        assert "nothing to backfill" in capsys.readouterr().out
        assert len(rows(console)) == 1

    def test_an_unmapped_repo_stops_rather_than_defaulting(self, cli, console,
                                                           capsys):
        """A silently-defaulted product files a row under a product nobody chose.

        `tasks.repo` is immutable once written, so this arranges the state at
        insert rather than by editing it afterwards -- which is also the only
        way it could arise in production.
        """
        add_task(console, repo="some-other-repo")
        assert cli.main(["decision", "backfill", "--execute"]) == 2
        assert "no product mapping" in capsys.readouterr().err
        assert rows(console) == []

    def test_the_list_marks_reconstructed_rows(self, cli, console, capsys):
        add_task(console, title="Refund reporting")
        cli.main(["decision", "backfill", "--execute"])
        capsys.readouterr()
        cli.main(["decision", "list"])
        out = capsys.readouterr().out
        assert "reconstructed" in out
