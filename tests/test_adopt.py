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


# ---- the readers pick their run by the branch, not by recency ---------------

class TestRecencyIsNotIdentity:
    """What adoption broke the first time it was used, and how it was found.

    Every reader took the NEWEST run of a task and treated its patch step as
    the thing to check `branch_name` against. That was correct only because the
    runner writes branch_name from the run it has just finished, so the two
    were the same row BY CONSTRUCTION. Adoption is the first operation that
    points branch_name at an older run's branch.

    On the first adoption -- task 69, fleet/task-69.3 from run 44 -- the accept
    page compared that branch's tip against run 45's patch sha, which belonged
    to fleet/task-69.4, and reported: "fleet/task-69.3 is at cb4b80f5841c but
    the run verified c585d46faf8b." Two branches, one comparison, and a
    sentence that reads as tampering.

    IT FAILED CLOSED, which is the only reason this is a test rather than an
    incident: preflight refuses on tip mismatch, so nothing merged and nothing
    could be accepted. The task was stuck, not at risk.
    """

    @pytest.fixture
    def two_runs(self, console, runner, agent_conn, verifier_conn, repo):
        """Task 69's shape: an older green run, a newer one on another branch."""
        sh(repo, "git", "checkout", "-q", "-b", "fleet/task-1.2", "main")
        (repo / "thing.py").write_text("value = 99\n")
        sh(repo, "git", "commit", "-qam", "the rebuild")
        sh(repo, "git", "checkout", "-q", "main")

        task = failed_task(console, runner, verifier_conn, repo)   # run A, .3-like
        older = runner.execute(
            "SELECT id FROM runs WHERE task_id=%s ORDER BY id DESC LIMIT 1",
            (task,)).fetchone()["id"]
        agent_conn.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
            " VALUES (%s, 1, 'PATCH_PROPOSED', 'fleet-runner/agent', %s)",
            (older, Jsonb({"base_commit_sha": base_sha(repo),
                           "patch_commit_sha": head_sha(repo, "fleet/task-1")})))
        newer = runner.execute(
            "INSERT INTO runs (task_id, work_type, contract_version,"
            " spend_limit_gbp, status) VALUES (%s, 'dd_api', 1, 3.00, 'FAILED')"
            " RETURNING id", (task,)).fetchone()["id"]
        # Committed before the agent references it: two connections, and the
        # second cannot see the first's uncommitted row.
        runner.commit()
        agent_conn.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
            " VALUES (%s, 1, 'PATCH_PROPOSED', 'fleet-runner/agent', %s)",
            (newer, Jsonb({"base_commit_sha": base_sha(repo),
                           "patch_commit_sha": head_sha(repo, "fleet/task-1.2")})))
        agent_conn.commit()
        return task, older, newer

    def test_the_query_finds_the_run_by_the_commit(self, dsns, two_runs, repo,
                                                    monkeypatch):
        from console import queries
        task, older, newer = two_runs
        assert queries.patch_for_tip(task, head_sha(repo))["run_id"] == older
        assert queries.patch_for_tip(
            task, head_sha(repo, "fleet/task-1.2"))["run_id"] == newer

    def test_the_adopted_branch_selects_its_own_run_not_the_newest(
            self, dsns, console, runner, verifier_conn, two_runs, repo, settings):
        """The exact inversion: branch_name is the OLDER run's branch."""
        from console import app
        task, older, newer = two_runs
        row = console.execute("SELECT * FROM tasks WHERE id=%s", (task,)).fetchone()
        run_id, patch, tip = app._patch_for_branch(row)
        assert run_id == older, "the newest run verified a different branch"
        assert patch["patch_commit_sha"] == head_sha(repo)
        assert tip == head_sha(repo)

    def test_a_commit_nothing_verified_is_a_refusal_and_not_the_newest_run(
            self, dsns, console, runner, verifier_conn, two_runs, repo, settings):
        """The guard preflight was built for, kept: a commit appended after
        verification must not silently borrow another run's shas."""
        from console import app
        task, older, newer = two_runs
        sh(repo, "git", "checkout", "-q", "fleet/task-1")
        (repo / "thing.py").write_text("value = 4\n")
        sh(repo, "git", "commit", "-qam", "appended after the checks")
        sh(repo, "git", "checkout", "-q", "main")
        row = console.execute("SELECT * FROM tasks WHERE id=%s", (task,)).fetchone()
        run_id, patch, tip = app._patch_for_branch(row)
        assert run_id is None and patch == {}
        assert tip == head_sha(repo), "the tip resolved; it is the RUN that is missing"

    def test_a_branch_git_cannot_resolve_is_a_different_nothing(
            self, dsns, console, runner, verifier_conn, two_runs, repo, settings):
        """No checkout, no ref, no git -- preflight's sentence, not this one.
        Reporting 'nothing verified this branch' for a branch that does not
        exist is the same substitution pointed the other way."""
        from console import app
        task, _older, _newer = two_runs
        console.execute("UPDATE tasks SET branch_name='fleet/task-nope'"
                        " WHERE id=%s", (task,))
        console.commit()
        row = console.execute("SELECT * FROM tasks WHERE id=%s", (task,)).fetchone()
        run_id, patch, tip = app._patch_for_branch(row)
        assert run_id is None and tip == ""


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


