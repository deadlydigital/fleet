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
# port fix, tests/analytics is green after five fixture fixes. So a wider gate
# is now POSSIBLE, and one of the two reasons not to has since gone away:
# the test-db tmpfs was raised from 384 MiB to 1536 MiB on 8 Sep 2026, and a
# whole tests/analytics directory run peaks at 648 MiB -- so it no longer
# exhausts the disk after about eight files, and no longer needs the database
# recreated part way through. What remains is time: tests/analytics is ~7.5
# minutes in one process and tests/api ~10. Neither belongs in the path of
# every task until the changed-file-aware gate exists to make the cost
# proportional to the diff.
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
    # Close the write end of the FIFO: db_lock.py hold is blocked on stdin, so
    # EOF is what releases the advisory lock. This runs on every exit path, and
    # if the gate is killed outright the fd closes with the shell anyway --
    # which is the property a lockfile does not have.
    exec 9>&- 2>/dev/null || true
    [ -n "${LOCK_PID:-}" ] && wait "$LOCK_PID" 2>/dev/null
    [ -n "${LOCK_DIR:-}" ] && rm -rf "$LOCK_DIR"
    [ "$STARTED_SERVICES" -eq 1 ] && docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1
}
trap cleanup EXIT

docker exec deadly-digital-test-db pg_isready >/dev/null 2>&1 || {
    echo "FAIL: the test database is not accepting connections."
    echo "      Reported as 'could not run' (2), never as a pass."
    exit 2
}

# THE EXCLUSIVE LOCK, HELD ACROSS THE WHOLE SWEEP.
#
# A gate anything else on the box can invalidate is not a gate. Two runs sharing
# the test database do not collide loudly -- `test_engine` drops every table at
# session end and `db_session` TRUNCATEs 40 tables after each test -- so the
# second run silently deletes the first one's rows mid-assertion and both report
# failures that belong to neither. That is not hypothetical: it invalidated
# three runs on 7 Sep 2026 and it is where TEST-004's 81-failure baseline came
# from, a number that was reproduced for weeks and never described the code.
#
# ACROSS THE SWEEP, NOT PER FILE. This gate runs pytest ~31 times. A lock taken
# per pytest process would let a second gate interleave between files, which is
# the same corruption one file later. So the lock is taken once, here, and
# DD_TEST_DB_LOCK_HELD tells the child processes their sweep already owns it --
# without it each child would block on the lock this script is holding.
#
# Held by a background `db_lock.py hold` blocked on a FIFO. The lock is a
# Postgres session advisory lock, so it lives exactly as long as that
# connection: releasing is closing fd 9, and dying is also closing fd 9.
LOCK_DIR=$(mktemp -d) || { echo "FAIL: could not create a lock directory"; exit 2; }
mkfifo "$LOCK_DIR/fifo" || { echo "FAIL: could not create the lock FIFO"; exit 2; }
"$PY_BIN" tests/db_lock.py hold <"$LOCK_DIR/fifo" >"$LOCK_DIR/ready" 2>"$LOCK_DIR/err" &
LOCK_PID=$!
exec 9>"$LOCK_DIR/fifo"

# db_lock.py waits out a legitimate holder rather than failing on contact, so
# this waits with it. 35 minutes is its own timeout plus slack; past that it has
# already given up and printed who was holding.
for _ in $(seq 1 2100); do
    grep -q READY "$LOCK_DIR/ready" 2>/dev/null && break
    kill -0 "$LOCK_PID" 2>/dev/null || break
    sleep 1
done
if ! grep -q READY "$LOCK_DIR/ready" 2>/dev/null; then
    echo "FAIL: could not take the exclusive test-database lock."
    sed 's/^/      /' "$LOCK_DIR/err" 2>/dev/null
    echo "      Reported as 'could not run' (2), never as a pass."
    exit 2
fi
export DD_TEST_DB_LOCK_HELD=1

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
