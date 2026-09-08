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
    monkeypatch.setattr(morning, "_timer_enabled", lambda *a, **k: True)
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
        assert "Nothing completed since the last brief." in body
        assert "Nothing, because you haven&#39;t approved anything." in body \
            or "Nothing, because you haven't approved anything." in body

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
        assert ("covering everything since" in body
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
        monkeypatch.setattr(morning, "_timer_enabled", lambda *a, **k: True)
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


class TestThePromotionGap:
    def test_the_unrecorded_human_step_is_rendered_not_skipped(self):
        """Promoting drafts/ to specs/ has no database row, by design.

        A thread that jumped from a FAILED spec task straight to a queued code
        task would read as though Fleet did that itself, which is the one claim
        this page must never make.
        """
        step = morning.promote_gap()
        assert step.actor == "HUMAN"
        assert step.unrecorded is True
        assert "no database row" in step.detail


class TestTheTimerProbe:
    def test_an_unanswerable_probe_is_not_read_as_enabled(self, monkeypatch):
        """An unknown that resolves to the reassuring answer is decoration."""
        monkeypatch.setattr(morning.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        assert morning._timer_enabled() is None


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
