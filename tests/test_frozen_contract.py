"""A declared key must have a reader, and a contract key must reach the task.

THE CLASS THESE EXIST FOR, and it went wrong three times in ten days.

Something is declared -- in a `fleet-spec` block, or in a `contracts/*.yaml` --
and nothing reads it. No error, no warning, no row that looks different. The
writer believes the declaration and the system never made the promise:

  read_only_links   a contract key, missing from autoqueue's opt-in list.
  evidence_queries  the same, 15 Sep 2026: "an AUTOQUEUED task could never
                    carry them however the contract was written".
  self_check        the same, and never fixed until 17 Sep 2026.
    self_check_max  All 32 autoqueued draft_spec tasks since 8 Sep ran with
    paths_pack      the in-run gate off -- 0 of 37 runs ever recorded a
                    self-check -- and with a 4000-entry path list taken from a
                    46,193-file tree instead of the ~170 under the two roots
                    the contract narrows it to.
  auto_merge        a BLOCK key, read by neither parser, while the contract
                    file documents it as the way to ask for a human reviewer.
                    Task 125 was 1h20m from an unattended push believed held.

Adding each key to a list as it is discovered fixes the instance and leaves
the class. These assert the class: refuse the unknown, and carry everything
that is not argued out.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from console import autoqueue

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACTS = sorted((ROOT / "contracts").glob("*.yaml"))


def _block(**over) -> str:
    b = {"work_type": "dd_api", "repo": "deadly-digital-platform",
         "title": "a title", "writable_paths": ["api/analytics/routes/x.py"]}
    b.update(over)
    return "```fleet-spec\n" + yaml.safe_dump(b) + "```\n"


class TestTheBlockRefusesTheUnknown:
    def test_a_key_nothing_reads_is_refused(self):
        with pytest.raises(autoqueue.QueueRefused) as e:
            autoqueue.spec_blocks(_block(auto_merge_please=False))
        assert "auto_merge_please" in str(e.value)
        assert "nothing reads" in str(e.value)

    def test_the_refusal_lists_what_a_block_may_carry(self):
        with pytest.raises(autoqueue.QueueRefused) as e:
            autoqueue.spec_blocks(_block(nonsense=1))
        for k in autoqueue.BLOCK_KEYS:
            assert k in str(e.value)

    def test_every_known_key_is_accepted(self):
        got = autoqueue.spec_blocks(_block(contract="x.yaml", auto_merge=False,
                                           evidence_queries=[]))
        assert got[0]["auto_merge"] is False

    def test_every_block_key_has_a_stated_reader(self):
        """The dict is the schema AND the documentation. A key added with an
        empty reason is a key somebody meant to wire up and did not."""
        for k, why in autoqueue.BLOCK_KEYS.items():
            assert why and why.strip(), f"{k} is allowed with no reader named"

    def test_auto_merge_must_be_a_boolean(self):
        """`auto_merge: "false"` is a non-empty string. Under a truthiness
        test that reads as consent, which is the direction that ships."""
        with pytest.raises(autoqueue.QueueRefused) as e:
            autoqueue.spec_blocks(_block(auto_merge="false"))
        assert "not a boolean" in str(e.value)

    def test_the_required_keys_are_all_known_keys(self):
        assert set(autoqueue.REQUIRED) <= set(autoqueue.BLOCK_KEYS)

    def test_the_cli_refuses_the_same_block(self):
        """TWO parsers read a block, and the more permissive one is the hole.
        `fleet task add` read exactly one key and ignored the rest; it now
        shares this definition, so a spec cannot mean one thing to the chain
        and another to a person."""
        import importlib.util
        from importlib.machinery import SourceFileLoader
        spec = importlib.util.spec_from_loader(
            "fleetcli", SourceFileLoader("fleetcli", str(ROOT / "fleet")))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with pytest.raises(cli.SpecBlockRefused):
            cli._spec_block(_block(auto_merge_please=False))
        # and it is still lenient about a spec with no block at all
        assert cli._spec_block("# just prose\n") is None


class TestTheFrozenContractCarriesEverything:
    def test_every_key_every_contract_declares_is_carried_or_excluded(self):
        """THE CLASS ASSERTION. Not "these keys are copied" -- a rule written
        against the keys that happen to exist today refuses the next contract
        for being different, and worse, says nothing when one is dropped."""
        unaccounted = {}
        for path in CONTRACTS:
            declared = set(yaml.safe_load(path.read_text()) or {})
            missing = declared - set(autoqueue.EXCLUDED_FROM_FROZEN)
            # Everything not excluded is carried by construction -- `frozen`
            # is a copy of contract.items() minus the exclusions. So this can
            # only fail if that inversion is undone.
            for k in sorted(missing):
                if k not in _carried_keys():
                    unaccounted.setdefault(path.name, []).append(k)
        assert not unaccounted, (
            f"declared, not carried, not excluded: {unaccounted}. Add a reader "
            f"and let it flow, or argue it into EXCLUDED_FROM_FROZEN.")

    def test_the_freeze_is_a_copy_minus_exclusions_not_an_opt_in_list(self):
        """The inversion IS the fix. An opt-in list drifts from the schema
        silently and in the permissive direction, three times in ten days."""
        src = (ROOT / "console" / "autoqueue.py").read_text()
        assert "if k not in EXCLUDED_FROM_FROZEN" in src, (
            "the frozen contract is no longer a copy-minus-exclusions")
        assert 'for opt in ("creatable_paths"' not in src, (
            "the opt-in list is back; that is the defect this replaced")

    def test_every_exclusion_states_why(self):
        for k, why in autoqueue.EXCLUDED_FROM_FROZEN.items():
            assert why and why.strip(), f"{k} is excluded with no reason given"

    def test_the_column_exclusions_really_are_columns(self, dsns, console):
        """Four of the five are excluded because a task COLUMN already holds
        them. If that stops being true the exclusion is just a drop again."""
        cols = {r["column_name"] for r in console.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'tasks'").fetchall()}
        for k in ("repo", "base_branch", "max_cost_gbp", "timeout_seconds"):
            assert k in autoqueue.EXCLUDED_FROM_FROZEN
            assert k in cols, f"{k} is excluded as a column and is not one"

    def test_max_requirements_is_consumed_at_queue_time(self):
        """The fifth. It gates the queue and nothing downstream asks again."""
        src = (ROOT / "console" / "autoqueue.py").read_text()
        assert 'contract.get("max_requirements")' in src

    def test_the_keys_that_were_silently_dropped_now_flow(self):
        """The three that were live on 17 Sep 2026, named so a regression is
        reported as itself rather than as a mysteriously weaker draft."""
        draft = yaml.safe_load((ROOT / "contracts" / "draft-spec.yaml").read_text())
        for k in ("self_check", "self_check_max", "paths_pack"):
            assert draft.get(k) is not None, f"draft-spec.yaml stopped declaring {k}"
            assert k not in autoqueue.EXCLUDED_FROM_FROZEN
            assert k in _carried_keys()


def _carried_keys() -> set[str]:
    """Every key any shipped contract declares that is not excluded.

    Derived from the contracts themselves rather than typed, for the reason
    tests/conftest.py gives: a fixture more permissive than production is not
    a fixture, and a list of key names is exactly the thing that drifted.
    """
    declared: set[str] = set()
    for path in CONTRACTS:
        declared |= set(yaml.safe_load(path.read_text()) or {})
    return declared - set(autoqueue.EXCLUDED_FROM_FROZEN)


class TestBothFreezeSitesObeyTheSameRule:
    """TWO places freeze a contract onto a task, and they forgot different
    keys. `console.autoqueue` (code tasks, from an accepted draft) carried
    `agent_tools` and dropped `self_check`; `console.approve` (the draft_spec
    task itself) dropped both. Two hand-maintained lists are two lists to
    forget."""

    def test_the_draft_spec_contract_carries_everything_declared(self):
        from console import approve
        declared = yaml.safe_load(
            (ROOT / "contracts" / "draft-spec.yaml").read_text()) or {}
        contract, _cost, _timeout, _base = approve._draft_spec_contract()
        for k in sorted(set(declared) - set(autoqueue.EXCLUDED_FROM_FROZEN)):
            assert k in contract, (
                f"draft-spec.yaml declares {k} and the frozen contract drops "
                f"it. Every draft_spec task on this host is built from this "
                f"dict.")

    def test_the_column_exclusions_are_absent_and_returned_separately(self):
        from console import approve
        contract, cost, timeout, base = approve._draft_spec_contract()
        for k in ("repo", "base_branch", "max_cost_gbp", "timeout_seconds"):
            assert k not in contract
        assert cost and timeout and base

    def test_the_gate_the_contract_declares_actually_reaches_the_agent(self):
        """The three that were dropped together, asserted as the capability
        rather than as key names: an agent cannot self-check without the
        environment AND the tool, and it had neither for 32 tasks."""
        from console import approve
        from runner import packs
        contract, *_ = approve._draft_spec_contract()
        env = packs.selfcheck_env(contract)
        assert env.get("FLEET_SELFCHECK_COMMAND"), (
            "self_check is declared and selfcheck_env still returns nothing")
        assert env["FLEET_SELFCHECK_MAX"] == "3"
        assert any("spec_selfcheck.sh" in t for t in contract["agent_tools"]), (
            "the agent cannot run the check it is being handed an env for")

    def test_neither_site_keeps_its_own_opt_in_list(self):
        for mod in ("autoqueue.py", "approve.py"):
            src = (ROOT / "console" / mod).read_text()
            assert "EXCLUDED_FROM_FROZEN" in src, f"{mod} does not use the rule"
            assert 'for opt in (' not in src, (
                f"{mod} has an opt-in list again; that is the defect this "
                f"replaced, and it went wrong three times in ten days")
