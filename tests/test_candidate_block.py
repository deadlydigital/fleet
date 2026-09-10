"""The candidate producer's acceptance check.

The property that matters: **a claim about the repository is re-executed, not
re-read.** `specs/metorik-gap.md` is 11 days old and two of its four Daily-band
Missing/Partial rows are already wrong at HEAD -- the same two a person caught
by hand when batch 8 was assembled. A parser reproduces both as current
candidates; this check refuses them, and `test_a_stale_claim_is_refused_at_head`
uses the real rows rather than invented ones.

The second property is that the §7 prohibitions are enforced by SHAPE. A block
that sets a disposition cannot pass, so "a producer must not pre-approve" is a
thing the format cannot express rather than an instruction it was asked to
follow.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

CHECK = Path.home() / "fleet" / "contracts" / "checks" / "candidate_block_shape.py"
PY = Path.home() / "fleet" / ".venv" / "bin" / "python"
PLATFORM = Path.home() / "deadly-digital-platform"
GAP_SHA = "73dc37fac0f57eb39b0bd6d5a82297d2b8034e46"


def head() -> str:
    return subprocess.run(("git", "-C", str(PLATFORM), "rev-parse", "HEAD"),
                          capture_output=True, text=True).stdout.strip()


PROSE = textwrap.dedent("""\
    # Candidates from the Metorik gap list

    Re-verified against `deadly-digital-platform`. Evidence:
    `api/analytics/routes/orders.py`, `api/analytics/routes/segments.py`,
    `api/analytics/services/analytics_engine.py`, `specs/metorik-gap.md`,
    `platform/app/(dashboard)/analytics/geography/page.tsx`.

    ## What I could not verify

    Nothing here establishes a claim about the world: whether Metorik still
    ships a feature, whether merchants want one, or whether the document's
    agency-use band is right. The probes prove presence and absence in a
    repository only, and a parameter existing is not a filter working.
    """)


def candidate(**over):
    c = {
        "title": "CSV export of the order list",
        "rationale": ("The only text/csv response in the analytics API is the "
                      "segment export, so orders cannot be got out at all."),
        "repo": "deadly-digital-platform",
        "objective_ref": "dd-feature-parity",
        "suggested_paths": ["api/analytics/routes/orders.py"],
        "verified_sha": head(),
        "hib_signal": None,
        "probes": [{"grep_count": {"glob": "api/analytics/routes/*.py",
                                   "pattern": "text/csv", "expected": 1}}],
        "evidence": [{"document": "specs/metorik-gap.md", "sha": GAP_SHA,
                      "status": "Missing", "agency_use_band": "Daily"}],
    }
    c.update(over)
    return {k: v for k, v in c.items() if v is not ...}


def block(candidates=None, **over):
    b = {
        "source": {"document": "specs/metorik-gap.md", "sha": GAP_SHA},
        "ordering": "unranked",
        "unasked_question": (
            "Nobody has asked HIB's team what they need, so a candidate "
            "justified by an hib_signal is justified by what HIB has rather "
            "than what its team would actually open."),
        "objectives_considered": (
            "Weighed dd-trustworthy against dd-feature-parity for every row. "
            "None of these puts a wrong number in front of a person; they are "
            "reports the product does not have at all, so parity is the "
            "honest label and correctness work is not being deferred by it."),
        "candidates": candidates if candidates is not None else [candidate()],
    }
    b.update(over)
    return b


def run(tmp_path, blk, *, max_candidates=10, body=None, files=None):
    doc = tmp_path / "candidates.md"
    text = body if body is not None else (
        PROSE + "\n```fleet-candidates\n" + yaml.safe_dump(blk) + "```\n")
    doc.write_text(text)
    env = {**os.environ,
           "FLEET_CHANGED_FILES": files if files is not None else doc.name}
    r = subprocess.run((str(PY), str(CHECK), "--max-candidates",
                        str(max_candidates)),
                       cwd=tmp_path, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ---- the live probe --------------------------------------------------------

class TestAClaimIsReExecutedNotReRead:

    def test_a_true_claim_passes(self, tmp_path):
        code, out = run(tmp_path, block())
        assert code == 0, out
        assert "re-executed at HEAD" in out

    def test_a_stale_claim_is_refused_at_head(self, tmp_path):
        """The real row, and the real reason D exists.

        `specs/metorik-gap.md` says routes/orders.py accepts "nothing else"
        beyond status, search and sort. At HEAD it accepts payment_method,
        country, coupon and has_discount. A parser emits this as a current
        candidate; the probe cannot.
        """
        stale = candidate(
            title="Order filtering by payment, location and coupon",
            probes=[{"grep_count": {"glob": "api/analytics/routes/orders.py",
                                    "pattern": "payment_method", "expected": 0}}])
        code, out = run(tmp_path, block([stale]))
        assert code == 1
        assert "probe FAILED at HEAD" in out
        assert "payment_method" in out

    def test_the_other_real_stale_row_is_refused_too(self, tmp_path):
        """"built but unreachable -- there is no page". The page exists."""
        stale = candidate(
            title="Location reports by country and city",
            probes=[{"path_absent":
                     "platform/app/(dashboard)/analytics/geography/page.tsx"}])
        code, out = run(tmp_path, block([stale]))
        assert code == 1 and "probe FAILED at HEAD" in out

    def test_a_candidate_with_no_probe_is_refused(self, tmp_path):
        code, out = run(tmp_path, block([candidate(probes=[])]))
        assert code == 1 and "declares no probes" in out

    def test_a_probe_outside_the_vocabulary_is_refused(self, tmp_path):
        code, out = run(tmp_path, block(
            [candidate(probes=[{"run_shell": "rm -rf /"}])]))
        assert code == 1 and "not in the probe vocabulary" in out

    def test_path_exists_holds_for_something_that_does(self, tmp_path):
        code, out = run(tmp_path, block([candidate(
            probes=[{"path_exists": "api/analytics/routes/orders.py"}])]))
        assert code == 0, out


# ---- the prohibitions ------------------------------------------------------

class TestTheProhibitionsAreInTheShape:

    @pytest.mark.parametrize("field,value", [
        ("disposition", "APPROVED"),
        ("disposition_reason", "looks good"),
        ("work_type", "dd_api"),
        ("batch_id", 8),
        ("spec_task_id", 21),
        ("work_task_id", 26),
        ("approval_decision_id", 22),
    ])
    def test_a_forbidden_field_is_refused(self, tmp_path, field, value):
        code, out = run(tmp_path, block([candidate(**{field: value})]))
        assert code == 1
        assert field in out and "autonomy this refuses" in out


# ---- the six required fields ----------------------------------------------

class TestTheSixRequiredFields:

    @pytest.mark.parametrize("field", [
        "title", "rationale", "repo", "evidence", "suggested_paths",
        "objective_ref"])
    def test_each_is_required(self, tmp_path, field):
        c = candidate()
        del c[field]
        code, out = run(tmp_path, block([c]))
        assert code == 1 and field in out

    def test_objective_ref_may_be_null_but_the_key_must_be_there(self, tmp_path):
        code, out = run(tmp_path, block([candidate(objective_ref=None)]))
        assert code == 0, out

    def test_an_unknown_objective_is_refused(self, tmp_path):
        code, out = run(tmp_path, block([candidate(objective_ref="dd-nope")]))
        assert code == 1 and "does not contain" in out

    def test_evidence_must_carry_the_sha_it_was_read_at(self, tmp_path):
        code, out = run(tmp_path, block([candidate(
            evidence=[{"document": "specs/metorik-gap.md"}])]))
        assert code == 1 and "sha it was read at" in out

    def test_a_thin_rationale_is_refused(self, tmp_path):
        code, out = run(tmp_path, block([candidate(rationale="do it")]))
        assert code == 1 and "rationale" in out

    def test_a_suggested_path_in_a_directory_that_does_not_exist(self, tmp_path):
        code, out = run(tmp_path, block([candidate(
            suggested_paths=["api/nope/nowhere/thing.py"])]))
        assert code == 1 and "does not exist" in out


# ---- the sha, carried per row ---------------------------------------------

class TestEachRowCarriesTheShaItWasVerifiedAt:

    def test_a_missing_sha_is_refused(self, tmp_path):
        c = candidate()
        del c["verified_sha"]
        code, out = run(tmp_path, block([c]))
        assert code == 1 and "verified_sha" in out

    def test_a_sha_that_is_not_a_commit_is_refused(self, tmp_path):
        code, out = run(tmp_path, block([candidate(verified_sha="0" * 40)]))
        assert code == 1 and "not a commit" in out


# ---- hib_signal is a fact, with its age ------------------------------------

class TestHibSignalIsAFactAndCarriesItsAge:
    """`hib_relevant` does not exist in any findings document in either
    repository -- measured, zero hits. So the mechanism is built and reports
    the absence; it never infers one from what HIB happens to have.
    """

    def test_the_key_is_required_even_when_there_is_no_signal(self, tmp_path):
        c = candidate()
        del c["hib_signal"]
        code, out = run(tmp_path, block([c]))
        assert code == 1 and "omits hib_signal" in out

    def test_null_is_accepted_and_means_the_document_declares_none(self, tmp_path):
        code, out = run(tmp_path, block([candidate(hib_signal=None)]))
        assert code == 0, out

    def test_a_signal_without_an_as_of_is_refused(self, tmp_path):
        code, out = run(tmp_path, block(
            [candidate(hib_signal={"value": "HIB ships to 40 countries"})]))
        assert code == 1 and "as_of" in out

    def test_a_signal_with_a_value_and_an_as_of_is_accepted(self, tmp_path):
        code, out = run(tmp_path, block([candidate(
            hib_signal={"value": "HIB ships to 40 countries",
                        "as_of": "2026-07-14"})]))
        assert code == 0, out


# ---- the block does not rank, and says the thing nobody asked --------------

class TestTheBlockDoesNotPretendToRank:

    def test_ordering_must_be_declared_unranked(self, tmp_path):
        code, out = run(tmp_path, block(ordering="by_priority"))
        assert code == 1 and "candidate order is read as rank order" in out

    def test_the_unasked_question_is_required(self, tmp_path):
        code, out = run(tmp_path, block(unasked_question="TODO"))
        assert code == 1 and "asked HIB's team" in out


# ---- the objective was weighed, not inferred from the document's title -----

class TestTheObjectiveWasWeighed:
    """Batch 9 put dd-feature-parity on all nine rows and said nothing.

    Two of those rows are document rows a person had labelled dd-trustworthy
    eleven days earlier. objectives-2026-Q4.yaml predicted it in its own
    comments -- "without a baseline this objective ranks build another report
    forever", "parity work must not outrank correctness work by default" -- and
    the field carries principles.md's top ranking rule.

    None of these checks that a label is RIGHT. That is the judgement the field
    exists to hold and no check can make it. They check that more than one
    objective was weighed in writing.
    """

    def test_a_block_with_no_objectives_considered_is_refused(self, tmp_path):
        code, out = run(tmp_path, block(objectives_considered=None))
        assert code == 1 and "objectives_considered" in out

    def test_a_token_sentence_is_refused(self, tmp_path):
        code, out = run(tmp_path, block(objectives_considered="parity, obviously"))
        assert code == 1 and "objectives_considered" in out

    def test_naming_one_objective_is_not_weighing(self, tmp_path):
        code, out = run(tmp_path, block(objectives_considered=(
            "Every row here serves dd-feature-parity, which is what the gap "
            "list is about, and there is nothing further worth saying about "
            "the matter at all beyond that simple observation.")))
        assert code == 1 and "Weighing one objective is not weighing" in out

    def test_naming_an_objective_that_does_not_exist_does_not_count(self, tmp_path):
        code, out = run(tmp_path, block(objectives_considered=(
            "Weighed dd-feature-parity against dd-correctness, which is the "
            "one about numbers being right, and parity won for all of these "
            "rows because none of them reports a wrong figure today.")))
        assert code == 1 and "Weighing one objective is not weighing" in out

    def test_a_substring_of_an_id_does_not_count_as_naming_it(self, tmp_path):
        # "dd-feature-parity-ish" is not dd-feature-parity, and a bare
        # `in` test would have said it was.
        code, out = run(tmp_path, block(objectives_considered=(
            "Weighed dd-feature-parity-ish reasoning against nothing else in "
            "particular here, which is a sentence long enough to clear the "
            "word floor while naming no real objective at all.")))
        assert code == 1 and "Weighing one objective is not weighing" in out

    def test_two_real_objectives_weighed_is_accepted(self, tmp_path):
        code, out = run(tmp_path, block())
        assert code == 0, out

    def test_the_objective_spread_is_printed_even_when_it_passes(self, tmp_path):
        code, out = run(tmp_path, block([candidate(title="a"),
                                         candidate(title="b")]))
        assert code == 0, out
        assert "objectives: dd-feature-parity=2" in out
        assert "EVERY ROW" in out

    def test_a_mixed_batch_is_not_flagged_as_flat(self, tmp_path):
        code, out = run(tmp_path, block([
            candidate(title="a", objective_ref="dd-feature-parity"),
            candidate(title="b", objective_ref="dd-trustworthy")]))
        assert code == 0, out
        assert "EVERY ROW" not in out


# ---- the ceiling lives in the contract ------------------------------------

class TestTheCeiling:

    def test_over_the_cap_is_refused(self, tmp_path):
        many = [candidate(title=f"thing {i}") for i in range(11)]
        code, out = run(tmp_path, block(many), max_candidates=10)
        assert code == 1 and "ceiling of 10" in out

    def test_at_the_cap_is_accepted(self, tmp_path):
        many = [candidate(title=f"thing {i}") for i in range(10)]
        code, out = run(tmp_path, block(many), max_candidates=10)
        assert code == 0, out

    def test_the_cap_comes_from_the_argument_not_the_check(self, tmp_path):
        many = [candidate(title=f"thing {i}") for i in range(4)]
        assert run(tmp_path, block(many), max_candidates=3)[0] == 1
        assert run(tmp_path, block(many), max_candidates=4)[0] == 0

    def test_duplicate_titles_are_refused(self, tmp_path):
        code, out = run(tmp_path, block([candidate(), candidate()]))
        assert code == 1 and "duplicate titles" in out


# ---- the document itself ---------------------------------------------------

class TestTheDocument:

    def test_no_block_at_all(self, tmp_path):
        code, out = run(tmp_path, None, body=PROSE)
        assert code == 1 and "0 ```fleet-candidates blocks" in out

    def test_two_blocks(self, tmp_path):
        body = (PROSE + "\n```fleet-candidates\n" + yaml.safe_dump(block())
                + "```\n\n```fleet-candidates\n" + yaml.safe_dump(block()) + "```\n")
        code, out = run(tmp_path, None, body=body)
        assert code == 1 and "2 ```fleet-candidates blocks" in out

    def test_two_markdown_files_is_two_batches(self, tmp_path):
        (tmp_path / "other.md").write_text("# other\n")
        code, out = run(tmp_path, block(), files="candidates.md other.md")
        assert code == 1 and "One document, one batch" in out

    def test_a_source_document_that_does_not_exist(self, tmp_path):
        code, out = run(tmp_path, block(
            source={"document": "specs/nope.md", "sha": GAP_SHA}))
        assert code == 1 and "does not exist" in out

    def test_the_block_must_name_the_sha_it_read_the_document_at(self, tmp_path):
        code, out = run(tmp_path, block(
            source={"document": "specs/metorik-gap.md"}))
        assert code == 1 and "sha it was read at" in out