# ---- 042: a check that fails identically on the base ------------------------

def base_step(conn, task_id: int, *, base, checks, patch="") -> int:
    """The evidence `console.adopt.corroborate` writes, as the console writes it.

    Inserted rather than produced, because what is under test here is the
    JUDGEMENT of the evidence -- 042's clause and _corroboration_for, which
    have to agree. Producing it would mean running a suite inside a unit test
    to assert something about SQL.
    """
    run = conn.execute("SELECT id FROM runs WHERE task_id=%s ORDER BY id DESC",
                       (task_id,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
        " VALUES (%s, 9, 'BASE_CHECK_RUN', 'fleet-console/adopt', %s)",
        (run, Jsonb({"base_commit_sha": base, "patch_commit_sha": patch,
                     "checks": checks})))
    conn.commit()
    return run


class TestACheckThatFailsOnTheBaseIsNotEvidence:
    """042, at the database. Task 100: five checks green, one failing on a
    migration tally the BASE had already broken, branch touching neither.

    Every test here moves the row by hand, for the reason the class above
    gives: console/adopt.py refuses first and refuses better, but the wall has
    to be in the database or the rule is advice.
    """

    def test_a_corroborated_failure_can_be_adopted(
            self, dsns, console, runner, verifier_conn, repo):
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("ruff"), check("pytest", exit_code=1)]))
        base_step(console, task, base=base_sha(repo),
                  checks=[check("pytest", exit_code=1)])
        move_to_ready(console, task)
        assert console.execute("SELECT status FROM tasks WHERE id=%s",
                               (task,)).fetchone()["status"] == "READY_FOR_REVIEW"

    def test_a_different_exit_code_does_not_corroborate(
            self, dsns, console, runner, verifier_conn, repo):
        """The base fails, but not the same way. That is two failures, not one
        fact about the branch."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("pytest", exit_code=1)]))
        base_step(console, task, base=base_sha(repo),
                  checks=[check("pytest", exit_code=2)])
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_a_different_command_does_not_corroborate(
            self, dsns, console, runner, verifier_conn, repo):
        """Matched on the command, never on position: a contract edited between
        the run and now would otherwise excuse one check with another's
        evidence."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("pytest", exit_code=1)]))
        base_step(console, task, base=base_sha(repo),
                  checks=[check("ruff", exit_code=1)])
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_evidence_against_another_base_does_not_corroborate(
            self, dsns, console, runner, verifier_conn, repo):
        """Corroboration is against the base the RUN recorded. A base check run
        somewhere else answers a question nobody asked."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("pytest", exit_code=1)]))
        base_step(console, task, base="0" * 40,
                  checks=[check("pytest", exit_code=1)])
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_a_timeout_is_excused_by_nothing(
            self, dsns, console, runner, verifier_conn, repo):
        """A timeout corroborated by a timeout is how a busy box adopts a
        branch nobody judged."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("pytest", exit_code=1, timed_out=True)]))
        base_step(console, task, base=base_sha(repo),
                  checks=[check("pytest", exit_code=1, timed_out=True)])
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    @pytest.mark.parametrize("reason", ["unresolved_reason", "undecided_reason"])
    def test_a_check_that_never_answered_is_excused_by_nothing(
            self, dsns, console, runner, verifier_conn, repo, reason):
        """It did not judge the tree here, so nothing about another tree can
        rescue it."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("pytest", exit_code=1, **{reason: "SIGKILL"})]))
        base_step(console, task, base=base_sha(repo),
                  checks=[check("pytest", exit_code=1, **{reason: "SIGKILL"})])
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    @pytest.mark.parametrize("reason", ["skipped_reason", "unresolved_reason",
                                        "undecided_reason"])
    def test_a_base_check_that_did_not_run_is_not_evidence(
            self, dsns, console, runner, verifier_conn, repo, reason):
        """The base run has to have LOOKED. A base check that was skipped
        because the clone had no node_modules says nothing about the base."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("pytest", exit_code=1)]))
        base_step(console, task, base=base_sha(repo),
                  checks=[check("pytest", exit_code=1, **{reason: "no deps"})])
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)

    def test_a_protected_path_is_still_refused_however_corroborated(
            self, dsns, console, runner, verifier_conn, repo):
        """042 widened one clause and no other. A run that wrote to the suite
        that judges it cannot have its checks believed, corroborated or not."""
        task = failed_task(console, runner, verifier_conn, repo, pay=payload(
            repo, checks=[check("pytest", exit_code=1)],
            violations={"protected": {"api/tests/**": ["api/tests/x.py"]},
                        "outside_writable": [], "over_diff_limit": False}))
        base_step(console, task, base=base_sha(repo),
                  checks=[check("pytest", exit_code=1)])
        with pytest.raises(psycopg.errors.RaiseException):
            move_to_ready(console, task)


