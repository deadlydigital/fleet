"""The chain loop. specs/one-entry-point.md.

The stages are already tested by test_runner_cycle, test_automerge and
test_autoapprove. What is new here is the SCHEDULING, and every test below is
about a property the four separate units could not have: ordering, the two
safety stops, the loop's own clock, and the fact that it re-implements nothing.

The stages are stubbed. That is deliberate rather than convenient: a test that
drove real builds would be testing cycle.tick again, slowly, and would not say
anything about the loop. What the loop owes is that it calls the right stage at
the right time and stops when it should.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import chain


@pytest.fixture
def cfg_file(tmp_path) -> Path:
    p = tmp_path / "chain.yaml"
    p.write_text(textwrap.dedent("""
        stages: {build: true, merge: true, approve: true}
        wall_clock_seconds: 7200
        queue: null
    """))
    return p


class FakeConn:
    """Stands in for the reader connection. Answers only what the loop asks."""

    def __init__(self, *, queued=None, credit=60.0, credit_status="COMPUTED",
                 waiting=()):
        self.queued = list(queued or [])
        self.credit, self.credit_status = credit, credit_status
        self._waiting = list(waiting)
        self.closed = False

    def execute(self, sql, params=None):
        if "fleet_month_credit" in sql:
            return _Rows([{"status": self.credit_status,
                           "autonomous_remaining_gbp": self.credit}])
        if "READY_FOR_REVIEW" in sql:
            return _Rows(self._waiting)
        if "status = 'QUEUED'" in sql:
            return _Rows(self.queued[:1])
        raise AssertionError(f"the loop asked something unexpected: {sql}")

    def close(self):
        self.closed = True


class _Rows:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


def task(tid=1, cost=3.0, title="a task"):
    return {"id": tid, "title": title, "max_cost_gbp": cost,
            "attempts": 0, "max_attempts": 1}


@pytest.fixture
def stages(monkeypatch):
    """Record what the loop called, and let each test say what happened."""
    calls: list[str] = []
    plan = {"build": [], "merge": [], "approve": []}

    def _next(stage, default):
        calls.append(stage)
        queue = plan[stage]
        return queue.pop(0) if queue else default

    def fake_build(cfg, conn, *, dry_run, failed, emit):
        outcome = _next("build", None)
        if outcome is None:
            return chain.Step("build", False, "no task is queued"), None
        tid, result = outcome
        if tid in failed:
            return chain.Step("build", False, "already failed"), chain.REPEAT_FAILURE
        step = chain.Step("build", True, f"task {tid}: {result}", task_id=tid)
        if result == "FAILED":
            if tid in failed:
                return step, chain.REPEAT_FAILURE
            failed.add(tid)
        return step, None

    def fake_merge(cfg, conn, *, dry_run, emit):
        acted = _next("merge", False)
        return chain.Step("merge", bool(acted), "merge"), None

    def fake_approve(cfg, conn, *, dry_run, emit):
        acted = _next("approve", False)
        return chain.Step("approve", bool(acted), "approve"), None

    monkeypatch.setattr(chain, "_build", fake_build)
    monkeypatch.setattr(chain, "_merge", fake_merge)
    monkeypatch.setattr(chain, "_approve", fake_approve)
    return {"calls": calls, "plan": plan}


@pytest.fixture
def conn(monkeypatch):
    holder = {}

    def _make(dsn):
        return holder["conn"]

    monkeypatch.setattr(chain, "_connect", _make)
    monkeypatch.setattr("console.config.console_reader_dsn", lambda: "stub")
    return holder


# ---- ordering --------------------------------------------------------------

class TestDrainBeforeYouAdd:
    """The order is the complaint. The timers approved at 01:30, built until
    04:00 and merged ONCE at 03:30, so a task finishing at 03:40 waited a day
    for a decision that takes seconds."""

    def test_build_comes_before_merge_and_merge_before_approve(
            self, cfg_file, stages, conn):
        conn["conn"] = FakeConn()
        chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert stages["calls"] == ["build", "merge", "approve"]

    def test_acting_restarts_the_pass_rather_than_finishing_it(
            self, cfg_file, stages, conn):
        """A build may have produced something to merge, and a merge may have
        queued something to build. Carrying on down the list would leave that
        for the next pass and, with one stage left, for tomorrow."""
        conn["conn"] = FakeConn()
        stages["plan"]["build"] = [(1, "READY_FOR_REVIEW")]
        chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert stages["calls"] == ["build", "build", "merge", "approve"]

    def test_it_runs_to_a_fixpoint(self, cfg_file, stages, conn):
        """Not a fixed sequence: a merged draft queues its code task, and since
        037 a candidate may split into several links."""
        conn["conn"] = FakeConn()
        stages["plan"]["build"] = [(1, "READY_FOR_REVIEW")]
        stages["plan"]["merge"] = [True]
        stages["plan"]["approve"] = [True]
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert result.passes > 1
        assert result.stopped_by == chain.IDLE


# ---- the two safety stops --------------------------------------------------

class TestTheSameTaskFailingTwice:
    """A loop is more dangerous than a sweep here, and not obviously.

    cycle.py re-queues a failed task while attempts < max_attempts. Under
    timers the next fire is twenty minutes away; here QUEUED is claimed on the
    next pass, so max_attempts: 3 is three rebuilds in minutes with nobody
    between them. And a rebuild is a re-roll -- task 69 produced tests of 377,
    606, 439 and 385 lines from one spec, and the fourth replaced a verified
    branch with one that failed ruff.
    """

    def test_the_second_failure_halts_the_loop(self, cfg_file, stages, conn):
        conn["conn"] = FakeConn()
        stages["plan"]["build"] = [(7, "FAILED"), (7, "FAILED")]
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert result.stopped_by == chain.REPEAT_FAILURE
        assert result.failed_task_ids == [7]

    def test_a_different_task_failing_does_not_halt_it(
            self, cfg_file, stages, conn):
        """One failure is an ordinary night. It is the SAME task twice that is
        evidence the loop is paying to re-roll dice."""
        conn["conn"] = FakeConn()
        stages["plan"]["build"] = [(7, "FAILED"), (8, "FAILED")]
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert result.stopped_by == chain.IDLE
        assert result.failed_task_ids == [7, 8]


class TestTheCreditCeiling:
    """It is checked before EVERY build. Today autoapprove reads the pool at
    01:30 and the runner spends against that figure until 04:00 -- nothing
    bounds the night against the pool once approval has happened."""

    def test_a_task_that_cannot_be_afforded_stops_the_loop(
            self, cfg_file, conn, monkeypatch):
        conn["conn"] = FakeConn(queued=[task(cost=6.0)], credit=2.5)
        monkeypatch.setattr(chain, "_merge",
                            lambda *a, **k: (chain.Step("merge", False), None))
        monkeypatch.setattr(chain, "_approve",
                            lambda *a, **k: (chain.Step("approve", False), None))
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert result.stopped_by == chain.CREDIT
        assert "GBP 6.00" in result.steps[0].detail
        assert "GBP 2.50" in result.steps[0].detail

    def test_an_uncomputed_pool_is_a_stop_and_not_a_budget_of_nothing(
            self, cfg_file, conn, monkeypatch):
        """The two produce the same behaviour and completely different
        sentences, and the sentence is what gets read in the morning."""
        conn["conn"] = FakeConn(queued=[task()], credit=None,
                                credit_status="UNCOMPUTED")
        monkeypatch.setattr(chain, "_merge",
                            lambda *a, **k: (chain.Step("merge", False), None))
        monkeypatch.setattr(chain, "_approve",
                            lambda *a, **k: (chain.Step("approve", False), None))
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert result.stopped_by == chain.CREDIT
        assert "UNCOMPUTED" in result.steps[0].detail

    def test_an_affordable_task_is_built(self, cfg_file, conn, monkeypatch):
        conn["conn"] = FakeConn(queued=[task(cost=3.0)], credit=60.0)
        seen = {}

        def fake_tick(**kw):
            seen.update(kw)
            # The real tick takes the task out of QUEUED, and the loop's
            # termination depends entirely on the world changing under it. A
            # fake that did not would run to PASS_CEILING -- which it did, and
            # the backstop caught it, which is what the backstop is for.
            conn["conn"].queued.clear()
            return type("T", (), {"outcome": "READY_FOR_REVIEW", "task_id": 1,
                                  "reason": "ready", "cost_gbp": 2.5})()

        monkeypatch.setattr("runner.cycle.tick", fake_tick)
        monkeypatch.setattr(chain, "_merge",
                            lambda *a, **k: (chain.Step("merge", False), None))
        monkeypatch.setattr(chain, "_approve",
                            lambda *a, **k: (chain.Step("approve", False), None))
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert any(s.stage == "build" and s.acted for s in result.steps)
        assert result.spent_gbp == 2.5


# ---- the loop's own clock --------------------------------------------------

class TestTheLoopOwnsItsClock:
    """fleet-runner.service's TimeoutStartSec=4200 is sized for ONE task.
    Being killed by systemd mid-merge is the hardest failure to read in the
    morning: the merge either happened or did not, the decision row either
    exists or does not, and the journal stops mid-sentence."""

    def test_it_stops_on_its_own_deadline(self, tmp_path, stages, conn):
        p = tmp_path / "chain.yaml"
        p.write_text("stages: {build: true, merge: true, approve: true}\n"
                     "wall_clock_seconds: 10\n")
        conn["conn"] = FakeConn()
        stages["plan"]["build"] = [(i, "READY_FOR_REVIEW") for i in range(1, 40)]

        ticks = iter(range(0, 10_000, 4))    # 0, 4, 8, ... past 10 quickly
        result = chain.run(config_path=p, emit=lambda _m: None,
                           clock=lambda: next(ticks))
        assert result.stopped_by == chain.WALL_CLOCK

    def test_the_deadline_is_checked_between_stages_not_inside_one(
            self, tmp_path, conn, monkeypatch):
        """A stage that has started is allowed to finish. A merge interrupted
        halfway is the state the deadline exists to avoid producing."""
        p = tmp_path / "chain.yaml"
        p.write_text("stages: {build: true, merge: true, approve: true}\n"
                     "wall_clock_seconds: 1\n")
        conn["conn"] = FakeConn()
        ran = []

        def slow_build(cfg, c, *, dry_run, failed, emit):
            ran.append("build")
            return chain.Step("build", False, "no task is queued"), None

        def merge(cfg, c, *, dry_run, emit):
            ran.append("merge")
            return chain.Step("merge", False, "nothing waiting"), None

        monkeypatch.setattr(chain, "_build", slow_build)
        monkeypatch.setattr(chain, "_merge", merge)
        # start, top-of-pass, before build -- all inside the deadline; the
        # clock then expires DURING the build, which is where a check inside a
        # stage would have bitten.
        ticks = iter([0, 0, 0, 5, 5, 5, 5, 5])
        result = chain.run(config_path=p, emit=lambda _m: None,
                           clock=lambda: next(ticks))
        assert ran == ["build"], "the build finished; merge never started"
        assert result.stopped_by == chain.WALL_CLOCK


# ---- stage switches --------------------------------------------------------

class TestTheStagesCanBeTurnedOff:
    """This is what replaces "stop one unit at 3am". run_automerge.py argues
    for its own separation on exactly that ground, and a loop must not cost
    it."""

    def test_a_disabled_stage_is_never_called(self, tmp_path, stages, conn):
        p = tmp_path / "chain.yaml"
        p.write_text("stages: {build: true, merge: false, approve: true}\n"
                     "wall_clock_seconds: 7200\n")
        conn["conn"] = FakeConn()
        chain.run(config_path=p, emit=lambda _m: None)
        assert "merge" not in stages["calls"]
        assert stages["calls"] == ["build", "approve"]

    def test_the_default_is_on(self, tmp_path):
        p = tmp_path / "chain.yaml"
        p.write_text("wall_clock_seconds: 60\n")
        cfg = chain.load_config(p)
        assert cfg["stages"] == {"build": True, "merge": True, "approve": True}

    def test_the_shipped_config_has_every_stage_on(self):
        cfg = chain.load_config()
        assert cfg["stages"] == {"build": True, "merge": True, "approve": True}
        assert cfg["wall_clock_seconds"] > 0


# ---- the dry run -----------------------------------------------------------

class TestTheDryRunIsOnePass:
    def test_it_does_not_spin_to_the_pass_ceiling(self, cfg_file, stages, conn):
        """The fixpoint is reached by the world changing. A dry run changes
        nothing, so every pass would see what the last one saw and decide the
        same thing again."""
        conn["conn"] = FakeConn()
        stages["plan"]["build"] = [(i, "READY_FOR_REVIEW") for i in range(1, 90)]
        result = chain.run(dry_run=True, config_path=cfg_file,
                           emit=lambda _m: None)
        assert result.passes == 1
        assert result.stopped_by == chain.DRY_RUN_ONE_PASS
        assert result.stopped_by != chain.MAX_PASSES


# ---- what the one command owes back ----------------------------------------

class TestTheReport:
    def test_it_names_what_is_waiting_for_a_person(self, cfg_file, stages, conn):
        conn["conn"] = FakeConn(waiting=[
            {"id": 71, "title": "Draft spec: something", "repo": "fleet",
             "branch_name": "fleet/task-71", "work_type": "draft_spec",
             "completed_at": None}])
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        lines = "\n".join(chain.describe(result))
        assert "1 waiting for your accept" in lines
        assert "task 71" in lines and "fleet/task-71" in lines

    def test_an_empty_queue_says_so_rather_than_printing_nothing(
            self, cfg_file, stages, conn):
        conn["conn"] = FakeConn()
        result = chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert "nothing is waiting for you" in "\n".join(chain.describe(result))

    def test_the_connection_is_closed_even_when_a_stage_raises(
            self, cfg_file, conn, monkeypatch):
        c = FakeConn()
        conn["conn"] = c

        def boom(*a, **k):
            raise RuntimeError("the build exploded")

        monkeypatch.setattr(chain, "_build", boom)
        with pytest.raises(RuntimeError):
            chain.run(config_path=cfg_file, emit=lambda _m: None)
        assert c.closed, "a loop that leaks a connection per night is a loop"


# ---- it re-implements nothing ----------------------------------------------

def test_the_peek_matches_what_claim_task_would_take(dsns, console, runner):
    """chain.next_claimable copies claim_task's predicate, and the copy is the
    risk. If the two disagree, the loop checks affordability and repeat-failure
    against one task and then builds a different one -- a safety control aimed
    at the wrong row.

    There is no way to ask the database what it WOULD claim without claiming
    it, so the copy stands and this asserts the two agree on a real queue.
    """
    import json
    from tests.support import PLATFORM_FLOOR

    contract = json.dumps({"work_type": "dd_api",
                           "protected_paths": PLATFORM_FLOOR})
    ids = []
    for priority in (200, 100, 100):
        row = console.execute(
            "INSERT INTO tasks (title, spec_md, repo, base_branch,"
            " acceptance_contract, max_cost_gbp, priority, status)"
            " VALUES ('t','# t','deadly-digital-platform','main',%s,3.00,%s,"
            " 'QUEUED') RETURNING id", (contract, priority)).fetchone()["id"]
        ids.append(row)
    console.commit()

    peeked = chain.next_claimable(console, None)
    claimed = runner.execute("SELECT claim_task(NULL) AS id").fetchone()["id"]
    runner.commit()
    assert peeked["id"] == claimed, (
        f"the loop peeked {peeked['id']} and claim_task took {claimed}")
    # And the ordering really is priority-then-id, so the test could have failed.
    assert claimed == min(ids[1:]), "priority 100 beats 200, lowest id first"


def test_a_task_at_its_attempt_ceiling_is_not_peeked(dsns, console, runner):
    """claim_task requires attempts < max_attempts. A peek that ignored it
    would report a task the database will never hand over, and the loop would
    stop on a credit ceiling for work it was never going to do."""
    import json
    from tests.support import PLATFORM_FLOOR

    contract = json.dumps({"work_type": "dd_api",
                           "protected_paths": PLATFORM_FLOOR})
    console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch,"
        " acceptance_contract, max_cost_gbp, status, attempts, max_attempts)"
        " VALUES ('spent','# t','deadly-digital-platform','main',%s,3.00,"
        " 'QUEUED', 1, 1)", (contract,))
    console.commit()
    assert chain.next_claimable(console, None) is None
    assert runner.execute("SELECT claim_task(NULL) AS id").fetchone()["id"] is None
