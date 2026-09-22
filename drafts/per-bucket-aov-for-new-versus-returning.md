# Draft spec — finish the new-versus-returning block with the per-bucket AOV, emitted twice

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Per-bucket AOV on the new-versus-returning block — an all-orders and a paid-only average for each bucket, with a free-entry count beside each, and every figure that ships today unchanged
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
  - api/analytics/routes/dashboard.py
  - api/analytics/routes/customers.py
```

## The figures, stated rather than asked for

The agent that builds this gets `Read`, `Edit`, `Write`, `Grep` and `Glob`.
`contracts/deadly-digital-platform-api.yaml` declares no `agent_tools`, so
`runner.yaml`'s default applies: **no database, no interpreter, no network.**
Every figure below is a **given**, and no numbered requirement asks anybody to
re-derive any of it.

| Figure | Value | Source |
|---|---|---|
| Orders with `total = 0` | 66,764 of 2,890,319 (2.3%) | third correction |
| Of those, status `completed` | 66,676 — inside `_REVENUE_STATUSES` | third correction |
| Distinct customers placing one | 15,616 | third correction |
| Store-wide AOV as shipped | £8.23 | third correction |
| Store-wide AOV over non-zero totals | £8.43 | third correction |
| Store-wide understatement | 2.4% | third correction |
| Orders carrying a non-zero total | 2,823,569 of 2,890,319 | candidate coverage |

"Third correction" is *Correction (16 September 2026), third entry* of
`research/metorik-report-classification-2026-09-15.md`, stated as fact by Eamonn:
HIB runs prize competitions, a prize competition must offer a free entry route by
law, and the zero-total orders are that route. They are real orders by real
customers, they belong in every order count, and what they do not belong in
**unlabelled** is a mean of `orders.total`.

**The one figure nobody has is the per-bucket dilution.** The 2.4% is store-wide.
A free entry can be a customer's *acquiring* order, so it lands in the new
bucket, and the candidate row records that the new bucket's dilution is therefore
larger than the store-wide figure and is stated nowhere. Requirement 3 exists so
the figure becomes visible; it does not ask the build agent to produce it,
because the build agent cannot.

## What I read, and what I did not

This draft was written from the fleet tree and from the path listing the runner
generated for this run. Every Deadly Digital path below is from that listing.
**I did not read the Deadly Digital source** — the checkout is outside this run's
readable directories — so there are no quoted expressions and no verified line
numbers here. The candidate row reports the deferral comment at line 105 of
`api/analytics/services/analytics_engine.py`; that is quoted from the row, not
read from the file, and nothing turns on the number — requirement 2 has the build
agent locate the sites by `Grep` and treats the file as the authority.

## What shipped, and what did not

`research/metorik-report-classification-2026-09-15.md` §"Monthly — Retention (4
of 4)" classifies **New vs returning customer KPIs** as bucket **A** with a
`MUST SPLIT FREE ENTRIES` mark, and is explicit that the mark is not a
do-not-propose: the row is proposable, and the report must *say* whether free
entries are in or out.

`drafts/new-vs-returning-orders-and-revenue.md` built the counts and the sums.
Its requirement 2 added `new_orders`, `returning_orders`, `new_revenue` and
`returning_revenue`; its requirement 4 added `unattributed_orders` and
`unattributed_revenue` so the buckets partition the rows by construction. Six
columns off one aggregate.

Its requirement 5 then refused the AOV in as many words — *"Emit no AOV derived
from these figures, on any endpoint, under any key"* — and gave the reason: a
free entry can be an acquiring order, so `new_revenue / new_orders` carries a
dilution specific to the new bucket, and a per-bucket AOV needed the free-entry
question decided first.

**It has been decided.** `drafts/say-whether-aov-includes-free-entries.md`
shipped the convention: `aov` keeps its population, `aov_paid` and `orders_free`
sit beside it, and a `free_entry_convention` block on the revenue and dashboard
payloads states in words which figure averaged over which population. So the
blocker named in the deferral is gone, and what is left is the deferred figure.

## Why this is a code change and not an investigation

Nothing has to be found out. The classification is computed per order already and
read back as six columns off one row; the free-entry predicate is written
already, twice, in the same module. The work is two ratios per bucket over
aggregates that exist, plus the count that makes each denominator legible — all
`FILTER` aggregates over rows the statement is already scanning. **No new column,
no migration, no second pass over `orders`.**

## Why the AOV is emitted twice and never once

One number here would repeat, in a new place, the defect the third correction
records store-wide: £8.23 printed where paid-only is £8.43, with nothing on the
surface saying which population it was — and it would repeat it on the bucket
where the dilution is worst, since an acquiring free entry is by construction a
new-bucket order.

The repair that correction names is *show both figures, or name the free bucket*,
never drop orders from a denominator. This spec does both. The general rule the
same correction states reaches this row directly: **any report whose measure is a
mean of `orders.total` must state whether free entries are in or out.**

## Why this contract

`contracts/deadly-digital-platform-api.yaml`, work_type `dd_api`. All four
declared paths are in its enumerated writable set; it caps the change at 400
production lines, admits one added test under
`api/tests/analytics/test_fleet_*.py` that must fail against the tree without
the change, and runs `tests/unit` and `tests/analytics` per file.

`contracts/dd-order-filters.yaml` is the other `dd_api` contract for this repo
and it is not eligible: its whole writable set is
`api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`,
and the period aggregates are in neither. It also **permits no new test file**,
which for a change whose entire content is *which population a mean divided by*
would be a boundary that cannot fail. Choosing it would be choosing not to test
the work.

`contracts/dd-analytics-frontend.yaml` covers the pages. Out of scope below.

## Why four writable paths when the candidate suggested three

The candidate names `api/analytics/services/analytics_engine.py`,
`api/analytics/routes/revenue.py` and `api/analytics/routes/dashboard.py`.
`api/analytics/routes/customers.py` is added because
`drafts/new-vs-returning-orders-and-revenue.md` requirement 7 named it as one of
the three routes the six columns reach, and a bucket AOV on two of the three
endpoints and not the third is the inconsistency that draft's requirement 1
existed to prevent. Writable is not an instruction to change: if
`customer_report()` turns out not to return the six columns, requirement 2's
comment records that and the file is left alone.

## Citing the requirements

`contracts/checks/spec_requirements_cited.py` runs first under this contract and
reads only lines the diff adds. Put `# spec:N` on a line this change adds — the
line computing an aggregate, the docstring line naming a key, a test name — for
each of 1 through 7. Seven requirements, against a `max_requirements` of 10.

