# The index and the rewrite are one change

**Measured 14 September 2026, on `analytics_2` — 2,887,010 orders.**

The dashboard endpoint took 21.3s. 85% of its SQL is one query, run twice, and
its plan sequentially scans every order to remove 2,063 of them, hash-joins to
1,724,169 rows, and sorts those to disk under a 4MB `work_mem` to produce
21,280. Eighty-one rows read and sorted for every one kept.

The obvious fix is a composite index on `(customer_id, created_at, id)`. **It
does nothing.** That is the finding, and it was one approval away from being
shipped as a 112MB index per tenant schema that changed no plan at all.

## What was measured, with `hypopg`

| | planner cost |
|---|---|
| today | 383,082 .. **392,785** |
| with the index, planner free to choose | 383,082 .. **392,785** — *identical; not chosen* |
| with `enable_seqscan=off`, `enable_hashjoin=off` | still not chosen; it takes `ix_analytics_orders_status` |
| the `LATERAL` rewrite, **no** new index | **4,094 ms executed** — *worse than the 3,410 ms it replaces* |
| **the rewrite _and_ the index** | 2,602 .. **73,194**, per customer `Limit (cost=0.06..4.00)` |

Each half alone is neutral or negative. Together the estimate falls 5.4× and
the sort disappears.

## Why

`DISTINCT ON (customer_id) … ORDER BY customer_id, created_at, id` over a set
of customers is not a question a btree can answer. Postgres has no loose or
skip index scan, so "the first order per customer" means reading every matching
row for those customers and reducing it — the index changes which rows are read
and not how many. The semi-join `customer_id IN (window_customers)` then makes
the planner prefer a sequential scan and a sort regardless of what indexes
exist.

`LATERAL … LIMIT 1` asks the question **once per customer**, and `LIMIT 1` is
what lets an index stop after one entry. That shape needs the index to be
cheap; the index needs that shape to be used at all.

## The trap this nearly walked into

Two of them, and both were caught by measuring rather than reasoning.

**The partial index looked ignored and was not.** `hypopg` does not model
partial-index predicates, so `… WHERE status IN ('completed','processing')`
appeared to be refused by the planner. A control — a hypothetical
`billing_email` index, 83,177 → 421 — proved the tool works, and the plain
composite *is* chosen on a simpler query. Reported without that control, it
would have been a finding about Postgres that was really a finding about
`hypopg`.

**"Build the index and measure nothing" was the plausible path.** It is the
version that gets approved: one migration, one index, a familiar shape, no
rewrite to review. It would have cost 112MB per schema, several minutes of
`CONCURRENTLY` build on 2.9M rows, and changed the plan not at all — and the
page would still have taken 21.3s, with an index sitting there as evidence that
somebody had tried.

## What this means for how the two tasks are sequenced

They are one change in two repositories' worth of gates:

* the index is a migration, so it merges under `dd-index-migration` and
  **deploys only by hand** — `console/autodeploy` refuses any range containing
  one;
* the rewrite is ordinary API work under `deadly-digital-platform-api.yaml`,
  which **auto-merges and auto-deploys**.

So the rewrite can reach production before the index does, and if it does, the
page gets **slower** — 4,094 ms against 3,410 ms, measured. The order is not a
preference.

**The loop cannot sequence this itself.** `task_chain` exists and `automerge`
honours it, but `CHAIN_READY = ("READY_FOR_REVIEW", "MERGED")` — a link is
satisfied when its sibling is *ready for review*, which is before it is merged,
let alone deployed. Nothing in the chain can express "wait until the index is
live in production", and the information needed to express it
(`console/deploys` knows the running sha) is not wired to any gate.

Queue them one at a time, index first, and deploy between. See
`040_an_index_is_not_a_schema_change.sql` for why the index needs a migration
at all.
