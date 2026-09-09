"""The decision log: what was chosen, why, and what happened afterwards.

Three properties carry this file, and each is tested by arranging the state
that would make a wrong implementation look right:

1. **Outcomes are derived.** Every outcome is read from `decision_outcomes`,
   never from a column. The tests build a merged task, an abandoned one and
   one still in flight, and assert the view says three different things about
   three decisions whose own rows are identical apart from the task they cite.

2. **A reopen is not a good outcome.** An issue that resolved, came back and
   resolved again is currently RESOLVED. A view that read the status would
   call that a decision that worked. It did not: it came back.

3. **A reason is mandatory, including on a rejection.** Both halves are
   needed -- the NOT NULL, and the check that stops a live row using the
   backfill's UNRECORDED sentinel to satisfy it. Either one alone leaves a
   way to record a rejection that says nothing.

Every test drives the database through the identity that would do the thing
in production. `console` is the only one the log accepts a write from.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

REPO = "deadly-digital-platform"
PRODUCT = "deadly_digital"

from tests.support import PLATFORM_FLOOR

FLOOR = PLATFORM_FLOOR

def contract(repo: str = REPO) -> str:
    return json.dumps({
        "work_type": "dd_feature", "repo": repo, "base_branch": "main",
        "writable_paths": ["platform/app/(dashboard)/analytics/orders/**"], "protected_paths": list(FLOOR),
        "verification": ["pytest api/tests/"], "max_diff_lines": 800,
    })


# ---- arranging the world the view reads -----------------------------------

def add_task(console, status="QUEUED", attempts=1, title="a task",
             repo=REPO) -> int:
    row = console.execute(
        """
        INSERT INTO tasks (title, spec_md, repo, base_branch,
                           acceptance_contract, max_cost_gbp, status, attempts,
                           max_attempts)
        VALUES (%(title)s, '# do it', %(repo)s, 'main', %(c)s, 20.00,
                %(status)s, %(attempts)s, 9)
        RETURNING id
        """,
        {"title": title, "repo": repo, "c": contract(repo), "status": status,
         "attempts": attempts}).fetchone()
    console.commit()
    return row["id"]


def add_run(admin, task_id: int, cost: str, status="FAILED") -> int:
    """Runs are the runner's to write; arranged here as the admin.

    The point of these rows is the cost the view sums, not who wrote them, and
    a run has a budget trigger that a test fixture should not be re-proving.

    FAILED by default, deliberately: `runs_one_active_per_task` is a unique
    index over ACTIVE and AWAITING_HUMAN, so a task with several open runs is
    a state 003 refuses. A task that took four attempts has three closed runs
    and one open one, which is what these fixtures build.
    """
    row = admin.execute(
        """
        INSERT INTO runs (task_id, work_type, contract_version, status,
                          spend_limit_gbp, committed_gbp)
        VALUES (%s, 'dd_feature', 1, %s, 20.00, %s) RETURNING id
        """, (task_id, status, cost)).fetchone()
    return row["id"]


def merge_task(console, admin, task_id: int) -> None:
    """Walk a task to MERGED the way the system does, not by writing the word.

    QUEUED -> RUNNING -> READY_FOR_REVIEW -> MERGED, each move checked by
    `enforce_task_transition` against `task_transitions`. Setting the status
    directly would arrange a state the state machine does not admit, and a
    view tested only against impossible rows is a view tested against nothing.
    """
    admin.execute("UPDATE tasks SET status='RUNNING', claimed_at=now()"
                  " WHERE id=%s", (task_id,))
    admin.execute("UPDATE tasks SET status='READY_FOR_REVIEW',"
                  " branch_name=%s, completed_at=now() WHERE id=%s",
                  (f"fleet/task-{task_id}", task_id))
    admin.execute("UPDATE tasks SET status='MERGED' WHERE id=%s", (task_id,))


def add_issue(admin, fingerprint="fp-1", first_seen=None) -> int:
    """An open issue, with its first occurrence written by 001's trigger."""
    first_seen = first_seen or datetime.now(timezone.utc) - timedelta(days=7)
    row = admin.execute(
        """
        INSERT INTO issues (fingerprint, product, issue_type, subject_type,
                            subject_id, detector_key, first_seen, last_seen,
                            severity)
        VALUES (%s, %s, 'MISSING_ANALYTICS_ORDER', 'tenant', '2',
                'dd_analytics_reconciliation', %s, %s, 'HIGH')
        RETURNING id
        """, (fingerprint, PRODUCT, first_seen, first_seen)).fetchone()
    return row["id"]


