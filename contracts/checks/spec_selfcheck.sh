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

# THE SAME-SHAPE GUARD.
#
# The check reports EVERY unresolved path at once, so a path appearing in run
# N that was absent from run N-1 was not revealed by fixing something else --
# it was introduced. That is the mutation signature: an agent trying another
# spelling rather than establishing what the file is.
#
# It WARNS and records; it does not refuse. Refusing would block a legitimate
# rewrite, and the terminal check is what enforces correctness either way.
OFFENDING=$(echo "$out" | grep -oE "'[^']+'" | sort -u | tr '\n' ' ')
SHAPE_CHANGED=no
if [ -n "$STATE" ] && [ -f "$STATE" ] && [ -n "${OFFENDING// }" ]; then
    PREV=$(grep '^  offending: ' "$STATE" | tail -1 | sed 's/^  offending: //')
    if [ -n "${PREV// }" ]; then
        for tok in $OFFENDING; do
            case " $PREV " in
                *" $tok "*) ;;
                *) SHAPE_CHANGED=yes ;;
            esac
        done
    fi
fi
if [ "$SHAPE_CHANGED" = yes ]; then
    echo
    echo "selfcheck: WARNING -- this run names a path the previous run did not."
    echo "The check reports every unresolved path at once, so this one was not"
    echo "uncovered by fixing another: it is new. If you are trying spellings,"
    echo "stop and read the tree instead -- reference/PATHS.md lists it. This"
    echo "is recorded on the run either way."
fi

if [ -n "$STATE" ]; then
    {
      echo "run $n exit=$code shape_changed=$SHAPE_CHANGED"
      echo "  offending: $OFFENDING"
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
