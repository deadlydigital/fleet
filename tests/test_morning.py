"""The morning page.

What these protect, in one line each:

  the EMPTY morning renders sentences, not blanks  -> TestTheEmptyMorning
  a missing value is a dot and never a zero        -> TestNeverAZero
  built, merged and deployed stay three states     -> TestShipped
  a state file is only as true as its mtime        -> TestFreshness
  the same failure twice is one finding            -> TestPatterns
  no source and a broken source are different      -> TestUninstrumented
  a batch reason is not printed five times         -> TestTheBatchReason
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from console import deploys, morning

NOW = datetime.now(timezone.utc)


def _thread_row(**over):
    """One row shaped like MORNING_THREADS, defaulted to the boring case.

    Written out rather than fetched so a column added to the query fails these
    tests loudly instead of being silently absent from every fixture.
    """
    row = dict(
        candidate_id=1, title="A candidate", repo="deadly-digital-platform",
        objective_ref="dd-feature-parity", disposition="APPROVED",
        decided_at=NOW, batch_id=1,
        decision_id=None, decision_reason="because", decision_at=NOW,
        decided_by="eamonn", decided_via=None,
        spec_task_id=None, spec_status=None, spec_completed_at=NOW,
        spec_branch="fleet/task-7", spec_work_type="draft_spec",
        spec_cost=1.0, spec_elapsed=60.0, spec_merged_via=None,
        work_task_id=None, work_status=None, work_completed_at=NOW,
        work_branch="fleet/task-8", work_work_type="dd_frontend",
        work_cost=2.0, work_elapsed=120.0, work_merged_via=None)
    row.update(over)
    return row


@pytest.fixture
def client(dsns, monkeypatch, tmp_path):
    """The console, with both off-database reads pointed somewhere empty.

    `deploys.SAMPLES` and the systemd probe are the two things on this page
    that read the HOST rather than the database. Left alone they would make
    every assertion here depend on what this particular box happens to be
    running, and the empty-morning tests would pass or fail according to
    whether a drift check had fired.

    Both drift checks are given a fresh OK, because "an empty morning" means
    nothing is blocking -- and an ABSENT deploy check is genuinely a blocker,
    which TestAHostThatCannotSee below asserts separately. A fixture that left
    them absent would make every empty-state test pass for the wrong reason.
    """
    from console import app as app_module
    monkeypatch.setattr(app_module.config, "repo_root",
                        lambda: Path("/nonexistent"))
    for name in ("drift.state", "drift-frontend.state"):
        (tmp_path / name).write_text("status=OK\ndetail=" + "c" * 40 + "\n")
    monkeypatch.setattr(deploys, "SAMPLES", tmp_path)
    monkeypatch.setattr(morning, "units", dict)
    with TestClient(app_module.app) as c:
        yield c


# ---------------------------------------------------------------------------
# The empty morning — designed first, because it is most mornings
# ---------------------------------------------------------------------------


class TestTheEmptyMorning:
    """Nothing happened. That must read as a fact, not as a broken page."""

    def test_every_section_renders_a_sentence_with_no_data(self, client):
        r = client.get("/")
        assert r.status_code == 200
        body = r.text

        assert "Nothing is waiting on you." in body
        assert "Nothing completed." in body
        assert "could not see" in body
        # The section this used to assert on is gone. It looked for "Nothing,
        # because you haven't approved anything -- the queue is empty and only
        # an approval fills it", which described a loop where a queue only
        # filled if the reader filled it. console/autoapprove.py fills it on a
        # timer, so the queue is a line in the overnight chain now and not a
        # heading of its own.
        assert "you haven" not in body

    def test_the_empty_page_has_no_zeroes_standing_in_for_absence(self, client):
        """The failure mode this page is most likely to have.

        An empty section rendered as `£0.00` or `0m00s` claims a measurement
        nobody made. The dot is the only thing allowed to stand where a value
        is missing.
        """
        body = client.get("/").text
        stand = body[body.find('class="stand"'):]
        assert "£0.00" not in stand

    def test_it_says_which_window_it_is_reporting_on(self, client):
        """A page reporting 'since' nothing in particular reports nothing."""
        body = client.get("/").text
        assert ("everything since" in body
                or "first brief" in body
                or "no brief has ever run" in body)


class TestAHostThatCannotSee:
    """The empty morning is only empty when the host is actually healthy."""

    def test_an_absent_deploy_check_is_itself_a_blocker(
        self, dsns, monkeypatch, tmp_path
    ):
        """A check that has never run is not the same as a check saying OK.

        Without this the page would read "nothing is waiting on you" on a box
        where nothing can tell whether anything shipped -- the most reassuring
        possible rendering of the least verified state.
        """
        from console import app as app_module
        monkeypatch.setattr(app_module.config, "repo_root",
                            lambda: Path("/nonexistent"))
        monkeypatch.setattr(deploys, "SAMPLES", tmp_path)   # empty: no files
        monkeypatch.setattr(morning, "units", dict)
        with TestClient(app_module.app) as c:
            body = c.get("/").text
        assert "Nothing is waiting on you." not in body
        assert "whether the frontend has shipped" in body


# ---------------------------------------------------------------------------
# The two rules carried over from /briefs
# ---------------------------------------------------------------------------


class TestNeverAZero:
    def test_a_missing_elapsed_is_a_dot(self):
        assert morning.human_elapsed(None) == "·"

    def test_a_missing_cost_is_a_dot(self):
        assert morning.money(None) == "·"

    def test_a_real_zero_is_still_rendered_as_a_number(self):
        """The rule is about ABSENCE, not about small values.

        A run that genuinely cost nothing is a fact worth printing. Collapsing
        it into the same dot as "we have no record" would lose exactly the
        distinction the dot exists to make.
        """
        assert morning.money(0) == "£0.00"
        assert morning.human_elapsed(0) == "0s"


# ---------------------------------------------------------------------------
# Built, merged, deployed
# ---------------------------------------------------------------------------


def _dep(name="api", status="OK", checked_at=None, sha="a" * 40):
    checked_at = checked_at or NOW
    return deploys.Deployment(name=name, status=status, detail=sha, sha=sha,
                              checked_at=checked_at,
                              age=NOW - checked_at)


class TestShipped:
    def test_a_merged_frontend_change_cannot_be_called_shipped(self):
        """The live case on this host, and the reason the module exists.

        drift-frontend.state reads UNKNOWN because the image carries no
        GIT_SHA. A page that treated 'merged' as 'live' would be asserting
        something no check has verified for five days.
        """
        deps = {"api": _dep(), "frontend": _dep("frontend", status="UNKNOWN")}
        verdict, why = deploys.shipped("dd_frontend", NOW - timedelta(hours=2),
                                       deps)
        assert verdict == "CANNOT_SAY"
        assert why

    def test_a_merged_api_change_with_a_fresh_ok_is_shipped(self):
        deps = {"api": _dep(), "frontend": _dep("frontend", status="UNKNOWN")}
        verdict, _ = deploys.shipped("dd_api", NOW - timedelta(hours=2), deps)
        assert verdict == "SHIPPED"

    def test_a_check_that_ran_before_the_merge_has_not_seen_it(self):
        """An OK from 09:30 says nothing about a branch merged at 09:35.

        This is the subtle one. The state file is fresh, the status is OK, and
        the answer is still 'cannot say' -- because the check has not looked
        since the thing being asked about happened.
        """
        deps = {"api": _dep(checked_at=NOW - timedelta(minutes=20))}
        verdict, why = deploys.shipped("dd_api", NOW - timedelta(minutes=5),
                                       deps)
        assert verdict == "CANNOT_SAY"
        assert "not looked since" in why

    def test_work_with_nothing_to_deploy_is_not_reported_as_undeployed(self):
        """A research document has no running copy to be behind."""
        deps = {"api": _dep()}
        for work_type in ("research", "draft_spec", "dd_docs"):
            verdict, _ = deploys.shipped(work_type, NOW, deps)
            assert verdict == "NOTHING_TO_SHIP", work_type


class TestFreshness:
    def test_a_state_file_nobody_has_written_for_hours_is_stale(self, tmp_path):
        """drift-platform.state has read OK since 26 August.

        A status with no timestamp beside it is a claim about the past wearing
        the present tense. The check runs every 15 minutes, so an hour of
        silence means it stopped, and its last answer is not today's.
        """
        p = tmp_path / "drift.state"
        p.write_text("status=OK\ndetail=" + "b" * 40 + "\n")
        old = (NOW - timedelta(days=13)).timestamp()
        import os
        os.utime(p, (old, old))

        d = deploys._parse(p, "api")
        assert d.status == "STALE"
        assert not d.usable
        assert "stopped" in d.detail

    def test_an_absent_state_file_says_so_rather_than_reading_ok(self, tmp_path):
        d = deploys._parse(tmp_path / "nope.state", "api")
        assert d.status == "ABSENT"
        assert not d.usable

    def test_prose_in_the_detail_field_is_not_mistaken_for_a_commit(self, tmp_path):
        """The frontend check writes a sentence where the api writes a sha."""
        p = tmp_path / "drift-frontend.state"
        p.write_text("status=UNKNOWN\ndetail='x' carries no GIT_SHA\n")
        d = deploys._parse(p, "frontend")
        assert d.sha is None
        assert d.short_sha == ""


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------


def _fail(task_id, tail, command="/x/y/draft_spec_shape.py", when=None):
    return {"task_id": task_id, "command": command, "output_tail": tail,
            "completed_at": when or NOW, "exit_code": 1}


class TestPatterns:
    #: The two real failures from 8 Sep 2026, verbatim.
    T23 = ("FAIL: drafts/coupon-discount-report.md cites repo paths in prose "
           "that resolve in neither deadly-digital-platform nor fleet: "
           "['api/analytics/routes/coupons.py', "
           "'api/analytics/services/coupon_report.py']\n")
    T24 = ("FAIL: drafts/product-performance-by-category.md cites repo paths "
           "in prose that resolve in neither deadly-digital-platform nor "
           "fleet: ['api/analytics/services/category_report.py', "
           "'routes/categories.py']\n")

    def test_two_specs_failing_the_same_check_are_one_finding(self):
        """The addition asked for on 8 Sep.

        Two rows saying FAILED is not the thing worth seeing; a spec-writer
        getting paths wrong two times in four is.
        """
        pats = morning.failure_patterns(
            [_fail(23, self.T23), _fail(24, self.T24)], None, attempted=4)
        assert len(pats) == 1
        assert sorted(pats[0].task_ids) == [23, 24]
        assert pats[0].of_total == 4

    def test_the_gist_is_the_shape_and_not_one_instance(self):
        """A claim about the step must not quote one task's filename."""
        pats = morning.failure_patterns(
            [_fail(23, self.T23), _fail(24, self.T24)], None, attempted=4)
        assert "coupon-discount-report.md" not in pats[0].gist
        assert "product-performance" not in pats[0].gist
        assert "cites repo paths in prose" in pats[0].gist

    def test_one_failure_is_not_a_pattern(self):
        """A single failure reads better as its own thread.

        A pattern asserts something about the step, and one instance cannot.
        """
        assert morning.failure_patterns([_fail(23, self.T23)], None, 4) == []

    def test_different_checks_do_not_group(self):
        other = _fail(30, "FAIL: ruff introduced 3 new findings",
                      command="/x/ruff_no_new_findings.py")
        pats = morning.failure_patterns(
            [_fail(23, self.T23), _fail(24, self.T24), other], None, 5)
        assert len(pats) == 1

    def test_failures_before_the_window_are_not_counted(self):
        old = _fail(9, self.T23, when=NOW - timedelta(days=3))
        pats = morning.failure_patterns(
            [old, _fail(24, self.T24)], NOW - timedelta(hours=6), 4)
        assert pats == []


