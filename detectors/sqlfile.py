"""Loader for the versioned SQL in detectors/queries/.

Every query a detector runs lives in a file named <key>.v<n>.sql, and the
key and version travel with the observation it produces
(evidence_query_key / evidence_query_version). An observation whose query
text cannot be recovered from version control is not evidence.

Identifiers cannot be bound as parameters, so the one identifier that
varies -- the per-tenant analytics schema -- is substituted textually and
validated against a strict pattern first. Values are always bound.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from . import config

_FILENAME_RE = re.compile(r"^(?P<key>[a-z0-9_]+)\.v(?P<version>\d+)\.sql$")
_ANALYTICS_SCHEMA_RE = re.compile(r"^analytics_[0-9]+$")


@dataclass(frozen=True)
class Query:
    key: str
    version: int
    sql: str

    def bind_schema(self, analytics_schema: str) -> "Query":
        """Return this query with {analytics_schema} substituted."""
        if not _ANALYTICS_SCHEMA_RE.match(analytics_schema):
            raise ValueError(f"refusing to interpolate schema name {analytics_schema!r}")
        return Query(self.key, self.version, self.sql.format(analytics_schema=analytics_schema))


@lru_cache(maxsize=None)
def load(key: str, version: int = 1) -> Query:
    path = config.QUERY_DIR / f"{key}.v{version}.sql"
    if not path.exists():
        raise FileNotFoundError(f"no query file {path}")
    return Query(key=key, version=version, sql=path.read_text())


def analytics_schema(tenant_id: int) -> str:
    return f"analytics_{int(tenant_id)}"
