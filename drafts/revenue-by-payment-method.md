# Draft spec — break revenue down by payment method, and name the orders that carry none

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Break revenue down by payment method on the revenue summary — orders, gross, refunds and AOV per method, with the orders carrying no method reported as a named bucket
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
```

## What is missing, re-measured against the tree

`specs/metorik-gap.md` carries **Payment method breakdown** as *Partial*:
`payment_method` populated on 2,782,530 of 2,844,177 orders and shown on order rows;
no report groups by it.

That is still exactly true at the tree this spec was written against. `payment_method`
reaches the order list three ways and stops there:

| Where | What it is |
|---|---|
| `api/analytics/routes/orders.py` | a `payment_method` query parameter, described as an exact match |
| `api/analytics/services/order_query.py` | `o.payment_method = :payment_method` in `_filter_clause`, and the column in the row `SELECT` |
| `api/analytics/models.py` | `payment_method = Column(String(50))`, nullable |

The string does not occur in `api/analytics/routes/revenue.py` at all, and does not occur
in `api/analytics/services/analytics_engine.py` at all. A filter answers *"show me the
orders paid by PayPal"*. It does not answer *"what share of the money came through each
gateway"*, and nothing does.

So this is an absent computation over a stored, well-populated column — the same shape of
gap, on the same table, as the coupon block that shipped from
`drafts/coupon-performance-on-the-revenue-summary.md`.

## Two things this spec decides rather than leaves to the implementation

### The 61,647 orders with no payment method are named, not dropped

2,844,177 − 2,782,530 = **61,647 orders**, 2.17% of the table. A `GROUP BY
payment_method` drops them silently — `NULL` forms no group a reader is shown, and the
percentages beside the remaining rows then sum to 100% of a population that is 97.83% of
the store while being printed as though it were the store.

That is the same scruple `coupon_breakdown` already applies with `not_returned`, and the
same one `revenue_summary` applies when it reports `orders_with_refund` beside
`net_revenue` so that *"no refund is recorded"* cannot be read as *"refunds netted to
nothing"*. Requirement 4 below makes the bucket a first-class part of the response, and
requirement 4 is the reason this row is worth building rather than a decoration on it.

**The gap document's figure does not distinguish `NULL` from the empty string**, and
the two behave differently downstream: `_filter_clause` in
`api/analytics/services/order_query.py` tests `if payment_method:`, so an empty-string
method cannot be filtered for — the parameter is falsy and the whole predicate is
skipped, returning the unfiltered list. A row in this breakdown keyed on `''` would be a
row that clicks through to *every* order. Requirement 4 therefore counts the two
separately, and requirement 3 keeps the empty string out of the per-method rows.

### It goes on the revenue summary, because the page for it cannot be built

`platform/components/layout/Sidebar.tsx` carries a comment listing analytics pages the
nav is designed around that do not exist, and `/analytics/payment-methods` is one of the
five. **It is a reserved nav slot, and no unattended task can fill it.**
`contracts/dd-analytics-frontend.yaml` enumerates the page directories it may write —
`churn`, `customers`, `geography`, `orders`, `products`, `revenue`, `segments`, `sources`,
plus the two named files at the root of `platform/app/(dashboard)/analytics/` — and a
`payment-methods` directory is in none of them. `Sidebar.tsx` itself is writable only
under `contracts/dd-acquiring-page.yaml`. A candidate proposing that page can only be
refused for the path, which is how task 23 died on
`api/analytics/routes/coupons.py`; `specs/candidate-paths-must-be-buildable.md` is the
rule that now catches it earlier.

The revenue page exists, it reads `GET /api/analytics/revenue`, and `revenue_summary()`
in `api/analytics/services/analytics_engine.py` already computes window totals — gross,
net, refunded amount, orders with a refund, and the coupon block — over one window and
one status rule. *Orders, gross and AOV per payment method* is the same shape of figure
over the same rows in the same window. Put there, it inherits a window selector, a status
predicate and a live page rather than restating any of them.

**`revenue_summary()` has exactly one caller**, `api/analytics/routes/revenue.py`. It is
not on the dashboard route, so the cost this adds is paid by the revenue page and by
nothing else — which is what makes requirement 5's single extra scan affordable without a
switch to turn it off.

## The band is Rarely, and stays Rarely

`specs/metorik-gap.md` files this row under **Rarely**, and the well-populated column is
not a reason to move it. The band estimates how often somebody opens the report; the
97.83% coverage is a fact about HIB's data. Promoting on the second would be answering
the first question with the wrong evidence — and the Agency-use column is already the
document's own first entry under *What I could not verify*, an estimate with no agency
asked and no usage data behind it. Nothing here is a stronger reading of it.

What justifies building a *Rarely* row now is cost, not demand: two files, one function
beside one that already exists, one extra grouped scan, and a test. It is cheap because
the coupon block paid for the shape.

## Contract, and why this one

`contracts/dd-order-filters.yaml` is the other `dd_api` contract on this repo. Its whole
writable set is `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py` — neither file in the block above — so it cannot
make this change at all, and its three checks are a compile, a lint ratchet and an
order-filter shape check that would say nothing about an aggregate.

`contracts/deadly-digital-platform-api.yaml` covers both declared paths, runs
`tests/unit` and `tests/analytics` per file, and requires one added test proven by
`contracts/checks/new_test_bites.sh` to fail against the tree before the change. For a
new SQL aggregate over a column with a `NULL` tail, that is the difference between the
work being tested and not.

**Citing the requirements.** Each numbered requirement must be cited by a line the diff
adds — `# spec:4` on the line computing the unattributed bucket, and so on.
`contracts/checks/spec_requirements_cited.py` runs first in that contract's verification
list and fails the task otherwise. Six requirements, against a `max_requirements` of 10.

