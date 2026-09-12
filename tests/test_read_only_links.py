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
    """A worktree with the two link shapes that actually exist.

    Built by link_dependencies itself rather than by hand, because the whole
    distinction is in HOW each one is made: node_modules is FARMED into a real
    directory of symlinks inside the worktree, and a reference checkout is one
    plain symlink pointing out of it. A fixture that made both the same way
    would have modelled the thing the rule turns on out of existence -- which
    the first version of this file did.
    """
    wt = tmp_path / "wt"
    wt.mkdir()
    source = tmp_path / "checkout"
    (source / ".git").mkdir(parents=True)
    (source / "platform" / "node_modules" / "typescript").mkdir(parents=True)
    (source / "platform" / "node_modules" / ".vite").mkdir()
    worktree.link_dependencies(wt, {
        "reference/deadly-digital-platform": str(source),
        "platform/node_modules": str(source / "platform" / "node_modules"),
    })
    return wt, source


CONTRACT = {
    "worktree_links": {
        "reference/deadly-digital-platform": "/does/not/matter",
        "platform/node_modules": "/does/not/matter/either",
    },
    "read_only_links": ["reference/deadly-digital-platform"],
}


class TestTheStructuralRule:
    """A link that resolves OUTSIDE the worktree is never probed.

    Not a heuristic. Verification writes only inside the tree that gets thrown
    away, so a check needing to write through a link that points out of it is
    writing into a tree nobody deletes -- and the answer is to farm it, as
    node_modules was, not to make a production checkout writable.
    """

    def test_a_farmed_tree_is_inside_and_is_probed(self, tree):
        wt, _ = tree
        probed = worktree.writable_links(wt, {
            "worktree_links": {"platform/node_modules": "x"}})
        assert probed == [wt / "platform/node_modules"]
        assert worktree.inside(wt, wt / "platform/node_modules")

    def test_a_reference_symlink_is_outside_and_is_not(self, tree):
        wt, _ = tree
        assert worktree.writable_links(wt, {
            "worktree_links": {"reference/deadly-digital-platform": "x"}}) == []
        assert not worktree.inside(wt, wt / "reference/deadly-digital-platform")

    def test_it_needs_no_declaration_to_work(self, tree):
        """The point of making it structural. Task 71's frozen contract has
        worktree_links and read_only_links: null and always will -- the console
        freezes from the task row, and guard_task_immutability allows a change
        only while QUEUED. A rule derived from the filesystem reaches it."""
        wt, _ = tree
        undeclared = {"worktree_links": CONTRACT["worktree_links"]}
        assert worktree.writable_links(wt, undeclared) == [
            wt / "platform/node_modules"]

    def test_the_declaration_can_only_remove(self, tree):
        """read_only_links stays as documentation of intent. Both tests must
        pass, so declaring one wrongly loses a probe rather than gaining one."""
        wt, _ = tree
        both = dict(CONTRACT)
        both["read_only_links"] = list(CONTRACT["worktree_links"])
        assert worktree.writable_links(wt, both) == []

    def test_a_contract_with_no_links_probes_nothing(self, tree):
        wt, _ = tree
        assert worktree.writable_links(wt, {}) == []


class TestTheLinkPathDoesNotDependOnWhenItIsAsked:
    """The timing bug. `(worktree / target).resolve()` reads the filesystem, so
    it answers differently before and after the link is made -- which is why a
    refusal naming <trial>/reference/... all morning named
    /home/ubuntu/deadly-digital-platform in the afternoon, for the same probe
    writing to the same place."""

    def test_it_is_the_same_before_and_after_the_link_exists(self, tmp_path):
        wt = tmp_path / "wt"
        (wt / "reference").mkdir(parents=True)
        src = tmp_path / "src"
        src.mkdir()
        target = "reference/deadly-digital-platform"

        before = worktree.link_path(wt, target)
        (wt / target).symlink_to(src)
        after = worktree.link_path(wt, target)

        assert before == after == wt / target
        # And the expression it replaces does NOT have that property, so this
        # test would pass vacuously if link_path ever went back to resolve().
        assert (wt / target).resolve() == src.resolve() != before

    def test_it_names_where_the_link_lives_not_where_it_points(self, tree):
        wt, source = tree
        p = worktree.link_path(wt, "reference/deadly-digital-platform")
        assert p == wt / "reference/deadly-digital-platform"
        assert p != source

    def test_containment_still_follows_symlinks(self, tmp_path):
        """`inside` makes the opposite choice from link_path, deliberately. The
        agent runs BEFORE the links are made and could leave `reference` as a
        symlink to /etc; a lexical containment check would see a path under the
        worktree and mkdir(parents=True) would build the rest of it there."""
        wt = tmp_path / "wt"
        wt.mkdir()
        elsewhere = tmp_path / "etc"
        elsewhere.mkdir()
        (wt / "reference").symlink_to(elsewhere)
        assert not worktree.inside(wt, worktree.link_path(wt, "reference/sub/x"))

    def test_a_planted_symlink_is_refused_rather_than_followed(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        elsewhere = tmp_path / "etc"
        (elsewhere / "sub").mkdir(parents=True)
        (wt / "reference").symlink_to(elsewhere)
        src = tmp_path / "src"
        src.mkdir()
        with pytest.raises(worktree.GitError, match="outside the worktree"):
            worktree.link_dependencies(wt, {"reference/sub/x": str(src)})
        assert not (elsewhere / "sub" / "x").exists(), \
            "mkdir(parents=True) built into the planted tree"


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