# ---------------------------------------------------------------------------
# What could not be seen
# ---------------------------------------------------------------------------


class TestUninstrumented:
    """An objective with no source, versus a claim with a broken one."""

    def test_an_objective_with_no_claim_of_any_kind_is_reported(self, tmp_path):
        path = tmp_path / "obj.yaml"
        path.write_text(json.dumps({"objectives": [
            {"id": "pi-revenue", "weight": 0.25, "statement": "PI converts",
             "signals": ["MRR"]},
        ]}))
        out = morning.uninstrumented_objectives(path, claim_keys=["dd.x"])
        assert [o["id"] for o in out] == ["pi-revenue"]
        assert out[0]["weight"] == 0.25

    def test_an_objective_whose_claim_merely_failed_is_NOT_reported(self, tmp_path):
        """cost-discipline is represented — as cost.aws.monthly_gbp UNCOMPUTED.

        THE DISTINCTION IS THE POINT. A broken source already appears in the
        uncomputed list with its reason. Repeating it here would file it twice
        and, worse, would put a quarter of the quarter in the same visual
        weight as a gap that is already being reported.
        """
        path = tmp_path / "obj.yaml"
        path.write_text(json.dumps({"objectives": [
            {"id": "cost-discipline", "weight": 0.05, "statement": "AWS"},
            {"id": "pi-revenue", "weight": 0.25, "statement": "PI"},
        ]}))
        # cost.aws.monthly_gbp is present as a KEY even though it is uncomputed.
        out = morning.uninstrumented_objectives(
            path, claim_keys=["cost.aws.monthly_gbp"])
        assert [o["id"] for o in out] == ["pi-revenue"]

    def test_the_real_objectives_file_reports_exactly_punter_insight(self):
        """Against the file as it actually is, not a fixture.

        dd-* is instrumented, cost-discipline has a broken source, pi-revenue
        has never had one. If that changes this test should fail and be read.
        """
        out = morning.uninstrumented_objectives(claim_keys=[
            "dd.analytics_1.orders.count", "cost.aws.monthly_gbp",
            "fleet.tasks.total"])
        assert [o["id"] for o in out] == ["pi-revenue"]


