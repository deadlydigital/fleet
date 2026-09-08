#!/bin/bash
# Test gate: tests/unit, ONE FILE PER PYTEST PROCESS.
#
# Run from the root of the worktree. Exits 0 if every file passes, 1 naming
# the files that did not, 2 if the gate could not run at all.
#
# WHY PER FILE AND NOT `pytest tests/unit`
#
# api/CLAUDE.md forbids suite and directory runs on this host, and the reason
# is not a memory budget: this box serves production traffic. The test stack
# wants a Postgres, a Redis, a RAM-backed data directory and a few hundred
# concurrently-allocating Python processes on the same kernel and page cache
# as the live API, four workers and the frontend. Incident 3 (23 Aug 2026) was
# an allocation failure inside a test process with 63 MB free beside a live
# API. Per-file is what that document permits, and it works because each
# process exits before the next starts, so peak footprint stays one file wide.
#
# It is also MORE trustworthy here, not less. The suite leaks state between
# modules -- schemas, rows and sequences survive from one file into the next --
# so a directory run reports failures a clean run does not. api/CLAUDE.md logs
# that costing real time twice in one day. Per-file is the isolation the suite
# actually has.
#
# WHY tests/unit AND NOTHING WIDER, TODAY
#
# Measured 8 Sep 2026 at 7375d0a, file by file on a clean database: tests/unit
# and tests/api are both green, tests/integration is green after the Redis
# port fix, tests/analytics is green after four fixture fixes. So a wider gate
# is now POSSIBLE -- but tests/analytics exhausts the 384 MiB tmpfs after
# about eight files and needs the test database recreated to continue, and
# tests/api takes ~10 minutes. Neither belongs in the path of every task until
# the changed-file-aware gate exists to make the cost proportional to the diff.
#
# tests/unit is 31 files, ~5 minutes, and needs no database reset.
#
# WHY --no-cov
#
# pytest.ini puts `--cov=app` in addopts. Coverage on a single file costs
# memory and time for a number nobody reads here, and `--cov-fail-under` --
# which used to make a green run exit non-zero -- has since moved to the CI
# api step. The flag stays for the cost, not for the exit code.
set -uo pipefail

API_DIR="${1:-api}"
TARGET="${2:-tests/unit}"

# ABSOLUTE, like every other command in this contract. api/.venv is gitignored,
# so a worktree has none -- the interpreter comes from the main checkout while
# the CODE UNDER TEST comes from the worktree's cwd. Read, never written.
PY_BIN="${FLEET_API_PYTHON:-/home/ubuntu/deadly-digital-platform/api/.venv/bin/python}"
COMPOSE_FILE="tests/docker-compose.test.yml"

[ -x "$PY_BIN" ] || { echo "FAIL: no interpreter at $PY_BIN"; exit 2; }
cd "$API_DIR" || { echo "FAIL: no $API_DIR in $(pwd)"; exit 2; }

# THE TEST SERVICES, STARTED AND LEFT AS FOUND.
#
# api/CLAUDE.md: "Start the test services first and stop them again afterwards
# -- they must not be left running alongside the app containers." So this
# starts them only if they are down, and stops them again only if it started
# them. A gate that left a Postgres and a Redis running beside production every
# time a task ran would be doing the thing that document forbids, slowly.
STARTED_SERVICES=0
if ! docker exec deadly-digital-test-db pg_isready >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" up -d >/dev/null 2>&1 || {
        echo "FAIL: could not start the test services"; exit 2; }
    STARTED_SERVICES=1
    for _ in $(seq 1 30); do
        docker exec deadly-digital-test-db pg_isready >/dev/null 2>&1 && break
        sleep 2
    done
    sleep 3
fi
cleanup() {
    [ "$STARTED_SERVICES" -eq 1 ] && docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1
}
trap cleanup EXIT

docker exec deadly-digital-test-db pg_isready >/dev/null 2>&1 || {
    echo "FAIL: the test database is not accepting connections."
    echo "      Reported as 'could not run' (2), never as a pass."
    exit 2
}

mapfile -t FILES < <(find "$TARGET" -name 'test_*.py' | sort)
[ "${#FILES[@]}" -gt 0 ] || { echo "FAIL: no test files under $TARGET"; exit 2; }

# The guards. A gate that degrades the API is worse than no gate, so this
# stops rather than pushes on -- and reports 2 (could not run), never 0.
MIN_MEM_MB=500
failed=()
for f in "${FILES[@]}"; do
    avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
    if [ "${avail:-0}" -lt "$MIN_MEM_MB" ]; then
        echo "FAIL: aborting with ${avail}MB available (floor ${MIN_MEM_MB}MB)."
        echo "      The gate stops rather than compete with the live API for memory."
        exit 2
    fi
    if ! timeout 300 "$PY_BIN" -m pytest "$f" -q --no-cov \
            -p no:cacheprovider --tb=short >/tmp/pgate.$$ 2>&1; then
        failed+=("$f")
        echo "--- FAILED $f"
        tail -15 /tmp/pgate.$$
    fi
done
rm -f /tmp/pgate.$$

if [ "${#failed[@]}" -gt 0 ]; then
    echo
    echo "FAIL: ${#failed[@]} of ${#FILES[@]} files in $TARGET failed:"
    printf '  %s\n' "${failed[@]}"
    exit 1
fi
echo "PASS: ${#FILES[@]} files in $TARGET, one process each"
