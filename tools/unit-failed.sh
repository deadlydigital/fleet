#!/bin/sh
# Say that a fleet unit failed. Invoked by OnFailure= on every fleet unit.
#
# WHY THIS IS SHELL, AND WHY IT IMPORTS NOTHING
# ---------------------------------------------
# The most likely reason a fleet unit fails is that the fleet code on disk is
# broken or missing -- which is precisely what happened on 2026-09-09, when a
# branch switch removed run_brief.py and two detector modules and three timers
# began failing in silence. A handler written in Python against this
# repository would have had the exact failure it exists to report.
#
# So: POSIX sh, and nothing from /home/ubuntu/fleet except `.env`. `.env` is
# untracked, so no git operation can remove it -- unlike every module in the
# tree beside it.
#
# WHY IT IS INSTALLED OUTSIDE THE WORKING TREE
# --------------------------------------------
# For the same reason. The copy that RUNS lives at /usr/local/lib/fleet/;
# this file is its source of truth, and
# tests/test_unit_failure_notice.py asserts the two have not drifted. A
# notifier that a `git checkout` can delete is not a notifier.
#
# IT NEVER EXITS NON-ZERO
# -----------------------
# A failing failure-handler is a second silent failure, and it would be the
# one nobody is looking for. Every step tolerates its own failure and the
# script ends with `exit 0`. The journal is the backstop: everything it does,
# it also logs.
set -u

UNIT="${1:-unknown}"
ENV_FILE=/home/ubuntu/fleet/.env
LOG=/var/log/fleet/unit-failures.log
STATE_DIR=/run/fleet-unit-failed
# One Telegram message per unit per hour. fleet-sentry fires every 15 minutes;
# unthrottled it would have sent 12 messages on the morning of 2026-09-09, and
# 12 messages is not 12 times the signal of one -- it is a muted chat.
# The log below is NOT throttled, so the record stays complete.
THROTTLE_SECONDS=3600

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
mkdir -p "$STATE_DIR" 2>/dev/null || true

WHEN=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo unknown)
RESULT=$(systemctl show "$UNIT" -p Result --value 2>/dev/null || echo unknown)
STATUS=$(systemctl show "$UNIT" -p ExecMainStatus --value 2>/dev/null || echo unknown)
TAIL=$(journalctl -u "$UNIT" -n 6 --no-pager -o cat 2>/dev/null \
       | tr '\n\t' '  ' | cut -c1-400)

logger -t fleet-unit-failed "$UNIT result=$RESULT status=$STATUS" 2>/dev/null || true
printf '%s\t%s\tresult=%s\tstatus=%s\t%s\n' \
       "$WHEN" "$UNIT" "$RESULT" "$STATUS" "$TAIL" >> "$LOG" 2>/dev/null || true

# ---- throttle -------------------------------------------------------------
# In /run, so a reboot clears it: after a reboot every unit deserves to be
# heard again.
STAMP="$STATE_DIR/$(printf '%s' "$UNIT" | tr -c 'a-zA-Z0-9' '_')"
NOW=$(date +%s 2>/dev/null || echo 0)
if [ -f "$STAMP" ]; then
    LAST=$(cat "$STAMP" 2>/dev/null || echo 0)
    [ -z "$LAST" ] && LAST=0
    if [ $((NOW - LAST)) -lt "$THROTTLE_SECONDS" ]; then
        logger -t fleet-unit-failed "throttled (logged, not sent): $UNIT" 2>/dev/null || true
        exit 0
    fi
fi
printf '%s' "$NOW" > "$STAMP" 2>/dev/null || true

# ---- the ping -------------------------------------------------------------
# Its own bot, the same one the morning brief uses. Read straight out of .env
# with sed rather than sourcing it: `.env` holds database URLs and secrets for
# the whole fleet, and a handler that sources it would put all of them in the
# environment of a process that only needs two.
TOKEN=$(sed -n 's/^FLEET_TELEGRAM_BOT_TOKEN=//p' "$ENV_FILE" 2>/dev/null \
        | tr -d "\"'" | head -1)
CHAT=$(sed -n 's/^FLEET_TELEGRAM_CHAT_ID=//p' "$ENV_FILE" 2>/dev/null \
       | tr -d "\"'" | head -1)

if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
    logger -t fleet-unit-failed \
        "no FLEET_TELEGRAM_BOT_TOKEN/CHAT_ID in $ENV_FILE; logged only" 2>/dev/null || true
    exit 0
fi

TEXT="FLEET UNIT FAILED

$UNIT
result=$RESULT status=$STATUS
$WHEN

$TAIL

journalctl -u $UNIT -n 50"

curl -s -S --max-time 15 -o /dev/null \
     -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
     --data-urlencode "chat_id=$CHAT" \
     --data-urlencode "text=$TEXT" \
     --data-urlencode "disable_web_page_preview=true" \
     2>&1 | logger -t fleet-unit-failed 2>/dev/null || true

exit 0
