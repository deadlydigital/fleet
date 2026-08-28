# Why `tax_total`, `shipping_total` and `refund_total` are empty

Investigated 2026-08-28, read-only, against `~/deadly-digital-platform` and the
production `deadly_digital` database. Raised by `specs/metorik-gap.md`, which
flagged three columns that exist and carry no data and could not say why.

**The three columns do not have the same answer.**

| Column | Verdict | Confidence |
|---|---|---|
| `tax_total` | The tenant genuinely has none. The zeros are correct. | High — two independent proofs |
| `shipping_total` | The tenant genuinely has none. The zeros are correct. | High — same two proofs |
| `refund_total` | **None of the three candidate causes.** The pipeline works and the store almost certainly has refunds; the history is a *backfill coverage* artefact. | Medium — inference, one check would settle it |

**Cost answer: a day of work, not a schema-and-backfill project.** No migration
is needed for any of the three. Detail in the last section.

---

## The three candidates, tested

### Candidate 2 — "`sync_engine.py` isn't mapping them" — ruled out, definitively

The field survives every stage:

| Stage | Where | What happens |
|---|---|---|
| Wire → model | `api/app.py:2636-2639` | `OrderSync` declares `refund_total`, `discount_total`, `shipping_total`, `tax_total` as `Optional[float] = None`. |
| Model → hook payload | `api/app.py:6037` | `analytics_payload = {"orders": [o.model_dump(mode="json") …]}`. Declared fields survive `model_dump`. |
| Hook → batch | `sync_engine.py:1114-1134` | `analytics_sync_hook(..., "orders", …)` passes the dicts straight to `process_orders_batch`. |
| Batch → row | `sync_engine.py:408-411` | `"tax_total": _num(order_data.get("tax_total"), Decimal("0"))`, and the same for the other three. |
| Row → table | `sync_engine.py:512-541` | All four are in the INSERT column list, the `CAST(:… AS numeric[])` unnest, and the `ON CONFLICT DO UPDATE` set-list — so a later re-push overwrites, which is what a refund needs. |

There is a documented precedent for exactly this failure, and it is instructive
because it does **not** match what we see. `app.py:2624-2627` records that
`payment_method` "was never declared — so `model_dump()` stripped it and the
column was NULL on every row ever synced." A field stripped by the model lands
**NULL**. `tax_total` is **0.00**, not NULL, because `_num()` defaults it. The
signature is different, and the fix that closed the `payment_method` bug is
already applied to all four money fields.

> **The design flaw this investigation exists because of.** `_num(…, Decimal("0"))`
> collapses "the connector did not report this" and "the connector reported
> zero" into the same stored value. The same code block deliberately preserves
> that distinction one line later — `coupon_code` is left NULL with the comment
> *"'not reported' and 'no coupon' are different facts"* — and does not do it for
> the four money columns. Had they been nullable with a NULL default, this
> document would have been one query. Recommended, not done: this was read-only.

### Candidate 1 — "the Woo connector isn't sending them" — ruled out for tax and shipping

`discount_total` and `coupon_code` travel in the **same payload block, through
the same model, through the same code path** as `tax_total` and `shipping_total`.
They arrive. The others do not:

```
   month    | orders | w_discount | w_coupon | w_tax | w_ship | w_paymethod
------------+--------+------------+----------+-------+--------+------------
 2026-01-01 |  76325 |       1305 |     1306 |     0 |      0 |      76063
 2026-04-01 |  61770 |       2744 |     2747 |     0 |      0 |      61490
 2026-07-01 |  70018 |       8993 |     9003 |     0 |      0 |      67690
 2026-08-01 |  66359 |      10220 |    10216 |     0 |      0 |      62196
```

And the block is not a recent plugin upgrade — it has been arriving since the
first order in the table:

```
 first_order | first_discount | first_coupon | first_paymethod | first_country | first_utm
-------------+----------------+--------------+-----------------+---------------+-----------
 2023-03-12  | 2023-03-15     | 2023-03-15   | 2023-03-12      | 2023-03-12    | 2023-03-12
```

