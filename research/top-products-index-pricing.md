# Pricing the `top_products` covering index

**Written 15 September 2026.** Platform read at the checkout this task was given,
which is `fd20133` plus what has merged since; the statement below was read out
of the tree rather than recalled.

**STATUS OF THE MEASUREMENT: NOT RUN.** This task was queued under
`contracts/research.yaml`, which grants Read, Grep, Glob, Write, Edit, WebSearch
and WebFetch and carries no `evidence_queries` — so `runner/cycle.py` assembled
no evidence pack and there is no pack file in this worktree. I have no shell and
no database. **Every cell in every result table below reads `not run`, and every
performance claim in this document is a prediction.** The procedure in §4 is
runnable as pasted; §5 is the same procedure in the shape `runner/evidence.py`
takes, for whoever wants the fleet to fill the tables on a re-queue.

**THE WINDOW.** Every figure quoted or asked for here is the 30-day window
`2026-08-15 .. 2026-09-15` — half-open, `created_at >= '2026-08-15' AND
created_at < '2026-09-15'` — on tenant 2, `analytics_2`. That is the window the
958 ms control was taken on (`research/candidates-dashboard-remaining-2026-09-14.md`)
and the one `research/task-102-timing.sql` binds. **Whoever runs this must keep
those literal dates even if the run happens later**, because "the last 30 days"
on 20 September is not the window the control was measured on and the two
numbers would not be comparable. `specs/neither-half-works-alone.md` spent a day
and two withdrawn conclusions learning that a timing without its window is not a
measurement.

**This document writes no migration and proposes no build.** If the pricing says
yes, §9 hands a follow-up task under `contracts/dd-index-migration.yaml`
everything it needs. That task is queued afterwards, from this document, or not
at all — not as a chained link, because a chained link would be written and
verified without the result that is supposed to decide whether it should exist.

---

## 1. The statement, and every column it reads

`dashboard_overview` (`api/analytics/services/analytics_engine.py:492`) issues it
at `api/analytics/services/analytics_engine.py:709`, and it is what
`GET /api/analytics/dashboard` (`api/analytics/routes/dashboard.py:20`) returns
as `top_products`. Verbatim, as it stands in the tree:

```python
    # Top 5 products WITHIN the chosen window.
    top_products_rows = db.execute(
        text(f"""
            SELECT
                oi.wc_product_id,
                oi.product_name,
                SUM(oi.total) AS revenue,
                SUM(oi.quantity) AS quantity_sold,
                COUNT(DISTINCT o.id) AS order_count
            FROM {schema}.order_items oi
            JOIN {schema}.orders o ON o.id = oi.order_id
            WHERE {range_predicate("o.created_at")}
              AND o.status IN {_REVENUE_STATUSES}
            GROUP BY oi.wc_product_id, oi.product_name
            ORDER BY revenue DESC
            LIMIT 5
        """),
        range_params(start, end)
    ).fetchall()
```

`range_predicate` and `range_params` are in
`api/analytics/services/date_range.py:152` and `:172`; the predicate expands to
`o.created_at >= :start AND o.created_at < :end_plus`, with `end_plus` the
inclusive `end` plus one day. `_REVENUE_STATUSES` is
`api/analytics/services/analytics_engine.py:32` — `('completed', 'processing')`.

**Columns of `order_items` read, and nothing else:**

| column | how it is used |
|---|---|
| `order_id` | the join predicate, `o.id = oi.order_id` |
| `wc_product_id` | projected; `GROUP BY` key |
| `product_name` | projected; `GROUP BY` key |
| `total` | `SUM(oi.total) AS revenue` |
| `quantity` | `SUM(oi.quantity) AS quantity_sold` |

**Columns of `orders` read:** `id` (join, and `COUNT(DISTINCT o.id)`),
`created_at` (window predicate), `status` (revenue filter). Nothing else.

* **Join predicate:** `o.id = oi.order_id`, inner.
* **`GROUP BY`:** `oi.wc_product_id, oi.product_name`.
* **`ORDER BY`:** `revenue DESC` — the aggregate alias, so the sort is after the
  aggregation and cannot be served by any index.
* **`LIMIT`:** 5, hard-coded.

### The falsification this requirement asks for, applied first

The proposed index is `(order_id) INCLUDE (wc_product_id, product_name, total,
quantity)`. If the statement read any `order_items` column outside those five,
the heap fetch the INCLUDE list exists to avoid would happen anyway and the
candidate index would be wrong as written.

**It does not. The set matches exactly — key `order_id`, four INCLUDE columns,
no sixth column.** The proposed INCLUDE list is correct for this statement and
needs no amendment. That is the one thing in this document that is established
rather than predicted, because it is a fact about the source and I could read the
source.

### The three call sites are not the same query, and only one is on the dashboard

The candidate's probes count three `FROM {schema}.order_items oi` and three joins
to `orders`. They are:

| site | function | `order_items` columns |
|---|---|---|
| `api/analytics/services/analytics_engine.py:717` | `dashboard_overview` — **this is the dashboard's** | `order_id`, `wc_product_id`, `product_name`, `total`, `quantity` |
| `api/analytics/services/analytics_engine.py:1879` | `product_report` (`/analytics/products`) | the same five |
| `api/analytics/services/analytics_engine.py:2014` | `product_category_report`, the `labelled` CTE | the same five **plus `oi.id`** |

