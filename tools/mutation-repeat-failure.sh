#!/bin/bash
# Does tests/test_repeat_failure.py actually bite?
#
#     ./tools/mutation-repeat-failure.sh
#
# A suite that passes against the fix AND against the defect is a suite that is
# not testing the fix. This breaks the identity and the outcome rule one way at
# a time, reruns the module, and REQUIRES A FAILURE each time. A mutation that
# survives is printed as SURVIVED and the script exits non-zero.
#
# WHY THIS EXISTS HERE AND NOT AS A TEST. The mutations change a MIGRATION
# FILE, and tests/conftest.py builds its template database by globbing the
# migrations — so the only way to run the suite against a mutated predicate is
# to mutate the file on disk and rebuild. A pytest that did that to its own
# schema mid-session would be arranging the thing it is measuring.
#
# The tree is restored on exit, including on Ctrl-C, and the script refuses to
# start if the files it will edit are already modified — a restore that
# overwrote somebody's uncommitted work would be a worse defect than the one
# this is checking for.
set -uo pipefail
cd "$(dirname "$0")/.."

SQL=027_repeat_failure_identity.sql
PY=console/work_key.py
RANK=console/rank.py
TARGETS=("$SQL" "$PY" "$RANK")
SUITE=tests/test_repeat_failure.py

if ! git diff --quiet -- "${TARGETS[@]}"; then
    echo "REFUSING: ${TARGETS[*]} have uncommitted changes." >&2
    echo "This script edits them in place and restores from git on exit;" >&2
    echo "running it now would discard work that is not committed." >&2
    exit 2
fi

restore() { git checkout -- "${TARGETS[@]}"; }
trap restore EXIT INT TERM

PASS=0
SURVIVED=0

# mutate <name> <file> <python-replacement-expression>
#
# The replacement is a Python literal pair applied with str.replace, so a
# mutation that no longer matches the source is reported rather than silently
# doing nothing — a no-op mutation that "fails to survive" would be this
# script lying in the safe-looking direction.
mutate() {
    local name="$1" file="$2" old="$3" new="$4"
    restore
    python3 - "$file" "$old" "$new" <<'EOF'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path).read()
if old not in s:
    print(f"NO-OP: the mutation text is not in {path}", file=sys.stderr)
    sys.exit(3)
open(path, "w").write(s.replace(old, new, 1))
EOF
    if [ $? -ne 0 ]; then
        echo "  ERROR  $name — the mutation no longer applies to the source"
        SURVIVED=$((SURVIVED + 1))
        return
    fi
    if .venv/bin/python -m pytest "$SUITE" -q -x >/tmp/mutation-$$.log 2>&1; then
        echo "  SURVIVED  $name"
        echo "            the suite passed against the broken predicate"
        SURVIVED=$((SURVIVED + 1))
    else
        local first
        first=$(grep -m1 '^FAILED' /tmp/mutation-$$.log | sed 's/^FAILED //')
        echo "  killed    $name"
        echo "            by ${first:-a failing test}"
        PASS=$((PASS + 1))
    fi
    rm -f /tmp/mutation-$$.log
}

echo "Mutating the repeat-failure identity and count predicate."
echo

# ---- the identity ----------------------------------------------------------

mutate "022's identity: key on the title again" "$SQL" \
    "SELECT coalesce(c.work_key,
                    'title::' || c.repo || '#' || lower(btrim(c.title)))" \
    "SELECT 'title::' || c.repo || '#' || lower(btrim(c.title))"

mutate "a NULL key identifies as NULL instead of falling back" "$SQL" \
    "SELECT coalesce(c.work_key,
                    'title::' || c.repo || '#' || lower(btrim(c.title)))" \
    "SELECT c.work_key"

mutate "resolve() drops the word boundary" "$PY" \
    'and (r.startswith(topic + "-") or topic.startswith(r + "-"))' \
    'and (r.startswith(topic) or topic.startswith(r))'

mutate "resolve() picks the longest instead of refusing an ambiguity" "$PY" \
    "return hits.pop() if len(hits) == 1 else None" \
    "return max(hits, key=len) if hits else None"

mutate "topic_of() keeps the band prefix" "$PY" \
    'return slug(_BAND_PREFIX_RE.sub("", str(section or "").strip()))' \
    'return slug(str(section or "").strip())'

# ---- the outcome rule ------------------------------------------------------

mutate "022's outcome rule: every FAILED row counts" "$SQL" \
    "       AND task_was_unsuccessful_attempt(t.id);" \
    "       AND t.status = 'FAILED';"

mutate "a missing verification verdict is treated as a pass" "$SQL" \
    "       AND coalesce(task_verification_result(t.id), 'NONE') <> 'PASS'" \
    "       AND coalesce(task_verification_result(t.id), 'PASS') <> 'PASS'"

# ---- the count and the stop ------------------------------------------------

mutate "one task counted once per candidate that reaches it" "$SQL" \
    "SELECT count(DISTINCT t.id)::int" \
    "SELECT count(t.id)::int"

mutate "the gate fires above the stop instead of at it" "$RANK" \
    "if prior_failures >= REPEAT_FAILURE_STOP:" \
    "if prior_failures > REPEAT_FAILURE_STOP:"

echo
echo "$PASS mutation(s) killed, $SURVIVED survived."
[ "$SURVIVED" -eq 0 ] || exit 1
