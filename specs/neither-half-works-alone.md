# The index and the rewrite are one change

**Measured 14 September 2026, on `analytics_2` — 2,887,010 orders.**

**EVERY FIGURE IN THIS DOCUMENT IS THE 30-DAY WINDOW** (`2026-08-15..2026-09-14`,
tenant 2) unless it says otherwise. That sentence was missing until the evening
of the 14th and its absence cost two wrong conclusions in one day — see "State
the window" at the end.

The dashboard endpoint took 21.3s. 85% of its SQL is one query, run twice, and
its plan sequentially scans every order to remove 2,063 of them, hash-joins to
1,724,169 rows, and sorts those to disk under a 4MB `work_mem` to produce
21,280. Eighty-one rows read and sorted for every one kept.

The obvious fix is a composite index on `(customer_id, created_at, id)`. **It
does nothing.** That is the finding, and it was one approval away from being
shipped as a 112MB index per tenant schema that changed no plan at all.

## What was measured, with `hypopg` — 30-day window

| | planner cost |
|---|---|
| today | 383,082 .. **392,785** |
| with the index, planner free to choose | 383,082 .. **392,785** — *identical; not chosen* |
| with `enable_seqscan=off`, `enable_hashjoin=off` | still not chosen; it takes `ix_analytics_orders_status` |
| the `LATERAL` rewrite, **no** new index | **4,094 ms executed** — *worse than the 3,410 ms it replaces* |
| **the rewrite _and_ the index** | 2,602 .. **73,194**, per customer `Limit (cost=0.06..4.00)` |

Each half alone is neutral or negative. Together the estimate falls 5.4× and
the sort disappears.

## Confirmed by execution, 14 September 2026 — 30-day window

The index was built — 1s on `analytics_1`, 5s on `analytics_2`, 26 MB and
112 MB, the planner's size estimate exact. Both halves are now measured against
the real thing rather than modelled:

| | executed |
|---|---|
| `_query_period_stats` before the index | 3,410 ms |
| `_query_period_stats` **with** the index | **3,602 ms** — plan identical |
| the `LATERAL` rewrite **with** the index | **252 ms** |

The plan with the index is unchanged in every respect that matters: the
sequential scan over 2,885,101 rows to remove 2,068 is still there, the
1,724,435-row external merge still spills 50,664 kB, and the query still uses
`ix_analytics_orders_created` rather than the new composite. **hypopg was
right**, by estimate and then by execution.

The rewrite with the index is a **14× reduction, executed**: no seq scan, no
sort, no spill, and a per-customer `Limit` costing 0.007 ms across 21,532
loops.

**Superseded 14 Sep 19:30 — see "State the window". The paragraph below
compares two endpoint timings whose windows were never recorded, so its
conclusion is not supported by its evidence. Kept because the reasoning is the
thing worth seeing.**

**And the dashboard's improvement in the same window was not this.** It went
21.3s to 9.1s while the index changed no plan, which resolves a gap this
document left open: the SQL only ever accounted for 6.5s of the 21.3s, and the
remainder was contention — the first figure was taken while the chain and the
test suite competed for two CPUs, the second on a box at load 0.03. Worth
stating because the index landing and the page getting faster in the same
afternoon is exactly the coincidence that would otherwise be read as cause.

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

## In production, 14 September 2026, 19:30

The rewrite merged as task 100 and the image was built at 19:19:57Z. Measured
after that, on a box at load 0.23–0.72, against the running API.

**The query, isolated, old form against new, same connection, medians of three:**

| window | `DISTINCT ON` | `LATERAL` |
|---|---|---|
| 30 days (`2026-08-15..2026-09-14`) | 2,711 ms | **260 ms** |
| 180 days (`2026-03-18..2026-09-14`) | 4,081 ms | 719 ms |

**252 ms was right.** The endpoint's own copy carries all nine output columns
rather than the two this comparison selects, so inside `dashboard_overview` it
runs 300–330 ms per call at 30 days and ~1,303 ms at 180.

**The endpoint, and where its time goes.** Every statement timed in process,
48 of them per request. **Medians of three warm passes**, which is not what the
first version of this table carried — it was one pass per window, and the
180-day column moved by up to 9% when repeated:

| | 30 days | 180 days |
|---|---|---|
| `_query_period_stats` × 2 | 622 ms | 2,675 ms |
| `top_products` | 619 ms | 1,251 ms |
| `_feed_health` | 115 ms | 147 ms |
| trends | 102 ms | 451 ms |
| customers totals | 84 ms | 83 ms |
| 36 × reconciliation breakdown | 89 ms | 96 ms |
| six others | 10 ms | 4 ms |
| **SQL** | **1,666 ms** | **4,717 ms** |
| **not SQL** | **25 ms** | **23 ms** |
| wall | 1,689 ms | 4,740 ms |

`top_products` is the largest single statement at the 30-day window: 619 ms in
one statement against 622 ms across the two `_query_period_stats` calls.

End to end over HTTP, warm: 30 days **1.71 s**, 90 days 2.88 s, 180 days
4.72 s. The public HTTPS route adds 50–130 ms. Independently: 1.77, 1.73,
1.69 s.

**So there is no non-SQL residue.** It is 24–26 ms at every window measured.
The "~2.6 s of the 9.1 s is not SQL" this document carried earlier was an
artefact of the same mistake as everything else here, and is withdrawn.

## State the window

The number that matters is a function of the window, and this document spent a
day quoting it without one. It cost two wrong conclusions:

* **"The dashboard improved 21.3 s → 9.1 s while the index changed no plan, so
  the remainder was contention."** Partly true at best. 9.12 s is the 30-day
  window with the old query; what window the 21.3 s was taken on was never
  recorded, so the two were never comparable and the contention story cannot be
  checked. It stands as unresolved rather than explained.

* **"The rewrite is deployed and the endpoint moved 0.34 s, so ~7 s of it has
  never been SQL."** The 8.78 s was taken before the image existed, and against
  a 30-day endpoint whose SQL I had been quoting from the same window all along
  without saying so. The rewrite saves 4.9 s of query time at that window, and
  the endpoint is 1.7 s.

Both readings were reasonable from the evidence as written. Neither survived
the window being stated. **A timing without its window is not a measurement.**

## What the day cost, and what it bought

One index, one query rewrite, and the machinery that turned out to be in the
way of both:

* **`api/analytics/migrations/**` was on the protected floor of every
  contract**, so no task this system had ever run could add an index. 040 made
  an index migration expressible; 041 made a declared waiver insufficient
  unless the database had granted it; `contracts/dd-index-migration.yaml` and
  `contracts/checks/index_migration_only.py` are the narrow hole the floor now
  has, and `api/alembic/**` stays floored entirely.

* **Eight places enforce that floor, and all eight were found by hitting
  them** — the boundary check, `rank.gate` gate 6, autodeploy's migration
  refusal, three refusals inside `enforce_contract_floor()`, the Python mirror
  in `runner/config.load_contract`, and `boundary.enforce` through two callers.
  The last two were found by a branch being refused by a gate it had already
  passed. They were found one at a time, each by a failure, which is the
  expensive way and was the only way available.

* **A ninth thing, in a different wall.** Task 100 was refused by a CHECK
  rather than a gate — a hand-maintained step tally in
  `test_migrations.py` that the index migration had moved and that had already
  been stale twice. 042 and `console/adopt.corroborate` are the answer: a check
  that fails identically on the base is not evidence about the branch.

Net: the dashboard's dominant query went 3,602 ms to 260 ms at the 30-day
window, and the system can now write a migration at all.