The dashboard runs the first, and that is what is priced here. `product_report`
reads the identical five columns, so whatever the pricing concludes transfers to
it unchanged — it is a second beneficiary, not a second measurement.

`product_category_report` carries `oi.id AS item_id`, which the coverage block
needs to collapse the category fan-out back to one row per line
(`api/analytics/services/analytics_engine.py:2003`). **The proposed index cannot
give that statement an index-only scan**, and extending the INCLUDE list to cover
it would add a sixth column — `id`, 4 bytes on every one of 4.5M entries — to an
index whose size is already the argument against it. It is not on the dashboard.
Leave it out and say so, rather than widening the index for a page nobody
measured.

*One thing noticed while reading and deliberately left alone:* `ORDER BY revenue
DESC LIMIT 5` has no tiebreaker, so products tied on revenue at the cut are
returned in an unspecified order. That is the BUG-008 shape
`api/analytics/services/analytics_engine.py:2025` already names for the category
report. It is a correctness observation about a statement I had to quote in full,
not part of this pricing, and no index changes it.

---

## 2. The two outcomes, named before the run

Written before any EXPLAIN output exists, because a document that only explains
the result it got is a document that would have explained either.

### Outcome A — the plan flips

The `Parallel Seq Scan on order_items` becomes an index scan (or index-**only**
scan) on `order_items`, driven by the window's ~23,571 qualifying orders, most
likely under a nested loop with the existing `Parallel Index Scan using
ix_analytics_orders_created` on the outer side.

What that would be worth, and why: the current plan reads **all 4,546,466 rows**
of `order_items` to keep **104,840**, at 39,356 buffer hits + **45,271 buffer
reads** and **244 ms** of I/O. The index path reads instead ~23,571 btree
descents and the leaf pages holding 104,840 entries. `order_id` is a `SERIAL`
assigned in insertion order and the window's orders are the most recent, so those
entries should be physically clustered near one end of the index — the plausible
read volume is low thousands of buffers rather than 45,271. **That reasoning is
why a flip is worth pricing. It is not evidence that a flip will happen**, and
the planner does not reason this way; it costs probes at `random_page_cost`.

### Outcome B — the plan does not flip

The planner continues to estimate 23,571 probes yielding 104,840 rows, plus
per-row visibility work, as dearer than a 4.5M-row parallel sequential scan.

**This is the expected outcome, not the surprising one.**
`ix_analytics_order_items_order` already exists on `order_id`
(`api/analytics/migrations/versions/v0001_baseline.py:114`) and the planner
declines it today. The covering columns change that estimate in exactly one way:
they remove the heap access from the inner side. They do not change the probe
count, they do not change the row count, and they do not change the parallel
sequential scan's cost. If the heap access was not the deciding term in the
comparison, the covering index changes nothing — which is precisely what
happened on 14 September, when the composite index on `orders` was assumed to be
the fix, was built at 112 MB per schema, and changed no plan at all
(`specs/neither-half-works-alone.md`).

**The predictor to look at first** is step 0's `relallvisible / relpages` on
`analytics_2.order_items`. An index-only scan is only cheap in the planner's
model to the degree the table is all-visible; `order_items` is rewritten by the
sync on every re-sync of an order — `DELETE` then `INSERT`, at
`api/analytics/services/sync_engine.py:618` and `:652` — so a low all-visible
fraction is entirely possible, and it would cost the covering index most of its
modelled advantage before any of this is run. If that number comes back low,
outcome B is the one to expect.

---

## 3. The decision rule, fixed now and applied later

Three gates, in order. Each is stated with its consequence, and none of the
thresholds may be revised after a number is seen.

### Gate A — calibration. Does hypopg model *this* planner?

A hypothetical **bare `(order_id)`** index must **not** flip the plan. That index
already exists and is already declined, so the correct answer is known before the
question is asked. If the hypothetical version flips it, hypopg is not modelling
this planner and every number after it is void: **report that and stop.**

**A2, added here because it is the cheapest way this run could be silently
wrong.** hypopg must be shown to have *honoured* the `INCLUDE` clause rather than
parsed it away. `hypopg_create_index()` builds its hypothetical from the
statement text, and support for covering indexes arrived in a specific hypopg
version; an older build that ignored the clause would produce a hypothetical
identical to the bare `(order_id)` index while reporting success, and the run
would then be a second, more expensive calibration test rather than a pricing.

The check needs no new tooling: compare `hypopg_relation_size()` of the bare
index against the covering one. The covering index carries a `bigint`, a
`varchar(255)`, an `integer` and a `numeric` on every entry. **If the two sizes
are within a few percent of each other, the INCLUDE was dropped and the run is
void** — same consequence as gate A, report and stop.

### Gate B — the flip

The covering hypothetical flips the plan to an index scan on `order_items`.

**If it does not, the candidate dies here.** The document records that the item
side is not addressable by this index, no migration is written, and §8 is what is
left. There is no partial credit at this gate: a plan that keeps the parallel
sequential scan pays the full 45,271 buffer reads regardless of what the index
would have cost to build.

### Gate C — the size of the win

A migration on this path deploys by hand — `console/autodeploy` refuses any range
containing one, and `contracts/dd-index-migration.yaml` sets `auto_merge: false`
— so it has to be worth a person's deploy plus several hundred MB per tenant
schema, forever, written on every sync.

