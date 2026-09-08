"""The morning ping: one Telegram message when the brief lands.

WHAT IT SAYS, AND WHY THAT AND NOTHING ELSE
-------------------------------------------
What is blocking you, how many, and a link. Not the brief -- the brief is a
file and a page, and a phone notification that tried to be either would be
neither. The ping's whole job is to answer "do I need to open the console this
morning", and on most mornings the answer is no and it should say so in one
line without being opened.

So the message is short by design and the page is where detail lives. If the
ping ever needs a second screenful, the thing to change is the page.

ITS OWN BOT
-----------
`FLEET_TELEGRAM_BOT_TOKEN` and `FLEET_TELEGRAM_CHAT_ID`, and NOT Punter
Insight's. Two reasons, and the second is the one that matters:

  * a shared bot means one revoked token takes out both, and the revocation
    will happen for a reason belonging to whichever product is not the one you
    are trying to fix at the time
  * PI's bot talks to PI's users. Fleet's ping is operational -- queue depths,
    review counts, a link to an internal console. A misrouted message from a
    shared bot puts internal state in front of a customer, and there is no
    mechanism here that would catch it: chat ids are integers, and a wrong one
    is a successful send.

THE BRIEF MUST NOT DEPEND ON THIS, AND THE DEPENDENCE IS REMOVED STRUCTURALLY
----------------------------------------------------------------------------
Not by being careful. By ordering and by construction:

  1. the ping is sent AFTER run_pass() has returned, so the brief_runs row is
     committed and the file is on disk before anything is sent
  2. notify() catches every exception, including ones raised while building
     the message, and returns a result instead of raising
  3. the HTTP call carries a timeout, so an unreachable Telegram delays the
     unit by seconds and cannot hang it -- fleet-brief.service allows 600s and
     the worst case here is a small fraction of that
  4. run_brief.py's exit code is computed before notify() is called and is not
     changed by it, so `SuccessExitStatus=0` still means "the brief was
     written" and never "the ping went out"

WHAT HAPPENS WHEN THE SEND FAILS
--------------------------------
The brief is written, the file is on disk, the console page is current, and the
unit exits 0. The failure is logged at ERROR with the reason and the HTTP
status, so `journalctl -u fleet-brief` has it.

Nothing retries it later and nothing alerts on it, and that is a real gap
rather than an oversight: the honest detection path for a missing ping is that
you did not get one. It degrades to the state that existed before this module
-- you open the console yourself -- which is why it is acceptable for the ping
to be best-effort and would not be acceptable for the brief.

A ping that is CONFIGURED and failing is different from one that was never
configured, and the log distinguishes them: an unset token logs once at INFO
and is not an error, because a box with no bot is a choice.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx
import psycopg
from psycopg.rows import dict_row

from detectors import config

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"

#: Two attempts, not five. The message is worth one retry over a dropped
#: connection and is not worth holding the unit open for a Telegram outage --
#: it is superseded by tomorrow's ping and by the page, both of which are
#: already correct.
ATTEMPTS = 2
TIMEOUT_SECONDS = 10.0


@dataclass
class Result:
    sent: bool
    reason: str = ""
    text: str = ""
    #: True when no bot is configured. Not a failure: a box with no bot is a
    #: choice, and logging it as an error would train the reader to ignore
    #: errors from this unit.
    unconfigured: bool = False


# ---------------------------------------------------------------------------
# What is blocking, read as the identity the brief already reads with
# ---------------------------------------------------------------------------

#: Deliberately the SAME shapes the morning page uses, so the ping and the page
#: cannot disagree about how many things are waiting. Read as
#: dd_detector_login: 012 and 013 already grant it SELECT on tasks and
#: candidates, so this needs no new grant and no new credential.
BLOCKERS_SQL = """
    SELECT
      (SELECT count(*) FROM tasks
        WHERE status = 'READY_FOR_REVIEW'
          AND acceptance_contract->>'work_type' = 'draft_spec') AS specs,
      (SELECT count(*) FROM tasks
        WHERE status = 'READY_FOR_REVIEW'
          AND acceptance_contract->>'work_type' <> 'draft_spec') AS branches,
      (SELECT count(*) FROM candidates
        WHERE disposition IN ('PENDING','NOT_NOW'))              AS candidates,
      (SELECT count(*) FROM tasks WHERE status = 'QUEUED')       AS queued
