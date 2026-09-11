"""Accepting a draft spec queues the code task it describes.

specs/auto-approval.md §8: creating the code task was the largest remaining
hand step -- approve_batch makes ONLY draft-spec tasks, so every code task on
this host was typed by a person. This removes it.

WHAT THESE TESTS ARE MOSTLY ABOUT is what it refuses. A step that used to be a
person typing an INSERT is now a function reading a document written by an
agent, and the document declares the boundary its own work will run under. The
one thing that must not be possible is a spec widening its own contract.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from console import autoqueue


def sh(repo, *args):
    subprocess.run(args, cwd=repo, check=True, capture_output=True)


def _block(**over):
    b = {"work_type": "dd_frontend", "repo": "deadly-digital-platform",
         "title": "Carry the four order filters onto the orders page",
         "writable_paths": ["platform/app/api/analytics/orders/route.ts"]}
    b.update(over)
    return b


def _draft(block=None, prose="# A draft spec\n\nWords.\n"):
    import yaml
    if block is None:
        block = _block()
    return prose + "\n```fleet-spec\n" + yaml.safe_dump(block) + "```\n"


class TestReadingTheBlock:

    def test_the_block_is_read(self):
        b = autoqueue.spec_block(_draft())
        assert b["work_type"] == "dd_frontend"
        assert b["title"].startswith("Carry the four")

    def test_no_block_is_refused(self):
        with pytest.raises(autoqueue.QueueRefused, match="no ```fleet-spec"):
            autoqueue.spec_block("# Just prose\n")

    def test_two_blocks_are_two_links_now(self):
        """CHANGED 11 Sep 2026 — this asserted that two blocks were refused.

        specs/auto-approval.md §12: a candidate whose paths no single contract
        covers is split by the draft into an ordered chain, one block per link,
        and no link merges until every link has verified. Refusing the second
        block was the rule that made gate 6 hold six of the seven live
        candidates in the newest batch.

        `spec_block` still returns one — the first — for callers that want
        exactly one. `spec_blocks` is the chain.
        """
        two = _draft() + _draft({**_block(), "writable_paths": ["api/other.py"]})
        assert len(autoqueue.spec_blocks(two)) == 2
        assert autoqueue.spec_block(two) == autoqueue.spec_blocks(two)[0]

    def test_two_blocks_declaring_the_same_path_are_still_refused(self):
        """The disjointness the chain rests on. Links are verified without
        each other's changes, which is only sound while no two can write the
        same file."""
        with pytest.raises(autoqueue.QueueRefused, match="both declare"):
            autoqueue.spec_blocks(_draft() + _draft())

    @pytest.mark.parametrize("field", ["work_type", "repo", "title",
                                       "writable_paths"])
    def test_a_missing_field_is_refused(self, field):
        b = _block()
        del b[field]
        with pytest.raises(autoqueue.QueueRefused, match="missing"):
            autoqueue.spec_block(_draft(b))

    def test_writable_paths_must_be_a_list(self):
        with pytest.raises(autoqueue.QueueRefused, match="not a list"):
            autoqueue.spec_block(_draft(_block(writable_paths="one/path.ts")))

    def test_invalid_yaml_is_refused(self):
        bad = "# x\n\n```fleet-spec\nwork_type: [unclosed\n```\n"
        with pytest.raises(autoqueue.QueueRefused, match="not valid YAML"):
            autoqueue.spec_block(bad)


class TestWhichFileTheDraftWrote:
    """From the run's own PATCH_PROPOSED, never from a guess at the name."""

    def test_the_one_draft_is_found(self):
        assert autoqueue.draft_path(
            {"files_changed": ["drafts/order-filters.md"]}) == \
            "drafts/order-filters.md"

    def test_two_drafts_are_refused(self):
        with pytest.raises(autoqueue.QueueRefused, match="2 markdown"):
            autoqueue.draft_path({"files_changed": ["drafts/a.md", "drafts/b.md"]})

    def test_a_file_outside_drafts_is_not_a_draft(self):
        """draft-spec.yaml makes drafts/** writable and nothing else, so a
        markdown file elsewhere is not the artefact this task produces."""
        with pytest.raises(autoqueue.QueueRefused, match="0 markdown"):
            autoqueue.draft_path({"files_changed": ["specs/promoted.md"]})


