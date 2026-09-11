"""A candidate that needs two contracts becomes a chain that merges as one.

specs/auto-approval.md §12. Gate 6 held six of the seven live candidates in the
newest batch for spanning two contracts, so the pool was stopped rather than
slow: 19 open, 0 eligible on 11 Sep 2026.

THE HALF-SHIPPED STATE IS UNREPRESENTABLE, NOT DETECTED. No link merges until
every link has verified, so if the second half fails the first was never
merged. That is the property this file exists to hold, and it is the one that
distinguishes this from task 28 -- where the backend merged, the frontend half
was queued by hand six hours later, failed, and candidates 22 and 30 are still
PENDING two days on.
"""
from __future__ import annotations

import json

import pytest

from console import automerge, autoqueue, rank

TWO_BLOCKS = """# Draft — both halves

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
title: backend half
writable_paths:
  - api/analytics/services/segment_engine.py
```

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
title: frontend half
writable_paths:
  - platform/app/(dashboard)/analytics/page.tsx
```
"""


class TestADraftMayDeclareMoreThanOneBlock:
    def test_two_blocks_are_two_links_in_order(self):
        blocks = autoqueue.spec_blocks(TWO_BLOCKS)
        assert [b["title"] for b in blocks] == ["backend half", "frontend half"]

    def test_one_block_still_works(self):
        one = TWO_BLOCKS.split("```fleet-spec")[0] + "```fleet-spec" + \
            TWO_BLOCKS.split("```fleet-spec")[1]
        assert len(autoqueue.spec_blocks(one)) == 1
        assert autoqueue.spec_block(one)["title"] == "backend half"

    def test_no_block_is_refused(self):
        with pytest.raises(autoqueue.QueueRefused, match="no ```fleet-spec"):
            autoqueue.spec_blocks("# just prose\n")

    def test_two_links_declaring_the_same_path_are_refused(self):
        """LOAD BEARING, not tidiness. Each link is built and verified without
        its siblings' changes, which is sound only while they are disjoint —
        two links sharing a file would each be checked against a tree that is
        not the tree that ships, and both could pass while the pair does not
        work."""
        clash = TWO_BLOCKS.replace(
            "platform/app/(dashboard)/analytics/page.tsx",
            "api/analytics/services/segment_engine.py")
        with pytest.raises(autoqueue.QueueRefused, match="both declare"):
            autoqueue.spec_blocks(clash)

    def test_a_malformed_later_block_names_which_one(self):
        bad = TWO_BLOCKS.replace("title: frontend half", "title:\n  - a: [")
        with pytest.raises(autoqueue.QueueRefused, match="block 2 of 2"):
            autoqueue.spec_blocks(bad)


class TestTheHold:
    """The whole feature, expressed as one refusal."""

    def _chain(self, position, length, waiting):
        return {"candidate_id": 33, "position": position, "length": length,
                "waiting": waiting, "complete": not waiting, "failed": []}

    def _task(self):
        return {"id": 70, "acceptance_contract": {"work_type": "dd_api",
                                                  "creatable_paths": ["api/tests/x_*.py"]}}

    def test_a_link_is_held_while_a_sibling_is_not_ready(self):
        v = automerge.eligible(
            self._task(), None,
            self._chain(1, 2, ["task 71 (RUNNING)"]))
        assert v.ok is False
        assert "link 1 of 2" in v.reason
        assert "task 71 (RUNNING)" in v.reason
        assert "none of them shipped" in v.reason

    def test_the_hold_is_ahead_of_the_re_verification(self):
        """It costs a trial clone and a full contract run to be told a sibling
        is still building. The hold is free, so it comes first."""
        v = automerge.eligible(self._task(), None,
                               self._chain(1, 2, ["task 71 (QUEUED)"]))
        assert "not ready" in v.reason
        assert "re-verif" not in v.reason

    def test_a_complete_chain_is_not_held_by_this_rule(self):
        v = automerge.eligible(self._task(), None, self._chain(1, 2, []))
        assert "not ready" not in (v.reason or "")

    def test_a_task_with_no_chain_is_not_held(self):
        """Every existing caller passes no chain and must be unaffected."""
        v = automerge.eligible(self._task(), None, None)
        assert "not ready" not in (v.reason or "")

    def test_the_hard_rules_still_win_over_the_hold(self):
        """A row held by rule 1 today must keep reporting rule 1, or a new
        feature reads as a behaviour change in the brief."""
        task = {"id": 70, "acceptance_contract": {"work_type": "research"}}
        v = automerge.eligible(task, None, self._chain(1, 2, ["task 71"]))
        assert "read by a person" in v.reason


