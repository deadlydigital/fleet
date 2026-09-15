# Price the `top_products` covering index before anything writes it

```fleet-spec
work_type: research
repo: fleet
contract: research.yaml
title: Price the top_products covering index with hypopg and a control, and decide before a migration is written
writable_paths:
  - research/top-products-index-pricing.md
```

## What this is, and why it is research and not a migration

`top_products` is the largest single statement on `GET /api/analytics/dashboard`:
**619 ms** of the endpoint's 1,666 ms of SQL at the 30-day window, and **958 ms**
measured alone under `EXPLAIN (ANALYZE, BUFFERS)`. Its plan parallel-seq-scans
all **4,546,466** rows of `analytics_2.order_items` to keep the **104,840** that
belong to the window's orders — 43 read per row kept, 45,271 buffers off disk,
244 ms of that in I/O. The orders side is already served by
`ix_analytics_orders_created` and costs 25 ms, so the item side is the whole
cost. All of that is measured and cited:
`research/candidates-dashboard-remaining-2026-09-14.md`, section "Daily —
`top_products` reads every order item to find a month's worth", at platform
`fd20133`.

What is **not** measured is whether any index changes that plan.
`ix_analytics_order_items_order` already exists on `order_id` and the planner
declines it: on its estimates a hash join over the whole table beats 23,571
index probes. A covering index — `(order_id) INCLUDE (wc_product_id,
product_name, total, quantity)` — is the obvious thing to try and it is exactly
the kind of obvious thing this thread has already been wrong about once. On
14 September a composite index on `orders` was assumed to be the fix, was built,
and **changed no plan at all**; the fix was the query shape. That is recorded in
`specs/neither-half-works-alone.md` and it is the reason this spec buys a
measurement rather than a migration.

So the deliverable is one document that prices the index, states a decision rule
**before** it sees a number, and either hands the follow-up task its DDL or kills
the candidate. No migration is written by this task. If the pricing says yes, the
migration is a separate task under `contracts/dd-index-migration.yaml`, where it
is reviewed by a person and deployed by hand.

**Not a two-link chain.** `draft_spec_shape.py` would accept a second
`fleet-spec` block for the migration, and it would be wrong here: chained links
are built and verified independently, so the migration link would be written
without the result that is supposed to decide whether it exists at all. Queue
the migration afterwards, from this document, or do not queue it.

## How the numbers get into the document

State this plainly because it shapes every requirement below.
`contracts/research.yaml` gives the agent Read, Grep, Glob, Write, Edit,
WebSearch and WebFetch. **No shell and no database**, deliberately — and unlike
`contracts/research-metorik-gap.yaml`, it carries no `evidence_queries`, so
`runner/cycle.py` assembles no evidence pack for it. The agent can read the
platform checkout and nothing else.

Two ways to run this, and the spec supports both:

* **As queued.** The task delivers requirements 1, 2, 3, 6 and 7 in full — the
  statement's real shape, the two plans, the runnable pricing SQL, the decision
  rule and the alternatives — with every measured cell in the result tables
  marked `not run`. A person runs the SQL and fills them, which is the division
  that produced `research/task-102-measurement-2026-09-15.md`.
* **With a pack.** A human adds the queries of requirement 3 to a research
  contract as `evidence_queries` before queueing, and the task fills the tables
  itself. Requirement 3 therefore writes them in the shape `run_queries` takes —
  a `key`, a `reader`, and one `sql` — so that paste is mechanical. Editing a
  contract is a human act: `contracts/**` is on the fleet floor for every task,
  including this one.

What the document must never do is estimate a cell it did not measure. An
unfilled table is honest; a plausible number is the failure this whole thread
exists to stop.

## Requirements

### 1. The statement's real shape, read from the engine and quoted

The SQL is in the analytics engine, and the candidate's own probes locate it —
three occurrences of `FROM {schema}.order_items oi`, three of the join to
`orders`, one `SUM(oi.quantity) AS quantity_sold`:

    api/analytics/services/analytics_engine.py