---

### 1. An additive block on the revenue summary, and no new route parameter

`revenue_summary()` in `api/analytics/services/analytics_engine.py` gains one new
top-level key on the dict it already returns, holding everything in requirements 3, 4 and
5. The computation lives in a new function in the same file, beside `coupon_breakdown`
and shaped like it.

**No existing key changes name, meaning or value.** The revenue page reads this object
today and `platform/**` is protected under this contract, so a renamed or recomputed key
ships a silently different number with nothing able to notice. That is the discipline
`specs/net-revenue-after-refunds.md` established for net beside gross and the coupon block
kept.

`api/analytics/routes/revenue.py` gains **no new query parameter**. The coupon block took
`coupon_limit` because `coupon_limit=0` skips a whole grouped scan over 65,444 distinct
codes and an ordinary page load wants that cheap path. Payment methods are the store's
enabled gateways; there is no equivalent saving, the page always wants the block, and a
second knob on an endpoint nobody has asked to tune is surface without a caller. The route
change is therefore comment only, or nothing at all — and no new route module, since
`writable_paths` on this contract is enumerated and `creatable_paths` admits only the one
test file.

### 2. The same window and the same population as the figures beside it

The breakdown uses the window bounds and the revenue-status predicate that
`revenue_summary()` already applies to gross and net — read them in the file and reuse
them; do not write a second list of statuses and do not re-derive the bounds. Two
definitions that can drift is how a payment-method table and the gross figure printed
above it come to disagree about the same window.

Where the surrounding code reports both populations — all-status and revenue-status — as
separately named figures, so does this. Every money figure here is revenue-status only,
matching `revenue` and `net_revenue`; every count carries both.

### 3. One row per method, keyed exactly as stored

Rows carry the payment method, the all-status and revenue-status order counts, the gross
total, the refunded amount over those same rows, and the AOV computed as that gross over
that revenue-status count. Ordered by gross descending, tie-broken on the method itself,
which is unique by construction and is the group key (BUG-008 — an `ORDER BY` feeding a
`LIMIT` needs a total order).

The `GROUP BY` key is `payment_method` **exactly as stored**: no `LOWER()`, no `TRIM()`,
no mapping of gateway ids to display names. `_filter_clause` in
`api/analytics/services/order_query.py` matches `o.payment_method = :payment_method`,
exact and case-sensitive, so a normalised value here is a row that clicks through to an
empty order list. If a display name is ever wanted it is a second field beside the stored
one, and a decision somebody takes with this report in hand.

Rows exclude `NULL` and the empty string. Both are reported by requirement 4 instead,
because neither can be clicked through to and both are facts about coverage rather than
about a gateway.

### 4. The orders with no payment method are a named bucket, and coverage is stated

Beside the rows, as named fields:

* the count and gross of orders whose `payment_method` **is NULL**, both populations;
* the count and gross of orders whose `payment_method` **is the empty string**, both
  populations, kept separate because the gap document's coverage figure cannot tell them
  apart and because the order-list filter cannot match one of them;
* the two added together, so a reader has the total unattributed figure without doing the
  arithmetic;
* the share of revenue-status orders, and the share of gross, that the rows in
  requirement 3 actually cover.

On the production reading in `specs/metorik-gap.md` that share is 97.83% of orders. **A
table that does not print it reads as the whole store.** A zero is reported, not omitted:
a window in which every order carries a method returns these fields present and zeroed,
because *checked and none* and *not checked* are the difference this requirement exists
to make.

### 5. Bounded, self-describing, and one extra scan

Two grouped aggregations at most, and in practice one scan each: one aggregate over the
window yielding the unattributed counts of requirement 4, the distinct-method count, the
currency and the coverage denominators; one `GROUP BY payment_method ... ORDER BY ...
LIMIT` yielding requirement 3. Never a query per method, and never a round trip per row.

