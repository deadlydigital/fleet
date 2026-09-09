#!/bin/bash
# The added test must FAIL against the pre-change tree.
#
# Run from the root of the worktree. Exits 0 if the test bites, 1 naming what
# went wrong, 2 if the check could not run at all.
#
# WHY THIS EXISTS
#
# specs/unattended-operation.md §3.2. `api/tests/**` is on the floor as "the
# suite that judges the work", so an agent cannot write tests -- and a feature
# therefore lands with nothing covering the new behaviour. Running the whole
# analytics suite proves the change BROKE NOTHING. It cannot prove the new
# thing works. Task 28's own spec says so about itself: a passing run does not
# establish that any comparison window it computes is the right one.
#
# On auto-merge, "675 tests passed" reads as verified and means "not obviously
# regressed". That is the fifth check-that-could-not-fail in this codebase, and
# it would be the first one built deliberately.
#
# So `creatable_paths` lets the agent ADD one test file (never modify one), and
# this is the check that stops the obvious cheat. An `assert True` passes
# against the change AND against the tree before it. A test that discriminates
# does not.
#
# This is PLAN.md §6.2 Rule 2 -- "a check must be demonstrated to fail against
# the broken state before its pass is believed" -- applied by machine instead
# of by hand. The codebase already applies it by hand in tests/revert_guards.py
# and applies it nowhere automatically.
#
# WHAT IT DOES NOT ESTABLISH, SO NOBODY READS MORE INTO A GREEN
#
# That the test asserts the RIGHT thing. A test that fails before and passes
# after has discriminated between two trees; whether it discriminated on the
# property the spec asked for is a question only the spec and a reader can
# answer. This closes the vacuous case, not the wrong-assertion case.
#
# WHAT CHANGED WHEN THE FRONTEND GOT A CONTRACT (9 Sep 2026)
#
# This was written for `api` and pytest and is now used by `platform` and
# vitest too. Three things moved, and only the third is a behaviour change:
#
#   the project directory and the suite directory are arguments, because the
#   frontend suite is platform/__tests__/ rather than <project>/tests/
#
#   the interpreter precondition is gone. It checked
#   api/.venv/bin/python without ever invoking it, and
#   pytest_unit_per_file.sh checks the same interpreter and reports 2 itself.
#   Duplicating it here meant a second runner had to satisfy a precondition
#   belonging to the first.
#
#   COULD-NOT-RUN IS NO LONGER READ AS "THE TEST BITES". Step 4 asked the
#   runner to fail against the pre-change tree and took ANY non-zero exit as
#   proof. A runner that cannot start also exits non-zero -- and the
#   pre-change tree is materialised with `git archive`, which for the frontend
#   contains no node_modules, so vitest could not have started there at all.
#   That would have passed this check on every frontend task while proving
#   nothing: this file's own fifth check-that-could-not-fail, built by the
#   file that exists to stop them. Runners report 2 for could-not-run, and
#   both invocations below now distinguish it.
set -uo pipefail

PROJECT_DIR="${1:-api}"
PATTERN="${2:-tests/analytics/test_fleet_*.py}"
# Where the protected suite lives, relative to PROJECT_DIR. Step 2 refuses any
# change to it beyond the one added file.
SUITE_DIR="${3:-tests}"

BASE="${FLEET_BASE_SHA:-}"

# The thing that actually runs one test file, and the thing that decides what
# an exit code means. Overridable so this check can be tested without the
# docker stack, and so the frontend can hand it vitest_one_file.sh. Whatever
# it is, the contract is the same: 0 passed, 1 failed, 2 COULD NOT RUN.
RUNNER="${FLEET_TEST_RUNNER:-$(cd "$(dirname "$0")" && pwd)/pytest_unit_per_file.sh}"
[ -x "$RUNNER" ] || { echo "FAIL: no test runner at $RUNNER"; exit 2; }

# THE SERVICES COME UP ONCE, NOT TWICE.
#
# The harness starts the test services if they are down and stops them again if
# it started them -- correct on its own, and this check invokes it twice, so
# left alone it pays two start/stop cycles for two runs of one file. Bringing
# them up here means both inner runs find them already up and leave them alone,
# and this script puts them back exactly as it found them.
COMPOSE="$PROJECT_DIR/$SUITE_DIR/docker-compose.test.yml"
SERVICES_STARTED=0
if [ -f "$COMPOSE" ] && ! docker exec deadly-digital-test-db pg_isready >/dev/null 2>&1; then
    if docker compose -f "$COMPOSE" up -d >/dev/null 2>&1; then
        SERVICES_STARTED=1
        for _ in $(seq 1 30); do
            docker exec deadly-digital-test-db pg_isready >/dev/null 2>&1 && break
            sleep 2
        done
    fi
fi
stop_services() {
    if [ "$SERVICES_STARTED" -eq 1 ]; then
        docker compose -f "$COMPOSE" down >/dev/null 2>&1 || true
    fi
}
trap stop_services EXIT

[ -n "$BASE" ]   || { echo "FAIL: FLEET_BASE_SHA is not set, so there is no "\
                           "pre-change tree to test against"; exit 2; }
