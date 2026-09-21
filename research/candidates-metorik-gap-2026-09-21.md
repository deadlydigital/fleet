# Candidates from the Metorik report classification — batch 23

Produced 2026-09-21. Serves `dd-feature-parity`.

This is the second producer batch read from
`research/metorik-report-classification-2026-09-15.md`. The first was batch 16
(`research/candidates-metorik-gap-2026-09-16.md`), five days ago, and this run
exists because of one line in it: nine of the thirty bucket-A rows were dropped
for the ten-row ceiling and not for merit, and batch 16 closed by asking
"whether the nine rows dropped for the ceiling are still open next week".

They are. All nine, established against `deadly-digital-platform` at **fd5a404**
rather than assumed from batch 16's table, and all nine are emitted here. That
is one under the ceiling, and the tenth slot is deliberately left empty; the
disposition table below says what was considered for it and why it was not
taken.

## What moved in the platform tree between 7a09b92 and fd5a404

Batch 16 read the platform at `7a09b92`. Five of its ten candidates have landed
since, and one row it emitted turns out to have landed as well, which changes
what this batch may propose. Taken from the tree, endpoint by endpoint:

| Batch 16 row | State at fd5a404 |
|---|---|
| Item count distribution (c3) | **shipped** — `GET /orders/item-counts` at `api/analytics/routes/orders.py:357`, backed by `item_count_distribution` in `api/analytics/services/order_query.py:668`, with a twenty-bucket cap and a named `tail` |
| Average order item count (c4) | **shipped** — `avg_items` per period in the revenue series, documented at `api/analytics/routes/revenue.py:82` |
| Orders by day of week (c5) | **shipped** — `GET /orders/by-weekday` at `api/analytics/routes/orders.py:426`, `EXTRACT(ISODOW ...)` at `api/analytics/services/order_query.py:960`, bucketed in the report timezone |
| Product comparison (c9) | **shipped** — `GET /products/compare` at `api/analytics/routes/products.py:280`, `compare_products` in the engine |
| **New vs returning customer orders (c69)** | **SHIPPED, and the task row says otherwise** — see below |
| Orders by hour of day (c74), Orders heatmap (c75) | not in the tree; no route, no engine function. Queued as tasks 136 and 137, attempt 2 as of today. **Not proposed here.** |
| Order sources by UTM combination (c76) | still open; `/sources` still groups `fo.utm_*` — the first-order attribution — at `api/analytics/routes/sources.py:311` |

**`New vs returning customer orders` has shipped, and this is the one place the
task's own input is wrong.** The spec for this run records c69 as "task 118
FAILED at 2/2 — attempts exhausted". The work is nonetheless in the tree:
`_NEW_VS_RETURNING_SELECT` at `api/analytics/services/analytics_engine.py:111`
appends six columns — `new_orders`, `returning_orders`, `new_revenue`,
`returning_revenue`, `unattributed_orders`, `unattributed_revenue` — off the
acquiring-order lookup, read back by `_new_vs_returning` at line 134 and
switched on for the dashboard overview at line 951. It carries a spec:5 note
saying free entries are in, both halves. A failed task row is not a claim that
the work does not exist, and c69's own probes (`new_orders|returning_orders`
expected 0 in the engine) will now retire it at the next sweep without anybody
doing anything. **I have not proposed it**, and it is not one of the nine.

That is the same mechanism that retired `Order value distribution` and
`Category comparison` on 21 Sep, and it is worth noting what it costs: c2's
retiring probe was `WIDTH_BUCKET|width_bucket` over the whole engine, and what
put `width_bucket` there is `ltv_distribution` at
`api/analytics/services/analytics_engine.py:3568`, which buckets **lifetime
spend per customer**, not **order total per order**. Those are different
reports. I did not re-open that row — it was retired by a decision I am not
re-litigating — but a reader should know that no endpoint in this tree returns
a histogram of `orders.total`, and that the probe which said otherwise was
reading a neighbouring feature. It is the c28 failure shape in a retiring probe
rather than in a proposing one.

## The nine, established from the tree rather than from batch 16's table

Every one was checked against `fd5a404` by reading the module that would hold
it, not by trusting the row above. What follows is the finding per row; the
sizes are judged from the tree, because **A is a statement about data and not
about difficulty**.

**The three forecast rows are open and there is no forecasting code at all.**
`[Ff]orecast` returns zero matches across every `.py` under `api/analytics`, and
zero across every `.tsx` under the analytics dashboard. Batch 16 called these
the largest of the thirty — "a fit, a horizon and a confidence band are a
service module, not a `GROUP BY`" — and I agree, with one correction in their
favour: the history each one fits is **already materialised**. `DailyMetrics` at
`api/analytics/models.py:260` stores `date`, `revenue`, `orders` and
`new_customers` per day, one row per day, backfilled by `backfill_daily_metrics`
at `api/analytics/services/analytics_engine.py:481`. So the three rows are one
service module and three thin callers over a stored series, not three
independent projects. They are emitted separately because they are three rows in
the source document, and each rationale says so.