**The bar, both clauses required:**

1. The real measured statement at this window is at least **2× faster** than the
   **958 ms** control.
2. It takes at least **250 ms** off the endpoint's **1,666 ms** SQL budget.

Below that: record the number and **recommend against**. A 1.71 s page does not
get a hand-deployed schema change for 10%.

**One refinement to those thresholds, argued rather than assumed, because the two
clauses are quoted on different scales.** 958 ms is the statement under
`EXPLAIN (ANALYZE, BUFFERS)`, which adds per-node timing overhead; 619 ms is the
same statement timed in process inside the endpoint, and 1,666 ms is the sum of
those in-process figures. Applying clause 2 to the EXPLAIN number would compare a
saving measured one way against a budget measured the other.

So: **clause 1 is judged on the EXPLAIN control (958 ms → ≤479 ms); clause 2 is
judged on a re-measured in-endpoint figure (619 ms → ≤369 ms).** A run that
produces only the EXPLAIN number can still decide clause 1, and may note that 2×
there corresponds to roughly 309 ms of the endpoint's budget *if* the saving
scales proportionally between the two instrumentations — but that proportionality
is an assumption, it must be labelled as one, and it cannot be used to *pass*
clause 2 on its own. The thresholds themselves are unchanged and I am not
arguing them down: 2× and 250 ms are the right bar for a hand deploy.

---

## 4. The pricing procedure, runnable as pasted

Against `analytics_2`, via psql, as a role that can read the tenant schemas.
Every statement carries the same explicit window. `hypopg_reset()` runs between
every step.

**The extension is a superuser act.** The readers this fleet holds are
SELECT-only (`runner/evidence.py:34`), so step 0's `CREATE EXTENSION` will fail
for any of them. If hypopg is not installed and cannot be installed by whoever
runs this, **the pricing stops at step 0 and this document says so rather than
substituting a guess.** That is a real possible outcome of this task and it is
not a failure of it.

### Step 0 — session, extension, and the facts that predict the answer

```sql
\set ON_ERROR_STOP on
\pset pager off
\timing on

SET statement_timeout = 0;

-- Superuser. If this fails, stop here and report gate 0.
CREATE EXTENSION IF NOT EXISTS hypopg;

SELECT version();
SELECT extname, extversion FROM pg_extension WHERE extname = 'hypopg';
SELECT current_setting('work_mem')                        AS work_mem,
       current_setting('max_parallel_workers_per_gather')  AS max_parallel,
       current_setting('effective_cache_size')             AS effective_cache_size,
       current_setting('random_page_cost')                 AS random_page_cost;
```

```sql
-- The table, its width, and the visibility fraction that decides whether an
-- index-only scan is cheap in the planner's model (see §2, outcome B).
SELECT c.reltuples::bigint                                     AS est_rows,
       c.relpages,
       c.relallvisible,
       round(100.0 * c.relallvisible / NULLIF(c.relpages, 0), 1) AS pct_all_visible,
       pg_size_pretty(pg_relation_size(c.oid))                 AS heap,
       pg_size_pretty(pg_total_relation_size(c.oid))           AS heap_plus_indexes
  FROM pg_class c
 WHERE c.oid = 'analytics_2.order_items'::regclass;

SELECT count(*)                            AS order_items_rows,
       round(avg(length(product_name)), 1) AS avg_product_name_len,
       max(length(product_name))           AS max_product_name_len
  FROM analytics_2.order_items;

SELECT indexname,
       pg_size_pretty(pg_relation_size(('analytics_2.' || indexname)::regclass)) AS size,
       indexdef
  FROM pg_indexes
 WHERE schemaname = 'analytics_2' AND tablename = 'order_items'
 ORDER BY indexname;

-- The window, restated as a count, so the 23,571 figure is checked and not
-- assumed on the day of the run.
SELECT count(*) AS window_orders
  FROM analytics_2.orders o
 WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
   AND o.status IN ('completed', 'processing');
```

### Step 1 — the control

Run the block **four times**; discard the first as a warm-up and take the median
of the remaining three. `research/task-102-timing.sql` is the precedent and its
header says why: `EXPLAIN ANALYZE` on a cold cache measures the cache, and a
single pass gave `top_products` as 660 ms against a median of 619 ms.

```sql
SELECT hypopg_reset();

EXPLAIN (ANALYZE, BUFFERS)
SELECT
    oi.wc_product_id,
    oi.product_name,
    SUM(oi.total)         AS revenue,
    SUM(oi.quantity)      AS quantity_sold,
    COUNT(DISTINCT o.id)  AS order_count
FROM analytics_2.order_items oi
JOIN analytics_2.orders o ON o.id = oi.order_id
WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
  AND o.status IN ('completed', 'processing')
GROUP BY oi.wc_product_id, oi.product_name
ORDER BY revenue DESC
LIMIT 5;
```

### Step 2 — gate A, calibration: the bare index that is already declined

