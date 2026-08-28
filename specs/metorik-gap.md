# Metorik feature gap list — DD analytics

Produced 2026-08-28. Serves `dd-feature-parity` in `objectives-2026-Q4.yaml`,
which names this list as its own first deliverable: *"NEEDS A BASELINE: a
written gap list, Metorik feature vs DD status, ordered by how often an agency
would use it. Without that, this objective ranks 'build another report'
forever."*

The ordering column is therefore the point of the document. A feature DD is
missing that an agency opens twice a year is not a gap worth a sprint, however
cheap it is to build.

---

## How to read this

**DD status** is one of three, and every one of them was established by reading
code or querying the production database on 2026-08-28, not by reading DD's own
documentation. Sources are named per row.

| Status | Means |
|---|---|
| **Has** | Reachable in the product today: an endpoint that is mounted *and* a page that reaches it. |
| **Partial** | Some of it exists — a column that is populated, an endpoint with no page, a report with one dimension where Metorik has ten. The row says which. |
| **Missing** | Nothing. In several rows a *column* exists and is empty in production; that is recorded as missing with the count, because a report over an empty column is not a feature. |

**Agency use** is Daily / Weekly / Rarely / Never. **This column is an estimate
and nothing else.** No agency was asked, no usage was measured, and DD has no
telemetry that would answer it — see *What I could not verify*. It is a
judgement about a WooCommerce agency running client stores, and it is the single
most falsifiable thing in this document. Correcting it is cheaper than building
against it.

Within each frequency band, rows run Missing → Partial → Has, so the gaps read
first.

---

## Summary

The table holds 50 rows: 48 Metorik features, plus 2 DD capabilities with no
Metorik counterpart, marked as such. Of the 48 Metorik features:
**28 missing, 8 partial, 12 has.**

By band — 14 Daily, 21 Weekly, 13 Rarely, 2 Never.

The Daily band first, because a gap an agency hits on its first morning is the
one that ends an evaluation:

* Nothing in DD nets revenue of refunds. The field that would is populated on
  **1 order out of 2,844,177** — which `empty-columns.md` traces to backfill
  coverage rather than to a broken sync, so this is a missing *report*, not a
  missing pipeline.
* There is exactly **one CSV export** in the whole analytics API, and it emits
  one fixed customer segment with fixed columns.
* Segmenting is **seven hard-coded RFM buckets** — Champions, Loyal, Potential
  Loyalists, At Risk, Hibernating, Lost, New, all seven populated on tenant 2.
  Metorik's central claim is that any resource can be segmented by any of its
  attributes.
* There is **no scheduled report** of any kind — no digest, no email, no Slack.
* There is **no cross-store view** for an agency holding several clients.
* There is **no cost data anywhere**, so no profit reporting is possible.

Two things run the other way and are worth protecting rather than closing:
source attribution with CPA and LTV-by-source, and churn prediction with
intervention ROI. Metorik has no equivalent to either.

---

## The table

### Daily — an agency would open this most working days