class TestTheModuleAndTheDatabaseAgreeOnCorroboration:
    """_corroboration_for mirrors 042's clause. Two places decide this, and the
    module can only ever be the more conservative of the two."""

    BASE = "a" * 40

    def _payload(self, **over):
        p = {"base_commit_sha": self.BASE, "checks": [check("pytest", exit_code=1)],
             "boundary_violations": {"protected": {}, "outside_writable": []}}
        p.update(over)
        return p

    def _evidence(self, **over):
        c = check("pytest", exit_code=1)
        c.update(over)
        return {"base_commit_sha": self.BASE, "checks": [c]}

    def test_it_excuses_the_same_failure(self):
        p = self._payload()
        assert adopt._verification_is_green(p, [self._evidence()]) is True

    def test_it_excuses_nothing_without_evidence(self):
        assert adopt._verification_is_green(self._payload(), []) is False

    def test_a_green_check_needs_no_evidence_and_gets_none(self):
        p = self._payload(checks=[check("pytest", exit_code=0)])
        assert adopt._verification_is_green(p, []) is True

    def test_a_payload_of_skips_is_still_not_a_pass(self):
        """042 left the ran-at-all half alone, and this is the half people
        drop when they widen the other one."""
        p = self._payload(checks=[check("tsc", skipped_reason="no .ts files")])
        assert adopt._verification_is_green(p, [self._evidence()]) is False

    @pytest.mark.parametrize("over,why", [
        ({"exit_code": 2}, "a different exit code"),
        ({"timed_out": True}, "a timeout"),
        ({"skipped_reason": "no deps"}, "a skipped base check"),
        ({"unresolved_reason": "missing"}, "an unresolved base check"),
        ({"undecided_reason": "SIGKILL"}, "an undecided base check"),
    ])
    def test_what_does_not_corroborate(self, over, why):
        assert adopt._verification_is_green(
            self._payload(), [self._evidence(**over)]) is False, why

    def test_evidence_for_another_base_is_ignored(self):
        ev = self._evidence()
        ev["base_commit_sha"] = "b" * 40
        assert adopt._verification_is_green(self._payload(), [ev]) is False

    def test_the_refusal_names_the_remedy(self):
        why = adopt._why_not_green(self._payload(), [])
        assert "--corroborate-base" in why

    def test_a_check_that_cannot_speak_at_the_base_excuses_nothing(self):
        """15 Sep 2026, and the reason the citation gate now exits 2 there.

        contracts/checks/spec_requirements_cited.py reads `git diff BASE..HEAD`.
        At a corroboration run BASE and HEAD are the same commit, so the diff is
        empty, so nothing is cited, so it failed -- for every branch, whatever
        the branch did. Matched on command and exit code, which is all this
        function and 042 compare, that excused the one gate in the path that
        reads a spec.

        The check now reports 2 there. This asserts the half that lives on THIS
        side: a 2 at the base is not evidence, so the branch's 1 stands.
        """
        cite = "spec_requirements_cited.py"
        p = self._payload(checks=[check(cite, exit_code=1)])
        at_base = {"base_commit_sha": self.BASE,
                   "checks": [check(cite, exit_code=2,
                                    undecided_reason="exited 2, COULD NOT RUN")]}
        assert adopt._verification_is_green(p, [at_base]) is False

    def test_the_old_hole_is_what_it_would_have_done(self):
        """Stated as its own test so the regression is legible rather than
        implied: had the check kept returning 1 at the base, this is the excuse
        it would have manufactured for itself, on any branch at all."""
        cite = "spec_requirements_cited.py"
        p = self._payload(checks=[check(cite, exit_code=1)])
        as_it_was = {"base_commit_sha": self.BASE,
                     "checks": [check(cite, exit_code=1)]}
        assert adopt._verification_is_green(p, [as_it_was]) is True


    def test_it_does_not_name_the_remedy_for_a_check_that_cannot_use_it(self):
        """Offering --corroborate-base for a timeout would send someone to run
        a suite for nothing."""
        p = self._payload(checks=[check("pytest", exit_code=1, timed_out=True)])
        why = adopt._why_not_green(p, [])
        assert "--corroborate-base" not in why
        assert "timed out" in why

