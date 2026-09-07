"""A claim, and the two ways it can exist.

Every claim is COMPUTED with a source and a recency, or UNCOMPUTED with a
reason. There is no third state and no way to build one -- `Claim.computed`
requires both fields positionally, and `Claim.uncomputed` refuses a value.

The database enforces the same rule (012_daily_brief.sql, sections 2), so this
module is the ergonomic half rather than the guarantee. Both exist because a
constraint catches the mistake and a constructor prevents it, and the second is
worth having when the first would only fire at the end of a long pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

CHANGED = "CHANGED"
LOOKS_WRONG = "LOOKS_WRONG"   # DELIBERATELY UNUSED — see `brief/render.py`
UNCOMPUTED = "UNCOMPUTED"


@dataclass(frozen=True)
class Claim:
    section: str
    metric_key: str
    statement: str
    status: str
    source: Optional[str] = None
    as_of: Optional[datetime] = None
    value_num: Optional[Decimal] = None
    value_text: Optional[str] = None
    previous_num: Optional[Decimal] = None
    delta_num: Optional[Decimal] = None
    query_key: Optional[str] = None
    query_version: Optional[int] = None
    uncomputed_reason: Optional[str] = None

    @staticmethod
    def computed(metric_key: str, statement: str, *, source: str,
                 as_of: datetime, value_num: Any = None,
                 value_text: Optional[str] = None,
                 query_key: Optional[str] = None,
                 query_version: Optional[int] = None) -> "Claim":
        """A claim the pass actually computed.

        `source` and `as_of` are keyword-REQUIRED rather than defaulted. A
        default here would be the whole failure: every claim would carry a
        plausible provenance nobody supplied.

        `as_of` is the instant the VALUE describes, not the instant it was read.
        A count taken at 03:00 from a table last written at 21:00 is as_of
        21:00, and passing `now()` would make a stale number look fresh.
        """
        if value_num is None and value_text is None:
            raise ValueError(
                f"{metric_key}: a computed claim needs a value; if there is "
                "none, it is UNCOMPUTED and should say why")
        return Claim(
            section=CHANGED, metric_key=metric_key, statement=statement,
            status="COMPUTED", source=source, as_of=as_of,
            value_num=None if value_num is None else Decimal(str(value_num)),
            value_text=value_text, query_key=query_key,
            query_version=query_version)

    @staticmethod
    def uncomputed(metric_key: str, statement: str, *, reason: str) -> "Claim":
        """Something the pass could not compute, named rather than dropped.

        There is no `value` parameter, and that is deliberate: "could not
        check, but here is a number anyway" is worse than either half.
        """
        if not reason or not reason.strip():
            raise ValueError(f"{metric_key}: an uncomputed claim must say why")
        return Claim(
            section=UNCOMPUTED, metric_key=metric_key, statement=statement,
            status="UNCOMPUTED", uncomputed_reason=reason)

    def with_previous(self, previous_num: Optional[Decimal]) -> "Claim":
        """Carry yesterday's value forward and compute the delta from it.

        The delta is arithmetic on the two STORED values, never a fresh read.
        Recomputing it from today's database would let a backfilled source
        silently restate history -- the same defect as a view that recomputes
        the evidence a decision cited.
        """
        if previous_num is None or self.value_num is None:
            return self
        prev = Decimal(str(previous_num))
        return Claim(**{**self.__dict__,
                        "previous_num": prev,
                        "delta_num": self.value_num - prev})