class TestTheContractItWouldRunUnder:

    def test_work_type_alone_does_not_identify_a_contract(self):
        """dd_frontend matches two: dd-analytics-frontend.yaml and the spent
        single-task dd-acquiring-page.yaml. Without the declared paths there is
        nothing to choose on, and choosing anyway is what draft_spec_shape.py
        does by filesystem order -- §9.13."""
        with pytest.raises(autoqueue.QueueRefused, match="matches 2 contracts"):
            autoqueue._contract_for("dd_frontend", "deadly-digital-platform")

    def test_the_declared_paths_break_the_tie(self):
        contract, name = autoqueue._contract_for(
            "dd_frontend", "deadly-digital-platform",
            ["platform/app/api/analytics/orders/route.ts"])
        assert name == "dd-analytics-frontend.yaml"

    def test_and_they_choose_the_other_one_when_they_fit_it(self):
        """The tie-break is a real discriminator, not a preference for the
        newer file: a spec about the acquiring page fits only that contract."""
        contract, name = autoqueue._contract_for(
            "dd_frontend", "deadly-digital-platform",
            ["platform/components/layout/Sidebar.tsx"])
        assert name == "dd-acquiring-page.yaml"

    def test_paths_fitting_neither_refuse_rather_than_pick(self):
        with pytest.raises(autoqueue.QueueRefused, match="fit 0 of them"):
            autoqueue._contract_for("dd_frontend", "deadly-digital-platform",
                                    ["platform/lib/auth.ts"])

    def test_an_unknown_work_type_is_refused(self):
        with pytest.raises(autoqueue.QueueRefused, match="names no contract"):
            autoqueue._contract_for("dd_nonexistent", "deadly-digital-platform")

    def test_the_right_repo_is_required(self):
        """A work_type contracted for another repo is not this one's."""
        with pytest.raises(autoqueue.QueueRefused, match="names no contract"):
            autoqueue._contract_for("dd_frontend", "fleet")

    def test_the_refusal_says_the_contracts_may_have_moved(self):
        """draft_spec_shape.py checked against the contracts as they were when
        the draft RAN. This queues against them as they are NOW, and the gap
        between the two is where a retired contract would surface."""
        with pytest.raises(autoqueue.QueueRefused, match="as they are now"):
            autoqueue._contract_for("dd_gone", "deadly-digital-platform")


class TestASpecMayNotWidenItsContract:
    """The one thing that must not be possible.

    draft_spec_shape.py checked the declared paths against the contract's
    PROTECTED list. A path that is neither protected nor writable passes that
    and is still outside the boundary the task runs under -- the runner would
    refuse it after the money was spent, and on the unattended path nobody
    would be watching when it did.
    """

    def test_a_path_inside_the_writable_set_is_allowed(self):
        contract, _ = autoqueue._contract_for(
            "dd_frontend", "deadly-digital-platform",
            ["platform/app/api/analytics/orders/route.ts"])
        assert autoqueue._inside(
            "platform/app/api/analytics/orders/route.ts",
            list(contract["writable_paths"]))

    def test_a_path_outside_it_is_not(self):
        contract, _ = autoqueue._contract_for(
            "dd_frontend", "deadly-digital-platform",
            ["platform/app/api/analytics/orders/route.ts"])
        for p in ("platform/lib/auth.ts",
                  "platform/app/api/billing/checkout/route.ts",
                  "api/analytics/routes/orders.py"):
            assert not autoqueue._inside(p, list(contract["writable_paths"])), p

    def test_a_glob_prefix_does_not_match_a_sibling(self):
        """`platform/app/(dashboard)/analytics/orders/**` must not reach
        `.../analytics/orders-admin/page.tsx`."""
        globs = ["platform/app/(dashboard)/analytics/orders/**"]
        assert autoqueue._inside(
            "platform/app/(dashboard)/analytics/orders/page.tsx", globs)
        assert not autoqueue._inside(
            "platform/app/(dashboard)/analytics/orders-admin/page.tsx", globs)


