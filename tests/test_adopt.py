"""Adopting a verified branch instead of rebuilding it. 038, console/adopt.py.

TASK 69 IS THE WHOLE ARGUMENT AND IT COST £15.06. Four runs off one spec and
one base commit. Run 44's branch passed all six of its contract's checks and
was refused by max_test_diff_lines at a value retired the same day; there was
no edge from FAILED to READY_FOR_REVIEW, so the only way back in was QUEUED,
and QUEUED means the agent writes the change again. It wrote a different one --
377, 606, 439, 385 lines across the four -- and the rebuild failed ruff on a
single new I001.

The precondition is the point. Three of those four runs must NOT be adoptable,
and two of them never opened a check at all: a run refused before verification
proved nothing about its branch, and by STATUS it is indistinguishable from the
one that proved everything. So the test of adoptability reads the recorded
payload, and these tests are mostly about the ways a payload can look green
without being green.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from console import adopt
from runner import verify
from tests.support import PLATFORM_FLOOR

REPO = "deadly-digital-platform"


def sh(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    """A base branch with one commit on top of it, as a run would leave."""
    root = tmp_path / "repos"
    (root / REPO).mkdir(parents=True)
    r = root / REPO
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "t")
    (r / "thing.py").write_text("value = 1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    sh(r, "git", "checkout", "-q", "-b", "fleet/task-1")
    (r / "thing.py").write_text("value = 2\n")
    sh(r, "git", "commit", "-qam", "work")
    sh(r, "git", "checkout", "-q", "main")
    return r


@pytest.fixture
def settings(repo, monkeypatch):
    monkeypatch.setattr(adopt.config, "repo_root", lambda: repo.parent)
    return repo


def base_sha(repo: Path) -> str:
    return sh(repo, "git", "rev-parse", "main^{commit}")


def head_sha(repo: Path, branch="fleet/task-1") -> str:
    return sh(repo, "git", "rev-parse", f"{branch}^{{commit}}")


def check(command="pytest", exit_code=0, **over) -> dict:
    c = {"command": command, "expanded": command, "exit_code": exit_code,
         "duration_ms": 10, "timed_out": False, "skipped_reason": None,
         "unresolved_reason": None, "undecided_reason": None, "output_tail": ""}
    c.update(over)
    return c


def payload(repo: Path, *, checks=None, skipped=None, violations=None,
            branch="fleet/task-1") -> dict:
    """Run 44's shape: FAIL overall, boundary dirty on size, checks green."""
    return {
        "result": "FAIL",
        "boundary_clean": False,
        "base_commit_sha": base_sha(repo),
        "patch_commit_sha": head_sha(repo, branch),
        "contract_version": 1,
        "verification_skipped": skipped,
        "verification_unresolved": None,
        "verification_undecided": None,
        "checks": [check()] if checks is None else checks,
        "boundary_violations": violations if violations is not None else {
            "protected": {}, "outside_writable": [], "over_diff_limit": False,
            "diff_lines": 784, "prod_diff_lines": 345, "test_diff_lines": 439,
            "over_test_limit": True, "max_test_diff_lines": 400},
    }


