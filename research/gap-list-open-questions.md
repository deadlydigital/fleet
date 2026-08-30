# The five queries the gap list could not run, and the refund disagreement

Answers to *What would settle the most in the least time* in
`research/metorik-gap-2026-08-30.md`, plus the refund question that document
left open.

Read-only against `deadly_digital` on **2026-08-30**. Every figure below is
tenant 2 (`analytics_2`) unless it says otherwise. Nothing was written to any
database and nothing in `~/deadly-digital-platform` was changed.

> **On the credential.** The runner's evidence pack is produced by
> `dd_detector_login`, which holds SELECT on `analytics_1.orders` and
> `analytics_2.orders` and nothing else — which is why the gap list could not
> answer these. These readings were taken by hand with the migration identity
> in a `default_transaction_read_only` session. That identity is a migration
> identity and not a runtime principal (`001_v1_core.sql`), so this is an
> operator running queries, not a capability the runner gained. **If these
> readings are to be refreshed on a schedule, the right move is to widen the
> detector reader deliberately, not to repeat this.**

---

## Summary

| Question | Answer | What it does to the ranking |
|---|---|---|
| 1. UTM attribution | **287 sources, none of them `direct`. 29% is the empty string.** Real attribution, badly fragmented | Sources page is genuine — but a normalisation job is now a *prerequisite*, not a polish item |
| 2. Tax and shipping | **Settled: the store charges neither.** Every row passed through the writer | Both rows drop off the list. Not a gap |
| 3. `order_items.price` / `sku` | **0 of 4,488,746.** Both entirely absent | Variation and SKU reporting move from "Rarely" to **impossible**. `implied_unit_price` is the only path, not a fallback |
| 4. `product_categories` | **3,951 rows, 47 categories, 1,723 of 3,700 products** | A category report would render. Row rises |
| 5. `customers` | **195,397** | Customer reports have data. Confirms rather than changes |
| 6. Refund disagreement | Different questions, not a conflict. **Use `refund_total`** | And it exposes something worse — see below |

---

## 1. UTM attribution — the one that decided the most

```sql
SELECT count(*), count(utm_source), count(DISTINCT utm_source),
       count(*) FILTER (WHERE utm_source = 'direct')
  FROM analytics_2.orders;
--  2847915 | 2847915 | 287 | 0
```

**Both hypotheses were wrong.** It is not a column of `direct` — the literal
string `direct` appears **zero** times. And it is not the clean 100% coverage
the gap list reports.

The gap list says `utm_source` is "populated on 100% of orders". That is
`count(utm_source) = count(*)`, and it is true only because **833,490 rows
(29.3%) hold the empty string rather than NULL**. `count()` scores `''` as
populated. There are no NULLs at all. So the honest figure is **70.7%
attributed**, and the document's headline number should be corrected.

What is actually there, normalised:

| | orders | % |
|---|---:|---:|
| *(unattributed — empty string)* | 833,490 | 29.3 |
| Meta family | 759,916 | 26.7 |
| `(direct)` | 628,692 | 22.1 |
| Klaviyo | 334,616 | 11.7 |
| Google family | 260,579 | 9.1 |
| everything else | 30,649 | 1.1 |

**The sentinel is `(direct)` with parentheses**, not `direct`. Anything
written against the unparenthesised spelling matches nothing.

**The fragmentation is the finding.** The Meta family alone is spread across
**21 spellings** — `m.facebook.com`, `facebook.com`, `l.facebook.com`, `fb`,
`meta_paid`, `Meta_Paid`, `l.instagram.com`, `ig` and more. Case matters:
`meta_paid` and `Meta_Paid` are different rows today. Of the 287 distinct
values, **220 account for fewer than 100 orders each and 3,606 orders between
them** — a long tail that is almost entirely spelling.

**What it settles:** the sources page is showing an agency real attribution,
not a column of `direct`. The gap list's ranking of it as one of DD's three
strongest positions survives.

