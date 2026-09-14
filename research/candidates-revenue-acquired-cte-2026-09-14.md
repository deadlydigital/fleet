# The revenue endpoint's 7.6s is the query task 100 rewrote, in two places it did not reach

Measured 14 September 2026, 19:52–19:57 UTC, against the running API on
`analytics_2` (2,887,637 orders), box at load 0.04–0.54. Platform at `fd20133`.

**30-day window, `2026-08-15..2026-09-14`, tenant 2, `granularity=day`,
`coupon_limit=20`. Medians of three warm passes.** The window is stated because
this endpoint's cost is a function of it and a figure without one cost this
thread two wrong conclusions earlier today — `specs/neither-half-works-alone.md`,
"State the window".

## Three endpoints, one window

| | HTTP, median of 3 |
|---|---|
| `/api/analytics/revenue` | **7.60 s** (7.60, 8.54, 7.57) |
| `/api/analytics/customers` | **7.12 s** (7.35, 7.09, 7.12) |
| `/api/analytics/dashboard` | 1.73 s |

The dashboard is the one that had its `acquired` CTE rewritten by task 100.

## Where the revenue endpoint's time goes

Nine statements per request, every one timed in process:

| ms | phase | statement |
|---|---|---|
| **3,622** | `revenue_summary` | `WITH acquired AS (SELECT DISTINCT ON (a.customer_id) …` |
| **3,598** | `revenue_report` | `WITH acquired AS (SELECT DISTINCT ON (a.customer_id) …` |
| 163 | `revenue_summary` | coupon aggregate |
| 136 | `payment_method_breakdown` | null/all counts |
| 84 | `payment_method_breakdown` | grouped by method |
| 59 | `revenue_summary` | coupon per-code |
| 2 | all three | 3 × `schema_exists` |
| **7,706** | | **SQL total** |
| **6** | | **not SQL** |
| 7,712 | | wall |

By engine call: `revenue_report` 3,602 ms, `revenue_summary` 3,852 ms,
`payment_method_breakdown` 222 ms.

`/api/analytics/customers` is the same story in three statements: 3,594 ms and
3,601 ms, both the same CTE — `customer_report` builds `acquired_cte` once at
line 1578 and executes it in two queries — plus 0.8 ms of `schema_exists`.
7,192 ms of SQL, 2.3 ms of anything else.

## Both of the specific suspicions are refuted by the measurement

**It is not the coupon block or the payment-method breakdown.** Together they
are 442 ms of 7,706 ms — 5.7%. The coupon block came in with task 72
(`9f195ca`) and the payment-method breakdown with task 85 (`660bb31`), both
this week, and both are among the cheapest things the endpoint does.

**It is not this week's growth.** `analytics_engine.py` did grow — 1,420 lines
at the last commit before 7 Sep to 2,304 now, **+884** (the boundary matters:
measured from 8 Sep it is +757, which is the same arithmetic the window
principle is about). But the two statements that are 94% of the endpoint were
written on **23 August 2026** — `7b4c283` for both revenue copies, `fa0f96d`
for the customers one. The page was this slow before any of this week's work
landed; nothing measured it until now.

## Why it costs what it costs