class TestGateSixLetsThemThrough:
    def test_a_spanning_candidate_is_eligible_now(self, console):
        floor = [r["glob"] for r in console.execute(
            "SELECT glob FROM protected_path_floor WHERE repo=%s",
            ("deadly-digital-platform",)).fetchall()]
        w = rank.contract_writables("deadly-digital-platform")
        cand = {"id": 900, "disposition": "PENDING", "batch_id": 1,
                "repo": "deadly-digital-platform",
                "suggested_paths": ["api/analytics/services/segment_engine.py",
                                    "platform/app/(dashboard)/analytics/page.tsx"],
                # A probe that HOLDS, so the row reaches the end of the
                # gates and the recorded split is visible on a pass rather
                # than on some later refusal.
                "probes": [{"path_exists": "api/analytics/services/segment_engine.py"}],
                "premise": []}
        g = rank.gate(cand, newest_batch=1, live_tasks=[], writables=w, floor=floor)
        assert g["eligible"] is True, g.get("detail")
        assert g["rule"] != "spans_contracts"
        assert g.get("spans_contracts") is True, (
            "the split is still recorded; it is no longer a refusal")

    def test_the_later_gates_still_judge_it(self, console):
        """THE BUG THIS TEST EXISTS FOR. The first version of the change
        returned eligible from gate 6, which skipped gates 7 and 8 — so a
        spanning candidate would have been the one kind of row whose probes
        were never re-executed."""
        floor = [r["glob"] for r in console.execute(
            "SELECT glob FROM protected_path_floor WHERE repo=%s",
            ("deadly-digital-platform",)).fetchall()]
        w = rank.contract_writables("deadly-digital-platform")
        cand = {"id": 900, "disposition": "PENDING", "batch_id": 1,
                "repo": "deadly-digital-platform",
                "suggested_paths": ["api/analytics/services/segment_engine.py",
                                    "platform/app/(dashboard)/analytics/page.tsx"],
                "probes": [{"path_exists": "api/nope_not_here.py"}], "premise": []}
        g = rank.gate(cand, newest_batch=1, live_tasks=[], writables=w, floor=floor)
        assert g["eligible"] is False
        assert g["rule"] == "probes_failed"

    def test_a_path_no_contract_covers_is_still_refused(self, console):
        """unwritable_path is a different finding and stays a refusal: no
        chain can be built for a path nothing makes writable."""
        floor = [r["glob"] for r in console.execute(
            "SELECT glob FROM protected_path_floor WHERE repo=%s",
            ("deadly-digital-platform",)).fetchall()]
        w = rank.contract_writables("deadly-digital-platform")
        cand = {"id": 900, "disposition": "PENDING", "batch_id": 1,
                "repo": "deadly-digital-platform",
                "suggested_paths": ["api/analytics/routes"], "probes": [], "premise": []}
        g = rank.gate(cand, newest_batch=1, live_tasks=[], writables=w, floor=floor)
        assert g["rule"] == "unwritable_path"