A connector that sends `discount_total` and `coupon_code` on the same order,
from day one, is sending the money block. It reports no tax and no shipping
because there is none.

### Candidate 3 — "the tenant genuinely has none" — confirmed for tax and shipping

`docs/CONNECTOR-V3-SPEC.md:185` states the identity the payload must satisfy:

```
total == subtotal + tax + shipping - discount
```

Measured over 2,843,780 revenue-status orders that have line items:

* **`total == SUM(order_items.total)` holds to the penny on 2,831,826 of them — 99.58%.**
* Split by discount, the line items turn out to arrive *already net of discount*:
  of 145,996 discounted orders, **145,504 satisfy `total == items_total`** and
  only **13** satisfy `total == items_total − discount_total`. So this store's
  true identity is `total = items_total`, with no tax term and no shipping term
  in it at all.
* The 0.42% that miss are off by **negative pennies** — the largest buckets are
  −0.09 (743 orders), −0.24 (711), −0.49 (685), −0.04 (643), −0.14 (455). Items
  slightly *exceed* the total, which is rounding on per-line discount
  apportionment. Shipping would be a **positive** residual clustered on a few
  round values (£3.95, £4.95). There is no positive cluster anywhere.

If this store charged £4.95 shipping or 20% VAT, `total` would exceed
`items_total` by that amount on essentially every one of 2.84M orders across
three and a half years. It does not.

**Verdict: `tax_total` and `shipping_total` are correctly zero. There is nothing
to fix, and `specs/metorik-gap.md` should be corrected** — it lists both as
"Missing in effect", which reads as a DD defect and is not one. They are
untested rather than broken: no tenant in the database charges either, so the
path has never been exercised, and the first tenant that does will be the test.

---

## Refunds: none of the three candidates is the answer

The pipeline is fine, and the store almost certainly does have refunds.

**The pipeline works.** There is exactly one order with status `refunded` in
2,844,177 — `wc_order_id` 3570823, 2026-08-16, `total` 0.69 — and it carries
`refund_total` 0.69. Status-level refund capture is **1 of 1**.

**One refund is not credible for this store.** 2,843,809 revenue-status orders,
£23,412,312 gross, AOV £8.23, median order £5.00, over 41 months. One refund is
a rate of 0.00004%. Published retail refund rates run 1-10%; even 0.1% would be
~2,800 refunds. A sub-£10 median makes a genuinely low rate plausible — nobody
returns a £5 item — but not a rate three orders of magnitude below the floor.

**The history is a backfill coverage artefact, and the status mix proves it.**
Non-completed statuses appear only in the last two weeks of a 41-month table:

```
    day     | completed | cancelled | pending | refunded
------------+-----------+-----------+---------+----------
 2026-08-16 |      5064 |         0 |       0 |        1
 2026-08-20 |       888 |         0 |       0 |        0
 2026-08-21 |      3201 |         1 |       0 |        0
 2026-08-25 |      1132 |        29 |       0 |        0
 2026-08-26 |      1990 |        75 |       8 |        0
 2026-08-28 |      2651 |        85 |      13 |        0
```

Whole-table first-and-last dates per status tell the same story: `cancelled`
exists only from 2026-08-21, `pending` only from 2026-08-26, `processing` only
between 2025-01-21 and 2025-02-14. A store does not go from zero
cancellations in three years to 85 a day. Something in the ingestion path
started carrying non-completed orders around 2026-08-21 — near the 2026-08-18
rebuild that the fleet detection layer's README already records as the cause of
its own gap. Before that, the analytics table was effectively completed-orders-only,
and a refunded order was not in it to carry a `refund_total`.

`CONNECTOR-V3-SPEC.md` independently predicts this outcome. Lines 219-226:
*"Recommended: omit `refund_total` during historical backfill, then do one
refund-driven pass"* — because `get_total_refunded()` is the one field in the
block that costs a query per order. **The historical zeros are what the spec
asked for.** The refund-driven pass it prescribes appears never to have run;
nothing in the repo implements one.

