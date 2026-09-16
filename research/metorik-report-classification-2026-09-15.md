# Metorik's 100 published reports, classified against what DD holds

Produced 2026-09-15. Serves `dd-feature-parity`. It classifies every row of
`research/metorik-report-catalogue-2026-09-15.md` into one of three buckets and
gives each an agency-use band, so that the catalogue can be read next to the
data DD actually has.

It does not rank, prioritise, recommend or estimate effort, and it writes no
candidates. Bucket and band are all it claims.

## What this was built from

| Input | What it settled |
|---|---|
| `api/analytics/models.py` | which tables and columns exist. `EXPECTED_TABLES` is derived from `ALL_MODELS`: customers, orders, order_items, products, product_categories, customer_segments, churn_scores, interventions, daily_metrics, sync_log, churn_snapshots, metrics_dirty_dates, reconciliation_manifests. Thirteen, and nothing else. |
| `EVIDENCE.md` in this worktree | five readings taken by the runner at 2026-09-15 19:52 UTC as the `deadly_digital` reader, over `analytics_2.orders` and `analytics_2.order_items` only. I could not run anything else. |
| `research/metorik-report-catalogue-2026-09-15.md` | the 100 rows, in their own 17 groups and order, which this document preserves. |
| `https://metorik.com/reports`, fetched 2026-09-15 | the relayed catalogue's source, checked as far as a fetch can check it. See *The live page, checked*. |
| `specs/metorik-gap.md` | the empty-column rule and the sense of the band column, both reused here unchanged. |

The readings, quoted once so the rows below can cite figures rather than repeat
the query. All are `analytics_2`, 2,889,850 orders, 4,549,662 order item rows:

* Populated: `currency` 2,889,850; `payment_method` 2,826,259; `billing_country`
  2,884,311; `billing_city` 2,884,311; `billing_postcode` 2,884,111;
  `utm_source` 2,054,935; `utm_medium` 1,460,764; `utm_campaign` 211,957;
  `coupon_code` 152,698; `discount_total` non-zero 152,685;
  `order_items.product_name` 4,549,662 over 3,743 distinct `wc_product_id`.
* Empty or as good as: `shipping_total` non-zero **0**; `tax_total` non-zero
  **0**; `shipping_country` **0**; `order_items.sku` **0**; `order_items.price`
  **0**; `refund_total` non-zero **4** of 2,889,850.
* Status vocabulary: completed 2,887,414, cancelled 1,971, processing 241,
  on-hold 203, pending 20, refunded 1.
* Span 2023-03-12 to 2026-09-15 — 1,283 days — over 157,311 distinct
  `customer_id`.

## The three buckets, defined before anything was classified

**A — DD already holds the data.** Every field the report needs is a column on
a table `api/analytics/models.py` defines, and the evidence pack shows that
column populated. The report is a fixed aggregation over those columns: a known
`GROUP BY` on a named column, a histogram, a window function, a join between
two tables DD has.

**B — the data is not in DD.** Either the report needs an entity `models.py`
has no model for, or it needs a column `models.py` defines and the pack shows
empty. Every B row below is tagged `no model` or `empty column` so the two are
never confused, because they are different repairs. The empty-column case is
filed under B and not under a fourth bucket because bucket A excludes it by
rule and bucket C is defined over *data DD holds* — an empty column is not
data DD holds, so B is the only bucket left. `specs/metorik-gap.md` set the
underlying rule: a report over an empty column is not a feature.

**C — needs the segmentation engine.** The data is held and populated, but the
grouping is one `customer_segments` cannot express. That table stores exactly
one `segment_name` per customer plus an RFM triple, so the engine question
bites in two shapes: the grouping dimension is chosen by the user rather than
fixed, or the unit of the report is a customer or a cohort of customers grouped
by an attribute derived from their orders — `customers` in `models.py` carries
`order_count`, `total_spent`, `aov`, `first_order_at`, `last_order_at` and
nothing about where a customer is, what they first bought, or where they came
from.

