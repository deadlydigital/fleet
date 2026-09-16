# Candidates from the Metorik report classification — batch 16

Produced 2026-09-16. Serves `dd-feature-parity`.

This is the first producer batch read from
`research/metorik-report-classification-2026-09-15.md` rather than from
`specs/metorik-gap.md`. The classification carries the two columns this
pipeline needs and the gap list does not: a bucket per row, and a band in the
section heading `console/load_candidates.band_of` reads. Every candidate below
cites the heading of the row it covers, so every row loads with a band rather
than sorting last forever under `console/rank.py`'s `NO_BAND = 4`.

Ten candidates, which is the ceiling
`contracts/checks/candidate_block_shape.py --max-candidates 10` enforces. Thirty
bucket-A rows were considered. The disposition of all thirty is below, because a
silent cap reads as coverage.

## What was re-verified, and where the input I was given was wrong

`deadly-digital-platform` was read at `7a09b92`. The task handed me a table of
seven A rows said to have shipped, with an explicit instruction to take it from
the tree rather than from the table. Six of the seven confirm exactly:

| Row | What I found at HEAD |
|---|---|
| Net/gross revenue over time | `net_revenue` is computed in `api/analytics/services/analytics_engine.py` in four separate aggregates — the period stats, the revenue series, the revenue summary and the dashboard overview — as `revenue - refunded_amount`, both sums taken over identical revenue-status rows. Gross is untouched beside it. Shipped. |
| Revenue by billing/… /payment method | `payment_method_breakdown` in the same file, reached from `GET /revenue` in `api/analytics/routes/revenue.py`. Shipped. |
| Order groups → By payment method | Same endpoint. Shipped. |
| Coupon usage, amount discounted, sales generated | `coupon_breakdown` in `api/analytics/services/analytics_engine.py`, one `GROUP BY coupon_code` with a bounded per-code table and a tail. Shipped. The initial grep that returned nothing was indeed a false negative. |
| Top selling categories | `GET /products/categories` at `api/analytics/routes/products.py:138`, backed by `product_category_report`. Shipped — with the `‡` caveat below. |
| Order groups → By status | `GET /statuses` at `api/analytics/routes/orders.py:167`, derived from the data. Shipped. |

**The seventh is a partial and I am emitting it.** *Order sources by UTM
combination* is not covered by `GET /timeline-by-campaign`, and it is not covered
by `GET /sources` either, for a reason narrower than "campaign only":

* `/timeline-by-campaign` groups on `COALESCE(o.utm_campaign, '(direct)')` and
  the date. One dimension of three.
* `/sources` **does** carry all three columns — but behind
  `DISTINCT ON (o.customer_id)`, taking each customer's **first** order's triple
  and attributing all their later orders to it. That is first-order customer
  attribution, which the classification files as bucket **C** under *Customer
  sources by UTM combination*. The A row asks for orders grouped by **their own**
  triple.

The code knows the difference: the same query computes an `is_source_order` flag
that asks whether an order carried the same tags as the one it was attributed to.
Nothing groups on it. Candidate 8 is that grouping.

**Two shipped rows I checked that the table did not name.** *Orders over time*
and *Average order gross over time* are both in the revenue series
(`revenue_report` returns orders and `aov` per period), and *New customers over
time* is the `new` key of `customer_report`'s daily rows. *By billing/shipping
location* is shipped on all three live dimensions — `country_breakdown`,
`city_breakdown` and the postcode area/district cuts in
`api/analytics/services/geography.py`. All four are dispositioned as shipped
below.

## The rows I may not propose, stated so the next batch does not re-derive it

Twenty-eight of the 100 rows are marked N/A with the words *do not propose* in
the row itself, on four facts Eamonn stated on 2026-09-16: HIB does not refund,
ships nothing, charges no VAT on entries, and sells no recurring product. None of
the twenty-eight is a bucket-A row, so none was a candidate for this batch in any
case — but the mechanical check could not have stopped one. Its vocabulary is
`path_exists`, `path_absent` and `grep_count` over a source tree, and a probe
asserting "no refund reason column exists" holds at HEAD.