**What remains genuinely unknown: partial refunds.** A WooCommerce partial
refund does *not* change order status — a `completed` order can carry one, and
it would be invisible to every check above. `CONNECTOR-V3-SPEC.md:191-202` is
explicit that refunds are separate `WC_Order_Refund` objects created later and
that *"a refund will be missed unless you re-push the order"*, prescribing
`woocommerce_order_refunded` and `woocommerce_refund_created` hooks. Whether the
deployed plugin has them cannot be answered from this repo — **there is no PHP
anywhere in it**; the connector ships separately.

---

## What I could not check

* **`public.orders` does not hold these fields.** It has 15 columns —
  `id, tenant_id, customer_id, woo_order_id, customer_email, status, total,
  currency, billing_first_name, billing_last_name, billing_phone, items_count,
  order_date, created_at, synced_at`. No tax, shipping, refund, discount or
  coupon column exists. The analytics schema is *richer* than public here, so
  public cannot corroborate or contradict anything above.
* **The legacy phpstack database is not reachable.** The cluster holds
  `deadly_digital, fleet, listmonk, postgres, rdsadmin, yessms` and no phpstack.
  It is a system DD is migrating reports *from*, and both `api/CLAUDE.md:930`
  and `docs/REPORT-MIGRATION-PLAN.md:196` state plainly that **no phpstack
  fixture exists**. This leg of the investigation cannot be completed by anyone
  from these machines.
* **The raw wire payload.** `sync_jobs.payload` stores replay records, but the
  only `analytics_replay` row for tenant 2 holds **0 orders**, and the 30
  `analytics_backfill` rows hold parameters (`source, trigger, metric_rows,
  queue_depth, stale_dates`), not order data. Nothing on the box preserves a
  connector payload as received.
* **The connector source.** Not in this repo. Confirming the refund hooks needs
  the plugin, or a test refund on the live store.
* **Tenant 1.** Every figure here is tenant 2 (`analytics_2`). `analytics_1`
  exists and was not measured.

---

## Cost: a day, not a project

**Not a schema-and-backfill project.** All three columns already exist, are
already mapped end to end, and are already written by an upsert that a re-push
overwrites. No migration is required.

| Work | Estimate | Notes |
|---|---|---|
| Correct `specs/metorik-gap.md` for tax and shipping | minutes | They are correct data, not gaps. |
| Establish whether the connector hooks refund events | 1-2 h | Needs the plugin source or one test refund on the live store. **Do this first** — it decides the next row. |
| Net-revenue-after-refunds in the revenue report and dashboard | ~0.5 day | Column exists and is trustworthy for anything the pipeline has seen since ~2026-08-21. `revenue_report()` and `dashboard_overview()` each gain a netted figure beside the gross one; the semantic-layer discipline already in those functions says both must be named, never one unqualified. |
| *If* the hooks are missing: add them, plus one refund-driven backfill pass | ~1 day | `CONNECTOR-V3-SPEC.md:226-231` already designs the pass — walk the refunds, not the orders, so it is O(refunds) and portable across HPOS and legacy post storage. |
| **Total** | **0.5-2 days** | Worst case assumes the hooks are missing. |

Two things worth doing at the same time, neither of them required:

* **Make the four money columns nullable with a NULL default.** It is the
  distinction `coupon_code` already keeps, it is the reason this took a day to
  answer instead of a query, and it is a migration on an empty-valued column.
* **Do not report a net-revenue figure over pre-2026-08-21 data without saying
  so.** Netting refunds across a period the pipeline was not carrying refunded
  orders in produces a number that is *exactly* gross and looks netted. That is
  the failure mode `SEMANTIC-LAYER.md` exists to prevent, and it is worse than
  showing gross alone.

---

Figures dated 2026-08-28, tenant 2. Re-run them rather than quoting them.