**What it changes:** an unnormalised report fragments the single largest
channel across 21 rows and buries it under `(direct)`. A merchant would
conclude Meta drives 19% when it drives 27%. **Source normalisation moves from
absent-from-the-list to a prerequisite for the sources page being trusted** —
and it is a lookup table, not a project. The 29% empty string is a separate
question for the connector: those orders arrived with no source at all.

## 2. Tax and shipping — settled, and they are not gaps

The gap list could not separate *"this store charges no tax"* from *"these
rows predate the writer"*. The plugin ship date, established from the
migrations rather than guessed:

- `v0004_drop_unused_order_money_columns.py` **dropped** `tax_total`,
  `shipping_total`, `refund_total`, `discount_total`, `coupon_code` on
  **17 Aug 2026**, with a census proving all five were empty across 803,256
  rows — they had been added by hand in Feb 2026 and never had a writer.
- `v0007_orders_money_columns.py` **restored all five with a writer** —
  `OrderSync` declares them and `process_orders_batch()` writes them. Committed
  **2026-08-18**.

So the cut-off is 18 Aug 2026. And it turns out not to matter, because:

```sql
SELECT count(*), count(*) FILTER (WHERE synced_at > '2026-08-18') FROM analytics_2.orders;
--  2847933 | 2847933
```

**Every row was synced after the writer shipped** — a full re-sync on 25–26
Aug moved 2.84M rows. There is no pre-writer population left to blame.

| on rows the writer processed | count |
|---|---:|
| `tax_total > 0` | **0** |
| `shipping_total > 0` | **0** |
| `discount_total > 0` | 146,582 |
| `coupon_code IS NOT NULL` | 146,658 |

The same writer, on the same rows, populated two sibling columns 146k times
and these two zero times. That is as close to proof as this gets: **the store
charges no tax and no shipping.**

**What it changes:** both rows come off the gap list. The gap list already
marked them "Not applicable to this tenant" on an arithmetic argument
(`total = SUM(order_items.total)` leaving no room for a tax term); this
replaces inference with a measurement. What remains true is that neither has
ever been *exercised*, so a tenant that does charge tax would be testing the
path in production.

## 3. `order_items.price` and `sku` — both entirely absent

```sql
SELECT count(*), count(price), count(sku) FROM analytics_2.order_items;
--  4488746 | 0 | 0
```

**Zero of 4.49 million rows carry either.** `specs/refund-hook.md` §D1
measured `sku` at 0/74 on a build that sends it; this is the same defect at
2,000× the scale, and `price` is in the same state.

**What it settles:** `api/analytics/services/order_query.py` computes
`implied_unit_price` as `total / quantity` and flags
`unit_price_is_implied`. That is not a fallback for occasional missing data —
**it is the only path that has ever run.** Every unit price DD has ever
displayed is a reconstruction, and it is post-line-discount, so it is not the
price anyone paid attention to at checkout.

**What it changes:** variation-level reporting (gap list row 25, "Rarely") and
anything keyed on SKU are not low-priority — **they are impossible** until the
connector sends the fields. The gap list ranked them by how often an agency
would want them; the correct ranking is that they are blocked, and the
unblocking work is in the plugin, not in DD. This is the row most misplaced by
the original list.

## 4. `product_categories` — populated, and a report would render

```sql
SELECT count(*), count(DISTINCT product_id), count(DISTINCT category)
  FROM analytics_2.product_categories;   -- 3951 | 1723 | 47
SELECT count(*) FROM analytics_2.products;             -- 3700
```

**3,951 rows, 47 distinct categories, covering 1,723 of 3,700 products (47%).**

**What it settles:** the gap list could not tell whether a category report
would render anything. It would. 47 categories is a usable axis, and the
average product carries 2.3 of them.

**What it changes:** "Product performance by category" was **Partial** on the
grounds that the data exists and no endpoint groups by it. That is now
confirmed rather than assumed, and the row rises: it is a report over
populated data with a nav slot already reserved
(`platform/components/layout/Sidebar.tsx`), not a data project. The 53% of
products with no category is the caveat — a category report silently omits
half the catalogue unless it says so.

## 5. `customers` — 195,397