def failed_task(console, runner, verifier_conn, repo, *, pay=None,
                status="FAILED", branch="fleet/task-1") -> int:
    """A task that ran, produced a branch and failed -- by the real route.

    Each write goes through the identity the database accepts it from: the
    console queues, the runner claims and fails, the verifier records the
    verification. Driving all three through one connection would build a row
    no production path can produce, which is the way a fixture ends up
    proving something about itself.
    """
    task = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch,"
        " acceptance_contract, max_cost_gbp, status, branch_name, attempts,"
        " max_attempts) VALUES ('t', '# t', %s, 'main', %s, 3.00, 'QUEUED',"
        " %s, 1, 1) RETURNING id",
        (REPO, Jsonb({"work_type": "dd_api",
                      "protected_paths": PLATFORM_FLOOR}), branch)).fetchone()["id"]
    console.commit()

    run = runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version,"
        " spend_limit_gbp, status) VALUES (%s, 'dd_api', 1, 3.00, 'ACTIVE')"
        " RETURNING id", (task,)).fetchone()["id"]
    runner.commit()

    verifier_conn.execute(
        "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
        " VALUES (%s, 2, 'VERIFICATION_RUN', 'fleet-runner/verifier', %s)",
        (run, Jsonb(pay if pay is not None else payload(repo, branch=branch))))
    verifier_conn.commit()

    runner.execute("UPDATE runs SET status='FAILED' WHERE id=%s", (run,))
    if status == "FAILED":
        # QUEUED -> RUNNING -> FAILED, which is the only road there.
        runner.execute("UPDATE tasks SET status='RUNNING' WHERE id=%s", (task,))
        runner.execute("UPDATE tasks SET status='FAILED' WHERE id=%s", (task,))
    runner.commit()
    return task


def move_to_ready(conn, task_id: int, branch="fleet/task-1"):
    conn.execute("UPDATE tasks SET status='READY_FOR_REVIEW', branch_name=%s"
                 " WHERE id=%s", (branch, task_id))
    conn.commit()


# ---- the edge itself, at the database ---------------------------------------