The row list is bounded by a ceiling constant in
`api/analytics/services/analytics_engine.py` — a judgement, not a measurement, and
labelled as one in the code: nothing in this run measured the distinct-method cardinality
on production, only the coverage. A few dozen is generous for a store's enabled gateways
and cheap insurance against a tenant whose connector writes something per-transaction
into that column. Beside the rows, the same tail the coupon block reports: the total
number of distinct methods in the window, the number returned, and the order count and
gross of those **not** returned, obtained by subtracting the returned rows from the
requirement 4 totals rather than by a third query.

Currency is named rather than implied, with a flag saying outright when the window holds
more than one, exactly as `coupon_breakdown` does. No conversion: `specs/metorik-gap.md`
records every production order as GBP and multi-currency as out of scope.

### 6. A test that fails without this change

One new file, `api/tests/analytics/test_fleet_payment_methods.py`. This contract's
`creatable_paths` admits `api/tests/analytics/test_fleet_*.py` and nothing else, no
existing test may be edited, and `contracts/checks/new_test_bites.sh` proves the new one
fails against the tree before the change — it also refuses a diff adding more than one
test file, so this must not be added to `api/tests/analytics/test_fleet_coupons.py`, which
already exists and is protected anyway. Its budget is `max_test_diff_lines`, separate from
the production 400.

It asserts four things, because a test that only checks for the key's presence satisfies
the bite check while establishing nothing:

* the block appears on the revenue summary and every pre-existing summary key keeps its
  name and its value, the coupon block included — requirement 1;
* over a fixture with two methods whose AOVs differ, both rows are returned and each AOV
  equals that row's own gross over its own revenue-status count — requirement 3;
* a fixture seeded with `NULL` methods, empty-string methods and populated ones reports
  the two unattributed figures **separately and non-zero**, and the stated coverage share
  equals the rows' orders over the window's revenue-status orders — requirement 4. This is
  the test that would fail a `GROUP BY` that silently drops the `NULL`s;
* a fixture carrying more distinct methods than the ceiling returns exactly the ceiling's
  worth of rows and a tail whose count and gross account for the remainder —
  requirement 5.

---

## What this task must not do

* **No page, no proxy, no sidebar entry.** `platform/**` is protected under this
  contract, and the `/analytics/payment-methods` slot is writable under no contract
  either. Rendering this on the existing revenue page is a later frontend draft against
  `contracts/dd-analytics-frontend.yaml`, whose `revenue` directory it already covers.
  Named here so it is a known follow-up rather than a discovery.
* **No new route module and no new service module.** The two files in the block are the
  whole of the production diff.
* **No migration and no index.** `api/analytics/migrations/**` and `api/alembic/**` are
  protected here and nothing above needs either; `payment_method` is a stored column that
  `api/analytics/services/sync_engine.py` already writes on every upsert.
* **No change to the order-list filter.** The `payment_method` parameter on
  `api/analytics/routes/orders.py` works and is deployed. Its empty-string blind spot is
  *reported* by requirement 4 and not fixed here — changing that predicate is a change to
  a shipped filter's behaviour, which belongs to whoever reads the number this produces.
* **No gateway display names, no grouping of variants.** Requirement 3 says why: the
  click-through is an exact match.
* **No reformatting and no unrelated lint fixes.** The ruff gate is a ratchet that
  tolerates existing findings — `api/analytics/routes/revenue.py` carries a pre-existing
  I001, recorded in `contracts/deadly-digital-platform-api.yaml`'s own header — so a
  tidy-up is pure diff with no gate asking for it, and `api/ruff.toml` is protected.

## Before this is queued

* **Locate `revenue_summary()` and `coupon_breakdown()` by name, not by line number.**
  Nothing above quotes a line number for that reason: the file has moved under its
  recorded line numbers before, and `specs/net-revenue-after-refunds.md` says the same
  thing.
* **The `NULL`/empty-string split is a prediction, and requirement 4 is how it gets
  tested.** The 61,647 figure is a subtraction from `specs/metorik-gap.md`'s two counts,
  and the document does not say which side of it the empty string falls on. If the
  empty-string figure comes back large, the connector is writing `''` where WooCommerce
  gave nothing, and that is a sync defect worth its own row — findable only because this
  requirement counts the two apart.
* **The ceiling in requirement 5 is unmeasured and says so.** The tail is what keeps a
  wrong ceiling from becoming a wrong report, which is the argument the coupon block's
  `not_returned` already makes at 65,444 codes.
* **This merges with nobody reading it.** `auto_merge` is `true` on
  `contracts/deadly-digital-platform-api.yaml`, and that file's header sets out the cost:
  five of six requirements can ship with every check green and no revert triggered,
  because there is nothing to revert. The `spec:N` tokens in the diff are the only trace.
  `specs/unattended-operation.md` §3.2 is the distinction being relied on — the suites
  prove nothing broke, `contracts/checks/new_test_bites.sh` proves the added test
  discriminates, and neither proves the other five requirements were built. If one
  requirement is read against the diff by hand, make it 4.