```sql
SELECT hypopg_reset();

SELECT indexrelid, indexname
  FROM hypopg_create_index(
       'CREATE INDEX ON analytics_2.order_items (order_id)');

SELECT h.indexname,
       hypopg_relation_size(h.indexrelid)                  AS bytes,
       pg_size_pretty(hypopg_relation_size(h.indexrelid))  AS size
  FROM hypopg() h;

-- NO ANALYZE. A hypothetical index cannot be executed; asking for one is an
-- error, not a slower answer.
EXPLAIN
SELECT
    oi.wc_product_id,
    oi.product_name,
    SUM(oi.total)         AS revenue,
    SUM(oi.quantity)      AS quantity_sold,
    COUNT(DISTINCT o.id)  AS order_count
FROM analytics_2.order_items oi
JOIN analytics_2.orders o ON o.id = oi.order_id
WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
  AND o.status IN ('completed', 'processing')
GROUP BY oi.wc_product_id, oi.product_name
ORDER BY revenue DESC
LIMIT 5;

SELECT hypopg_reset();
```

**Expected: no change from step 1's plan shape.** A flip here voids the run.

### Step 3 — the placebo: an index that cannot serve this query

```sql
SELECT hypopg_reset();

SELECT indexrelid, indexname
  FROM hypopg_create_index(
       'CREATE INDEX ON analytics_2.order_items (product_name)');

EXPLAIN
SELECT
    oi.wc_product_id,
    oi.product_name,
    SUM(oi.total)         AS revenue,
    SUM(oi.quantity)      AS quantity_sold,
    COUNT(DISTINCT o.id)  AS order_count
FROM analytics_2.order_items oi
JOIN analytics_2.orders o ON o.id = oi.order_id
WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
  AND o.status IN ('completed', 'processing')
GROUP BY oi.wc_product_id, oi.product_name
ORDER BY revenue DESC
LIMIT 5;

SELECT hypopg_reset();
```

**Expected: no change.** `product_name` is a `GROUP BY` key and nothing else;
there is no path by which an index on it serves this shape. If it flips the plan,
hypopg is producing plan changes that are not about the index, and the run is
void for the same reason as gate A.

### Step 4 — the candidate, and gate B

```sql
SELECT hypopg_reset();

SELECT indexrelid, indexname
  FROM hypopg_create_index(
       'CREATE INDEX ON analytics_2.order_items (order_id) '
       'INCLUDE (wc_product_id, product_name, total, quantity)');

-- Gate A2: this size against step 2's. Within a few percent means the INCLUDE
-- was parsed away and the run is void.
SELECT h.indexname,
       hypopg_relation_size(h.indexrelid)                  AS bytes,
       pg_size_pretty(hypopg_relation_size(h.indexrelid))  AS size
  FROM hypopg() h;

EXPLAIN
SELECT
    oi.wc_product_id,
    oi.product_name,
    SUM(oi.total)         AS revenue,
    SUM(oi.quantity)      AS quantity_sold,
    COUNT(DISTINCT o.id)  AS order_count
FROM analytics_2.order_items oi
JOIN analytics_2.orders o ON o.id = oi.order_id
WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
  AND o.status IN ('completed', 'processing')
GROUP BY oi.wc_product_id, oi.product_name
ORDER BY revenue DESC
LIMIT 5;
```

Record which scan node appears on `order_items`: `Seq Scan` / `Parallel Seq
Scan` (no flip), `Index Scan` (flip, heap still touched), or `Index Only Scan`
(flip, heap avoided to the degree the visibility map allows). The three are
different results and the difference is most of what gate C will turn on.

### Step 5 — return to control

```sql
SELECT hypopg_reset();
SELECT count(*) AS hypothetical_indexes_remaining FROM hypopg();
```

Then re-run step 1's `EXPLAIN (ANALYZE, BUFFERS)` block three times and show the
median matches step 1's, so the session ended where it started and nothing in
between left residue. If the two controls disagree by more than the spread of
their own three runs, the box moved underneath the measurement and the whole run
needs retaking — which is the failure a single-pass measurement cannot see.

### Step 6 — the §8 alternative, priced while hypopg is already loaded

Free to take at this point and it answers requirement 7's question directly.
See §8 for what the rewrite is and why it is the only reshape worth pricing.

```sql
SELECT hypopg_reset();

EXPLAIN (ANALYZE, BUFFERS)
SELECT
    oi.wc_product_id,
    oi.product_name,
    SUM(oi.total)              AS revenue,
    SUM(oi.quantity)           AS quantity_sold,
    COUNT(DISTINCT oi.order_id) AS order_count
FROM analytics_2.order_items oi
WHERE oi.order_id = ANY (ARRAY(
        SELECT o.id FROM analytics_2.orders o
         WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
           AND o.status IN ('completed', 'processing')))
GROUP BY oi.wc_product_id, oi.product_name
ORDER BY revenue DESC
LIMIT 5;
```

Take it four times, median of the last three, exactly as step 1. Then repeat it
once with the step 4 hypothetical in place (`EXPLAIN`, no `ANALYZE`), to see
whether the reshape and the index together reach a plan that neither reaches
alone — which is the shape `specs/neither-half-works-alone.md` found last time
and the reason to spend one extra statement looking for it.

---

## 5. The same procedure as `evidence_queries`, for a re-queue with a pack

A human may add these to a research contract before queueing, and the task then
fills §6 itself. `contracts/**` is on the fleet floor for every task including
this one, so editing a contract is a human act and this block is written to make
that paste mechanical.