The CTE asks for the acquiring order of **every customer in the table**, with
no restriction of any kind:

    WITH acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM orders a
        WHERE a.status IN ('completed','processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )

`EXPLAIN (ANALYZE, BUFFERS)` at the 30-day window:

    Aggregate                                              3,860 ms
      Merge Left Join                                     72,665 rows
        Sort (o.customer_id)                              72,665 rows,    68 ms
          Index Scan using ix_analytics_orders_created
        Unique                                           156,981 rows, 3,750 ms
          Index Scan using ix_analytics_orders_customer_created
                                                       2,885,651 rows
    Buffers: shared hit=2,789,136

**The index is used, and that is the point.** `ix_analytics_orders_customer_created`
— the index built for the dashboard on 14 Sep — is chosen here, and the query
walks the whole of it: 2,885,651 rows to produce 156,981 distinct customers,
2.79M buffers, 3,750 ms in that node. The window side is 72,665 rows and
68 ms. The outer query is `FROM orders o LEFT JOIN acquired q ON
q.customer_id = o.customer_id WHERE o.created_at` in the window, so only the
**21,579** customers active in the window can ever match. It computes 156,981
to use 21,579 — **7.3× more than it can use**, twice per revenue request and
twice per customers request.

This is a worse form than the one the dashboard had before task 100. That one
at least carried `customer_id IN (SELECT customer_id FROM window_customers)`.
These carry nothing.

## What is NOT established

* **Whether the `LATERAL` rewrite transfers.** It needs a driving set of
  customers and these CTEs have none, so the first step is the restriction the
  dashboard already had, and only then the rewrite. Which of the two carries
  the win here is **unmeasured**: the index is already being used, so this is
  not the same situation as the dashboard, where the index changed no plan at
  all and the shape was the whole fix.
* **Whether restricting to window customers is semantics-preserving at all
  three sites.** It looks so — all four outer queries join `acquired` only on
  `o.customer_id` for orders inside the window — but "looks so" is what
  requirement 3 of the last one was for, and that was settled by comparing the
  two forms row for row on production data, not by reading.
* **`compute_daily_metrics` carries a fourth copy** (line 119, `7874844`,
  23 Aug). It is a nightly batch rather than an endpoint, was not measured, and
  is deliberately outside this row.

## Daily — the acquiring-order CTE is unrestricted in three places

Filed below.

```fleet-candidates
source:
  document: research/candidates-revenue-acquired-cte-2026-09-14.md
  sha: b63d8c5
  repo: fleet

ordering: unranked

objectives_considered: >
  dd-trustworthy, on the same reading as task 100 and candidates 66 and 67: a
  page a merchant stops opening is a correctness-of-service problem, and two
  pages at seven and a half seconds are the measured majority of that. I
  weighed cost-discipline and it is untouched — the fix adds no request, no
  fixed cost and no dependency, and would reduce CPU on a box already paid for.
  I weighed dd-feature-parity and rejected it: no Metorik row asks for this,
  no gap closes, and ranking it as parity would put two seven-second pages
  behind rows that add reports. dd-first-revenue does not apply, since this is
  HIB's own store rather than the unsigned agency partner's. Unlike 66 and 67
  this one is not small: it is 94% of two endpoints, and I record that it is
  the largest measured win still available on the analytics surface.

unasked_question: >
  Nobody has asked whether anyone opens the revenue and customers pages at all,
  and nothing on this box can answer it — DD holds no event, session or
  page-view table on any schema, so a page that takes 7.6 seconds and a page
  nobody opens are indistinguishable from here. The second unasked question is
  why nothing measured these two endpoints between 23 August, when the queries
  were written, and tonight: the dashboard was measured because somebody
  complained about it, and the same query shape sat in three other functions
  for three weeks without anyone timing them. Whatever would have caught that
  is the more valuable thing and it is not in scope here.

candidates:

  - title: The acquiring-order CTE is unrestricted in revenue_report, revenue_summary and customer_report
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    verified_sha: fd201331bb7c322c05d5074a8b2139c8cf0a92e9
    band: daily
    rationale: >
      /api/analytics/revenue is 7.60s and /api/analytics/customers is 7.12s at a
      30-day window on a quiet box, against 1.73s for the dashboard at the same
      window. Instrumented, the revenue endpoint issues nine statements and two
      of them are 7,220ms of 7,706ms: the same DISTINCT ON acquiring-order CTE
      that task 100 replaced in _query_period_stats, in revenue_report and
      revenue_summary. customer_report holds a third copy and executes it twice
      for 7,192ms of its 7,194ms. The non-SQL portion is 6ms and 2ms. These
      copies are worse than the form the dashboard had before task 100: that one
      restricted the CTE to the window's customers, and these restrict it to
      nothing, so the plan walks all 2,885,651 index entries of
      ix_analytics_orders_customer_created to produce 156,981 customers where
      the outer join can only ever match the 21,579 active in the window, 7.3x
      more than it can use, at 2.79M buffers and 3,750ms per execution. The two
      suspicions this was filed against are both refuted by the measurement: the
      coupon block and the payment-method breakdown together are 442ms, 5.7% of
      the endpoint, and the two dominant statements date from 23 Aug 2026
      (7b4c283, fa0f96d) rather than from this week's 884 lines of growth. The
      work is to give these CTEs the window restriction they lack and then
      consider the LATERAL form, in that order, proving the answer unchanged
      row for row on production data the way task 100's requirement 3 was
      proved — and NOT to assume an index, because the index here is already
      chosen and walked in full.
    evidence:
      - document: research/candidates-revenue-acquired-cte-2026-09-14.md
        sha: b63d8c5
        repo: fleet
        section: "Daily — the acquiring-order CTE is unrestricted in three places"
    suggested_paths:
      - api/analytics/services/analytics_engine.py
    hib_signal: null
    probes:
      - path_exists: api/analytics/services/analytics_engine.py
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'SELECT DISTINCT ON \(a\.customer_id\)'
          expected: 4
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'CROSS JOIN LATERAL'
          expected: 1
    premise:
      - claim: >
          Four copies of the DISTINCT ON acquiring CTE remain and exactly one
          function has been rewritten, which is the whole shape of this finding.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'CROSS JOIN LATERAL'
            expected: 1
      - claim: >
          revenue_summary and customer_report are both still defined in the
          engine, so the two endpoints measured here are the ones that change.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def (revenue_summary|customer_report)'
            expected: 2
```