| Metorik feature | DD status | Evidence | Agency use (est.) |
|---|---|---|---|
| Segment any resource (orders, customers, products, coupons, subscriptions, carts) by any attribute, AND/OR groups | **Missing** | `segment_engine.py` assigns customers — and only customers — to seven fixed buckets from an NTILE(5) RFM score; `VALID_SEGMENTS` is a literal list and `routes/segments.py` rejects anything outside it. A rule builder exists at `app/(dashboard)/segments/builder` but it belongs to the email side — I did not verify it can express analytics filters. | Daily |
| CSV export of orders / customers / products | **Missing** | The only `text/csv` response in the analytics API is `GET /segments/{name}/export` (`routes/segments.py:75`). No order, customer or product export exists. | Daily |
| Export with chosen columns, reordered, incl. custom fields | **Missing** | `export_segment_csv()` emits a fixed 10-column header. | Daily |
| Profit dashboard: revenue − COGS − ad spend − fees − fixed costs | **Missing** | No cost column exists anywhere. `analytics_2.products` is `id, wc_product_id, name, sku, price, category, status`. | Daily |
| Digests — scheduled dashboard summary to email or Slack, daily/weekly/monthly | **Missing** | No digest, scheduled-report or Slack code in `api/analytics` or the analytics frontend. | Daily |
| Multi-store dashboard combining several stores | **Missing** | Analytics is per-tenant throughout (`analytics_schema_name(tenant.id)`). The only cross-tenant view is `app/(dashboard)/admin/tenants`, which is DD staff admin, not an agency-facing roll-up. | Daily |
| Net revenue (gross less refunds) on the main figures | **Missing (the report); the column is sound** | `refund_total` reaches the order list and detail (`order_query.py:162,240`) and no aggregate nets it. It is non-zero on 1 of 2,844,177 orders — traced 2026-08-28 to backfill coverage, not to the sync: the map works end to end and the one `refunded`-status order in the table carries its refund correctly. See `empty-columns.md`. | Daily |
| Order filtering: status, payment, shipping, location, customer tags, email engagement, products contained | **Partial** | `routes/orders.py` accepts `start`, `end`, exact `status`, `search` (email prefix or WooCommerce order id), `sort_by`, `sort_dir`. Nothing else. The order rows *carry* payment method, country, coupon and discount; they cannot be filtered on. | Daily |
| Compare any period to any other, incl. year-on-year | **Partial** | `dashboard_overview()` compares the window to the equal-length window immediately before it (`analytics_engine.py:426`) — a genuine like-for-like, but the only comparison there is. No arbitrary range and no YoY. | Daily |
| Store dashboard: sales, orders, AOV, customers | **Has** | `dashboard_overview()`, `app/(dashboard)/analytics/page.tsx`. | Daily |
| Revenue over time, by hour / day / week / month | **Has** | `revenue_report()` with all four granularities; `analytics/revenue` page. Revenue-status filtering is applied to both sides of AOV (documented conflict 2.1). | Daily |
| Order list, paginated and sortable | **Has** | `routes/orders.py`, `analytics/orders` page. Sort is a total order ending in the primary key, so paging cannot drop rows. | Daily |
| Order detail view | **Has** | `GET /orders/{id}`, `analytics/orders/[id]` page. Shows discount, refund, shipping, tax, coupon, payment method, both addresses. | Daily |
| Order statuses actually present in the store, with counts | **Has** | `GET /orders/statuses`, derived from data rather than a fixed list. | Daily |

### Weekly — an agency would open this most weeks