Four things about `runner/evidence.py` shape the block, and getting any of them
wrong produces a pack full of errors:

* **The session is read-only** (`runner/evidence.py:66`, `conn.read_only = True`)
  and the reader holds SELECT only. **`CREATE EXTENSION` cannot be in the pack.**
  hypopg must already be installed by a superuser, out of band, before the task
  is queued. `hypopg_create_index()` itself is fine: its hypothetical lives in
  backend memory, writes no catalog row, and survives a rollback.
* **Order matters and is preserved within a reader.** Queries are grouped by
  reader and run in list order on one connection, so the hypopg session state
  carries from one query to the next. Keep these contiguous, in this order, and
  do not interleave other `deadly_digital` queries between them.
* **Every query must return rows.** `run_queries` calls `fetchall()`
  (`runner/evidence.py:96`), so a statement producing no result set is recorded
  as an error. `SELECT hypopg_reset()` returns one row and is fine.
* **`FORMAT JSON`, not the default text.** `render()` turns rows into a markdown
  table, and a 20-line text plan becomes 20 table rows with its indentation
  collapsed. `FORMAT JSON` returns one row in one cell, intact.

`statement_timeout` is 30 s in the pack (`runner/evidence.py:40`), which the
~1 s control clears comfortably; a flipped plan that somehow took longer would be
recorded as a timeout error rather than a number, which is the right failure.

```yaml
evidence_queries:
  - key: tp_00_hypopg_present
    reader: deadly_digital
    sql: |
      SELECT extname, extversion FROM pg_extension WHERE extname = 'hypopg'
  - key: tp_01_table_facts
    reader: deadly_digital
    sql: |
      SELECT c.reltuples::bigint AS est_rows, c.relpages, c.relallvisible,
             round(100.0 * c.relallvisible / NULLIF(c.relpages, 0), 1) AS pct_all_visible,
             pg_size_pretty(pg_relation_size(c.oid)) AS heap,
             pg_size_pretty(pg_total_relation_size(c.oid)) AS heap_plus_indexes
        FROM pg_class c WHERE c.oid = 'analytics_2.order_items'::regclass
  - key: tp_02_control_explain
    reader: deadly_digital
    sql: |
      EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
      SELECT oi.wc_product_id, oi.product_name,
             SUM(oi.total) AS revenue, SUM(oi.quantity) AS quantity_sold,
             COUNT(DISTINCT o.id) AS order_count
        FROM analytics_2.order_items oi
        JOIN analytics_2.orders o ON o.id = oi.order_id
       WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
         AND o.status IN ('completed', 'processing')
       GROUP BY oi.wc_product_id, oi.product_name
       ORDER BY revenue DESC LIMIT 5
  - key: tp_03_calibration_bare_create
    reader: deadly_digital
    sql: |
      SELECT h.indexname, hypopg_relation_size(h.indexrelid) AS bytes
        FROM hypopg_create_index(
               'CREATE INDEX ON analytics_2.order_items (order_id)') x
        JOIN hypopg() h ON h.indexrelid = x.indexrelid
  - key: tp_04_calibration_bare_explain
    reader: deadly_digital
    sql: |
      EXPLAIN (FORMAT JSON)
      SELECT oi.wc_product_id, oi.product_name,
             SUM(oi.total) AS revenue, SUM(oi.quantity) AS quantity_sold,
             COUNT(DISTINCT o.id) AS order_count
        FROM analytics_2.order_items oi
        JOIN analytics_2.orders o ON o.id = oi.order_id
       WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
         AND o.status IN ('completed', 'processing')
       GROUP BY oi.wc_product_id, oi.product_name
       ORDER BY revenue DESC LIMIT 5
  - key: tp_05_reset_a
    reader: deadly_digital
    sql: SELECT hypopg_reset() AS reset
  - key: tp_06_placebo_create
    reader: deadly_digital
    sql: |
      SELECT h.indexname, hypopg_relation_size(h.indexrelid) AS bytes
        FROM hypopg_create_index(
               'CREATE INDEX ON analytics_2.order_items (product_name)') x
        JOIN hypopg() h ON h.indexrelid = x.indexrelid
  - key: tp_07_placebo_explain
    reader: deadly_digital
    sql: |
      EXPLAIN (FORMAT JSON)
      SELECT oi.wc_product_id, oi.product_name,
             SUM(oi.total) AS revenue, SUM(oi.quantity) AS quantity_sold,
             COUNT(DISTINCT o.id) AS order_count
        FROM analytics_2.order_items oi
        JOIN analytics_2.orders o ON o.id = oi.order_id
       WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
         AND o.status IN ('completed', 'processing')
       GROUP BY oi.wc_product_id, oi.product_name
       ORDER BY revenue DESC LIMIT 5
  - key: tp_08_reset_b
    reader: deadly_digital
    sql: SELECT hypopg_reset() AS reset
  - key: tp_09_covering_create_and_size
    reader: deadly_digital
    sql: |
      SELECT h.indexname, hypopg_relation_size(h.indexrelid) AS bytes,
             pg_size_pretty(hypopg_relation_size(h.indexrelid)) AS size
        FROM hypopg_create_index(
               'CREATE INDEX ON analytics_2.order_items (order_id) INCLUDE (wc_product_id, product_name, total, quantity)') x
        JOIN hypopg() h ON h.indexrelid = x.indexrelid
  - key: tp_10_covering_explain
    reader: deadly_digital
    sql: |
      EXPLAIN (FORMAT JSON)
      SELECT oi.wc_product_id, oi.product_name,
             SUM(oi.total) AS revenue, SUM(oi.quantity) AS quantity_sold,
             COUNT(DISTINCT o.id) AS order_count
        FROM analytics_2.order_items oi
        JOIN analytics_2.orders o ON o.id = oi.order_id
       WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
         AND o.status IN ('completed', 'processing')
       GROUP BY oi.wc_product_id, oi.product_name
       ORDER BY revenue DESC LIMIT 5
  - key: tp_11_reset_c
    reader: deadly_digital
    sql: SELECT hypopg_reset() AS reset
  - key: tp_12_return_to_control
    reader: deadly_digital
    sql: |
      EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
      SELECT oi.wc_product_id, oi.product_name,
             SUM(oi.total) AS revenue, SUM(oi.quantity) AS quantity_sold,
             COUNT(DISTINCT o.id) AS order_count
        FROM analytics_2.order_items oi
        JOIN analytics_2.orders o ON o.id = oi.order_id
       WHERE o.created_at >= '2026-08-15' AND o.created_at < '2026-09-15'
         AND o.status IN ('completed', 'processing')
       GROUP BY oi.wc_product_id, oi.product_name
       ORDER BY revenue DESC LIMIT 5
```