class TestAnObligationIsNeverCorroborable:
    """046, and the other half of the corroborate fix.

    Making spec_requirements_cited.py exit 2 at the base closes the hole for
    THAT check. This closes it for the class: an obligation is owed BY THE
    BRANCH, the base has no branch and owes nothing, so a base run of such a
    check refuses identically for every branch. That is an excuse, not
    evidence -- and a check that forgets the base-run rule must still not be
    excusable on one.
    """

    BASE = "a" * 40

    def _p(self, c):
        return {"base_commit_sha": self.BASE, "checks": [c],
                "boundary_violations": {"protected": {}, "outside_writable": []}}

    def _owes(self, **over):
        c = check("cite", exit_code=3, obligation_reason="uncited: 5, 6, 7")
        c.update(over)
        return c

    def test_an_obligation_is_not_green(self):
        assert adopt._check_is_green(self._owes()) is False

    def test_an_obligation_is_not_excusable(self):
        why = adopt._excusable(self._owes())
        assert why and "the base owes" in why

    def test_an_obligation_cannot_be_corroborated_by_an_obligation(self):
        ev = [{"base_commit_sha": self.BASE, "checks": [self._owes()]}]
        assert adopt._corroboration_for(self._owes(), ev, self.BASE) is None
        assert adopt._verification_is_green(self._p(self._owes()), ev) is False

    def test_an_obligation_cannot_be_corroborated_by_a_plain_failure(self):
        """Matching exit codes are not matching causes, and here they are not
        even matching KINDS."""
        plain = check("cite", exit_code=3)
        ev = [{"base_commit_sha": self.BASE, "checks": [plain]}]
        assert adopt._corroboration_for(self._owes(), ev, self.BASE) is None

    def test_a_base_obligation_excuses_nothing_at_all(self):
        """The other direction. A base check that reports an obligation is a
        base run answering a question about a branch that is not applied."""
        plain = check("cite", exit_code=3)
        ev = [{"base_commit_sha": self.BASE, "checks": [self._owes()]}]
        assert adopt._corroboration_for(plain, ev, self.BASE) is None

    def test_a_plain_failure_is_still_corroborable(self):
        """The rule 042 exists for, and this must not widen over it. Task 100:
        a migration tally the base had already broken."""
        c = check("pytest", exit_code=1)
        ev = [{"base_commit_sha": self.BASE, "checks": [check("pytest", exit_code=1)]}]
        assert adopt._corroboration_for(c, ev, self.BASE) is not None
        assert adopt._verification_is_green(self._p(c), ev) is True


class TestTheBaseRunIsNotHandedFilesTheBaseDoesNotHave:
    """The structural half of the same rule, 15 Sep 2026.

    `changed` is the BRANCH's file list. Expanding `{changed_files}` with it at
    the base names paths that are not there -- a file the branch ADDED cannot
    be checked on a tree that does not have it, and the error that produces is
    about the missing file, not about the base.

    Files the branch MODIFIED are kept, deliberately. Those exist at the base,
    a check over them asks a real question there, and task 100's kind of excuse
    has to survive this.
    """

    def test_added_files_are_dropped_and_modified_files_are_kept(self, tmp_path):
        trial = tmp_path / "trial"
        (trial / "api").mkdir(parents=True)
        (trial / "api" / "engine.py").write_text("x = 1\n")
        changed = ["api/engine.py", "api/tests/test_fleet_new.py"]
        at_base = [f for f in changed if (trial / f).exists()]
        assert at_base == ["api/engine.py"]

    def test_a_placeholder_over_added_files_alone_is_skipped(self, tmp_path):
        """And a skipped base check excuses nothing -- which is the point of
        dropping them rather than letting the command fail on a missing path."""
        from runner import verify
        cmd = "compileall {changed_files:.py}"
        expanded, had, matched = verify.expand_changed_files(cmd, [])
        assert had and matched == 0
        result = verify.run(tmp_path, [cmd], 30.0, changed=[])
        assert len(result.checks) == 1
        assert result.checks[0].skipped_reason is not None
        assert adopt._corroboration_for(
            {"command": cmd, "exit_code": 1, "skipped_reason": None,
             "unresolved_reason": None, "undecided_reason": None,
             "timed_out": False},
            [{"base_commit_sha": "b",
              "checks": [{"command": cmd, "exit_code": 1,
                          "skipped_reason": "no changed file matched",
                          "unresolved_reason": None, "undecided_reason": None,
                          "timed_out": False}]}],
            "b") is None