Three tie-break rules, also written first:

1. **A is a statement about data, not about difficulty.** A forecast is
   arithmetic over `orders.created_at` and `orders.total`; it needs no table
   DD lacks and no grouping `customer_segments` blocks, so it is A. That says
   the data is not the obstacle. It does not say the report is cheap, and this
   document does not estimate effort.
2. **A report spanning two buckets goes in the one that blocks it.** Gross
   revenue is A-shaped and net revenue is not, so *Net/gross revenue over time*
   is B: the half that cannot be built decides.
3. **A report offering alternative dimensions is A if any named dimension is
   populated**, with the empty ones named in the row. *Revenue by
   billing/shipping location or payment method* is A on billing and on payment
   method; its shipping half is dead (`shipping_country` set on 0 rows) and the
   row says so.

## The band, and why these four words

`Daily`, `Weekly`, `Monthly`, `Rarely`: how often an agency running WooCommerce
stores for clients would open the report. The reasoning, once, rather than per
row:

* **Daily** is what an agency looks at before it does anything else — today's
  money, today's orders, whether anything is stuck. Eight rows.
* **Weekly** is the client-facing rhythm: what sold, where orders came from,
  which coupons ran, what is going wrong that is not on fire. Thirty-five rows.
* **Monthly** is the retrospective — cohorts, retention, forecasts, costs.
  Twenty-five rows.
* **Rarely** is a report with a real use that comes up a few times a year, or
  one that depends on the store selling something this store does not. Thirty-
  two rows, eighteen of which are the subscriptions block.

This is a judgement and nothing else. No agency was asked and DD has no
telemetry that would answer it; it is the most falsifiable column here and the
cheapest to correct.

**The band word leads every group heading below**, because
`console/load_candidates.py` reads a candidate's band from the heading of the
evidence section it cites. Two details of that reader shaped the headings.
`BANDS` is exactly the four words above, and a heading whose lead is any other
single alphabetic word followed by a dash *raises* rather than loading as
band-less — so `specs/metorik-gap.md`'s fifth status, `Never`, is unusable as a
heading here, and the subscriptions block is banded `Rarely` instead. And where
one catalogue group splits across bands, it appears below as more than one
heading, marked `(n of m)`, with the catalogue's order kept inside each — one
heading cannot carry two bands, and `console/rank.py` would sort the difference
silently.

There is no band column in the tables. The heading is the band, so a column
repeating it could only ever disagree with it.

## Summary

| Bucket | Rows | Share |
|---|---|---|
| **A** — DD holds the data | 29 | 29% |
| **B** — the data is not in DD | 59 | 59% |
| **C** — needs the segmentation engine | 12 | 12% |

Of the 59 in B, **54 are `no model`** and 5 are `empty column` — the five being
*Net/gross revenue over time*, three of the six refund reports, and *Customer
groups by shipping location*. Twenty-five of the 59 are the subscriptions and
carts blocks — see *Subscriptions and carts*.

By band: 8 Daily, 35 Weekly, 25 Monthly, 32 Rarely.

Two facts that cut across the table. **Refunds are absent** — `refund_total` is
non-zero on 4 orders of 2,889,850 and no refund entity exists, which takes the
whole six-row Refunds group and the net half of the headline revenue report.
**Costs are absent** — no table in `models.py` has a cost column, which takes
the five-row Costs & profit group and three of the ten cohort reports.

## The classification

### Daily — Revenue (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Net/gross revenue over time | **B** `empty column` | Spans A and B; B blocks it. Gross is `orders.total` over `orders.created_at`, both present. Net needs `orders.refund_total`, non-zero on 4 of 2,889,850. No refund entity exists to fix that from. |

