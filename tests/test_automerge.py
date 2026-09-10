"""What may merge with nobody watching.

specs/unattended-operation.md §6.1. The failure mode of an eligibility rule is
to be accidentally PERMISSIVE, so most of these assert a refusal, and the one
that asserts a pass names every condition it rested on.
"""
from __future__ import annotations

from types import SimpleNamespace

from console import automerge
from tests.support import PLATFORM_FLOOR

BITE_OK = {"command": "/home/ubuntu/fleet/contracts/checks/new_test_bites.sh api",
           "exit_code": 0, "duration_ms": 61000}


def _contract(**over) -> dict:
    c = {"work_type": "dd_api", "repo": "deadly-digital-platform",
         "writable_paths": ["api/analytics/routes/orders.py"],
         "protected_paths": list(PLATFORM_FLOOR),
         "creatable_paths": ["api/tests/analytics/test_fleet_*.py"],
         "verification": ["true"], "max_diff_lines": 400}
    c.update(over)
    return c


def _task(**over) -> dict:
    t = {"id": 99, "repo": "deadly-digital-platform",
         "acceptance_contract": _contract()}
    t.update(over)
    return t


def _rv(**over):
    d = {"ok": True, "could_not_run": False, "skipped_reason": "",
         "checks": [BITE_OK], "merged_sha": "a" * 40, "base_sha": "b" * 40}
    d.update(over)
    return SimpleNamespace(**d)


# ---- the one that passes --------------------------------------------------

def test_an_ordinary_dd_api_task_is_eligible_by_default():
    """No flag needed. The default is scoped to the parity push — see the
    module docstring and specs/unattended-operation.md §7."""
    v = automerge.eligible(_task(), _rv())
    assert v.ok, v.reason
    assert v.gates["test_bit"] is True
    assert v.gates["reviewed_by_a_person"] is False
    assert v.gates["merged_sha"] == "a" * 40


# ---- the hard rule --------------------------------------------------------

#: The REAL draft-spec contract shape, not `_contract(work_type="draft_spec")`.
#:
#: The first version of this test used the fixture default and passed while
#: the real path could not have got past gate 3: `_contract()` carries
#: `creatable_paths` and `_rv()` carries a passing bite check, and
#: contracts/draft-spec.yaml has neither and never will. A test whose fixture
#: is more permissive than production is a test that cannot fail for the
#: reason it exists.
def _draft_contract(**over) -> dict:
    c = {"work_type": "draft_spec", "repo": "fleet",
         "writable_paths": ["drafts/**"],
         "protected_paths": ["specs/**", "console/**"],
         "verification": ["/home/ubuntu/fleet/contracts/checks/"
                          "draft_spec_shape.py"],
         "max_diff_lines": 400}
    c.update(over)
    return c


#: What re-verification looks like for a document: one check, its own shape
#: check, and no bite check anywhere.
def _draft_rv(**over):
    d = {"ok": True, "could_not_run": False, "skipped_reason": "",
         "checks": [{"command": "/home/ubuntu/fleet/contracts/checks/"
                                "draft_spec_shape.py",
                     "exit_code": 0, "duration_ms": 900}],
         "merged_sha": "a" * 40, "base_sha": "b" * 40}
    d.update(over)
    return SimpleNamespace(**d)


def test_a_real_draft_spec_merges_unattended_since_the_gate_was_removed():
    """The gate is gone, deliberately, and nothing replaces it.

    This asserted the opposite until 10 Sep 2026, when `draft_spec` came off
    NEVER_UNATTENDED. Inverted rather than deleted so the removal is a thing
    the suite states, not a rule that quietly stopped being tested. What it
    costs is in console/automerge.py's docstring and in
    specs/auto-approval.md §9.9: nothing reads a spec at any point now.
    """
    v = automerge.eligible(_task(acceptance_contract=_draft_contract()),
                           _draft_rv())
    assert v.ok, v.reason


def test_a_merged_document_does_not_claim_a_test_bit():
    """False, not absent and not True. A later reader needs to know that no
    test bit here because there was nothing for one to bite on."""
    v = automerge.eligible(_task(acceptance_contract=_draft_contract()),
                           _draft_rv())
    assert v.gates["test_bit"] is False
    assert v.gates["document"] is True


def test_a_document_still_has_to_pass_its_own_check():
    """Skipping the added-test gate must not skip re-verification. If
    draft_spec_shape.py fails, the draft does not merge."""
    for rv in (_draft_rv(ok=False, reason="shape check failed"),
               _draft_rv(could_not_run=True),
               _draft_rv(skipped_reason="no trial clone"),
               None):
        v = automerge.eligible(_task(acceptance_contract=_draft_contract()),
                               rv)
        assert not v.ok

