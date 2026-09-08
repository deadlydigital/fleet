#!/usr/bin/env bash
# The acceptance check, made reachable DURING the run.
#
# Three draft specs died at the same gate for the same reason -- paths written
# from recall rather than read -- and every one of them was a fix of seconds
# that nobody was in a position to make, because the check ran after the agent
# had exited. This is that check, callable by the agent, so the correction
# happens while there is still someone there to make it.
#
# IT IS CAPPED, AND THE CAP IS THE POINT
#
# An agent that can run the gate can also mutate paths until the gate goes
# green, which satisfies the check without knowing what the file is -- a worse
# outcome than the failure, because it passes. So:
#
#   * FLEET_SELFCHECK_MAX invocations, default 3. One to discover, one to
#     confirm the fix, one spare for a second distinct problem. Past that it
#     is not correction, it is search.
#   * every invocation is logged with its verdict, OUTSIDE the worktree, and
#     the runner attaches the log to the PATCH_PROPOSED step. A sequence whose
#     unresolved set CHANGES COMPOSITION rather than shrinking is the
#     signature of mutation, and it is visible to whoever reads the branch.
#   * the runner re-runs the real verification after the agent exits, exactly
#     as before. This never becomes the gate; it is a preview of it.
#
# The agent cannot edit this script: contracts/** is protected, so a change
# here lands in the derived diff and the boundary refuses the branch.
set -uo pipefail

STATE="${FLEET_SELFCHECK_STATE:-}"
MAX="${FLEET_SELFCHECK_MAX:-3}"
CHECK="${FLEET_SELFCHECK_COMMAND:-}"

if [ -z "$CHECK" ]; then
    echo "selfcheck: FLEET_SELFCHECK_COMMAND is not set; the runner sets it" >&2
    exit 2
fi

used=0
if [ -n "$STATE" ] && [ -f "$STATE" ]; then
    used=$(grep -c '^run ' "$STATE" 2>/dev/null || echo 0)
fi

if [ "$used" -ge "$MAX" ]; then
    echo "selfcheck: you have used all $MAX self-checks."
    echo
    echo "That is the cap, and it is deliberate. If the check is still failing,"
    echo "the remaining problem is one to think about rather than to iterate"
    echo "against: read the tree and establish what the path IS, rather than"
    echo "trying another spelling. The runner will run the real check when you"
    echo "exit, and what it says will be recorded either way."
    exit 3
fi

# The runner derives the diff from git after the agent exits; here we have to
# derive it ourselves, and it must match -- untracked files included, because
# a new draft is untracked until the runner commits it.
# -uall, NOT the default. `git status --porcelain` collapses an untracked
# DIRECTORY to `drafts/`, so the check was handed a directory and correctly
# reported "no markdown file in the diff" -- a self-check that fails for a
# reason the agent has no way to act on is worse than none.
# NEWLINE-SEPARATED, because that is what the runner sets and what the check
# splits on. Joining with spaces produced a single element with a trailing
# space, which does not end in ".md", and the check reported "no markdown file
# in the diff" about a diff containing exactly one. A self-check that formats
# its input differently from the gate is testing a different program.
CHANGED=$(git status --porcelain -uall 2>/dev/null | awk '{print $NF}')
if [ -z "${CHANGED//[[:space:]]/}" ]; then
    echo "selfcheck: nothing has changed in the worktree yet; write the draft first."
    exit 2
fi

n=$((used + 1))
echo "selfcheck $n of $MAX, over:"
echo "$CHANGED" | sed 's/^/  /'
echo
out=$(FLEET_CHANGED_FILES="$CHANGED" $CHECK 2>&1)
code=$?
echo "$out"

if [ -n "$STATE" ]; then
    {
      echo "run $n exit=$code"
      echo "  changed: $(echo "$CHANGED" | tr '\n' ' ')"
      echo "$out" | sed 's/^/  /'
    } >> "$STATE"
fi

if [ "$code" -eq 0 ]; then
    echo
    echo "selfcheck: passing. $((MAX - n)) self-check(s) left; you do not have"
    echo "to use them."
fi
exit "$code"