**The four retention rows are open, and one of them is now half-shipped.**

* *Orders made over customer lifetime* — nothing buckets a per-customer order
  count. `ltv_distribution` buckets money; `item_count_distribution` buckets
  lines per order. Both are the pattern this row reuses, and neither is this
  row. Small: one `GROUP BY` over a count, plus the bucket-and-tail convention
  the item-count distribution already settled. Batch 16 called it "the best
  Monthly row for the next batch" and I have no reason to move it.
* *New vs returning customer KPIs* — **the counts and the revenue shipped with
  c69 and the AOV did not**, and the engine says so in its own words at
  `api/analytics/services/analytics_engine.py:105`: "a free entry can be a
  customer's ACQUIRING order, which books an acquisition at £0, so
  `new_revenue / new_orders` carries a dilution specific to the new bucket. A
  per-bucket AOV needs the free-entry split decided first and is not this
  task." The split has since been decided — `free_entry_convention` at line 279
  and `aov_paid`/`orders_free` are live on `/revenue` and `/dashboard`. So this
  row is now the one deferred figure, with the thing it was waiting for in
  place. Small.
* *Time between repeat orders* — the window function exists and is used once,
  for something else: `churn_engine.py:192` computes
  `created_at - LAG(created_at) OVER (PARTITION BY customer_id ...)` and takes a
  **single median restricted to gaps over 30 days**, emitted as one sentence of
  churn-insight prose. The report is that same expression kept as a
  distribution over all gaps. Batch 16 called it "a window function over
  `created_at` partitioned by `customer_id`; small", and the tree agrees — and
  adds that the expression is already written.
* *Items bought over customer lifetime* — nothing aggregates line items per
  customer. Same shape as *Orders made over customer lifetime* and it should be
  taken with it or after it; the rationale says so rather than leaving an
  approver to find out.

**`Frequently bought together` is open and the bound batch 16 asked for now
exists.** Batch 16 said a self-join over 4.55M line rows "needs a bound before
it is unattended work". Migration 0015,
`api/analytics/migrations/versions/v0015_order_items_order_covering_index.py`,
built `ix_analytics_order_items_order_covering` on
`(order_id, wc_product_id, product_name, total, quantity)` — `order_id` leading
because that is what a join on it seeks, with the product columns covering so
the scan is index-only. That is precisely the index a co-occurrence self-join on
`order_id` needs. It does not make the row small: the bound still has to be
stated as a window, a minimum support and a pair cap, and the rationale says
which. But it is no longer unbounded work over an unindexed table.

**`By currency` is open, and it is the weakest of the nine.** `orders.currency`
is set on all 2,889,850 rows and nothing groups orders or revenue by it on any
endpoint. But the engine is not silent about currency either: `revenue_summary`
and `payment_method_breakdown` both carry `currency` and a `mixed_currency`
boolean, and `ltv_distribution` runs an actual `GROUP BY o.currency` at
`api/analytics/services/analytics_engine.py:3635` and **throws the count away**,
keeping only the list of codes. The classification's own note stands — "the pack
did not count distinct values, so the report is buildable and may well return
one row". It is emitted, with that said in the rationale rather than
discovered after the work.

## Why nine and not ten, and what the tenth slot was considered for

The ceiling is ten. Nine survived, so nothing was dropped for the ceiling this
time — which is the state batch 16 wanted and did not have.

Two rows were considered for the tenth slot and neither was taken:

* **`New vs returning customer orders` (c69)** — shipped at HEAD, as established
  above. Not a candidate.
* **`Order sources by UTM combination` (c76)** — genuinely open, Weekly band,
  and therefore the row that would rank highest of anything in this document.
  **It is already a live candidate in the pool.** Its draft-spec task 123 failed
  and no work task was created, which is a task-level failure and not a missing
  candidate: nothing about c76's ground has changed, its probes still hold, and
  the row is still there to be ticked. Emitting a second row for it would create
  a second `(title, repo)` identity for one piece of work — and since 047 makes
  `candidate_work_identity()` fall back to `(title, repo)` for a `topic:` key,
  a new title is exactly what resets the repeat-failure count the ceiling reads.
  Proposing it again would not be re-proposing the work; it would be laundering
  its failure history. If c76 should be retried, the retry belongs on c76.

The task spec permits proposing c76 provided the rationale names the prior
failure. I have declined the permission rather than used it, and the reason is
above so that the next batch can disagree with it deliberately.

## Rows I may not propose, restated because nothing mechanical stops me