"""


def read_blockers(fleet_dsn: str) -> Dict[str, int]:
    with psycopg.connect(fleet_dsn, row_factory=dict_row) as conn:
        conn.read_only = True
        row = conn.execute(BLOCKERS_SQL).fetchone() or {}
    return {k: int(v or 0) for k, v in row.items()}


def credit_line(fleet_dsn: str) -> Optional[str]:
    """One line about the month's ceiling, when it is shut.

    Only when it is UNCOMPUTED, because that state stops every task insert --
    it is the one ceiling whose absence means nothing can be queued at all, so
    it belongs in a message whose purpose is "do I need to act this morning".
    A healthy pool is a number for the page, not for a notification.
    """
    try:
        with psycopg.connect(fleet_dsn, row_factory=dict_row) as conn:
            conn.read_only = True
            row = conn.execute("SELECT * FROM fleet_month_credit()").fetchone()
    except Exception as exc:                                  # noqa: BLE001
        log.warning("could not read the credit position for the ping: %s", exc)
        return None
    if row and row.get("status") == "UNCOMPUTED":
        return ("No credit pool reading for this month — nothing can be "
                "queued until one is recorded.")
    return None


# ---------------------------------------------------------------------------
# The message
# ---------------------------------------------------------------------------


def compose(blockers: Dict[str, int], console_url: Optional[str],
            extra: Optional[List[str]] = None) -> str:
    """The message: counts and a link, no titles.

    "What is blocking, how many, and a link." Counts rather than titles because
    the ping answers one question -- do I need to open this -- and a list of
    five titles on a lock screen answers it no better than a number while being
    four lines longer. The titles are one tap away.

    Plain text, never Markdown, and that is deliberate: `parse_mode` would make
    the message breakable by any text that reaches it. Nothing user-written is
    interpolated TODAY, so this costs nothing today; it means the first time
    somebody adds a title here it cannot silently swallow half the message. A
    bare URL autolinks without markup anyway, so the markup buys nothing.
    """
    specs = blockers.get("specs", 0)
    branches = blockers.get("branches", 0)
    cands = blockers.get("candidates", 0)

    lines: List[str] = []
    bullets: List[str] = []
    if branches:
        bullets.append(f"• {branches} branch{'' if branches == 1 else 'es'} "
                       f"ready for review")
    if specs:
        bullets.append(f"• {specs} drafted spec{'' if specs == 1 else 's'} "
                       f"awaiting your approval")
    if cands:
        bullets.append(f"• {cands} candidate{'' if cands == 1 else 's'} "
                       f"awaiting a tick")
    for line in extra or []:
        bullets.append(f"• {line}")

    if bullets:
        lines.append(f"Fleet — {len(bullets)} thing"
                     f"{'' if len(bullets) == 1 else 's'} waiting on you")
        lines.append("")
        lines.extend(bullets)
    else:
        # The ordinary morning, and it must read as an answer rather than as a
        # message that failed to say anything. Same sentence as the page.
        lines.append("Fleet — nothing is waiting on you.")
        queued = blockers.get("queued", 0)
        lines.append("")
        lines.append(f"{queued} task{'' if queued == 1 else 's'} queued."
                     if queued else
                     "Nothing queued, because nothing has been approved.")

    if console_url:
        lines.append("")
        lines.append(console_url)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The send
# ---------------------------------------------------------------------------


def send(text: str, *, token: Optional[str] = None,
         chat_id: Optional[str] = None) -> Result:
    """Post one message. Never raises."""
    token = token or config.get("FLEET_TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or config.get("FLEET_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return Result(sent=False, unconfigured=True, text=text,
                      reason="FLEET_TELEGRAM_BOT_TOKEN / "
                             "FLEET_TELEGRAM_CHAT_ID are not set")

    last = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = httpx.post(API.format(token=token),
                           json={"chat_id": chat_id, "text": text,
                                 "disable_web_page_preview": True},
                           timeout=TIMEOUT_SECONDS)
            if r.status_code == 200:
                return Result(sent=True, text=text)
            # Telegram puts the useful part in the body, not the status.
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:                              # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        if attempt < ATTEMPTS:
            log.warning("telegram ping attempt %d failed (%s), retrying",
                        attempt, last)
    return Result(sent=False, reason=last, text=text)


def notify(fleet_dsn: str, *, dry_run: bool = False) -> Result:
    """Build and send the morning ping. NEVER raises, whatever happens.

    The blanket except is the point of the function rather than laziness: this
    is called after the brief is already written, and any exception escaping
    here would turn a successful brief into a failed unit -- which is exactly
    the dependence the module exists to prevent.
    """
    try:
        blockers = read_blockers(fleet_dsn)
        extra = [line for line in [credit_line(fleet_dsn)] if line]
        text = compose(blockers, config.get("FLEET_CONSOLE_URL"), extra)
    except Exception as exc:                                  # noqa: BLE001
        log.error("morning ping NOT sent: could not build it (%s: %s). "
                  "The brief is unaffected.", type(exc).__name__, exc)
        return Result(sent=False, reason=f"compose failed: {exc}")

    if dry_run:
        return Result(sent=False, text=text, reason="dry run")

    try:
        result = send(text)
    except Exception as exc:                                  # noqa: BLE001
        # send() is written not to raise, and this catches it anyway. The
        # module's contract with run_brief.py is "never raises", and a contract
        # that holds only while a second function keeps its own promise is one
        # promise away from turning a written brief into a failed unit.
        log.error("morning ping FAILED unexpectedly (%s: %s). The brief is "
                  "unaffected.", type(exc).__name__, exc)
        return Result(sent=False, reason=f"{type(exc).__name__}: {exc}",
                      text=text)

    if result.sent:
        log.info("morning ping sent")
    elif result.unconfigured:
        log.info("morning ping not sent: %s. This is a configuration choice, "
                 "not a failure.", result.reason)
    else:
        log.error("morning ping FAILED: %s. The brief was written and the "
                  "console is current; nothing retries this and nothing "
                  "alerts on it, so the way you find out is that you did not "
                  "get a message.", result.reason)
    return result
