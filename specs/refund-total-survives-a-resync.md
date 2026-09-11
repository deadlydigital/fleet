# Draft spec — a re-sync must not erase a refund it was not told about

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
title: A re-sync must not erase a refund it was not told about
writable_paths:
  - api/analytics/services/sync_engine.py
  - api/analytics/services/analytics_engine.py
```

## The defect

`research/refund-coverage.md` (task 57, 2026-09-11) found this while answering a
different question and flagged it rather than fixing it. Verified against the
tree on the same day.

Two lines, and neither is wrong on its own:

`api/analytics/services/sync_engine.py:408` stores the field with a zero
default —

    "refund_total": _num(order_data.get("refund_total"), Decimal("0")),

and `_num` (`sync_engine.py:114-125`) returns that default for `None` **and**
for `""`. So a payload that omits `refund_total` entirely and an order that
genuinely had no refund produce the identical stored value, `0.00`.

`api/analytics/services/sync_engine.py:512-541` then upserts with

    ON CONFLICT (wc_order_id) DO UPDATE SET
      ...
      refund_total = EXCLUDED.refund_total,

with no guard. Overwriting is *correct* for the case this was written for — a
refund arrives on an order already stored, and the new value must win. It runs
the other way too: **a re-sync whose payload omits the field writes `0.00` over
a refund that was previously captured.** Any full re-sync from a build without
the refund hooks silently erases refund history, and because the column cannot
represent "not reported", nothing afterwards can tell that it happened.

The comment three lines above the writer already states the principle this
misses:

> `coupon_code` stays NULL because "not reported" and "no coupon" are different
> facts.

`specs/empty-columns.md:42-48` named the same flaw on 2026-08-28 for the four
money columns and it has not been acted on.

**This is a defect regardless of current coverage.** On 2026-09-11 the
reconciliation manifests agree with the platform's stored refund totals in all
54 covered periods across both tenants, so nothing is known to have been lost
yet. That is the reason to fix it now rather than the reason not to: the loss
would be silent and unrecoverable, and the next full re-sync is the event that
causes it.

## What to change

**1.1 A re-sync must not erase a captured refund.** When the incoming payload
did not carry the field, an existing row's `refund_total` stands. The upsert
set-list keeps
`refund_total = EXCLUDED.refund_total` for the case where a refund arrives, and
must not apply it where the incoming value is the `_num` default standing in for
an absent field. `GREATEST(orders.refund_total, EXCLUDED.refund_total)` is the
smallest change that achieves it and is acceptable; so is threading a sentinel
through `_num` so absence is distinguishable from zero. A genuine reduction of a
refund — a reversal — is out of scope and is named in 1.3.

**1.2 A new test bites on the erasure.** Under
`api/tests/analytics/test_fleet_*.py`, which the contract's `creatable_paths`
permits. It must fail against the code as it stands: sync an order carrying a
refund, re-sync the same `wc_order_id` with the field absent from the payload,
and assert the stored `refund_total` is unchanged. A test that only exercises
the happy path does not bite and the contract's `new_test_bites.sh` will say so.

**1.3 Say in the code what the guard does not cover.** Whatever mechanism 1.1
uses, a comment must state that a refund being *reduced or reversed* upstream is
not propagated by it, so the next reader does not take the guard for more than
it is. Do not build reversal handling here.

## The docstring correction, which travels with this

**2.1 Correct the off-by-one at `api/analytics/services/analytics_engine.py:961-964`.**
It reads:

> three of the four refunds on the second live tenant sit on `cancelled` orders,
> outside the revenue-status filter, so neither term sees them

which implies the fourth *is* seen. It is not: the fourth is `status =
'refunded'`, equally outside `_REVENUE_STATUSES` (`analytics_engine.py:32`,
the literal `('completed','processing')`). All four are excluded. The
arithmetic the passage defends is unaffected and must not be changed — netting
a refund against gross its order never contributed to would remove money that
was never added. Only the account of why is wrong.

Confirmed independently on 2026-09-11 from the tenant's own reconciliation
manifests: across all 29 manifests for `analytics_2`, the store reports
`completed` = 63,871 orders with `refund_total` 0.00 and `refunded` = 1 order
with 0.69. No refund the store reports sits on a revenue-status order.

Two constraints on 2.1 that are not separate requirements, because neither
produces a line to cite. The numbers in that docstring are prior readings: if a
count is quoted it carries the date it was taken. And `specs/metorik-gap.md:82`
is wrong in the other direction — it quotes "1 of 2,844,177", which is
`status = 'refunded'`, against a sentence about `refund_total > 0`, where the
count is 4 — but it is not editable from this task, because `specs/**` is on
the fleet floor. Do not attempt it.

## What a human checks

That the new test fails before the change and passes after. The contract runs
`compileall`, `ruff_no_new_findings.py`, per-file pytest and `new_test_bites.sh`;
none of them knows what a refund is. `auto_merge` is `true` on this contract, so
absent a person looking, those four checks are the whole review.
