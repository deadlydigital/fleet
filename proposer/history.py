"""The layer's own past output.

Not track 1, and not part of the detectors adapter: this is the proposal
layer reading what it has already said, so that a daily cycle does not spend
its five slots repeating yesterday's five. Read through the same read-only
role, which holds SELECT on proposals and not on decisions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from .adapter import AdapterOutput, Reading, load_query

ADAPTER = "proposals"

PROPOSAL_ACTIVITY = "proposal_activity"
PROPOSAL_HISTORY = "proposal_history"
PROPOSAL_EPOCH = "proposal_epoch"


class ProposalHistory:
    """Everything the cycle needs to know about its own record."""

    name = ADAPTER

    def __init__(self, fetched_at: datetime, rows: dict[str, tuple[dict[str, Any], ...]]):
        self.fetched_at = fetched_at
        self._rows = rows

    @classmethod
    def read(cls, conn: psycopg.Connection) -> "ProposalHistory":
        fetched_at = conn.execute("SELECT now() AS t").fetchone()["t"]
        rows = {}
        for key in (PROPOSAL_ACTIVITY, PROPOSAL_HISTORY, PROPOSAL_EPOCH):
            result = conn.execute(load_query(key).sql).fetchall()
            rows[key] = tuple(dict(r) for r in result)
        return cls(fetched_at, rows)

    # ---- questions --------------------------------------------------------

    @property
    def first_proposal_at(self) -> datetime | None:
        row = self._rows[PROPOSAL_EPOCH][0] if self._rows[PROPOSAL_EPOCH] else None
        return row["first_proposal_at"] if row else None

    @property
    def total_proposals(self) -> int:
        row = self._rows[PROPOSAL_EPOCH][0] if self._rows[PROPOSAL_EPOCH] else None
        return int(row["total_proposals"]) if row else 0

    def last_proposed(self, finding_key: str) -> datetime | None:
        for row in self._rows[PROPOSAL_HISTORY]:
            if row["finding_key"] == finding_key:
                return row["last_proposed_at"]
        return None

    def last_activity_on(self, objective_ref: str) -> datetime | None:
        for row in self._rows[PROPOSAL_ACTIVITY]:
            if row["objective_ref"] == objective_ref:
                return row["last_proposed_at"]
        return None

    def activity_row(self, objective_ref: str) -> dict[str, Any] | None:
        for row in self._rows[PROPOSAL_ACTIVITY]:
            if row["objective_ref"] == objective_ref:
                return row
        return None

    def reading(self, key: str, bound, fetched_at: datetime | None = None) -> Reading:
        """A history read wrapped as a reading, so it can become evidence.

        Current by construction: these are this layer's own timestamps and
        cannot go out of date relative to themselves.
        """
        return Reading(adapter=self.name, query_key=key, query_version=1,
                       rows=self._rows[key], fetched_at=fetched_at or self.fetched_at,
                       freshness_bound=bound, bound_source="cycle.yaml",
                       current_by_construction=True)