---

### 1. Every figure that ships today keeps its name, its population and its value

Unchanged, in expression, filter, name and value: `aov`, `aov_paid`,
`orders_free`, the `free_entry_convention` block, `new_orders`,
`returning_orders`, `new_revenue`, `returning_revenue`, `unattributed_orders`,
`unattributed_revenue`, `orders_all`, `orders_rev`, `revenue`, `net_revenue`,
`refunded_amount`, `orders_with_refund`, `customers_all`, `customers_rev`,
`new_customers`, `returning_customers`, the granularity bucketing, the coupon
block and the payment-method breakdown.

`_REVENUE_STATUSES` does not change. **No `total = 0`, `total != 0` or
`total > 0` predicate is added to any existing aggregate, CTE or `WHERE`
clause** — the new predicates belong only inside the new aggregates in
requirement 3, computed beside the existing ones over the same rows.

This is the requirement most likely to be broken by an agent that reads the
title and reaches for a filter. `specs/net-revenue-after-refunds.md` established
the discipline for net beside gross and
`drafts/say-whether-aov-includes-free-entries.md` requirement 1 restated it:
additive keys, nothing recomputed. The frontend is protected under this
contract, so a silently different number has no way to announce itself.

### 2. Find every site that returns the six columns, and list them in a comment

`Grep` `api/analytics/services/analytics_engine.py` for `new_orders` and for
`_new_vs_returning` and find every function that returns the six columns. Record
the list — one function name per site — in a comment above the first aggregate
you add, so the next reader can tell whether a site was considered and rejected
or simply missed.

`research/candidates-metorik-gap-2026-09-21.md` names `_new_vs_returning` as an
existing helper, and
`drafts/new-vs-returning-orders-and-revenue.md` requirement 1 named three
candidate sites: `_query_period_stats` (reached by `dashboard_overview()`),
`revenue_report()` and `customer_report()`. Those are the sites that draft aimed
at, not a verified account of where the columns landed. **The file is the
authority.**

**Every site that returns the six columns gets the new keys.** A response
carrying `new_revenue` and `new_orders` without the two averages beside them is
the half-shipped state this task exists to close, and closing it on one endpoint
and not its neighbour makes the product harder to read.

### 3. Six keys, computed in the same aggregate, per bucket

At each site from requirement 2, add to the existing outer aggregate, over the
same rows:

* `new_aov` — mean of `total` over the bucket's revenue-status orders, **all of
  them**, zero-total free entries included;
* `new_aov_paid` — mean of `total` over the bucket's revenue-status orders whose
  `total` is greater than zero;
* `new_orders_free` — count of the bucket's revenue-status orders whose `total`
  is zero;

