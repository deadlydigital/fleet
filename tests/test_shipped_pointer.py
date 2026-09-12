"""A task points at the decision that shipped it, and nothing acts on it.

specs/auto-approval.md §9.17. Four tasks -- 49, 51, 55, 58 -- read FAILED over
work that is on main, and `decision_outcomes` derived delivery from
`tasks.status` alone, so decision 31 rendered "task NOT_DELIVERED £1.90" over a
refund fix in production.

§9.3 refused a FAILED -> MERGED edge because it hands every future sweep the
rule "a failure may become a merge". THIS FILE'S JOB IS TO SHOW THAT THIS IS
NOT THAT. The pointer adds no edge and no status, and nothing reads it to
decide anything -- which is the only difference between the two, and therefore
the thing that has to be asserted rather than asserted about.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent



def _contract(console):
    """Built from `protected_path_floor`, never typed.

    `enforce_contract_floor()` refuses a contract that does not protect every
    floored path, and a hand-written protected list fails for a reason that has
    nothing to do with what is under test. Same rule as
    tests/test_autoapprove.py and the conftest docstring: when a test is about
    a value that DECIDES something, read the real artefact.
    """
    floor = [r["glob"] for r in console.execute(
        "SELECT glob FROM protected_path_floor WHERE repo=%s",
        ("deadly-digital-platform",)).fetchall()]
    return json.dumps({"work_type": "dd_api",
                       "writable_paths": ["api/analytics/services/order_query.py"],
                       "protected_paths": floor})


def _make_task(console, runner=None, admin=None, status=None):
    """A task, walked to `status` along the REAL edges.

    `enforce_task_transition()` refuses anything else, and the walk needs both
    roles because the machine splits them: only the runner may start or fail a
    task, only the console may merge one. Forcing the status with an UPDATE
    would be a fixture more permissive than production, and would be testing a
    state the system cannot reach.

    THERE IS NO FAILED -> MERGED EDGE IN `task_transitions`. That is §9.3's
    refusal, enforced in the database rather than argued in a comment, and it
    is the reason this whole feature is a pointer.
    """
    tid = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch,"
        " acceptance_contract, max_cost_gbp, timeout_seconds)"
        " VALUES ('t', '```fleet-spec\\nwork_type: dd_api\\n```',"
        " 'deadly-digital-platform', 'main', %s, 1.00, 600) RETURNING id",
        (_contract(console),)).fetchone()["id"]
    console.commit()
    if status in (None, "QUEUED"):
        return tid
    runner.execute("UPDATE tasks SET status='RUNNING' WHERE id=%s", (tid,))
    runner.commit()
    if status == "FAILED":
        runner.execute("UPDATE tasks SET status='FAILED' WHERE id=%s", (tid,))
        runner.commit()
    elif status == "MERGED":
        # The machine refuses READY_FOR_REVIEW without a branch AND without a
        # run, so the walk supplies both rather than side-stepping the rule.
        # The run is inserted by `admin`: 003 does not grant the runner INSERT
        # on runs from a test, which is that grant doing its job.
        admin.execute(
            "INSERT INTO runs (task_id, work_type, contract_version,"
            " spend_limit_gbp, committed_gbp, status)"
            # 1.00, not more: enforce_task_run_budget refuses a run whose
            # spend limit exceeds the task's max_cost_gbp, which is the ceiling
            # the fixture set above.
            " VALUES (%s,'dd_api',1,1.00,0.75,'AWAITING_HUMAN')", (tid,))
        admin.commit()
        runner.execute("UPDATE tasks SET status='READY_FOR_REVIEW',"
                       " branch_name=%s WHERE id=%s", (f"fleet/task-{tid}", tid))
        runner.commit()
        console.execute("UPDATE tasks SET status='MERGED' WHERE id=%s", (tid,))
        console.commit()
    else:
        raise AssertionError(f"no walk defined to {status}")
    return tid


def _make_decision(console, task_id):
    return console.execute(
        "INSERT INTO decision_log (product, subject, task_id, decision, reason)"
        " VALUES ('fleet', 's', %s, 'APPROVED', 'r') RETURNING id",
        (task_id,)).fetchone()["id"]


class TestTheConstraintMakesTheFalseStatementUnrepresentable:
    """A pointer may only name a decision that cites this very task."""

    def _task(self, console, runner, admin=None, status="FAILED"):
        return _make_task(console, runner, admin, status)

    def _decision(self, console, task_id):
        return _make_decision(console, task_id)

    def test_a_pointer_to_a_decision_that_cites_this_task_is_allowed(self, console, runner):
        tid = self._task(console, runner)
        did = self._decision(console, tid)
        console.execute("UPDATE tasks SET shipped_by_decision_id=%s WHERE id=%s",
                        (did, tid))
        console.commit()
        got = console.execute(
            "SELECT shipped_by_decision_id FROM tasks WHERE id=%s", (tid,)).fetchone()
        assert got["shipped_by_decision_id"] == did

    def test_a_pointer_to_a_decision_about_another_task_is_refused(self, console, runner):
        """The whole reason the key is composite."""
        import psycopg
        mine, theirs = self._task(console, runner), self._task(console, runner)
        theirs_decision = self._decision(console, theirs)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            console.execute("UPDATE tasks SET shipped_by_decision_id=%s WHERE id=%s",
                            (theirs_decision, mine))
        console.rollback()

    def test_a_pointer_to_a_decision_with_no_task_id_is_refused(self, console, runner):
        """Decision 25 exactly: "Merge task 49 by hand", task_id IS NULL. A
        pointer into a decision that does not admit to being about this task is
        the false statement the constraint exists to prevent, so it is refused
        and a new decision is written instead."""
        import psycopg
        tid = self._task(console, runner)
        loose = self._decision(console, None)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            console.execute("UPDATE tasks SET shipped_by_decision_id=%s WHERE id=%s",
                            (loose, tid))
        console.rollback()

    def test_null_is_the_ordinary_state(self, console, runner, admin):
        tid = self._task(console, runner, admin, status="MERGED")
        console.commit()
        got = console.execute(
            "SELECT shipped_by_decision_id FROM tasks WHERE id=%s", (tid,)).fetchone()
        assert got["shipped_by_decision_id"] is None, (
            "a MERGED task needs nobody to vouch for it")


class TestTheViewFollowsThePointer:
    def _shipped(self, console, runner, admin=None, status="FAILED"):
        t = _make_task(console, runner, admin, status)
        return t, _make_decision(console, t)

    def test_a_failed_task_with_a_pointer_reads_delivered_by_hand(self, console, runner):
        t, d = self._shipped(console, runner)
        console.execute("UPDATE tasks SET shipped_by_decision_id=%s WHERE id=%s", (d, t))
        console.commit()
        row = console.execute(
            "SELECT task_status, task_outcome, attempts_to_green"
            " FROM decision_outcomes WHERE id=%s", (d,)).fetchone()
        assert row["task_status"] == "FAILED", "the status is untouched"
        assert row["task_outcome"] == "DELIVERED_BY_HAND"
        assert row["attempts_to_green"] is None, (
            "it means the machine got this green, and it did not")

    def test_a_failed_task_without_one_still_reads_not_delivered(self, console, runner):
        t, d = self._shipped(console, runner)
        console.commit()
        row = console.execute(
            "SELECT task_outcome FROM decision_outcomes WHERE id=%s", (d,)).fetchone()
        assert row["task_outcome"] == "NOT_DELIVERED"

    def test_a_merged_task_still_reads_delivered(self, console, runner, admin):
        t, d = self._shipped(console, runner, admin, status="MERGED")
        console.commit()
        row = console.execute(
            "SELECT task_outcome FROM decision_outcomes WHERE id=%s", (d,)).fetchone()
        assert row["task_outcome"] == "DELIVERED", (
            "DELIVERED_BY_HAND must not swallow the ordinary case")


class TestTheTwoReadersAgree:
    """The property that makes precedent's copy acceptable.

    `decision_outcomes.task_outcome` is SQL; `precedent._delivered` is Python.
    console/rank._inside sets the precedent for a deliberate copy: it is only
    acceptable with a test asserting the two agree. Before 11 Sep 2026 they did
    not — precedent counted four hand-shipped tasks as failures while the
    console called them delivered.
    """

    CASES = [
        ("MERGED", None, True),
        ("FAILED", None, False),
        ("FAILED", 7, True),
        ("ABANDONED", None, False),
        ("ABANDONED", 7, True),
        ("REJECTED", None, False),
        ("RUNNING", None, False),
        ("QUEUED", None, False),
    ]

    @pytest.mark.parametrize("status,pointer,delivered", CASES)
    def test_python_matches_the_declared_rule(self, status, pointer, delivered):
        from proposer import precedent
        assert precedent._delivered(
            {"task_status": status, "shipped_by_decision_id": pointer}) is delivered

    def test_the_sql_agrees_with_the_python_on_every_case(self, console):
        """Asked of the database, not reasoned about."""
        from proposer import precedent
        for status, pointer, _ in self.CASES:
            row = console.execute(
                "SELECT CASE"
                "  WHEN %s = 'MERGED' THEN 'DELIVERED'"
                "  WHEN %s::integer IS NOT NULL THEN 'DELIVERED_BY_HAND'"
                "  WHEN %s IN ('ABANDONED','REJECTED','FAILED') THEN 'NOT_DELIVERED'"
                "  ELSE 'IN_FLIGHT' END AS outcome",
                (status, pointer, status)).fetchone()
            sql_says = row["outcome"] in ("DELIVERED", "DELIVERED_BY_HAND")
            py_says = precedent._delivered(
                {"task_status": status, "shipped_by_decision_id": pointer})
            assert sql_says == py_says, (
                f"{status}/{pointer}: view says {row['outcome']}, precedent "
                f"says {'delivered' if py_says else 'not delivered'}")

    def test_precedent_reads_the_query_version_that_carries_the_pointer(self):
        src = (ROOT / "proposer" / "precedent.py").read_text()
        assert "load_query(REACH, 2)" in src
        v2 = (ROOT / "proposer" / "queries" / "decision_reach.v2.sql").read_text()
        assert "shipped_by_decision_id" in v2
        v1 = (ROOT / "proposer" / "queries" / "decision_reach.v1.sql").read_text()
        assert "shipped_by_decision_id" not in v1, (
            "v1 is kept as it was; readings taken under it are attributed to it")


class TestNothingActsOnIt:
    """§9.3's refusal, kept. The pointer changes what is displayed, never what
    is done. If this test starts failing, the pointer has become the edge that
    was refused, wearing a column."""

    #: Every module that decides whether work proceeds.
    DECIDING = ("console/rank.py", "console/automerge.py", "console/autodeploy.py",
                "console/autoqueue.py", "console/approve.py", "console/merge.py",
                "runner/cycle.py", "console/autoapprove.py")

    @pytest.mark.parametrize("module", DECIDING)
    def test_no_deciding_module_reads_the_pointer(self, module):
        src = (ROOT / module).read_text()
        assert "shipped_by_decision_id" not in src, (
            f"{module} reads the pointer. It is allowed to be displayed and "
            f"not to be acted on: a FAILED task carrying it must stay "
            f"unclaimable, unmergeable and undeployable, which is the whole "
            f"difference between this and the FAILED -> MERGED edge §9.3 "
            f"refused.")

    def test_there_is_still_no_failed_to_merged_edge(self, console):
        """§9.3's refusal, asserted where it actually lives.

        The point of the pointer is that this row never needed to exist. If it
        appears, the argument for the pointer has gone and something has taken
        the shortcut it was built to avoid.
        """
        got = console.execute(
            "SELECT count(*) n FROM task_transitions"
            " WHERE from_status='FAILED' AND to_status='MERGED'").fetchone()
        assert got["n"] == 0

    def test_the_ways_out_of_failed_are_three_and_the_third_is_explained(
            self, console):
        """ABANDONED, QUEUED, and -- since 038 -- READY_FOR_REVIEW.

        THE EXPLANATION THIS ASKED FOR. The third edge is adoption: a task
        whose branch passed every check its contract has, refused by a boundary
        rule rather than by anything wrong with it. Task 69's run 44 was one,
        and without this edge the only road back was QUEUED, which does not
        re-examine a branch -- it writes a new one. It wrote a worse one.

        IT IS NOT THE EDGE §9.3 REFUSED, and the difference is the whole of why
        it is allowed. FAILED -> MERGED would ship something no person looked
        at. This lands on READY_FOR_REVIEW, which is where the runner's own
        branches arrive and where a human decides -- and accept() re-runs the
        contract's verification against the base as it stands before merging
        anything. Adoption moves a branch INTO review. It does not shorten the
        road out of it, and the FAILED -> MERGED assertion above still holds.

        The precondition is in 038's trigger, not here: a recorded verification
        whose checks were green, which is exactly what the two runs refused
        before their checks opened do not have.
        """
        rows = {r["to_status"]: r["required_role"] for r in console.execute(
            "SELECT to_status, required_role FROM task_transitions"
            " WHERE from_status='FAILED'").fetchall()}
        assert set(rows) == {"ABANDONED", "QUEUED", "READY_FOR_REVIEW"}, rows
        # All three stay the console's. A runner that could adopt could promote
        # the branch it had just failed.
        assert set(rows.values()) == {"fleet_console"}, rows

    def test_the_runner_cannot_write_it(self, console):
        """A runner that can mark its own failed task as shipped is that edge
        with a column instead of a transition."""
        got = console.execute(
            "SELECT has_column_privilege('fleet_task_runner','tasks',"
            "'shipped_by_decision_id','UPDATE') AS p").fetchone()
        assert got["p"] is False

    def test_the_console_can(self, console):
        got = console.execute(
            "SELECT has_column_privilege('fleet_console','tasks',"
            "'shipped_by_decision_id','UPDATE') AS p").fetchone()
        assert got["p"] is True
