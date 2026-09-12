# Parked: three connector defects on the HIB store

**Parked 12 September 2026.** All three live in the Deadly Digital connector
plugin on the HIB Cloudways box, version 2.5.0. None can be diagnosed or fixed
from the platform side — every one of them needs the plugin source.

Where the plugin lives:
`/home/master/applications/fwztgnsurb/public_html/wp-content/plugins/deadly-digital-connector/`

WP-CLI must be run from `public_html`, not from inside the plugin directory —
it cannot bootstrap WordPress from there on this host.

---

## 1. Transition pushes are lost, about 0.2% of them

**Still happening.** Five more appeared on 12 September.

On 25 August the connector changed from pushing each order once on completion
to pushing on creation and again on every status transition. Since then a small
fraction of the transition pushes never arrive. The platform holds the creation
push, so the order is present with status `pending` and `updated_at` never set,
while the source has it `completed`. Being outside the counted population, both
the order and its money are invisible to the dashboard.

77 such orders were repaired by hand on 12 September with `wp dd sync-order`,
recovering roughly £940 of revenue that was not showing.

**What it is not**, all tested from the platform side and ruled out:

- Not an outage — in the ten minutes after each stuck order, ingest wrote
  between 9 and 147 other rows.
- Not the rate limit — stuck orders occur in minutes averaging 12 pushes
  against a 100/minute ceiling.
- Not batching — median create-to-transition lag is 20 seconds; it is
  event-driven.
- Not timing — in the same minutes as the stuck orders, 623 other orders were
  healthy. It is per-order.
- Not platform rejection — every `/api/sync/orders` call in the logged window
  returned 200.

**What it is: per-order and strongly gateway-skewed.** Controlling for time
completely, within the same minutes:

| gateway | orders | stuck | rate |
|---|---|---|---|
| angelleye_ppcp | 114 | 49 | 43% |
| cashflows_card | 594 | 32 | 5.4% |

Across all orders since 26 August: PayPal 1.17%, card 0.085%, hib_wallet 0 of
294, blank 0 of 1,238. An 8 to 14 times difference by gateway.

That points at completion paths running outside a normal front-end request — a
PayPal webhook or return handler, where a hook registered on a frontend-only
bootstrap would not fire. **But card orders are affected too, at a lower rate,
so it is not only that path.** That last step could not be closed without the
source.

---

## 2. Eleven orders were never sent at all

Distinct from the above and worth keeping separate. The stuck orders arrived
and then stopped being mentioned — present but wrong. These were never
mentioned: absent.

Across 25 Aug (4), 27 Aug (1), 2 Sep (4), 6 Sep (2) and 9 Sep (1). The platform
has no record of them, which means **nothing on the platform side can detect
this class at all** — the `STUCK_ORDER_TRANSITION` invariant built on
12 September will never see them.

Establishing that they are genuinely absent, rather than part of the known 2023
rebuild gap, needed an id-range test rather than a date-window one. See the
note in §5 about `public.orders.created_at`.

---

## 3. The descent responder does not exist

`GET /api/sync/manifest/status` now returns a `descent.wanted` array naming the
periods where the two sides disagree. Each entry asks for a POST of
`wc_order_id` values to `/api/sync/manifest/order-ids`, and some carry
`status: too_large` with a `halve_into` pair when the day exceeds the 5,000-id
cap.

**Nothing in the plugin reads it.** `wp dd` offers exactly three commands:
`manifest`, `sync-order`, `sync-refunds`. `wp dd manifest` sends a manifest,
sees it already acknowledged, and stops.

So the platform is asking ten questions and the store has no way to answer.

This is the same shape as the manifest gate being switched off for a week: the
platform half was built, merged and deployed, and nothing on the store could
use it. Nobody knew until the descent started asking.

**Without this, the eleven missing orders cannot be named** — only counted.

---

## What the platform side already does

All of this is live and needs nothing further:

- `analytics_2` migrated to 0013 on 12 September, so level 3 is available and
  the descent is asking.
- The reconciliation compares order count, gross, refund total and per-status
  figures per period, and reports a residual.
- `STUCK_ORDER_TRANSITION` is a live invariant on
  `dd_analytics_reconciliation` — `updated_at IS NULL` and a status outside the
  counted population, older than the settle lag. It found all 77 without a
  manifest and would have fired on 26 August.
- `descent_plan`'s early return now carries a reason naming migration 0013,
  rather than being silent.

---

## Open questions this does not answer

**The residual money on count-matching days.** After the resync, four days have
*more* money on the platform than at source — 29 Aug £33.53, 3 Sep £10.63,
5 Sep £9.40, 8 Sep £12.00 — and one has less, 30 Aug −£5.00. Both sides hold
the same order ids on those days, so the descent would come back empty and the
difference would stay unattributed. `identity_diff` compares set membership
only; **there is no level of the descent that compares per-order values.** That
is a design gap, deliberately deferred, and it is now the whole of what remains
on four of the ten discrepant days.

**A resting status is not a safe exclusion.** The `STUCK_ORDER_TRANSITION`
predicate excludes `cancelled` on the reasoning that it is a status an order
rests in. One order on 2 September is `cancelled` on the platform, never
updated, and completed at source — so the exclusion is wrong at least once.
Ten other never-updated cancelled orders, on 20/22/23/24 August, sit on days
that reconcile clean, so those really are cancelled. The predicate needs a
better rule than "resting status".

---

## Two findings recorded elsewhere that bear on this

**`public.orders.created_at` is the rebuild's write timestamp, not the order
date — for 2,880,483 rows.** Order 606438 reads 2026-08-26 15:20:05 in
`public.orders` and 2023-03-12 10:31:40 in `analytics_2.orders`. Any date-window
query against `public.orders` is measuring when the row was written, not when
the order was placed. This wasted time during the diagnosis and will waste more.

**The 20 days that reconcile exactly all predate 25 August**, when the connector
pushed once on completion. Under that design a lost transition was impossible —
there was only ever one push and it carried the final state. The new design is
strictly better for freshness and strictly worse for completeness. Manifests
only begin on 7 August, so there are 18 clean days of the old behaviour to
compare against, which is thin evidence for "it used to be fine".

---

## The prompt to start with

> **TASK: two connector defects and one missing capability. Diagnose before
> changing anything.**
>
> [paste §1, §2 and §3 above]
>
> Read the source and report on all three before proposing a fix. For 1 and 2,
> name the mechanism with file and line rather than describing the symptom —
> reasoning behaviourally about this connector has produced wrong findings
> twice.
>
> Do not deploy. This is a live store.