# ---------------------------------------------------------------------------
# Shaping
# ---------------------------------------------------------------------------


class TestTheBatchReason:
    def test_a_long_batch_reason_is_excerpted_with_an_ellipsis(self):
        """One reason covers up to five candidates, by design.

        Printed whole on every thread it appears five times and buries them.
        The ellipsis is required: a reason cut off without one reads as a
        complete thought that happens to be terse.
        """
        long = ("First merchant onboarding is the goal, so trust ranks above "
                "parity. " + "More reasoning follows and keeps going. " * 6)
        out = morning.excerpt(long)
        assert len(out) < len(long)
        assert out.endswith("…")

    def test_a_short_reason_is_left_alone(self):
        assert morning.excerpt("Because it matters.") == "Because it matters."

    def test_no_reason_is_empty_rather_than_None(self):
        assert morning.excerpt(None) == ""


class TestThePromotionStepIsGone:
    """It described a hand step that console/autoqueue.py removed.

    The old test asserted `promote_gap()` produced a HUMAN step saying
    "drafts/ to specs/ is a git commit". Accepting a draft merges it and
    queues the code task in the same request; the draft stays in drafts/.
    Kept as a test rather than deleted so the removal is something the suite
    states.
    """

    def test_there_is_no_promotion_step_to_build(self):
        assert not hasattr(morning, "promote_gap")

    def test_a_thread_goes_from_the_draft_to_the_build_with_no_hand_step(self):
        rows = [_thread_row(spec_task_id=7, spec_status="MERGED",
                            spec_merged_via="unattended",
                            work_task_id=8, work_status="RUNNING")]
        t = morning.build_threads(rows, {}, {})[0]
        labels = [s.label for s in t.steps]
        assert not any("specs/" in x for x in labels)
        assert labels.index("Merged the draft unattended") < \
            labels.index("Built the change")


