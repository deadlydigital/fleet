# Ask for the acquiring order once per customer

Rewrite the `acquired` CTE in `_query_period_stats`
(`api/analytics/services/analytics_engine.py`) so it asks per customer instead
of sorting every matching row. **The index it needs is already in production**
— `ix_analytics_orders_customer_created`, applied 14 Sep 2026.

## The measurement, which is the whole justification

`_query_period_stats` is 85% of the dashboard's SQL and runs twice per request.
Executed against `analytics_2` (2,887,844 orders), box at load 0.03:

| | executed |
|---|---|
| today | **3,602 ms** |
| the same answer asked per customer | **252 ms** |

The plan today, with the index present and unused:

    Seq Scan on orders          2,885,101 rows, to remove 2,068
    Hash Join                   -> 1,724,435 rows
    Sort (external merge)       50,664 kB spilled, to produce 21,298

and with the rewrite:

    Nested Loop
      -> HashAggregate                        21,532 customers
      -> Limit (cost=0.43..4.38 rows=1)        0.007 ms, 21,532 loops
         -> Index Scan using ix_analytics_orders_customer_created

**Read `specs/neither-half-works-alone.md` first.** The index alone changed
nothing — measured by estimate and then by execution — and this rewrite alone,
before the index existed, was **worse** than what it replaces (4,094 ms against
3,410 ms). Neither half works alone. The index is now live, so this half is the
one that remains.

## Requirements

### 1. The `acquired` CTE asks per customer

Replace the `DISTINCT ON (a.customer_id) … ORDER BY a.customer_id,
a.created_at, a.id` form with a `LATERAL` subquery carrying `ORDER BY
o.created_at, o.id LIMIT 1` per customer. `LIMIT 1` is what lets the index stop
after one entry; without it the plan reverts to reading every row for those
customers.

### 2. The answer is identical, and that is the correctness condition

The CTE returns, for each customer active in the window, the `created_at` of
their **earliest revenue-status order over all time**. Every clause matters and
none may be dropped:

- **history is unbounded** — "first" means first ever, not first in the window,
  which is why the inner query has no date predicate;
- **revenue-status only** — `status IN ('completed', 'processing')`, the same
  filter the outer aggregate uses, so `new_customers` counts the same
  population `revenue` is summed from;
- **the tiebreak is `created_at, id`** — two orders at the same instant must
  resolve the same way every time, or `new_customers` becomes unstable between
  runs.

### 3. `new_customers` is unchanged for the same window

Before and after must agree exactly. The docstring's CONFLICT 2.2 says
`new_customers` is derived from `orders` and never read off
`customers.first_order_at`; that stays true.

### 4. Nothing else in the query moves

`orders_all`, `orders_rev`, `revenue`, `customers_all`, `customers_rev`, `aov`,
`refunded_amount`, `orders_with_refund` and `net_revenue` are all computed in
the same outer aggregate over the same rows. This is one CTE, not a rewrite of
the function.

### 5. The comparison window pays the same cost

`dashboard_overview` calls `_query_period_stats` twice — the window and the
window it compares against. Both benefit; neither is special-cased.

## What to check before claiming it works

Run the contract's suite, and then compare the figures the function returns for
one window before and after your change. A faster query that returns a
different `new_customers` is not this task.

## What this does not fix

The dashboard endpoint measured 9.1s on a quiet box with ~6.5s of SQL, so
roughly 2.6s is not SQL and this does not touch it. An earlier 21.3s reading
was taken under CPU contention and is not a baseline. Do not claim an
end-to-end figure; claim the query.

## Objectives

`dd-trustworthy`. A page a merchant stops opening is a correctness-of-service
problem, and this is the measured majority of it.
