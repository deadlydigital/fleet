"""Shared helpers. Nothing here decides anything a test should assert."""
from __future__ import annotations

from datetime import datetime

from detectors import base
from detectors.reconciliation import ReconciliationDetector


#: The protected-path floor for `deadly-digital-platform`, as the database
#: holds it. ONE COPY, because there were eight and 017 broke all of them at
#: once: every fixture built a contract missing the five email globs, so 98
#: tests failed on `contract for deadly-digital-platform does not protect ...`
#: — none of them about what they were testing.
#:
#: `test_email_floor.py::test_the_test_floor_matches_the_database` asserts this
#: list is what `protected_path_floor` actually contains, so the next migration
#: that moves the floor fails ONE named test instead of a hundred unrelated
#: ones.
PLATFORM_FLOOR = [
    "api/tests/**",
    "api/pytest.ini",
    "api/ruff.toml",
    "api/alembic/**",
    "api/analytics/migrations/**",
    "platform/__tests__/**",
    "platform/vitest.config.ts",
    "platform/playwright.config.ts",
    # 017: the email floor. specs/unattended-operation.md §2.
    "api/app.py",
    "api/services/email_sender.py",
    "api/worker.py",
    "api/analytics/routes/interventions.py",
    "api/analytics/services/trigger_router.py",
    # 018: erasure
    "api/analytics/services/gdpr.py",
    # 019: the rest of the erasure path
    "api/services/gdpr_identity.py",
    "api/services/gdpr_replay_scrub.py",
    # 023: the platform floor, added when the frontend got a contract.
    # Auth and session. middleware.ts is not under app/, components/ or lib/,
    # so the retired wide contract missed it by accident.
    "platform/middleware.ts",
    "platform/lib/auth.ts",
    "platform/lib/api-auth.ts",
    "platform/lib/roles.ts",
    "platform/lib/csrf.ts",
    "platform/app/api/auth/**",
    # Billing.
    "platform/app/api/billing/**",
    "platform/app/api/admin/billing/**",
    "platform/app/(dashboard)/settings/billing/**",
    # Email: the frontend half of what 017 floored on the api side.
    "platform/app/api/campaigns/**",
    "platform/app/api/flows/**",
    "platform/app/api/domains/**",
    "platform/app/api/suppression/**",
    "platform/app/api/scheduled-campaigns/**",
    "platform/app/api/inline-css/**",
    "platform/app/api/listmonk/**",
    "platform/app/(dashboard)/campaigns/**",
    "platform/app/(dashboard)/flows/**",
    "platform/app/(dashboard)/settings/domains/**",
    # The storefront event ingest.
    "platform/app/api/track/**",
    # GDPR: the frontend half of 018 and 019.
    "platform/app/api/gdpr/**",
    "platform/app/(dashboard)/settings/privacy/**",
    # The intervention surface, inside the analytics tree -- 017's E3 case at
    # the frontend, and why dd-analytics-frontend.yaml enumerates.
    "platform/app/api/analytics/churn/intervene/**",
    "platform/app/api/analytics/interventions/**",
    "platform/app/(dashboard)/analytics/interventions/**",
]


def settled_slots(conn, count: int = 4, cadence: str = "1 hour",
                  settle_lag: str = "15 minutes") -> list[datetime]:
    """On-grid, already-settled slot ends, newest first."""
    rows = conn.execute(
        """
        SELECT date_trunc('hour', now() - %(lag)s::interval)
               - (i * %(cad)s::interval) AS slot
          FROM generate_series(0, %(n)s - 1) AS i
        """,
        {"lag": settle_lag, "cad": cadence, "n": count}).fetchall()
    return [r["slot"] for r in rows]


def heartbeat_slots(conn, count: int = 4) -> list[datetime]:
    rows = conn.execute(
        """
        SELECT date_trunc('hour', now())
               + (floor(extract(minute FROM now()) / 5) * interval '5 minutes')
               - (i * interval '5 minutes') AS slot
          FROM generate_series(0, %(n)s - 1) AS i
        """, {"n": count}).fetchall()
    return [r["slot"] for r in rows]


def run_reconciliation(fleet, dd_dsn: str, slot_end: datetime | None = None):
    return base.execute(ReconciliationDetector(dd_dsn), fleet, slot_end=slot_end)


def observations(conn, run_id: int | None = None,
                 observation_type: str | None = None,
                 subject_id: str | None = None) -> list[dict]:
    return conn.execute(
        """
        SELECT * FROM observations
         WHERE (%(run)s::bigint IS NULL OR detector_run_id = %(run)s)
           AND (%(type)s::text  IS NULL OR observation_type = %(type)s)
           AND (%(subj)s::text  IS NULL OR subject_id = %(subj)s)
         ORDER BY id
        """,
        {"run": run_id, "type": observation_type, "subj": subject_id}).fetchall()


def run_row(conn, run_id: int) -> dict:
    return conn.execute("SELECT * FROM detector_runs WHERE id = %s",
                        (run_id,)).fetchone()


def issue(conn, fingerprint: str) -> dict | None:
    return conn.execute("SELECT * FROM issues WHERE fingerprint = %s",
                        (fingerprint,)).fetchone()