class TestAHalfFailedChainIsReleasedAndNotResumed:
    def test_it_is_found_when_one_link_died_and_another_holds(self):
        rows = [{"candidate_id": 33, "position": 1, "task_id": 70,
                 "status": "READY_FOR_REVIEW"},
                {"candidate_id": 33, "position": 2, "task_id": 71,
                 "status": "FAILED"}]
        from console import morning
        asks = morning.half_failed_chains(rows)
        assert len(asks) == 1
        assert asks[0].kind == "CHAIN_HALF_FAILED"
        assert asks[0].needs == "NEEDS_YOU"
        assert "none of them merged" in asks[0].headline

    def test_a_chain_that_wholly_failed_is_not_this_finding(self):
        """Nothing is held and nothing half-shipped; it is an ordinary failed
        candidate and reporting it here would bury the ones that matter."""
        from console import morning
        rows = [{"candidate_id": 33, "position": 1, "task_id": 70, "status": "FAILED"},
                {"candidate_id": 33, "position": 2, "task_id": 71, "status": "FAILED"}]
        assert morning.half_failed_chains(rows) == []

    def test_a_wholly_merged_chain_is_not_reported(self):
        from console import morning
        rows = [{"candidate_id": 33, "position": 1, "task_id": 70, "status": "MERGED"},
                {"candidate_id": 33, "position": 2, "task_id": 71, "status": "MERGED"}]
        assert morning.half_failed_chains(rows) == []

    def test_the_ask_says_the_branches_are_kept(self):
        from console import morning
        rows = [{"candidate_id": 33, "position": 1, "task_id": 70,
                 "status": "READY_FOR_REVIEW"},
                {"candidate_id": 33, "position": 2, "task_id": 71, "status": "FAILED"}]
        detail = morning.half_failed_chains(rows)[0].detail
        assert "branches are kept" in detail
        assert "not retried" in detail


class TestTheChainTableRefusesWhatWouldBreakIt:
    def test_a_task_may_belong_to_only_one_chain(self, console):
        """A task held by one chain and merged by another is the half-ship
        arriving through the bookkeeping."""
        import psycopg
        cid = console.execute(
            "INSERT INTO candidate_batches (source_document, source_sha,"
            " source_repo) VALUES ('d','s','fleet') RETURNING id").fetchone()["id"]
        c1 = console.execute(
            "INSERT INTO candidates (batch_id, title, rationale, repo, band,"
            " probes, premise, suggested_paths, evidence)"
            " VALUES (%s,'a','r','fleet','daily','[]','[]','{}','[]') RETURNING id",
            (cid,)).fetchone()["id"]
        c2 = console.execute(
            "INSERT INTO candidates (batch_id, title, rationale, repo, band,"
            " probes, premise, suggested_paths, evidence)"
            " VALUES (%s,'b','r','fleet','daily','[]','[]','{}','[]') RETURNING id",
            (cid,)).fetchone()["id"]
        # The protected list is READ, never typed: enforce_contract_floor
        # refuses a contract that does not protect every floored path, and a
        # hand-written list fails for a reason that is not what is under test.
        floor = [r["glob"] for r in console.execute(
            "SELECT glob FROM protected_path_floor WHERE repo='fleet'").fetchall()]
        tid = console.execute(
            "INSERT INTO tasks (title, spec_md, repo, base_branch,"
            " acceptance_contract, max_cost_gbp, timeout_seconds)"
            " VALUES ('t','```fleet-spec\\nwork_type: research\\n```','fleet',"
            " 'master', %s, 1.00, 600) RETURNING id",
            (json.dumps({"work_type": "research", "writable_paths": ["research/**"],
                         "protected_paths": floor}),)
        ).fetchone()["id"]
        console.execute(
            "INSERT INTO task_chain (candidate_id, position, contract_file,"
            " declared_paths, task_id) VALUES (%s,1,'a.yaml','{x}',%s)", (c1, tid))
        with pytest.raises(psycopg.errors.UniqueViolation):
            console.execute(
                "INSERT INTO task_chain (candidate_id, position, contract_file,"
                " declared_paths, task_id) VALUES (%s,1,'b.yaml','{y}',%s)",
                (c2, tid))
        console.rollback()

    def test_the_runner_cannot_write_a_chain(self, console):
        """A link that could edit its own chain could release the hold on its
        own sibling."""
        got = console.execute(
            "SELECT has_table_privilege('fleet_task_runner','task_chain','UPDATE') p"
        ).fetchone()
        assert got["p"] is False