Twenty-eight of the 100 rows are **N/A** and carry the words *do not propose* in
the row itself, on four facts Eamonn stated on 2026-09-16: HIB does not refund,
ships nothing, charges no VAT on entries, and sells no recurring product. None
of the nine emitted below is one of them. The probe vocabulary in
`contracts/checks/candidate_block_shape.py` is `path_exists`, `path_absent` and
`grep_count` over a source tree and contains no business predicate, so a
candidate for *By refund reason* would pass every check in this repository while
proposing a report that returns empty forever. The row markers are the defence.

`orders.billing_state` is set on **0 of 2,890,319** rows, measured 2026-09-16.
No by-state grouping is proposed and no by-shipping-location grouping is
proposed. Carts (7 rows) and devices (3 rows) are bucket B and so not candidates
for this batch, and they are **real gaps and not inapplicable**.

`MUST SPLIT FREE ENTRIES` marks four rows and is not a refusal. One of the nine
carries it — *New vs returning customer KPIs* — and its candidate states
outright that free entries are **in**, both halves, matching the convention
`_NEW_VS_RETURNING_SELECT` already ships, and that the AOV must be emitted twice
rather than once.

## Disposition of all thirty bucket-A rows, and of the two open rows from batch 16

| # | Row | Section heading | Disposition at fd5a404 |
|---|---|---|---|
| 1 | Net/gross revenue over time | `Daily — Revenue (1 of 3)` | shipped before batch 16 |
| 2 | Orders over time | `Daily — Orders (3 of 10)` | shipped before batch 16 |
| 3 | New vs returning customer orders | `Daily — Orders (3 of 10)` | **shipped since batch 16** — `_NEW_VS_RETURNING_SELECT`, engine line 111. c69's own probes retire it; not proposed |
| 4 | Average order gross over time | `Daily — Orders (3 of 10)` | shipped before batch 16 |
| 5 | By status | `Daily — Order groups (1 of 6)` | shipped before batch 16 |
| 6 | New customers over time | `Daily — Customers (1 of 3)` | shipped before batch 16 |
| 7 | Top selling products | `Daily — Products (1 of 8)` | shipped before batch 16 |
| 8 | Revenue by billing/shipping location or payment method | `Weekly — Revenue (1 of 3)` | shipped before batch 16 |
| 9 | Order value distribution | `Weekly — Orders (7 of 10)` | c2 retired 21 Sep by its own probe. See the caveat above: no endpoint returns a histogram of `orders.total`, and the probe that retired it was reading `ltv_distribution` |
| 10 | Item count distribution | `Weekly — Orders (7 of 10)` | **shipped since batch 16** — `GET /orders/item-counts` |
| 11 | Average order item count | `Weekly — Orders (7 of 10)` | **shipped since batch 16** — `avg_items` in the revenue series |
| 12 | Orders by day of week | `Weekly — Orders (7 of 10)` | **shipped since batch 16** — `GET /orders/by-weekday` |
| 13 | Orders by hour of day | `Weekly — Orders (7 of 10)` | queued work — task 136, attempt 2, requeued 21 Sep. **Not proposed** |
| 14 | Orders heatmap (day × hour) | `Weekly — Orders (7 of 10)` | queued work — task 137, attempt 2, requeued 21 Sep. **Not proposed** |
| 15 | By payment method | `Weekly — Order groups (3 of 6)` | shipped before batch 16 |
| 16 | By billing/shipping location | `Weekly — Order groups (3 of 6)` | shipped before batch 16 on country, city and postcode; state is empty and shipping is N/A |
| 17 | Order sources by UTM combination | `Weekly — Acquisition / sources (6 of 6)` | open, and **already a live candidate (c76)**. Not re-proposed; see above |
| 18 | Coupon usage, amount discounted and sales generated | `Weekly — Coupons (1 of 1)` | shipped before batch 16 |
| 19 | Top selling categories | `Weekly — Products (4 of 8)` | shipped before batch 16 |
| 20 | Product comparison | `Weekly — Comparison (2 of 2)` | **shipped since batch 16** — `GET /products/compare` |
| 21 | Category comparison | `Weekly — Comparison (2 of 2)` | c10 retired 21 Sep by its own probe, `compare|comparison` over `api/analytics/routes/products.py` |
| 22 | Sales forecast (12 months) | `Monthly — Forecasts (3 of 3)` | **emitted** (candidate 1) |
| 23 | Order volume forecast (3/6/12 months) | `Monthly — Forecasts (3 of 3)` | **emitted** (candidate 2) |
| 24 | New customers forecast | `Monthly — Forecasts (3 of 3)` | **emitted** (candidate 3) |
| 25 | Orders made over customer lifetime | `Monthly — Retention (4 of 4)` | **emitted** (candidate 4) |
| 26 | New vs returning customer KPIs | `Monthly — Retention (4 of 4)` | **emitted** (candidate 5) — half-shipped; the AOV is the remainder |
| 27 | Time between repeat orders | `Monthly — Retention (4 of 4)` | **emitted** (candidate 6) |
| 28 | Items bought over customer lifetime | `Monthly — Retention (4 of 4)` | **emitted** (candidate 7) |
| 29 | Frequently bought together | `Monthly — Products (1 of 8)` | **emitted** (candidate 8) |
| 30 | By currency | `Rarely — Order groups (2 of 6)` | **emitted** (candidate 9) — the weakest of the nine, and the rationale says why |

