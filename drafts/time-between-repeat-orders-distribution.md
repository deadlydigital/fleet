# Draft spec — time between repeat orders, kept as a distribution instead of thrown away behind one median

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Return the distribution of gaps between a customer's consecutive orders over a window — day-range buckets, always all present, with percentiles beside them and the churn median left alone
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/customers.py
```

## What this is

The gap between one order and the same customer's next one, over a window,
reported as a **shape** rather than a single number: how many gaps fall in the
first day, the first week, the first month, the first year, and beyond. It
answers whether repeat buying on this store is daily, weekly or annual, and it
is the Metorik row *Time between repeat orders* from
`research/metorik-report-classification-2026-09-15.md` §*Monthly — Retention (4
of 4)* at sha `80677a2`, classified **A** with no dagger: *"A window function
over `orders.created_at` partitioned by `customer_id`. Both columns
populated."*

## Why this is a code change and not an investigation

Nothing has to be found out first, and the reason is stronger here than on the
other parity rows: **the expression is already written and already running.**
`research/candidates-metorik-gap-2026-09-21.md` records, established against the
platform at `fd5a404`, that `api/analytics/services/churn_engine.py` line 192
builds `created_at - LAG(created_at) OVER (PARTITION BY customer_id ...)`, takes
a **single median restricted to gaps over 30 days**, and renders it as one
sentence of churn-insight prose. Everything else the window function computes —
the mode, the body, the tail — is discarded on the way out.

So this task is not "introduce window functions over the order table". It is
"keep what one already produces". No new column, no new table, and no
migration: `api/analytics/migrations/**` is protected under
`contracts/deadly-digital-platform-api.yaml` and nothing here wants one.
`api/analytics/migrations/versions/v0014_orders_customer_created_index.py`
already built an index on `orders` over the customer and created-at columns,
which is the access path a `PARTITION BY customer_id ORDER BY created_at` seeks
on, so the ordered scan this report needs is the one the tree is already built
for.

## Figures, given — nothing here is to be measured

The build agent has `Read`, `Edit`, `Write`, `Grep` and `Glob` and no shell, no
database and no timer. Every number below is **given**, from
`research/candidates-metorik-gap-2026-09-21.md` and the classification it reads.
Cite them as the argument for what you built, never as something you observed.

| Figure | Value | What it argues |
|---|---|---|
| Orders on tenant 2 | 2,889,850 | The grouped query must be one pass, not a per-customer loop |
| Distinct customers | 157,311 | The partition count |
| Mean orders per customer | 18.4 | Most customers contribute several gaps, so the distribution has a body and not only a mode |
| Zero-total orders (free entries) | 66,764 | Requirement 4 exists because of these |
| Share of customers with two or more orders | **not known** | Recorded nowhere readable; the candidate carries `coverage: null` for it deliberately. Requirement 2's `customers_with_gaps` is how the response stops this being unknowable a third time |

**Do not put a timing, a row count or a plan in this diff or its test.** Nothing
in this task can take one.

## What could not be read for this spec, stated plainly

**No read-only checkout of `deadly-digital-platform` was present in the worktree
this spec was written in.** The runner supplied a generated listing of every file
in the tree, and every path below is taken from that listing, which is the
authority for what exists. The *contents* below — the `LAG` at
`api/analytics/services/churn_engine.py` line 192 and its 30-day restriction,
`avg_order_frequency_days`, `ltv_distribution` and its `width_bucket`, the
revenue-status constant, the free-entry convention in
`api/analytics/services/analytics_engine.py` — come from
`research/candidates-metorik-gap-2026-09-21.md` and
`research/metorik-report-classification-2026-09-15.md`. No line number is
authoritative. **Locate every symbol by name before relying on it**, and where
this spec asserts what an existing helper does, read it and follow what it
actually does.

## Why these two files, and not the module the expression lives in

The candidate's `suggested_paths` are advisory. Two of the three are taken and
the third cannot be.

**`api/analytics/services/analytics_engine.py`, and not
`api/analytics/services/churn_engine.py`.** The nearest shipped thing to this
report is `ltv_distribution` in the engine — a histogram over a per-customer
derived value, with `width_bucket` in it. That is this report's shape exactly,
one column over. `api/analytics/services/churn_engine.py` computes a churn
score and the prose around it; its median is an input to a *churn signal*, and
extending it would make one report out of two. Copy its window expression; do
not import it, do not refactor it into a shared helper, and do not edit that
file. It is not in the writable set above, deliberately, and requirement 5 says
why in more detail.

**`api/analytics/routes/customers.py`.** The subject is the customer
population, not the order list, and `platform/app/(dashboard)/analytics/customers/page.tsx`
is the page this eventually lands on. If the engine's other customer-population
distributions turn out to be served from a different router in that directory,
**stop and say so rather than editing a file this spec did not declare** — a
declared writable set is the boundary, not a starting point.

**Not the page.** `platform/**` is protected under this contract, so no `dd_api`
task can write `platform/app/(dashboard)/analytics/customers/page.tsx`. The
chart is a separate `dd_frontend` task under
`contracts/dd-analytics-frontend.yaml`. Until it lands this is an endpoint an
agency can call and not a report an agency can see.

## Why this contract

`contracts/dd-order-filters.yaml` also carries `work_type: dd_api`, and it
cannot host this work at all: its writable set is
`api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`,
neither of which is a file this task touches. That settles it on coverage
before it gets to merit — but the merit is the same argument the item-count
distribution made in `drafts/item-count-distribution.md`: that contract runs
three checks, none of which executes a test.
`contracts/deadly-digital-platform-api.yaml` requires one added test and proves
it fails without the change. A bucketed distribution is a report whose numbers
all look plausible when they are wrong, and it should not ship untested.

## There is no timezone decision here, and that is worth saying

The weekday and hour-of-day reports both turn on one, because a *bucket by clock
position* is a local concept. **A gap is a duration**, and a duration between two
timezone-aware instants is the same duration in every zone. Do not add a zone
conversion to the gap arithmetic, and do not copy one out of the weekday report.
The only place a zone could enter is in resolving the window bounds, which is
already settled by whatever `api/analytics/services/date_range.py` does for
every other windowed report; use it and add nothing.

## What to build

Six requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring, or a test name — for each of `1` through `6`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under this
contract and reads only added lines.

### 1. One CTE, and the gap belongs to the window by its LATER order

Add one function to `api/analytics/services/analytics_engine.py`, beside the
other distributions, taking a tenant and a bounded date range.

* **One pass.** A CTE computing `created_at - LAG(created_at) OVER (PARTITION BY
  customer_id ORDER BY created_at)`, then a grouped select over it. Not a query
  per customer, not a fetch of 2,889,850 rows regrouped in Python.
* **Reuse the population, by reference.** The same revenue-status constant the
  neighbouring engine reports use — reference it, do not write a status tuple as
  a literal. A cancelled order sitting between two completed ones must not split
  one real gap into two, which is what including it would do.
* **The `LAG` runs over the customer's whole history; the window filters the
  gap, by the date of the LATER of its two orders.** This is the requirement
  most likely to be built wrongly, because the wrong version is shorter: filter
  the orders to the window first, then `LAG` inside it. That version **cannot
  return a gap longer than the window**. Asked for 30 days it reports that
  nobody on this store waits more than a month — not as an error, as a
  confident, clipped, wrong distribution, and the tail is the whole reason this
  report exists. Filter after the window function, on the later order's
  `created_at`.
* **The same `schema_exists()` guard the neighbouring reports use**, returning
  an empty result rather than raising for a tenant whose analytics schema has
  not been created.

### 2. Eleven buckets, always all eleven, with their bounds in the response

Gaps are expressed in **days as a fractional number** — the interval converted
to days, not rounded to a whole one — and bucketed half-open, `min_days`
inclusive and `max_days` exclusive:

    [0,1) [1,2) [2,4) [4,7) [7,14) [14,30) [30,60) [60,90) [90,180) [180,365) [365,∞)

* **Every bucket appears every time**, in ascending order, with `gaps: 0` where
  there are none. A grouped select returns only non-empty buckets, and a bar
  chart handed eight of eleven either draws eight bars or has to know to
  zero-fill, which puts the same rule in two places. Fill it here, once, in the
  service.
* **Each bucket carries its own bounds** — `min_days`, `max_days`, and `gaps`.
  `max_days` on the final bucket is `null`, not a large number. A reader must
  not have to infer the boundaries from the labels, and a frontend must not
  hard-code a second copy of them.
* **The last bucket is open-ended and is not a `tail` in the item-count sense.**
  `item_count_distribution` caps at twenty observed values and names the
  remainder; here the bucket edges are fixed in advance, so nothing is truncated
  and no bucket is ever omitted for being too far out.
* **Two denominators travel with the buckets**: `gaps_total`, the sum across the
  eleven, and `customers_with_gaps`, the count of distinct customers
  contributing at least one gap in the window. The second is the figure nobody
  has: a customer with one order contributes no gap and is invisible in this
  report, so without it a reader cannot tell a store where everybody repeats
  from one where a few people repeat a lot.

Same-instant orders give a gap of `0.0` and belong in the first bucket; they are
real and are not filtered out.

### 3. Percentiles beside the buckets, over ALL gaps

In the same response: `p25`, `median`, `p75`, `p90` and `mean`, in days, over
the same gap set the buckets are built from and **with no 30-day floor**.

Buckets give the shape and percentiles give the position, and each is bad at the
other's job — a median cannot say whether the distribution is bimodal, and
eleven buckets cannot say where the middle sits inside the widest of them. They
come from the same CTE and cost one more aggregate.

`mean` is included **because the comparison is the point**: churn derives
`avg_order_frequency_days` per customer as a span divided by a count, and that
has never been put beside the gaps it claims to summarise. This response is what
makes the comparison possible for a person. It does not perform it —
requirement 5.

When there are no gaps in the window, every one of these is `null`, not `0`. A
zero median means "customers reorder the same day" and is a different claim from
"there is nothing to report".

### 4. Say which orders were counted, in the response

**Free entries are in.** The gaps are over the revenue-status population of
requirement 1, and the 66,764 zero-total orders are part of it.

That is a decision this spec is making rather than discovering, and the argument
is that it is the honest default: a free entry is a real order placed on a real
date, and excluding it would mean this report's population silently differs from
the order list and from churn's. It is also the decision most likely to be
misread — a free entry between two purchases genuinely shortens the gap it sits
in, and on a store with 66,764 of them that is not a rounding difference.

So the response **names the convention rather than leaving it in a docstring**.
`api/analytics/services/analytics_engine.py` already carries a free-entry
convention field that shipped on the revenue and dashboard responses; find it by
name and reuse it. Do not invent a second name for the same idea, and do not add
a parameter to switch the population — one report that states its population
beats two that disagree.

### 5. Churn is not touched, and the two medians are allowed to differ

Stated as a prohibition because the tempting change is a wrong one.

* **Do not edit `api/analytics/services/churn_engine.py`.** It is not in the
  writable set. Its median is restricted to gaps over 30 days and feeds a churn
  signal; this report's median is over all gaps and will be **much smaller**.
  That is not a contradiction and neither number is a bug.
* **Do not recompute, correct or reconcile `avg_order_frequency_days`**, and do
  not write a line anywhere claiming it is wrong. Nothing in this task measures
  it. The engine docstring may say that this report's `mean` is computed over
  observed gaps while churn's figure is a per-customer span over a count, and
  may say that the two are not expected to be equal. It may not say which is
  right.
* **Do not extract a shared helper** between the two modules. One report reading
  the other's SQL is how a churn-score change silently moves a retention report
  a year from now.

### 6. `GET /customers/…` on `api/analytics/routes/customers.py`

One new endpoint on the existing router, taking the same `start` and `end`
parameters, parsed and validated **exactly the way the routes already in that
module parse and validate them** — the same ISO-date handling with a 400 on a
bad value, the same default window when they are absent, the same subscription
dependency. Do not invent a second date-parsing convention in a module that
already has one.

* **Declare the literal path ahead of any parameterised route on the same
  prefix.** `platform/app/(dashboard)/analytics/customers/[id]/page.tsx` exists,
  so the module serves a per-customer detail route; read
  `api/analytics/routes/customers.py` and place the new literal before anything
  that could capture it as an id.
* **Update the module docstring's route list** if it keeps one. A docstring that
  lists the routes and then does not is how the next person gets the ordering
  wrong.
* The endpoint docstring states, in one sentence, that gaps are attributed to
  the window by the later order and that the population is the revenue-status
  one including free entries. The two facts a support ticket will turn on.

## The test

This contract requires exactly one new test file and proves it bites:
`contracts/checks/new_test_bites.sh` runs it against the tree before the change
and the tree after, and a test that passes on both is refused. Create

    api/tests/analytics/test_fleet_repeat_order_gaps.py

which is the only creatable shape the contract allows — `test_fleet_*.py` under
`api/tests/analytics`. The budget is about 300 lines, separate from the 400
production lines, and it is a target rather than a bound. Read a neighbour in
`api/tests/analytics/` for the tenant-schema fixture conventions. No existing
test file may be edited.

The fixture places a small number of customers with orders at chosen dates:

* **A customer with two orders 5 days apart** produces exactly one gap, in the
  `[4,7)` bucket. The report in one line.
* **A customer with one order** produces no gap and does not appear in
  `customers_with_gaps`. The zero-contributor case, which an implementation
  joining wrongly turns into a phantom gap of zero.
* **A gap whose earlier order is BEFORE the window and whose later order is
  inside it** is counted, with its full length. Requirement 1, and this is the
  assertion the short wrong implementation fails.
* **A gap longer than the window itself** — a 400-day gap reported through a
  30-day window — lands in the `[365,∞)` bucket. Requirement 1 again, from the
  other side; an implementation that filters before the window function cannot
  make this pass.
* **A gap whose later order is after the window ends** is not counted, even
  though its earlier order is inside.
* **All eleven buckets present** on a fixture touching three of them, the other
  eight `gaps: 0` and not absent; assert the length is 11 and assert on a named
  empty bucket by its bounds. Requirement 2.
* **Bucket edges are half-open**: gaps of exactly 7.0 and 13.99 days both land in
  `[7,14)` and a gap of exactly 14.0 lands in `[14,30)`. The off-by-one that
  otherwise ships.
* **`gaps_total` equals the sum of `gaps` across the eleven buckets**, and
  `customers_with_gaps` equals the number of distinct customers in the fixture
  with two or more in-scope orders.
* **An order carrying a non-revenue status between two counted ones** does not
  split the gap: the two survivors produce one gap of the full length, not two.
  Requirement 1's use of the status constant.
* **A zero-total free-entry order between two purchases** DOES split the gap,
  and the convention field in the response says so. Requirement 4 — and this
  assertion is the one that fails if somebody later changes the population
  without changing the field.
* **An empty window** returns eleven zero buckets and `null` for every
  percentile, not zeroes. Requirement 3.
* **A gap of 0.0** from two same-instant orders is counted in the first bucket.

## What this does not do, stated so nobody reads it as doing it

**It does not change the churn report, the churn page or
`avg_order_frequency_days`.** Requirement 5. Whether churn's per-customer figure
agrees with the observed gaps is a real question and this endpoint is what makes
it answerable, but answering it needs a database and a person, and no line of
this diff may claim it was answered.

**It does not bucket by the customer's own history length or segment.** "Time
between repeat orders for customers who have ordered ten times" is a different
report and a second dimension; the Metorik row is one-dimensional and so is
this.

**It does not build the per-customer view.** A list of customers with their
individual gaps is a different endpoint on a different page; this returns the
population's shape.

**It does not add an index and it does not write a migration.**
`api/analytics/migrations/**` is protected under this contract.
`api/analytics/migrations/versions/v0014_orders_customer_created_index.py` is
already the index this scan wants. If the query turns out to need another one,
that is a separate measured proposal with a timing in it, not something to slip
into this diff.

**It does not report gaps for the other three retention rows.** *Orders made
over customer lifetime* and *Items bought over customer lifetime* are separate
candidates in `research/candidates-metorik-gap-2026-09-21.md` and reuse the
bucket-and-tail convention from `drafts/item-count-distribution.md`, not this
one's fixed edges. The two conventions differ because the data does — an order
count has twenty sensible exact values and a gap in days has twelve hundred —
and a later reader should not read that difference as an inconsistency to tidy.

## Before this is queued

`auto_merge` is `true` on this contract and nobody reads a spec against a diff
on that path. The requirement most likely to ship **wrongly** is **1**: the
window-first version compiles, lints, passes every test that does not
deliberately reach across the window boundary, and returns a clipped
distribution that looks entirely reasonable. The requirement most likely to ship
**unbuilt** is **2**'s `customers_with_gaps`, because a response full of buckets
looks complete without it. If one thing is read against the diff, read those.