| Metorik feature | DD status | Evidence | Agency use (est.) |
|---|---|---|---|
| Coupon and discount performance: usage, discount total, orders, AOV with/without | **Missing** | No coupon report or endpoint. The data is partly there — `coupon_code` and `discount_total` are populated on 146,136 and 146,043 orders respectively — and surfaces only as fields on an order row. `Sidebar.tsx` reserves a `/analytics/coupons` nav slot for a page that does not exist. | Weekly |
| Refund reports: refund rate over time, refunds by country | **Missing** | As above — the column is effectively empty in production. | Weekly |
| Subscription reports: MRR, churn, subscription LTV, cohorts | **Missing** | No subscription table exists in `deadly_digital` at all. Applies only to stores selling subscriptions. | Weekly *(for subscription stores; Never otherwise)* |
| Cart reports: abandoned, in-progress, placed | **Missing** | No cart table exists in `deadly_digital` at all. | Weekly |
| Abandoned cart recovery automation | **Missing** | Flow trigger types offered by the UI are `event`, `segment_enter`, `manual` (`flows/page.tsx:132`). No cart trigger. `flows` holds 0 rows in production. | Weekly |
| Recurring exports on a schedule to email / Slack / webhook | **Missing** | No scheduling of any export. | Weekly |
| Inventory levels and forecasts | **Missing** | No stock or inventory column in `analytics_2.products`. | Weekly |
| Product COGS and margin per product | **Missing** | No cost column. | Weekly |
| Product performance by category / vendor / brand | **Partial** | `analytics_2.product_categories` and `products.category` exist, and no endpoint groups by them. `Sidebar.tsx` reserves `/analytics/categories`; no page. | Weekly |
| Location reports: revenue and customers by country / region / city | **Partial — built but unreachable** | `routes/geography.py` is mounted (`analytics/__init__.py:80`) and serves `/geography`, `/cities`, `/areas/{area}` over `billing_country`, populated on 2,840,035 of 2,844,177 orders. There is no page and no frontend proxy route; `Sidebar.tsx` lists `/analytics/geography` among pages that "do not exist yet". An agency cannot reach it. | Weekly |
| Ad platform integrations (Meta, Google, TikTok, Pinterest, Snapchat, Reddit, Bing) | **Partial** | Meta only — `20260817_1400_meta_ad_metrics.py`, `20260825_1100_meta_campaign_alias.py`, and spend enrichment in `routes/sources.py`. No other platform. | Weekly |
| Customer lifetime value | **Partial** | `customers.total_spent` and `aov` are stored, and `/sources/insights` computes LTV *by acquisition source* over a 365-day lookback. There is no LTV distribution or retention-curve report. | Weekly |
| Customer reports: new vs returning, top customers | **Has** | `customer_report()`, `top_customers()`, `analytics/customers` page. | Weekly |
| Customer profile page | **Has** | `customer_profile()`, `analytics/customers/[id]` page. | Weekly |
| Cohort analysis by acquisition month | **Has** | `cohort_analysis()`, `GET /customers/cohorts`, `analytics/customers/cohorts` page. Distinguishes "month has not elapsed" from "nobody returned", which most implementations collapse. | Weekly |
| Product sales and trends | **Has** | `product_report()`, `analytics/products` page, sortable by revenue or quantity. | Weekly |
| UTM source attribution | **Has, and ahead** | `routes/sources.py`: first-order attribution over `utm_source/medium/campaign` (populated on 2,010,699 of 2,844,177 orders), plus CPA, LTV by source, timeline, per-campaign timeline, and scale/cut insights. Metorik reports UTM; it does not do the CPA-versus-LTV judgement. | Weekly |
| Which product acquired each customer | **Has — no Metorik equivalent found** | `GET /products/acquiring`, with a coverage reconciliation in the response. | Weekly |
| Email automations with open / click / revenue reporting | **Has** | `flows`, `campaigns`, `flow_revenue` tables and pages. DD's own product rather than an analytics feature. | Weekly |
| Broadcasts to a segment | **Has** | `app/(dashboard)/campaigns`. | Weekly |
| Predictive churn scoring and intervention ROI | **Has — Metorik has none** | `churn_engine.py`, `intervention_tracker.py`, `analytics/churn` and `analytics/interventions` pages. | Weekly |

### Rarely — a few times a year, or for one client in ten

| Metorik feature | DD status | Evidence | Agency use (est.) |
|---|---|---|---|
| Tax reporting | **Not applicable to this tenant** | `orders.tax_total` is non-zero on 0 of 2,844,177 orders, and `total = SUM(order_items.total)` holds to the penny on 99.58% of them, leaving no room for a tax term. The store charges none — this is correct data, not a gap. Untested rather than broken; see `empty-columns.md`. | Rarely |
| Shipping revenue and shipping-cost rules by country / weight / method | **Not applicable to this tenant (revenue); Missing (cost rules)** | `orders.shipping_total` is non-zero on 0 of 2,844,177 orders and the same arithmetic leaves no room for a shipping term — the store charges none. The cost-rule concept is genuinely absent. See `empty-columns.md`. | Rarely |
| Payment gateway fees as a cost | **Missing** | No fee field. | Rarely |
| Device reports (desktop / mobile / tablet, AOV by device) | **Missing** | No device field on `orders`. | Rarely |
| Order value and item-count distributions | **Missing** | No such report. | Rarely |
| Time between order created and shipped | **Missing** | `orders` carries `created_at`, `updated_at`, `synced_at` — no paid, completed or shipped timestamp. | Rarely |
| Segment by custom meta fields the store defines | **Missing** | No custom-field ingestion in `sync_engine.py`. | Rarely |
| Variation-level product reporting | **Missing** | `order_items` carries `wc_product_id` only; no variation id. | Rarely |
| Support desk integrations (Zendesk, Help Scout, Gorgias, Intercom, Freshdesk, Groove) | **Missing** | None present. | Rarely |
| ShipStation, Google Sheets, Zapier integrations | **Missing** | None present. | Rarely |
| Refunds, coupons, products, carts as segmentable resources in their own right | **Missing** | Only customers are segmentable, into fixed buckets. | Rarely |
| Payment method breakdown | **Partial** | `payment_method` populated on 2,782,530 of 2,844,177 orders and shown on order rows; no report groups by it. `Sidebar.tsx` reserves `/analytics/payment-methods`; no page. | Rarely |
| Orders by currency | **Partial** | `currency` is stored and displayed per order; nothing aggregates by it. | Rarely |

