"""Adapter plumbing: what a reading is, and when it stops being usable.

Every query an adapter runs declares a freshness bound before it runs, and
every reading carries the timestamp of the newest fact it rests on. A reading
older than its bound is returned marked, never returned quietly: silence
about age is how a dashboard keeps showing yesterday's number as today's.

The bound is a property of the question, not of the read. "How many issues
are open" is only as fresh as the last detector run, so its bound comes from
detector_registry geometry. "What is the false-positive rate" is only as
fresh as the last verdict a person entered, so its bound is a human cadence
and lives in cycle.yaml. A query about the run history itself -- when did
each detector last succeed -- is correct whenever it is asked, and says so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any, Mapping, Sequence

from . import config

FRESH = "FRESH"
STALE = "STALE"
NO_DATA = "NO_DATA"
CURRENT_BY_CONSTRUCTION = "CURRENT_BY_CONSTRUCTION"

_FILENAME_RE = re.compile(r"^(?P<key>[a-z0-9_]+)\.v(?P<version>\d+)\.sql$")


@dataclass(frozen=True)
class Query:
    key: str
    version: int
    sql: str


@lru_cache(maxsize=None)
def load_query(key: str, version: int = 1) -> Query:
    path = config.QUERY_DIR / f"{key}.v{version}.sql"
    if not path.exists():
        raise FileNotFoundError(f"no query file {path}")
    return Query(key=key, version=version, sql=path.read_text())


def jsonable(value: Any) -> Any:
    """A scalar a jsonb object can hold, or an error.

    Flat and scalar, on track 1's terms: nested objects are how free text
    gets in, and evidence is read by a person deciding something.
    """
    if value is None or isinstance(value, (bool, int, str, float)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (list, tuple)):
        return ",".join(str(jsonable(v)) for v in value)
    raise TypeError(f"{type(value).__name__} is not evidence-shaped")


def flatten(row: Mapping[str, Any], *, keys: Sequence[str] | None = None,
            **extra: Any) -> dict[str, Any]:
    chosen = keys if keys is not None else list(row)
    out = {k: jsonable(row[k]) for k in chosen if k in row}
    out.update({k: jsonable(v) for k, v in extra.items()})
    return out


@dataclass(frozen=True)
class Reading:
    """One adapter query's answer, with its age and the bound it was judged by."""

    adapter: str
    query_key: str
    query_version: int
    rows: tuple[dict[str, Any], ...]
    fetched_at: datetime
    freshness_bound: timedelta
    bound_source: str
    # Newest fact this answer rests on. None means the question has no
    # underlying history yet -- which is not the same as stale, and must not
    # be reported as if it were.
    data_as_of: datetime | None = None
    # A question whose answer is correct whenever it is asked: the run
    # history's own timestamps cannot themselves go out of date.
    current_by_construction: bool = False
    # Set when the reading rests on something that should exist and does not
    # -- a detector that has never succeeded, so there is no "as of" at all.
    # Distinct from data_as_of being None because nothing has happened yet:
    # one is unusable, the other is an honest zero.
    data_missing_reason: str | None = None
    note: str = ""

    @property
    def age(self) -> timedelta | None:
        if self.current_by_construction or self.data_as_of is None:
            return None
        return self.fetched_at - self.data_as_of

    @property
    def status(self) -> str:
        if self.data_missing_reason is not None:
            return STALE
        if self.current_by_construction:
            return CURRENT_BY_CONSTRUCTION
        if self.data_as_of is None:
            return NO_DATA
        return STALE if self.age > self.freshness_bound else FRESH

    @property
    def stale(self) -> bool:
        return self.status == STALE

    @property
    def usable(self) -> bool:
        """NO_DATA is usable: zero rows is an answer. STALE is not."""
        return not self.stale

    def describe(self) -> str:
        bound = _humanise(self.freshness_bound)
        if self.data_missing_reason is not None:
            return (f"{self.adapter}.{self.query_key} v{self.query_version}: "
                    f"{len(self.rows)} rows, unusable -- {self.data_missing_reason} "
                    f"(bound {bound}, {self.bound_source}) -> {STALE}")
        if self.current_by_construction:
            return (f"{self.adapter}.{self.query_key} v{self.query_version}: "
                    f"{len(self.rows)} rows, current by construction "
                    f"(bound {bound}, {self.bound_source})")
        if self.data_as_of is None:
            return (f"{self.adapter}.{self.query_key} v{self.query_version}: "
                    f"{len(self.rows)} rows, no underlying history yet "
                    f"(bound {bound}, {self.bound_source})")
        return (f"{self.adapter}.{self.query_key} v{self.query_version}: "
                f"{len(self.rows)} rows, data as of "
                f"{self.data_as_of.isoformat(timespec='seconds')} "
                f"({_humanise(self.age)} old, bound {bound}, "
                f"{self.bound_source}) -> {self.status}")


@dataclass
class AdapterOutput:
    """Everything one adapter read in one pass."""

    adapter: str
    fetched_at: datetime
    readings: dict[str, Reading] = field(default_factory=dict)

    def __getitem__(self, query_key: str) -> Reading:
        return self.readings[query_key]

    @property
    def stale(self) -> list[Reading]:
        return [r for r in self.readings.values() if r.stale]

    def describe(self) -> str:
        lines = [f"adapter {self.adapter} read at "
                 f"{self.fetched_at.isoformat(timespec='seconds')}"]
        lines += ["  " + r.describe() for r in self.readings.values()]
        return "\n".join(lines)


def _humanise(delta: timedelta | None) -> str:
    if delta is None:
        return "n/a"
    seconds = int(delta.total_seconds())
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{sign}{seconds // size}{unit}"
    return f"{sign}{seconds}s"
