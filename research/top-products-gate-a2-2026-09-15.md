# Task 105's gate A2, run — and gates A, placebo and B with it

**Not produced by task 105.** That task had no shell, no credential and no
evidence pack, and `research/top-products-index-pricing.md` is careful to say
so: every row of its §6 reads `not run` and every performance claim in it is
labelled a prediction. Nothing here changes that document and it should not be
re-run. This is the reading it designed and could not take, taken afterwards by
a session that had a database, and recorded beside it.

Run 15 Sep 2026 against `analytics_2`, read-only. No index was created.

## Gate A2 — does hypopg honour the `INCLUDE` clause?

The document's own words: *"A2 in §3 is the cheapest test I could design for the
first, and it is a test I have not run."*

| hypothetical | `hypopg_relation_size` |
|---|---|
| bare `(order_id)` | **101 MB** (106,201,088 bytes) |
| covering `(order_id) INCLUDE (wc_product_id, product_name, total, quantity)` | **361 MB** (378,355,712 bytes) |

3.56×. The gate's void condition is "within a few percent of each other", so it
is not close. **hypopg 1.4.2 is installed and honours the clause.** The run is
not void on this count, and the `What I could not establish` entry that named
this is now closed.

## Gates A, placebo and B — the plan, at the same window

The document's §4 procedure, pasted and run. The scan node on `order_items`:

| step | hypothetical | node on `order_items` |
|---|---|---|
| 1. control | none | `Parallel Seq Scan` |
| 2. gate A — calibration | bare `(order_id)` | `Parallel Seq Scan` — **no flip, as required** |
| 3. placebo | `(product_name)` | `Parallel Seq Scan` — **no flip, as required** |
| 4. gate B | the covering candidate | **`Index Only Scan`** |

Gate A passes: the index that already exists and is already declined does not
flip the plan hypothetically either, so hypopg is modelling this planner.
The placebo passes: an index that cannot serve the query does not flip it.
**Gate B passes, at the strongest of the three outcomes the document named** —
not `Index Scan` but `Index Only Scan`, the heap avoided to the degree the
visibility map allows.

## Gate C is still unreachable, and that is the document's own finding

Gate C needs a REAL measured execution time against a REAL index, and the two
ways to get one are §7's proposals, neither performed. The hypothetical costs
the planner prints are estimates, not times, and this note does not offer them
as a substitute. Nothing here passes gate C and nothing here recommends the
migration.

## What made the run possible

Two things the document correctly identified as missing:

* **the grant.** `dd_detector_login` could not read `analytics_2.order_items`
  at all — `permission denied`, and the table was not even visible in
  `information_schema`. Granted by `dd_047_the_evidence_reader_can_see_order_items.sql`.
  Gate A2 needs only catalog access and would have run without it; gates A and
  B are `EXPLAIN` over the real statement and could not.
* **the pack.** §5 of the document is a ready-to-paste `evidence_queries` block
  written against `runner/evidence.py`'s real constraints, four of them derived
  with line numbers. All four were checked independently and all four are
  correct. That block now has a route to a task: `evidence_queries` may be
  declared on a `fleet-spec` block and is frozen onto the task.

A re-queue carrying §5's block would fill §6 itself. That is the document's own
proposal and it now works; whether the pricing is worth re-queueing is a
separate decision, and gate C's bar — 2× and 250 ms for a hand-deployed schema
change — is unchanged and was fixed before any number was seen.