and `returning_aov`, `returning_aov_paid`, `returning_orders_free` under the same
three definitions over the returning bucket.

All six come out of the **same outer aggregate over the same rows** as
`new_orders` and `new_revenue` — `SUM`/`COUNT` with a `FILTER` clause or the
equivalent conditional. Not a second query, not a second scan of `orders`, not a
post-hoc division in Python, and not a second call to the acquiring-order
lookup.

`new_orders` minus `new_orders_free` is the bucket's paid count and **no key is
added for it**, matching how `orders_free` sits beside `orders` today.

`new_orders_free` and `returning_orders_free` are `0`, never `None`, for a period
with no free entries. `new_orders_free` is the key that makes the new bucket's
dilution legible for the first time; it is not decoration.

**Each average is `None` when its own denominator is zero — never `0`, never the
other average, never the store-wide `aov`.** A period with no new-customer
orders has no new-customer average, and a period whose every new-customer order
was a free entry has no paid average; £0.00 in either place is a figure a reader
takes for a collapse in order value. This is the no-baseline rule
`specs/dashboard-comparison-windows.md` states for a comparison window with no
prior and `drafts/say-whether-aov-includes-free-entries.md` requirement 2
restated for `aov_paid`: absent is reported as absent.

### 4. The classification is not reopened, and the acquiring order is not re-decided

An order is a new-customer order iff it is its customer's acquiring order,
matched by primary key, exactly as
`drafts/new-vs-returning-orders-and-revenue.md` requirement 3 specifies and as
the tree already implements. **Free entries are in, both halves**, matching the
convention the six shipped columns use: a free entry is an order, and it adds £0
to a sum.

`research/candidates-metorik-gap-2026-09-21.md` records the open question this
sits next to: whether HIB reads a free entrant who later pays as an acquisition
at £0 or as an acquisition at their first *paid* order. The two give different
new-bucket averages and different acquisition dates, **and nobody has been
asked.** So this task does not answer it. It keeps today's rule and emits
`new_orders_free`, which is the figure somebody would need in order to answer
it — the open question becomes answerable without being answered.

Do not touch the acquiring-order lookup's `ORDER BY`, `LIMIT`, filter or shape,
do not bound it to the window, do not factor the copies into a helper, and do
not add an index.
`api/analytics/migrations/versions/v0014_orders_customer_created_index.py` is
already the index this read wants, and everything under the migrations tree is
protected by this contract in any case.
`specs/lateral-acquiring-order-in-three-call-sites.md` is separate, queued work
over the same lookups; whichever branch lands second rebases onto the first.

### 5. The convention block names the population behind each new average

`api/analytics/routes/revenue.py` and `api/analytics/routes/dashboard.py` each
build a `free_entry_convention` block today. Each gains, in the same block and
under the same shape, the statement that the two all-orders bucket averages
include zero-total free entries, that the two paid-only ones do not, and that
`new_orders_free` and `returning_orders_free` count the free entries inside each
bucket. Built from the keys requirement 3 returned; **no further query.**

The block is additive: it does not nest, rename or reorder `data`, `summary`,
`period`, `previous` or anything already inside the block, and no existing
consumer changes to keep working.

If requirement 2 finds that `api/analytics/routes/customers.py` serves the six
columns, that route carries the same statement over its own window. It has no
such block today, so adding one there is an additive top-level key of the same
shape and nothing about `new_customers` or `returning_customers` moves.

Free entries are not a data-quality problem and the wording must not read like
one. Nearer *"1,204 of these new-customer orders were free entries"* than
*"1,204 new-customer orders had missing totals"*: a competition's free-entry
route is a legal obligation being met correctly.

### 6. The route docstrings say which population each figure used

Each route above documents, in the docstring of the endpoint that returns these
keys, that `new_aov` and `returning_aov` include zero-total free entries, that
`new_aov_paid` and `returning_aov_paid` do not, that any of the four is `None`
rather than `0` when its own denominator is empty, and what the two free counts
count.

This is not decoration. The JSON is the only contract a consumer of these routes
has, the frontend is protected under this contract and cannot be updated in this
diff, and whoever writes the page draft will read these docstrings and nothing
else. `api/analytics/routes/products.py` is the precedent: its docstring
explains why the per-category rows do not sum to the revenue total — the same
class of statement about the same class of trap.

### 7. One added test, and what it has to pin

Create one file, `api/tests/analytics/test_fleet_per_bucket_aov.py`. This
contract's `creatable_paths` admits `api/tests/analytics/test_fleet_*.py` and
nothing else; every existing file under `api/tests` is protected and none may be
edited. `new_test_bites.sh` runs the added test against the tree before the
change and requires it to fail there, so it must turn on the new keys' **values**
and not on their presence.

