"""The spec's numbered requirements, listed beside the diff.

specs/auto-approval.md §9.9. No contract check reads the spec: task 53 shipped
§2.5 unbuilt with tsc, vitest, the bite check and paired_paths all green. On a
contract with auto_merge: false this page is the only reader, and the reader
who missed §2.5 had a 250-line spec against a 300-line diff.

This list checks nothing. §9.12 measured the cheap version that would --
grepping the diff for the requirement number scored 1 for §2.1 and §2.5 (both
stray digits) and 0 for §2.2 and §2.3, which were implemented -- so it would
have refused working changes and passed the missing one. These tests hold the
line between "makes the reading systematic" and "makes a claim".
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from console import requirements


def parse(md):
    return requirements.parse(textwrap.dedent(md))


class TestWhatCountsAsARequirement:

    def test_a_numbered_heading_counts(self):
        r = parse("""
            ## What to build
            ### 1. The proxy forwards the four parameters
            prose
            ### 2. The page sends them
            """)
        assert [(x.id, x.title) for x in r] == [
            ("1", "The proxy forwards the four parameters"),
            ("2", "The page sends them")]

    def test_a_numbered_bold_lead_counts_and_nests(self):
        """Task 53's real shape: the sub-requirements that were missed."""
        r = parse("""
            ### 2. The page sends them
            **2.5 The table cells set the filters.** Exact matching is only
            usable if the user can produce the exact string.
            """)
        assert [(x.id, x.depth) for x in r] == [("2", 0), ("2.5", 1)]
        assert r[1].title == "The table cells set the filters."

    def test_an_unnumbered_heading_does_not_count(self):
        """A checklist containing things the spec did not number is one the
        reviewer learns to distrust, and the first item they dismiss is the one
        that mattered."""
        assert parse("## What is wrong\n### Clearing\n") == []

    def test_prose_that_reads_like_an_instruction_does_not_count(self):
        assert parse("Do not introduce a second mechanism for filter state.\n") == []

    def test_a_bare_bold_number_does_not_count(self):
        """`**1. Something**` is how paragraphs are often emphasised. Only a
        DOTTED id is taken as a sub-requirement."""
        assert parse("**1. A bold opening.** and then prose\n") == []

    def test_identifiers_survive_cleaning(self):
        """has_discount, not hasdiscount. The list exists so a reviewer can
        look for these exact strings in the diff; mangling them defeats it."""
        r = parse("**2.1 `has_discount` is three-state, not a checkbox.** x\n")
        assert r[0].title == "has_discount is three-state, not a checkbox."

    def test_examples_inside_a_fence_are_not_requirements(self):
        r = parse("""
            ### 1. Real
            ```
            ### 2. An example in a code block
            **3.1 Also an example.**
            ```
            ### 4. Also real
            """)
        assert [x.id for x in r] == ["1", "4"]

    def test_a_repeated_id_is_listed_once(self):
        """A spec referring back to 2.5 is citing it, not restating it."""
        r = parse("""
            **2.5 The table cells set the filters.** first
            **2.5 The table cells set the filters.** cited again later
            """)
        assert [x.id for x in r] == ["2.5"]

    def test_a_long_title_is_truncated_not_dropped(self):
        r = parse("### 1. " + "word " * 60 + "\n")
        assert r and r[0].title.endswith("…") and len(r[0].title) <= 110

    def test_no_spec_is_no_list_rather_than_an_error(self):
        assert requirements.parse(None) == []
        assert requirements.parse("") == []


class TestTheRealSpecs:
    """Parsed from the specs on disk, not from fixtures written to agree."""

    def test_task_53s_spec_yields_the_requirement_that_was_missed(self):
        md = (Path(__file__).resolve().parent.parent
              / "drafts" / "order-filters-frontend.md").read_text()
        r = requirements.parse(md)
        ids = [x.id for x in r]
        assert ids == ["1", "2", "2.1", "2.2", "2.3", "2.4", "2.5", "3"]
        missed = next(x for x in r if x.id == "2.5")
        assert missed.title == "The table cells set the filters."

    def test_a_promoted_spec_with_only_top_level_sections_parses(self):
        p = (Path(__file__).resolve().parent.parent
             / "specs" / "net-revenue-after-refunds.md")
        if not p.exists():
            pytest.skip("that spec is not in this tree")
        assert [x.id for x in requirements.parse(p.read_text())] == \
            ["1", "2", "3", "4", "5"]


class TestItRendersBesideTheDiff:

    @pytest.fixture
    def client(self, dsns, monkeypatch):
        from console import app as app_module
        monkeypatch.setattr(app_module.config, "repo_root",
                            lambda: Path("/nonexistent"))
        with TestClient(app_module.app) as c:
            yield c

    def _task(self, console, spec_md):
        from tests.support import PLATFORM_FLOOR
        import json
        row = console.execute(
            "INSERT INTO tasks (title, spec_md, repo, acceptance_contract,"
            " max_cost_gbp) VALUES ('t',%s,'deadly-digital-platform',%s,2.00)"
            " RETURNING id",
            (spec_md, json.dumps({
                "work_type": "dd_frontend",
                "writable_paths": ["platform/app/(dashboard)/analytics/orders/**"],
                "protected_paths": PLATFORM_FLOOR,
                "verification": ["true"], "max_diff_lines": 400}))).fetchone()
        console.commit()
        return row["id"]

    def test_the_requirements_are_listed(self, client, console):
        tid = self._task(console, "### 1. Do the thing\n"
                                  "**1.2 And the other thing.** prose\n")
        body = client.get(f"/tasks/{tid}").text
        assert "What the spec asked for" in body
        assert "Do the thing" in body and "And the other thing." in body
        assert "2 numbered requirements" in body

    def test_it_says_plainly_that_nothing_is_recorded(self, client, console):
        """A tick that looked persisted would be a claim about state, which is
        the one thing this page must not invent."""
        tid = self._task(console, "### 1. Do the thing\n")
        body = client.get(f"/tasks/{tid}").text
        assert "nothing is recorded" in body

    def test_a_spec_with_no_numbering_renders_no_list_at_all(self, client, console):
        """An empty checklist would read as "nothing to check"."""
        tid = self._task(console, "Just prose, no numbered requirements.\n")
        assert "What the spec asked for" not in client.get(f"/tasks/{tid}").text