class TestWhoDidIt:
    """The page must not credit the reader with a decision a timer made."""

    def test_an_unattended_approval_is_not_you(self):
        t = morning.build_threads(
            [_thread_row(decision_id=1, decided_via="unattended")], {}, {})[0]
        step = [s for s in t.steps if s.status == "APPROVED"][0]
        assert step.actor == "AUTO"
        assert "you" not in step.label.lower()

    def test_a_console_approval_is_you(self):
        t = morning.build_threads(
            [_thread_row(decision_id=1, decided_via="console")], {}, {})[0]
        step = [s for s in t.steps if s.status == "APPROVED"][0]
        assert step.actor == "HUMAN"

    def test_a_decision_written_before_the_column_existed_is_a_person(self):
        """NULL is every approval made before 026 added the column, and all of
        those were somebody clicking Accept."""
        assert morning.actor_of(None) == "HUMAN"

    def test_an_unattended_merge_does_not_say_you_merged_it(self):
        t = morning.build_threads(
            [_thread_row(work_task_id=8, work_status="MERGED",
                         work_merged_via="unattended")], {}, {})[0]
        step = [s for s in t.steps if s.label.startswith("Merged")][0]
        assert step.actor == "AUTO"


class TestAMergedDraftThatQueuedNothing:
    """automerge logs the refusal and does not fail the sweep, so this is the
    one state where nothing is wrong and nothing happens either."""

    def test_it_is_a_gap_and_not_a_silence(self):
        t = morning.build_threads(
            [_thread_row(spec_task_id=7, spec_status="MERGED",
                         work_task_id=None)], {}, {})[0]
        gap = [s for s in t.steps if s.status == "NOT_QUEUED"]
        assert len(gap) == 1
        assert gap[0].actor == "GAP"

    def test_a_draft_that_has_not_merged_yet_is_not_a_gap(self):
        t = morning.build_threads(
            [_thread_row(spec_task_id=7, spec_status="RUNNING",
                         work_task_id=None)], {}, {})[0]
        assert not [s for s in t.steps if s.status == "NOT_QUEUED"]