### Weekly — Revenue (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Revenue by billing/shipping location or payment method | **A** † | `orders.billing_country` 2,884,311, `orders.billing_city` 2,884,311, `orders.payment_method` 2,826,259. The shipping dimension is dead: `shipping_country` set on 0. Measure is `orders.total`, which the pack did not measure. |

### Rarely — Revenue (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Revenue by tax code, label or ID | **B** `no model` | `models.py` has one tax field, `orders.tax_total`, and no code, label or ID anywhere. It is non-zero on 0 of 2,889,850, so even the amount is absent. |

### Daily — Costs & profit (1 of 5)

| Report | Bucket | Why |
|---|---|---|
| Profit & costs over time | **B** `no model` | No cost column on any of the 13 tables in `ALL_MODELS`. `products` is `id, wc_product_id, name, sku, price, category, status` — a price, never a cost. |

### Weekly — Costs & profit (1 of 5)

| Report | Bucket | Why |
|---|---|---|
| Advertising costs by platform | **B** `no model` | No ad-spend entity in the analytics models. |

### Monthly — Costs & profit (3 of 5)

| Report | Bucket | Why |
|---|---|---|
| Operational costs by type | **B** `no model` | No cost entity of any kind. |
| Transaction costs by payment method | **B** `no model` | `orders.payment_method` is populated on 2,826,259, but there is no fee column to group. The dimension exists and the measure does not. |
| Shipping costs by shipping method | **B** `no model` | No shipping-method column on `orders`; `shipping_total` is non-zero on 0 of 2,889,850. Both halves missing. |

### Monthly — Forecasts (3 of 3)

| Report | Bucket | Why |
|---|---|---|
| Sales forecast (12 months) | **A** † | `orders.created_at` and `orders.total` over 1,283 days, 2023-03-12 to 2026-09-15. Enough history to fit on; `total` not measured by the pack. |
| Order volume forecast (3/6/12 months) | **A** | `orders.created_at`, 2,889,850 rows across the same span. A count, so nothing unmeasured. |
| New customers forecast | **A** | First order per `orders.customer_id` — 157,311 distinct — over `created_at`. `customers.first_order_at` and `daily_metrics.new_customers` would serve too but are not needed, so this row does not rest on an unverified table. |

### Daily — Orders (3 of 10)

| Report | Bucket | Why |
|---|---|---|
| Orders over time | **A** | `orders.created_at`, 2,889,850 rows, 2023-03-12 to 2026-09-15. |
| New vs returning customer orders | **A** | `orders.customer_id` populated across 157,311 distinct customers; first-order date derivable from `orders` alone. |
| Average order gross over time | **A** † | `orders.total` over `orders.created_at`. `daily_metrics.aov` holds it precomputed; `total` was not measured. |

### Weekly — Orders (7 of 10)

| Report | Bucket | Why |
|---|---|---|
| Item count distribution | **A** † | `order_items` 4,549,662 rows keyed by `order_id`. Lines per order is measured; a true item count needs `order_items.quantity`, which the pack did not measure. |
| Order value distribution | **A** † | `orders.total`, not measured by the pack. |
| Orders by day of week | **A** | `orders.created_at` is `DateTime(timezone=True)`. |
| Orders by hour of day | **A** | As above — the column carries the time, not just the date. |
| Orders heatmap (day × hour) | **A** | Same column, two-dimensional bucketing. |
| Average order item count | **A** † | 4,549,662 item rows over 2,889,850 orders. `quantity` unmeasured. |
| Order created → completed time | **B** `no model` | `orders` has `created_at`, `updated_at`, `synced_at` and a single current `status`. There is no status-transition history, and `updated_at` is the last write of any kind, not the moment of completion. |

### Daily — Order groups (1 of 6)

| Report | Bucket | Why |
|---|---|---|
| By status | **A** | `orders.status`, six values measured: completed 2,887,414, cancelled 1,971, processing 241, on-hold 203, pending 20, refunded 1. |

### Weekly — Order groups (3 of 6)