**A pack cannot give a median.** Each key runs once. A pack run therefore
decides gates A, A2 and B — which are about plan *shape* and index *size*, and a
plan shape does not move between runs — and it cannot decide gate C, which needs
three warm runs of a real index. Duplicating `tp_02` under three keys would give
three runs and is worth doing if a pack is used at all.

---

## 6. Results

**Nothing in this section was measured.** Every cell reads `not run` because no
pack was assembled and this task has no database access. Filling them is the
whole of the remaining work.

### 6.1 Step 0 — the facts

| reading | value |
|---|---|
| hypopg installed, version | not run |
| `order_items` rows | not run *(4,546,466 on 14 Sep)* |
| `order_items` heap size | not run |
| `relallvisible / relpages` | not run — **the predictor for outcome B** |
| avg / max `length(product_name)` | not run |
| existing indexes and their sizes | not run |
| orders in window, revenue statuses | not run *(~23,571 on 14 Sep)* |
| `work_mem`, `random_page_cost`, parallel workers | not run |

### 6.2 Gates A and A2 — calibration

| | plan on `order_items` | hypopg size | verdict |
|---|---|---|---|
| step 1 control | not run | — | — |
| bare `(order_id)` hypothetical | not run | not run | not run |
| placebo `(product_name)` | not run | not run | not run |
| covering hypothetical | not run | not run | not run |
| bare vs covering size ratio | — | not run | **A2: not run** |

### 6.3 Gate B — the flip

| | scan node on `order_items` | estimated cost | flipped? |
|---|---|---|---|
| control | not run | not run | — |
| with covering hypothetical | not run | not run | **not run** |

### 6.4 Gate C — the size of the win

Only reachable with a **real** index; a hypothetical gives no execution time.
See §7 for what obtaining one costs.

| | measured | threshold | pass? |
|---|---|---|---|
| statement, `EXPLAIN (ANALYZE, BUFFERS)`, median of 3 | not run | ≤ 479 ms (2× of 958 ms) | not run |
| statement, in-endpoint, median of 3 | not run | ≤ 369 ms (250 ms off 619 ms) | not run |
| buffers read | not run | vs 45,271 | not run |
| I/O time | not run | vs 244 ms | not run |
| real index size, `analytics_2` | not run | — | not run |
| real index build time, `analytics_2` | not run | — | not run |

### 6.5 Step 5 — return to control

| | median of 3 | matches step 1? |
|---|---|---|
| control retaken after `hypopg_reset()` | not run | not run |

### 6.6 Step 6 — the §8 reshape

| | execution | scan node on `order_items` |
|---|---|---|
| `= ANY (ARRAY(...))`, no hypothetical | not run | not run |
| `= ANY (ARRAY(...))` + covering hypothetical | not run (EXPLAIN only) | not run |

**Overall verdict: not reached.** Gates A, A2, B and C are all open.

---

## 7. What a true execution time costs — proposed, not performed

A plan flip is necessary and not sufficient. hypopg models estimates; only a real
index gives a real execution time, and gate C is stated in milliseconds. Two ways
to get one, and **this document performs neither**.

### Option 1 — `CREATE INDEX` inside a transaction that is rolled back

```sql
BEGIN;
CREATE INDEX ix_tmp_pricing_order_items_covering
    ON analytics_2.order_items (order_id)
    INCLUDE (wc_product_id, product_name, total, quantity);
-- ... EXPLAIN (ANALYZE, BUFFERS) the statement, four times, median of last three
ROLLBACK;
```

Cheapest to clean up: the rollback leaves nothing behind, with no invalid
leftover and nothing to remember to drop. **The cost is a lock.** A
non-concurrent `CREATE INDEX` takes `SHARE` on the table for the whole build,
which blocks writes while leaving reads alone — and the sync path writes this
table, `DELETE` then `INSERT` per batch at
`api/analytics/services/sync_engine.py:618` and `:652`. For the length of the
build, sync batches touching tenant 2 block. The dashboard keeps serving.