Sixteen shipped, two queued, two retired by their own probes, one held as an
existing candidate, nine emitted.

## Paths, and why none of them is a directory

Every `suggested_paths` entry below names a FILE. `specs/candidate-paths-must-be-buildable.md`
is the rule and c24, c26 and the repaired c28 are why it exists. Each path was
checked against `contracts/deadly-digital-platform-api.yaml` (which lists
individual modules under `api/analytics/`, never the directory) and
`contracts/dd-analytics-frontend.yaml` (which globs the dashboard and proxy
directories). `contracts/dd-acquiring-page.yaml` owns no path any of these nine
would touch.

Six of the nine name both an `api/analytics/` module and a dashboard page, which
sit under **two different contracts** — the API contract protects `platform/**`
and the frontend contract does not make `api/analytics/` writable. That is a
split for the draft-spec step to make, not a defect in the paths, and it is the
same shape batch 16's ten carried. Three of them will also want a new Next proxy
route under `platform/app/api/analytics/...`; those directories are covered by
`**` globs in the frontend contract, so a new sibling route stays inside the
writable set.

**Every candidate carries at least one probe asserting the ABSENCE of the thing
the work would add**, because that is the only shape `console/retire.py` can
later read as "somebody did this". c28 is the worked example of getting this
wrong: it probed for a coupon column and a reserved nav slot, its report shipped
on 16 Sep, and none of its three probes noticed for five days.

## The candidates

