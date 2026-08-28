"""The detectors adapter: track 1's tables, read-only, with their age.

Connects as fleet_detector_reader, which holds SELECT on track 1 and nothing
else. There is no write path from this module by role and by intent.

Five questions, plus the two readings that establish how fresh the answers
are:

  registry_geometry       schedule geometry and last success per detector
  detector_health         run history: successes, errors, streaks, silence
  open_issues             severity, magnitude, occurrence count, age
  false_positive_rate     by detector and observation type, recent vs prior
  untriaged_observations  what the false-positive rate is starved of
  coverage_gaps           open issues that cannot resolve, and why
  verdict_recency         when a person last ruled on anything

Freshness. Every reading that rests on detector output is judged against the
detector that is furthest past its own cadence + grace, not against an
average and not against the fastest. A heartbeat running every five minutes
does not vouch for a reconciliation detector that stopped yesterday, and the
reading that says "one issue is open" is exactly as trustworthy as the
weakest detector behind it. A reading past its bound is returned marked
STALE; the cycle refuses to build a finding on one.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import config
from .adapter import AdapterOutput, Reading, load_query

log = logging.getLogger(__name__)

ADAPTER = "detectors"

REGISTRY_GEOMETRY = "registry_geometry"
DETECTOR_HEALTH = "detector_health"
OPEN_ISSUES = "open_issues"
FALSE_POSITIVE_RATE = "false_positive_rate"
UNTRIAGED_OBSERVATIONS = "untriaged_observations"
COVERAGE_GAPS = "coverage_gaps"
VERDICT_RECENCY = "verdict_recency"

# Used only when the registry is empty -- there is then no geometry to derive
# a bound from, and a reading with no bound at all cannot be judged.
NO_DETECTORS_BOUND = timedelta(hours=1)


def connect(dsn: str | None = None) -> psycopg.Connection:
    """A read-only connection as fleet_detector_reader.

    read_only is set on the session as well as being enforced by the grants:
    the role cannot write, and the session would refuse to if it could.
    """
    conn = psycopg.connect(dsn or config.reader_dsn(), row_factory=dict_row,
                           autocommit=False)
    conn.read_only = True
    return conn


class DetectorsAdapter:
    name = ADAPTER

    def __init__(self, dsn: str | None = None,
                 cycle_config: dict[str, Any] | None = None) -> None:
        self._dsn = dsn
        self._config = cycle_config if cycle_config is not None else config.load_cycle_config()

    # ---- entry point ------------------------------------------------------

    def read(self, conn: psycopg.Connection | None = None) -> AdapterOutput:
        if conn is not None:
            return self._read(conn)
        with connect(self._dsn) as owned:
            return self._read(owned)

    def _read(self, conn: psycopg.Connection) -> AdapterOutput:
        fetched_at = conn.execute("SELECT now() AS t").fetchone()["t"]
        out = AdapterOutput(adapter=self.name, fetched_at=fetched_at)

        geometry = self._rows(conn, REGISTRY_GEOMETRY)
        health = self._rows(conn, DETECTOR_HEALTH)
        recency = self._rows(conn, VERDICT_RECENCY)

        # Geometry and health answer questions about the run history itself,
        # so they are correct whenever they are asked.
        out.readings[REGISTRY_GEOMETRY] = self._current(
            REGISTRY_GEOMETRY, geometry, fetched_at,
            bound=self._widest_silence_budget(geometry))
        out.readings[DETECTOR_HEALTH] = self._current(
            DETECTOR_HEALTH, health, fetched_at,
            bound=self._widest_silence_budget(geometry))

        detector_freshness = self._detector_freshness(geometry, fetched_at)

        for key, params in ((OPEN_ISSUES, None),
                            (UNTRIAGED_OBSERVATIONS, None),
                            (COVERAGE_GAPS, None)):
            out.readings[key] = Reading(
                adapter=self.name, query_key=key, query_version=1,
                rows=self._rows(conn, key, params), fetched_at=fetched_at,
                bound_source="detector_registry", **detector_freshness)

        window = config.parse_interval(
            self._config["findings"]["false_positive_rate_rising"]["window"])
        fp_rows = self._rows(conn, FALSE_POSITIVE_RATE,
                             {"window": f"{int(window.total_seconds())} seconds"})
        out.readings[FALSE_POSITIVE_RATE] = self._verdict_reading(
            FALSE_POSITIVE_RATE, fp_rows, recency, fetched_at)
        out.readings[VERDICT_RECENCY] = self._verdict_reading(
            VERDICT_RECENCY, recency, recency, fetched_at)

        return out

    # ---- helpers ----------------------------------------------------------

    def _rows(self, conn: psycopg.Connection, key: str,
              params: dict[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
        query = load_query(key)
        rows = conn.execute(query.sql, params).fetchall()
        return tuple(dict(r) for r in rows)

    def _current(self, key: str, rows: tuple[dict[str, Any], ...],
                 fetched_at: datetime, bound: timedelta) -> Reading:
        return Reading(adapter=self.name, query_key=key, query_version=1,
                       rows=rows, fetched_at=fetched_at,
                       freshness_bound=bound, bound_source="detector_registry",
                       current_by_construction=True)

    @staticmethod
    def _active(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        """Detectors that are supposed to be running right now.

        A retired detector is silent on purpose, and one in maintenance has
        been told to be. Neither should make every other reading stale.
        """
        out = []
        for row in rows:
            if row.get("retired_at") is not None:
                continue
            until = row.get("maintenance_until")
            if until is not None and until > datetime.now(until.tzinfo):
                continue
            out.append(row)
        return out

    @staticmethod
    def _widest_silence_budget(geometry: tuple[dict[str, Any], ...]) -> timedelta:
        budgets = [r["silence_budget"] for r in DetectorsAdapter._active(geometry)]
        return max(budgets) if budgets else NO_DETECTORS_BOUND

    @staticmethod
    def _detector_freshness(geometry: tuple[dict[str, Any], ...],
                            fetched_at: datetime) -> dict[str, Any]:
        """Judge every active detector against its own budget, report the worst.

        By excess -- age minus that detector's own silence budget -- and not
        by oldest timestamp. A detector on a five-minute cadence that has been
        quiet an hour is further gone than one on a daily cadence quiet for a
        day, and picking the oldest timestamp would report the second and miss
        the first.
        """
        active = DetectorsAdapter._active(geometry)
        if not active:
            return {"freshness_bound": NO_DETECTORS_BOUND,
                    "data_as_of": None,
                    "data_missing_reason": None}

        never = [r["detector_key"] for r in active if r["last_ok_at"] is None]
        if never:
            return {"freshness_bound": DetectorsAdapter._widest_silence_budget(geometry),
                    "data_as_of": None,
                    "data_missing_reason":
                        "no successful scheduled run on record for "
                        + ", ".join(sorted(never))}

        worst = max(active,
                    key=lambda r: (fetched_at - r["last_ok_at"]) - r["silence_budget"])
        return {"freshness_bound": worst["silence_budget"],
                "data_as_of": worst["last_ok_at"],
                "data_missing_reason": None,
                "note": f"bound set by {worst['detector_key']}"}

    def _verdict_reading(self, key: str, rows: tuple[dict[str, Any], ...],
                         recency: tuple[dict[str, Any], ...],
                         fetched_at: datetime) -> Reading:
        """Verdict-derived readings age on a human cadence, not a detector one."""
        bound = config.parse_interval(self._config["freshness"]["verdicts"])
        last = recency[0]["last_verdict_at"] if recency else None
        return Reading(adapter=self.name, query_key=key, query_version=1,
                       rows=rows, fetched_at=fetched_at,
                       freshness_bound=bound, bound_source="cycle.yaml",
                       data_as_of=last,
                       note="no verdict has ever been recorded" if last is None else "")
