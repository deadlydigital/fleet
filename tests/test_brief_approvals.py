"""The Overnight section's approvals: what was ticked with nobody watching.

specs/auto-approval.md §4. An approval produces no run, so without this a night
where auto-approval queued four wrong specs and the runner then ran them reads
as four ordinary failures with no clue where they came from.

  the approvals sit ABOVE the runs they caused  -> TestOrder
  the signal the ranker may not read is printed -> TestWhatTheReaderSees
  what it PASSED OVER, and why                  -> TestWhatTheReaderSees
  the undo is a real command                    -> TestTheUndoIsCopyPaste
  end to end, off a real sweep                  -> TestFromARealApproval
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from brief import pass_ as P
from brief import sources as S
from brief.claims import Claim
from brief.render import render
from console import autoapprove

NOW = datetime(2026, 9, 10, 7, 45, tzinfo=timezone.utc)


def _render(claims):
    return render(claims, generated_at=NOW, compares_since=None,
                  sources_ok=1, sources_failed=0)


def _ov(key, statement, **kw):
    kw.setdefault("value_num", 1)
    return Claim.overnight(key, statement, source="fleet:decision_log",
                           as_of=NOW, **kw)


class TestOrder:
    def test_approvals_render_above_the_runs_they_caused(self):
        md = _render([
            _ov("overnight.runs", "4 run(s) finished: 0 merged, 4 failed"),
            _ov("overnight.approvals", "4 candidate(s) auto-approved"),
        ])
        assert md.index("auto-approved") < md.index("run(s) finished")

    def test_approval_detail_sits_under_the_approval_rollup(self):
        md = _render([
            _ov("overnight.approvals", "1 candidate(s) auto-approved"),
            _ov("overnight.approval.20", "c20 -> task 51 — daily: Forward"),
            _ov("overnight.runs", "1 run(s) finished"),
        ])
        lines = [l for l in md.splitlines() if l.strip()]
        roll = next(i for i, l in enumerate(lines) if "auto-approved" in l)
        det = next(i for i, l in enumerate(lines) if "c20 -> task 51" in l)
        runs = next(i for i, l in enumerate(lines) if "run(s) finished" in l)
        assert roll < det < runs
        assert lines[det].startswith("  - ")


class TestWhatTheReaderSees:
    """Built from mechanics rather than re-derived, so the brief reports what
    the decision actually rested on rather than what it would rest on now."""

    def _rows(self, *, signal=None, held=None):
        return [{
            "id": 47,
            "decided_at": NOW,
            "reason": "Candidate 20 was taken because ...",
            "mechanics": {
                "rank_version": 1,
                "platform_sha": "6fd8ddd5e4269278dc64bc80d1198a85871d6619",
                "probes": {"run": 32, "held": 32},
                "credit": {"reserved": 2.0},
                "ranked": held or [],
            },
            "approved": [{"candidate_id": 20, "title": "Forward the filters",
                          "band": "daily", "hib_signal": signal,
                          "task_id": 51}],
        }]

    def _claims(self, monkeypatch, rows):
        class _R:
            def probe(self, key, body):
                if key == "fleet:decision_log/approvals":
                    return rows
                # fleet_month_credit(): a TUPLE, read positionally, with the
                # 60% figure appended at index 8 by 026.
                return (None, "COMPUTED", 158.0, "s", NOW, 18.91, 139.09,
                        None, 75.89)

            def failed(self, key):
                return None
        return P._approval_claims(_R(), NOW - timedelta(days=1))

    def test_the_signal_is_printed_verbatim(self, monkeypatch):
        """§2.2 established the ranker cannot read it. This is where it goes
        instead: in front of the one reader who can, on the morning the work
        has not been built yet."""
        sig = {"value": "refund_total non-zero on 1 of 2,844,177 orders",
               "as_of": "2026-08-28", "source": "specs/metorik-gap.md"}
        md = _render(self._claims(monkeypatch, self._rows(signal=sig)))
        assert "refund_total non-zero on 1 of 2,844,177 orders" in md
        assert "2026-08-28" in md

    def test_no_signal_says_the_document_stated_none(self, monkeypatch):
        """Different from the field being missing, and the brief says which."""
        md = _render(self._claims(monkeypatch, self._rows(signal=None)))
        assert "none stated in the source document" in md

    def test_the_reserved_spend_and_the_60_percent_line_are_both_shown(
            self, monkeypatch):
        md = _render(self._claims(monkeypatch, self._rows()))
        assert "GBP 2.00 reserved" in md
        assert "GBP 139.09 remains" in md
        assert "GBP 75.89" in md and "60% stop" in md

    def test_the_top_row_it_passed_over_is_named_with_the_rule(
            self, monkeypatch):
        """A ranking is wrong in what it PASSED OVER, and a list of what it
        took cannot show that."""
        held = [{"candidate_id": 21, "eligible": False, "rule": "path_overlap",
                 "detail": "names platform/app/(dashboard)/analytics/page.tsx, "
                           "which queued task 49 declares"},
                {"candidate_id": 22, "eligible": False, "rule": "path_overlap",
                 "detail": "same file, same task"}]
        md = _render(self._claims(monkeypatch, self._rows(held=held)))
        assert "passed over c21" in md
        assert "queued task 49 declares" in md
        assert "2 row(s) held in total" in md

    def test_the_probe_count_is_shown(self, monkeypatch):
        """A night where a gate silently stopped running reads identically to
        a night where everything held."""
        md = _render(self._claims(monkeypatch, self._rows()))
        assert "32 of 32 held" in md
        assert "6fd8ddd" in md

    def test_a_quiet_night_says_so_rather_than_rendering_nothing(self):
        class _R:
            def probe(self, key, body):
                return [] if key == "fleet:decision_log/approvals" else None

            def failed(self, key):
                return None
        claims = P._approval_claims(_R(), NOW - timedelta(days=1))
        md = _render(claims)
        assert "0 candidate(s) were auto-approved since the last brief" in md

    def test_an_unreadable_log_is_not_a_quiet_night(self):
        class _R:
            def probe(self, key, body):
                return None

            def failed(self, key):
                return "permission denied for table decision_log"
        claims = P._approval_claims(_R(), NOW - timedelta(days=1))
        # UNCOMPUTED, never an empty section: "the log could not be read" and
        # "nothing was approved" are different mornings, and only one of them
        # means the reader can stop looking. The reason is the source's own
        # message where it has one -- an interpretation layered over it would
        # be this pass guessing at a failure it did not diagnose.
        assert len(claims) == 1
        assert claims[0].status == "UNCOMPUTED"
        md = _render(claims)
        assert "permission denied" in md
        assert "auto-approved" not in md


class TestTheUndoIsCopyPaste:
    def test_the_brief_prints_the_undo_command(self, monkeypatch):
        class _R:
            def probe(self, key, body):
                if key == "fleet:decision_log/approvals":
                    return [{"id": 47, "decided_at": NOW, "reason": "r",
                             "mechanics": {"rank_version": 1,
                                           "platform_sha": "6fd8ddd",
                                           "probes": {"run": 32, "held": 32},
                                           "credit": {"reserved": 2.0},
                                           "ranked": []},
                             "approved": []}]
                return (None, "COMPUTED", 158.0, "s", NOW, 18.91, 139.09, None,
                        75.89)

            def failed(self, key):
                return None
        md = _render(P._approval_claims(_R(), NOW - timedelta(days=1)))
        assert "./fleet candidates undo 47" in md

    def test_that_command_actually_exists(self):
        """A copy-paste undo that is not a real command is worse than no line:
        it reads as a safety net right up until somebody needs it."""
        import subprocess
        import sys
        r = subprocess.run(
            [sys.executable, "fleet", "candidates", "undo", "--help"],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "decision_id" in r.stdout


class TestFromARealApproval:
    """End to end: sweep(), then read the brief claims off what it wrote."""

    def test_a_real_sweep_produces_a_readable_approval_section(
            self, dsns, console, admin):
        from tests.test_autoapprove import (
            _batch, _cand, _pool, API_PRESENT, PLATFORM_FEATURE_MISSING,
            EXISTS, ABSENT_FILE, PLATFORM)

        _pool(admin)
        b = _batch(console)
        top = _cand(console, b, title="Forward the four order filters",
                    repo=PLATFORM,
                    probes=[API_PRESENT, PLATFORM_FEATURE_MISSING],
                    signal={"value": "payment_method populated on 2,782,530 "
                                     "of 2,844,177 orders",
                            "as_of": "2026-08-28",
                            "source": "specs/metorik-gap.md"})
        _cand(console, b, title="A new report", probes=[EXISTS, ABSENT_FILE])

        out = autoapprove.sweep()
        assert out["approve_ids"] == [top]

        rows = console.execute(
            P._APPROVALS_SQL,
            {"since": datetime.now(timezone.utc) - timedelta(hours=1)}
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["mechanics"]["rank_version"] == 1
        assert rows[0]["approved"][0]["candidate_id"] == top
        # The signal survives the whole chain: block -> column -> mechanics
        # row -> brief. That chain is what dropped it before there was a loader.
        assert "2,782,530" in rows[0]["approved"][0]["hib_signal"]["value"]


# ---- the night that decided nothing ----------------------------------------

class TestARefusedNightIsARecordedNight:
    """A refusal used to write no row at all, so it rendered as a quiet night.

    "the ranker declined because no key separated the top two" and "the timer
    never fired" produced the same brief, which is the exact defect this whole
    section exists to prevent, arriving on the section itself.
    """

    def _rows(self, *, streak=1, reason=None):
        return [{
            "id": 31,
            "decided_at": NOW - timedelta(hours=6),
            "reason": reason or (
                "candidates 20 and 21 are indistinguishable on every key that "
                "means anything: both frontend-only, both band daily, and only "
                "the candidate id separates them."),
            "streak": streak,
            "mechanics": {
                "cut": {"n": 1, "bound_by": ["per_night"],
                        "limits": {"per_night": 1}},
                "ranked": [{"candidate_id": 20, "eligible": True},
                           {"candidate_id": 21, "eligible": True},
                           {"candidate_id": 17, "eligible": False,
                            "rule": "older_batch"}],
            },
        }]

    def _claims(self, rows):
        class _R:
            def probe(self, key, body):
                return rows if key == "fleet:decision_log/refusals" else None

            def failed(self, key):
                return None
        return P._refusal_claims(_R(), NOW - timedelta(days=1))

    def test_the_refusal_and_its_reason_are_rendered(self):
        md = _render(self._claims(self._rows()))
        assert "approved nothing" in md
        assert "indistinguishable on every key" in md

    def test_a_single_refusal_does_not_claim_a_streak(self):
        md = _render(self._claims(self._rows(streak=1)))
        assert "night(s) running" not in md

    def test_a_run_of_refusals_is_counted_and_named_as_the_pool(self):
        """One refused night is Tuesday. Five is the keys being exhausted."""
        md = _render(self._claims(self._rows(streak=5)))
        assert "5 night(s) running" in md
        assert "the pool, not the night" in md

    def test_how_many_rows_passed_every_gate_is_shown(self):
        """Refusing with two eligible rows and refusing with none are
        different mornings: one is a tie, the other is a pool with nothing
        approvable in it."""
        md = _render(self._claims(self._rows()))
        assert "2 row(s) passed every gate" in md
        assert "bound by per_night" in md

    def test_no_refusal_renders_nothing_rather_than_a_reassuring_line(self):
        assert self._claims([]) == []

    def test_an_unreadable_log_is_not_a_night_without_a_refusal(self):
        class _R:
            def probe(self, key, body):
                return None

            def failed(self, key):
                return "permission denied for table decision_log"
        claims = P._refusal_claims(_R(), NOW - timedelta(days=1))
        assert claims and claims[0].uncomputed_reason