[ -d .git ] || [ -f .git ] || { echo "FAIL: not a git worktree"; exit 2; }

# ---- 1. what was added --------------------------------------------------
# --diff-filter=A: ADDED only. A modified test is refused by the boundary
# before this runs, and asking git for the status again here means this check
# does not depend on that having happened.
mapfile -t ADDED < <(git diff --diff-filter=A --name-only "$BASE..HEAD" \
                     -- "$PROJECT_DIR/$PATTERN" | sort)

if [ "${#ADDED[@]}" -eq 0 ]; then
    echo "FAIL: the change adds no test matching $PROJECT_DIR/$PATTERN"
    echo "      A task that changes behaviour must add a test that fails"
    echo "      without the change. specs/unattended-operation.md §3.2."
    exit 1
fi
if [ "${#ADDED[@]}" -gt 1 ]; then
    # Not a rule about tidiness: each extra file is another thing that has to
    # be shown to bite, and one that does not would hide behind one that does.
    echo "FAIL: ${#ADDED[@]} test files were added and this check proves one:"
    printf '       %s\n' "${ADDED[@]}"
    exit 1
fi
NEW_TEST="${ADDED[0]}"
REL_TEST="${NEW_TEST#"$PROJECT_DIR"/}"
echo "the added test: $NEW_TEST"

# ---- 2. anything else under the suite is a refusal ----------------------
mapfile -t OTHER < <(git diff --name-only "$BASE..HEAD" -- "$PROJECT_DIR/$SUITE_DIR/" \
                     | grep -v -F -x "$NEW_TEST" | sort)
if [ "${#OTHER[@]}" -gt 0 ]; then
    echo "FAIL: the change touches the suite beyond the one added test:"
    printf '       %s\n' "${OTHER[@]}"
    exit 1
fi

# ---- 3. it must pass HERE ------------------------------------------------
echo "--- against the change"
"$RUNNER" "$PROJECT_DIR" "$REL_TEST" >/tmp/nb_after.$$ 2>&1
AFTER=$?
if [ "$AFTER" -ne 0 ]; then
    tail -20 /tmp/nb_after.$$
    rm -f /tmp/nb_after.$$
    if [ "$AFTER" -eq 2 ]; then
        echo "FAIL: the runner could not run the added test at all, so nothing"
        echo "      is established about it. Reported as 'could not run' (2)."
        exit 2
    fi
    echo "FAIL: the added test does not pass against its own change"
    exit 1
fi
rm -f /tmp/nb_after.$$
echo "    passes"

# ---- 4. and FAIL against the tree before it ------------------------------
# The pre-change tree is materialised from git rather than by reverting in
# place: this worktree is what everything else in the run is judged against,
# and un-applying a change inside it would leave the run standing on a tree
# nobody checked afterwards.
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/fleet-bite-XXXXXX")"
trap 'stop_services; rm -rf "$SCRATCH"' EXIT

if ! git archive "$BASE" | tar -x -C "$SCRATCH" 2>/dev/null; then
    echo "FAIL: could not materialise $BASE"; exit 2
fi
# The test itself comes from the CHANGE. That is the mutation: the new test
# meets the old code.
mkdir -p "$SCRATCH/$(dirname "$NEW_TEST")"
cp "$NEW_TEST" "$SCRATCH/$NEW_TEST"

echo "--- against the tree before it ($BASE)"
cd "$SCRATCH" || { echo "FAIL: could not enter the scratch tree"; exit 2; }
"$RUNNER" "$PROJECT_DIR" "$REL_TEST" >/tmp/nb_before.$$ 2>&1
BEFORE=$?

# 2 IS NOT 1, AND CONFLATING THEM IS HOW THIS CHECK STOPS WORKING.
#
# What must be established is that the test FAILED here -- that it ran, and
# disagreed with the old code. A runner that never started also exits
# non-zero, and reading that as a failure turns every task in a tree the
# runner cannot start in into a PASS. The scratch tree is a `git archive`, so
# it is missing exactly the gitignored things a runner needs: this is not a
# hypothetical, it is the frontend's default state.
if [ "$BEFORE" -eq 2 ]; then
    tail -20 /tmp/nb_before.$$
    rm -f /tmp/nb_before.$$
    cat <<'EOF'
FAIL: the runner could not run against the pre-change tree, so it is NOT
      established that the added test fails without the change. This is
      reported as 'could not run' (2) and never as a pass -- a non-zero exit
      from a runner that never started is not evidence of anything.
EOF
    exit 2
fi

if [ "$BEFORE" -eq 0 ]; then
    echo "    PASSES — and that is the failure"
    tail -10 /tmp/nb_before.$$
    rm -f /tmp/nb_before.$$
    cat <<'EOF'
FAIL: the added test passes against the code as it was BEFORE the change, so
      it does not test the change. It may be asserting something that was
      already true, or asserting nothing at all.

      A test that cannot fail is not evidence, and a merge gated on it is
      gated on nothing.
EOF
    exit 1
fi
rm -f /tmp/nb_before.$$
echo "    fails, as it must"

echo "PASS: the added test bites — it fails without the change and passes with it"
exit 0
