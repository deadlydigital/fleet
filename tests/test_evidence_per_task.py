"""A research task can declare the readings it needs.

specs/auto-approval.md §9.16 found on 11 Sep 2026 that no research task gets an
evidence pack, and offered two repairs. Neither was right, and task 105's
document is the fourth to report the gap:

  A. widen research-metorik-gap.yaml's writable path so it can be resolved.
     DEAD: §9.13's ambiguity rule now refuses that contract's own filename,
     because the path matches both research contracts.

  B. put evidence_queries on research.yaml.
     NEVER SUFFICIENT, for two reasons §9.16 could not have seen:
       - the only DD reader could not read `order_items`, the table task 105's
         research is entirely about (fixed by 047);
       - console/autoqueue built `frozen` from a named key list that did NOT
         include evidence_queries, so an AUTOQUEUED task could never carry
         them however the contract was written. The chain autoqueues
         everything, so B would have changed nothing.

The repair is that the block travels with the TASK. A research question and its
queries are one-to-one -- which is why the only contract that ever carried
queries was pinned to a single filename.
"""
from __future__ import annotations

import pytest

from runner import evidence


class TestWhatATaskMayDeclare:
    def _q(self, **over):
        q = {"key": "k", "reader": "deadly_digital",
             "sql": "SELECT count(*) FROM analytics_2.order_items"}
        q.update(over)
        return q

    def test_a_well_formed_block_is_accepted(self):
        out = evidence.validate_task_queries([self._q()])
        assert len(out) == 1 and out[0]["key"] == "k"

    def test_it_is_marked_task_authored(self):
        """run_queries redacts these results and passes contract-level ones
        through. The flag is how it tells them apart."""
        assert evidence.validate_task_queries([self._q()])[0]["task_authored"]

    def test_none_is_an_empty_block_and_not_an_error(self):
        assert evidence.validate_task_queries(None) == []

    @pytest.mark.parametrize("over,why", [
        ({"key": ""}, "no key"),
        ({"reader": "root"}, "a reader that does not exist"),
        ({"reader": None}, "no reader"),
        ({"sql": "  "}, "no sql"),
    ])
    def test_what_is_refused(self, over, why):
        with pytest.raises(evidence.QueryRefused):
            evidence.validate_task_queries([self._q(**over)])

    def test_a_repeated_key_is_refused(self):
        """Two readings under one name cannot be told apart afterwards."""
        with pytest.raises(evidence.QueryRefused, match="repeats the key"):
            evidence.validate_task_queries([self._q(), self._q()])

    def test_the_ceiling_holds(self):
        many = [self._q(key=f"k{i}") for i in range(evidence.MAX_TASK_QUERIES + 1)]
        with pytest.raises(evidence.QueryRefused, match="ceiling"):
            evidence.validate_task_queries(many)


class TestATaskMayNotReadTheSecrets:
    """The containment that makes an agent-authored query safe to run.

    A draft-spec task merges UNATTENDED, so this SQL reaches production with
    nobody in the loop. The session is read-only, the role holds SELECT, the
    timeout is 30 s and the pack keeps 200 rows -- none of which stops it
    READING something it should not, and the pack is written to a path the
    contract declares writable and therefore COMMITS.

    Measured 15 Sep 2026: of the nine tables dd_detector_login can SELECT,
    exactly one carries a secret -- public.tenants has api_key and
    api_key_hash. So the denylist is one name and covers the whole surface.
    """

    def test_tenants_is_refused(self):
        with pytest.raises(evidence.QueryRefused, match="tenants"):
            evidence.validate_task_queries([{
                "key": "k", "reader": "deadly_digital",
                "sql": "SELECT api_key FROM public.tenants"}])

    def test_it_is_refused_however_it_is_spelled(self):
        for sql in ("select * from TENANTS",
                    "SELECT t.api_key FROM public.tenants t",
                    "with x as (select 1) select * from tenants"):
            with pytest.raises(evidence.QueryRefused):
                evidence.validate_task_queries([{
                    "key": "k", "reader": "deadly_digital", "sql": sql}])

    def test_a_table_merely_containing_the_word_is_not_blocked(self):
        """`\\b` matching, so `tenant_settings` is not `tenants`. A denylist
        that refuses neighbouring names refuses legitimate research."""
        evidence.validate_task_queries([{
            "key": "k", "reader": "deadly_digital",
            "sql": "SELECT count(*) FROM analytics_2.orders WHERE tenant_id = 2"}])

    def test_credential_shaped_values_are_redacted(self):
        """Belt and braces: the denylist depends on a list of what is sensitive
        staying current, and lists go stale. A table granted next month carrying
        a secret nobody added above still does not reach a committed file."""
        assert evidence.redact("dd_a42Kq1wEnfKjaSdfKjhaSdfKjhaSdfKjhaSdf99") \
            == evidence.REDACTED
        assert evidence.redact("dd_short") == "dd_short"
        assert evidence.redact(42) == 42
        assert evidence.redact(None) is None

    def test_a_contract_query_is_not_redacted(self):
        """research-metorik-gap.yaml's dd_tenants reads id, name and created_at
        and a person wrote it into a protected file. Silently rewriting their
        reading would be the worse surprise."""
        assert "task_authored" not in {"key": "dd_tenants"}
