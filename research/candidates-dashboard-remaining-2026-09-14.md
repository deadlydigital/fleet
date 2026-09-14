# What is left in the dashboard endpoint after the LATERAL rewrite

Measured 14 September 2026, 19:20–19:35 UTC, against the running API on
`analytics_2` (2,887,637 orders, 4,546,466 order items), box at load 0.23–0.72.
Platform at `fd20133`, which is task 100 merged.

**Every figure here states its window.** That is not decoration: this thread
produced two wrong conclusions in one day from timings quoted without one. See
`specs/neither-half-works-alone.md`, "State the window".

## What the endpoint costs now

`GET /api/analytics/dashboard`, tenant 2, warm, over loopback: **1.71 s** at a
30-day window, 2.88 s at 90 days, 4.72 s at 180. Every statement timed in
process — 48 per request — accounts for it:

| | 30 days | 180 days |
|---|---|---|
| `_query_period_stats` × 2 | 622 ms | 2,675 ms |
| **`top_products`** | **619 ms** | **1,251 ms** |
| `_feed_health` | 115 ms | 147 ms |
| trends | 102 ms | 451 ms |
| customers totals | 84 ms | 83 ms |
| **36 × reconciliation breakdown** | **89 ms** | **96 ms** |
| six others | 10 ms | 4 ms |
| SQL | 1,666 ms | 4,717 ms |
| not SQL | 25 ms | 23 ms |

**Corrected 14 Sep 19:50.** These are medians of three warm passes. The first
version of this table, and the `fleet-candidates` block below, were written
from one pass per window: they give `top_products` as 660 ms at 30 days and
1,370 ms at 180, against medians of 619 ms and 1,251 ms. **Batch 17 carries the
single-pass figures and is left as it was loaded** — a batch is the record of
what was measured when it was loaded, and there is no path that edits one,
correctly. Nothing about either candidate changes: `top_products` is still the
largest single statement on the page, and the EXPLAIN ANALYZE below — 958 ms,
4,546,466 rows scanned — is a separate measurement that is unaffected.

The rewrite did what it was for: `_query_period_stats` is 260 ms isolated at
30 days against 2,711 ms for the form it replaced. Two things are left that
are worth naming, and neither is urgent at 1.71 s.

## Daily — `top_products` reads every order item to find a month's worth

It is now the largest single statement on the page. `EXPLAIN (ANALYZE,
BUFFERS)` at the 30-day window:

    Limit                                    958.853 ms
      Sort  (top-N heapsort)
        GroupAggregate                       105 rows out
          Gather Merge                       104,840 rows
            Parallel Hash Join               34,947 rows × 3 loops
              Parallel Seq Scan on order_items
                                             1,515,489 rows × 3 loops
              Parallel Hash
                Parallel Index Scan using ix_analytics_orders_created
                                             23,571 rows × 3 loops
    Buffers: shared hit=39356 read=45271   I/O Timings: shared read=243.917

The orders side is already indexed and costs 25 ms. The order-items side reads
**all 4,546,466 rows** to keep the 104,840 that belong to the window's orders
— 43 rows read for every one kept, 45,271 buffers off disk, 244 ms of it in
I/O. `ix_analytics_order_items_order` exists on `order_id` and the planner does
not use it: a hash join over the whole table beats 23,571 index probes on its
estimates.

**What is NOT established.** Whether any index changes that plan. The shape is
different from the one this thread already solved — there is no per-group
`LIMIT` to exploit, the aggregate genuinely needs every matching item — so the
`LATERAL` answer does not transfer, and an index on `(order_id)` already
exists and is declined. A covering index on `(order_id) INCLUDE (wc_product_id,
product_name, total, quantity)` is the obvious thing to price and it is
**unmeasured**; `hypopg` can model it, and the control discipline from
`specs/neither-half-works-alone.md` applies — the last time this looked
obvious, the index changed no plan at all.

Any index here is a migration, so it belongs under
`contracts/dd-index-migration.yaml` and deploys by hand.

## Daily — the dashboard runs one query per manifest ever received

36 executions of one statement per request, 2.5 ms each, 91 ms total. The count
is 36 at both the 30-day and 180-day window, so it does not track what was
asked for. It tracks `analytics_2.reconciliation_manifests`, which holds
exactly 36 rows, all at `day` grain.

`_platform_breakdown` (`api/analytics/services/reconciliation.py:415`) is
called once per period from `verify_period` at `:618`, and the loop above it
iterates **every manifest with no window bound**:

    for m in manifests:
        v = verify_period(db, tenant_id, m, coverage, tenant_timezone, settle_hours)

The code's own comment nearby anticipates the growth — "~40 rows for a two-year
store instead of ~730" — and 730 is the day-grain number. At 2.5 ms a query
that is ~1.8 s per dashboard request, arriving one manifest at a time, on a
page that is 1.71 s today.

**What is NOT established.** Whether the loop can be bounded by the window
without changing what the verification block means. It may not be: the block
answers "is what we were told complete?", which is a question about coverage
over all history rather than over the window, and narrowing it could silently
turn an unverified period into an unmentioned one. That is the question this
work has to answer first, and it is a correctness question, not a performance
one. Folding 36 single-period queries into one grouped query is the other
shape, and it changes no semantics.