class TestTheTimerProbe:
    def test_an_unanswerable_probe_is_not_read_as_enabled(self, monkeypatch):
        """An unknown that resolves to the reassuring answer is decoration.

        `_timer_enabled` watched one timer and was replaced by `units()`,
        which watches four. The property it existed to hold is unchanged and
        is asserted here against its replacement.
        """
        monkeypatch.setattr(morning.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        stages = morning.units()
        assert stages and all(st.unreadable for st in stages.values())
        assert all(st.enabled is None for st in stages.values())


class TestAThreadIsNotInTwoSectionsAtOnce:
    """"What I did" and "what's next" must not both claim the same work."""

    def _thread(self, *steps):
        t = morning.Thread(key="k", title="t", repo="r", objective_ref=None)
        t.steps = list(steps)
        return t

    def test_an_approval_alone_is_not_something_that_got_done(self):
        """Task 25: approved at 23:08, never ran, still QUEUED.

        Its only in-window event is the reader's own approval. Listing it under
        "what I did" claims work that has not happened, while it correctly also
        appears under "what I'm doing next" — and one of those two has to be
        wrong.
        """
        approved_at = NOW - timedelta(hours=2)
        t = self._thread(
            morning.Step(actor="FLEET", label="Proposed as a candidate"),
            morning.Step(actor="HUMAN", label="You approved it",
                         when=approved_at, status="APPROVED"),
            morning.Step(actor="FLEET", label="Wrote a draft spec",
                         when=None, status="QUEUED"))
        assert t.progressed_since(NOW - timedelta(hours=6)) is False
        assert morning.in_window([t], NOW - timedelta(hours=6)) == []

    def test_a_thread_whose_task_finished_in_the_window_did_get_done(self):
        t = self._thread(
            morning.Step(actor="HUMAN", label="You approved it",
                         when=NOW - timedelta(hours=5), status="APPROVED"),
            morning.Step(actor="FLEET", label="Wrote a draft spec",
                         when=NOW - timedelta(hours=1), status="FAILED"))
        assert t.progressed_since(NOW - timedelta(hours=6)) is True

    def test_work_that_finished_before_the_window_is_not_re_reported(self):
        t = self._thread(
            morning.Step(actor="FLEET", label="Wrote a draft spec",
                         when=NOW - timedelta(days=4), status="MERGED"))
        assert t.progressed_since(NOW - timedelta(hours=6)) is False


# ---------------------------------------------------------------------------
# The overnight chain. Added 10 Sep 2026 with the redesign.
#
# Every test here is about the page's fourth rule -- that it never says
# "nothing is wrong" when it means "I could not look" -- because that is the
# rule the chain section exists to keep. Three units decide things with nobody
# watching, and each of them can be off, broken, or unreadable.
# ---------------------------------------------------------------------------


class TestReadingAUnit:
    def test_a_unit_that_cannot_be_read_is_a_gap_and_not_a_silence(
            self, monkeypatch):
        """The whole section is worthless if this returns an empty Stage.

        A stage that could not be read must not arrive looking like a stage
        that ran and did nothing: `enabled` and `ok` stay None, which is what
        the template tests to decide whether to say anything at all.
        """
        monkeypatch.setattr(morning, "_show", lambda *a, **k: None)
        stages = morning.units()
        assert len(stages) == len(morning.CHAIN)
        for st in stages.values():
            assert st.unreadable is True
            assert st.enabled is None and st.ok is None

    def test_every_stage_is_present_even_when_the_unit_is_not_installed(
            self, monkeypatch):
        """`systemctl show` answers happily about a unit that does not exist.

        A chain built from what systemd could find would drop a stage the
        night depends on and look complete doing it.
        """
        monkeypatch.setattr(morning, "_show",
                            lambda unit, props: {"LoadState": "not-found"})
        stages = morning.units()
        assert len(stages) == len(morning.CHAIN)
        assert all(not st.installed for st in stages.values())

    def test_a_dry_run_is_read_off_the_unit_and_not_assumed(self, monkeypatch):
        """It ran --dry-run for two months and this page reported its
        decisions as events."""
        monkeypatch.setattr(morning, "_show", lambda unit, props: {
            "LoadState": "loaded", "Result": "success",
            "ExecStart": "{ argv[]=/x/python /x/run_automerge.py --dry-run }"})
        assert all(st.dry_run for st in morning.units().values())

    def test_dry_run_is_matched_as_a_word_and_not_as_a_substring(
            self, monkeypatch):
        """A path containing the text must not mark a live unit as a dry run:
        that errs towards telling the reader LESS happened than did."""
        monkeypatch.setattr(morning, "_show", lambda unit, props: {
            "LoadState": "loaded",
            "ExecStart": "{ argv[]=/opt/--dry-run-notes/python /x/run.py }"})
        assert not any(st.dry_run for st in morning.units().values())

    def test_a_failed_result_is_not_read_as_success(self, monkeypatch):
        monkeypatch.setattr(morning, "_show", lambda unit, props: {
            "LoadState": "loaded", "Result": "exit-code"})
        assert all(st.ok is False for st in morning.units().values())

    def test_a_result_systemd_did_not_give_is_not_read_as_either(
            self, monkeypatch):
        monkeypatch.setattr(morning, "_show",
                            lambda unit, props: {"LoadState": "loaded"})
        assert all(st.ok is None for st in morning.units().values())


class TestATimestampThatIsNotOne:
    def test_a_unit_that_has_never_run_has_no_last_time(self):
        assert morning._stamp("") is None
        assert morning._stamp("n/a") is None
        assert morning._stamp(None) is None

    def test_a_real_stamp_parses_as_utc(self):
        t = morning._stamp("Thu 2026-09-10 03:30:01 UTC")
        assert t is not None and t.hour == 3 and t.tzinfo is not None


class TestTheScheduleIsShortenedOnlyWhenItIsSafeTo:
    def test_a_plain_daily_time_loses_its_seconds(self):
        st = morning.Stage(key="k", name="n", unit="u", schedule="03:30:00")
        assert st.schedule_short == "03:30"

    def test_a_repeat_expression_is_left_alone(self):
        """`02..04:00/20:00` also ends in `:00`, and cutting it would turn
        "every twenty minutes between two and four" into nonsense."""
        st = morning.Stage(key="k", name="n", unit="u",
                           schedule="02..04:00/20:00")
        assert st.schedule_short == "02..04:00/20:00"


class TestWhatTheNightDecided:
    def test_no_decisions_is_not_reported_as_approving_nothing(self):
        """A night the ranker declined and a night the timer never fired are
        the same silence in decision_log. Only the unit can tell them apart,
        so this must not put words in the database's mouth."""
        stages = {"approve": morning.Stage(key="approve", name="n", unit="u")}
        morning.describe_night(stages, [])
        assert stages["approve"].said == ""

    def test_a_refusal_is_reported_as_much_as_an_approval(self):
        stages = {"approve": morning.Stage(key="approve", name="n", unit="u")}
        morning.describe_night(stages, [{"decision": "DEFERRED"}])
        assert "declined" in stages["approve"].said

    def test_approvals_and_refusals_are_counted_separately(self):
        stages = {"approve": morning.Stage(key="approve", name="n", unit="u")}
        morning.describe_night(stages, [{"decision": "APPROVED"},
                                        {"decision": "APPROVED"},
                                        {"decision": "DEFERRED"}])
        assert "2 approvals" in stages["approve"].said
        assert "1 night" in stages["approve"].said


class TestTheWholeChainIsWatched:
    """It watched fleet-runner.timer alone, which was right while the runner
    was the only thing that ran unattended. Three more units decide things
    now, and a page that checked one of four would report a silent night as a
    quiet one."""

    def _stages(self, **over):
        out = {}
        for key, name, unit in morning.CHAIN:
            out[key] = morning.Stage(key=key, name=name, unit=unit,
                                     enabled=True, ok=True)
        for k, v in over.items():
            for attr, val in v.items():
                setattr(out[k], attr, val)
        return out

    def test_a_healthy_chain_asks_for_nothing(self):
        assert morning.fleet_blocked(None, {}, self._stages()) == []

    def test_a_disabled_timer_anywhere_in_the_chain_is_an_ask(self):
        for key, _, unit in morning.CHAIN:
            asks = morning.fleet_blocked(
                None, {}, self._stages(**{key: {"enabled": False}}))
            assert [a for a in asks if a.kind == "UNIT_DISABLED"], unit

    def test_a_failed_unit_is_an_ask_and_says_what_did_not_happen(self):
        asks = morning.fleet_blocked(
            None, {}, self._stages(merge={"ok": False}))
        failed = [a for a in asks if a.kind == "UNIT_FAILED"]
        assert len(failed) == 1
        assert "fleet-automerge" in failed[0].headline

    def test_an_unreadable_unit_is_an_ask_rather_than_nothing(self):
        asks = morning.fleet_blocked(
            None, {}, self._stages(deploy={"unreadable": True}))
        assert [a for a in asks if a.kind == "UNIT_UNREADABLE"]

    def test_a_missing_committed_figure_is_a_dot_and_not_a_zero(self):
        """The credit blocker formatted `float(x or 0)` and put £0.00 beside
        a month nobody had read a figure for."""
        asks = morning.fleet_blocked(
            {"status": "UNCOMPUTED", "uncomputed_reason": "no reading",
             "committed_gbp": None}, {}, {})
        assert dict(asks[0].meta)["committed so far"] == "·"


class TestTheRequirementsOfAMergeNobodyRead:
    def test_a_spec_with_numbered_requirements_becomes_an_ask(self):
        rows = [{"task_id": 61, "title": "t", "repo": "r", "merged_at": NOW,
                 "merge_commit": "a" * 40,
                 "spec_md": "### 2. The page sends them\n"
                            "**2.5 The table cells set the filters.** ..."}]
        out = morning.unread_specs(rows)
        assert len(out) == 1
        assert [q.id for q in out[0].reqs] == ["2", "2.5"]
        assert out[0].merge_commit == "a" * 12

    def test_a_spec_with_nothing_numbered_produces_no_ask(self):
        """An empty checklist beside a merge reads as "nothing to check",
        which is a claim, and the wrong one."""
        rows = [{"task_id": 61, "title": "t", "repo": "r", "merged_at": NOW,
                 "merge_commit": "", "spec_md": "Just some prose."}]
        assert morning.unread_specs(rows) == []


class TestWhereAThreadGotTo:
    def _t(self, *statuses):
        t = morning.Thread(key="k", title="t", repo="r", objective_ref=None)
        t.steps = [morning.Step(actor="FLEET", label="x", status=s)
                   for s in statuses]
        return t

    def test_the_furthest_step_wins_not_the_last(self):
        """A task that failed and was merged by hand has both statuses, and
        it did not fail."""
        assert self._t("FAILED", "MERGED").outcome == "MERGED"

    def test_a_deploy_check_that_cannot_answer_does_not_make_it_a_failure(self):
        assert self._t("MERGED", "CANNOT_SAY").outcome == "MERGED"

    def test_a_merged_draft_that_queued_nothing_is_not_filed_as_a_failure(self):
        assert self._t("NOT_QUEUED").outcome == "NOT_QUEUED"

    def test_shipped_beats_merged(self):
        assert self._t("MERGED", "SHIPPED").outcome == "SHIPPED"
