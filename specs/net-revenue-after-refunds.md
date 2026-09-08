# Draft spec — net revenue after refunds on the revenue report and dashboard

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
title: Net revenue after refunds on the revenue report and dashboard
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
  - api/analytics/routes/dashboard.py
```

## Why this is a code change and not an investigation

`specs/metorik-gap.md` leads its Daily band with this row, and
`research/metorik-gap-2026-08-30.md` splits it into two: row 4 (the revenue
series is gross only) and row 14 (net revenue as the headline number). Row 14
is separated deliberately, and the separation is the whole argument for doing
this first — it is not a report DD lacks, it is the number on reports DD
already has being the wrong one.

Every layer beneath the aggregate is finished. `refund_total` is a column on
`AnalyticsOrder` (`api/analytics/models.py:87`), restored together with its
writer by `api/analytics/migrations/versions/v0007_orders_money_columns.py`,
written by the sync engine's upsert
(`api/analytics/services/sync_engine.py:511-518`), and returned per row by the
order list and order detail (`api/analytics/services/order_query.py:162,240`).
The verification cited on this candidate — no reference to `refund_total`
anywhere in `api/analytics/services/analytics_engine.py`, checked 2026-09-07 at
`7375d0a` — is the entire gap. So this is a report, in one service module, over
a column that already exists. There is nothing here to investigate that has not
already been investigated three times, in `specs/empty-columns.md`,
`specs/refund-hook.md` and `research/gap-list-open-questions.md`.

## What the contract can and cannot establish

`contracts/deadly-digital-platform-api.yaml` verifies with `compileall` and a
ruff-no-new-findings ratchet. **There is no test gate.** A passing run means
the changed files parse and introduce no new lint finding, and nothing more —
the contract says so itself, and the api suite carries roughly 81 pre-existing
failures on a clean database, so it cannot be turned on for this task.

That is a real constraint on how this change should be written, not a footnote.
The arithmetic has to be correct by construction and checkable by reading, in
one pass over rows the function already selects. A netting implemented as a
second query with its own date bounds, its own status predicate or its own join
would be exactly the kind of change this contract cannot catch when it drifts.
Do not write one.

## The three aggregates

Three call sites in `api/analytics/services/analytics_engine.py`, all of which
today sum `o.total` and stop:

1. `revenue_report()` — the per-bucket series behind
   `GET /api/analytics/revenue` (`api/analytics/routes/revenue.py:21`), at
   hour, day, week or month granularity. Gross sum at `:731`.
2. `revenue_summary()` — the summary a merchant actually reads, at `:816`.
   `research/metorik-gap-2026-08-30.md` names this line specifically as the
   headline number.
3. `dashboard_overview()` — the KPI block behind
   `GET /api/analytics/dashboard` (`api/analytics/routes/dashboard.py:19`),
   which also computes a preceding equal-length comparison window at `:451-455`.

Line numbers are as recorded in `research/metorik-gap-2026-08-30.md`, read at
fleet sha `73dc37fac0f57eb39b0bd6d5a82297d2b8034e46`. **Locate each function by
name, not by line** — the file has moved under these numbers before.

## What done means

### 1. Net is added beside gross. Gross does not change.

No existing key changes meaning or value. Every aggregate above gains, next to
its existing gross figure:

- a refunded amount — `SUM(o.refund_total)`
- a net figure — gross minus that refunded amount
- a count of orders in the bucket carrying `refund_total > 0`

Renaming the gross key, or netting it in place, would change the number under
every existing consumer without any of them asking. The frontend is protected
under this contract and cannot be updated in the same branch — see
[The frontend is out of scope](#the-frontend-is-out-of-scope-and-that-is-fine)
— so an in-place netting would ship a silently different number to
`platform/app/(dashboard)/analytics/revenue/page.tsx` and
`platform/app/(dashboard)/analytics/page.tsx` with no way to tell. Additive
keys are the only shape that is safe to merge without the frontend.

This is also the discipline the module already practises. Both order
populations — all-status and revenue-status — are named on every figure rather
than collapsed into one ambiguous number
(`api/analytics/services/analytics_engine.py:755-766`,
`api/analytics/services/order_query.py:185-197`). Gross and net are the same
kind of pair. Name both, always; never one unqualified.

### 2. Both sums run over exactly the same rows.

This is the correctness condition and the only one that is hard.

`SUM(o.refund_total)` must be computed in the same query, over the same date
bounds, the same revenue-status predicate and the same joins as the
`SUM(o.total)` it nets. Not a second query. Not a different status filter.

The reason is specific. Of the four refunded orders on tenant 2, **three sit on
`cancelled` orders** (`research/gap-list-open-questions.md` §6): WooCommerce's
status records the workflow that ended the order, not whether money went back.
If `cancelled` is outside the revenue-status predicate — read the predicate,
do not assume it — those three orders contribute no gross, and subtracting
their refunds would remove money that was never added. Same reasoning applies
to `refunded` itself: whatever that predicate does with a fully-refunded order,
doing the same thing to both terms is right under either answer.

Hold that invariant and every case falls out correctly:

- A partial refund on a `completed` order: the row is in the population, gross
  counts the full total, the refund subtracts the part. Correct.
- A full refund on an order the predicate excludes: neither term sees the row.
  Correct.
- A full refund on an order the predicate includes: both terms see it, net is
  zero for that order. Correct.

### 3. Use `refund_total`, never `status = 'refunded'`.

Settled in `research/gap-list-open-questions.md` §6 and not open for
re-litigation here. The two counts disagree — 1 by status against 4 by amount,
the identical split on both tenants — because they answer different questions.
Net revenue is `gross − refunded`, an arithmetic fact about money; `status` is
a workflow label, and a label is not an amount. Status misses 3 of the 4
refunds on tenant 2, and it is structurally incapable of expressing a partial
refund at all, since an order refunded by half stays `completed`.

### 4. The response must make an empty result legible.

The refunded amount and the refunded-order count are not decoration. They exist
so that a net figure equal to gross reads as *"no refunds are recorded in this
window"* rather than *"refunds were netted and came to nothing"*.

That distinction is doing real work right now. `analytics_2.orders` carries 4
orders with `refund_total > 0` out of 2,846,280, and every one of them is a
**full** refund — there is not one partial refund in 2.85 million orders
(`research/gap-list-open-questions.md` §6). Either this store has never issued
a partial refund, or partial refunds are not being captured, and the second is
far more likely at that scale. `specs/refund-hook.md` establishes that the
connector's refund hooks are registered and that a refund-driven backfill
exists as `wp dd sync-refunds` with no record of it ever having been run.

So a net figure shipped today will frequently equal gross. That is fine and
honest *if* the zero is visible. It is a wrong number presented confidently if
it is not. Returning the refunded amount and the refunded-order count in the
same payload is the cheapest thing that keeps it honest, and it is why they are
required rather than optional.

Record this in the docstrings of the functions you change, in the module's own
voice: a refunded total of zero over a window means no refund has been recorded
against those orders, which is not the same as no refund having occurred.

### 5. The dashboard comparison is computed on the same basis.

`dashboard_overview()` compares the window to the preceding equal-length window
(`:451-455`). If a net figure is added to the current window, the prior window
gets the same treatment from the same code path — a change-versus-prior
computed with net on one side and gross on the other is a fabricated movement.
Given four refunds in the whole table, the honest outcome on today's data is a
net change indistinguishable from the gross change, and that is the correct
outcome, not a sign the change did not work.

## What must not change

- **Gross.** Its key, its value, its status predicate. If the gross number
  moves at all, something is wrong with the change and not with the old code.
- **The revenue-status predicate**, wherever it lives. Read it, reuse it,
  leave it exactly as it is. Widening it to sweep in `cancelled` orders so that
  the other three refunds appear would be a change to what "revenue" means,
  smuggled in under a netting task.
- **`api/analytics/models.py`, `api/analytics/services/sync_engine.py`,
  `api/analytics/services/order_query.py`.** Storage, writer and per-row
  readers are all finished. None is writable in this branch and none needs to
  be.
- **Anything under `api/analytics/migrations/`.** Protected by the contract,
  and correctly: no migration is required for any part of this.
  `specs/empty-columns.md` is explicit — the columns exist, are mapped end to
  end, and are written by an upsert that a re-push overwrites.
- **The two route files, unless they would drop the new keys.** They are
  writable only because `GET /api/analytics/dashboard` returns a fixed shape
  (`api/analytics/routes/dashboard.py:38-40`) and a response model or an
  explicit key-picking there or in `api/analytics/routes/revenue.py` would
  silently discard everything this task adds. If the routes pass the engine's
  dicts through untouched, do not touch them. If they do not, the only
  permitted edit is admitting the new keys — plus the docstring line that says
  what net means. No other change to either route.
- **Import order, formatting, unrelated lint.** The api contract's ratchet
  exists precisely so a change need not arrive carrying an unrelated
  import-sort. `api/analytics/routes/revenue.py` already carries a pre-existing
  `I001`; leave it.

## The frontend is out of scope, and that is fine

`platform/**` is protected under `dd_api`, so nothing in this branch reaches
`platform/app/(dashboard)/analytics/revenue/page.tsx`,
`platform/app/(dashboard)/analytics/page.tsx`, or the proxy at
`platform/app/api/analytics/dashboard/route.ts`. The verification scope is the
backend and the writable scope matches it, which is the point of splitting the
two DD contracts at all.

The consequence, stated plainly so nobody reads a merged branch as a shipped
feature: **after this change the API returns net revenue and the product still
displays gross.** A follow-on task under `dd_frontend` surfaces it. That
sequencing is deliberate — the API is where the number is decided, it is where
the semantic-layer discipline lives, and a frontend task that had to invent the
netting in TypeScript would be the wrong place for it.

## How to check it, given the contract cannot

The contract runs `compileall` and the ruff ratchet. Beyond those, this change
is verified by reading, and a reviewer should be able to answer all five
without running anything:

1. Gross is untouched — same key, same expression, same predicate.
2. Every net figure is `gross − SUM(o.refund_total)` over the identical row
   set, in one query. No second query, no second date bound, no second status
   filter.
3. No aggregate reads `status = 'refunded'`.
4. Every response carrying a net figure also carries the refunded amount and
   the refunded-order count for the same population and the same window.
5. `dashboard_overview()`'s prior window is computed on the same basis as its
   current window.

## Sequencing note, not a blocker

`research/gap-list-open-questions.md` closes on the view that settling whether
partial refunds are captured is worth more than building this report, because a
net-revenue report over uncaptured refunds is a wrong number presented
confidently. That is right, and it is a plugin question — `specs/refund-hook.md`
§"What would settle the question definitively" sets out the two commands, on a
WordPress host this fleet does not reach.

It is not a blocker for this task, for one reason: the report specified above
cannot present a wrong number confidently. It never replaces gross, it always
names the refunded amount beside the net, and a window with no captured refunds
renders as gross with a visible zero. The capture question changes how much
refund there is to net, not whether the arithmetic is right. Running
`wp dd sync-refunds` and doing the hook check remain worth doing, and belong to
whoever has host access — they are cheap, and they are the thing that makes
this report interesting rather than merely correct.