```fleet-candidates
source:
  document: research/candidates-dashboard-remaining-2026-09-14.md
  sha: d69723f
  repo: fleet

ordering: unranked

objectives_considered: >
  Both rows are dd-trustworthy rather than cost-discipline, and the distinction
  is worth stating because the cheap reading is the wrong one. Neither costs
  money: the queries run on a box that is already paid for and neither adds a
  request, a fixed cost or a dependency, so cost-discipline is untouched by
  both. What they affect is whether a merchant opens the page, which is the
  correctness-of-service framing dd-trustworthy exists for and the same one
  task 100 was filed under. I weighed dd-feature-parity and rejected it: no
  Metorik row asks for either, no gap closes, and filing them as parity would
  rank them against seven rows that add reports a merchant cannot get at all
  today, which would be the wrong trade. dd-first-revenue does not apply —
  this is HIB's own store. I also record that at 1.71 s the page is no longer
  slow, so neither row is urgent, and saying so is part of the ranking rather
  than an argument against filing them.

unasked_question: >
  Nobody has asked what window merchants actually use, and nothing here could
  answer it. The dashboard's cost is a function of the window and ranges from
  0.36 s at a single day to 15.8 s at a year, so which of those a real reader
  picks decides whether either of these rows matters at all — and DD holds no
  event, session or page-view table on any schema, so the distribution of
  requested windows has never been observed. The second unasked question is
  whether anyone reads the reconciliation block on the dashboard at all, which
  would decide whether its 36 queries are worth one line of work or none.

candidates:

  - title: Price an index for top_products, which reads all 4.5M order items
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    verified_sha: fd201331bb7c322c05d5074a8b2139c8cf0a92e9
    band: daily
    rationale: >
      top_products is the largest single statement on the dashboard at the
      30-day window, 660 ms in the endpoint and 958 ms measured alone with
      EXPLAIN ANALYZE. Its plan parallel-seq-scans all 4,546,466 rows of
      analytics_2.order_items to keep the 104,840 belonging to the window's
      orders, 43 read for every one kept, with 45,271 buffers off disk and
      244 ms of that in I/O. The orders side is already served by
      ix_analytics_orders_created and costs 25 ms, so the whole cost is the
      item side. ix_analytics_order_items_order exists on order_id and the
      planner declines it in favour of the hash join. The work is to price a
      covering index — (order_id) INCLUDE (wc_product_id, product_name, total,
      quantity) is the candidate — with hypopg and a control, and only then
      write the migration under dd-index-migration. It is explicitly NOT to
      assume an index helps: the same assumption about this endpoint was
      measured and found false earlier the same day, where a composite index
      changed no plan and the fix was the query shape.
    evidence:
      - document: research/candidates-dashboard-remaining-2026-09-14.md
        sha: d69723f
        repo: fleet
        section: "Daily — `top_products` reads every order item to find a month's worth"
    suggested_paths:
      - api/analytics/migrations/versions
    hib_signal: null
    probes:
      - path_exists: api/analytics/services/analytics_engine.py
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'SUM\(oi\.quantity\) AS quantity_sold'
          expected: 1
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'JOIN \{schema\}\.orders o ON o\.id = oi\.order_id'
          expected: 3
    premise:
      - claim: >
          The top_products query still joins order_items to orders in the
          engine, so the plan measured here is the plan the page runs.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'FROM \{schema\}\.order_items oi'
            expected: 3
      - claim: >
          The LATERAL rewrite is present, so this measurement was taken after
          task 100 and the 660 ms is what remains rather than what it replaced.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'CROSS JOIN LATERAL'
            expected: 1

  - title: The dashboard runs one reconciliation query per manifest ever received
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    verified_sha: fd201331bb7c322c05d5074a8b2139c8cf0a92e9
    band: daily
    rationale: >
      A dashboard request issues 48 statements and 36 of them are the same
      one — _platform_breakdown, 2.5 ms each, 91 ms total. The count is 36 at
      both a 30-day and a 180-day window, so it is not a function of what was
      asked for: it is one query per row in analytics_2.reconciliation_manifests,
      which holds exactly 36, all at day grain. The loop over them carries no
      window bound, and the code's own comment nearby anticipates ~730 rows for
      a two-year store at that grain, which is ~1.8 s per request arriving one
      manifest a day on a page that is 1.71 s today. The work has a correctness
      question in front of it and must answer that first: whether the loop can
      be bounded by the window at all without turning an unverified period into
      an unmentioned one, since the block answers a question about coverage
      over all history rather than over the window. If it cannot, the other
      shape is to fold 36 single-period queries into one grouped query, which
      changes no semantics.
    evidence:
      - document: research/candidates-dashboard-remaining-2026-09-14.md
        sha: d69723f
        repo: fleet
        section: "Daily — the dashboard runs one query per manifest ever received"
    suggested_paths:
      - api/analytics/services/reconciliation.py
    hib_signal: null
    probes:
      - path_exists: api/analytics/services/reconciliation.py
      - grep_count:
          glob: api/analytics/services/reconciliation.py
          pattern: 'ours_by_status = _platform_breakdown'
          expected: 1
      - grep_count:
          glob: api/analytics/services/reconciliation.py
          pattern: 'for m in manifests:'
          expected: 1
    premise:
      - claim: >
          _platform_breakdown is still defined in the reconciliation service,
          so the per-period query measured here is the one that would change.
        probe:
          grep_count:
            glob: api/analytics/services/reconciliation.py
            pattern: 'def _platform_breakdown'
            expected: 1
```