One column, not a row: **`orders.billing_state` is set on 0 of 2,890,319**,
measured 2026-09-16. *By billing/shipping location (country, state, city, ZIP)*
stays bucket A on country, city and postcode, and I have proposed no by-state
grouping and no by-shipping-location grouping. `api/analytics/services/geography.py`
already names `billing_state` as `connector_never_sends` in its own
`unavailable_dimensions()`, which is the same finding arrived at from the code.

Carts (7 rows) and devices (3 rows) are bucket B and so not candidates here, but
they are **real gaps and not inapplicable** — a cart is a funnel stage and a
device split is a browser fact, and this store has both.

## How thirty became ten

Band order, which is the order `console/rank.py` sorts in: Daily, then Weekly,
then Monthly, then Rarely. Of the seven Daily A rows, six have shipped, leaving
one. Of the fourteen Weekly A rows, five have shipped, leaving nine. One plus
nine is exactly ten, so **the ceiling is reached before the Monthly band begins**
and no Monthly or Rarely row is emitted. That is the rule applied, not a
judgement about the Monthly rows, four of which are small work.

Within the Weekly band I did not need a tie-break, because all nine open rows
fit. Six of the ten sit in one section heading (`Weekly — Orders`), and two pairs
overlap heavily — *Item count distribution* with *Average order item count*, and
*Orders by day of week* / *by hour of day* with *Orders heatmap*. They are
separate rows in the source document and are emitted separately; each rationale
names the row it overlaps so an approver can take one and defer the other rather
than discovering the overlap after two tasks have run.

**None of the ten needs a migration.** Every one reads columns that already exist
on `api/analytics/models.py`, and every suggested path is a file that at least one
contract for this repo makes writable and does not protect —
`deadly-digital-platform-api.yaml` for the four `api/analytics/` modules and
`dd-analytics-frontend.yaml` for the three dashboard pages. Three of the ten want
a new Next proxy directory under `platform/app/api/analytics/orders/`; that path
is covered by a `**` glob in the frontend contract, so a new sibling route
directory is inside the writable set and this stays unattended work.

**A is a statement about data, not about difficulty.** The three forecast rows
are bucket A and are not small; they are dropped for the ceiling and not because
they are cheap or dear. Each rationale below states the size I judged from the
tree.

## Disposition of all thirty bucket-A rows