| Report | Bucket | Why |
|---|---|---|
| By payment method | **A** | `orders.payment_method` set on 2,826,259 of 2,889,850. |
| By shipping method | **B** `no model` | No shipping-method column exists on `orders`. |
| By billing/shipping location (country, state, city, ZIP) | **A** † | Billing is populated — country 2,884,311, city 2,884,311, postcode 2,884,111. `billing_state` exists in `models.py` and was not measured. The shipping columns are the empty half: `shipping_country` 0. |

### Rarely — Order groups (2 of 6)

| Report | Bucket | Why |
|---|---|---|
| By currency | **A** | `orders.currency` set on all 2,889,850. The pack did not count distinct values, so the report is buildable and may well return one row. |
| By custom field | **B** `no model` | `orders` is named columns by design — the comment above the billing block says so, because `gdpr.py` must be able to enumerate them. There is no JSONB bag and no custom-field table. |

### Weekly — Refunds (3 of 6)

| Report | Bucket | Why |
|---|---|---|
| Refunds over time | **B** `empty column` | `orders.refund_total` non-zero on 4 of 2,889,850; one order carries status `refunded`. |
| Most refunded products | **B** `no model` | `refund_total` is order-level. `order_items` has no refund column, so a refund cannot be attributed to a line even when it exists. |
| By refund reason | **B** `no model` | No reason column anywhere in `models.py`. |

### Rarely — Refunds (3 of 6)

| Report | Bucket | Why |
|---|---|---|
| Time between order & refund | **B** `no model` | No refund timestamp exists. `orders` has no refunded_at and there is no refund entity to carry one. |
| By billing location | **B** `empty column` | The dimension is fine (`billing_country` 2,884,311); the measure is not — 4 non-zero refunds. |
| By shipping location | **B** `empty column` | Both halves empty: `shipping_country` 0 and `refund_total` non-zero on 4. |

### Weekly — Acquisition / sources (6 of 6)

| Report | Bucket | Why |
|---|---|---|
| Order sources by referring site | **B** `no model` | `orders` carries `utm_source`, `utm_medium`, `utm_campaign` and no referrer column. |
| Order sources by landing path | **B** `no model` | No landing-page or path column on `orders`. |
| Order sources by UTM combination | **A** | `utm_source` 2,054,935, `utm_medium` 1,460,764, `utm_campaign` 211,957 of 2,889,850 — the three-way combination is groupable today, and the campaign column even has an index. |
| Customer sources by referring site | **B** `no model` | Blocked by the absent column before the engine question arises. |
| Customer sources by landing path | **B** `no model` | As above. |
| Customer sources by UTM combination | **C** | The data is held and populated on `orders`; `customers` carries no source at all. Attributing a customer to one of their orders' UTM triples is a derived per-customer attribute, and `customer_segments` holds one RFM `segment_name` per customer. |

### Weekly — Coupons (1 of 1)

| Report | Bucket | Why |
|---|---|---|
| Coupon usage, amount discounted and sales generated | **A** † | `orders.coupon_code` set on 152,698 and `orders.discount_total` non-zero on 152,685 — the two agree to within 13 rows. "Sales generated" needs `orders.total`, unmeasured. |

### Daily — Customers (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| New customers over time | **A** | First order per `orders.customer_id` over `created_at`, 157,311 distinct customers. Needs no table the pack could not see. |

### Monthly — Customers (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Customers by first-ordered month | **C** | A cohort key derived per customer from their orders, then counted by month. The data is in `orders`; the grouping is the one `customer_segments` cannot hold. |

### Rarely — Customers (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Customer heatmap (world map) | **C** | `orders.billing_country` is populated on 2,884,311 rows, but `customers` has no address column — placing a *customer* on a map means deriving one location from many orders, which is a per-customer attribute the engine would own. |

### Monthly — Customer groups (3 of 5)