def resolve_issue(admin, issue_id: int, at=None) -> None:
    at = at or datetime.now(timezone.utc)
    admin.execute(
        """
        UPDATE issues SET status='RESOLVED', resolution_type='CLEARED',
               resolved_at=%s, resolution_effective_at=%s WHERE id=%s
        """, (at, at, issue_id))


def reopen_issue(admin, issue_id: int, at=None) -> None:
    """Exactly how a detector reopens one: last_seen forward, status back."""
    at = at or datetime.now(timezone.utc)
    admin.execute(
        """
        UPDATE issues SET status='OPEN', resolution_type=NULL, resolved_at=NULL,
               resolution_effective_at=NULL, last_seen=%s,
               reopen_count=reopen_count+1 WHERE id=%s
        """, (at, issue_id))


def decide(console, **over) -> int:
    fields = {"product": PRODUCT, "decision": "APPROVED",
              "reason": "worth doing", "subject": "a thing"}
    fields.update(over)
    cols = ", ".join(fields)
    marks = ", ".join(f"%({k})s" for k in fields)
    row = console.execute(
        f"INSERT INTO decision_log ({cols}) VALUES ({marks}) RETURNING id",
        fields).fetchone()
    console.commit()
    return row["id"]


def outcome(console, decision_id: int) -> dict:
    return console.execute(
        "SELECT * FROM decision_outcomes WHERE id = %s", (decision_id,)).fetchone()


# ---- the reason ------------------------------------------------------------

class TestAReasonIsMandatory:
    """Including on rejections, which is the half that is easy to lose."""

    def test_a_decision_with_no_reason_is_refused(self, console):
        with pytest.raises(psycopg.errors.NotNullViolation):
            decide(console, reason=None)

    def test_a_rejection_with_no_reason_is_refused(self, console):
        """The record this log exists to keep is the one being refused here."""
        with pytest.raises(psycopg.errors.NotNullViolation):
            decide(console, decision="REJECTED", reason=None)

    def test_a_deferral_with_no_reason_is_refused(self, console):
        with pytest.raises(psycopg.errors.NotNullViolation):
            decide(console, decision="DEFERRED", reason=None)

    def test_a_blank_reason_is_refused(self, console):
        """NOT NULL alone accepts a space, which says nothing more than NULL."""
        with pytest.raises(psycopg.errors.CheckViolation):
            decide(console, decision="REJECTED", reason="   ")

    def test_a_live_decision_cannot_use_the_backfill_sentinel(self, console):
        """Otherwise UNRECORDED becomes the way to satisfy a NOT NULL."""
        with pytest.raises(psycopg.errors.CheckViolation,
                           match="sentinels_are_backfill_only"):
            decide(console, decision="REJECTED", reason="UNRECORDED")

    def test_a_rejection_with_a_reason_is_recorded(self, console):
        did = decide(console, decision="REJECTED",
                     reason="the detector is right but the fix is a product "
                            "decision I am not making this quarter")
        row = outcome(console, did)
        assert row["decision"] == "REJECTED"
        assert "product decision" in row["reason"]


# ---- outcomes are derived --------------------------------------------------

