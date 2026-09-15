# Metorik's published report catalogue — 100 reports

## Provenance, and what it is not

| | |
|---|---|
| **Source** | Metorik's own reports page, `https://metorik.com/reports` |
| **Retrieved** | 2026-09-15 |
| **Retrieved by** | a person, and pasted into the fleet |
| **Verified against the live page by this repository** | **NO** |

**This is a RELAYED document.** Nothing in it was fetched or checked by the
fleet: no agent opened that page, and the list below is exactly what was handed
over, regrouped into markdown and counted. Treat every line as "Metorik's
marketing said this on 2026-09-15" and not as "this is what Metorik does".

**The counts were checked.** The group headings claim 3, 5, 3, 10, 6, 6, 6, 1,
3, 5, 4, 10, 8, 2, 3, 18, 7 — which sums to 100, and each group's listed items
match its heading. That is arithmetic on the relayed text, not corroboration of
it.

**Metorik markets "75+ reports" and the catalogue lists 100.** Worth recording
rather than reconciling: a marketing number and a page listing are two claims
about the same product and they disagree, which is a reason to trust neither as
a count of what is *implemented*.

## How this relates to `specs/metorik-gap.md`, which it does NOT replace

The two are different kinds of document and only one of them has done the hard
part.

| | `specs/metorik-gap.md` | this |
|---|---|---|
| produced | 2026-08-28 | 2026-09-15 |
| rows | **50** — 48 Metorik features + 2 DD capabilities with no Metorik counterpart | **100** reports |
| DD status per row | **yes** — Has / Partial / Missing / Not applicable, each established by reading code or querying production on 2026-08-28 | **none** |
| agency-use band | **yes** — 14 Daily, 21 Weekly, 13 Rarely, 2 Never | **none** |
| grouping | by how often an agency would use it | by Metorik's own product sections |

The gap list's own header says the ordering column "is therefore the point of
the document". This catalogue has no ordering column, no DD status, and no
band.

**That is why the candidate producer is NOT pointed here yet.**
`console/load_candidates.band_of` reads a candidate's band from the *section
heading* of the evidence it cites, and `console/rank.py` sorts a NULL band
LAST (`NO_BAND = 4`). A producer run against this document would emit
technically-legal candidates with no band, and every one of them would rank
below every banded candidate already in the pool — permanently, and silently,
because nothing refuses them. The catalogue widens what the pool can draw from
only once something supplies the status and the band.

## The catalogue

### Revenue (3)
- Net/gross revenue over time
- Revenue by billing/shipping location or payment method
- Revenue by tax code, label or ID

### Costs & profit (5)
- Profit & costs over time
- Advertising costs by platform
- Operational costs by type
- Transaction costs by payment method
- Shipping costs by shipping method

### Forecasts (3)
- Sales forecast (12 months)
- Order volume forecast (3/6/12 months)
- New customers forecast

### Orders (10)
- Orders over time
- New vs returning customer orders
- Item count distribution
- Order value distribution
- Orders by day of week
- Orders by hour of day
- Orders heatmap (day × hour)
- Average order gross over time
- Average order item count
- Order created → completed time

### Order groups (6)
- By status
- By payment method
- By shipping method
- By currency
- By billing/shipping location (country, state, city, ZIP)
- By custom field

### Refunds (6)
- Refunds over time
- Time between order & refund
- Most refunded products
- By refund reason
- By billing location
- By shipping location

### Acquisition / sources (6)
- Order sources by referring site
- Order sources by landing path
- Order sources by UTM combination
- Customer sources by referring site
- Customer sources by landing path
- Customer sources by UTM combination

### Coupons (1)
- Coupon usage, amount discounted and sales generated

### Customers (3)
- New customers over time
- Customers by first-ordered month
- Customer heatmap (world map)

### Customer groups (5)
- By first product ordered
- By billing location
- By shipping location
- By custom field
- By customer role

### Retention (4)
- Orders made over customer lifetime
- New vs returning customer KPIs
- Time between repeat orders
- Items bought over customer lifetime

### Cohorts (10)
- Returning customers
- Customers by order count
- Orders per customer
- Average order value
- Average order profit
- Customer lifetime value
- Customer lifetime profit
- Sales over time
- Orders over time
- Profit over time

### Products (8)
- Frequently bought together
- Top selling products
- Top selling variations
- Top selling categories
- Product groups (custom bundles of products/variations)
- Product stock velocity
- Variation stock velocity
- Product vendors/brands

### Comparison (2)
- Product comparison
- Category comparison

### Devices (3)
- Orders by device (desktop vs mobile)
- Orders by operating system
- Orders by browser

### Subscriptions (18)
- MRR over time
- Active subscriptions over time
- Subscription plans breakdown
- Retention rate over time
- Churn rate over time
- Subscription cohort retention
- Subscription events over time
- Active subs by billing location
- Active subs by shipping location
- Active subs by payment method
- Active subs by billing period/interval
- Active subs by custom field
- Active subscriptions heatmap
- Future renewals (expected revenue)
- Subs started by day of week
- Subs started by hour
- Subs cancelled by day
- Subs cancelled by hour

### Carts (7)
- Carts started by date
- Carts abandoned by date
- Carts placed by date
- Carts recovered by date
- Time between cart & order
- Carts by billing country
- Cart product reports (most added / abandoned / placed / recovered)

## Two things the count understates, relayed as given

**The catalogue is a starting point, not the surface area.** Any report can be
filtered by a claimed 500+ filters across orders, customers, products,
subscriptions, carts and coupons — including custom fields, with AND/OR logic
and filter groups, and saved segments shared with a team. So the product is
report × segment, not 100 fixed views. If that is accurate it matters more than
the hundred: it is the difference between building reports and building a
reporting engine.

**The surrounding machinery may be the harder half.** CSV export on any report,
scheduled email digests (daily/weekly/monthly), a REST API and webhooks, custom
dashboards, multi-store reporting, and all processing done off-site so the
store's database is not queried. Plus, newly marketed, an MCP integration for
Claude/ChatGPT and a "Tori" AI sidekick.

None of that paragraph was verified either.

## What this document deliberately does not do

It does not say what DD has, what it lacks, or what any of it is worth. That is
the classification task queued against it, and until that exists this is an
inventory of somebody else's marketing page and should be cited as one.