Quote the `top_products` statement verbatim in the document and record, as a
list: every column of `order_items` it reads, the join predicate, the
`GROUP BY`, the `ORDER BY`, and the `LIMIT`.

The point of this is falsifiable and it comes first: **if the statement reads any
column of `order_items` outside `(order_id, wc_product_id, product_name, total,
quantity)`, the proposed INCLUDE list cannot produce an index-only scan and the
candidate index is wrong as written** — the heap fetch it was supposed to avoid
happens anyway. Say so, and give the corrected column list, before pricing
anything. There are three call sites; if they do not read the same columns, say
which one the dashboard runs and price that one.

### 2. The two outcomes, named before the run

Write down, before any EXPLAIN output appears in the document, what each result
would mean:

* **The plan flips.** The parallel seq scan becomes an index scan on
  `order_items` driven by the window's ~23,571 order ids, and the win is the
  45,271 buffers and 244 ms of I/O that the full scan currently pays.
* **The plan does not flip.** The planner still estimates 104,840 probes plus
  heap access as dearer than a 4.5M-row parallel scan — which is what it already
  concludes about `ix_analytics_order_items_order`, so this is the *expected*
  outcome, not the surprising one. The covering columns change that estimate only
  by removing the heap access; they do not change the probe count.

A document that only explains the result it got is a document that would have
explained either.

### 3. The pricing procedure, written as runnable SQL

One fenced block per step, runnable as pasted against `analytics_2`, every
statement carrying the same explicit window so the numbers are comparable:

1. **Control.** `EXPLAIN (ANALYZE, BUFFERS)` of the statement as it runs today.
2. **The hypothetical covering index.**
   `CREATE EXTENSION IF NOT EXISTS hypopg;` then `hypopg_create_index('CREATE
   INDEX ON analytics_2.order_items (order_id) INCLUDE (...)')`, then `EXPLAIN`
   — **no ANALYZE**: a hypothetical index cannot be executed, and asking for one
   is an error rather than a slower answer.
3. **Its size**, from `hypopg_relation_size()`, because an index on a 4.5M-row
   table is also a write cost on every sync and a disk cost forever.
4. **Reset**, `hypopg_reset()`, between every step.

`CREATE EXTENSION` is a superuser act and the readers this fleet holds are
SELECT-only. If hypopg is not installed and cannot be installed, the pricing
stops there and the document says so rather than substituting a guess — that is
a real possible outcome of this task and it is not a failure of it.

### 4. The control, which is the part that was missing last time

`hypopg` models the planner's estimates. That it produces a cheaper plan is not
evidence the real planner will, so the run must first show that hypopg agrees
with a fact already known to be true:

* **Calibration.** Price a hypothetical *bare* `(order_id)` index — the index
  that already exists and is already declined. It must **not** flip the plan. If
  it does, hypopg is not modelling this planner and every number after it is
  suspect; stop and report that.
* **Placebo.** Price a hypothetical index that cannot serve the query at all
  (`(product_name)` will do). It must not flip the plan either.
* **Return to control.** Re-take the control EXPLAIN after `hypopg_reset()` and
  show it matches the first one, so the session is where it started.

Every timing states its window, and every execution figure is the median of
three warm runs with the first discarded. `specs/neither-half-works-alone.md`
says why in its own words: *a timing without its window is not a measurement*,
and that document cost a day and two withdrawn conclusions to learn it.

### 5. What a true execution time costs, proposed and not performed

A plan flip is necessary and not sufficient: only a real index gives a real
execution time. Set out both ways of getting one and what each costs on a live
table, and **propose** rather than perform:

* `CREATE INDEX` inside a transaction that is rolled back. Cheapest to clean up
  — the rollback leaves nothing behind — but a non-concurrent build takes a
  SHARE lock, which blocks writes to `analytics_2.order_items` for the length of
  the build while leaving reads alone. The sync path writes that table.