### Never — not worth building for this quarter's agency

| Metorik feature | DD status | Evidence | Agency use (est.) |
|---|---|---|---|
| Multi-currency conversion and reporting | **Missing** | All 2,844,177 production orders are GBP. For the stores DD holds today this would render one row. | Never *(on current tenants)* |
| Shopify-side reporting and Shopify-specific fields | **Missing** | DD ingests WooCommerce only. Relevant only if the agency partner brings Shopify clients — a platform-coverage question, not a report gap, and out of scope for a parity list. | Never *(as a report)* |

---

## What I could not verify

Listed because a gap list whose weakest column is unlabelled will be read as
though every column were equally solid.

1. **The whole Agency-use column.** It is my estimate. No agency was asked, no
   usage data exists, and the agency-partner deal named in `dd-first-revenue`
   has not been signed, so there is no named counterparty whose habits could
   have been used instead. Everything downstream of this ordering inherits that
   uncertainty. One conversation with the prospective partner would replace the
   entire column with something real, and it is by far the cheapest way to make
   this document worth acting on.

2. **Metorik's exact feature set** comes from public marketing and help docs
   (`metorik.com/features`, `/analytics-reports`, `/analytics-reports/costs-profit-reporting`,
   `/engage`, `help.metorik.com` on segmenting and exports). I have no Metorik
   account, so nothing here was seen working. Marketing pages overstate; some
   rows may be thinner in practice than the gap implies. I have not repeated
   Metorik's own count of "75+ reports" anywhere, because I could not check it.

3. ~~**Why `refund_total`, `tax_total` and `shipping_total` are empty.**~~
   **Resolved 2026-08-28 — see `empty-columns.md`.** Tax and shipping: the
   tenant genuinely charges neither, and the table rows above are corrected.
   Refunds: the pipeline is sound and the empty history is a backfill coverage
   artefact. The work is a day, not a schema project. One thing remains open
   there — whether the connector hooks WooCommerce's refund events, which
   decides whether *partial* refunds on completed orders are captured; the
   plugin source is not in the repo.

4. **Whether the email-side segment builder** (`app/(dashboard)/segments/builder`)
   can express analytics filters. If it can, the flexible-segmentation gap is
   narrower than the table says. I confirmed the directory exists and did not
   read the builder.

5. **Only tenant 2 was measured.** `deadly_digital` holds `analytics_1` and
   `analytics_2`; every population count above is tenant 2. A field empty here
   may be populated for tenant 1.

6. **Live behaviour.** Nothing was exercised against a running API. "Has" means
   an endpoint is mounted and a page exists that reaches it, established by
   reading code — not that it renders correctly.

7. **Frontend depth.** I confirmed which pages exist. I did not read each page
   to check that it surfaces everything its endpoint returns, so a row marked
   Has may be thinner in the UI than in the API.

---

## A note on DD's own gap document

`~/deadly-digital-platform/docs/ANALYTICS-GAP-ANALYSIS.md` (dated 17 Feb 2026)
already compares DD to Metorik. **It is stale in at least four places, all in the
same direction — it understates what DD now has:**

* "Refund tracking — Nothing, no refund status handling in analytics schema" —
  `orders.refund_total` exists and reaches the order detail. (Though it is
  empty, so the conclusion happens to survive for a different reason.)
* "Coupon & discount analytics — Nothing, no coupon/discount fields in schema" —
  `coupon_code` and `discount_total` exist and are populated on ~146k orders.
* "Source / UTM attribution — Partial, no general source tracking in analytics
  schema" — `routes/sources.py` now carries attribution, CPA, LTV-by-source and
  Meta ad spend.
* "Cohort retention heatmap — Backend only, no API endpoint or frontend page" —
  both exist.

`platform/components/layout/Sidebar.tsx` carries the same problem in miniature: a
comment listing eight pages "which do not exist yet", two of which (`/analytics/orders`
and cohorts) now do.

Nothing in the table above was taken from either. This document will rot the
same way; the population counts are dated 2026-08-28 and should be re-run, not
quoted, after that.