### Option 2 — `CREATE INDEX CONCURRENTLY`, measure, `DROP INDEX CONCURRENTLY`

```sql
-- Outside any transaction block.
CREATE INDEX CONCURRENTLY ix_tmp_pricing_order_items_covering
    ON analytics_2.order_items (order_id)
    INCLUDE (wc_product_id, product_name, total, quantity);
-- ... EXPLAIN (ANALYZE, BUFFERS) the statement, four times, median of last three
DROP INDEX CONCURRENTLY analytics_2.ix_tmp_pricing_order_items_covering;
```

No write blocking, a slower build, two passes over 4,546,466 rows, and **a real
index that exists until it is dropped** — including if the session dies mid-build,
which leaves an invalid index behind. That leftover is exactly what
`CreateIndexStep`'s leading `DROP INDEX IF EXISTS` exists to clean up
(`api/analytics/migrations/migration.py:153`), but here there is no migration
running and the drop is the operator's to remember.

**Note the name.** Both options above build `ix_tmp_pricing_order_items_covering`
and **not** the name §9 proposes for the migration. That is deliberate: the
migration's step predicate is `IndexValid(table, index)`, so an abandoned
hand-built index carrying the migrated name would make the migration's predicate
pass against a schema the migration had never been applied to. A trial index must
not be able to impersonate a migrated one.

### Recommendation

**Option 2, on `analytics_2` only, in a quiet window, with the drop scheduled
before the build is started.** The write-blocking in option 1 is the worse cost:
it lands on the sync, the sync is what keeps the analytics true, and a blocked
sync batch is a correctness-adjacent failure rather than a slow page. Option 2's
risk is forgetting the drop, and that is a checklist problem rather than an
outage.

**What it is expected to cost, stated as estimate and not measurement.** Size: an
entry carries `order_id` (int4), `wc_product_id` (int8), `product_name`
(varchar(255), average length unmeasured — step 0 asks for it), `quantity`
(int4) and `total` (numeric(10,2)), against 4,546,466 rows. The bare
`(customer_id, created_at, id)` index on 2,887,844 `orders` rows measured
**112 MB** (`specs/neither-half-works-alone.md`), so scaling by row count and by
a substantially wider entry puts this in the **low hundreds of MB per tenant
schema**. I am not narrowing that: `hypopg_relation_size()` in step 4 settles it
for free and no estimate here should be quoted instead of that number. Build
time: **unmeasured**, and `api/analytics/migrations/versions/v0014_orders_customer_created_index.py`
argues in its own header why guessing one is worse than the gap — an operator who
reads "a few minutes" and sees ten has to work out which to believe.

The decision to build is the operator's. Nothing in this document should be read
as though it had been agreed.

---

## 8. If B or C fails — what is left, and what can be priced cheaply

**The `LATERAL` answer from task 100 does not transfer, and it should not be
proposed by analogy.** That rewrite worked because `DISTINCT ON (customer_id)`
asks a per-group *first-row* question, and `LIMIT 1` is what lets a btree stop
after one entry (`specs/neither-half-works-alone.md`, "Why"). `top_products` has
no per-group `LIMIT` to exploit: `SUM(oi.total)` and `SUM(oi.quantity)`
genuinely need every matching item, and the only `LIMIT` is the 5 at the very
end, after aggregation, on an expression no index can order. There is no
per-group shortcut here and pattern-matching to the previous win would invent
one.

**The one shape worth pricing** is whether feeding the planner the window's order
ids *differently* changes the estimate that is currently declining
`ix_analytics_order_items_order`. The refusal is an estimate about probe count,
not a fact about the index, and the statement makes that unusually easy to test,
because **the orders side projects nothing but `o.id`**. `COUNT(DISTINCT o.id)`
over an inner join on `o.id = oi.order_id` is identical to `COUNT(DISTINCT
oi.order_id)` — every counted `o.id` is a joined `oi.order_id` and vice versa —
so the join can become a semi-join or an `= ANY(...)` over an id list without
changing a single output value.

Step 6 of §4 is that rewrite, runnable. `ARRAY(...)` rather than a bare `IN
(subquery)` is the point of it: materialising the ids makes the planner cost the
inner side as ~23,571 probes against a known array, which is a different
estimate from the hash-join-versus-scan comparison it makes today. The orders
side already produces those ids in 25 ms, so the reshape costs nothing it was not
paying.

**What that would and would not buy.** If the reshape alone flips the plan, the
answer is a query change under `contracts/deadly-digital-platform-api.yaml`,
which auto-merges and auto-deploys — no migration, no hand deploy, no index to
maintain, and by far the cheapest outcome available here. If it flips only
together with the covering hypothetical, that is the `specs/neither-half-works-alone.md`
shape exactly — neither half works alone — and the two must then be sequenced
index-first with a deploy between, because the rewrite can reach production
before the index and the page gets slower if it does. **If neither flips**, the
candidate is closed: the item side is not addressable at this window, the honest
finding is that reading 4.5M rows is what this aggregate costs on this schema,
and the next place to look is whether the dashboard needs a live `top_products`
at all rather than a precomputed one — which is a different candidate, not a
variant of this one, and is not priced here.

---