* `CREATE INDEX CONCURRENTLY`, then measure, then `DROP INDEX CONCURRENTLY`. No
  write blocking, a slower build, two passes over 4.5M rows, and a real index
  that exists until it is dropped — including if the session dies, which is what
  `CreateIndexStep`'s invalid-leftover drop exists to clean up.

Name which one is recommended, what it is expected to cost in wall clock and
disk, and leave the decision to the person who runs it. Do not write a document
that reads as though the build has already been agreed.

### 6. The decision rule, written before the numbers and applied after

Three gates, in order, each with its consequence stated:

* **A — calibration.** Bare `(order_id)` does not flip. If it flips, the run is
  void; report and stop.
* **B — the flip.** The covering hypothetical flips the plan to an index scan on
  `order_items`. **If it does not, the candidate dies here.** The document says
  the item side is not addressable by this index, no migration is written, and
  requirement 7 is what is left.
* **C — the size of the win.** A migration on this path deploys by hand, so it
  has to be worth a person's deploy. The bar: the real measured statement at the
  30-day window must be at least **2× faster** than the 958 ms control **and**
  take at least **250 ms** off the endpoint's 1,666 ms SQL budget. Below that,
  record the number and recommend against — a 1.71 s page does not get a
  hand-deployed schema change for 10%.

If the thresholds in C are wrong, argue them in the document and use better
ones. What is not acceptable is choosing them after seeing the result.

### 7. What to price instead if the index dies, and what to hand on if it lives

**If B or C fails.** Say what is left and price what can be priced at hypopg
cost. The `LATERAL` answer from task 100 does not transfer — this shape has no
per-group `LIMIT` to exploit and the aggregate genuinely needs every matching
item — so do not propose it by analogy. The one shape worth pricing is whether
feeding the planner the window's order ids differently (a semi-join, or
`= ANY(...)` over the ids the orders side already produces in 25 ms) changes the
estimate that is currently declining the existing index, since the refusal is an
estimate about probe count rather than about the index.

**If B and C pass.** Hand the follow-up task everything it needs, because the
contract it runs under verifies structure and not content:
`contracts/checks/index_migration_only.py` proves every step is a
`CreateIndexStep` and nothing more, and `contracts/dd-index-migration.yaml` says
in its own header that **the column order is verified by no check at all**. So
the document carries the exact DDL, the index name in the convention the tree
already uses (`ix_analytics_orders_customer_created`,
`ix_analytics_order_items_order`), the fact that it must be created in every
tenant schema rather than one, and the measured numbers a reviewer can hold it
to. The migration file will be the next free version under

    api/analytics/migrations/versions/

after

    api/analytics/migrations/versions/v0014_orders_customer_created_index.py

and `CreateIndexStep` supplies CONCURRENTLY, IF NOT EXISTS, the invalid-leftover
drop and the `indisvalid` predicate, so the migration does not restate them.

## Notes for whoever writes it

**The limits section is required and is not a formality.**
`contracts/checks/research_document_shape.py` refuses a document with no
heading admitting what could not be established, and refuses one whose
admission is under 40 words. Here that section has real content: whether the run
happened at all, whether hypopg was installable, whether a real build was
performed or only proposed, and — if the tables are unfilled — that every
performance claim in the document is a prediction.

**Markdown only.** The same check fails the diff if it touches a non-markdown
file, so the SQL lives in fenced blocks inside the document. It cannot be a
sibling `.sql` file, however much `research/task-102-timing.sql` looks like a
precedent; that file was committed by a person, not produced by a research task.

**Platform paths appear in code blocks above rather than inline spans.** The
draft-spec check resolves inline path citations against the repository this
block names, which is `fleet`. The research document has no such problem —
`research_document_shape.py` resolves citations against both checkouts — so
cite the engine and the migration files inline there, in full from the
repository root.

**The filename carries no date** (`research/top-products-index-pricing.md`),
unlike most of `research/`, because the document's date is the date of the run
and a filename fixed at queue time would disagree with it. The document itself
must carry a date; the shape check requires one no more than seven days old.
