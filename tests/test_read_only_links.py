"""A reference link is read, never written, and the probe stops asserting it.

12 Sep 2026. Accepting task 71 refused with

    /tmp/.../fleet-accept-trial-71/reference/deadly-digital-platform is not
    writable (Read-only file system)

and every part of that was working: the console has ProtectHome=read-only and
no ReadWritePaths, deliberately, since the merge moved into a throwaway clone
on 11 Sep. What was wrong is that anything asked.

THE MIRROR IMAGE OF THE CASE THE PROBE EXISTS FOR. vitest made a real write
into a real dependency tree, exited 1, and was indistinguishable from a failing
test -- so verify.unwritable was added to ask the filesystem first. Here there
is no write to predict, and the check that predicts writes was making the only
one. These tests pin the distinction in both directions: a dependency tree is
still probed, a declared reference is not.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from runner import config, verify, worktree


@pytest.fixture
def tree(tmp_path):
    """A worktree with two links: one written through, one read."""
    wt = tmp_path / "wt"
    (wt / "reference").mkdir(parents=True)
    (wt / "platform").mkdir()
    source = tmp_path / "checkout"
    (source / ".git").mkdir(parents=True)
    (source / "node_modules").mkdir()
    (wt / "reference" / "deadly-digital-platform").symlink_to(source)
    (wt / "platform" / "node_modules").symlink_to(source / "node_modules")
    return wt, source


CONTRACT = {
    "worktree_links": {
        "reference/deadly-digital-platform": "/does/not/matter",
        "platform/node_modules": "/does/not/matter/either",
    },
    "read_only_links": ["reference/deadly-digital-platform"],
}


class TestWhichLinksAreProbed:

    def test_a_declared_reference_is_left_out(self, tree):
        wt, _ = tree
        probed = worktree.writable_links(wt, CONTRACT)
        assert (wt / "platform/node_modules").resolve() in probed
        assert (wt / "reference/deadly-digital-platform").resolve() not in probed

    def test_the_default_is_to_probe(self, tree):
        """The direction of the error is chosen. A link a contract forgot to
        declare gives a loud could_not_run naming the path; a link wrongly
        assumed unwritten gives a tool dying on EROFS reported as the branch
        failing, which is the defect the probe was built after."""
        wt, _ = tree
        undeclared = {"worktree_links": CONTRACT["worktree_links"]}
        probed = worktree.writable_links(wt, undeclared)
        assert len(probed) == 2

    def test_a_contract_with_no_links_probes_nothing(self, tree):
        wt, _ = tree
        assert worktree.writable_links(wt, {}) == []


class TestTheProbeItself:
    """unwritable is unchanged and still does the thing rather than asking
    os.access: a directory can be writable by mode and unwritable because the
    mount is read-only."""

    def test_it_still_names_a_tree_it_cannot_write(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        locked = tmp_path / "locked"
        locked.mkdir()
        os.chmod(locked, 0o555)
        try:
            problems = verify.unwritable(wt, [locked])
            assert len(problems) == 1
            assert str(locked) in problems[0]
            assert "looks like the branch failing" in problems[0]
        finally:
            os.chmod(locked, 0o755)

    def test_it_leaves_no_probe_behind(self, tmp_path):
        """The probe writes into whatever it is pointed at, which for the
        runner has been the live production checkout on every draft-spec
        verification -- ReadWritePaths lets it succeed and cycle.py excludes
        the whole checkout from the drift guard, so nothing saw it. It is
        transient, and this is what 'transient' has to mean."""
        wt = tmp_path / "wt"
        wt.mkdir()
        before = set(wt.iterdir())
        assert verify.unwritable(wt, []) == []
        assert set(wt.iterdir()) == before

    def test_a_path_that_is_not_a_directory_is_skipped(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        assert verify.unwritable(wt, [tmp_path / "gone"]) == []


class TestTheDeclarationIsValidated:
    """A typo names nothing, the opt-out silently does not apply, and the
    contract is back to refusing an accept for a write nobody makes -- with a
    file that says it should not."""

    def _write(self, tmp_path, contract):
        p = tmp_path / "c.yaml"
        p.write_text(yaml.safe_dump(contract))
        return p

    def test_a_read_only_link_that_is_not_a_link_is_refused(self, tmp_path):
        base = yaml.safe_load(Path("contracts/draft-spec.yaml").read_text())
        base["read_only_links"] = ["reference/typo"]
        with pytest.raises(RuntimeError, match="read_only_links"):
            config.load_contract(base["repo"], self._write(tmp_path, base))

    def test_the_real_contract_declares_a_link_that_exists(self):
        base = yaml.safe_load(Path("contracts/draft-spec.yaml").read_text())
        assert base["read_only_links"] == ["reference/deadly-digital-platform"]
        assert set(base["read_only_links"]) <= set(base["worktree_links"])

    def test_every_shipped_contract_still_loads(self):
        for path in sorted(Path("contracts").glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            config.load_contract(data["repo"], path)

    def test_node_modules_is_never_declared_read_only(self):
        """The tree tools DO write into. Declaring it read-only would re-open
        the vitest failure with a line of yaml."""
        for path in sorted(Path("contracts").glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            for target in data.get("read_only_links") or []:
                assert not target.endswith("node_modules"), (
                    f"{path.name} declares {target} read-only, and tools write "
                    f"caches into node_modules -- that is task 53's EROFS")


class TestItSurvivesBeingFrozen:
    """The opt-out travels with the link or it does not apply to a queued task,
    which is 9.4's flattened objective_ref by another route."""

    def test_approve_carries_it(self):
        import inspect

        from console import approve
        src = inspect.getsource(approve._draft_spec_contract)
        assert "read_only_links" in src
        assert "worktree_links" in src

    def test_autoqueue_carries_it(self):
        import inspect

        from console import autoqueue
        src = inspect.getsource(autoqueue)
        assert "read_only_links" in src