| Report | Bucket | Why |
|---|---|---|
| By first product ordered | **C** | Held: `order_items.product_name` on all 4,549,662 lines, 3,743 distinct products, joined through `orders.created_at`. The grouping is a derived per-customer attribute. |
| By billing location | **C** | Held on `orders`, absent on `customers`, same shape as the heatmap row. |
| By shipping location | **B** `empty column` | Spans B and C; B blocks it. `shipping_country` is set on 0 of 2,889,850, so there is nothing for an engine to group. |

### Rarely — Customer groups (2 of 5)

| Report | Bucket | Why |
|---|---|---|
| By custom field | **B** `no model` | No custom-field storage on `customers` or anywhere else. |
| By customer role | **B** `no model` | `customers` is `wc_customer_id, email, first_name, last_name, first_order_at, last_order_at, order_count, total_spent, aov, created_at, updated_at`. No role. |

### Monthly — Retention (4 of 4)

| Report | Bucket | Why |
|---|---|---|
| Orders made over customer lifetime | **A** | A count per `orders.customer_id` across 157,311 customers, bucketed. One `GROUP BY`, no per-customer dimension to choose. |
| New vs returning customer KPIs | **A** † | Same derivation; the revenue KPIs among them need `orders.total`, unmeasured. |
| Time between repeat orders | **A** | A window function over `orders.created_at` partitioned by `customer_id`. Both columns populated. |
| Items bought over customer lifetime | **A** † | `order_items` 4,549,662 rows joined to `orders` by `order_id`. A line count is covered; a unit count needs `quantity`, unmeasured. |

### Monthly — Cohorts (10 of 10)

| Report | Bucket | Why |
|---|---|---|
| Returning customers | **C** | A cohort matrix: cohort key × elapsed period × metric, over `orders.customer_id` and `created_at`. Data held; the cohort key is the user's choice and `customer_segments` holds one fixed label. |
| Customers by order count | **C** | Cohort matrix over a derived per-customer count. |
| Orders per customer | **C** | As above, with orders as the measure. |
| Average order value | **C** † | Same matrix; the measure is `orders.total`, unmeasured. |
| Average order profit | **B** `no model` | Spans B and C; B blocks it. No cost column exists, so no profit measure exists to put in the matrix. |
| Customer lifetime value | **C** | `customers.total_spent` exists, and the lifetime-by-cohort curve is the matrix again. |
| Customer lifetime profit | **B** `no model` | No cost column. |
| Sales over time | **C** † | Cohorted revenue; `orders.total` unmeasured. |
| Orders over time | **C** | Cohorted counts over `orders.created_at`. |
| Profit over time | **B** `no model` | No cost column. |

### Daily — Products (1 of 8)

| Report | Bucket | Why |
|---|---|---|
| Top selling products | **A** † | `order_items.product_name` set on all 4,549,662 lines over 3,743 distinct `wc_product_id`. Ranking by revenue needs `order_items.total` and by units needs `quantity`; neither was measured. `order_items.price` and `sku` are NULL on all 4,549,662, so neither can be the measure. |

### Weekly — Products (4 of 8)

| Report | Bucket | Why |
|---|---|---|
| Top selling variations | **B** `no model` | `products` has no parent or variation column and `order_items` records one `wc_product_id`. A variation is not a thing DD stores. |
| Top selling categories | **A** ‡ | `product_categories` is one row per (product, category) — the right shape, deliberately not `products.category`, which joins names together. The pack cannot see either table, so the population is unknown. |
| Product stock velocity | **B** `no model` | No stock or inventory column on `products`. |
| Variation stock velocity | **B** `no model` | Neither the variation nor the stock exists. |

### Monthly — Products (1 of 8)

| Report | Bucket | Why |
|---|---|---|
| Frequently bought together | **A** | A self-join of `order_items` on `order_id` — 4,549,662 rows, 3,743 distinct products, `product_name` populated throughout. No column the pack found empty is involved. |