class TestTaskOutcomeIsDerived:

    def test_a_merged_task_reads_delivered(self, console, admin):
        task = add_task(console, attempts=2)
        add_run(admin, task, "1.50")
        add_run(admin, task, "2.25", status="AWAITING_HUMAN")
        merge_task(console, admin, task)
        row = outcome(console, decide(console, task_id=task))
        assert row["task_status"] == "MERGED"
        assert row["task_outcome"] == "DELIVERED"
        assert float(row["total_cost_gbp"]) == 3.75
        assert row["runs_total"] == 2
        assert row["attempts_to_green"] == 2

    def test_an_abandoned_task_reads_not_delivered_and_has_no_green(self, console, admin):
        task = add_task(console, status="ABANDONED", attempts=3)
        add_run(admin, task, "4.00", status="FAILED")
        row = outcome(console, decide(console, task_id=task))
        assert row["task_outcome"] == "NOT_DELIVERED"
        assert float(row["total_cost_gbp"]) == 4.00
        # attempts-so-far under the name of a result is the thing being refused
        assert row["attempts_to_green"] is None

    def test_a_task_still_open_reads_in_flight(self, console):
        task = add_task(console, status="QUEUED")
        row = outcome(console, decide(console, task_id=task))
        assert row["task_outcome"] == "IN_FLIGHT"
        assert row["attempts_to_green"] is None
        assert float(row["total_cost_gbp"]) == 0.0
        assert row["runs_total"] == 0

    def test_cost_is_every_run_not_the_latest(self, console, admin):
        """A task that took four attempts cost what all four cost.

        These are task 5's real figures: £5.00, £4.80, £5.57, £4.58. The
        console's task list showed £4.58 for it before `spent_all_runs`
        existed, which is the understatement this asserts against.
        """
        task = add_task(console, attempts=4)
        for c in ("5.00", "4.80", "5.57"):
            add_run(admin, task, c)
        add_run(admin, task, "4.58", status="AWAITING_HUMAN")
        merge_task(console, admin, task)
        row = outcome(console, decide(console, task_id=task))
        assert float(row["total_cost_gbp"]) == 19.95
        assert row["runs_total"] == 4

    def test_a_decision_citing_no_task_has_no_task_outcome(self, console):
        """Absent is not the same as bad and must not read like it."""
        row = outcome(console, decide(console))
        assert row["task_outcome"] is None
        assert row["task_status"] is None
        assert row["total_cost_gbp"] is None

    def test_the_outcome_moves_when_the_task_does(self, console, admin):
        """The proof that nothing is stored: change the task, re-read the view."""
        task = add_task(console, status="QUEUED")
        did = decide(console, task_id=task)
        assert outcome(console, did)["task_outcome"] == "IN_FLIGHT"
        add_run(admin, task, "1.00", status="AWAITING_HUMAN")
        merge_task(console, admin, task)
        assert outcome(console, did)["task_outcome"] == "DELIVERED"
        assert float(outcome(console, did)["total_cost_gbp"]) == 1.00


class TestIssueOutcomeIsDerived:

    def test_an_issue_resolved_after_the_decision_reads_resolved_held(
            self, console, admin):
        issue = add_issue(admin)
        did = decide(console, issue_id=issue)
        resolve_issue(admin, issue)
        row = outcome(console, did)
        assert row["issue_outcome"] == "RESOLVED_HELD"
        assert row["resolved_since_decision"] is True
        assert row["reopened_since_decision"] is False

    def test_an_issue_that_reopens_does_not_read_as_a_good_outcome(
            self, console, admin):
        """THE ONE THIS CLASS EXISTS FOR.

        Resolved, reopened, resolved again. `issues.status` is RESOLVED, so a
        view that read the status would report a decision that worked. It did
        not work: the problem came back, and the second fix is a different
        decision's to claim.
        """
        issue = add_issue(admin)
        did = decide(console, issue_id=issue)
        resolve_issue(admin, issue)
        reopen_issue(admin, issue)
        resolve_issue(admin, issue)

        row = outcome(console, did)
        assert row["issue_status"] == "RESOLVED"          # the tempting read
        assert row["issue_outcome"] == "REOPENED"         # the honest one
        assert row["issue_outcome"] != "RESOLVED_HELD"
        assert row["reopened_since_decision"] is True

    def test_an_issue_still_open_reads_still_open(self, console, admin):
        issue = add_issue(admin)
        row = outcome(console, decide(console, issue_id=issue))
        assert row["issue_outcome"] == "STILL_OPEN"

    def test_an_issue_resolved_before_the_decision_is_not_credited_to_it(
            self, console, admin):
        """A decision taken after the fact cannot claim the fix."""
        issue = add_issue(admin)
        resolve_issue(admin, issue,
                      at=datetime.now(timezone.utc) - timedelta(hours=1))
        admin.execute("COMMIT")
        did = decide(console, issue_id=issue)
        row = outcome(console, did)
        assert row["issue_outcome"] == "RESOLVED_BEFORE_DECISION"
        assert row["resolved_since_decision"] is False

    def test_a_decision_citing_no_issue_has_no_issue_outcome(self, console):
        row = outcome(console, decide(console))
        assert row["issue_outcome"] is None
        assert row["issue_status"] is None