class TestTheDatabaseDecidesWhatIsAdoptable:
    """038's trigger, which is the half of the precondition the DB can hold.

    Everything here bypasses console/adopt.py on purpose. The module refuses
    first and refuses better, but it is not what makes adoption safe -- a hand
    UPDATE has to hit the same wall, or the precondition is advice.
    """

    def test_a_green_run_can_be_adopted(self, dsns, console, runner, verifier_conn, repo):
        task = failed_task(console, runner, verifier_conn, repo)
        move_to_ready(console, task)
        assert console.execute("SELECT status FROM tasks WHERE id=%s",
                               (task,)).fetchone()["status"] == "READY_FOR_REVIEW"

    def test_a_run_refused_before_its_checks_opened_is_not(
            self, dsns, console, runner, verifier_conn, repo):
        """Runs 41 and 43. By status they are identical to run 44; by payload
        they are empty, and this is the case the whole precondition is for."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[], skipped="boundary violation"))
        with pytest.raises(psycopg.errors.RaiseException,
                           match="no run whose recorded checks were green"):
            move_to_ready(console, task)

    def test_a_failing_check_is_not(self, dsns, console, runner, verifier_conn, repo):
        """Run 45: boundary clean and one new I001. Not adoptable either."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(repo, checks=[
            check("spec_requirements_cited.py"), check("ruff", exit_code=1)]))
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_a_payload_of_skips_is_not(self, dsns, console, runner, verifier_conn, repo):
        """Every check passed and not one of them looked at anything.
        Verification.passed's own second half, which is easy to drop."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(repo, checks=[
            check("tsc", skipped_reason="no .ts files changed"),
            check("vitest", skipped_reason="no .ts files changed")]))
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    @pytest.mark.parametrize("reason", ["unresolved_reason", "undecided_reason"])
    def test_a_check_that_never_answered_is_not(
            self, dsns, console, runner, verifier_conn, repo, reason):
        """Exit 0 and nothing established. A checker that is not on disk, or
        one the kernel killed -- both exit somehow and neither is a verdict."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(repo, checks=[
            check("tsc", exit_code=0, **{reason: "SIGKILL (128+9)"})]))
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_a_timed_out_check_is_not(self, dsns, console, runner, verifier_conn, repo):
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(repo, checks=[
            check("pytest", exit_code=0, timed_out=True)]))
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_a_protected_path_is_not_adoptable_however_green(
            self, dsns, console, runner, verifier_conn, repo):
        """The suite is on the protected list. A change that rewrote it cannot
        be judged by it, whatever the checks came back saying."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, violations={"protected": {"api/tests/t.py": "api/tests/**"},
                              "outside_writable": []}))
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_a_file_outside_the_contract_is_not_either(
            self, dsns, console, runner, verifier_conn, repo):
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, violations={"protected": {}, "outside_writable": ["README.md"]}))
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_the_runner_may_not_adopt_its_own_failure(
            self, dsns, console, verifier_conn, runner, repo):
        """The role, not the payload. A runner that can adopt can promote the
        branch it just failed, which is the separation this track rests on."""
        task = failed_task(console, runner, verifier_conn, repo)
        with pytest.raises(psycopg.errors.RaiseException, match="requires"):
            move_to_ready(runner, task)

    def test_a_branchless_task_is_still_refused(
            self, dsns, console, runner, verifier_conn, repo):
        """The older precondition, unchanged by 038."""
        task = failed_task(console, runner, verifier_conn, repo)
        console.execute("UPDATE tasks SET branch_name=NULL WHERE id=%s", (task,))
        console.commit()
        with pytest.raises(psycopg.errors.RaiseException, match="without a branch"):
            console.execute("UPDATE tasks SET status='READY_FOR_REVIEW'"
                            " WHERE id=%s", (task,))

    def test_the_runners_own_edge_is_untouched(self, dsns, console):
        row = console.execute(
            "SELECT required_role FROM task_transitions WHERE from_status='RUNNING'"
            " AND to_status='READY_FOR_REVIEW'").fetchone()
        assert row["required_role"] == "fleet_task_runner"


# ---- the half that lives in git ---------------------------------------------

class TestTheTreeIsAskedTheTwoQuestionsTheRowCannotAnswer:

    def test_it_adopts_the_branch_it_verified(self, dsns, console, runner,
                                              verifier_conn, repo, settings):
        task = failed_task(console, runner, verifier_conn, repo)
        decided = adopt.adopt(task, "fleet/task-1")
        assert decided.head_sha == head_sha(repo)
        assert decided.base_sha == base_sha(repo)
        row = console.execute("SELECT status, branch_name FROM tasks WHERE id=%s",
                              (task,)).fetchone()
        assert row["status"] == "READY_FOR_REVIEW"
        assert row["branch_name"] == "fleet/task-1"

    def test_a_branch_that_moved_since_it_was_checked_is_refused(
            self, dsns, console, runner, verifier_conn, repo, settings):
        """The checks looked at a commit. This is no longer that commit."""
        task = failed_task(console, runner, verifier_conn, repo)
        sh(repo, "git", "checkout", "-q", "fleet/task-1")
        (repo / "thing.py").write_text("value = 3\n")
        sh(repo, "git", "commit", "-qam", "more")
        sh(repo, "git", "checkout", "-q", "main")
        with pytest.raises(adopt.NotAdoptable, match="no run of task"):
            adopt.plan(task, "fleet/task-1")

    def test_a_base_that_moved_is_refused(self, dsns, console, runner, verifier_conn,
                                          repo, settings):
        """Green against 871f165d is not green against whatever main becomes."""
        task = failed_task(console, runner, verifier_conn, repo)
        (repo / "other.py").write_text("x = 1\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "base moved")
        with pytest.raises(adopt.NotAdoptable, match="the base has moved"):
            adopt.plan(task, "fleet/task-1")
        assert console.execute("SELECT status FROM tasks WHERE id=%s",
                               (task,)).fetchone()["status"] == "FAILED"

    def test_a_task_that_is_not_failed_is_refused(self, dsns, console, runner,
                                                  verifier_conn, repo, settings):
        task = failed_task(console, runner, verifier_conn, repo, status="QUEUED")
        with pytest.raises(adopt.NotAdoptable, match="is QUEUED, not FAILED"):
            adopt.plan(task, "fleet/task-1")

    def test_a_branch_name_git_should_not_be_handed_is_refused(
            self, dsns, console, runner, verifier_conn, repo, settings):
        task = failed_task(console, runner, verifier_conn, repo)
        with pytest.raises(adopt.NotAdoptable, match="not a branch name"):
            adopt.plan(task, "--upload-pack=touch /tmp/x")

    def test_the_refusal_names_the_failing_check(self, dsns, console, runner,
                                                 verifier_conn, repo, settings):
        """A refusal that says only 'not green' sends somebody to the database."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(repo, checks=[
            check("ruff_no_new_findings.py", exit_code=1)]))
        with pytest.raises(adopt.NotAdoptable,
                           match="ruff_no_new_findings.py"):
            adopt.plan(task, "fleet/task-1")

    def test_a_dry_run_writes_nothing(self, dsns, console, runner, verifier_conn,
                                      repo, settings):
        task = failed_task(console, runner, verifier_conn, repo)
        assert adopt.main(["--task", str(task), "--branch", "fleet/task-1",
                           "--dry-run"]) == 0
        assert console.execute("SELECT status FROM tasks WHERE id=%s",
                               (task,)).fetchone()["status"] == "FAILED"


