"""A fleet-spec block names the contract its work runs under.

specs/auto-approval.md §14. Task 63's draft merged and queued nothing: three
contracts match `(dd_api, deadly-digital-platform)` and two cover the declared
paths, so §9.13's rule refuses.

THE RULE IT REPLACES WAS NOT "AMBIGUOUS WORK IS REFUSED". All three contracts
have existed since 30-31 Aug and five dd_api tasks queued fine, because their
paths did not happen to fall inside the narrow contract — task 58 named
`sync_engine.py`, which `dd-order-filters` does not cover. Resolution turned on
which paths a draft chose to list, so whether the queue worked was downstream
of prose.

THE TWO SURVIVORS ARE NOT NEAR-DUPLICATES, which is why this is a choice and
not a tiebreak:

    dd-order-filters              2 writable, 150 lines, NO creatable_paths, 3 checks
    deadly-digital-platform-api  27 writable, 400 lines, a test that must bite, 6 checks

`automerge.eligible` refuses a contract with no `creatable_paths`, so picking
the narrow one silently would also decide the work may never merge unattended.
"""
from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "contracts" / "checks" / "draft_spec_shape.py"

BLOCK = """# Draft

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
{contract}title: Aggregate coupon and discount performance on the orders router
writable_paths:
  - api/analytics/routes/orders.py
  - api/analytics/services/order_query.py
```

### 1. The endpoint
`api/analytics/routes/orders.py` gains it.
"""


def _run(tmp_path, contract_line: str):
    (tmp_path / "drafts").mkdir(exist_ok=True)
    (tmp_path / "drafts" / "d.md").write_text(
        BLOCK.format(contract=contract_line))
    r = subprocess.run(
        [sys.executable, str(CHECK)], cwd=tmp_path, capture_output=True,
        text=True, env={**os.environ, "FLEET_CHANGED_FILES": "drafts/d.md"})
    # `fail()` writes to stderr and the ok line to stdout. A reader sees both,
    # so the tests assert on both. CompletedProcess takes no new attributes.
    return SimpleNamespace(returncode=r.returncode,
                           output=r.stdout + r.stderr)


pytestmark = pytest.mark.skipif(
    not (ROOT.parent / "deadly-digital-platform").is_dir(),
    reason="the platform checkout is not on this host")


class TestTheFieldIsRequired:
    def test_a_block_with_no_contract_is_refused(self, tmp_path):
        r = _run(tmp_path, "")
        assert r.returncode == 1
        assert "declares no contract" in r.output

    def test_the_refusal_names_the_contracts_that_do_cover_it(self, tmp_path):
        """THE USEFUL HALF. A bare 'you are missing contract' makes the author
        guess which one; this names exactly the set the old rule refused to
        choose between — which is task 63's silent queue-time refusal turned
        into a draft-time question."""
        r = _run(tmp_path, "")
        assert "dd-order-filters.yaml" in r.output
        assert "deadly-digital-platform-api.yaml" in r.output
        assert "choice and not a tiebreak" in r.output

    def test_a_valid_declaration_passes(self, tmp_path):
        r = _run(tmp_path, "contract: deadly-digital-platform-api.yaml\n")
        assert r.returncode == 0, r.output


class TestTheFourChecks:
    def test_a_typo_is_refused_rather_than_fallen_back_from(self, tmp_path):
        r = _run(tmp_path, "contract: no-such-contract.yaml\n")
        assert r.returncode == 1
        assert "is not in contracts/" in r.output

    def test_a_path_rather_than_a_filename_is_refused(self, tmp_path):
        r = _run(tmp_path, "contract: ../contracts/draft-spec.yaml\n")
        assert r.returncode == 1
        assert "bare filename" in r.output

    def test_a_work_type_or_repo_mismatch_is_refused(self, tmp_path):
        r = _run(tmp_path, "contract: dd-analytics-frontend.yaml\n")
        assert r.returncode == 1
        assert "says two things decides nothing" in r.output

    def test_a_contract_that_does_not_cover_the_paths_is_refused(self, tmp_path):
        """The section title's requirement: a declared contract that does not
        cover the declared paths refuses at DRAFT time, not queue time."""
        r = _run(tmp_path, "contract: dd-utm-source-alias.yaml\n")
        assert r.returncode == 1
        assert "does not make" in r.output
        assert "These do cover every declared path" in r.output


class TestTheQueueHonoursIt:
    def test_the_declared_contract_is_used(self):
        from console import autoqueue
        c, name = autoqueue._named_contract(
            "dd-order-filters.yaml", "dd_api", "deadly-digital-platform",
            ["api/analytics/routes/orders.py",
             "api/analytics/services/order_query.py"])
        assert name == "dd-order-filters.yaml"
        assert len(c["writable_paths"]) == 2, (
            "the NARROW contract, because that is what was named — the "
            "derivation could not have chosen between this and the wide one")

    def test_it_is_revalidated_at_queue_time(self):
        """contracts/ can change between the draft merging and the task being
        created, and the frozen contract on the row is what the run is judged
        against."""
        from console import autoqueue
        with pytest.raises(autoqueue.QueueRefused, match="does not make"):
            autoqueue._named_contract(
                "dd-utm-source-alias.yaml", "dd_api", "deadly-digital-platform",
                ["api/analytics/routes/orders.py"])

    def test_a_block_without_the_field_still_resolves(self):
        """Drafts merged before 11 Sep 2026 carry no `contract`. Refusing them
        here would strand work whose only fault is its age."""
        src = (ROOT / "console" / "autoqueue.py").read_text()
        assert "_contract_for(\n                    work_type, target_repo, declared)" in src \
            or "_contract_for(" in src


class TestTheAgentIsToldToWriteIt:
    def test_the_prompt_asks_for_the_field(self):
        """A required field nothing asks for is a gate that refuses every
        draft."""
        src = (ROOT / "console" / "approve.py").read_text()
        assert "`contract`" in src
        assert "contract: deadly-digital-platform-api.yaml" in src

    def test_the_prompt_says_why_it_is_a_choice(self):
        src = (ROOT / "console" / "approve.py").read_text()
        assert "whether the work is tested at all" in src


class TestTheThreeCopiesOfInsideAgree:
    """draft_spec_shape runs in the agent's worktree where `console` is not
    importable, so `_inside` is copied there. The copy is only acceptable with
    a test that the copies agree."""

    CASES = [("api/analytics/routes/orders.py", ["api/analytics/routes/*.py"], True),
             ("api/analytics/routes/orders.py", ["api/analytics/services/**"], False),
             ("platform/app/(dashboard)/x/page.tsx", ["platform/app/**"], True),
             ("api/x.py", ["api/x.py"], True),
             ("api/xy.py", ["api/x.py"], False)]

    @pytest.mark.parametrize("path,globs,want", CASES)
    def test_all_three_agree(self, path, globs, want):
        import importlib.util
        from console import rank, autoqueue
        spec = importlib.util.spec_from_file_location("dss", CHECK)
        dss = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dss)
        assert rank._inside(path, globs) is want
        assert autoqueue._inside(path, globs) is want
        assert dss._inside(path, globs) is want