class TestThereIsNowhereToTypeAnOutcome:

    def test_decision_log_has_no_outcome_column(self, console):
        cols = {r["column_name"] for r in console.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'decision_log'").fetchall()}
        assert not cols & {"outcome", "task_outcome", "issue_outcome",
                           "total_cost_gbp", "attempts_to_green", "executed",
                           "outcome_note", "worked"}

    def test_writing_an_outcome_is_a_missing_column_not_a_silent_accept(
            self, console):
        with pytest.raises(psycopg.errors.UndefinedColumn):
            console.execute(
                "INSERT INTO decision_log (product, subject, decision, reason,"
                " task_outcome) VALUES ('p','s','APPROVED','r','DELIVERED')")

    def test_a_settled_decision_cannot_be_revised(self, console):
        did = decide(console)
        with pytest.raises((psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.RaiseException)):
            console.execute("UPDATE decision_log SET reason='different' "
                            "WHERE id=%s", (did,))

    def test_a_settled_decision_cannot_be_deleted(self, console):
        did = decide(console)
        with pytest.raises((psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.RaiseException)):
            console.execute("DELETE FROM decision_log WHERE id=%s", (did,))


# ---- provenance ------------------------------------------------------------

class TestBackfilledRowsAreDistinguishable:

    def test_a_live_row_says_recorded_and_stated(self, console):
        row = outcome(console, decide(console))
        assert row["origin"] == "RECORDED"
        assert row["confidence"] == "STATED"

    def test_a_backfilled_row_says_so_on_both_axes(self, console):
        did = decide(console, origin="BACKFILLED", confidence="INFERRED",
                     reason="UNRECORDED", decided_by="UNRECORDED")
        row = outcome(console, did)
        assert row["origin"] == "BACKFILLED"
        assert row["confidence"] == "INFERRED"
        assert row["reason"] == "UNRECORDED"

    def test_a_backfilled_row_cannot_claim_stated_confidence(self, console):
        with pytest.raises(psycopg.errors.CheckViolation,
                           match="backfill_is_inferred"):
            decide(console, origin="BACKFILLED", confidence="STATED",
                   reason="UNRECORDED")

    def test_the_two_are_separable_by_query(self, console):
        decide(console, subject="live one")
        decide(console, subject="old one", origin="BACKFILLED",
               confidence="INFERRED", reason="UNRECORDED",
               decided_by="UNRECORDED")
        live = console.execute(
            "SELECT subject FROM decision_outcomes WHERE origin='RECORDED'"
        ).fetchall()
        assert [r["subject"] for r in live] == ["live one"]

    def test_a_live_row_may_still_be_inferred(self, console):
        """The implication runs one way only: written up later, from memory."""
        did = decide(console, confidence="INFERRED",
                     reason="reconstructed from my notes the following week")
        assert outcome(console, did)["origin"] == "RECORDED"


# ---- who may write ---------------------------------------------------------

class TestOnlyTheConsoleDecides:

    def test_the_runner_cannot_record_a_decision(self, runner):
        """A decision is made ABOUT the runner's work."""
        with pytest.raises((psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.RaiseException)):
            runner.execute(
                "INSERT INTO decision_log (product, subject, decision, reason)"
                " VALUES ('p','s','APPROVED','because')")

    def test_the_trigger_refuses_the_runner_even_when_it_holds_the_grant(
            self, runner, admin):
        """TWO MECHANISMS REFUSE THE RUNNER, AND THIS ISOLATES THE SECOND.

        The absent INSERT grant refuses it, and so does the authority trigger.
        A test that accepts either exception cannot say which one fired --
        `tests/revert_schema_guards.py` proved exactly that by disabling the
        trigger and watching the test above keep passing on the grant alone.

        So the grant is given here, deliberately, on a throwaway database. What
        is left is the trigger, and the assertion is its own message rather
        than any refusal at all.
        """
        admin.execute("GRANT INSERT ON decision_log TO fleet_task_runner")
        admin.execute("GRANT USAGE, SELECT ON SEQUENCE decision_log_id_seq "
                      "TO fleet_task_runner")
        with pytest.raises(psycopg.errors.RaiseException,
                           match="may not record decisions"):
            runner.execute(
                "INSERT INTO decision_log (product, subject, decision, reason)"
                " VALUES ('p','s','APPROVED','because')")

    def test_the_proposer_cannot_record_a_decision(self, proposer):
        """A layer that can record its own approval is marking its own work."""
        with pytest.raises((psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.RaiseException)):
            proposer.execute(
                "INSERT INTO decision_log (product, subject, decision, reason)"
                " VALUES ('p','s','APPROVED','because')")

    def test_the_proposal_layer_cannot_read_how_it_was_graded(self, reader):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("SELECT 1 FROM decision_log")

    def test_the_read_only_console_can_read_and_not_write(self, dsns):
        with psycopg.connect(dsns["console_reader"]) as c:
            assert c.execute("SELECT count(*) FROM decision_outcomes"
                             ).fetchone()[0] == 0
        with psycopg.connect(dsns["console_reader"]) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("INSERT INTO decision_log (product, subject, decision,"
                          " reason) VALUES ('p','s','APPROVED','because')")


# ---- what the human does not have to type ----------------------------------

class TestSubjectAndEvidenceAreCaptured:

    def test_the_subject_comes_from_the_cited_task(self, console):
        task = add_task(console, title="Refund reporting on the orders page")
        row = outcome(console, decide(console, task_id=task, subject=None))
        assert row["subject"] == "Refund reporting on the orders page"

    def test_the_subject_comes_from_the_cited_issue(self, console, admin):
        issue = add_issue(admin)
        row = outcome(console, decide(console, issue_id=issue, subject=None))
        assert "MISSING_ANALYTICS_ORDER" in row["subject"]
        assert "tenant 2" in row["subject"]

    def test_a_decision_citing_nothing_must_name_its_subject(self, console):
        with pytest.raises(psycopg.errors.NotNullViolation,
                           match="needs a subject"):
            decide(console, subject=None)

    def test_the_issue_evidence_is_a_snapshot_not_a_live_read(
            self, console, admin):
        """`current_magnitude` moves. What was in front of the person does not."""
        issue = add_issue(admin)
        admin.execute("UPDATE issues SET current_magnitude=29603,"
                      " current_unit='orders' WHERE id=%s", (issue,))
        did = decide(console, issue_id=issue, subject=None)
        admin.execute("UPDATE issues SET current_magnitude=4, severity='LOW'"
                      " WHERE id=%s", (issue,))

        evidence = outcome(console, did)["evidence"]
        assert len(evidence) == 1
        assert evidence[0]["magnitude"] == 29603
        assert evidence[0]["severity"] == "HIGH"

    def test_the_evidence_comes_from_the_cited_proposal(self, console, proposer):
        """Written by the proposer, captured by the trigger, read by the console.

        Three principals in one test, deliberately: the layer that produced the
        evidence cannot read it back, the person deciding never types it, and
        the row that ends up on the decision is a copy rather than a join.
        """
        pid = proposer.execute(
            """
            INSERT INTO proposals (cycle_id, kind, product, area, finding_key,
                                   title, body, objective_ref, reversibility,
                                   confidence)
            VALUES (gen_random_uuid(), 'OBSERVATION', 'deadly_digital',
                    'analytics', 'issue_open_too_long:abc',
                    'Tenant 2 has an old gap',
                    'It has been open six days.', 'dd-trustworthy', 'TRIVIAL', 1.0)
            RETURNING id
            """).fetchone()["id"]
        proposer.execute(
            """
            INSERT INTO proposal_evidence (proposal_id, adapter, query_key,
                                           value, fetched_at, freshness_bound)
            VALUES (%s, 'detectors', 'issue_open_too_long',
                    '{"days_open": 6, "severity": "CRITICAL"}'::jsonb,
                    now(), interval '2 hours')
            """, (pid,))
        proposer.commit()

        row = outcome(console, decide(console, proposal_id=pid, subject=None))
        assert row["subject"] == "Tenant 2 has an old gap"
        assert len(row["evidence"]) == 1
        assert row["evidence"][0]["kind"] == "proposal_evidence"
        assert row["evidence"][0]["value"]["days_open"] == 6

    def test_evidence_is_empty_rather_than_invented(self, console):
        assert outcome(console, decide(console))["evidence"] == []


# ---- one log ---------------------------------------------------------------

def test_one_log_across_products(console):
    """Product is a column. Two products, one query, both rows."""
    decide(console, product="deadly_digital", subject="one")
    decide(console, product="fleet", subject="two")
    rows = console.execute(
        "SELECT product FROM decision_outcomes ORDER BY id").fetchall()
    assert [r["product"] for r in rows] == ["deadly_digital", "fleet"]
