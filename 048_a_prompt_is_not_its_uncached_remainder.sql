-- ============================================================================
-- 048_a_prompt_is_not_its_uncached_remainder.sql
--
-- NOT APPLIED BY ANYTHING AUTOMATIC. Apply as the owner: `model_calls` is
-- owned by listmonk and `settle_model_budget` by fleet_owner, and this file
-- alters both.
--
-- WHAT WAS RECORDED, AND WHAT IT WAS
--
-- `model_calls.prompt_tokens` has never held the prompt. runner/cycle.py
-- reads the agent CLI's top-level `usage` block and stores
-- `usage.input_tokens`, which is the UNCACHED REMAINDER of the input and
-- nothing else. The three classes that make up the rest of a prompt --
-- `cache_read_input_tokens`, `cache_creation_input_tokens`, and the TTL split
-- inside the latter -- were read by nothing and stored nowhere.
--
-- Measured over the 88 agent runs of September 2026:
--
--     prompt_tokens as recorded            5,626
--     uncached input, summed               5,636
--     cache reads                    295,720,310
--     cache writes (all 1h)           10,246,814
--     ACTUAL PROMPT VOLUME           305,972,760      54,385x the recorded figure
--
-- The number was not approximately right. It described 0.0018% of the prompt,
-- and it did so silently, because a plausible small integer in an int column
-- looks like a measurement.
--
-- WHY THE FALLBACK THAT WOULD HAVE CAUGHT THIS NEVER RAN
--
-- runner/cycle.py already contains correct code. `_model_usage_totals()` sums
-- `inputTokens + cacheReadInputTokens + cacheCreationInputTokens` across every
-- model a run billed, and has since it was written. It is guarded by
--
--     if not call.get("prompt_tokens") and not call.get("completion_tokens"):
--
-- so it runs ONLY when the top-level block is empty -- which happens only on a
-- budget-exhausted run. Every ordinary run took the wrong path. The good
-- accounting was reachable exactly when the run had already failed.
--
-- WHAT THE CLI ACTUALLY REPORTS, CHECKED RATHER THAN ASSUMED
--
-- `--output-format json` carries a `modelUsage` map, one entry per model a
-- session billed -- including the small housekeeping model, which bills
-- alongside the main one and which a total that omits it does not describe:
--
--     "claude-opus-5[1m]": {"inputTokens": 2, "outputTokens": 4,
--                           "cacheReadInputTokens": 16634,
--                           "cacheCreationInputTokens": 6809,
--                           "costUSD": 0.076517, "canonicalModel": "claude-opus-5"}
--
-- That is the source this migration is built for, and it is the one the
-- runner now reads first rather than last.
--
-- WHAT IS DELIBERATELY NOT RECORDED: THE CACHE-WRITE TTL SPLIT
--
-- A 1-hour cache write is priced at 2x input and a 5-minute write at 1.25x, so
-- repricing a run exactly needs the split. `modelUsage` does not carry it --
-- only the per-turn `message.usage.cache_creation` block does, and that lives
-- in the CLI transcript rather than in the result the runner parses.
--
-- A column that could only ever be populated by the backfill, and would sit
-- NULL on every row written from here on, is worse than no column: it reads as
-- a measurement that stopped being taken. So cache writes are one number, and
-- the split stays recoverable from the transcript for anyone who needs to
-- reprice. Every write in September was 1h; that is an observation about this
-- workload, not a property to hard-code.
--
-- WHAT marginal_cost_gbp IS, NOW THAT IT CAN BE CHECKED
--
-- It is ACCURATE and it is NOTIONAL, and both halves need saying.
--
-- Accurate: recomputing September from the transcripts at published rates --
-- cache reads at 0.1x input, 1h writes at 2x, output at full -- gives $314.56
-- against the CLI's own $316.49, agreeing to 0.6%. The CLI's arithmetic is
-- list price done correctly, cache discounts included.
--
-- Notional: nothing billed it. `~/.claude/.credentials.json` carries
-- `subscriptionType = max`, there is no ANTHROPIC_API_KEY in .env, in the
-- environment, or in any unit under systemd/, and runner/agent.py invokes a
-- bare `claude`. The runs authenticate against a Claude Max subscription,
-- where usage is metered by rate limit rather than billed per token. The
-- provider's month-to-date API spend over the same period was $80.41, which
-- this usage is not in.
--
-- So the column keeps its value and loses its name's implication. It is what
-- the work WOULD have cost on the API, which is a real and useful quantity --
-- it is the only cross-model comparable this host can compute -- and it is not
-- money anybody paid. The COMMENT below says so, because the next person to
-- sum it will otherwise sum it as money, which is what 014's ceiling does.
--
-- Target: PostgreSQL 15+, same floor as 001.
-- ============================================================================

\set ON_ERROR_STOP on

-- ONE TRANSACTION, because 011 half-applied and the README keeps the reason:
-- ON_ERROR_STOP with psql's autocommit leaves every statement before the
-- failure in place. Every statement here is idempotent as well, so a retry
-- after a rolled-back attempt is a no-op rather than a second column.
BEGIN;

-- ========================================================= 1. THE CLASSES

ALTER TABLE model_calls
    ADD COLUMN IF NOT EXISTS input_tokens          int,
    ADD COLUMN IF NOT EXISTS cache_read_tokens     int,
    ADD COLUMN IF NOT EXISTS cache_creation_tokens int,
    ADD COLUMN IF NOT EXISTS token_source          text;

COMMENT ON COLUMN model_calls.input_tokens IS
  'Uncached input tokens. This is what prompt_tokens used to hold ALONE, '
  'which is why prompt_tokens read 54,000x low -- see 048.';