### Rarely — Products (2 of 8)

| Report | Bucket | Why |
|---|---|---|
| Product groups (custom bundles of products/variations) | **B** `no model` | A user-defined bundle has to be stored. There is no product-group table, so this is blocked by the missing entity before it is blocked by the engine. |
| Product vendors/brands | **B** `no model` | No vendor or brand column on `products`. |

### Weekly — Comparison (2 of 2)

| Report | Bucket | Why |
|---|---|---|
| Product comparison | **A** † | Two products, two windows, over `order_items` joined to `orders.created_at`. The measure is `order_items.total`, unmeasured. |
| Category comparison | **A** ‡ | Same shape through `product_categories`, whose population the pack could not see. |

### Rarely — Devices (3 of 3)

| Report | Bucket | Why |
|---|---|---|
| Orders by device (desktop vs mobile) | **B** `no model` | No device, user-agent, OS or browser column on `orders` or anywhere in `ALL_MODELS`. |
| Orders by operating system | **B** `no model` | As above. |
| Orders by browser | **B** `no model` | As above. |

### Rarely — Subscriptions (18 of 18)

Every row here is **B** `no model` for the same reason, stated once: there is
no subscription model in `api/analytics/models.py`, so there is no subscription,
no plan, no billing interval, no renewal and no subscription event. No row in
this block is blocked by a band, by the engine, or by an empty column — it is
blocked by an entity DD has never had.

| Report | Bucket | Why |
|---|---|---|
| MRR over time | **B** `no model` | No subscription entity. |
| Active subscriptions over time | **B** `no model` | No subscription entity. |
| Subscription plans breakdown | **B** `no model` | No plan entity. |
| Retention rate over time | **B** `no model` | No subscription entity. Distinct from customer retention, which is C above. |
| Churn rate over time | **B** `no model` | `churn_scores` predicts *customer* churn from order recency; it is not subscription churn and has no subscription to cancel. |
| Subscription cohort retention | **B** `no model` | No subscription entity. |
| Subscription events over time | **B** `no model` | No subscription event log. |
| Active subs by billing location | **B** `no model` | No subscription entity; the location would come from `orders` in any case. |
| Active subs by shipping location | **B** `no model` | No subscription entity, and `shipping_country` is set on 0 orders. |
| Active subs by payment method | **B** `no model` | No subscription entity. |
| Active subs by billing period/interval | **B** `no model` | No interval is stored because no subscription is. |
| Active subs by custom field | **B** `no model` | Neither the subscription nor a custom field exists. |
| Active subscriptions heatmap | **B** `no model` | No subscription entity. |
| Future renewals (expected revenue) | **B** `no model` | No renewal date exists to project from. |
| Subs started by day of week | **B** `no model` | No subscription start timestamp. |
| Subs started by hour | **B** `no model` | No subscription start timestamp. |
| Subs cancelled by day | **B** `no model` | No cancellation timestamp. |
| Subs cancelled by hour | **B** `no model` | No cancellation timestamp. |

### Weekly — Carts (7 of 7)

Every row here is **B** `no model`: `api/analytics/models.py` defines no cart.
DD's order rows begin at the order, so a cart that never became one leaves no
trace at all.

| Report | Bucket | Why |
|---|---|---|
| Carts started by date | **B** `no model` | No cart entity. |
| Carts abandoned by date | **B** `no model` | No cart entity, and abandonment is a cart state. |
| Carts placed by date | **B** `no model` | The resulting order exists; the cart it came from does not, so "placed" cannot be distinguished from "ordered". |
| Carts recovered by date | **B** `no model` | No cart and no recovery event. `interventions` records churn interventions against a customer, not a cart. |
| Time between cart & order | **B** `no model` | No cart timestamp to subtract from `orders.created_at`. |
| Carts by billing country | **B** `no model` | No cart entity; the country would come from `orders`. |
| Cart product reports (most added / abandoned / placed / recovered) | **B** `no model` | No cart and no cart line. |