| # | Row | Section heading | Disposition |
|---|---|---|---|
| 1 | Net/gross revenue over time | `Daily — Revenue (1 of 3)` | already shipped at HEAD — `net_revenue` beside gross in four aggregates in `api/analytics/services/analytics_engine.py` |
| 2 | Orders over time | `Daily — Orders (3 of 10)` | already shipped at HEAD — orders per period in `revenue_report`, rendered on the overview |
| 3 | New vs returning customer orders | `Daily — Orders (3 of 10)` | **emitted** (candidate 1) |
| 4 | Average order gross over time | `Daily — Orders (3 of 10)` | already shipped at HEAD — `aov` per period in `revenue_report`, both sides revenue-status since FEAT-032 |
| 5 | By status | `Daily — Order groups (1 of 6)` | already shipped at HEAD — `GET /statuses`, `api/analytics/routes/orders.py:167` |
| 6 | New customers over time | `Daily — Customers (1 of 3)` | already shipped at HEAD — `customer_report` daily `new`, derived from orders not `customers.first_order_at` |
| 7 | Top selling products | `Daily — Products (1 of 8)` | already shipped at HEAD — `GET /products`, `product_report` |
| 8 | Revenue by billing/shipping location or payment method | `Weekly — Revenue (1 of 3)` | already shipped at HEAD — `payment_method_breakdown` in the `/revenue` payload; billing via the geography routes |
| 9 | Order value distribution | `Weekly — Orders (7 of 10)` | **emitted** (candidate 2) |
| 10 | Item count distribution | `Weekly — Orders (7 of 10)` | **emitted** (candidate 3) |
| 11 | Average order item count | `Weekly — Orders (7 of 10)` | **emitted** (candidate 4) |
| 12 | Orders by day of week | `Weekly — Orders (7 of 10)` | **emitted** (candidate 5) |
| 13 | Orders by hour of day | `Weekly — Orders (7 of 10)` | **emitted** (candidate 6) |
| 14 | Orders heatmap (day × hour) | `Weekly — Orders (7 of 10)` | **emitted** (candidate 7) |
| 15 | By payment method | `Weekly — Order groups (3 of 6)` | already shipped at HEAD — same `/revenue` breakdown as row 8 |
| 16 | By billing/shipping location (country, state, city, ZIP) | `Weekly — Order groups (3 of 6)` | already shipped at HEAD on all three live dimensions — `country_breakdown`, `city_breakdown`, postcode area and district in `api/analytics/services/geography.py`. State is empty and shipping is N/A; neither was proposed |
| 17 | Order sources by UTM combination | `Weekly — Acquisition / sources (6 of 6)` | **emitted** (candidate 8) — the shipped endpoint is campaign-only, and `/sources` groups by customer attribution |
| 18 | Coupon usage, amount discounted and sales generated | `Weekly — Coupons (1 of 1)` | already shipped at HEAD — `coupon_breakdown` |
| 19 | Top selling categories | `Weekly — Products (4 of 8)` | already shipped at HEAD — `GET /products/categories`, `product_category_report` |
| 20 | Product comparison | `Weekly — Comparison (2 of 2)` | **emitted** (candidate 9) |
| 21 | Category comparison | `Weekly — Comparison (2 of 2)` | **emitted** (candidate 10) |
| 22 | Sales forecast (12 months) | `Monthly — Forecasts (3 of 3)` | dropped for the ceiling — Monthly band, and the largest of the thirty: a fit, a horizon and a confidence band are a service module, not a `GROUP BY` |
| 23 | Order volume forecast (3/6/12 months) | `Monthly — Forecasts (3 of 3)` | dropped for the ceiling |
| 24 | New customers forecast | `Monthly — Forecasts (3 of 3)` | dropped for the ceiling |
| 25 | Orders made over customer lifetime | `Monthly — Retention (4 of 4)` | dropped for the ceiling — the best Monthly row for the next batch: one bucketed count over `orders.customer_id`, no new column |
| 26 | New vs returning customer KPIs | `Monthly — Retention (4 of 4)` | dropped for the ceiling — partially served already by `customer_report`'s window totals |
| 27 | Time between repeat orders | `Monthly — Retention (4 of 4)` | dropped for the ceiling — a window function over `created_at` partitioned by `customer_id`; small |
| 28 | Items bought over customer lifetime | `Monthly — Retention (4 of 4)` | dropped for the ceiling |
| 29 | Frequently bought together | `Monthly — Products (1 of 8)` | dropped for the ceiling — open at HEAD, and a self-join over 4.55M line rows needs a bound before it is unattended work |
| 30 | By currency | `Rarely — Order groups (2 of 6)` | dropped for the ceiling — Rarely is the last band, and the pack never counted distinct currencies, so this may legitimately return one row |

Eleven shipped, ten emitted, nine dropped for the ceiling.

## The candidates

