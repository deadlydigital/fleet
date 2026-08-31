#!/usr/bin/env python3
"""Acceptance check: replacing `_META_PAID_SOURCES` must not move a single order.

Run from the root of the worktree. Lives in the fleet repository, so the agent
working in a platform worktree cannot edit what judges it -- out of reach by
construction rather than by being on a protected-path list.

WHAT IT ASSERTS, AND WHY IT IS WRITTEN NOW WHILE IT PASSES
----------------------------------------------------------
`api/analytics/routes/sources.py` decides whether an order counts as Meta-paid
with a hardcoded set:

    _META_PAID_SOURCES = {"meta_paid", "fb", "facebook", "ig", "instagram", "meta"}

The utm_source_alias work deletes that set and reads `is_paid_meta` from the
table instead. Measured 31 Aug 2026 against `analytics_2.orders`, the two
classify **exactly the same orders**: the set and the seed's four
`is_paid_meta=true` rows each match 105,540 -- lost 0, gained 0.

That 0/0 is not luck. It was bought deliberately: seed row 20 holds
`facebook`'s `is_paid_meta` TRUE precisely so the cutover moves nothing, and
`instagram`/`meta` match no orders on this tenant so dropping them costs
nothing. This check freezes that property **while it holds**, so the thing it
objects to is a later edit -- someone flipping `facebook` to false, or adding a
spelling to the seed without thinking about spend_attribution -- rather than a
cutover nobody can undo. See `ATTR-001` in the platform repo's `docs/TODO.md`.

WHAT IT DOES NOT ASSERT: 105,540
--------------------------------
`analytics_2.orders` is live and ingesting. The count moved +4 in the 40
minutes between being measured and this file being written. Asserting the
literal 105,540 would make the check red by tomorrow morning for a reason that
has nothing to do with anyone's change, and an unreachable gate teaches
everyone to ignore it -- which is `TEST-004`'s finding, in a new place.

So the assertion is the INVARIANT (`lost == 0 and gained == 0`, and the two
populations are equal), not the number. The absolute count is printed with its
drift from the 31 Aug baseline so a human can see movement, and is floor-checked
only to catch a query aimed at the wrong tenant or an empty table.

THE TWO HALVES
--------------
1. STATIC. The seed's `is_paid_meta=true` alias_norm set must be exactly
   {meta_paid, fb, ig, facebook}. Needs no database and is the half that
   actually objects to an edit. Always runs.
2. DATABASE. Materialises the two populations over `analytics_2.orders` as
   `dd_detector_login` (DD_DSN, read-only) and asserts 0/0.

The database half FAILS the run if it cannot connect, because "could not
establish 0/0" is not "0/0 holds" -- the distinction this whole entry is about.
Set UTM_ALIAS_CHECK_ALLOW_NO_DB=1 to downgrade it to a loud recorded skip when
the database is genuinely unreachable and the branch must still be judged.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# The historical set, frozen here ON PURPOSE. The task under test deletes it
# from sources.py, so this check cannot read it from the post-change tree --
# and should not, because what is being frozen is the behaviour BEFORE the
# change. If this literal is ever edited, the check has stopped meaning what it
# says.
HISTORICAL_META_PAID_SOURCES = {"meta_paid", "fb", "facebook", "ig", "instagram", "meta"}

# The seed rows carrying is_paid_meta=true. Derived from the settled seed, and
# re-derived from the tree at run time -- this literal is the expectation, the
# parse is the observation, and the check is that they agree.
EXPECTED_PAID_META_ALIASES = {"meta_paid", "fb", "ig", "facebook"}

# Baseline reading, for drift reporting only. Never asserted.
BASELINE_COUNT = 105_540
BASELINE_TAKEN = "2026-08-31 ~20:30 UTC"
COUNT_FLOOR = 50_000

TENANT_ID = 2
SCHEMA = "analytics_2"

CANONICAL_SEED = Path("/home/ubuntu/fleet/specs/data/utm_source_alias_seed.sql")
MIGRATION_GLOB = "api/alembic/versions/*utm_source_alias*.py"

# (2, 'alias_norm', 'alias_raw', 'Canonical', 'channel', is_paid_meta, allow_override,
#  'origin', 'note')  -- we want alias_norm and the FIRST boolean after it.
ROW_RE = re.compile(
    r"\(\s*(?P<tenant>\d+)\s*,\s*"
    r"'(?P<alias_norm>(?:[^']|'')*)'\s*,\s*"
    r"'(?:[^']|'')*'\s*,\s*"          # alias_raw
    r"'(?:[^']|'')*'\s*,\s*"          # canonical_source
    r"'(?:[^']|'')*'\s*,\s*"          # channel
    r"(?P<is_paid_meta>true|false)\s*,\s*"
    r"(?P<allow_override>true|false)\s*,",
    re.IGNORECASE,
)


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def find_seed_source() -> tuple[Path, str]:
    """The migration in the worktree if this task wrote one, else the canonical seed.

    Returns (path, provenance). Which one was used is printed, because a check
    that silently falls back to a file the task did not produce is asserting
    something other than what the reader assumes.
    """
    matches = sorted(Path(".").glob(MIGRATION_GLOB))
    if matches:
        return matches[0], "migration in this worktree"
    if CANONICAL_SEED.exists():
        return CANONICAL_SEED, "canonical seed in the fleet repo (no migration in this worktree)"
    raise FileNotFoundError(
        f"neither {MIGRATION_GLOB} nor {CANONICAL_SEED} exists; nothing to check against"
    )


def parse_seed(text: str) -> tuple[set[str], set[str], int]:
    """(paid_meta aliases, override-suppressed aliases, total rows) for TENANT_ID."""
    paid, no_override, total = set(), set(), 0
    for m in ROW_RE.finditer(text):
        if int(m.group("tenant")) != TENANT_ID:
            continue
        total += 1
        alias = m.group("alias_norm").replace("''", "'")
        if m.group("is_paid_meta").lower() == "true":
            paid.add(alias)
        if m.group("allow_override").lower() == "false":
            no_override.add(alias)
    return paid, no_override, total


def check_static() -> tuple[int, set[str]]:
    try:
        path, provenance = find_seed_source()
    except FileNotFoundError as exc:
        return fail(str(exc)), set()

    paid, no_override, total = parse_seed(path.read_text())
    print(f"  seed source : {path} ({provenance})")
    print(f"  rows parsed : {total} for tenant {TENANT_ID}")

    if total != 20:
        return fail(
            f"parsed {total} seed rows for tenant {TENANT_ID}, expected 20. "
            "Either the seed changed or this check's row pattern no longer matches it; "
            "both need a human before the counts below mean anything."
        ), set()

    if len(no_override) != 5:
        return fail(
            f"{len(no_override)} rows have allow_override=false, expected 5 "
            f"({sorted(no_override)}). Flag 6 requires the column and five rows opt out; "
            "a change here is a decision, not a refactor."
        ), set()

    if paid != EXPECTED_PAID_META_ALIASES:
        added = sorted(paid - EXPECTED_PAID_META_ALIASES)
        removed = sorted(EXPECTED_PAID_META_ALIASES - paid)
        return fail(
            "the seed's is_paid_meta=true rows are no longer "
            f"{sorted(EXPECTED_PAID_META_ALIASES)}: added={added} removed={removed}. "
            "This is the edit the check exists to object to -- it moves orders "
            "into or out of spend_attribution's unattributable_paid count. If it is "
            "intended, re-measure the diff and update EXPECTED_PAID_META_ALIASES and "
            "the baseline together, in the same commit, with the new numbers stated."
        ), set()

    print(f"  is_paid_meta: {sorted(paid)} -- matches the frozen expectation")
    return 0, paid


def check_database(paid: set[str]) -> int:
    dsn_var = "DD_DSN"
    waived = os.environ.get("UTM_ALIAS_CHECK_ALLOW_NO_DB") == "1"

    try:
        sys.path.insert(0, "/home/ubuntu/fleet")
        import psycopg  # noqa: PLC0415
        from detectors import config as base_config  # noqa: PLC0415

        dsn = base_config.require(dsn_var)
        conn = psycopg.connect(dsn, connect_timeout=20)
        conn.read_only = True
    except Exception as exc:  # noqa: BLE001
        msg = f"cannot reach {dsn_var}: {str(exc).splitlines()[0][:200]}"
        if waived:
            print(f"  SKIP (waived by UTM_ALIAS_CHECK_ALLOW_NO_DB=1): {msg}")
            print("  The 0/0 diff was NOT established on this run. A skipped reading "
                  "and a passing one are different facts.")
            return 0
        return fail(
            f"{msg}. The whole point of this check is the measured diff, so a "
            "connection failure is a failure to establish it, not a pass. Set "
            "UTM_ALIAS_CHECK_ALLOW_NO_DB=1 to record it as a skip if the branch "
            "must be judged without a database."
        )

    with conn:
        conn.execute("SET statement_timeout = 120000")
        sql = f"""
            WITH o AS (SELECT lower(btrim(utm_source)) AS k FROM {SCHEMA}.orders)
            SELECT
              count(*) FILTER (WHERE k = ANY(%(hist)s))                          AS set_paid,
              count(*) FILTER (WHERE k = ANY(%(seed)s))                          AS seed_paid,
              count(*) FILTER (WHERE k = ANY(%(hist)s) AND NOT k = ANY(%(seed)s)) AS lost,
              count(*) FILTER (WHERE k = ANY(%(seed)s) AND NOT k = ANY(%(hist)s)) AS gained
            FROM o
        """
        params = {"hist": sorted(HISTORICAL_META_PAID_SOURCES), "seed": sorted(paid)}
        set_paid, seed_paid, lost, gained = conn.execute(sql, params).fetchone()

    drift = set_paid - BASELINE_COUNT
    print(f"  {SCHEMA}.orders, as the read-only reader:")
    print(f"    classed Meta-paid by _META_PAID_SOURCES : {set_paid:,}")
    print(f"    classed Meta-paid by seed is_paid_meta  : {seed_paid:,}")
    print(f"    lost at cutover: {lost}    gained at cutover: {gained}")
    print(f"    baseline {BASELINE_COUNT:,} taken {BASELINE_TAKEN}; drift {drift:+,} "
          "(the table is live -- the count is expected to move, the diff is not)")

    if set_paid < COUNT_FLOOR:
        return fail(
            f"only {set_paid:,} orders classed Meta-paid, below the {COUNT_FLOOR:,} floor. "
            "That is not drift -- it suggests an empty table, the wrong tenant schema, or "
            "a reader that cannot see the rows. The 0/0 below would be vacuous."
        )

    if lost or gained:
        return fail(
            f"the cutover is NOT a no-op: {lost} orders lose Meta-paid status and "
            f"{gained} gain it. spend_attribution's unattributable_paid count changes "
            "silently at cutover for those orders. Either restore the property or make "
            "the change deliberately -- re-measure, state the new numbers, and update "
            "this check and ATTR-001 in the same commit."
        )

    if set_paid != seed_paid:
        return fail(
            f"populations differ in size ({set_paid:,} vs {seed_paid:,}) while lost and "
            "gained are both 0. That is arithmetically impossible unless the query "
            "changed; do not trust this run."
        )

    print(f"  0/0 holds: both classify the same {set_paid:,} orders")
    return 0


def main() -> int:
    print("utm_source_alias cutover diff -- ATTR-001")
    rc, paid = check_static()
    if rc:
        return rc
    rc = check_database(paid)
    if rc:
        return rc
    print("ok: the seed's is_paid_meta rows classify exactly the orders "
          "_META_PAID_SOURCES classifies; replacing it moves nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