## 9. If B and C pass — what the migration task needs

`contracts/checks/index_migration_only.py` proves every step is a
`CreateIndexStep` and nothing more. It does not prove the index is the right
index, and `contracts/dd-index-migration.yaml` says in its own header that
**the column order is verified by no check at all**. So the follow-up task is
handed the exact thing to write, and a reviewer is handed the numbers to hold it
to.

**Do not queue this as a chained link of this task.** Chained links are built and
verified independently, so a migration link would be written without the result
that decides whether it should exist. Queue it afterwards, from a filled §6, or
not at all.

**The DDL, as `CreateIndexStep` arguments:**

```python
CreateIndexStep(
    table="order_items",
    index="ix_analytics_order_items_order_covering",
    columns="order_id) INCLUDE (wc_product_id, product_name, total, quantity",
)
```

**That `columns` value needs checking before it is written, and the follow-up
task must check it rather than copy it.** `CreateIndexStep` renders `columns`
straight into `CREATE INDEX ... ON {schema}.{table} ({columns})`
(`api/analytics/migrations/migration.py:142`), so an `INCLUDE` clause can only be
expressed by closing the parenthesis inside the string — which works, and reads
as a trick, and puts a bracket-balancing act in the one field no check verifies.
The alternative is a plain composite `(order_id, wc_product_id, product_name,
total, quantity)`: same columns, same index-only coverage, no string trick,
slightly larger internal nodes and no `INCLUDE` semantics. **Both must be priced
in step 4 before one is written** — add the composite as a second hypothetical
and compare size and plan. If they price the same, take the composite; it is the
one a reviewer can read.

**Index name:** `ix_analytics_order_items_order_covering`, following
`ix_analytics_orders_customer_created` and `ix_analytics_order_items_order` —
`ix_analytics_` + table + what it is on.

**Every tenant schema, not one.** `discover_tenant_ids`
(`api/analytics/migrations/runner.py:144`) walks every schema matching
`^analytics_[0-9]+$`, so the migration applies everywhere, and the cost is paid
per schema. `analytics_1` (679,917 orders), `analytics_2` (2,887,844) and
`analytics_12` (802,396) are the three named in the tree. **Only `analytics_2`
will have been measured.** Give `analytics_2` its own window, the way v0014 gives
one to it and v0003 gave one to `analytics_12`.

**The file** is the next free version under `api/analytics/migrations/versions/`
after `api/analytics/migrations/versions/v0014_orders_customer_created_index.py`:

```
api/analytics/migrations/versions/v0015_order_items_order_covering_index.py
```

`version=15`, `transactional=False`, `unique` left false. The check refuses
anything else at the top level of that module, and refuses `unique=True`
outright.

**What the migration must NOT restate**, because `CreateIndexStep` supplies all
of it: `CONCURRENTLY` on a live schema, `IF NOT EXISTS`, the drop of an invalid
leftover from a failed concurrent build, and the `indisvalid` predicate.

**What the docstring must carry**, since it is the only place a reviewer gets the
evidence: the filled §6.3 and §6.4 numbers, the window they were taken on, the
real measured size and build time on `analytics_2` from §7, and — if it is true —
the fact that this index is a **precondition** rather than a speed-up, in the
same words v0014 had to use. The write cost belongs there too: `order_items` is
rewritten `DELETE`-then-`INSERT` per sync batch
(`api/analytics/services/sync_engine.py:618`, `:652`), so this index is
maintained on every re-sync of every order, not only on first load.

---

## What I could not establish

**Whether any of it is true.** The run did not happen. This task was queued
under a contract with no `evidence_queries`, so no evidence pack was assembled
and no pack file exists in this worktree; with no shell and no database
credential I could not run one statement of §4. **Every table in §6 reads `not
run`, and every performance claim in this document — the flip, the buffer saving,
the index size, the build time, the whole of gate C — is a prediction and not a
measurement.** The single exception is §1's column list, which is a fact about
the source tree and which I read out of it.

**Whether hypopg is installed, or installable.** `CREATE EXTENSION` is a
superuser act and every reader this fleet holds is SELECT-only, so I could not
check and the pack form in §5 cannot install it either. If it is absent and
cannot be added, the pricing stops at step 0 — that is a real outcome of this
task and not a failure of it.

**Whether hypopg honours the `INCLUDE` clause on the installed version, and
whether it models index-only scans faithfully on this table.** Both are assumed
by the procedure and neither is verified by it; A2 in §3 is the cheapest test I
could design for the first, and it is a test I have not run. The second is why
the predictor in §6.1 is asked for at all.

**No execution time exists for any index here, and none was obtained.** §7
proposes two ways to get one and performs neither; gate C is unreachable until
somebody builds a real index, and the recommendation to use
`CREATE INDEX CONCURRENTLY` is a recommendation, not an agreement to build.

**Whether the composite form or the `INCLUDE` form is the right one to write.**
§9 states the trade and refuses to pick, because picking would need the size and
plan comparison that §4 step 4 has not been run to produce.

**One tenant, one window, one box.** Everything asked for is `analytics_2` at
`2026-08-15 .. 2026-09-15`, and a migration would apply to every schema matching
`^analytics_[0-9]+$`. `analytics_1` and `analytics_12` would pay the size and the
write cost on evidence taken from neither of them.
