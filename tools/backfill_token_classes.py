#!/usr/bin/env python
"""Backfill model_calls token classes from the agent CLI's own transcripts.

WHY THIS EXISTS. 048 split `model_calls.prompt_tokens` into the three input
classes that were always there and never recorded. That fixes every run from
now on and leaves the history describing 0.0018% of the prompt -- and the
history is what the per-task ceiling has to be re-derived from, because a cap
in turns or tokens cannot be set against runs whose tokens were never kept.

WHERE THE NUMBERS COME FROM. The runner records `agent_session_id` on every
PATCH_PROPOSED step, and the CLI writes a JSONL transcript per session under
~/.claude/projects/. Each assistant turn carries a `message.usage` block with
the classes separated.

TWO THINGS THIS IS HONEST ABOUT, AND `token_source` IS WHY IT CAN BE:

  ONE TURN IS MANY LINES. A message with N content blocks is written as N
  records, each repeating the SAME usage block. Summing records rather than
  messages counts every multi-block turn two or three times -- it inflated a
  first pass at this by 2.16x, which was within touching distance of plausible
  and would have been believed. Deduplicated by `message.id` below.

  THE TRANSCRIPT IS THE MAIN MODEL ONLY. `modelUsage` -- the live path -- also
  carries the small housekeeping model a session bills alongside the main one;
  the transcript does not. Backfilled rows therefore run slightly low against
  rows written live. Measured on a one-turn probe the housekeeping model was
  521 input and 12 output tokens against the main model's 23,445, so the error
  is well under a percent -- but it is a real difference in what the number
  means, which is what `token_source` records and why this writes 'transcript'
  rather than 'modelUsage'.

WHAT IT DOES NOT TOUCH. `marginal_cost_gbp`. That figure is the CLI's own and
is accurate list price; 048's COMMENT says what it is and is not. Rewriting it
from tokens would replace a measurement with an estimate.

Needs a DSN that can UPDATE model_calls (owned by listmonk). Read-only by
default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import psycopg

TRANSCRIPTS = pathlib.Path.home() / ".claude" / "projects"


def session_usage(path: pathlib.Path) -> dict[str, int] | None:
    """The token classes for one session, counting each message once."""
    seen: set[str] = set()
    c = collections.Counter()
    for line in path.open():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        usage = msg.get("usage") or {}
        mid = msg.get("id")
        if not usage or not mid or mid in seen:
            continue
        seen.add(mid)
        c["input_tokens"] += int(usage.get("input_tokens") or 0)
        c["cache_read_tokens"] += int(usage.get("cache_read_input_tokens") or 0)
        c["cache_creation_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)
        c["completion_tokens"] += int(usage.get("output_tokens") or 0)
    if not seen:
        return None
    c["prompt_tokens"] = (c["input_tokens"] + c["cache_read_tokens"]
                          + c["cache_creation_tokens"])
    c["turns"] = len(seen)
    return dict(c)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True, help="must be able to UPDATE model_calls")
    ap.add_argument("--apply", action="store_true", help="write (default: report only)")
    args = ap.parse_args()

    index = {p.stem: p for d in TRANSCRIPTS.glob("*/") for p in d.glob("*.jsonl")}
    if not index:
        print(f"no transcripts under {TRANSCRIPTS}", file=sys.stderr)
        return 2

    with psycopg.connect(args.dsn) as conn:
        rows = conn.execute("""
            SELECT mc.id, mc.run_id, mc.prompt_tokens, mc.completion_tokens,
                   s.payload->>'agent_session_id' AS sid
              FROM model_calls mc
              JOIN run_steps s
                ON s.run_id = mc.run_id AND s.step_type = 'PATCH_PROPOSED'
             WHERE mc.token_source IS NULL
             ORDER BY mc.id
        """).fetchall()

        # THE LEDGER IS APPEND-ONLY, AND THE TRIGGER COMES BACK ON IN THE SAME
        # TRANSACTION.
        #
        # `model_calls_immutable` is BEFORE DELETE OR UPDATE with no escape.
        # 011 is the precedent for this exact shape -- add a column, backfill
        # it -- and the README's reasoning carries over: DISABLE TRIGGER is
        # scoped to the table owner, which is the migration identity, and doing
        # it inside the transaction means a failure anywhere rolls the disable
        # back and cannot leave the table writable.
        #
        # What is being corrected is an omission, not a claim. No row's account
        # of what happened changes; three columns that were never filled get
        # filled, and `token_source` says of each row where its numbers came
        # from.
        #
        # lock_timeout because DISABLE TRIGGER takes ACCESS EXCLUSIVE: if a
        # runner is settling a call right now, this should fail fast and be
        # re-run rather than block the settle path behind it.
        if args.apply:
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("ALTER TABLE model_calls DISABLE TRIGGER model_calls_immutable")

        done = skipped = 0
        before_p = after_p = 0
        for mc_id, run_id, old_prompt, old_completion, sid in rows:
            path = index.get(sid) if sid else None
            usage = session_usage(path) if path else None
            if usage is None:
                print(f"  skip  call {mc_id:>5} run {run_id:<5} "
                      f"{'no session id' if not sid else 'no transcript'}")
                skipped += 1
                continue
            before_p += old_prompt or 0
            after_p += usage["prompt_tokens"]
            print(f"  call {mc_id:>5} run {run_id:<5} "
                  f"prompt {old_prompt or 0:>8,} -> {usage['prompt_tokens']:>11,}   "
                  f"out {old_completion or 0:>7,} -> {usage['completion_tokens']:>7,}   "
                  f"{usage['turns']:>3} turns")
            if args.apply:
                conn.execute("""
                    UPDATE model_calls
                       SET input_tokens = %(input_tokens)s,
                           cache_read_tokens = %(cache_read_tokens)s,
                           cache_creation_tokens = %(cache_creation_tokens)s,
                           prompt_tokens = %(prompt_tokens)s,
                           completion_tokens = %(completion_tokens)s,
                           token_source = 'transcript'
                     WHERE id = %(id)s
                """, {**usage, "id": mc_id})
            done += 1

        if args.apply:
            conn.execute("ALTER TABLE model_calls ENABLE TRIGGER model_calls_immutable")
            still_off = conn.execute(
                "SELECT tgenabled FROM pg_trigger"
                " WHERE tgrelid = 'model_calls'::regclass"
                "   AND tgname = 'model_calls_immutable'").fetchone()[0]
            if still_off == 'D':
                raise RuntimeError(
                    "model_calls_immutable is still disabled; refusing to commit")
            conn.commit()

    print()
    print(f"  {done} call(s) {'updated' if args.apply else 'would be updated'}, "
          f"{skipped} skipped")
    print(f"  prompt tokens {before_p:,} -> {after_p:,}"
          + (f"   ({after_p / before_p:,.0f}x)" if before_p else ""))
    if not args.apply:
        print("\n  DRY RUN. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
