#!/bin/bash
# Does the file set reproduce the deployed schema?
#
#     ./tools/schema-drift-check.sh
#
# Builds a database from 001..011 on the local cluster, fingerprints both it
# and production, and diffs. Written after finding that it did NOT: commits
# 712195d and a99f17c added two grants to 001_v1_core.sql on `master`, and
# `track-2-foundation` -- the branch carrying everything from 002 onwards --
# was never merged with it. Production had the grants because the migration
# identity owns the tables, so nothing surfaced until a role that owns nothing
# needed them. Merged in 168e8bb; this is what keeps it merged.
#
# WHY NOT pg_dump. The two servers are different major versions (RDS 15.17,
# this box 16.x) and have different owners and login roles, so every object
# would differ on OWNER TO alone and half the file on deparser changes. The
# fingerprint compares the catalog instead, and excludes login roles and
# ownership deliberately -- they are environment, not schema.
#
# VIEW BODIES ACROSS MAJOR VERSIONS. `pg_get_viewdef` qualifies CTE column
# references with the CTE alias on 16 and not on 15, so a view can hash
# differently on the two servers while being the same view. Rather than
# filtering out the one view this affects today -- a filter that hides one
# view's hash hides the next one's too -- the fingerprint emits the server
# major version, and a difference confined to VIEW hash lines is reported as
# not-comparable when the majors differ and as DRIFT when they match.
#
# The views' output SHAPE is still compared either way: information_schema
# .columns covers view columns, so a view that gained, lost or retyped a
# column shows up as a COL difference regardless of version.
set -euo pipefail
cd "$(dirname "$0")/.."

# Every migration, in order. 015, 016 and 017 were missing from this list
# until 9 Sep 2026 -- so the comparison was being made against a schema three
# migrations behind, and drift in anything they touched was invisible to the
# check whose whole job is finding drift.
MIGRATIONS=(001_v1_core 002_proposals 003_tasks 004_console_reader
            005_console_decisions 006_verdict_coverage 007_research_floor
            008_task_reclaim 009_task_reclaims 010_decision_log
            011_proposal_product 012_daily_brief 013_approval_surface
            014_monthly_credit 015_sentry_detector 016_aws_cost_detector
            017_email_floor)
SCRATCH="${TMPDIR:-/tmp}/fleet-drift-$$"
LOCAL_DB="fleet_fromfiles"
SOCKET="${PGHOST:-/var/run/postgresql}"

# The migration identity is the platform api's DATABASE_URL user against the
# `fleet` database -- the same one 001-010 name in their headers. Assembled
# rather than stored a second time in fleet/.env.
PROD_DSN="$(.venv/bin/python - <<'PY'
import urllib.parse as up
for line in open("/home/ubuntu/deadly-digital-platform/api/.env"):
    if line.startswith("DATABASE_URL="):
        u = up.urlsplit(line.split("=", 1)[1].strip())
        print(up.urlunsplit((u.scheme,
              f"{u.username}:{u.password}@{u.hostname}:{u.port or 5432}",
              "/fleet", "sslmode=require", "")))
        break
PY
)"

mkdir -p "$SCRATCH"
trap 'rm -rf "$SCRATCH"' EXIT

echo "building $LOCAL_DB from ${#MIGRATIONS[@]} migration files..."
psql -q -h "$SOCKET" -d postgres \
     -c "DROP DATABASE IF EXISTS $LOCAL_DB WITH (FORCE)" \
     -c "CREATE DATABASE $LOCAL_DB" >/dev/null
for f in "${MIGRATIONS[@]}"; do
    psql -v ON_ERROR_STOP=1 -q -h "$SOCKET" -d "$LOCAL_DB" -f "$f.sql" >/dev/null
done

psql -q -h "$SOCKET" -d "$LOCAL_DB" -f tools/schema_fingerprint.sql > "$SCRATCH/files.txt"
psql -q "$PROD_DSN"                 -f tools/schema_fingerprint.sql > "$SCRATCH/prod.txt"

echo "  files:      $(wc -l < "$SCRATCH/files.txt") objects"
echo "  production: $(wc -l < "$SCRATCH/prod.txt") objects"
echo

if diff "$SCRATCH/prod.txt" "$SCRATCH/files.txt" > "$SCRATCH/delta.txt"; then
    echo "no drift: the file set reproduces the deployed schema"
    exit 0
fi

cat "$SCRATCH/delta.txt"
echo

# Everything the diff reported that is not a VIEW body hash or the SERVER
# line itself. SERVER is the metadata that explains the VIEW lines; counting
# it as drift would make the explanation trigger the alarm.
STRUCTURAL="$(grep -E '^[<>] ' "$SCRATCH/delta.txt" \
              | grep -vE '^[<>] (VIEW|SERVER) ' || true)"
PROD_MAJOR="$(grep '^SERVER ' "$SCRATCH/prod.txt"  | awk '{print $2}')"
FILE_MAJOR="$(grep '^SERVER ' "$SCRATCH/files.txt" | awk '{print $2}')"

if [ -z "$STRUCTURAL" ] && [ "$PROD_MAJOR" != "$FILE_MAJOR" ]; then
    echo "no structural drift. The differences above are view-body hashes only,"
    echo "and the servers are different major versions (production $PROD_MAJOR,"
    echo "local $FILE_MAJOR), which deparse views differently. View output"
    echo "shape is compared separately via COL rows and matches."
    exit 0
fi

echo "DRIFT: production and the file set disagree above (< production, > files)."
exit 1