```fleet-candidates
source:
  document: research/metorik-report-classification-2026-09-15.md
  sha: 80677a2
ordering: unranked
unasked_question: >-
  Nobody has asked HIB's team which of these reports they would open, and this
  batch is the one where that matters most. Every row below is Monthly or
  Rarely — the two bands the source document itself calls the most falsifiable
  column in it — so the whole batch rests on a judgement about a generic
  WooCommerce agency rather than on anything HIB has said. Three of the nine are
  forecasts, which is the largest work in the document, and a single sentence
  from HIB's team about whether they would ever act on a twelve-month projection
  would either promote them above everything in the pool or kill all three.
objectives_considered: >-
  dd-feature-parity and dd-trustworthy were weighed row by row and all nine
  landed on dd-feature-parity, which is the same answer batch 16 reached and
  deserves the argument again rather than by inheritance. dd-trustworthy covers
  figures DD already prints being wrong; none of these nine changes a printed
  number, because none of the nine reports exists at all. The genuinely close
  call is candidate 5: DD prints new_orders and new_revenue today, a reader can
  divide them, and the ratio they get is diluted by free entries — which is
  "one metric telling two stories" in everything but the metric being printed.
  It stays parity for the reason batch 16 gave about the same family: the AOV
  that would be wrong does not exist yet, and the free-entry convention block
  that will label it has already shipped. Candidate 9 was the second closest,
  since a by-currency grouping would test the mixed_currency boolean two
  endpoints already assert; it is still a new report and not a repair.
  dd-first-revenue and cost-discipline were considered and rejected: a report
  nobody has asked for is not a revenue event, and none of the nine changes what
  the fleet or the platform costs to run.
candidates:
  - title: Sales forecast over a twelve-month horizon, with the band stated rather than implied
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      DD has no forecasting code of any kind — `[Ff]orecast` returns zero
      matches across every module under api/analytics and every page under the
      analytics dashboard. This is the largest of the thirty bucket-A rows and
      the rationale says so rather than letting the A bucket imply it is cheap:
      a fit, a horizon and a confidence band are a service module, and the
      judgement in it is which fit and how wide the band, not the SQL. What
      makes it smaller than it looks is that the history is already
      materialised — daily_metrics stores revenue per day and
      backfill_daily_metrics fills it across the whole span — so the work is a
      fit over a stored series rather than a scan of 2.9M orders. It is one
      service module shared with candidates 2 and 3; an approver taking this
      one should expect the other two to be nearly free afterwards. No new
      column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Forecasts (3 of 3)
    hib_signal:
      value: >-
        2,889,850 orders spanning 1,283 days, 2023-03-12 to 2026-09-15 — about
        42 months, so a 12-month horizon is fitted on roughly three and a half
        times its own length. orders.total is NOT NULL on all 2,890,319 rows and
        non-zero on 2,823,569, so the measure a sales forecast fits is populated.
      as_of: "2026-09-16"
      coverage:
        metric: orders carrying a non-zero total, the measure a sales forecast fits
        populated: 2823569
        total: 2890319
    measured_impact: null
    unasked_question: >-
      Whether a twelve-month sales forecast is a number HIB would act on or a
      chart it would glance at. A prize competition's revenue is driven by which
      draws are running, which no time-series fit can see, and nobody has asked
      whether that makes the forecast decorative.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/revenue.py
      - platform/app/(dashboard)/analytics/revenue/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/services/*.py
          pattern: '[Ff]orecast'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/revenue/*.tsx
          pattern: '[Ff]orecast'
          expected: 0
    premise:
      - claim: >-
          A per-period revenue series over a chosen window already exists in the
          engine and is already served, so a forecast extends a series DD
          computes rather than defining a second revenue history beside it.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def revenue_report\('
            expected: 1

  - title: Order volume forecast at three, six and twelve months
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      The count half of the forecast group, and the cheapest of the three
      because it fits a stored integer rather than a money column: daily_metrics
      carries an `orders` count per day, written by compute_daily_metrics and
      backfilled across the history. Nothing forecasts it — there is no
      forecasting module, no horizon parameter and no projection anywhere in
      api/analytics. Three horizons rather than one is the part worth deciding
      before building: they are three reads of one fit, and emitting them as
      three numbers with three bands is a different screen from emitting one
      curve. Shares its service module with candidates 1 and 3. No new column,
      no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Forecasts (3 of 3)
    hib_signal:
      value: >-
        2,889,850 orders across 1,283 days on a timezone-aware created_at, every
        one of them counted — a volume forecast reads no nullable column, which
        is why this row carries no dagger in the source document.
      as_of: "2026-09-15"
      coverage:
        metric: orders carrying a created_at, the only column an order-volume fit reads
        populated: 2889850
        total: 2889850
    measured_impact: null
    unasked_question: >-
      Whether the three horizons are wanted as three numbers or as one curve
      with three markers, which decides whether this is a stat row or a chart
      and therefore most of the frontend cost.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/orders.py
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: '[Ff]orecast'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/*.tsx
          pattern: '[Ff]orecast'
          expected: 0
    premise:
      - claim: >-
          A daily order count is already stored per day and already backfilled
          across the tenant's whole history, so the series this forecast fits is
          materialised rather than re-derived from 2.9M order rows each call.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def backfill_daily_metrics\('
            expected: 1

  - title: New customers forecast, over the acquisition series DD already computes
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      The third of the forecast group and the one with the most settled input:
      customer_report already returns a per-period `new` count derived from
      orders rather than from customers.first_order_at, so the acquisition
      series a forecast would fit is the same series the customers page renders
      today and cannot disagree with it. Nothing forecasts it. The judgement
      specific to this row is that acquisition for a prize-competition store is
      campaign-driven, so a fit with no campaign term will read the end of a
      promotion as a trend — which is a reason to ship the band wide and label
      it, not a reason to skip the row. Shares its service module with
      candidates 1 and 2. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Forecasts (3 of 3)
    hib_signal:
      value: >-
        157,311 distinct customer_id values across the order table, each with a
        first order derivable from orders alone, over 1,283 days. No coverage
        ratio is stated because 157,311 is a count of DISTINCT VALUES and not a
        nullability proof — the engine makes the same point at
        analytics_engine.py line 92, where it counts customer-less orders as a
        third bucket rather than assuming there are none.
      as_of: "2026-09-15"
      coverage: null
    measured_impact: null
    unasked_question: >-
      Whether a new-customer forecast should be conditioned on planned draws.
      HIB knows its competition calendar and DD does not hold it, so the honest
      version of this report may be one that takes a planned-volume input nobody
      has offered to supply.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/customers.py
      - platform/app/(dashboard)/analytics/customers/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/customers.py
          pattern: '[Ff]orecast'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/customers/*.tsx
          pattern: '[Ff]orecast'
          expected: 0
    premise:
      - claim: >-
          A per-period new-customer count already exists in the engine, derived
          from the order table rather than from a stored first-order column, so
          the series this fit reads is the one already in front of a user.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def customer_report\('
            expected: 1

  - title: Orders made over a customer lifetime, as a bucketed distribution
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      How many customers bought once, twice, five times, twenty times. DD holds
      customers.order_count and ranks on it, and segment and churn code read it,
      but nothing anywhere buckets it into a distribution — the shape of the
      repeat-buying curve is the report and DD has only its mean. Small work,
      and the smallest of the nine: one bucketed count over orders.customer_id,
      no new column, no migration. Both halves of the pattern are already
      written and should be reused rather than reinvented — the LTV population
      CTE settles what "a customer in this window" means and refuses to clip a
      lifetime to it, and the item-count distribution settles the bucket cap and
      the named tail. Take this before candidate 7, which is the same query with
      a join and one more decision in it.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Retention (4 of 4)
    hib_signal:
      value: >-
        2,889,850 orders across 157,311 distinct customer_id values, a mean of
        18.4 orders per customer — high enough that the interesting part of this
        distribution is its tail and a naive twenty-bucket cap would fold most
        of the population into it. No coverage ratio: 157,311 is a count of
        distinct values, not a measure of how many orders carry a customer_id.
      as_of: "2026-09-15"
      coverage: null
    measured_impact: null
    unasked_question: >-
      Whether the buckets should be fixed widths or quantiles. With a mean of
      18.4 and an unmeasured tail, fixed widths could put almost everyone in one
      bucket, and nobody has said which HIB would read.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/customers.py
      - platform/app/(dashboard)/analytics/customers/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/customers.py
          pattern: 'orders_per_customer|order_count_distribution|orders-per-customer'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'order_count_distribution|lifetime_order_count'
          expected: 0
    premise:
      - claim: >-
          A per-customer population CTE with a settled window rule already
          exists in the engine — membership is the first revenue-status order
          inside the window and the lifetime measured is never clipped to it —
          so this distribution inherits that definition instead of choosing a
          fourth one.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def _ltv_population_cte\('
            expected: 1

  - title: Finish the new-versus-returning KPI block with the per-bucket AOV the engine deferred
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      Four of this row's five KPIs shipped since batch 16 — new and returning
      orders, new and returning revenue, plus an unattributed bucket that makes
      the partition exhaustive. The AOV did not, and the engine records exactly
      why at analytics_engine.py line 105: a free entry can be a customer's
      ACQUIRING order, so new_revenue / new_orders carries a dilution specific
      to the new bucket, and a per-bucket AOV needed the free-entry split
      decided first. It has since been decided — free_entry_convention and the
      aov_paid / orders_free pair are live on the revenue and dashboard
      payloads. So this is the deferred figure with its blocker removed, and it
      is small: two ratios off an aggregate that is already computed. FREE
      ENTRIES ARE IN, both halves, matching the convention the six shipped
      columns already use — and the AOV must be emitted TWICE, all-orders beside
      paid-only, never as one number. Emitting one would repeat the defect the
      third correction measured store-wide — £8.23 printed where paid-only is
      £8.43 — in a new place, on the one bucket where the dilution is worse
      than store-wide. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Retention (4 of 4)
    hib_signal:
      value: >-
        66,764 of 2,890,319 orders carry total = 0 and 66,676 of those are
        `completed`, so they sit inside the revenue statuses this split already
        counts. Store-wide that understates AOV by 2.4% — £8.23 against £8.43
        paid-only — and the new bucket is the one where an acquiring free entry
        lands, so its dilution is larger than the store-wide figure and is not
        measured anywhere.
      as_of: "2026-09-16"
      coverage:
        metric: orders carrying a non-zero total, the measure both bucket AOVs divide
        populated: 2823569
        total: 2890319
    measured_impact: null
    unasked_question: >-
      Whether HIB reads a free entrant who later pays as an acquisition at £0 or
      as an acquisition at their first PAID order. The two give different new-
      bucket AOVs and different acquisition dates, and nobody has been asked.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/revenue.py
      - api/analytics/routes/dashboard.py
    probes:
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'new_aov|returning_aov|aov_new|aov_returning'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'returning_aov|aov_returning'
          expected: 0
    premise:
      - claim: >-
          The new-versus-returning classification is already computed per order
          and read back as six columns off one row, so the missing AOVs are two
          divisions over aggregates that exist rather than a second pass over
          the order table.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def _new_vs_returning\('
            expected: 1

  - title: Time between repeat orders, as a distribution rather than one median
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      The gap between a customer's consecutive orders, across the window. DD
      computes this expression exactly once and throws almost all of it away:
      churn_engine.py line 192 builds created_at minus LAG(created_at)
      partitioned by customer_id, then takes a single median of gaps over 30
      days and renders it as one sentence of churn-insight prose. Everything
      else about the shape — the mode, the tail, whether repeat buying is daily
      or monthly on this store — is computed and discarded. Small work: the
      window function is written, and the report is the same CTE kept, bucketed
      and served. It also puts a number beside churn's avg_order_frequency_days,
      which is derived per customer as a span divided by a count and has never
      been checked against the actual gaps. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Retention (4 of 4)
    hib_signal:
      value: >-
        2,889,850 orders over 157,311 distinct customers on a timezone-aware
        created_at, a mean of 18.4 orders each, so most customers contribute
        several gaps rather than none. No coverage ratio is stated: the share of
        customers with two or more orders is computed live by churn_engine's
        repeat-rate insight and is recorded nowhere in the source document, so
        any ratio here would be invented.
      as_of: "2026-09-15"
      coverage: null
    measured_impact: null
    unasked_question: >-
      Whether the gap should be measured between all orders or only between
      PAID ones. A free entry placed between two purchases shortens every gap it
      sits in, and on a store with 66,764 of them that is not a rounding
      difference.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/customers.py
      - platform/app/(dashboard)/analytics/customers/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'gap_days|time_between|repeat_interval|between-orders'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'gap_days|repeat_interval'
          expected: 0
    premise:
      - claim: >-
          The per-customer order-gap window function already exists in this
          codebase and already runs against the revenue-status population, so
          this report keeps an expression DD computes rather than introducing
          window functions over the order table for the first time.
        probe:
          grep_count:
            glob: api/analytics/services/churn_engine.py
            pattern: 'LAG\('
            expected: 1

  - title: Items bought over a customer lifetime, and say whether it counts lines or units
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      How many items a customer has bought in total, bucketed across the
      customer base. Nothing aggregates line items per customer anywhere in the
      engine. This is candidate 4's query with a join to order_items and one
      extra decision — lines or units — which the shipped item-count
      distribution has already answered once for a different report, choosing
      lines and saying so in its docstring rather than reading quantity. A
      lifetime report should probably choose units, because 21.13 entries per
      line on free-entry orders means lines and units differ by more than an
      order of magnitude on part of this population, and the rationale states
      that rather than leaving it to be discovered. Take it after candidate 4,
      whose bucket-and-tail shape it reuses. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Retention (4 of 4)
    hib_signal:
      value: >-
        order_items.quantity is NOT NULL on all 4,550,334 rows and non-zero on
        4,550,326 of them, so a true unit count is available and not only a line
        count. The 73,378 line rows inside free-entry orders average 21.13
        entries each, which is where lines and units diverge hardest.
      as_of: "2026-09-16"
      coverage:
        metric: order_items rows carrying a non-zero quantity, the measure a unit count sums
        populated: 4550326
        total: 4550334
    measured_impact: null
    unasked_question: >-
      Whether a free entry counts as an item bought. Twenty-one free entries and
      one paid ticket are both real, and putting them in one lifetime total
      makes an entrant look like a buyer.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/services/order_query.py
      - api/analytics/routes/customers.py
    probes:
      - grep_count:
          glob: api/analytics/routes/customers.py
          pattern: 'items_per_customer|lifetime_items|items_bought'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'items_per_customer|lifetime_items|items_bought'
          expected: 0
    premise:
      - claim: >-
          A bucketed distribution over a per-order line count is already
          implemented and served, with a bucket cap and a named tail for what
          the cap folded away, so this report reuses a convention that is
          written down instead of choosing new bucket behaviour.
        probe:
          grep_count:
            glob: api/analytics/services/order_query.py
            pattern: 'def item_count_distribution\('
            expected: 1

  - title: Frequently bought together, bounded to a window and a minimum pair support
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      Which products appear in the same order. DD ranks products, compares two
      of them and names a top product per churn tier, and nothing pairs them —
      no co-occurrence expression exists in the engine or on any route. Batch 16
      dropped this saying a self-join over 4.55M line rows needs a bound before
      it is unattended work, and half that objection is now answered: migration
      0015 built a covering index leading on order_id and carrying
      wc_product_id, product_name, total and quantity, which is exactly the
      index a self-join on order_id needs to stay index-only. The other half
      still stands and belongs in the spec rather than in the agent's judgement:
      a date window, a minimum support per pair and a cap on pairs returned.
      Moderate work with those three fixed, and unbounded without them. A
      warning that belongs here rather than in a retrospective: free-entry
      orders carry 73,378 line rows at 21.13 entries a line, so the top pairs
      will be free-entry products unless the report says whether they are in.
      No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Monthly — Products (1 of 8)
    hib_signal:
      value: >-
        4,549,662 order_items rows over 3,743 distinct wc_product_id with
        product_name set on every line, so both sides of a pair are populated.
        Category coverage is 51.5% and 99.9% of categorised products carry more
        than one category, which is why this report should pair PRODUCTS and not
        categories.
      as_of: "2026-09-15"
      coverage:
        metric: order_items rows carrying a product_name, the dimension both sides of a pair read
        populated: 4549662
        total: 4549662
    measured_impact: null
    unasked_question: >-
      Whether "bought together" means the same order or the same customer over
      time. For a competition store the second is the more useful question and
      it is a different and much larger query, and nobody has said which is
      wanted.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/products.py
      - platform/app/(dashboard)/analytics/products/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/products.py
          pattern: 'bought_together|frequently_bought|co_occurrence'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'bought_together|co_occurrence|market_basket'
          expected: 0
    premise:
      - claim: >-
          A covering index leading on order_id and carrying the product columns
          already exists on order_items, so the self-join this report needs has
          an index-only path rather than a sequential scan of 4.55M rows.
        probe:
          path_exists: api/analytics/migrations/versions/v0015_order_items_order_covering_index.py

  - title: Group orders and revenue by currency, and keep the count the engine already discards
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: fd5a404
    rationale: >-
      The weakest of this batch's nine and emitted with that said rather than
      discovered later. orders.currency is set on every row and no endpoint
      groups by it — but the engine is not silent about currency either: the
      revenue summary and the payment-method breakdown each carry a currency and
      a mixed_currency boolean, and ltv_distribution already runs a real
      GROUP BY over orders.currency and keeps only the list of codes, throwing
      the per-currency count away. So the work is genuinely small — that count
      kept, scoped to the window, and surfaced beside the other order groupings
      — and the likely finding is that this tenant is single-currency and the
      report has one row. That is worth knowing and is cheap to establish; it is
      not worth a page of its own. An approver who wants the finding without the
      feature should reject this and read currencies_present instead, and that
      is a reasonable outcome. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Rarely — Order groups (2 of 6)
    hib_signal:
      value: >-
        orders.currency is set on all 2,889,850 rows. The number of DISTINCT
        currency codes has never been counted — not by the evidence pack, not by
        the 16 September measurement — so the source document's own note stands
        that this report is buildable and may legitimately return a single row.
      as_of: "2026-09-15"
      coverage:
        metric: orders carrying a currency code; the number of distinct codes is unmeasured
        populated: 2889850
        total: 2889850
    measured_impact: null
    unasked_question: >-
      Whether HIB has ever taken an order in anything but GBP. One answer makes
      this report a one-row table and the other makes it the first place DD
      would have to decide whether to convert, and the question has never been
      put to anyone.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/orders.py
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'by-currency|currency_breakdown'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'currency_breakdown'
          expected: 0
    premise:
      - claim: >-
          The engine already groups the order table by its currency column in
          one statement and discards the per-currency count, so this report
          keeps a result that is computed today rather than introducing the
          grouping.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'GROUP BY o\.currency'
            expected: 1
```