class TestWhatItQueues:

    @pytest.fixture
    def merged_draft(self, dsns, console, tmp_path, monkeypatch):
        """A fleet repo with a merged draft, and the spec task that made it."""
        root = tmp_path / "repos"
        repo = root / "fleet"
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "master")
        sh(repo, "git", "config", "user.email", "t@t")
        sh(repo, "git", "config", "user.name", "t")
        (repo / "drafts").mkdir()
        (repo / "drafts" / "order-filters.md").write_text(_draft())
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-q", "-m", "the merged draft")
        merged = subprocess.run(("git", "-C", str(repo), "rev-parse", "HEAD"),
                                capture_output=True, text=True).stdout.strip()
        monkeypatch.setattr(autoqueue.config, "repo_root", lambda: root)

        from console import approve
        contract, _c, _t, _b = approve._draft_spec_contract()
        row = console.execute(
            "INSERT INTO tasks (title, spec_md, repo, base_branch,"
            " acceptance_contract, max_cost_gbp, status, objective_ref)"
            " VALUES ('Draft spec: x','spec','fleet','master',%s,2.00,"
            " 'QUEUED','dd-feature-parity') RETURNING id",
            (json.dumps(contract),)).fetchone()
        console.commit()
        task = dict(console.execute(
            "SELECT * FROM tasks WHERE id=%s", (row["id"],)).fetchone())
        return task, {"files_changed": ["drafts/order-filters.md"]}, merged

    def test_it_queues_the_task_the_spec_describes(self, merged_draft, console):
        task, patch, merged = merged_draft
        q = autoqueue.from_accepted_draft(task, patch, merged)
        assert q.task_id is not None
        row = console.execute(
            "SELECT title, repo, base_branch, status, spec_md,"
            " acceptance_contract AS c FROM tasks WHERE id=%s",
            (q.task_id,)).fetchone()
        assert row["repo"] == "deadly-digital-platform"
        assert row["status"] == "QUEUED"
        assert row["c"]["work_type"] == "dd_frontend"
        # THE WHOLE DRAFT, not a summary: the requirements checklist and the
        # brief both parse spec_md, and a summary would lose the numbering.
        assert "```fleet-spec" in row["spec_md"]

    def test_the_frozen_contract_carries_auto_merge(self, merged_draft, console):
        """The task runs under the contract as it is AT QUEUEING, frozen into
        the row -- so a later edit cannot change what this task was allowed."""
        task, patch, merged = merged_draft
        q = autoqueue.from_accepted_draft(task, patch, merged)
        c = console.execute("SELECT acceptance_contract AS c FROM tasks"
                            " WHERE id=%s", (q.task_id,)).fetchone()["c"]
        assert c["auto_merge"] is True
        # EVERY optional key the contract declares, not a hand-picked pair.
        # This asserted `paired_paths and creatable_paths` until 10 Sep 2026
        # and failed the day the pairings were removed -- not for a key
        # stopping being copied, but for a contract stopping declaring one.
        # A rule written against the keys that happened to exist refuses the
        # next contract for being different, which is the defect
        # test_every_shipped_contract_matches_the_repo_it_names had.
        import yaml
        from pathlib import Path as _P
        shipped = yaml.safe_load(
            (_P(__file__).resolve().parent.parent / "contracts"
             / "dd-analytics-frontend.yaml").read_text())
        for opt in ("creatable_paths", "paired_paths", "worktree_links",
                    "readable_repos", "agent_tools", "contract_version"):
            if shipped.get(opt) is not None:
                assert c.get(opt) == shipped[opt], (
                    f"{opt} is in the contract and not in the frozen row")
        assert c["creatable_paths"]

    def test_the_objective_is_carried_from_the_spec_task(self, merged_draft,
                                                         console):
        task, patch, merged = merged_draft
        q = autoqueue.from_accepted_draft(task, patch, merged)
        assert console.execute("SELECT objective_ref FROM tasks WHERE id=%s",
                               (q.task_id,)).fetchone()["objective_ref"] == \
            "dd-feature-parity"

    def test_it_links_the_candidate_that_asked_for_it(self, merged_draft,
                                                      console):
        """§9.8: work_task_id is read by two ceilings and was written by
        nobody, because the step that should have written it was the hand
        INSERT this function replaces."""
        task, patch, merged = merged_draft
        b = console.execute(
            "INSERT INTO candidate_batches (source_document, source_sha,"
            " source_repo) VALUES ('d','s','fleet') RETURNING id").fetchone()["id"]
        c = console.execute(
            "INSERT INTO candidates (batch_id,title,rationale,repo,spec_task_id)"
            " VALUES (%s,'t','because the finding said so','deadly-digital-platform',%s)"
            " RETURNING id", (b, task["id"])).fetchone()["id"]
        console.commit()

        q = autoqueue.from_accepted_draft(task, patch, merged)
        assert q.candidate_id == c
        assert console.execute("SELECT work_task_id FROM candidates WHERE id=%s",
                               (c,)).fetchone()["work_task_id"] == q.task_id

    def test_a_spec_widening_its_contract_queues_nothing(self, merged_draft,
                                                         console):
        task, patch, merged = merged_draft
        repo = autoqueue.config.repo_root() / "fleet"
        (repo / "drafts" / "order-filters.md").write_text(
            _draft(_block(writable_paths=["platform/lib/auth.ts"])))
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-q", "-m", "widened")
        merged = subprocess.run(("git", "-C", str(repo), "rev-parse", "HEAD"),
                                capture_output=True, text=True).stdout.strip()

        before = console.execute("SELECT count(*) AS n FROM tasks").fetchone()["n"]
        # It refuses, and WHICH refusal fires depends on how many contracts
        # share the work_type. platform/lib/auth.ts fits neither dd_frontend
        # contract, so resolution refuses before the widening check is reached.
        # Both are true statements and both queue nothing, which is the
        # property under test.
        with pytest.raises(autoqueue.QueueRefused):
            autoqueue.from_accepted_draft(task, patch, merged)
        assert console.execute(
            "SELECT count(*) AS n FROM tasks").fetchone()["n"] == before

    def test_widening_an_unambiguous_contract_says_so_in_those_words(
            self, merged_draft, console):
        """The branch that carries the sentence a person needs.

        It needs a work_type with exactly ONE contract, so that resolution
        succeeds and widening is what refuses. THREE of the seven work_types
        are ambiguous -- dd_api matches three contracts, dd_frontend two,
        research two -- because four spent single-task contracts (tasks 2, 3, 7
        and the metorik producer) still declare the same work_type as the
        general ones. §9.13. dd_infra is the one that is unambiguous, so it is
        what this uses."""
        task, patch, _ = merged_draft
        repo = autoqueue.config.repo_root() / "fleet"
        (repo / "drafts" / "order-filters.md").write_text(_draft(_block(
            work_type="dd_infra",
            writable_paths=["platform/lib/auth.ts"])))
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-q", "-m", "api widening")
        merged = subprocess.run(("git", "-C", str(repo), "rev-parse", "HEAD"),
                                capture_output=True, text=True).stdout.strip()

        before = console.execute("SELECT count(*) AS n FROM tasks").fetchone()["n"]
        with pytest.raises(autoqueue.QueueRefused, match="cannot widen"):
            autoqueue.from_accepted_draft(task, patch, merged)
        assert console.execute(
            "SELECT count(*) AS n FROM tasks").fetchone()["n"] == before

    def test_the_spec_is_read_from_the_MERGED_base(self, merged_draft, console):
        """Not from the branch. What is queued is what landed -- if the merge
        resolved differently from the branch tip, the branch is not what runs."""
        task, patch, merged_before = merged_draft
        repo = autoqueue.config.repo_root() / "fleet"
        (repo / "drafts" / "order-filters.md").write_text(
            _draft(_block(title="A LATER TITLE")))
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-q", "-m", "later")

        q = autoqueue.from_accepted_draft(task, patch, merged_before)
        assert "LATER" not in q.title
