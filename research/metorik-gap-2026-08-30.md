# Metorik feature gap list for DD analytics

Written 2026-08-30. Serves `dd-feature-parity` in `objectives-2026-Q4.yaml`,
which asks for "a written gap list, Metorik feature vs DD status, ordered by how
often an agency would use it".

Database readings are from `research/EVIDENCE-metorik.md`, **taken
2026-08-30 14:20 UTC** by the fleet runner. I could not run queries myself.
Metorik pages were read on **2026-08-30**; every URL is listed in
[Sources](#sources) with that date.

This document was written by reading `~/deadly-digital-platform` read-only.
Nothing was changed in it.

---

## How to read this

### The three statuses

| Status | Means |
|---|---|
| **Has** | An endpoint is **mounted** *and* a page in the product reaches it. Both halves were opened. An endpoint nobody can navigate to is not a feature, and a page that renders a hard-coded empty state is not either. |
| **Partial** | Either the data is stored but no report aggregates it, or the report exists but covers materially less than Metorik's equivalent. The cell says which. |
| **Missing** | No endpoint, no page, and in most cases no column. |

"Mounted" is checkable in one place: `api/analytics/__init__.py` includes twelve
sub-routers, and `api/app.py:5039-5040` mounts that router under
`/api/analytics`. `api/app.py:5047-5048` mounts the reconciliation manifest
under `/api/sync`. Every "Has" below traces to a decorator in
`api/analytics/routes/` plus a `fetch()` in `platform/app/(dashboard)/analytics/`.

### The ordering is my estimate and nothing measured it

The rows are ordered by **how often I judge a WooCommerce agency running client
stores would open the feature** — not by how hard it is to build, not by how
much of Metorik it covers. That ordering is a judgement, not a measurement. I
had no usage data for either product: the evidence pack contains none, DD has no
page-usage telemetry I found, and I have no Metorik account to observe. Treat
the ordering as a starting position to argue with, not a finding.

The one thing that shifts the order away from a plain merchant's ranking is the
agency framing in the objective. An agency logs into *many* client stores per
day and reports outward to clients. That moves multi-store switching, export and
scheduled digests up, and moves single-store operational depth (tax, shipping,
device) down.

### Evidence rules used

Every status cites a file path, an endpoint, a column or a migration. Where a
number appears it is either from the evidence pack (marked) or it is not stated
at all. `specs/refund-hook.md` is the standard being followed: name what was
read, quote it, and separate what was inferred from what was seen.

---

## Summary — what the table says

**DD has the reporting spine and almost none of the money breakdown.** The
dashboard, revenue series, order list and detail, product performance, customers,
top customers, cohorts, RFM segments, churn, interventions, source attribution
and geography are all mounted and all reachable from the sidebar. That is a
real analytics product, and it is further along than DD's own gap document says.

The gap is concentrated in three places, and only one of them is a schema
problem:

1. **Revenue is gross and only gross.** `refund_total` exists as a column, is
   written by the sync engine, and is displayed on a single order — but no
   aggregate anywhere subtracts it. `revenue_report()` and `revenue_summary()`
   both compute `SUM(o.total)` filtered by status and nothing else
   (`api/analytics/services/analytics_engine.py:731`, `:816`). Metorik leads
   with net revenue. This is the cheapest high-rank gap in the list because the
   column is already there and already populated.

2. **Five reports are missing over data DD already stores.** Coupons, payment
   methods, categories, tax and shipping all have their columns — `coupon_code`,
   `discount_total`, `payment_method`, `tax_total`, `shipping_total` on
   `api/analytics/models.py:83-93`, and `product_categories` as its own table at
   `:171`. None of them has a route. DD's own sidebar names three of these as
   pages it was designed around that do not exist
   (`platform/components/layout/Sidebar.tsx:45-49`). These are report work, not
   migration work.

3. **Profit does not exist at any layer.** There is no cost column on
   `AnalyticsProduct` (`api/analytics/models.py:150-164`) and no cost field on
   `OrderItem` (`:125-148`). COGS is Metorik's headline and it is the one Tier-1
   gap in this list that needs connector work, a schema change and a report
   before a single number appears.

Two structural gaps sit outside the report list and matter more for an agency
than any single report: **a user belongs to exactly one tenant**
(`platform/lib/auth.ts:26` carries a single `tenantId` through the session), so
there is no way for an agency to hold ten client stores in one login and no
combined view; and **there is no scheduled digest of any kind**, which is how an
agency delivers a weekly number to a client without the client logging in.

What DD has that Metorik does not is narrow but genuine: predictive churn
scoring, automated interventions with conversion attribution, and a
source-of-truth reconciliation manifest. Those are in
[What DD has that Metorik does not](#what-dd-has-that-metorik-does-not).

---

## The comparison table

Ordered by my estimate of how often a WooCommerce agency running client stores
would open it. Rank 1 = opened most often.

| # | Metorik feature | How often an agency opens it | DD status | Evidence |
|---|---|---|---|---|
| 1 | **Store overview dashboard** — KPIs for a window with change vs the prior period | Every day, first thing | **Has** | `GET /api/analytics/dashboard` at `api/analytics/routes/dashboard.py:19`; page `platform/app/(dashboard)/analytics/page.tsx:234`; proxy `platform/app/api/analytics/dashboard/route.ts`; sidebar link `platform/components/layout/Sidebar.tsx:60` |
| 2 | **Order lookup — search a list, open one order** | Every day (support, disputes) | **Has** | `api/analytics/routes/orders.py:54,89,114`; list page `platform/app/(dashboard)/analytics/orders/page.tsx:151`, row click to detail at `:389`; detail page `platform/app/(dashboard)/analytics/orders/[id]/page.tsx:110` |
| 3 | **Multiple stores in one account, switch instantly; multi-store dashboard** | Every day — this is the agency's front door | **Missing** | One `tenantId` per session, set once at sign-in and never switched: `platform/lib/auth.ts:26,32,36`. Cross-tenant views exist only for DD staff under `platform/app/(dashboard)/admin/tenants` |
| 4 | **Revenue over time, gross and net, at chosen granularity** | Most days | **Partial** — gross only | `GET /api/analytics/revenue` at `api/analytics/routes/revenue.py:21` with hour/day/week/month; page `platform/app/(dashboard)/analytics/revenue/page.tsx:112`. Net: `revenue_report()` sums `o.total` alone (`api/analytics/services/analytics_engine.py:731`), and `refund_total` appears nowhere in that file |
| 5 | **Segmenting — filter any report by any attribute, save the segment** ("500+ filters", "unlimited combinations") | Most days; Metorik's own most-used tool | **Missing** as a general capability | Analytics segments are a fixed RFM set validated against `VALID_SEGMENTS` (`api/analytics/routes/segments.py:29-36`). The orders list takes exactly three filters — date range, exact status, email-prefix-or-order-id (`api/analytics/routes/orders.py:58-61`). A rule builder exists for *email* segments (`platform/app/(dashboard)/segments/builder/page.tsx`) and does not reach analytics |
| 6 | **Marketing channel / source attribution** | Most days where the agency runs the ads | **Has**, first-order attribution only | `GET /api/analytics/sources` at `api/analytics/routes/sources.py:104`, plus `/timeline`, `/timeline-by-campaign`, `/insights`; page `platform/app/(dashboard)/analytics/sources/page.tsx:423-425`. Attribution model is each customer's first revenue-status order in range (`api/analytics/routes/sources.py:132-148`) — no last-click alternative |
| 7 | **Ad spend, ROAS, CPA synced from ad platforms** (ChatGPT Ads, Meta, Google, TikTok, Pinterest, Snapchat, Reddit, Microsoft) | Most days where the agency runs the ads | **Partial** — Meta only | `api/services/meta_ads.py`, imported at `api/analytics/routes/sources.py:24`; spend join and CPA/ROAS at `:872`, `:1023`; page renders blended ROAS and best/worst CPA (`platform/app/(dashboard)/analytics/sources/page.tsx:485-539`). No Google, TikTok, Pinterest, Snapchat, Reddit or Microsoft path exists |
| 8 | **CSV export from any report view** | Weekly — this is how client reporting leaves the tool | **Partial** — one view | Only `GET /api/analytics/segments/{name}/export` (`api/analytics/routes/segments.py:70`), reached from `platform/app/(dashboard)/analytics/segments/[name]/page.tsx:102`. `api/analytics/routes/geography.py:14` states the position in as many words: "THREE ROUTES, NO CSV EXPORT. Export is ticketed, not built" |
| 9 | **Product performance report** | Weekly | **Has** | `GET /api/analytics/products` at `api/analytics/routes/products.py:31`; page `platform/app/(dashboard)/analytics/products/page.tsx:120`. Sorts by revenue or quantity, top-N only |
| 10 | **Refund reporting — refund rate over time, refunds by product/reason** | Weekly | **Missing** as a report; column exists | `refund_total` column at `api/analytics/models.py:87`, written by `api/analytics/services/sync_engine.py:511-518`, returned per row by the order list and detail (`api/analytics/services/order_query.py:162,240`). No aggregate reads it. See [note A](#a-refunds-the-column-exists-the-report-does-not-and-the-data-is-nearly-empty) — the data is nearly empty and the two ways of counting a refund already disagree |
| 11 | **Coupon and discount performance** | Weekly during promo cycles | **Missing** as a report; columns exist and are populated | `coupon_code` and `discount_total` at `api/analytics/models.py:88,93`; both returned per order (`api/analytics/services/order_query.py:162`). No route. `platform/components/layout/Sidebar.tsx:47` lists `/analytics/coupons` as a page the nav was designed around that does not exist. Evidence pack, `analytics_2.orders`: 146,509 orders carry a `coupon_code` across 65,444 distinct codes, and 146,429 have `discount_total > 0`, of 2,846,280 orders |
| 12 | **Cart tracking and abandoned-cart recovery emails** | Runs continuously; checked weekly | **Missing** entirely | No cart table in `api/analytics/models.py` (`ALL_MODELS` at `:405-419` has thirteen models, none of them a cart), no cart route in `api/analytics/routes/`, no cart page. Metorik's needs its Helper plugin installed on the store; DD's connector has no equivalent surface |
| 13 | **Scheduled digests to email or Slack** | Set once, delivered weekly — the agency's client-reporting loop | **Missing** | No digest or scheduled-report route under `api/analytics/routes/`; no digest model in `api/analytics/models.py`. DD's scheduler exists for *campaigns*, not for reports |
| 14 | **Net revenue as the headline number** (revenue after refunds and discounts) | Weekly, and in every client conversation about money | **Missing** | Same evidence as row 4. Worth its own row because it is not "a report DD lacks" — it is the number on reports DD already has being the wrong one. `api/analytics/services/analytics_engine.py:816` is the summary a merchant reads |
| 15 | **COGS and profit — margin per product, variation, order and store** | Monthly in a client review; the number an owner asks for | **Missing** at every layer | No cost column on `AnalyticsProduct` (`api/analytics/models.py:150-164`) and none on `OrderItem` (`:125-148`). Needs connector payload, migration and report. Metorik syncs COGS from WooCommerce native or the official COGS plugin and adds shipping, ad spend, transaction fees and operating costs on top |
| 16 | **Customer LTV and top customers** | Weekly | **Has** | `GET /api/analytics/customers/top` at `api/analytics/routes/customers.py:49`; profile at `:102`; pages `platform/app/(dashboard)/analytics/customers/page.tsx:123` and `customers/[id]/page.tsx:141`. Average LTV per source also on the sources page (`api/analytics/routes/sources.py:641`) |
| 17 | **Free-text customer search inside analytics** | Weekly (support hand-offs) | **Partial** | The orders list searches by email prefix or exact order id (`api/analytics/services/order_query.py:120-127`), so a customer *can* be found via their orders. `GET /api/analytics/customers` takes only `start`/`end` and returns metrics, not a searchable list (`api/analytics/routes/customers.py:32-46`); the customers page sends no search term (`platform/app/(dashboard)/analytics/customers/page.tsx:117-123`) |
| 18 | **Category / collection reporting** | Monthly | **Missing** as a report; the table exists | `ProductCategory` model at `api/analytics/models.py:171-190`, created by `api/analytics/migrations/versions/v0008_product_categories.py` and written by the sync engine. `product_report()` groups by `oi.wc_product_id, oi.product_name` only (`api/analytics/services/analytics_engine.py:1226`). `platform/components/layout/Sidebar.tsx:49` lists `/analytics/categories` as missing |
| 19 | **Payment method reporting** | Monthly | **Missing** as a report; column populated | `payment_method` at `api/analytics/models.py:83`, returned per order (`api/analytics/services/order_query.py:160`). No route. `platform/components/layout/Sidebar.tsx:48` lists `/analytics/payment-methods` as missing. Evidence pack, `analytics_2.orders`: 2,784,598 of 2,846,280 orders carry one, across 9 distinct values |
| 20 | **Cohort retention** | Monthly | **Has** | `GET /api/analytics/customers/cohorts` at `api/analytics/routes/customers.py:68`; engine `cohort_analysis()` at `api/analytics/services/analytics_engine.py:1257`; page `platform/app/(dashboard)/analytics/customers/cohorts/page.tsx:155`; proxy `platform/app/api/analytics/customers/cohorts/route.ts`; sidebar `platform/components/layout/Sidebar.tsx:81` |
| 21 | **Saved and shareable custom dashboards** (templates, drag-and-drop, per-team layouts) | Set up monthly, seen daily | **Missing** | `GET /api/analytics/dashboard` returns one fixed shape — trends, top products, recent orders, lifetime totals (`api/analytics/routes/dashboard.py:38-40`). No layout persistence anywhere in `api/analytics/` |
| 22 | **Period-over-period comparison against an arbitrary period** (this week vs the same week last year) | Monthly, and every seasonal peak | **Partial** — previous equal-length window only | `dashboard_overview()` computes the preceding window of equal length ending the day before `start` (`api/analytics/services/analytics_engine.py:451-455`) and that is the only comparison offered. The revenue route has none at all (`api/analytics/routes/revenue.py:21-28`) |
| 23 | **Behavioural segments as reusable customer lists** | Monthly | **Has**, fixed set | `GET /api/analytics/segments` and `/{name}/customers` at `api/analytics/routes/segments.py:39,49`; engine `api/analytics/services/segment_engine.py`; pages `platform/app/(dashboard)/analytics/segments/page.tsx:62` and `segments/[name]/page.tsx:84`. Seven RFM groups, not user-defined — which is why row 5 is Missing rather than Partial |
| 24 | **Geographic reporting** — country, region, city, map | Monthly | **Has**, deeper than expected in one direction and absent in another | `api/analytics/routes/geography.py:59,81,94` — coverage + areas + countries, city ranking, and district drill-down inside a postcode area; page `platform/app/(dashboard)/analytics/geography/page.tsx:207,231,250`. Address columns from `api/analytics/migrations/versions/v0009_order_address_fields.py`. `api/analytics/services/geography.py:21-33` records that five of the eight address columns have never carried a value, so there is no region cut and no ship-to cut |
| 25 | **Product variation-level reporting** (size, dosage, colour) | Store-type dependent; weekly for apparel | **Missing** | `OrderItem` carries `wc_product_id`, `product_name`, `quantity`, `total`, `price`, `sku` and no parent/variation relationship (`api/analytics/models.py:125-148`). `AnalyticsProduct` has no parent id (`:150-164`) |
| 26 | **Inventory forecasting from sales velocity** | Store-type dependent; weekly for stock-holding stores | **Missing** | `AnalyticsProduct` has `name`, `sku`, `price`, `category`, `status` and no stock quantity or stock status (`api/analytics/models.py:150-164`) |
| 27 | **Subscription reporting — MRR, subscription churn, renewal cohorts** | Store-type dependent; weekly where it applies | **Missing** | No subscription model in `ALL_MODELS` (`api/analytics/models.py:405-419`), no subscription route |
| 28 | **Email marketing and automations** (Metorik Engage: broadcasts, automations, cart recovery) | Weekly where the agency runs the marketing | **Has**, and off by default | Campaigns and flows live outside `/analytics`: `platform/app/(dashboard)/campaigns`, `platform/app/(dashboard)/flows`. The whole Marketing nav section is gated on `NEXT_PUBLIC_ENABLE_MARKETING === 'true'` (`platform/components/layout/Sidebar.tsx:15,104`), so on a deployment without that variable an agency sees analytics only |
| 29 | **Tax reporting by jurisdiction** | Quarterly | **Missing** as a report; column exists, unpopulated here | `tax_total` at `api/analytics/models.py:90`. No route. Evidence pack, `analytics_2.orders`: **zero** of 2,846,280 orders have `tax_total > 0`. See [note B](#b-tax-and-shipping-are-zero-and-zero-has-two-meanings) — zero is ambiguous |
| 30 | **Shipping revenue and cost reporting** | Quarterly | **Missing** as a report; column exists, unpopulated here | `shipping_total` at `api/analytics/models.py:89`. No route. Evidence pack: **zero** of 2,846,280 orders in `analytics_2.orders` have `shipping_total > 0`. Same ambiguity as note B |
| 31 | **Device reports** (desktop / mobile / tablet) | Rarely | **Missing** | No device or user-agent column on `AnalyticsOrder` (`api/analytics/models.py:73-122`) |
| 32 | **Real-time updating reports** | A background property, not a page | **Missing** | Every analytics page polls with `fetch` on mount; there is no websocket or SSE path in `platform/app/(dashboard)/analytics/`. DD's model is push-on-order-change into per-tenant schemas, then recompute (`api/analytics/routes/sync.py:63`) |

---

## Notes on rows that need more than a cell

### A. Refunds: the column exists, the report does not, and the data is nearly empty

Three separate facts, and conflating them is how this row gets mis-costed.

1. **Storage is done.** `refund_total` is on `AnalyticsOrder`
   (`api/analytics/models.py:87`) and written by the sync engine's upsert
   (`api/analytics/services/sync_engine.py:511-518`).
   `api/analytics/migrations/versions/v0007_orders_money_columns.py:1-29`
   restored these five money columns *together with the writer*, explicitly
   because the first attempt at them shipped storage with no contract and sat
   empty for six months.

2. **No aggregate reads it.** Grep of `api/analytics/services/analytics_engine.py`
   returns no occurrence of `refund_total`, `discount_total`, `tax_total`,
   `shipping_total`, `coupon_code` or `payment_method`. The only readers are the
   order list and order detail (`api/analytics/services/order_query.py:162,240`)
   and the reconciliation manifest (`api/analytics/models.py:361`).

3. **There is almost nothing to report on yet, and the two counts disagree.**
   From the evidence pack: `analytics_2.orders` has **4** orders with
   `refund_total > 0` out of 2,846,280, and `analytics_1.orders` has **4** out
   of 679,912. The status breakdown for `analytics_2.orders` shows **1** order
   with status `refunded`. So a refund report built on `status = 'refunded'` and
   one built on `refund_total > 0` would show different numbers on the same
   store today — 1 against 4. Whichever is chosen has to be stated on the page.

   `specs/refund-hook.md` establishes independently that the connector's refund
   hooks are registered and that the refund-driven backfill exists as
   `wp dd sync-refunds` but has no record of ever being run. That is consistent
   with a near-empty column, and it means **a refund report shipped today would
   render an empty page for a reason that is not the report's fault**. Running
   that backfill is the prerequisite, and it is cheap.

### B. Tax and shipping are zero, and zero has two meanings

`v0007` gives the four money totals `DEFAULT 0` and makes `coupon_code`
nullable, deliberately:

> DEFAULT 0 on the four totals, NULL on `coupon_code`. That distinction is load
> bearing: "no coupon was used" and "the plugin did not send coupon data" are
> different facts […] BACKFILL: None, and none is possible. The plugin ships
> after the backend, so every existing row keeps 0 / NULL until that store
> re-syncs.
> — `api/analytics/migrations/versions/v0007_orders_money_columns.py:37-47`

So `tax_total = 0` on every row means either "this store charges no tax" or
"these rows predate the writer". I cannot distinguish them: the reader has no
access to `synced_at` distributions or anything else that would separate them,
and the evidence pack has no query for it.

The one thing pushing towards the first reading is that the same store's
`coupon_code` is **not** all-NULL — 146,509 rows carry one — which shows the
money block does arrive from this connector. A competitions store plausibly
charges no tax and ships nothing. **Plausible is not verified.** Before anyone
costs a tax report, run one query: `SELECT count(*) FROM analytics_2.orders
WHERE tax_total > 0 AND synced_at > <plugin ship date>`.

### C. UTM is on 100% of orders and I cannot tell what that means

The evidence pack shows `count(utm_source)` exactly equal to `count(*)` on both
tenants: 2,846,280 of 2,846,280 on `analytics_2.orders`, and 679,912 of 679,912
on `analytics_1.orders`. Not one NULL on either store.

The sync engine passes `utm_source` straight through with no default
(`api/analytics/services/sync_engine.py:422`), so the connector is supplying a
value for every order. The attribution query itself coalesces NULL to
`'(direct)'` (`api/analytics/routes/sources.py:151-153`) — a branch that,
on these two tenants, never fires.

**What I cannot tell is whether those 2.8M values are meaningful.** The pack has
no `count(DISTINCT utm_source)` and no value distribution. If the connector
writes a literal `"direct"` string for untagged traffic, the column is 100%
populated and mostly uninformative, and the sources page's own `(direct)` bucket
is being bypassed. That is a real risk to the number on the sources page and it
is one query away from being settled — it is just not a query I could run.

### D. Geography is better than the gap document says and worse than it looks

`api/analytics/routes/geography.py` mounts three routes and the page reaches all
three, including the postcode-district drill-down
(`platform/app/(dashboard)/analytics/geography/page.tsx:250` →
`platform/app/api/analytics/geography/areas/[area]/route.ts`). The service
docstring also documents two correctness rulings worth knowing: the UK postcode
decomposition is country-gated, because Irish Eircodes parse *plausibly* under a
UK regex and would file Dublin orders into London postcode areas; and the
district is taken as the outward code by length rather than by the regex the
migration plan proposed (`api/analytics/services/geography.py:35-78`).

Against that: `api/analytics/services/geography.py:21-33` records that
`billing_state` and all four `shipping_*` columns have never carried a value, so
there is no region cut and no ship-to-versus-bill-to cut, and neither is fixable
in DD — both need connector work. I did not verify those population figures
myself; see [What I could not verify](#what-i-could-not-verify).

From the evidence pack I *can* say `analytics_2.orders` has `billing_country`
on 2,842,138 of 2,846,280 orders across **2 distinct countries**. A country
report on this tenant has two rows in it.

---

## What DD has that Metorik does not

Not the point of this document, but it belongs in it: parity work should not
trade these away, and an agency evaluation will ask what DD does that the
incumbent does not.

| Capability | Status | Evidence |
|---|---|---|
| **Predictive churn scoring** — risk tiers, predicted churn date, days-since-last | Live, page reaches it | `api/analytics/routes/churn.py:34,43`; `ChurnScore` model `api/analytics/models.py:215-234`; page `platform/app/(dashboard)/analytics/churn/page.tsx:104,129` |
| **Automated interventions with conversion attribution** — did the email that went out actually produce an order | Live, page reaches it | `api/analytics/routes/interventions.py:23,34`; `Intervention` model with `converted`, `converted_at`, `revenue_recovered` at `api/analytics/models.py:237-257`; page `platform/app/(dashboard)/analytics/interventions/page.tsx:87,111` |
| **Source-of-truth reconciliation** — the store asserts its own period totals and DD compares against its copy | Live, surfaced on the dashboard | `api/analytics/routes/manifest.py:175,290`, mounted at `api/app.py:5047-5048`; `ReconciliationManifest` model `api/analytics/models.py:326-401`; dashboard verification wired in at `api/analytics/services/analytics_engine.py:477` |
| **"Which product acquired this customer"** | Live, own page | `api/analytics/routes/products.py:54`; `api/analytics/services/acquisition.py`; page `platform/app/(dashboard)/analytics/products/acquiring/page.tsx:166` |
| **Both order populations named on every figure** — all-status and revenue-status counts never collapsed into one ambiguous number | Live across the reporting surface | `api/analytics/services/order_query.py:185-197`; `api/analytics/services/analytics_engine.py:755-766` |
| **Schema-per-tenant isolation** | Live | `api/analytics/schema_context.py`, `api/analytics/schema_manager.py` |

I have no Metorik account, so "Metorik does not have this" rests entirely on its
public pages not advertising it. For predictive churn and intervention-to-order
attribution that is a reasonable read of a marketing site that lists its features
exhaustively. **It is not the same as having checked.**

---

## Where DD's own gap analysis is wrong

`docs/ANALYTICS-GAP-ANALYSIS.md` (platform repo, last updated 17 Feb 2026) is
the document this one replaces. It is six months stale and its "We Have" column
is wrong in eight places, all in the same direction: it under-reports what DD
has. Anyone ranking work off it will build things that exist.

| Its claim | What the source says |
|---|---|
| **#1 Refund tracking** — "Nothing — no refund status handling in analytics schema" | `refund_total` is a column (`api/analytics/models.py:87`), written by the sync engine (`api/analytics/services/sync_engine.py:511-518`) and shown per order (`api/analytics/services/order_query.py:294`). The gap is the *aggregate*, not the schema |
| **#3 Coupon analytics** — "Nothing — no coupon/discount fields in schema" | `coupon_code` and `discount_total` are columns (`api/analytics/models.py:88,93`) and are populated: 146,509 coupon codes and 146,429 discounted orders on `analytics_2.orders` per the evidence pack. This is now a report-only gap |
| **#4 Source/UTM attribution** — "Partial — […] No general source tracking in analytics schema" | `utm_source`, `utm_medium`, `utm_campaign` are columns (`api/analytics/models.py:107-109`, migration `api/analytics/migrations/versions/v0002_orders_utm_columns.py`), fully populated on both tenants, and there is a whole attribution surface at `api/analytics/routes/sources.py` with a page |
| **#5 Cohort retention heatmap** — "Backend only — `cohort_analysis()` exists but no API endpoint or frontend page" | Both exist: endpoint `api/analytics/routes/customers.py:68`, proxy `platform/app/api/analytics/customers/cohorts/route.ts`, page `platform/app/(dashboard)/analytics/customers/cohorts/page.tsx`, sidebar link `platform/components/layout/Sidebar.tsx:81` |
| **#11 Order detail page** — "No individual order page in analytics" | `GET /api/analytics/orders/{id}` at `api/analytics/routes/orders.py:114` and page `platform/app/(dashboard)/analytics/orders/[id]/page.tsx`, reached by clicking a row in the list (`platform/app/(dashboard)/analytics/orders/page.tsx:389`) |
| **#17 Ad spend integration** — "Nothing — no ad platform integrations" | Meta is integrated: `api/services/meta_ads.py`, imported at `api/analytics/routes/sources.py:24`, with CPA/ROAS enrichment at `:872` and budget read/write at `:1074,1092`. The gap is the *other* platforms |
| **#19 Geographic reporting** — "No location/address fields in analytics schema" | Eight address columns (`api/analytics/models.py:98-105`, migration `api/analytics/migrations/versions/v0009_order_address_fields.py`) and three geography routes with a page. Five of the eight columns are unpopulated, which is a different and smaller claim |
| **#20/#21 Tax and shipping** — "No tax fields in analytics schema" / "No shipping fields in analytics schema" | `tax_total` and `shipping_total` are columns (`api/analytics/models.py:89-90`). They are unpopulated on the tenant we can read — a connector or backfill problem, not a migration one, and it has a different cost |

**Its "Phase A" roadmap is mostly already delivered.** Phase A prescribes adding
`refund_total`, `discount_total` and `coupon_code` to the orders schema and
exposing `cohort_analysis()` as an endpoint plus a frontend heatmap. All four
shipped. What did *not* ship is the fourth Phase A bullet — "Modify all revenue
calculations to show gross/net/discount breakdown" — which is row 4 and row 14
of the table above and is the single highest-value item still open.

There is a documented reason the old document reads this way, and it is worth
knowing before writing the next one. `v0007`'s own header records that these
columns were added by hand in Feb 2026 *from that document's* "Data Schema
Changes Required" section, never committed, never populated, and dropped again
by migration 0004 on 17 Aug 2026 after a census found them empty across 803,256
rows. The gap document was describing a schema that briefly existed, then did
not, and now does again with a writer behind it
(`api/analytics/migrations/versions/v0007_orders_money_columns.py:9-29`).

---

## What I could not verify

This section is the honest part and it is long on purpose.

### Nothing about Metorik was seen working

I have no Metorik account. **Every Metorik claim in this document is a reading of
Metorik's own marketing and help pages, retrieved 2026-08-30**, and marketing
copy is the least reliable class of evidence in here. Specifically:

- Counts like "over 75 reports" and "500+ filters" are Metorik's numbers, not
  measured ones. I did not see 75 reports.
- Where a feature is described as covering something ("profit reporting includes
  shipping, ad spend, transaction-related costs, discounts and operational
  expenses"), I cannot say how well it covers it, what it costs, which plan tier
  it is on, or whether it works on a WooCommerce store of this size.
- I could not check whether any Metorik feature is degraded or absent for
  WooCommerce specifically versus Shopify — several pages describe both
  platforms in one breath.
- Metorik's cart-tracking page 404'd at the URL I first tried; the cart claims
  come from search results over `help.metorik.com` rather than from a page I
  fetched whole. That row is the weakest-sourced in the table.
- **"Metorik does not have X" is the weakest claim shape in this document** and
  it appears in [What DD has that Metorik does not](#what-dd-has-that-metorik-does-not).
  It rests on absence from a marketing site. Before that section is used in a
  sales conversation, someone with a Metorik trial should check it.

### The database reader could see four tables and no more

The evidence pack was produced against `analytics_1.orders`,
`analytics_2.orders`, `public.orders` and `public.tenants`. **There is no
`customers`, no `products`, no `order_items` and no `product_categories` in
anything I could read.** Every claim below would have needed one of those and is
therefore unverified:

| Claim I could not check | Table it needed |
|---|---|
| Whether `products.category` or `product_categories` is populated at all, and how many categories a real store has — so whether a category report would render anything | `analytics_N.product_categories`, `analytics_N.products` |
| Whether `order_items.price` and `order_items.sku` are arriving. `api/analytics/services/order_query.py:326-347` is built for `price` being NULL, and `specs/refund-hook.md` §D1 records `sku` measured at 0/74 on a build that sends it — an open defect I could not re-measure | `analytics_N.order_items` |
| How many products, variations or SKUs exist per tenant — so whether variation reporting (row 25) matters here | `analytics_N.products` |
| Customer counts, LTV distribution, or whether `customers.first_order_at` still disagrees with the derived value that `api/analytics/services/analytics_engine.py:679-686` warns about | `analytics_N.customers` |
| Whether any product co-occurs with another often enough for "frequently bought together" to be worth building | `analytics_N.order_items` |
| Whether the churn scores and RFM segments are populated, or whether those pages render empty on a real tenant | `analytics_N.churn_scores`, `analytics_N.customer_segments` |
| Whether `daily_metrics` agrees with `orders` — the two-populations problem `api/analytics/models.py:273-281` describes | `analytics_N.daily_metrics` |
| Whether any Meta ad spend rows exist, so whether the ROAS column on the sources page has ever shown a real number | Meta spend tables in `public` |

### Things I read in the platform but did not independently confirm

Several figures in this document are **quoted from DD's own source comments**,
not measured by me. They were true when written and I have no way to re-check
them:

- `api/analytics/services/geography.py:21-33`: five of eight address columns
  never populated, measured on `analytics_1` on 23 Aug 2026.
- `api/analytics/migrations/versions/v0007_orders_money_columns.py:13-15`: the
  803,256-row census behind migration 0004.
- `api/analytics/routes/products.py:88-90`: 785 acquiring products against a
  200-row page cap.
- `api/analytics/services/analytics_engine.py:781-788`: the 10.40× customer
  inflation the revenue summary was built to fix.

Where I state a population count as fact rather than as a quote, it comes from
`research/EVIDENCE-metorik.md` and nowhere else.

### Things about DD I could not establish from source alone

- **Whether any of this is deployed.** I read a checkout. `specs/refund-hook.md`
  makes the rule explicit — a copy on this box is not evidence of what is
  running — and it applies here in full. Every "Has" means "mounted and reachable
  in this source tree".
- **Whether the pages work.** I opened files and traced `fetch` calls to routes.
  I did not run the app, did not render a page, and did not observe a single
  response body. A page that reaches an endpoint and then throws on the shape of
  its response would read as "Has" to this method.
- **Whether `NEXT_PUBLIC_ENABLE_MARKETING` is set in any deployed environment**,
  which decides whether row 28 is Has or invisible.
- **Whether subscription gating blocks anything in practice.**
  `api/analytics/__init__.py:23-25` says every reporting route is gated by
  `subscription_required`. I did not check what an unpaid tenant sees.
- **The open reconciliation issue's effect on all of this.** The evidence pack
  carries one open fleet issue: `dd_analytics_reconciliation`,
  `MISSING_ANALYTICS_ORDER`, CRITICAL, 47 occurrences, current magnitude 29,603,
  first seen 2026-08-28 17:00 UTC, last seen 2026-08-30 14:00 UTC. **If 29,603
  orders are missing from analytics, every figure on every page in this document
  is computed over an incomplete population.** That is `dd-trustworthy`, not
  `dd-feature-parity`, and it outranks every row in the table — the objectives
  file says so directly: "Parity work must not outrank correctness work by
  default."

### What would settle the most in the least time

Five queries, none of which I could run:

```sql
SELECT count(DISTINCT utm_source), count(*) FILTER (WHERE utm_source = 'direct')
  FROM analytics_2.orders;                              -- note C
SELECT count(*) FROM analytics_2.orders
 WHERE tax_total > 0 AND synced_at > '<plugin ship date>';   -- note B
SELECT count(*), count(price), count(sku) FROM analytics_2.order_items;
SELECT count(*), count(DISTINCT category) FROM analytics_2.product_categories;
SELECT count(*) FROM analytics_2.customers;
```

The first decides whether the sources page — one of the three highest-ranked
things DD already has — is showing an agency a real number or a column of
`direct`. That is the one to run first.

---

## Sources

Metorik pages, all retrieved **2026-08-30**. These are Metorik's own marketing
and help properties, which is the only source used for what Metorik does.

- https://metorik.com/features — feature index: analytics and reports, costs and
  profit, product reporting, subscriptions, cohorts, segmenting, exporting,
  digests, Engage (automations, cart recovery, broadcasts), ad-platform
  integrations
- https://metorik.com/features/reports — "Over 75 Reports"; revenue (gross and
  net), orders, customers, subscriptions, discounts and refunds, retention,
  products, device, carts
- https://metorik.com/features/segmenting — "500+ Filters", "Unlimited
  Combinations", saved segments feeding digests, dashboards and CSV export
- https://metorik.com/analytics-reports/costs-profit-reporting — COGS, shipping,
  ad spend, transaction fees, operational expenses; COGS set manually, synced
  from WooCommerce/Shopify native, or bulk-imported by product id or SKU; ad
  spend synced from ChatGPT Ads, Meta, Google, TikTok, Pinterest, Snapchat,
  Reddit and Microsoft
- https://metorik.com/analytics-reports/product-reports — per-product and
  per-variation sales, inventory, costs and profit; category, collection, vendor
  and tag breakdowns; inventory forecasting from sales velocity
- https://metorik.com/analytics-reports/automated-reports-digests — scheduled
  digests by email or Slack
- https://metorik.com/blog/a-multistore-dashboard-for-woocommerce — multiple
  stores in one account, instant switching, aggregated multi-store dashboard
- https://help.metorik.com/article/108-cart-tracking-overview — cart tracking via
  the Metorik Helper plugin; carts marked abandoned after 30–60 minutes
- https://help.metorik.com/article/110-cart-recovery-emails — cart recovery
  emails via Engage
- https://help.metorik.com/article/53-all-about-exports — CSV export, emailed or
  posted to Slack, including recurring exports
- https://help.metorik.com/article/193-cost-of-goods-sold-cogs-and-profit-reports-in-metorik
  — how COGS is set in Metorik

Deadly Digital evidence: the file paths and line numbers cited throughout, read
from `~/deadly-digital-platform` on 2026-08-30, plus database readings in
`research/EVIDENCE-metorik.md` taken 2026-08-30 14:20 UTC.

Prior DD document overturned in eight places: `docs/ANALYTICS-GAP-ANALYSIS.md`
(platform repo, dated 17 Feb 2026).
