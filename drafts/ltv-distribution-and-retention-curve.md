# Draft spec — an LTV distribution and a retention curve that are not conditioned on a source

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
title: Report customer lifetime value as a distribution and a retention curve, computed from orders rather than read from customers.total_spent
writable_paths:
  - api/analytics/routes/customers.py
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/sources.py
```

## What is missing

`specs/metorik-gap.md` carries this in the Weekly band as **Partial**: *"`customers.total_spent`
and `aov` are stored, and `/sources/insights` computes LTV by acquisition source over a
365-day lookback. There is no LTV distribution or retention-curve report."* The candidate in
`research/candidates-metorik-gap-2026-09-10.md` re-verified that at platform sha
`6fd8ddd` and it still holds: `average_ltv` appears twice in
`api/analytics/routes/sources.py`, and the string `ltv` appears in
`api/analytics/routes/customers.py` zero times. Every LTV figure in the product today is
therefore an *average*, and an average *per acquisition source*.

Two things are missing and they are different questions:

* **A distribution.** A merchant asked "what is a customer worth" is given one number per
  channel. One number cannot say whether the channel's customers are uniformly mediocre or
  a handful of whales carrying a long tail, and those two stores are run differently.
* **A retention curve.** `cohort_analysis()` exists and the cohorts page renders it as a
  heatmap by acquisition month — that is retention *per cohort*, which is the right shape for
  spotting a bad month and the wrong shape for the question "how many of our customers come
  back, and when". The aggregate curve is not derivable by eye from a matrix whose cells have
  different denominators and different amounts of elapsed time.

## And there is a third thing, which is why this is worth more than a parity tick

Every LTV figure in the product reads `customers.total_spent` — a stored derived column.
`principles.md` is explicit: *"Read a field before storing a derived copy of it. A stored
value that looked obviously right has twice turned out to mean something else."* The same
tree already warns about the neighbouring column:
`api/analytics/services/analytics_engine.py` carries a comment about
`customers.first_order_at` disagreeing with the derived value, and
`research/metorik-gap-2026-08-30.md` lists "customer counts, LTV distribution, or whether
`customers.first_order_at` still disagrees" among the claims it **could not check**, because
the evidence pack's reader could see four tables and `analytics_N.customers` was not one of
them.

So the stored column has never been read against the orders it is derived from. A
distribution is the report that makes such a drift visible, and it would be built on top of
the unchecked column unless the spec says otherwise. It says otherwise: the figures below
are computed from `orders`, and the response carries the comparison against the stored
column as a first-class field.

## Why `dd_api` and why one link rather than a chain

The gap is an absent computation, not an unwired one. `contracts/deadly-digital-platform-api.yaml`
makes `api/analytics/routes/customers.py`, `api/analytics/routes/sources.py` and
`api/analytics/services/analytics_engine.py` writable, and its verification — compileall,
ruff-no-new-findings, both pytest suites, and a new test proven to bite — is what can
actually judge this change.

**The candidate also suggests the customers page, and this draft deliberately does not
declare it.** `specs/auto-approval.md` §12 provides for exactly that split: one `fleet-spec`
block per link, and a chain that merges whole or not at all. It is not usable here, and the
reason is mechanical rather than editorial. `console/autoqueue.py` writes the **whole draft**
into `tasks.spec_md` for *every* link, and `contracts/checks/spec_requirements_cited.py` —
first in the verification list of both contracts — fails a task unless every numbered
requirement in its `spec_md` is cited by a line that task's diff **adds**. A two-link split
therefore gives the API link a set of frontend requirements it cannot cite and the frontend
link a set of API requirements it cannot cite, and the only way through is for one of them to
write a `spec:` token over work it did not do, which that check names as a lie rather than
an oversight. Both links would fail, and under §12.6 a half-failed chain returns the
candidate to PENDING with the branches unmerged.

So: one link, and **the surface is a second draft**, written the way
`drafts/order-filters-frontend.md` was written — after the endpoint exists and its response
shape can be quoted rather than predicted. That draft declares
platform/app/(dashboard)/analytics/customers/page.tsx and the proxy directory under
platform/app/api/analytics/customers, both of which
`contracts/dd-analytics-frontend.yaml` already makes writable. Until it lands this feature
reaches nobody, which is the pile that contract's own header complains about — it is named
here rather than left to be discovered.

---

## 1. Lifetime value is computed from orders

**1.1 One definition, in the engine.** `api/analytics/services/analytics_engine.py` gains a
helper that returns a per-customer lifetime total: the sum of `total` over that customer's
**revenue-status** orders, grouped by customer. It reads `orders`. It does not read
`customers.total_spent`, and it does not fall back to it when the orders query returns
nothing.

**1.2 Lifetime is not clipped to the window.** `start` and `end` select the **population** —
customers whose *first* revenue-status order falls inside the window, which is the same
acquisition-cohort definition `cohort_analysis()` already uses — and the spend summed for
each of them is all of it, before and after the window. A "lifetime" value windowed to a
month is a monthly value with a misleading name.

**1.3 Both order populations are named, never collapsed.** The tree's existing rule
(`api/analytics/services/order_query.py` and the summary in
`api/analytics/services/analytics_engine.py`) is that an all-status count and a
revenue-status count are both reported. The response carries the revenue-status customer
count that the distribution describes **and** the all-status count of customers acquired in
the same window, as two named fields.

**1.4 A customer with no revenue-status order is out of the population, and counted.**
Dropping them silently makes the median look like the store's median when it is the median
of the customers who bought something. The difference between 1.3's two counts is that
number and the response states it.

## 2. The distribution

**2.1 A new endpoint, `GET /api/analytics/customers/ltv`.** Added to
`api/analytics/routes/customers.py` beside the cohorts endpoint, taking `start` and `end` on
the same terms as the routes already there, and mounted the same way. Additive only: no
existing route's response changes shape.

**2.2 Percentiles are the primary statement.** p10, p25, p50, p75, p90, p95 and p99, plus
mean, minimum, maximum and `n`. These are scale-free, which matters because nobody has yet
read this tenant's customer table (see above) and a histogram whose edges were guessed could
put 99% of the store in one bucket.

**2.3 A histogram beside them, with its edges echoed.** Fixed money edges, chosen in the
implementation and **returned in the response** rather than assumed by the reader, with one
entry per bucket carrying the lower edge, the upper edge, the customer count and the share.
Empty buckets are present with a count of zero — an absent bucket and an empty one read
identically on a chart and mean different things.

**2.4 Units are the order currency, unconverted.** `specs/metorik-gap.md` records every
production order as GBP and multi-currency as out of scope; this endpoint does no conversion
and the response says which currency it is reporting rather than leaving it implied.

## 3. The retention curve is derived from the cohort matrix, not defined a second time

**3.1 It reuses `cohort_analysis()`.** The curve is the cohort matrix aggregated down its
horizon columns: for horizon month *m*, the share of the population that placed a further
revenue-status order in month *m* after their first. Writing a second retention query would
create two numbers for one question that can disagree, and the existing one is already on a
page a merchant reads.

**3.2 A month that has not elapsed is `null`, never zero.** `specs/metorik-gap.md` singles
this out as the thing `cohort_analysis()` gets right and *"most implementations collapse"*.
The aggregate must not lose it: a cohort contributes to horizon *m* only if month *m* has
fully elapsed for that cohort, and a horizon no cohort has reached is reported as `null`
with the count of contributing cohorts beside it.

**3.3 Every point carries its denominator.** Horizon *m* is a share of the cohorts that
could have reached it, not of the whole population, and those are different numbers at the
tail of the curve. The response carries the numerator and the denominator per point so the
frontend cannot render a share whose base it does not know.

**3.4 The curve and the heatmap agree.** The new test asserts the aggregate against a
fixture where the per-cohort figures are known, so a later change to `cohort_analysis()`
cannot move one and not the other without something failing.

## 4. The stored column is read before it is trusted

**4.1 The response carries a drift block.** Comparing the per-customer figure from 1.1
against `customers.total_spent` over the same population: the number of customers compared,
the number differing by more than one penny, the largest absolute difference, and the signed
difference of the two totals. This is the field that makes principles.md's rule operative
rather than quoted.

**4.2 The drift is reported and never repaired.** No `UPDATE`, no backfill, no write of any
kind. `api/alembic/**` and `api/analytics/migrations/**` are protected under this contract
and nothing here needs them; a column that turns out to be wrong is a separate decision
someone makes with this report in hand.

**4.3 A zero drift is stated, not omitted.** If the column agrees everywhere, the block is
still present with zeros. An absent block reads as "not checked", and the point of this
requirement is the difference between those two.

## 5. One definition of LTV across the API

**5.1 `api/analytics/routes/sources.py` uses the shared helper.** Its `average_ltv` is
computed from the 1.1 helper rather than from `customers.total_spent` directly, so the
per-source average and the distribution are two views of one number instead of two numbers.

**5.2 The 365-day lookback in that route does not change.** What changes is where the
per-customer figure comes from, not which orders the source report covers. If the figure on
the sources page moves, it moves because the stored column was wrong, and the branch's reply
says by how much — the 4.1 block measures exactly that.

## 6. A test that fails without this change

**6.1 One new file, `api/tests/analytics/test_fleet_ltv.py`.** The contract's
`creatable_paths` allows `api/tests/analytics/test_fleet_*.py` and nothing else; no existing
test may be edited, and `new_test_bites.sh` proves the new one fails against the tree before
the change.

**6.2 It asserts the three properties that would otherwise ship silently**: that an
unelapsed horizon is `null` rather than zero (3.2), that the drift block is populated from a
fixture where the stored column deliberately disagrees with the orders (4.1), and that
lifetime spend outside the window is included for a customer acquired inside it (1.2). A
test that only asserts the endpoint returns 200 satisfies the bite check and establishes
nothing.

---

## What this task must not do

* **No migration and no schema change.** Everything above is computable from `orders` and
  `customers` as they stand.
* **No page, no proxy, no sidebar entry.** Those are the follow-up draft's, under a contract
  that can typecheck and render-test them. `api/**` is protected under
  `contracts/dd-analytics-frontend.yaml` and `platform/**` under this one, in both
  directions and on purpose.
* **No touching `api/app.py`, the email surface or the GDPR path.** All floored, none
  needed.
* **No second retention definition.** 3.1 is the whole of the design here.

## Before this is queued

* **The bucket edges in 2.3 are a guess and are labelled as one.** No reader in this fleet
  has ever seen `analytics_N.customers` — `research/metorik-gap-2026-08-30.md` says so in
  its own "what I could not verify" section. 2.2 exists so that a bad guess degrades the
  histogram and not the report.
* **4.1 may return a large number, and that is a result rather than a failure.** If
  `customers.total_spent` disagrees with `orders` at scale, then the LTV figures already on
  the sources page are wrong today, and 5.1 changes them in the same commit that measures
  them. Whoever reviews this branch should read the drift figure in the reply before reading
  the diff.
* **The feature is invisible until the second draft lands.** Stated in full above rather
  than assumed: this merges under `auto_merge: true` with nobody reading it, and the only
  thing that surfaces it afterwards is the morning brief's list of what shipped unattended.
