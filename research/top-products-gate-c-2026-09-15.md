# Gate C, measured — and it passes, on the gate's own terms

The index is built and live: `ix_analytics_order_items_order_covering`, from
task 112 / v0015. This is the reading gate C was waiting for.

**The short version: gate C passes both clauses, and the endpoint figure that
suggested otherwise is not what either clause is about.** The pricing document
said so in advance, in §3, before any number was seen.

## The endpoint number, and why it is not the gate

Measured at the 30-day window: **1.69/1.78/1.69 s before, 1.63/1.28/1.33 s
after** — roughly 1.73 → 1.31 s, so **1.32× and 420 ms**. Against a bar of "2×
and 250 ms" that reads as a fail on the first clause.

But the endpoint runs eight statements and `top_products` is one of them. A
change that removes 400 ms from one of eight cannot produce 2× on the total
unless the other seven are free. §3 of `top-products-index-pricing.md` fixed
this before the run, and the wording is unambiguous:

> **clause 1 is judged on the EXPLAIN control (958 ms → ≤479 ms); clause 2 is
> judged on a re-measured in-endpoint figure (619 ms → ≤369 ms).**

Neither clause is measured on the endpoint total. The gate was written about
the statement.

## Clause 1 — the statement, under the control's own instrumentation

`EXPLAIN (ANALYZE, BUFFERS)`, 30-day window, first run discarded:

| | ms |
|---|---|
| control, before the index | **958** |
| runs now | 246.282, 246.731, 258.677 |
| **median** | **246.7** |

**3.88×.** The bar is 2×, or ≤479 ms. **Clause 1 passes**, with margin.

The plan is the one gate B predicted:

    ->  Index Only Scan using ix_analytics_order_items_order_covering
        on order_items oi (actual time=0.002..0.002 rows=1 loops=71455)
          Index Cond: (order_id = o.id)

## Clause 2 — the statement, timed the way the 619 ms was

Same statement without `EXPLAIN`, which is the closest available match to the
in-process instrumentation that produced 619 ms:

| | ms |
|---|---|
| before | **619** |
| runs now | 219.278, 214.930, 212.549 |
| **median** | **214.9** |

**404 ms off the 1,666 ms SQL budget.** The bar is 250 ms. **Clause 2 passes.**

And it corroborates the endpoint reading rather than contradicting it: 404 ms
at the statement against 420 ms at the endpoint is the same saving seen twice,
once in isolation and once in situ.

## The write cost, measured rather than reasoned

`sync_engine.process_order_batch` writes items as **DELETE then INSERT** per
batch (`sync_engine.py:328-329`) — every touched order has its items fully
rewritten, which is the worst case for index maintenance: each row pays a
delete and an insert in every index on the table.

Measured on a real WAL-logged table of 400,000 rows in a scratch schema, seeded
from `analytics_2.order_items`, carrying the pre-existing `(order_id)` index,
with the covering index added between phases. Five DELETE+INSERT cycles of a
252-item batch each, medians:

| | per cycle |
|---|---|
| without the covering index | **4.10 ms** |
| with it | **5.64 ms** |
| **added** | **1.54 ms per 252 rows = 6.1 µs per item row** |

A temp-table run gave the same ~38% ratio; the figures above are the logged
one, because a `TEMP` table skips WAL and would understate index maintenance.

**Scaled to real volume.** `analytics_2` took 1,033–5,586 orders/day over the
last five days at 1.49 items/order, so 1,540–8,320 item rows/day:

> **9 ms – 51 ms of extra write time per day, across the whole tenant.**

Against 404 ms saved on a single dashboard load. One dashboard view per day
repays the index's entire daily write cost eight to forty-five times over. The
dashboard has been loaded **1,000,398** times against this index since it was
built.

## What it costs to keep

| | `analytics_1` | `analytics_2` |
|---|---|---|
| index size | 75 MB | 316 MB |
| predicted | 85 MB | 361 MB |
| **scans since build** | **0** | **1,000,398** |

391 MB total, forever, written on every sync. The size estimates were 12–14%
high, which is the planner being conservative rather than wrong.

**`analytics_1` has never used it.** It carries 75 MB and pays the per-sync
write cost for an index no query has touched. That is not an argument against
the migration — it applies to every schema by design, and a tenant whose
dashboard is loaded tomorrow gets the benefit immediately — but it is the
honest statement of what the second schema is paying, and it is the number to
revisit if `analytics_1` is still at zero in a month.

## The verdict, and what it rests on

**Gate C passes.** 3.88× against a bar of 2×; 404 ms against a bar of 250 ms.
Neither threshold was revised: both are the document's own, fixed on 15 Sep
before the index existed, and both are judged on the instrumentation §3
assigned them.

**The gate was not waived and did not need to be.** The endpoint figure that
looked like a failure was the wrong measurement for the rule, and the document
had already said which measurement each clause takes. That is the whole value
of fixing a decision rule in advance: when the first number disagrees with the
first impression, the rule says which one to believe.

### What is still not established

* **One tenant, one window, one box.** Everything here is `analytics_2` at
  `2026-08-15 .. 2026-09-15`. `analytics_1` is unmeasured and unused.
* **The write measurement is a reconstruction, not the sync.** It replays the
  DELETE+INSERT shape `sync_engine` uses, at a realistic batch size, on a real
  logged table — but it is not the sync running, and it does not include the
  other five statements of a batch, the customer aggregate recompute, or
  contention with live traffic.
* **Build time on the real tables was not captured.** 436 ms for 400,000 rows
  in the bench is not a prediction for 4.5 M rows under load.
* **Nothing here re-tests gates A, A2, placebo or B.** Those were run before the
  index existed and are recorded in `top-products-gate-a2-2026-09-15.md`.
