"""The cycle reads its own history, and that reading may not move the ranking.

THE ONE TEST THIS FILE EXISTS FOR is
`test_precedent_cannot_change_what_is_proposed`. Everything else here is
description; that one is the condition on which the proposer was allowed to
see the decision log at all.

010 refuses `fleet_detector_reader` any sight of `decision_log`, on the rule
that the layer being graded does not see the grade. The cycle now reads the
log on a THIRD connection, as the detector identity, which already holds the
grant. That keeps the identity half of 010's rule -- the write side still
cannot read the log, and the track-1 read side still cannot -- and gives up
the process half. What replaces it is structural and is asserted here:

    PRECEDENT IS AN OUTPUT, NEVER AN INPUT.

`rank()` does not take it, `findings.compute()` does not take it, and the
suppression loop does not consult it. A proposer that ranked on its own
approval history would be optimising for approval rather than for what is
true, which is precisely the failure 010's refusal was guarding.

The test has two halves and needs both. "Precedent cannot change the
ranking" passes trivially when nothing reads precedent at all, so the first
half proves the wiring exists and the second proves it is inert. Dropping
either leaves a test that a no-op satisfies.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from proposer import config
from proposer import cycle as cycle_module
from proposer.objectives import load as load_objectives
from support_proposals import all_detectors_healthy, arrange_issue

OBJECTIVES_FILE = config.PROJECT_ROOT / "objectives-2026-Q4.yaml"


@pytest.fixture
def objectives():
    return load_objectives(OBJECTIVES_FILE)


@pytest.fixture
def cycle_config():
    return copy.deepcopy(config.load_cycle_config())


def healthy(admin):
    """Every registered detector, from the registry. See support_proposals."""
    all_detectors_healthy(admin)


def open_issue(admin, days: int = 30, **kwargs):
    opened, now = admin.execute(
        "SELECT now() - %s * interval '1 day' AS opened, now() AS t",
        (days,)).fetchone().values()
    return arrange_issue(admin, first_seen=opened, last_seen=now, **kwargs)


def crowded(admin, n: int = 8):
    """More findings than the cap admits, so that ORDER IS OBSERVABLE.

    The first version of this test seeded ONE issue and therefore one
    finding, and a one-item list sorts the same in every order: a deliberate
    reversion that fed precedent straight into the ranking passed it. A test
    whose world cannot express the failure is not a guard, and this repo has
    `revert_guards.py` because that is easy to ship without noticing.

    Eight issues against a five-item cap means a reordering changes both
    which five are proposed and which three are cut.
    """
    return [open_issue(admin, days=30, severity="CRITICAL", subject_id=str(i))
            for i in range(1, n + 1)]


def decide(console, **over) -> int:
    """One row in the log, written by the only role the database accepts."""
    fields = {"product": "deadly_digital", "decision": "APPROVED",
              "reason": "worth doing", "subject": "a thing"}
    fields.update(over)
    cols = ", ".join(fields)
    marks = ", ".join(f"%({k})s" for k in fields)
    row = console.execute(
        f"INSERT INTO decision_log ({cols}) VALUES ({marks}) RETURNING id",
        fields).fetchone()
    console.commit()
    return row["id"]


def run(cycle_config, objectives, **kwargs):
    return cycle_module.run_cycle(cycle_config=cycle_config,
                                  objectives=objectives, dry_run=True, **kwargs)


# ---- the load-bearing one --------------------------------------------------

def test_precedent_cannot_change_what_is_proposed(admin, console, dsns,
                                                  cycle_config, objectives):
    """Two different decision logs, one identical set of findings.

    The log is append-only by design -- `decision_log_no_delete` refuses a
    DELETE and only fleet_admin holds the grant -- so the second world is the
    first with more decisions in it, which is also how a real morning differs
    from the one before it.
    """
    healthy(admin)
    crowded(admin)

    decide(console, subject="the first thing", reason="it was cheap")
    first = run(cycle_config, objectives)

    # THE TWO WORLDS DIFFER IN EVERY SCALAR PRECEDENT EXPOSES: total (1 -> 6,
    # so parity moves too), approved (1 -> 3), rejected (0 -> 2), deferred
    # (0 -> 1). A reversion is only caught if the quantity it reaches for
    # actually differs between the runs, and the first version of this test
    # moved only the total -- from 1 to 7, both odd -- so a deliberate
    # reversion keyed on `total % 2` sorted both worlds identically and
    # passed. Differing on one axis is how a guard quietly stops guarding.
    for n in range(2):
        decide(console, subject=f"approved thing {n}", reason="cheap enough")
    for n in range(2):
        decide(console, subject=f"rejected thing {n}", decision="REJECTED",
               reason="not this quarter")
    decide(console, subject="deferred thing", decision="DEFERRED",
           reason="waiting on the consent work")
    second = run(cycle_config, objectives)

    # HALF ONE: the wiring exists, and the two runs really did read
    # different records. Without this the assertion below is satisfied by a
    # cycle that never opened the connection.
    assert first.precedent is not None, (
        "the cycle proposed without reading the decision log at all")
    assert (first.precedent.total, first.precedent.approved,
            first.precedent.rejected, first.precedent.deferred) == (1, 1, 0, 0)
    assert (second.precedent.total, second.precedent.approved,
            second.precedent.rejected, second.precedent.deferred) == (6, 3, 2, 1)
    assert first.precedent.render() != second.precedent.render()

    # HALF TWO: and none of it reached the ranking.
    #
    # The cap must actually be binding, or "the same five" is satisfied by
    # there being only ever five. Asserted rather than assumed.
    assert len(first.proposed) == cycle_module.MAX_ITEMS
    assert first.dropped, "nothing was cut, so ordering is not observable here"

    assert [f.finding_key for f in first.proposed] == \
           [f.finding_key for f in second.proposed]
    assert [f.title for f in first.proposed] == \
           [f.title for f in second.proposed]
    assert [f.kind for f in first.proposed] == [f.kind for f in second.proposed]
    assert [f.finding_key for f in first.dropped] == \
           [f.finding_key for f in second.dropped]
    assert [f.finding_key for f, _ in first.suppressed] == \
           [f.finding_key for f, _ in second.suppressed]


def test_rank_cannot_reach_precedent_because_it_is_not_given_any(objectives):
    """The signature is the guarantee, so the signature is asserted.

    A future change that threads precedent into ranking has to change this
    line, which is the point: it becomes a deliberate edit with a failing
    test attached rather than an extra argument nobody notices.
    """
    import inspect
    assert list(inspect.signature(cycle_module.rank).parameters) == \
        ["finding", "objectives"]


# ---- what a thin record does to the output ---------------------------------

def _summary(**over):
    row = {"total": 10, "approved": 10, "rejected": 0, "deferred": 0,
           "backfilled": 0, "inferred": 0, "products": 1, "distinct_days": 2,
           "first_decided_at": datetime(2026, 8, 30, tzinfo=timezone.utc),
           "last_decided_at": datetime(2026, 9, 7, tzinfo=timezone.utc)}
    row.update(over)
    return row


def _reach_rows(n_tasks: int, objective: str = "dd-feature-parity",
                status: str = "MERGED"):
    return [{"decision_id": 1, "product": "deadly_digital",
             "decision": "APPROVED", "decided_at": _summary()["last_decided_at"],
             "origin": "RECORDED", "subject": "a thing", "link": "DIRECT",
             "task_id": i, "task_status": status, "task_repo": "fleet",
             "base_branch": "main", "objective_ref": objective,
             "work_type": "research", "patch_commit_sha": None,
             "runs_total": 1, "total_cost_gbp": 0}
            for i in range(1, n_tasks + 1)]


_SURFACE = [{"detector_key": "dd_analytics_reconciliation",
             "product": "deadly_digital", "open_issues": 1},
            {"detector_key": "fleet_heartbeat", "product": "deadly_digital",
             "open_issues": 0}]


def _built(summary, reach, cfg=None):
    from proposer import precedent as pm
    return pm._compute(datetime.now(timezone.utc), "dd_detector_login",
                       summary, reach, _SURFACE,
                       cycle_config=cfg or {"precedent": {"compare_floor": 6}},
                       deployments={})


class TestTheZeroRejectionCaveat:
    """It goes under EVERY approval sentence, which is the instruction.

    A caveat stated once at the top is a caveat scrolled past, and this is
    the most misleading thing in the record: 010 was built because rejections
    were leaving no trace at all, and a log that has recorded none since is
    either unbroken agreement or a log still not receiving them.
    """

    def test_it_appears_under_every_approval_derived_block(self):
        from proposer.precedent import Precedent
        built = _built(_summary(rejected=0), _reach_rows(8))
        rendered = "\n".join(built.render())
        approval_blocks = sum(1 for f in built.facts if f.approval_claim)
        assert approval_blocks >= 3, "expected several approval-derived blocks"
        assert rendered.count(Precedent.REJECTION_CAVEAT) == approval_blocks

    def test_it_disappears_once_a_rejection_exists(self):
        from proposer.precedent import Precedent
        built = _built(_summary(total=11, approved=10, rejected=1),
                       _reach_rows(8))
        assert Precedent.REJECTION_CAVEAT not in "\n".join(built.render())

    def test_no_approval_count_is_printed_without_it(self):
        """The property stated directly: every block that counts approvals
        carries the caveat, so there is no way to read one without it."""
        built = _built(_summary(rejected=0), _reach_rows(8))
        for fact in built.facts:
            if fact.approval_claim:
                assert built.has_no_rejections


class TestBelowTheFloorAGroupIsListedNotCompared:

    def test_a_thin_group_keeps_its_counts_and_loses_the_comparison(self):
        built = _built(_summary(), _reach_rows(3, objective="dd-trustworthy"))
        text = "\n".join(built.render())
        assert "3 linked task(s)" in text          # the counts survive
        assert "listed not compared" in text       # the sentence does not

    def test_a_group_at_the_floor_may_be_compared(self):
        built = _built(_summary(), _reach_rows(6))
        text = "\n".join(built.render())
        assert "6 linked task(s), 6 merged" in text
        assert "listed not compared" not in text

    def test_the_floor_is_configuration_not_a_literal(self):
        thin = _built(_summary(), _reach_rows(6),
                      cfg={"precedent": {"compare_floor": 9}})
        assert "listed not compared" in "\n".join(thin.render())


class TestUncomputedIsReachable:
    """A guard that can never fire is decoration, so both are exercised."""

    def test_an_empty_log_states_that_rather_than_saying_nothing(self):
        built = _built(_summary(total=0, approved=0, first_decided_at=None,
                                last_decided_at=None), [])
        text = "\n".join(built.render())
        assert "UNCOMPUTED" in text and "empty" in text

    def test_regressions_are_refused_and_the_detectors_are_named(self):
        built = _built(_summary(), _reach_rows(8))
        fact = next(f for f in built.facts if f.key == "regression")
        assert fact.status == "UNCOMPUTED"
        assert "dd_analytics_reconciliation" in fact.uncomputed_reason
        assert "fleet_heartbeat" in fact.uncomputed_reason
        assert "deadly_digital" in fact.uncomputed_reason

    def test_an_uncomputed_fact_cannot_be_made_without_a_reason(self):
        from proposer.precedent import Fact
        with pytest.raises(ValueError):
            Fact.uncomputed("k", "s", reason="   ")


class TestEveryComputedBlockCarriesItsBasis:
    """The size of the record sits in the same place as the claim."""

    def test_no_computed_fact_is_rendered_without_one(self):
        built = _built(_summary(), _reach_rows(8))
        for fact in built.facts:
            if fact.status == "COMPUTED" and fact.key != "deferrals":
                assert fact.basis is not None, f"{fact.key} has no basis"

    def test_the_basis_names_the_backfilled_and_unlinked_rows(self):
        built = _built(_summary(backfilled=7), _reach_rows(8))
        text = "\n".join(built.render())
        assert "7 backfilled (reason UNRECORDED)" in text


class TestAnUnreadableLogDoesNotStopTheMorning:

    def test_the_cycle_still_proposes_when_precedent_cannot_be_read(
            self, admin, dsns, cycle_config, objectives):
        """Precedent is a reading, not a dependency.

        Refusing to propose because the log was unreachable would make an
        optional block load-bearing, which is the opposite of what it is.
        """
        healthy(admin)
        crowded(admin)
        result = cycle_module.run_cycle(
            cycle_config=cycle_config, objectives=objectives, dry_run=True,
            precedent_dsn="postgresql://nobody@127.0.0.1:1/nothing")
        assert len(result.proposed) == cycle_module.MAX_ITEMS
        assert result.precedent.unavailable_reason is not None
        assert "UNCOMPUTED" in "\n".join(result.precedent.render())


class TestTheRefusalThisChangeWasAllowedUnderIsStillThere:
    """010's grant refusal must survive the feature that reads around it.

    The cycle reads the log on a third connection precisely so that
    `fleet_detector_reader` does not have to be granted it. If a later change
    finds the third connection inconvenient and widens the grant instead,
    the identity separation is gone and only the structural property is left
    holding the line. This fails if that happens.
    """

    def test_the_proposal_layers_read_identity_still_cannot_see_the_log(self, reader):
        import psycopg
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("SELECT 1 FROM decision_log")

    def test_the_write_identity_certainly_cannot(self, proposer):
        import psycopg
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            proposer.execute("SELECT 1 FROM decision_log")

    def test_precedent_is_read_as_the_detector_identity_not_the_readers(self, dsns):
        from proposer import config as pconfig
        assert pconfig.precedent_dsn() == dsns["fleet"]
        assert pconfig.precedent_dsn() != pconfig.reader_dsn()

    def test_the_identity_that_reads_it_cannot_write_it(self, fleet):
        """It holds SELECT and nothing else, and the connection says so too."""
        import psycopg
        with pytest.raises((psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.ReadOnlySqlTransaction)):
            fleet.execute(
                "INSERT INTO decision_log (product, subject, decision, reason)"
                " VALUES ('p', 's', 'APPROVED', 'r')")
