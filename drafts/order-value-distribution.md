# Draft spec — order value distribution, a histogram of `orders.total` over a window

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Order value distribution — how many orders fall in each money band over a window, with free entries named
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/orders.py
```

## Why this is a code change and not an investigation

Nothing needs finding out. `orders.total` exists and every revenue figure DD
prints already reads it; what no endpoint does is group it. The work is one
banded `GROUP BY` and one route, and
`research/metorik-report-classification-2026-09-15.md:714` classifies the report
**A** — buildable on today's schema — on `orders.total` over 2,889,850 orders.

The judgement in it is the band width and the zero bucket, not the SQL. Both are
decided below rather than left to the build agent.

## The candidate's premise is half wrong, and the half that is wrong matters

The candidate says the engine "has no bucketing expression at all". It has one.
`research/candidates-metorik-gap-2026-09-21.md:861` records that this very row was
**retired on 21 Sep 2026** by a probe matching `WIDTH_BUCKET|width_bucket` across
the engine, and what put `width_bucket` there is `ltv_distribution` at
`api/analytics/services/analytics_engine.py:3568`, which buckets **lifetime spend
per customer**. That is a different report one column over.

So two things follow, and they point in opposite directions:

* **The report is still missing.** The same paragraph states plainly that no
  endpoint in this tree returns a histogram of `orders.total`. The retirement was
  a probe reading a neighbouring feature.
* **The idiom is not missing.** There is a shipped money histogram in the file
  this spec makes writable. Requirement 1 says to follow it rather than invent a
  second way to band money in the same module.

**Before this is queued, somebody should confirm the retirement is being
reversed deliberately.** `research/candidates-metorik-gap-2026-09-21.md:861`
declined to re-open the row and said so; this draft proceeds on the finding that
put the candidate back in front of a reviewer. If that decision has not been
made, the cheap outcome is to not queue this, and the expensive one is to queue
it and discover the row was closed on purpose.

## Given measurements — nothing here is to be measured by the build agent

Every figure below is stated as given, taken 2026-09-16 on `analytics_2` and
recorded in `research/metorik-report-classification-2026-09-15.md:530` onward.
The build agent has `Read`, `Edit`, `Write`, `Grep` and `Glob` and no shell, no
database and no timer. It cannot reproduce any of these and must not try.

| Figure | Value |
|---|---|
| Orders on the tenant | 2,890,319 at the time of measurement |
| Orders inside the revenue statuses | 2,888,343 |
| Of those, non-zero `total` | 2,821,656 |
| Orders with `total = 0` | **66,764** (2.3%), of which 66,676 are `completed` |
| Distinct customers placing a zero-total order | 15,616 |
| Span of zero-total orders | 2023-03-15 to 2026-09-16 — the whole history |
| AOV over all orders | **£8.23** |
| AOV over paid orders only | **£8.43** |
| History available | 2023-03-12 to 2026-09-15, 1,283 days |

**Do not put a timing, a row count, an `EXPLAIN` plan or a production identity
proof in this diff or its test.** A numbered requirement asking for one is a run
that dies on a citation it could not honestly make; that has happened twice and
is recorded in `contracts/draft-spec.yaml`. Nothing below asks for one.

## Why £1 bands, which is the whole judgement

The band width is the report. Take it from the one figure that is known: the paid
mean is **£8.43**.

* **£5 or £10 bands say nothing.** At a paid mean of £8.43 a £5 band puts the
  mode and most of the store into one or two bars, which is the AOV problem
  redrawn as a chart. The candidate's own argument — that £52 is the same number
  whether the store sells one ticket at a time or splits between £5 and £200
  baskets — fails at £5 bands on a store whose mean is £8.43.
* **£1 bands give eight to ten populated bars below the mean**, which is a shape
  a reader can act on, and they are the coarsest width that does.
* **Sub-pound bands are not offered.** `orders.total` is money; a band finer than
  £1 on a mean of £8.43 is noise, and it multiplies the bands needed to reach the
  tail.

So: **default £1, and the caller may choose from a fixed list.** A merchant who
wants the £200-basket end passes `band=10` and covers £0–£400 under the same
40-band cap. The width is a parameter because there is no single right answer for
every window; the *default* is £1 because there is a right answer for this store.

This is the judgement a reviewer should argue with if they are going to argue
with anything. It is derived from one measured mean, it is stated rather than
buried in a `WIDTH_BUCKET` call, and changing it later changes one constant.

## Why these two files

The candidate's suggested paths are advisory. Two are taken; the third cannot be.

**`api/analytics/services/analytics_engine.py`, not
`api/analytics/services/order_query.py`.** The order-list service is the tempting
home — `drafts/item-count-distribution.md` puts a sibling distribution there, and
that is right for a report over the order list's *filtered* population. It is
wrong here, for a reason that file states about itself: its module docstring
records that an order list lists rows and does not compute a metric, and that
nothing in it filters by revenue status. This report's central requirement is a
revenue-status and free-entry decision, and the engine is where the revenue-status
constant, the free-entry convention and the shipped money histogram already live.
A money distribution built in the order-list service would have to restate all
three.

**`api/analytics/routes/orders.py`.** The subject is the order population and the
orders page is where it lands. `research/candidates-metorik-gap-2026-09-21.md:880`
records `GET /orders/by-weekday` at `api/analytics/routes/orders.py:426`, so this
router already serves window aggregates beside the list.

**Not the page.** `platform/**` is protected under
`contracts/deadly-digital-platform-api.yaml`, so no `dd_api` task can write
`platform/app/(dashboard)/analytics/orders/page.tsx`. The bar chart is a separate
`dd_frontend` task under `contracts/dd-analytics-frontend.yaml`, and until it
lands this is an endpoint an agency can call rather than a report an agency can
see. Queue it once this merges.

**No migration and no index.** No new column, and
`api/analytics/migrations/**` is protected. The grouping reads `orders.total` and
`orders.created_at` on rows a window already restricts; if it turns out to want
an access path, that is a separate proposal with a timing in it and not something
to fold into this diff.

## Why this contract

`contracts/dd-order-filters.yaml` also carries `work_type: dd_api` and
`repo: deadly-digital-platform`, and it cannot host this work: its writable set
is `api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`,
and the engine is not in it. Its third check,
`contracts/checks/order_filters_shape.py`, is another task's acceptance check and
has nothing to say about a histogram.

That settles it on coverage, and the choice would be the same if it did not.
`contracts/dd-order-filters.yaml` declares no `creatable_paths`, so a task under
it **adds no test at all** and a green run would mean "nothing broke".
`contracts/deadly-digital-platform-api.yaml` mandates one new test file and
`contracts/checks/new_test_bites.sh` proves it fails against the tree before the
change. For a report whose failure mode is a silently wrong bucket, the contract
that tests the buckets is the only defensible one.

Note what it costs: that contract sets `auto_merge: true`, so nobody reads this
spec against the diff. A requirement built four-fifths of the way merges green.
The requirements below are written to be individually checkable for that reason.

## What could not be read for this spec

**No read-only checkout of `deadly-digital-platform` was present in the worktree
this spec was written in.** The runner supplied a generated listing of every file
in the tree, and every path above and below is taken from that listing, which is
the authority for what exists.

The *contents* — `ltv_distribution` and its `width_bucket`, the revenue-status
constant, the free-entry convention, the module docstrings quoted above, the
route-ordering trap, the `mixed_currency` handling — come from
`research/metorik-report-classification-2026-09-15.md`,
`research/candidates-metorik-gap-2026-09-21.md` and
`drafts/item-count-distribution.md`. **No line number below is authoritative.
Locate every symbol by name before relying on it, and where this spec asserts
what an existing helper does, read it and follow what it actually does.** If a
helper named here does not exist under that name, say so rather than editing a
file this spec did not declare.

## What to build

Five requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring, or a test name — for each of `1` to `5`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under
`contracts/deadly-digital-platform-api.yaml` and reads only added lines.

### 1. One banded `GROUP BY` in `api/analytics/services/analytics_engine.py`

Add a method that, for one tenant, one window and one band width, returns how
many orders fall in each money band.

* **Band in SQL, in one statement.** Follow `ltv_distribution` in the same
  module — located by name, at or near line 3568 — for the bucketing idiom,
  whether that is `width_bucket` or a `FLOOR(total / band)`. Do not fetch totals
  and band them in Python: the window can be the whole table, 2,889,850 orders.
* **One way to band money in this module.** If `ltv_distribution`'s expression
  can be reused as it stands, reuse it. If it cannot, write the new one beside it
  and say in a comment why the shapes differ — per customer over lifetime spend
  against per order over one window. Do not refactor `ltv_distribution` itself;
  it is a shipped report and this change is not about it.
* **The engine's own status convention, and no filter of its own.** Restrict to
  the revenue statuses the engine's existing figures use — `_REVENUE_STATUSES`,
  located by name, which the 16 Sep measurement records as `completed`,
  `processing` and `on-hold`. It follows that this report's order count
  reconciles with the engine's other window figures for the same window, which is
  the consistency worth having for a revenue report.
* **Bands are half-open and ascending**: band *k* is `[k × band, (k+1) × band)`.
  State that in the docstring. A reader who does not know which end is closed
  cannot say which band a £5.00 order is in.

### 2. Free entries are a bucket of their own, and both means are returned

This is the requirement the report exists to get right.
`research/metorik-report-classification-2026-09-15.md:714` marks this row **MUST
SPLIT FREE ENTRIES**: 66,764 zero-total orders are HIB's legal free-entry route
for a prize competition, not £0 sales and not failed checkouts. A histogram that
drops them changes what "orders" means; one that puts them in the first band
invites a reader to read 2.3% of the store as abandoned carts.

So the response carries:

* `free_orders` — the count of orders in the window with `total = 0`, **as its
  own field, outside `bands`**. Named free rather than zero.
* `bands` — over **non-zero** orders only. Band 0 is therefore `(0, band)`, and
  the docstring says so: a paid order under £1 is in band 0 and a free entry
  never is.
* `mean_all` and `mean_paid` — the mean `total` over the window with free entries
  in and with them out, each to two decimal places, both derived from the same
  aggregate rather than a second query. Over the whole history these are the
  £8.23 and £8.43 of the given table; for any window they are the two numbers
  that make the report self-labelling.

Returning both means, rather than choosing one, is what discharges the 16 Sep
rule — *any report whose measure is a mean of `orders.total`, or a distribution
over it, must state whether free entries are in or out*. This one states both.

### 3. The band width is a parameter from a fixed list, and the response says which it used

* **Allowed widths: 1, 2, 5, 10, 25, 50, 100.** Anything else is a `400` before
  anything is queried. A list rather than a range keeps the bands comparable
  between two calls and keeps the expression integer-clean.
* **Default 1**, for the reason derived above from the £8.43 paid mean. Put that
  derivation in the docstring in one sentence, so the next person to change the
  constant knows what it was chosen against.
* **The response echoes `band`.** A bar chart that has to infer the width from
  the gap between two bucket keys gets it wrong on a window where a band is
  empty.
* **Currency.** Banding money across currencies is meaningless.
  `research/candidates-metorik-gap-2026-09-21.md:779` records that
  `ltv_distribution` already faces this with a real `GROUP BY` on currency and a
  `mixed_currency` boolean. Follow whatever that method actually does, located by
  name, and carry the same field or fields through. Do not invent a second
  convention, and do not silently sum across currencies.

### 4. Forty bands, a tail that admits truncation, and a total that reconciles

`orders.total` has no ceiling and this is served over HTTP, so cap `bands` at the
**forty lowest** bands and fold everything above into a single tail object
carrying:

* `min_total` — the lower bound of the tail;
* `orders` — how many orders are in it;
* `distinct_bands` — how many bands it swallowed.

Forty is a fixed count rather than a fixed range, so coverage scales with the
band the caller chose: £0–£40 at the default, which is 4.7× the paid mean, and
£0–£400 at `band=10`.

When nothing is above the cap the tail is **absent, not a zero-filled object**.
An absent tail says the cap did not bite; a zeroed one is indistinguishable from
a bug at a glance. A truncated list that does not say it was truncated would read
here as "no order in this store has ever exceeded £40", which is a claim this
change is in no position to make.

Also return:

* `orders_total` — every order in the window, which **must equal** the sum of
  `orders` across `bands`, plus the tail's `orders`, plus `free_orders`. That
  identity is the reason the tail is a count rather than a shrug, and requirement
  5's test asserts it.
* `max_total` — the largest `total` in the window, inside the cap or not. Without
  it a truncated tail has no top.

### 5. `GET /api/analytics/orders/value-distribution` in `api/analytics/routes/orders.py`

One route, returning requirement 4's shape.

* **Declare it above `/{order_id}`.** FastAPI matches in declaration order, so a
  literal path registered after the path-parameter route binds
  `order_id="value-distribution"` and 422s on int parsing. The module docstring of
  `api/analytics/routes/orders.py` records this trap and the existing literal
  routes are pinned by tests against it; pin this one the same way.
* **Parameters: `start`, `end`, `band`.** Nothing else. No `page`, `limit`,
  `sort_by` or `sort_dir` — an aggregate has no pagination and no row order to
  choose — and none of the order-list set filters, for the reason in *What this
  does not do*.
* **Reuse this module's existing date-range parsing**, located by name — both
  bounds or neither, with the same refusal the list route gives. Inheriting it is
  what keeps this route's `400`s identical to the list's.

## The test

`contracts/deadly-digital-platform-api.yaml` requires exactly one new test file
and `contracts/checks/new_test_bites.sh` proves it bites by running it against
the tree before the change. Create

    api/tests/analytics/test_fleet_order_value_distribution.py

which is the only creatable shape the contract allows —
`api/tests/analytics/test_fleet_*.py`. Budget is 300 lines, separate from the 400
production lines. No existing test may be edited.

Build a fixture whose arithmetic is known by hand and assert on all of it:

* paid orders of £0.50, £1.00, £1.50 and £8.00 at `band=1` → bands `0`, `1`, `1`,
  `8`, and nothing in band `0` that is not the £0.50 order. This is the assertion
  that gets the half-open boundary right: £1.00 is in band 1, not band 0;
* **a `total = 0` order → `free_orders` is 1 and no band contains it.** This is
  requirement 2 as an assertion, and it is the one a reasonable-looking
  implementation fails by putting the free entry in band 0;
* `orders_total` equals the sum of `orders` across `bands` plus the tail plus
  `free_orders`, on a fixture where all three are non-zero;
* `mean_all` and `mean_paid` over that fixture, both computed by hand in the test,
  and **asserted to differ** — a fixture where they are equal cannot fail the
  free-entry requirement;
* the same fixture at `band=5` → a strictly coarser set of bands over the same
  `orders_total`, and the echoed `band` is 5;
* `band=3` → `400`, and `band` absent → the `band=1` answer;
* more than forty bands present → exactly forty bands, a tail whose
  `distinct_bands` is the remainder, `min_total` at the cap boundary, and
  `max_total` above the cap. Then a fixture inside the cap → **no tail key at
  all**;
* an order outside the revenue statuses is excluded from `bands`, `free_orders`
  and `orders_total` alike;
* `GET /api/analytics/orders/value-distribution` resolves to this handler rather
  than to the single-order route, which is requirement 5's routing trap.

## What this does not do

**It does not follow the order list's filters.** No `status`, `search`,
`payment_method`, `country`, `coupon` or `has_discount`. The report is the
engine's window population under the engine's revenue statuses, which is what
makes its count reconcile with every other figure the engine prints for that
window. A histogram that followed the order list's query string is a different
and larger report — it would have to build its predicate from the order-list
service's shared filter clause, as `drafts/item-count-distribution.md` does — and
it is a reasonable next candidate. **Say in the route's docstring that the
distribution describes the window and not the page's current filters**, so a
merchant with filters applied does not read it as filtered.

**It does not draw anything.** There is no page in this change; see *Why these
two files*.

**It does not read `order_items`.** The value of an order is `orders.total`. The
line-level version is a different report and
`drafts/item-count-distribution.md` is its sibling on line counts.

**It does not touch `daily_metrics`.** There is a precomputed `aov` there and it
is a mean, so it cannot serve a distribution. Reading it would put this report
behind the metrics pipeline for nothing.

**It does not re-litigate the 21 Sep retirement.** See the second section. That
is a decision for whoever accepts this draft, not work for the build agent, and
nothing in the five requirements depends on how it is resolved.