Over one fixture holding, in the revenue statuses, a mix of paid and zero-total
orders in both buckets, assert:

* `aov`, `aov_paid`, `orders_free`, `new_orders`, `returning_orders`,
  `new_revenue`, `returning_revenue` and the window's revenue and order totals
  are all what they were. A test that checks only the new keys passes against a
  build that filtered free entries out of an existing denominator — requirement
  1's failure mode;
* `new_aov` equals `new_revenue / new_orders` on the fixture, and
  `new_aov_paid` equals the mean over that bucket's non-zero rows only. Seed the
  fixture so the two differ, in both buckets: equal values pass against code
  that returns the same number twice;
* **a zero-total order that is its customer's acquiring order** counts in
  `new_orders`, adds £0 to `new_revenue`, appears in `new_orders_free`, and
  appears in neither returning key. This is the case the deferral was about and
  the one that makes `new_aov` strictly below `new_aov_paid`;
* a bucket whose every order in the period is a free entry returns
  `new_aov_paid is None` with `new_aov` equal to `0`, and
  `new_orders_free` equal to that bucket's order count. A naive division writes
  `0.0` here or raises;
* a period with no new-customer orders at all returns `new_aov is None` and
  `new_aov_paid is None`, with `new_orders_free` equal to `0`;
* an order outside `_REVENUE_STATUSES` with `total = 0` appears in neither free
  count. The population is the revenue statuses, matching `orders_free` — 66,676
  of the 66,764 zero-total orders, not all of them;
* an order with no `customer_id` lands in `unattributed_orders` and in no bucket
  average or free count.

`test_diff_target` under this contract is 300 lines and is guidance, not a gate;
a case that earns its place is worth going over it for.

## Not in scope, stated so nobody reads it as included

**An unattributed-bucket average.** `unattributed_orders` and
`unattributed_revenue` exist so the partition is exhaustive by construction, and
`drafts/new-vs-returning-orders-and-revenue.md` requirement 4 records that nobody
has established whether the bucket is ever non-empty. A mean over a residual
whose population is unknown is a fourth figure with no reader, and the two sums
already reconcile to `revenue` without it. Add nothing there.

**The pages.** `platform/app/(dashboard)/analytics/revenue/page.tsx`,
`platform/app/(dashboard)/analytics/page.tsx` and
`platform/app/(dashboard)/analytics/customers/page.tsx` render none of these
keys, and `platform/**` is protected here. That is a `dd_frontend` task under
`contracts/dd-analytics-frontend.yaml`, drafted after this merges;
`drafts/net-revenue-on-the-analytics-overview.md` is the precedent for the split.
A two-block chain is the wrong instrument: `console/autoqueue.py` writes the
whole markdown into every link's `spec_md` and
`contracts/checks/spec_requirements_cited.py` obliges each link's diff to cite
every numbered requirement in it, so both links would fail having been built.

**Changing which average leads.** Whether paid-only should be the default is a
product decision for Eamonn, and requirement 1 keeps today's default precisely
so the decision stays open and reversible.

**Net revenue per bucket.** HIB has 4 non-zero refunds in 2,890,319 orders, so a
per-bucket net figure would differ from the gross one on almost no row.

**`daily_metrics.aov`.** A precomputed per-day value that may carry the same
mixing, named in `drafts/say-whether-aov-includes-free-entries.md` as a question
of its own. Nothing here reads or writes it, and no requirement touches
`api/analytics/models.py`.

**Whether the new bucket's dilution exceeds 2.4%.** The keys this change adds
are what would establish it, per period, on a real tenant. Nothing above asks
the build agent for it, because the build agent has no database.

## Before this is queued

`auto_merge` is `true` on this contract, so nobody reads a spec against a diff on
this path. Three ways this ships green and wrong:

* **6, unbuilt.** A docstring is invisible to `compileall`, to `ruff` and to
  every pytest run in the verification list, and the change passes every gate
  without it.
* **1, wrong.** The free entries quietly leave a denominator that already ships,
  `aov` becomes £8.43, the revenue page keeps its label, and the page disagrees
  with its own order count.
* **3, half-built.** One average per bucket instead of two — the exact defect
  this row exists to stop propagating.

A person confirming this branch should run each touched endpoint against a real
tenant schema for one 30-day window and one spanning a period boundary, and check
that every key requirement 1 lists is identical either side. That is a step in
the review of this branch and it is deliberately not a numbered requirement: a
branch claiming to have done it has claimed something it could not do.

## Objectives

`dd-feature-parity`. One bucket-**A** Metorik row, four fifths shipped, whose
last fifth was deferred for a reason that no longer holds.