```fleet-candidates
source:
  document: research/metorik-report-classification-2026-09-15.md
  sha: 80677a2
ordering: unranked
unasked_question: >-
  Nobody has asked HIB's team which of these reports they would actually open.
  Every band in the source document is a judgement about a generic WooCommerce
  agency, stated by that document to be the most falsifiable column in it, and
  every hib_signal below is a population figure about what HIB HAS rather than
  evidence about what its team WANTS. Six of these ten rows are cuts of the same
  orders table, and one conversation would probably kill three of them and move
  a forecast to the top.
objectives_considered: >-
  Both dd-feature-parity and dd-trustworthy were weighed, row by row, and all ten
  landed on dd-feature-parity. That is the answer batch 9 gave without arguing for
  it, so here is the argument. dd-trustworthy covers correctness of figures DD
  already prints; none of these ten changes an existing number. Each adds a cut
  that does not exist at all — a distribution, a time-of-day grouping, a
  per-order UTM grouping, a comparison — so there is no shipped figure for them to
  contradict. The one row where the two objectives genuinely competed is
  candidate 1: DD prints new and returning CUSTOMER counts today and they are
  correct, so adding the order and revenue split is parity work and not a repair,
  and I have labelled it accordingly. dd-first-revenue and cost-discipline were
  considered and rejected as the wrong shape for analytics report rows.
candidates:
  - title: Split orders and revenue by new versus returning customer, not just customer counts
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      DD answers "how many new and returning customers" and never "how many
      ORDERS and how much REVENUE came from each". customer_report returns
      new_customers and returning_customers as distinct-customer counts, and
      dashboard_overview and revenue_report carry the same two figures per
      period. The Metorik row is the order-level split, which is what tells an
      agency whether growth came from acquisition or from repeat buying. Small
      work: the acquiring-order CTE that dates each customer's first order is
      already built and already joined in the query that scans the order rows,
      so this is two more FILTER aggregates in an existing SELECT plus two stat
      cards. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Daily — Orders (3 of 10)
    hib_signal:
      value: >-
        orders.total is NOT NULL on every order and non-zero on 2,823,569 of
        2,890,319, so the revenue half of the split has a measure on 97.7% of
        rows; 157,311 distinct customer_id across the order table.
      as_of: 2026-09-16
      coverage:
        metric: orders carrying a non-zero total, the measure the new/returning split would sum
        populated: 2823569
        total: 2890319
    measured_impact: null
    unasked_question: >-
      Whether an agency reads the new/returning split as orders, as revenue, or
      as both — nobody has asked, and DD has no telemetry that would say.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/customers.py
      - platform/app/(dashboard)/analytics/customers/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'new_orders|returning_orders'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/customers.py
          pattern: 'new_vs_returning'
          expected: 0
    premise:
      - claim: >-
          The engine already derives each customer's acquiring order and joins it
          to the window's order rows in the same statement, so the new-versus-
          returning classification exists per ORDER today and only the aggregate
          over it is missing.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: '_acquiring_order_ctes'
            expected: 5

  - title: Order value distribution, a histogram of order totals over a window
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      Every revenue figure DD prints is a sum or a mean. There is no shape: an
      AOV of GBP 52 is the same number whether the store sells one ticket at a
      time or splits between GBP 5 and GBP 200 baskets, and those are different
      businesses. No route under api/analytics/routes/ mentions a distribution
      and the engine has no bucketing expression at all. Small work: one banded
      GROUP BY over orders.total with a chosen band width, plus a bar chart on
      the orders page. The judgement in it is the band width, not the SQL. No
      new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Orders (7 of 10)
    hib_signal:
      value: >-
        orders.total is NOT NULL on all 2,890,319 orders and non-zero on
        2,823,569 of them. The 66,750 zero-total orders are not explained by
        status — cancelled and pending together are 1,991 — so a histogram will
        show a zero bucket that is itself a finding.
      as_of: 2026-09-16
      coverage:
        metric: orders carrying a non-zero total, the column the histogram buckets
        populated: 2823569
        total: 2890319
    measured_impact: null
    unasked_question: >-
      Whether the band width should be fixed, quantile-based or chosen by the
      reader — the third is the segmentation engine's problem and the first two
      are not, and nobody has said which HIB wants.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/orders.py
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'distribution'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'WIDTH_BUCKET|width_bucket'
          expected: 0
    premise:
      - claim: >-
          A window aggregate over orders.total with the revenue-status filter
          already exists in the engine, so the histogram reuses a settled
          population rather than defining a fourth one.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def revenue_summary'
            expected: 1

  - title: Item count distribution, how many line items an order carries
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      DD counts line items for a single order in the orders list and nowhere
      aggregates that count. The report is the distribution across a window —
      how many orders are one line, two lines, five — which for a ticket store
      is the basket-size question. Small work: the per-order line count
      subquery already exists in order_query.py and needs lifting into a GROUP
      BY over it. Overlaps candidate 4, which is the mean of this same
      distribution; if only one is taken, take this one, because the mean is
      derivable from the buckets and the buckets are not derivable from the
      mean. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Orders (7 of 10)
    hib_signal:
      value: >-
        order_items.quantity is non-zero on 4,550,326 of 4,550,334 rows, so a
        true unit count is available and not only a line count; order_items.sku
        and order_items.price are NULL on every row and cannot be used.
      as_of: 2026-09-16
      coverage:
        metric: order_items rows carrying a non-zero quantity
        populated: 4550326
        total: 4550334
    measured_impact: null
    unasked_question: >-
      Whether "item count" means lines or units. The two differ wherever a
      quantity exceeds one, and nobody has said which number HIB reads.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/services/order_query.py
      - api/analytics/routes/orders.py
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'item_count|items_per_order'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/*.tsx
          pattern: '[Dd]istribution'
          expected: 0
    premise:
      - claim: >-
          DD already counts an order's line items against the order row when it
          lists and exports orders, so the per-order count this distribution
          buckets is an expression that exists rather than one to invent.
        probe:
          grep_count:
            glob: api/analytics/services/order_query.py
            pattern: 'order_items'
            expected: 2

  - title: Average order item count over time
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      The mean basket size per period, beside the AOV the revenue series already
      carries. Nothing in the engine computes it — there is no avg_items or
      items_per_order anywhere in it. Small work, and the smallest of the ten: a
      second ratio in the existing revenue_report series, with the same
      revenue-status filter on both sides that FEAT-032 settled for AOV, so it
      cannot import conflict 2.1. This is the mean of candidate 3's
      distribution; an approver taking both should expect them to be one task.
      No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Orders (7 of 10)
    hib_signal:
      value: >-
        4,550,334 order_items rows against 2,890,319 orders, with quantity
        non-zero on all but 8 lines, so both a line-count mean and a unit-count
        mean are computable.
      as_of: 2026-09-16
      coverage:
        metric: order_items rows carrying a non-zero quantity
        populated: 4550326
        total: 4550334
    measured_impact: null
    unasked_question: >-
      Whether this belongs on the revenue page beside AOV or on the orders page
      beside the order counts, which decides whose date range it follows.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/orders.py
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'avg_items|average_items|items_per_order'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'item_count|items_per_order'
          expected: 0
    premise:
      - claim: >-
          A line-item model with its own quantity column exists on the analytics
          schema, so the mean is an aggregate over stored rows and not a figure
          reconstructed from the order total.
        probe:
          grep_count:
            glob: api/analytics/models.py
            pattern: 'quantity = Column'
            expected: 1

  - title: Orders by day of week
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      orders.created_at is DateTime(timezone=True) and DD buckets it by hour,
      day, week and month — never by weekday. No route mentions EXTRACT(DOW or
      day_of_week; the one DOW expression in the repository is in churn_engine,
      grouping customer acquisition days for a churn signal, which is a
      different report on a different column. Small work: a seven-row GROUP BY
      plus a bar chart. The one real decision is the timezone — the granularity
      helper already buckets in the tenant's zone and this must do the same, or
      a UK store's Sunday leaks into Monday. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Orders (7 of 10)
    hib_signal:
      value: >-
        2,889,850 orders spanning 1,283 days, 2023-03-12 to 2026-09-15, on a
        timezone-aware column that carries the time and not only the date. Every
        weekday bucket has roughly 183 weeks of orders behind it.
      as_of: 2026-09-15
      coverage: null
    measured_impact: null
    unasked_question: >-
      Whether an agency wants weekday by order count, by revenue, or both — and
      whether it wants the average per weekday or the total, which are different
      reports over an unequal number of weekdays in a window.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/orders.py
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'EXTRACT\(DOW|ISODOW|day_of_week'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/*.tsx
          pattern: 'dayOfWeek|day of week'
          expected: 0
    premise:
      - claim: >-
          Date bucketing for the analytics reports is already centralised in one
          granularity helper with a tenant-timezone rule, so a weekday cut has an
          existing place to live and an existing answer to the timezone question.
        probe:
          grep_count:
            glob: api/analytics/services/date_range.py
            pattern: 'GRANULARITIES'
            expected: 1

  - title: Orders by hour of day, across a window rather than within one day
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      DD has hour granularity and it is not this report. revenue_report_hourly
      returns twenty-four points for ONE day, and the granularity helper caps
      hour buckets at a single-day window on purpose. The Metorik row is the
      twenty-four-bucket profile across a whole window — when in the day this
      store sells — which no endpoint returns. Small work: an hour-of-day
      extract and a GROUP BY, alongside the day-of-week cut in candidate 5 and
      sharing its timezone decision. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Orders (7 of 10)
    hib_signal:
      value: >-
        2,889,850 orders over 1,283 days on a timezone-aware created_at, so each
        of the twenty-four buckets has a large population; DD's existing hour
        support is capped at a one-day window by MAX_DAYS_FOR_HOUR.
      as_of: 2026-09-15
      coverage: null
    measured_impact: null
    unasked_question: >-
      Whether the hour profile is wanted for the store's own trading hours or for
      ad scheduling, which decides whether it needs splitting by source.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/orders.py
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'hour_of_day|hourOfDay'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'EXTRACT\(HOUR'
          expected: 0
    premise:
      - claim: >-
          Hour-level bucketing already exists in the shared date helper and is
          deliberately bounded to a single day, so this report extends a rule that
          is written down rather than introducing hour handling from nothing.
        probe:
          grep_count:
            glob: api/analytics/services/date_range.py
            pattern: 'MAX_DAYS_FOR_HOUR'
            expected: 2

  - title: Orders heatmap, day of week by hour of day
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      The 168-cell grid, which is the report an agency actually opens rather
      than the two one-dimensional cuts — a Friday-evening peak is invisible in
      both a weekday bar chart and an hour bar chart, and obvious here. No route
      mentions a heatmap and the orders page has none. This is the largest of
      the three time-shape rows and is deliberately listed after candidates 5
      and 6: the SQL is their two extracts in one GROUP BY, and if either lands
      first this becomes almost free. The real cost is the grid component and a
      colour scale. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Orders (7 of 10)
    hib_signal:
      value: >-
        2,889,850 orders over 1,283 days means roughly 17,000 orders per cell of
        a 168-cell grid, so no cell is sparse enough to be noise on this tenant.
      as_of: 2026-09-15
      coverage: null
    measured_impact: null
    unasked_question: >-
      Whether an empty cell should render as zero or as no-data. The cohort
      matrix already distinguishes them and nobody has said whether a heatmap
      over a short window should follow the same rule.
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/orders.py
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'heatmap'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/*.tsx
          pattern: '[Hh]eatmap'
          expected: 0
    premise:
      - claim: >-
          DD already renders a two-dimensional matrix of periods in the customer
          cohort view, with a settled convention for a cell that is absent rather
          than zero, so the grid and its hardest rendering question exist to reuse.
        probe:
          grep_count:
            glob: platform/app/(dashboard)/analytics/customers/cohorts/page.tsx
            pattern: 'heatmap'
            expected: 1

  - title: Group orders by their own UTM source, medium and campaign triple
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      Both shipped UTM views answer a different question. /timeline-by-campaign
      groups on utm_campaign alone. /sources carries all three columns but
      behind first-order customer attribution, so an order placed under one
      campaign is credited to whichever campaign first acquired that customer —
      which is the classification's bucket-C customer report, not this
      bucket-A order report. The distinction is already in the code: the same
      query computes a flag for whether an order's own tags match the ones it
      was attributed to, and nothing groups on it. Moderate work, because the
      new endpoint must sit beside the existing one without either page implying
      the other's numbers. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Acquisition / sources (6 of 6)
    hib_signal:
      value: >-
        utm_source is set on 2,054,935 orders, utm_medium on 1,460,764 and
        utm_campaign on 211,957 of 2,889,850 — so the three-way grouping is real
        but a large (none) bucket is guaranteed and must be labelled rather than
        dropped. The campaign column carries an index.
      as_of: 2026-09-15
      coverage:
        metric: orders carrying a utm_source, the widest of the three dimensions
        populated: 2054935
        total: 2889850
    measured_impact: null
    unasked_question: >-
      Whether HIB reads paid performance per order or per acquired customer. If
      it is the latter then the shipped attribution view is already the right
      report and this one would sit unused beside it.
    suggested_paths:
      - api/analytics/routes/sources.py
      - api/analytics/services/acquisition.py
      - platform/app/(dashboard)/analytics/sources/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/sources.py
          pattern: 'GROUP BY\s+o\.utm_source'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/sources.py
          pattern: 'utm_combination|timeline-by-utm'
          expected: 0
    premise:
      - claim: >-
          The sources module already reads each order's own three UTM columns in
          the same statement as the attributed ones, comparing the two per order,
          so the per-order triple is present and only the grouping is attributed.
        probe:
          grep_count:
            glob: api/analytics/routes/sources.py
            pattern: 'is_source_order'
            expected: 3

  - title: Compare two products across two date windows
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      DD ranks products and never compares two of them. The products route has
      no compare endpoint and the products page has no comparison control — the
      only comparison wording anywhere in that part of the dashboard is on the
      separate acquiring-products page, about something else. Moderate work, and
      most of it is the UI: two product pickers, two date pickers and a
      side-by-side, over a rollup that already exists. The measure must be
      order_items.total, because sku and price are NULL on every one of the 4.55M
      line rows. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Comparison (2 of 2)
    hib_signal:
      value: >-
        order_items.total is non-zero on 4,447,939 of 4,550,334 lines and
        product_name is set on all of them across 3,743 distinct wc_product_id,
        so both the dimension and the measure are populated.
      as_of: 2026-09-16
      coverage:
        metric: order_items rows carrying a non-zero total, the measure a comparison ranks on
        populated: 4447939
        total: 4550334
    measured_impact: null
    unasked_question: >-
      Whether "compare" means two products in one window or one product across
      two windows. Metorik's row implies both and they are different screens.
    suggested_paths:
      - api/analytics/routes/products.py
      - api/analytics/services/analytics_engine.py
      - platform/app/(dashboard)/analytics/products/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/products.py
          pattern: 'compare|comparison'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/products/*.tsx
          pattern: '[Cc]ompar'
          expected: 0
    premise:
      - claim: >-
          A per-product rollup over the line items, filtered by date window, is
          already implemented and serving the top-products ranking, so a
          comparison calls it twice rather than defining a second measure.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def product_report'
            expected: 1

  - title: Compare two product categories across two date windows
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 7a09b92
    rationale: >-
      The same screen as candidate 9 through the category rollup that shipped
      with GET /products/categories, and it carries a risk that candidate does
      not, which is stated here rather than discovered later. The classification
      marks this row with a double dagger because product_categories could not be
      read at all — the deadly_digital reader has no SELECT on it — so nobody has
      established that the table holds a single row. The shipped categories
      endpoint is the cheapest possible test of that: if it returns an empty
      rollup on tenant data, this candidate should be rejected rather than built,
      and the finding is worth more than the report. Small work if the categories
      hold. No new column, no migration.
    evidence:
      - document: research/metorik-report-classification-2026-09-15.md
        sha: 80677a2
        section: Weekly — Comparison (2 of 2)
    hib_signal:
      value: >-
        No population figure exists for this row and none can be taken with the
        credentials the fleet holds. analytics_2.products, product_categories and
        customers all return permission denied for the deadly_digital reader, so
        the double dagger in the source document stands and means what it says.
      as_of: 2026-09-16
      coverage: null
    measured_impact: null
    unasked_question: >-
      Whether HIB's entries are categorised at all in WooCommerce. If every
      product sits in one category this report has one column and is worthless,
      and that is a question for the store rather than for the database.
    suggested_paths:
      - api/analytics/routes/products.py
      - api/analytics/services/analytics_engine.py
      - platform/app/(dashboard)/analytics/products/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/products.py
          pattern: 'compare|comparison'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'category_comparison|compare_categories'
          expected: 0
    premise:
      - claim: >-
          A category rollup that joins the line items through the per-product
          category table is already implemented and already served, so this
          comparison reuses a join that is written and does not invent one.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: 'def product_category_report'
            expected: 1
```

