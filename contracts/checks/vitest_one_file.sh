#!/bin/bash
# Run vitest over one target, in a tree that may have no node_modules.
#
#     vitest_one_file.sh <project_dir> <target>
#
# Run from the root of the worktree. <target> is relative to <project_dir>.
# Exits 0 if the target passes, 1 if it fails, 2 if the check could not run.
#
# WHY IT EXISTS
#
# It is the frontend half of the pair pytest_unit_per_file.sh makes for the
# backend: the thing contracts/checks/new_test_bites.sh invokes to find out
# whether one test file passes against one tree. That check runs its target
# twice -- once against the change and once against a tree materialised from
# git -- and it needs a runner it can point at either.
#
# THE INTERFACE IS "ONE FILE", THE REASON IS NOT pytest_unit_per_file.sh's.
#
# That script runs one file per process because api/CLAUDE.md forbids suite
# runs on this host: the backend suite wants a Postgres, a Redis and a few
# hundred allocating processes beside a live API. None of that applies here.
# vitest needs no database and no docker -- the suite mocks HTTP with MSW --
# and all 21 files together are 65 seconds. So this is not an isolation
# measure and must not be read as one. It exists because new_test_bites.sh
# needs to run ONE named file, and because of the next paragraph.
#
# NODE_MODULES, WHICH IS THE WHOLE REASON THIS IS A SCRIPT AND NOT A COMMAND
#
# platform/node_modules is gitignored. The contract's ordinary verification
# gets it from `worktree_links`, which the runner sets up after the diff is
# judged -- but new_test_bites.sh materialises the PRE-CHANGE tree with
# `git archive`, and an archive of a gitignored directory contains nothing.
# So vitest in that tree cannot start.
#
# THAT FAILURE IS THE DANGEROUS ONE. new_test_bites.sh reads "the runner exited
# non-zero against the old tree" as "the test bites". A vitest that cannot
# start exits non-zero, so without this the bite check would PASS on every
# frontend task, having proved nothing -- the exact class of defect its own
# header calls "the fifth check-that-could-not-fail in this codebase".
#
# So: if the tree has no node_modules, this links the checkout's own in, runs,
# and removes the link. It links only what it created; a tree that already has
# one (the runner's worktree_links, or the checkout itself) is left alone.
set -uo pipefail

PROJECT_DIR="${1:-platform}"
TARGET="${2:-}"

# ABSOLUTE, like every other command in these contracts, and READ ONLY. The
# dependency tree comes from the main checkout; the CODE UNDER TEST comes from
# the worktree's cwd.
NODE_MODULES="${FLEET_PLATFORM_NODE_MODULES:-/home/ubuntu/deadly-digital-platform/platform/node_modules}"

[ -n "$TARGET" ] || { echo "FAIL: no target given"; exit 2; }
[ -d "$PROJECT_DIR" ] || { echo "FAIL: no $PROJECT_DIR in $(pwd)"; exit 2; }
[ -f "$PROJECT_DIR/$TARGET" ] || {
    echo "FAIL: no $PROJECT_DIR/$TARGET"; exit 2; }

LINKED=0
if [ ! -e "$PROJECT_DIR/node_modules" ]; then
    [ -d "$NODE_MODULES" ] || {
        echo "FAIL: $PROJECT_DIR has no node_modules and none at $NODE_MODULES."
        echo "      Reported as 'could not run' (2), never as a pass."
        exit 2; }
    ln -s "$NODE_MODULES" "$PROJECT_DIR/node_modules" || {
        echo "FAIL: could not link node_modules into $PROJECT_DIR"; exit 2; }
    LINKED=1
fi
cleanup() { [ "$LINKED" -eq 1 ] && rm -f "$PROJECT_DIR/node_modules"; }
trap cleanup EXIT

VITEST="$PROJECT_DIR/node_modules/.bin/vitest"
[ -x "$VITEST" ] || {
    echo "FAIL: no vitest at $VITEST."
    echo "      Reported as 'could not run' (2), never as a pass."
    exit 2; }

# --root, so vitest resolves vitest.config.ts, the `@` alias and
# __tests__/setup.ts from the tree under test rather than from wherever this
# was invoked. The target is passed as a filter, which vitest matches against
# the collected file list.
OUT=$(cd "$PROJECT_DIR" && timeout 300 ./node_modules/.bin/vitest run \
        --reporter=dot --no-color "$TARGET" 2>&1)
CODE=$?
echo "$OUT" | tail -25

if [ "$CODE" -eq 124 ]; then
    echo "FAIL: vitest did not finish within 300s on $TARGET"
    echo "      Reported as 'could not run' (2), never as a pass."
    exit 2
fi

# NO FILE MATCHED IS NOT A PASS. vitest exits 1 with "No test files found" for
# a filter that matches nothing, and that is a could-not-run rather than a
# failing test -- the distinction verify.Check.passed is built around, and the
# one that decides whether new_test_bites.sh believes a non-zero exit.
if echo "$OUT" | grep -q "No test files found"; then
    echo "FAIL: no test file matched $TARGET."
    echo "      Reported as 'could not run' (2), never as a pass."
    exit 2
fi

[ "$CODE" -eq 0 ] || { echo "FAIL: $TARGET did not pass"; exit 1; }
echo "PASS: $PROJECT_DIR/$TARGET"