# ---- the reimplementation is pinned to the original -------------------------

class TestGreenMeansWhatRunnerVerifyMeansByIt:
    """adopt.py and 038 both re-implement Verification.passed, on a payload
    instead of on objects. Three copies of one rule is two chances to drift,
    so the rule is asserted against the original rather than described."""

    CASES = [
        ("one green check", [verify.Check("pytest", 0, 10, "")]),
        ("a failing check", [verify.Check("ruff", 1, 10, "")]),
        ("green and failing", [verify.Check("a", 0, 1, ""),
                               verify.Check("b", 1, 1, "")]),
        ("all skipped", [verify.Check("tsc", 0, 1, "", skipped_reason="none")]),
        ("green plus a skip", [verify.Check("a", 0, 1, ""),
                               verify.Check("b", 0, 1, "", skipped_reason="none")]),
        ("unresolved", [verify.Check("a", 0, 1, "", unresolved_reason="gone")]),
        ("undecided", [verify.Check("a", 0, 1, "", undecided_reason="SIGKILL")]),
        ("timed out", [verify.Check("a", 0, 1, "", timed_out=True)]),
        ("no checks at all", []),
    ]

    @pytest.mark.parametrize("name,checks", CASES, ids=[c[0] for c in CASES])
    def test_the_payload_reading_agrees_with_the_objects(self, name, checks):
        v = verify.Verification(checks=list(checks))
        as_payload = {
            "verification_skipped": None,
            "checks": [{"command": c.command, "exit_code": c.exit_code,
                        "timed_out": c.timed_out,
                        "skipped_reason": c.skipped_reason,
                        "unresolved_reason": c.unresolved_reason,
                        "undecided_reason": c.undecided_reason} for c in checks],
        }
        assert adopt._verification_is_green(as_payload) is v.passed, name

    def test_a_skipped_verification_is_not_green_either(self):
        v = verify.Verification(skipped_reason="boundary violation")
        assert v.passed is False
        assert adopt._verification_is_green(
            {"verification_skipped": "boundary violation", "checks": []}) is False


def test_the_migration_is_the_one_the_database_is_running(dsns, console):
    """038 is applied by hand in production. The suite builds its template from
    the files, so this asserts the file and the live schema have not diverged
    in the one way that matters: the edge exists and it is the console's."""
    row = console.execute(
        "SELECT required_role, note FROM task_transitions"
        " WHERE from_status='FAILED' AND to_status='READY_FOR_REVIEW'").fetchone()
    assert row is not None, "038 has not been applied to this database"
    assert row["required_role"] == "fleet_console"
    assert "green" in row["note"]
    text = (Path(__file__).resolve().parent.parent
            / "038_a_verified_branch_can_be_adopted.sql").read_text()
    assert "FAILED' AND NEW.status = 'READY_FOR_REVIEW'" in text
