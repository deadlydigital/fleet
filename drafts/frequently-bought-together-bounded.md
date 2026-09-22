# Draft spec — frequently bought together, bounded to a window, a minimum pair support and a cap

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Frequently bought together, bounded to a window, a minimum pair support and a cap on pairs returned
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/products.py
```

## Everything numeric below is GIVEN. Nothing is to be measured

The agent that builds this gets `Read`, `Edit`, `Write`, `Grep` and `Glob` and
no shell, no database and no network. Every figure in this spec was taken by
somebody else on `analytics_2` and is cited to the document that holds it. Cite
them as stated facts; do not re-derive them and do not claim to have taken them.

| figure | value | source |
|---|---|---|
| `order_items` rows | 4,550,334 | `research/metorik-report-classification-2026-09-15.md:442` |
| distinct `wc_product_id` | 3,743, with `product_name` set on every line | `research/metorik-report-classification-2026-09-15.md:836` |
| `order_items.total` non-zero | 4,447,939 of 4,550,334 (97.8%), NOT NULL throughout | `research/metorik-report-classification-2026-09-15.md:443` |
| orders with `total = 0` — the legal free-entry route | 66,764 of 2,890,319 (2.3%), spanning the whole history | `research/metorik-report-classification-2026-09-15.md:548` |
| of those, status `completed` | 66,676, so they sit inside `_REVENUE_STATUSES` | `research/metorik-report-classification-2026-09-15.md:549` |
| line rows inside free-entry orders | 73,378, of which 71,122 are themselves zero-value | `research/metorik-report-classification-2026-09-15.md:552` |
| the index this query needs | `ix_analytics_order_items_order_covering`, on `(order_id, wc_product_id, product_name, total, quantity)`, composite | `specs/v0015-order-items-covering-index.md` |

Two figures follow from those by arithmetic and they are the two that shape the
design, so they are written out rather than left to be noticed:

* **73,378 ÷ 66,764 = 1.10 line rows per free-entry order.** At most 6,614 of
  the 66,764 can carry a second line at all, so **at least 60,150 of them
  contribute no pair whatever** — a pair needs two distinct products in one
  order.
* **102,395 line rows carry `total = 0`** (4,550,334 − 4,447,939), and 71,122 of
  those sit inside free-entry orders, so **31,273 zero-value line rows sit in
  orders that are not free entries.**

## Why this is a code change and not an investigation

Nothing pairs products anywhere in the tree. `research/candidates-metorik-gap-2026-09-21.md`
records it at candidate 8: the engine ranks products, compares two of them and
names a top product per churn tier, and no co-occurrence expression exists in
the engine or on any route. `research/metorik-report-classification-2026-09-15.md:851`
classifies the report bucket **A** — buildable from populated columns — on the
grounds that it is a self-join of `order_items` on `order_id`, over columns the
evidence pack found populated throughout.

Batch 16 dropped the row with a reason rather than a shrug:
`research/candidates-metorik-gap-2026-09-16.md:143` — *"a self-join over 4.55M
line rows needs a bound before it is unattended work"*. Half of that is now
answered by the tree. Migration 0015 built
`api/analytics/migrations/versions/v0015_order_items_order_covering_index.py`,
a composite leading on `order_id` and carrying `wc_product_id`, `product_name`,
`total` and `quantity` — which is exactly what a self-join on `order_id` seeks,
with the projected columns covering so the scan can stay index-only.
`research/top-products-index-pricing.md:96` is where the column set was
established against the statements that already exist.

The other half is not the agent's judgement to exercise, so this spec fixes it:
**a date window, a minimum support per pair, and a cap on pairs returned.** With
those three fixed this is moderate work. Without them it is a cross product over
a table with 4,550,334 rows and no upper bound on what comes back, which is the
thing batch 16 refused.

## Why this contract

Two contracts in `contracts/` cover `api/analytics/routes/products.py`:
`contracts/dd-docstring-proving.yaml` and
`contracts/deadly-digital-platform-api.yaml`. Only the second covers
`api/analytics/services/analytics_engine.py` — the first is `dd_docs`, caps the
diff at 30 lines and protects the services tree entirely, because it exists to
prove docstrings and not to add aggregates. A third `dd_api` contract for this
repo, `contracts/dd-order-filters.yaml`, makes exactly
`api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`
writable and covers neither path here.

So `contracts/deadly-digital-platform-api.yaml` is named, with its cost stated:
twenty-seven files writable where this needs two, and `auto_merge: true`, so
nobody reads this spec against the diff. What it buys is the only thing that can
check the claims below — one new `api/tests/analytics/test_fleet_*.py` is
creatable, and `contracts/checks/new_test_bites.sh` proves the added test fails
against the tree before the change. A support floor that is applied in Python
after an unbounded aggregate, a pair counted twice because a product appears on
two lines of one order, a mirrored duplicate: none of those is visible to a
contract with no test gate.

Because nobody reads the spec, `contracts/checks/spec_requirements_cited.py`
runs first and obliges the diff to cite each of `spec:1` through `spec:5` on a
line this change adds — a comment, a docstring or a test name.

## The five ways to get this wrong

1. **An unbounded self-join.** No window, or a window the caller may omit, and
   the statement pairs every line row against every other line row in its order
   across the whole history. This is batch 16's objection and it is the reason
   requirement 2 exists.
2. **A pair counted more than once per order.** An order with the same product
   on two lines — a second entry, a re-add — joins to itself twice and inflates
   support. Support is a count of **orders**, not of line pairs.
3. **Mirrored pairs and self-pairs.** An unconstrained self-join returns (A,B),
   (B,A) and (A,A). Two of those are noise and one of them doubles the row count
   for nothing.
4. **Grouping on `product_name`.** A product renamed mid-window pairs against
   half of itself, and the same two products appear as two pairs. The engine's
   existing `product_report` groups by `(wc_product_id, product_name)`, which is
   defensible for a ranking and wrong here.
5. **A cap applied silently.** A `LIMIT` with nothing saying it bound reads as
   "these are all the pairs there are". `api/analytics/routes/products.py`
   already carries `coverage` and `truncation` blocks on `/products/acquiring`
   under the comment *"No silent caps"*; this endpoint has the same obligation.

## What to build

Five requirements.

### 1. `product_pairs()` in `api/analytics/services/analytics_engine.py`

One function beside `product_report`, taking a tenant, a bounded date range, a
minimum support, a cap, and the free-entry mode of requirement 3. It returns the
pair list, the per-product names, and the blocks requirements 2 and 3 describe.

* **Reuse the population the module already uses**, without forking it: the same
  `_REVENUE_STATUSES` as the module defines it rather than a status list written
  into this statement, the same `range_predicate`/`range_params` convention from
  `api/analytics/services/date_range.py`, the same `schema_exists()` guard
  returning an empty result rather than raising, the same
  `analytics_schema_name()`. A pair list whose window disagrees with the
  `/products` ranking beside it on the same page is worse than no pair list.
* **One statement, built as CTEs.** The orders side first — the ids inside the
  window with a revenue status, each carrying whether `orders.total = 0`; then a
  **`DISTINCT` projection of `(order_id, wc_product_id)`** from `order_items`
  joined to it, which is what makes support a count of orders and not of line
  pairs; then the self-join; then the per-product order counts; then the final
  select. The `DISTINCT` is failure 2 and it is one word in the right place.
* **Read only the five covered columns** of `order_items` —`order_id`,
  `wc_product_id`, `product_name`, `total`, `quantity` — and no sixth. That set
  is what `ix_analytics_order_items_order_covering` carries, and a sixth column
  puts a heap fetch back into the join this task is being allowed to write
  because the index removed it. `research/top-products-index-pricing.md:111`
  records what a sixth column did to `product_category_report`, which is the
  one statement in the module the index cannot serve.
* **Exclude line rows whose `wc_product_id` is NULL** in the projection CTE. A
  line with no product id cannot be half of a pair, and joining on a NULL is a
  silent no-op rather than an error.
* **Never interpolate a date, a product id, a support floor or a limit into the
  SQL string.** They are bound parameters. The schema name is the only thing
  interpolated, as it already is everywhere else in this module.

### 2. The three bounds, applied in the database and reported in the response

The bounds are the reason this row was reopened, so they are not defaults the
caller may drift past.

* **The window is required and it is capped.** Both `start` and `end` must be
  given; a missing bound is a 400 and not a guess at the last 30 days. A window
  longer than **366 days** is a 400 naming the limit — the span of the data is
  the whole history since 2023-03-15, and a caller who asks for all of it is
  asking for the unbounded query. Put the ceiling in one named module-level
  constant, not in a literal inside the route.
* **The minimum support is a `HAVING` inside the statement.** Default **5**,
  floor **2**, rejected below that with a 400: a pair seen once is not a pattern
  and admitting it makes the result set the size of the cross product. Filtering
  in Python after the aggregate satisfies the letter of this and none of its
  purpose — the point is that the database never materialises the long tail.
* **The cap is bound, defaulted to 50 and hard-capped at 200**, applied as
  `ORDER BY support DESC` with a deterministic tiebreak on the two product ids
  ascending, so two calls with the same arguments return the same rows in the
  same order.
* **The cap is reported, never silent.** Carry `COUNT(*) OVER ()` on the
  support-filtered set so the response can state how many pairs met the support
  floor alongside how many were returned, and a `truncated` flag that is true
  exactly when those differ. This costs no second statement and it is failure 5.
* **An empty window is an empty list and a 200.** No orders in range, or none
  with two distinct products, returns `pairs: []` with the window, support and
  cap blocks populated. It is not a 404 and it is not an error.

### 3. Free entries are named in the response, whichever way they are counted

This is the warning the candidate asked to have written into the spec rather
than discovered in a retrospective, and the given figures change what it means.

**The default is to include them, and to say so.** The 16 September correction
in `research/metorik-report-classification-2026-09-15.md:575` is explicit that
free entries are real orders placed by real customers, that the defect is
confined to means and distributions, and that the repair *"is a labelling
problem rather than a filtering one"*. A pair count is a count of orders, so the
honest default is the one that counts them and labels them.

* Accept a `free_entries` parameter with two values — include (default) and
  exclude. Exclude drops orders where `orders.total = 0` in the orders CTE,
  before any join, so they leave both the pair counts and the denominator
  together.
* **Always return a `free_entries` block**, whichever mode ran: the mode, the
  rule in words (`orders.total = 0`), and the number of orders in the window the
  rule removed — which is zero in include mode and is still stated. Take that
  count with a `FILTER` aggregate over the orders CTE rather than a second
  statement.
* **The block must say what exclusion does not do**, in the response and in the
  docstring: excluding free-entry *orders* does not remove free-entry *products*
  from orders that were paid for. The arithmetic near the top of this spec is
  why that sentence is not pedantry — 31,273 zero-value line rows sit in orders
  that are not free entries, and an order-level rule does not touch one of them.
* Do **not** add a line-level filter on `order_items.total = 0` in this task.
  See the closing section for why it is separate work.

### 4. A pair is a set of two distinct product ids, keyed on the id alone

* **Canonicalise in the join predicate**: `b.wc_product_id > a.wc_product_id`.
  One inequality removes self-pairs and mirrored duplicates and halves the work,
  and it is cheaper than deduplicating afterwards. This is failure 3.
* **Group on the two ids and nothing else.** `product_name` is resolved for
  display, not grouped on. Pick it deterministically per product — the name on
  the highest-revenue line for that product inside the window, ties broken by
  the most recent `orders.created_at` — and return it **once per product** in a
  block keyed by `wc_product_id`, not repeated on both sides of every pair. This
  is failure 4, and it also keeps the payload from restating 3,743 names.
* **Per pair return** `product_a`, `product_b`, `support` (orders containing
  both), `orders_a` and `orders_b` (orders in the same filtered population
  containing each), and the derived measures computed server-side:
  `confidence_a_to_b` = support ÷ orders_a, `confidence_b_to_a` = support ÷
  orders_b, and `lift` = support × window_orders ÷ (orders_a × orders_b).
* **The denominators cannot be zero and the code should say why rather than
  guard.** A pair only exists when support ≥ the floor, which is ≥ 2, and
  `orders_a` ≥ support and `orders_b` ≥ support. If a caller's window produces
  no orders there are no pairs, so requirement 2's empty case has already
  returned. Derive the measures here rather than in the page that follows: the
  rounding and the denominators are the semantics of the report, and a second
  implementation of them in TypeScript is a second place for them to differ.

### 5. `GET /products/pairs` in `api/analytics/routes/products.py`

A further endpoint on the existing router, taking `start`, `end`,
`min_support`, `limit` and `free_entries`.

* **Call the module's existing `_parse_window` helper** rather than writing a
  second date parser into a router that has one, and take the same
  `subscription_required` dependency the other routes take. Do not adopt the
  convention in `api/analytics/routes/orders.py`, which refuses one bound
  without the other; a third date convention in one module is how a page and its
  own pair list come to disagree about which days they covered.
* **Reject before querying**: an `end` before its `start`, a window over the
  366-day ceiling, a `min_support` below 2, a `limit` outside 1–200, an
  unrecognised `free_entries` value. Each a 400 naming the parameter and the
  bound. An out-of-range `limit` is not silently clamped — clamping is the
  silent cap of failure 5 wearing a different hat.
* **Declare it after `/products/acquiring`** and update the module docstring's
  route list. The router already serves `/products`, `/products/acquiring`,
  `/products/categories` and `/products/export`, and the docstring records that
  literal routes must be declared before any `/products/{id}` that could shadow
  them. `/products/pairs` is a fifth literal, so nothing shadows anything — but
  the docstring is where that fact is written down, and leaving it listing fewer
  routes than the module serves is how the next person gets it wrong.

## What must not change

**The four routes this module already serves, and their response shapes.**
`/products`, `/products/acquiring`, `/products/categories` and
`/products/export` are consumed by the products pages under
`platform/app/(dashboard)/analytics/`, which is protected under this contract,
so a shape change here breaks a surface this task cannot repair. Add; do not
edit.

**`product_report` and `product_category_report`.** The new function sits beside
them and reuses their helpers; it does not refactor them into a shared base. A
refactor here spends the production budget on files this task is not being
judged on.

**The schema.** No new column, no migration, no index.
`api/analytics/migrations/**` is protected under this contract and nothing here
wants a column: the statement reads `order_items.order_id`, `wc_product_id`,
`product_name`, `total` and `quantity`, and `orders.id`, `created_at`, `status`
and `total`, all of which exist and are declared in `api/analytics/models.py`.
The index this query wants already exists and was hand-deployed under
`contracts/dd-index-migration.yaml`; see `specs/v0015-order-items-covering-index.md`.

## The test

Create

    api/tests/analytics/test_fleet_product_pairs.py

which is the only creatable shape `contracts/deadly-digital-platform-api.yaml`
allows — one added `test_fleet_*.py` under `api/tests/analytics`, never a
modification to an existing test. `contracts/checks/new_test_bites.sh` runs it
against the tree before the change and refuses it if it passes there. Budget is
300 lines, separate from the 400 production lines. Read the existing test files
in that directory for fixture conventions and do not edit them.

The fixture needs the cases where a wrong implementation and a right one differ:

* an order carrying **the same product on two lines** → the pair it forms with a
  third product has support 1 from that order, not 2. This is the `DISTINCT`;
* two products co-occurring in **three** orders with `min_support=3` → present;
  with `min_support=4` → absent. Assert both against the same fixture, so a
  floor applied after the aggregate and one applied inside it are told apart by
  the pair that sits exactly on the boundary;
* a pair appearing **once only** → absent at the default floor;
* products A and B in the same order → **one** row, never (A,B) and (B,A), and
  never (A,A);
* a product **renamed** between two orders in the window → one product id in the
  names block with one resolved name, and the pairs it forms counted once;
* an order **outside the window**, and an order inside it with a **non-revenue
  status** → in no pair. The second pins reuse of `_REVENUE_STATUSES`;
* an order on the **end date at 23:30** → inside the window. This pins the
  inclusive-end convention `api/analytics/services/date_range.py` already uses;
* a **free-entry order** (`total = 0`) containing two distinct products →
  counted by default with the `free_entries` block naming the mode, and absent
  under exclude with the removed-order count reading 1. Assert the block in both
  modes, not just the pair list;
* **more qualifying pairs than the cap** → the returned count equals the cap,
  the qualifying count exceeds it, and `truncated` is true. Assert the two
  numbers, not the flag alone;
* a window **over 366 days**, a `min_support` of 1, a `limit` of 500 → 400 each,
  and the `limit` case asserts a 400 rather than a clamp to 200;
* a window with **no orders** → 200, `pairs: []`, blocks populated.

## What this does not do, stated so nobody reads it as doing it

**It does not build the page.** Until a `dd_frontend` task lands, this is an
endpoint an agency can call and not a report an agency can see. `platform/**` is
protected here and no single contract covers both halves, so the split is
forced. Queue the page separately against `contracts/dd-acquiring-page.yaml`,
whose writable set is the products pages and their proxy and which sets
`auto_merge: false` so a person reads that spec against that diff.

**It does not pair products across a customer's lifetime.**
`research/candidates-metorik-gap-2026-09-21.md` files this as the candidate's
open question: whether "bought together" means the same order or the same
customer over time, and for a competition store the second may be the more
useful question. It is a different and much larger query — no `order_id` to join
on, and the covering index that makes this one affordable does not serve it —
and nobody has said which is wanted. This task answers the same-order question,
which is the one the report catalogue names and the one the index supports.
Naming the endpoint `/products/pairs` rather than `/products/frequently-bought`
leaves the other question room to be its own route.

**It does not filter free entries at the line level.** 31,273 zero-value line
rows sit in orders that are not free entries, and a rule that removed them would
change which products can appear in a pair rather than which orders are counted.
That is a different decision with a different denominator, nobody has asked for
it, and requirement 3 makes its absence visible in the response instead of
leaving it to be inferred. If the pair list turns out to be dominated by
zero-value lines inside paid orders, that is the proposal to write next, and it
starts from a number this endpoint will by then be able to show.

**It does not mine rules beyond pairs.** Triples are a different query shape and
a different cost, and no row in the report catalogue asks for them.

**It does not touch AOV or any mean of `orders.total`.** The free-entry
correction marks four rows `MUST SPLIT FREE ENTRIES` and they are all means or
distributions. A pair count is neither. The block requirement 3 asks for exists
so this report says where it stands, not so it repairs those rows.