## What I could not establish

**Whether the two double-dagger rows rest on anything.** `analytics_2.products`,
`analytics_2.product_categories` and `analytics_2.customers` return permission
denied for the `deadly_digital` reader, measured 2026-09-16, and this contract
grants no shell and no credential, so I could not retry. *Top selling categories*
has shipped as `GET /products/categories` and *Category comparison* is candidate
10, and **both rest on a table nobody has read**. If `product_categories` is
empty, the shipped endpoint is already returning nothing and candidate 10 should
be rejected rather than built. I have not asserted a population for it, and its
`hib_signal.coverage` is explicitly null for that reason rather than for want of
arithmetic.

**Whether any of these reports is what an agency would open.** The band on every
row is the source document's judgement, which that document calls the most
falsifiable column in it. No agency was asked, DD has no telemetry that would
settle it, and the ordering of this batch — one Daily row then nine Weekly ones —
is therefore an ordering over an unmeasured column. Six of the ten are cuts of
the same orders table and one conversation with HIB might well collapse them.

**Whether the shipped rows are shipped COMPLETELY.** I established presence, not
correctness or completeness: `payment_method_breakdown` existing in the revenue
payload is not the breakdown being right, reachable or rendered, and
`candidate_block_shape.py` says so about itself in as many words. Eleven of the
thirty rows are dispositioned as shipped on that standard, and a reader who wants
more than presence has to open the page.

**Why 66,750 orders carry a total of zero.** `orders.total` is NOT NULL on all
2,890,319 and non-zero on 2,823,569. Status accounts for at most 1,991 of the
difference. Candidate 2's histogram would put those orders in a visible zero
bucket, which is a reason to build it and not a reason to believe I know what
they are. It is a data question, I had no way to ask it, and no row above turns
on the answer.

**Whether `orders.billing_state` is empty because HIB does not collect a region,
because WooCommerce does not send one, or because the connector does not map it.**
The column is set on 0 of 2,890,319 and `api/analytics/services/geography.py`
independently records it as `connector_never_sends`. Those agree on the symptom
and not on the cause, and unlike shipping and tax there is no stated business
fact here. I proposed no by-state grouping either way.

**Whether the nine rows dropped for the ceiling are still open next week.** They
were verified open at `7a09b92` today and nothing re-runs their probes, because
they are not in the block. Rows 25 and 27 — *Orders made over customer lifetime*
and *Time between repeat orders* — are the two I would put in batch 17 first, and
whoever takes them should re-probe rather than trust this paragraph.