## What I could not establish

**The sha of the source document.** This contract grants no shell and no git,
so `80677a2` is taken from batch 16's block for the same file rather than
re-derived. The file in this worktree carries all four correction entries and
the 16 September measurements that batch 16 described, so it is the same
document; what I cannot rule out is an amendment since that left the content I
read untouched. Nothing in the nine turns on it.

**Whether the nine rows are missing for a good reason.** I established that no
module implements them. `candidate_block_shape.py` says of itself that it
cannot tell whether a row marked missing is missing for a good reason, and
neither can I: *By currency* is the row where that doubt is loudest, and its
rationale carries it rather than hiding it.

**How many distinct currencies exist on this tenant.** The evidence pack never
counted them and the 16 September measurement did not either. The candidate
therefore asserts that `orders.currency` is populated and explicitly does not
assert that the report will return more than one row.

**What share of customers have two or more orders.** Candidates 4, 6 and 7 all
rest on repeat buying being common. The mean of 18.4 orders per customer says it
is, and a mean is not a share — `churn_engine.py` computes the repeat rate live
and no figure from it is recorded anywhere I can read. All three candidates
carry `coverage: null` for that reason rather than for want of arithmetic.

**Whether `Order value distribution` is actually shipped.** It was retired on
21 Sep by a probe matching `width_bucket` anywhere in the engine, and what put
`width_bucket` there is the lifetime-spend histogram at
`api/analytics/services/analytics_engine.py:3568`. No endpoint in this tree
returns a histogram of `orders.total`. I have not re-proposed the row — the
retirement is a decision I was not asked to reverse — but if somebody expected
an order-value histogram to exist because that row closed, it does not.

**Whether any of these nine is a report an agency would open.** Every one is
Monthly or Rarely, the two least-used bands in a document that calls its own
band column the most falsifiable thing in it. Three of the nine are forecasts,
which is the largest work in the classification. No agency was asked, DD has no
telemetry that would settle it, and one conversation with HIB's team could
plausibly kill four of these nine and promote a Weekly row nobody has written
down yet.

**Whether the shipped rows in the disposition table are shipped COMPLETELY.** I
established presence by reading the module and the route decorator, not
correctness and not reachability. `GET /orders/by-weekday` existing at
`api/analytics/routes/orders.py:426` is not that endpoint being right, rendered
or used.
