"""The Overnight section: what the fleet did while nobody was watching.

specs/unattended-operation.md §4. The rest of the brief reports how the
world's numbers moved; this reports what this system DID, and on an
unattended night it is the only section a reader must not miss.

The property these are mostly about is NEGATIVE: a night the pass could not
read must not render as a quiet night. That is the failure mode a counts-only
brief has by construction, and it is the one autonomy makes expensive.
"""
from __future__ import annotations

from datetime import datetime, timezone

from brief.claims import CHANGED, OVERNIGHT, UNCOMPUTED, Claim
from brief.render import render

NOW = datetime(2026, 9, 10, 7, 45, tzinfo=timezone.utc)


def _render(claims):
    return render(claims, generated_at=NOW, compares_since=None,
                  sources_ok=1, sources_failed=0)


def _ov(key, statement, **kw):
    kw.setdefault("value_num", 1)
    return Claim.overnight(key, statement, source="fleet:runs", as_of=NOW, **kw)


def test_overnight_renders_before_what_changed():
    """A reader must not have to scroll past thirteen counts to find it."""
    md = _render([_ov("overnight.runs", "3 run(s) finished"),
                  Claim.computed("x.count", "42 things", source="s", as_of=NOW,
                                 value_num=42)])
    assert md.index("## Overnight") < md.index("## What changed")


def test_a_night_the_pass_could_not_read_does_not_look_quiet():
    """The whole point. An empty Overnight section must send the reader to the
    uncomputed list rather than reading as 'nothing happened'."""
    md = _render([Claim.uncomputed("overnight.runs",
                                   "what the fleet did since the last brief",
                                   reason="the runs table could not be read")])
    assert "## Overnight" in md
    assert "not the same as a quiet night" in md
    assert "the runs table could not be read" in md


def test_nothing_ran_is_a_reading_and_says_so():
    """Distinct from the above: the pass DID read, and found nothing."""
    md = _render([_ov("overnight.runs", "nothing ran since the last brief",
                      value_num=0)])
    assert "nothing ran since the last brief" in md
    assert "not the same as a quiet night" not in md


def test_task_lines_sit_under_the_run_rollup_not_under_spend():
    """Indentation is the only thing saying what these itemise."""
    md = _render([
        _ov("overnight.runs", "2 run(s) finished: 1 merged, 1 failed"),
        _ov("overnight.spend", "GBP 4.20 spent"),
        _ov("overnight.task.31", "task 31 — wrote outside its contract"),
        _ov("overnight.task.30", "task 30 — merged"),
    ])
    lines = md.splitlines()
    rollup = next(i for i, l in enumerate(lines) if "2 run(s) finished" in l)
    spend = next(i for i, l in enumerate(lines) if "GBP 4.20" in l)
    tasks = [i for i, l in enumerate(lines) if l.startswith("  - task ")]
    assert tasks, "the per-task lines were not rendered"
    assert all(rollup < i < spend for i in tasks)


def test_a_failure_class_reaches_the_reader():
    """Boundary violation, could-not-verify and verification-failed are three
    different mornings and must not read alike."""
    md = _render([_ov("overnight.task.31",
                      "task 31 — could not be verified (a checker was missing)")])
    assert "could not be verified (a checker was missing)" in md


def test_spend_is_reported_as_a_rate():
    """A number that only becomes alarming on the last day is not a control."""
    md = _render([_ov("overnight.spend",
                      "GBP 4.20 spent since the last brief; GBP 126.00 "
                      "remains — 30 more night(s) at this rate")])
    assert "more night(s) at this rate" in md


def test_a_drifted_deploy_is_stated_not_implied():
    md = _render([_ov("overnight.deployed.api",
                      "api: production DOES NOT match main (DRIFT)",
                      value_num=None, value_text="DRIFT")])
    assert "DOES NOT match main" in md


def test_overnight_claims_are_not_judgement():
    """LOOKS_WRONG stays empty. Overnight is description, and the renderer's
    refusal to judge is unchanged by adding it."""
    md = _render([_ov("overnight.runs", "3 run(s) finished")])
    assert "carries no judgement" in md


def test_an_overnight_claim_needs_a_value():
    """Same rule as every other claim: no value means UNCOMPUTED with a
    reason, never a statement with nothing behind it."""
    import pytest
    with pytest.raises(ValueError):
        Claim.overnight("k", "s", source="fleet:runs", as_of=NOW)


def test_the_section_constant_matches_the_schema():
    """021 widened the CHECK; a constant that drifts from it writes rows the
    database refuses at the end of a long pass."""
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parent.parent
           / "021_brief_overnight.sql").read_text()
    assert f"'{OVERNIGHT}'" in sql
    for other in (CHANGED, UNCOMPUTED):
        assert f"'{other}'" in sql, f"021 dropped {other} from the vocabulary"
