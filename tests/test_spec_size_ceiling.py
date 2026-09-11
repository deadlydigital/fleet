"""A spec may not be bigger than the contract will pay for.

Task 62 bought the same lesson twice in one afternoon:

    attempt 1   £3.00 at the spend cap, no branch, nothing derived
    attempt 2   £5.02, agent exit 0, 494 lines against a 400-line limit

Both are the same fact — the spec is too big for one task — arriving as two
different ceilings, neither of which says so. Its spec numbers 25 requirements
against a contract whose largest MERGED spec numbers 5, and
contracts/checks/spec_requirements_cited.py obliges the diff to cite every leaf
of those 25.

A CEILING, NOT AN ESTIMATE. Nothing in this system estimates what work will
cost from its spec — `autoqueue` takes the contract's flat `max_cost_gbp` and
always has. This does not fill that gap. It refuses a spec far outside what the
contract has ever delivered, before the money, in a sentence naming both
numbers.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from console import requirements

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = sorted((ROOT / "contracts").glob("*.yaml"))


def _c(name):
    return yaml.safe_load((ROOT / "contracts" / name).read_text())


class TestTheCeilingIsSetWhereItIsNeeded:
    @pytest.mark.parametrize("name", [
        "deadly-digital-platform-api.yaml", "dd-analytics-frontend.yaml",
        "dd-order-filters.yaml", "dd-acquiring-page.yaml",
        "dd-utm-source-alias.yaml", "dd-docstring-proving.yaml",
        "dd-infra.yaml"])
    def test_every_code_contract_declares_one(self, name):
        """A code contract has a diff limit and a spend cap, and both stop an
        oversized spec only after a run has been bought."""
        assert _c(name).get("max_requirements"), (
            f"{name} has a max_diff_lines and a max_cost_gbp but no "
            f"max_requirements, so an oversized spec is discovered by paying "
            f"for it")

    @pytest.mark.parametrize("name", ["research.yaml", "research-metorik-gap.yaml"])
    def test_research_is_deliberately_uncapped(self, name):
        """It produces a DOCUMENT. It has no diff limit to blow, and its two
        merged specs numbered 17 and 23 without trouble. A ceiling here would
        refuse work that has only ever succeeded."""
        assert _c(name).get("max_requirements") is None

    def test_the_ceiling_clears_what_has_actually_merged(self):
        """Measured, not chosen: dd_api's largest merged spec numbers 5 and
        dd_frontend's numbers 8. A ceiling below those would refuse work that
        has already shipped."""
        assert _c("deadly-digital-platform-api.yaml")["max_requirements"] >= 5
        assert _c("dd-analytics-frontend.yaml")["max_requirements"] >= 8


class TestItRefusesTheSpecThatFailedTwice:
    #: Task 62's shape: six top-level requirements, nineteen sub.
    def _spec(self, groups=6, per=3):
        out = ["# Draft\n"]
        for g in range(1, groups + 1):
            out.append(f"### {g}. Section {g}\n")
            for s in range(1, per + 1):
                out.append(f"**{g}.{s} Thing {s}.** prose\n")
        return "\n".join(out)

    def test_a_spec_over_the_ceiling_is_counted_as_over(self):
        spec = self._spec()
        n = len(requirements.parse(spec))
        assert n == 24, n
        assert n > _c("deadly-digital-platform-api.yaml")["max_requirements"]

    def test_a_spec_the_size_of_one_that_merged_is_not(self):
        """Task 26's spec numbers 5 and merged. The ceiling must not refuse
        the work it was measured from."""
        spec = self._spec(groups=1, per=4)
        n = len(requirements.parse(spec))
        assert n == 5, n
        assert n <= _c("deadly-digital-platform-api.yaml")["max_requirements"]

    def test_the_refusal_names_both_numbers(self):
        """A refusal that says only "too big" sends the reader to guess which
        ceiling and by how much."""
        src = (ROOT / "console" / "autoqueue.py").read_text()
        assert "the spec numbers {len(numbered)} requirements and" in src
        assert "accepts {ceiling}" in src

    def test_it_is_checked_before_the_task_row_is_written(self):
        """Before the money. The point is not to fail the run better."""
        src = (ROOT / "console" / "autoqueue.py").read_text()
        i = src.index("max_requirements")
        j = src.index("INSERT INTO tasks")
        assert i < j, "the ceiling must be read before any task is created"


class TestTheRealSpecsInThePool:
    """The ceiling against every spec this system has actually produced."""

    def test_no_merged_spec_would_have_been_refused(self, console):
        """The one property that would make this a bad gate: refusing work
        that already shipped."""
        rows = console.execute(
            "SELECT id, spec_md, acceptance_contract->>'work_type' wt, status"
            "  FROM tasks WHERE status='MERGED' AND spec_md IS NOT NULL").fetchall()
        by_wt = {}
        for c in CONTRACTS:
            d = yaml.safe_load(c.read_text()) or {}
            if d.get("work_type") and d.get("max_requirements"):
                by_wt.setdefault(d["work_type"], []).append(d["max_requirements"])
        offenders = []
        for r in rows:
            caps = by_wt.get(r["wt"])
            if not caps:
                continue
            n = len(requirements.parse(r["spec_md"] or ""))
            if n > max(caps):
                offenders.append((r["id"], r["wt"], n, max(caps)))
        assert offenders == [], (
            f"the ceiling would have refused work that merged: {offenders}")