COMMENT ON COLUMN model_calls.cache_read_tokens IS
  'Input served from cache, billed at 0.1x input on the API. Dominates every '
  'agent run: 96.6% of September''s prompt volume.';
COMMENT ON COLUMN model_calls.cache_creation_tokens IS
  'Input written to cache. NOT split by TTL: modelUsage does not carry the '
  'split and only the transcript does. 1h bills at 2x input, 5m at 1.25x, so '
  'an exact reprice needs the transcript. See 048.';
COMMENT ON COLUMN model_calls.token_source IS
  'Where the token counts came from: modelUsage (the CLI''s per-model map, the '
  'live path), transcript (backfilled from the session JSONL), or usage (the '
  'top-level block -- uncached remainder only, the defect 048 fixed). NULL on '
  'rows written before 048 and never corrected.';

-- prompt_tokens KEEPS ITS NAME AND GAINS ITS MEANING.
--
-- Renaming it would be the tidier change and the wrong one: console/queries.py
-- and 001's own INSERT both name it, and a rename turns a column that is
-- merely wrong into a column that is missing. It becomes the sum of the three
-- input classes -- which is what every reader has always believed it was.
COMMENT ON COLUMN model_calls.prompt_tokens IS
  'TOTAL input: input_tokens + cache_read_tokens + cache_creation_tokens. '
  'Before 048 it held the uncached remainder only. Rows with input_tokens '
  'NULL predate the fix and were never corrected; the CHECK below does not '
  'judge them.';

-- THE CONSTRAINT IS WHAT STOPS THIS RECURRING.
--
-- The defect was not that the arithmetic was hard. It was that nothing
-- compared the part to the whole, so a prompt_tokens that omitted 96.6% of the
-- prompt satisfied every rule the schema had. It cannot now.
--
-- Scoped to rows that carry the parts, so the pre-048 rows are left as the
-- record of what was recorded rather than retroactively rejected -- and so
-- this file needs no NOT VALID / VALIDATE dance.
ALTER TABLE model_calls
    DROP CONSTRAINT IF EXISTS model_calls_prompt_is_the_sum;
ALTER TABLE model_calls
    ADD CONSTRAINT model_calls_prompt_is_the_sum CHECK (
        input_tokens IS NULL
        OR prompt_tokens = input_tokens
                         + coalesce(cache_read_tokens, 0)
                         + coalesce(cache_creation_tokens, 0));

ALTER TABLE model_calls
    DROP CONSTRAINT IF EXISTS model_calls_token_source_known;
ALTER TABLE model_calls
    ADD CONSTRAINT model_calls_token_source_known CHECK (
        token_source IS NULL
        OR token_source IN ('modelUsage', 'transcript', 'usage'));

COMMENT ON COLUMN model_calls.marginal_cost_gbp IS
  'NOTIONAL list price, not money billed. The agent CLI''s own total_cost_usd '
  'converted at runner.yaml''s usd_to_gbp -- published rates with cache '
  'discounts applied, verified to 0.6% against a recomputation from the '
  'transcripts. NOTHING BILLED IT: the runs authenticate against a Claude Max '
  'subscription (see 048), which meters by rate limit rather than by token. '
  'Summing this as spend describes an account nobody holds.';

-- ========================================================= 2. THE WRITER

-- Unchanged except for the four new fields, and they are read with ->> so a
-- caller that does not send them writes NULL rather than failing. That is the
-- property that lets this migration be applied before the runner is updated,
-- in either order, with no window in which settlement breaks.
CREATE OR REPLACE FUNCTION settle_model_budget(p_token uuid, p_actual numeric, p_call jsonb)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE res public.budget_reservations; mc_id bigint;
BEGIN
    IF p_actual < 0 THEN RAISE EXCEPTION 'actual cost may not be negative'; END IF;

    UPDATE public.budget_reservations SET status = 'SETTLED', settled_at = now()
    WHERE id = p_token AND status = 'HELD'
    RETURNING * INTO res;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no held reservation % (already settled, voided, or unknown)',
            p_token;
    END IF;

    IF p_actual > res.estimate_gbp THEN
        RAISE EXCEPTION 'actual % exceeds reserved upper bound %',
            p_actual, res.estimate_gbp;
    END IF;

    UPDATE public.runs SET committed_gbp = committed_gbp - (res.estimate_gbp - p_actual)
    WHERE id = res.run_id;

    INSERT INTO public.model_calls (
        run_id, reservation_id, provider, model, purpose, started_at, completed_at,
        prompt_tokens, completion_tokens, load_duration_ms, prompt_eval_duration_ms,
        eval_duration_ms, total_duration_ms, marginal_cost_gbp, ok,
        input_tokens, cache_read_tokens, cache_creation_tokens, token_source)
    VALUES (
        res.run_id, p_token,
        p_call->>'provider', p_call->>'model', p_call->>'purpose',
        (p_call->>'started_at')::timestamptz, (p_call->>'completed_at')::timestamptz,
        (p_call->>'prompt_tokens')::int, (p_call->>'completion_tokens')::int,
        (p_call->>'load_duration_ms')::int, (p_call->>'prompt_eval_duration_ms')::int,
        (p_call->>'eval_duration_ms')::int, (p_call->>'total_duration_ms')::int,
        p_actual, coalesce((p_call->>'ok')::bool, true),
        (p_call->>'input_tokens')::int, (p_call->>'cache_read_tokens')::int,
        (p_call->>'cache_creation_tokens')::int, p_call->>'token_source')
    RETURNING id INTO mc_id;
    RETURN mc_id;
END; $$;

ALTER FUNCTION settle_model_budget(uuid, numeric, jsonb) OWNER TO fleet_owner;

COMMIT;