**What it settles:** customer reports, cohorts, RFM segments and churn scoring
all have a real population to run against. The gap list marked several of
these "Has" from source alone and could not confirm they would render
anything.

**What it changes:** nothing in the ranking. It removes a caveat rather than
moving a row. What it does *not* settle is whether `churn_scores` and
`customer_segments` are themselves populated — those tables were not queried
and remain open.

---

## 6. The refund disagreement — not a conflict

```
status = 'refunded'                          1
refund_total > 0                             4
both                                         1
status='refunded' AND refund_total = 0       0
status<>'refunded' AND refund_total > 0      3
```

Every order carrying either signal, on tenant 2:

| wc_order_id | status | total | refund_total | created |
|---|---|---:|---:|---|
| 2323545 | cancelled | 0.10 | 0.10 | 2025-04-24 |
| 2323537 | cancelled | 0.10 | 0.10 | 2025-04-24 |
| 2323533 | cancelled | 0.79 | 0.79 | 2025-04-24 |
| 3570823 | refunded | 0.69 | 0.69 | 2026-08-16 |

The three extra rows are **cancelled orders that were refunded**. They never
carried the `refunded` status because WooCommerce's status reflects the
workflow that ended the order, not whether money went back. Tenant 1 shows the
identical 1-against-4 split, so this is the shape of the data and not an
accident of one store.

**A report should use `refund_total`, and the reason is not that it is the
bigger number.**

- It answers the question being asked. Net revenue is `gross − refunded`, an
  arithmetic fact about money. `status` is a workflow label, and a label is
  not an amount.
- It is complete where status is not. `status = 'refunded'` misses 3 of the 4
  refunds here — a 75% undercount — because a cancelled-and-refunded order and
  a partially-refunded order both keep a different status.
- **Status can never express a partial refund at all.** An order refunded by
  half stays `completed` in WooCommerce. Any refund report built on status is
  structurally incapable of the most common case.

Use `status` for one thing only: counting orders that ended in the refunded
*state*, when that is genuinely the question.

### The finding underneath it

```sql
SELECT count(*) FILTER (WHERE refund_total > 0 AND refund_total < total),  -- 0
       count(*) FILTER (WHERE refund_total > 0 AND refund_total = total)   -- 4
  FROM analytics_2.orders;
```

**Every refund in the database is a full refund. There is not one partial
refund in 2.85 million orders.**

`specs/refund-hook.md` left exactly one question open: whether the connector
hooks `woocommerce_order_refunded`, *"which decides whether partial refunds on
completed orders are captured"*. This is evidence on that question and it
points one way. Either this store has never issued a partial refund, or
**partial refunds are not being captured** — and the second is far more likely
for a store with 2.85M orders.

It also revises what `empty-columns.md` concluded. The near-empty
`refund_total` was traced to backfill coverage; that explanation is now spent,
because the 25–26 Aug re-sync put every historical row through the writer and
the three 2025 refunds came through it correctly. Four refunds in 2.85M orders
is not a backfill artefact. It is either the truth about this store or a
capture gap, and the partial-refund result is the thread to pull.

**What it changes:** "Net revenue (gross less refunds)" is ranked Daily and
Missing. That ranking holds, but the reason shifts — the blocker is no longer
"the column is empty because of a backfill", it is "we do not yet know whether
refunds are being captured at all". Settling that is a plugin question and it
is worth more than building the report, because a net-revenue report over
uncaptured refunds is a wrong number presented confidently.

---

## What remains open

- **Whether partial refunds are captured.** Needs the connector source, which
  is not in this repository. `specs/refund-hook.md` §"What would settle the
  question definitively" already sets out how.
- **Why 29.3% of orders carry an empty `utm_source`.** Connector-side.
- **`churn_scores`, `customer_segments`, `daily_metrics`, Meta spend rows.**
  Not queried here; still unmeasured.
- **Whether `customers.first_order_at` disagrees with the derived value**
  `api/analytics/services/analytics_engine.py` warns about. Needs a join this
  did not run.
- **Tenant 1** was checked only for the refund split. Every other figure here
  is tenant 2 alone, and the gap list's own caveat about generalising from one
  tenant still stands.