def test_a_code_task_does_not_get_the_document_exemption():
    """The exemption is keyed on work_type and must not leak. A dd_api task
    with no creatable_paths is still refused."""
    v = automerge.eligible(
        _task(acceptance_contract=_contract(creatable_paths=[])), _rv())
    assert not v.ok
    assert "no new test file" in v.reason


def test_a_draft_spec_still_honours_auto_merge_false():
    """The hard rule went; the opt-out did not. A contract can still hold one
    back, which is the only remaining way to put a person in front of a spec."""
    v = automerge.eligible(
        _task(acceptance_contract=_contract(work_type="draft_spec",
                                            auto_merge=False)), _rv())
    assert not v.ok


def test_research_is_still_never_eligible():
    """Only draft_spec came off the tuple. The narrowness is the point."""
    for wt in ("research", "candidate_producer", "dd_infra"):
        v = automerge.eligible(
            _task(acceptance_contract=_contract(work_type=wt,
                                                auto_merge=True)), _rv())
        assert not v.ok, wt
        assert "exists to be read" in v.reason or "never merges" in v.reason


def test_research_never_merges_unattended():
    v = automerge.eligible(
        _task(acceptance_contract=_contract(work_type="research")), _rv())
    assert not v.ok


# ---- the opt-out ----------------------------------------------------------

def test_auto_merge_false_sends_it_to_a_person():
    v = automerge.eligible(
        _task(acceptance_contract=_contract(auto_merge=False)), _rv())
    assert not v.ok
    assert "for a person to look at" in v.reason


def test_auto_merge_true_is_accepted_but_is_not_what_makes_it_eligible():
    """Explicit true and absent must behave the same, or the default is a lie."""
    a = automerge.eligible(_task(acceptance_contract=_contract(auto_merge=True)), _rv())
    b = automerge.eligible(_task(), _rv())
    assert a.ok and b.ok


# ---- evidence that the NEW behaviour works --------------------------------

def test_no_reverification_is_refused():
    assert not automerge.eligible(_task(), None).ok


def test_a_skipped_reverification_is_refused():
    v = automerge.eligible(_task(), _rv(skipped_reason="the contract declares none"))
    assert not v.ok
    assert "nothing was checked" in v.reason


def test_could_not_run_is_refused_and_not_treated_as_a_pass():
    v = automerge.eligible(_task(), _rv(ok=False, could_not_run=True))
    assert not v.ok
    assert "not the same as passing" in v.reason


def test_a_failed_reverification_is_refused():
    assert not automerge.eligible(_task(), _rv(ok=False)).ok


def test_a_contract_with_no_creatable_paths_is_refused():
    """No new test could have been added, so a green suite shows only that
    nothing broke."""
    v = automerge.eligible(
        _task(acceptance_contract=_contract(creatable_paths=[])), _rv())
    assert not v.ok
    assert "could not have added one" in v.reason


def test_a_missing_bite_check_is_refused():
    v = automerge.eligible(_task(), _rv(checks=[
        {"command": "pytest_unit_per_file.sh api tests/analytics",
         "exit_code": 0}]))
    assert not v.ok
    assert "did not run" in v.reason


def test_a_test_that_did_not_bite_is_refused():
    """The whole point. It passes against the tree BEFORE the change."""
    v = automerge.eligible(_task(), _rv(checks=[dict(BITE_OK, exit_code=1)]))
    assert not v.ok
    assert "did not bite" in v.reason


# ---- the shape of the rule itself -----------------------------------------

def test_every_refusal_says_why_in_a_sentence():
    """These reach the brief and the console. A code is not a reason."""
    cases = [
        (_task(acceptance_contract=_contract(work_type="research")), _rv()),
        (_task(acceptance_contract=_contract(auto_merge=False)), _rv()),
        (_task(), None),
        (_task(), _rv(ok=False)),
        (_task(acceptance_contract=_contract(creatable_paths=[])), _rv()),
        (_task(), _rv(checks=[dict(BITE_OK, exit_code=1)])),
    ]
    for task, rv in cases:
        v = automerge.eligible(task, rv)
        assert not v.ok
        assert len(v.reason.split()) >= 6, f"terse refusal: {v.reason!r}"


def test_an_ineligible_task_carries_no_gates():
    """Gates are the record of a decision that was made. A refusal made none."""
    v = automerge.eligible(_task(acceptance_contract=_contract(auto_merge=False)),
                           _rv())
    assert v.gates == {}