## Subscriptions and carts, and what they do to a parity number

**Twenty-five of the 100 reports — a quarter of the catalogue — are
unreachable without an entity DD has never had.** Eighteen subscriptions and
seven carts, every one of them bucket B `no model`, none of them blocked by
anything smaller.

That matters to any parity figure computed from this document. "DD has 29 of
Metorik's 100" and "DD has 29 of the 75 that do not require a new entity class"
are different sentences, and the second is the one a reader should be given
before a number is quoted at anyone. The 25 are not "add a `GROUP BY`" work
sitting next to *Orders by day of week*; they are two product surfaces —
recurring billing and pre-order behaviour — that would each need ingestion from
the connector, a table, a sync path and a backfill before the first report
could be drawn. Counting them in the same denominator as the 29 makes the gap
look uniform when it is not.

The same care applies one level down. Of the remaining 34 B rows, refunds
account for 6 and costs for 8 across three groups — so two absent subjects,
neither of them an exotic one, carry 14 of the 34.

## Bucket-A rows the pack does not fully cover

The pack read `analytics_2.orders` and `analytics_2.order_items` and nothing
else, so some bucket-A rows rest on `api/analytics/models.py` alone. Both marks
used above are collected here; an A row carrying neither mark has every column
it needs measured and populated in the pack.

**‡ — the table is one the pack could not see.** The column exists in
`models.py`; whether it holds anything is unknown.

| Row | What is unverified |
|---|---|
| Top selling categories | `product_categories` and `products` — no reading of either table exists in the pack. |
| Category comparison | `product_categories`, as above. |

**† — the table was read, but this column was not one of the eight or five the
query named.** The dimension is measured; the measure usually is not. This mark
is not in the task's list of four unverified tables, and it is the same class
of claim: an unmarked row would assert a population figure the pack does not
contain.

| Row | Unverified column |
|---|---|
| Revenue by billing/shipping location or payment method | `orders.total` |
| Sales forecast (12 months) | `orders.total` |
| Average order gross over time | `orders.total` |
| Order value distribution | `orders.total` |
| New vs returning customer KPIs | `orders.total` |
| Coupon usage, amount discounted and sales generated | `orders.total` |
| By billing/shipping location (country, state, city, ZIP) | `orders.billing_state` |
| Item count distribution | `order_items.quantity` |
| Average order item count | `order_items.quantity` |
| Items bought over customer lifetime | `order_items.quantity` |
| Top selling products | `order_items.total`, `order_items.quantity` |
| Product comparison | `order_items.total` |

Two C rows carry † for the same reason — cohort *Average order value* and
*Sales over time* need `orders.total` — but their bucket does not turn on it,
since the engine blocks them either way.

`orders.total` is the single most load-bearing unmeasured column in this
document: it is the measure behind six A rows. It is `Numeric(10, 2)` and
nullable in `models.py`, and nothing in this pack says how often it is set.

## The live page, checked

`research/metorik-report-catalogue-2026-09-15.md` records that nothing in the
fleet had checked it against its source. I fetched
`https://metorik.com/reports` on **2026-09-15** and it was reachable. Per the
task, the catalogue is classified **as written**; this section records the
disagreement and does not reconcile it.

**It disagrees, mostly about shape.** The page as retrieved is marketing prose
under roughly nine or ten feature sections — Revenue, Order, Customer,
Subscription, Discounts & Refunds, Retention, Product, Device, Cart — not an
enumeration of 100 reports in 17 groups. The catalogue's group names *Costs &
profit*, *Forecasts*, *Order groups*, *Acquisition / sources*, *Coupons*,
*Customer groups*, *Cohorts* and *Comparison* do not appear as headings on the
page; coupons appear folded into "Discounts & Refunds", and cohorts and
comparison appear in body text and a screenshot caption rather than as sections.

**The headline count corroborates the catalogue's own warning.** The page says
"Over 75 Reports" while the catalogue lists 100 — exactly the discrepancy the
catalogue flagged and declined to reconcile.

**Individual rows corroborated by name**, in the fetched text: New vs Returning
Customers, Order Value Distribution, Item Count Distribution, Average Order
Net/Gross, orders grouped by Currency, orders grouped by Custom Field, Refunds
by Country, product comparison, Customer Cohorts, the subscription block's MRR /
churn / LTV / cohorts, the cart block's abandoned and placed carts, COGS and
shipping and transaction costs, inventory forecasts, filtering by UTM values and
landing page and referring domain, and a tax question ("Is revenue higher for
certain tax rates?").

**Wordings that differ.** The page says "Time between Created & Shipped" where
the catalogue says "Order created → completed time"; "Spend by Day/Hour" where
the catalogue has orders by day and by hour; an "in-progress" cart where the
catalogue says carts started; and it describes a desktop/mobile/**tablet**
breakdown where the catalogue says desktop vs mobile. None of these change a
bucket: the created→completed row is B `no model` either way, because DD stores
no status-transition timestamp of any kind.

**Nothing found is a row the catalogue lacks.** No report on the fetched page is
absent from the 100.

**What the fetch could not settle.** The retrieval converts the page to markdown
and answers through a small model, and that step is lossy: a second fetch
reported "not found" for heatmap, operating system, browser and vendor — four
things the catalogue lists — and in the same answer quoted my own question back
as though it were page text. So **absence in the fetch is not evidence of
absence on the page**, and I have not treated it as such anywhere above. The
honest summary is that the source page is organised differently from the
relayed catalogue and markets a smaller number, and that a row-by-row
reconciliation is a separate task with a separate method.

## What I could not verify

**The population of nine of the thirteen tables.** The pack covers `orders` and
`order_items` in `analytics_2`. `customers`, `products`, `product_categories`,
`daily_metrics`, `customer_segments`, `churn_scores`, `interventions`,
`sync_log` and the rest were not read at all. Two bucket-A rows rest on that
gap and are marked ‡; several rows name a convenient alternative source —
`daily_metrics.aov`, `customers.total_spent` — that I did not lean on for the
bucket precisely because it is unverified.

**Twelve columns on the two tables that were read**, listed under † above,
including `orders.total`. The five queries named eight columns on `orders`,
seven more on `orders`, and five on `order_items`; everything else on those two
tables is unmeasured, and I could not add a query.

**One tenant, one instant.** Every figure is `analytics_2` as of 2026-09-15
19:52 UTC. `analytics_1` was not read this run. The emptiness is at least not
new: `research/EVIDENCE-metorik.md`, taken 2026-08-30, shows the same tenant
with `tax_total > 0` and `shipping_total > 0` on 0 orders and `refund_total > 0`
on 4. Whether an empty column is empty because the store has no such data or
because the pipeline does not deliver it is a question this pack cannot answer,
and the two have different consequences — `specs/metorik-gap.md` separated them
for tax and shipping and I have not repeated that work here.

**Whether the buckets survive contact with an implementation.** A bucket-A row
says the columns are there and populated; it does not say the report is easy,
correct or cheap, and no row here was prototyped. In particular the A/C line is
a judgement about what `customer_segments` can express, not a measurement of it:
I read the model, not the engine's query surface, and a reader who thinks a
given C row is really an A row is disagreeing with a judgement rather than with
a figure.

**The bands, entirely.** No agency was asked, nothing was measured, and DD has
no telemetry that would settle any of the 100. They are the most falsifiable
column in the document.

**The catalogue itself remains relayed.** The fetch above narrows the
uncertainty but does not close it: a marketing page is not a feature list, and
neither the catalogue nor this classification establishes that any of the 100
reports is implemented in Metorik as described.
