# Draft spec — show net revenue after refunds beside gross on the analytics overview

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
contract: dd-analytics-frontend.yaml
title: Show net revenue after refunds beside gross on the analytics overview
writable_paths:
  - platform/app/(dashboard)/analytics/page.tsx
```

## What is already true, read from the tree rather than from the gap list

The API half shipped. `api/analytics/services/analytics_engine.py` computes
`refunded_amount`, `net_revenue` and `orders_with_refund` in the one query that
already produces gross `revenue` (lines 298–305), over the identical rows, with
the identical `status IN ('completed','processing')` filter, and returns all
three in the dict at lines 326–328. `dashboard_overview` puts that dict on the
response as `period` (line 755), emits a matching `trends.net_revenue` computed
net-against-net from the same code path (lines 626–629), and carries the same
three keys per day inside `trends_data` (lines 728–747).

`platform/app/api/analytics/dashboard/route.ts` forwards five query parameters
and returns the API's body through `NextResponse.json(data, …)` without
touching it (line 44). So all three figures already reach the browser on every
load of the overview page.

`platform/app/(dashboard)/analytics/page.tsx` throws them away. Its
`DashboardData` interface (lines 26–103) names `revenue`, the two order counts,
the two customer counts, `new_customers`, `returning_customers` and `aov`, and
neither `net_revenue` nor `refunded_amount` nor `orders_with_refund`; `trends`
names four keys and not the fifth. The string `refund` does not occur anywhere
in the file, in any case.

**This is one file. No proxy change, no query, no new parameter.** The page
sends nothing it does not already send, so
`contracts/checks/proxy_passthrough.py` — which compares the parameters the page
sends against the ones the proxy forwards, for this exact page/proxy pair — has
nothing new to compare and stays green without being touched.

## The whole difficulty is trust, and it is not a matter of taste

`net_revenue == revenue` is the common case on this data, and on the second live
tenant it is that way *by construction*:
`research/refund-coverage.md` establishes that every refund it has a status for
on that tenant sits on `cancelled` or `refunded`, none of which is in the
revenue-status filter both terms carry. So a net figure rendered alone, equal to
gross, says nothing that gross did not already say — and a merchant reads it as
the strong claim "refunds netted to nothing" when the only supportable claim is
"no refund is recorded against these orders".

The engine's own docstring makes exactly that distinction (lines 254–257 and
520–522) and ships `refunded_amount` and `orders_with_refund` *because of it*.
A page that renders the net number without the count collapses the distinction
the engine went to the trouble of preserving, which is worse than the missing
figure it replaces: `principles.md` ranks a wrong number above a missing one.

Hence the shape of requirements 2, 3 and 4 below. Net goes **beside** gross and
beside the other two keys, never instead of gross, and never alone.

### A deliberate departure from `research/refund-coverage.md` §3.2

That document pre-wrote the tile copy for whoever built this, and requirement
3.1 below does not use its wording. Its zero-refund label was *"Net revenue — no
refunds recorded in this window"*. Its own later finding — the tenant-2 section,
and the note that the engine docstring is off by one about which refunds the
filter excludes — is what makes that sentence false on the tenant it was written
about: refunds **are** recorded in those windows, on orders the revenue
population excludes. The sentence this spec requires is scoped to the population
rather than to the window, and it is the engine's own: *no refund is recorded
against the orders counted here*.

## 1. Read the three keys, and read them as optional

Add `net_revenue`, `refunded_amount` and `orders_with_refund` to
`DashboardData['period']`, and `net_revenue` to `DashboardData['trends']`, as
optional fields — `net_revenue?: number`, `trends.net_revenue?: number | null`.

Optional is not hedging, for the reason the `comparison` block one interface
above already gives about itself: the two shipped fixtures
`platform/__tests__/fixtures/analytics/overview-silent-feed.json` and
`platform/__tests__/fixtures/analytics/overview-window-before-gap.json` were
captured before these keys existed and contain none of them. `platform/__tests__/**`
is protected by this contract, so neither may be edited or re-captured, and a
required field would make requirement 4's branch unreachable rather than merely
unused.

The names are the API's. Do not alias them on the way in — `page.tsx:42–45`
records what the last rename on this interface cost, and the net figure is not
where to re-learn it.

## 2. Net beside gross, and gross untouched

The four existing `StatCard`s (`page.tsx:420–461`) do not change. `Total
Revenue` goes on rendering `period.revenue`, gross, with `trendOf('revenue')`,
in the first position. Nothing about the existing grid moves.

Directly beneath that grid and above the two charts, render a net-revenue block
carrying **all three figures together**: the net amount, the refunded amount and
the count of orders with a refund. Use `Card`/`CardContent`, already imported at
`page.tsx:18`.

**Not a fifth `StatCard`, and the reason is a boundary rather than a
preference.** `platform/components/ui/stat-card.tsx` has no slot for a companion
figure or a qualifying sentence — its props are `label`, `value`, `icon`,
`iconColor`, `iconBg`, `trend`, `className`, `loading` and nothing else — and
`contracts/dd-analytics-frontend.yaml` does not make it writable: it names four
components under `platform/components/analytics/` and excludes
`platform/components/ui/**` explicitly, because the ten analytics render tests
cannot show what a change there did to the campaigns, subscribers and billing
pages. Cramming the qualifier into the `label` string, the one thing that would
fit, is how the count gets dropped by the next person who shortens a label.

The net amount is `period.net_revenue` **as received**. The page must not
compute `revenue - refunded_amount` itself: a second lineage for a figure the
API already decided is the defect `page.tsx:317–325` and the revenue page's four
AOVs are the standing record of.

## 3. The count and the amount are part of the figure, not decoration

One sentence renders inside the same block as the net amount, on every path that
renders it at all, chosen on `orders_with_refund`.

**3.1 When `orders_with_refund === 0`, the sentence names the population.** The
exact string is `No refund is recorded against the orders counted here.` — not
"no refunds in this window", for the
reason set out above; not the bare label "Net revenue"; and not a suppression of
the block, because "we looked and found none" is a fact worth showing and is the
common case. The refunded amount still renders as £0.00 beside it — the reader
is being shown the evidence for the sentence, not asked to take it.

**3.2 When `orders_with_refund > 0`, the sentence names both figures**, in the
form `£{refunded_amount} refunded across {n} orders` — singular `order` at
`n === 1`. Currency formatting follows the existing cards: `£` and
`toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })`.

Neither figure may be rendered by a path that can omit the other. The
correctness condition is structural: there must be no branch in the finished
file that renders `net_revenue` without `orders_with_refund` beside it.

## 4. Absent keys render nothing, because absent is not zero

If any of `period.net_revenue`, `period.refunded_amount` or
`period.orders_with_refund` is `undefined` or `null`, render **no net block at
all** — no heading, no £0.00, no sentence.

This is the same distinction the API cannot make in its own storage and the
page therefore must: `research/refund-coverage.md` records that
`refund_total` has no state meaning "not reported", so a column default and a
genuine zero are indistinguishable at rest. Here they are distinguishable — a
key the response did not send is not a refunded amount of zero — and rendering
"£0.00 refunded" over a payload that said nothing about refunds is the invented
number this whole thread is about. It is also what keeps the 319 existing tests
honest rather than merely passing: both shipped fixtures take this branch, and
they must go on rendering exactly what they render today.

## 5. The net trend is net against net, or it is absent

If the net block shows a trend, it comes from `trends.net_revenue` and from
nowhere else. `trends.revenue` is gross on both sides and must never be borrowed
for it. `null` or `undefined` renders no trend at all, exactly as `trendOf`
already does for the four existing cards (`page.tsx:346–349`) — and `null` is
the deliberate output of the API's suppression path when the feed is silent over
the window, so a trend appearing here on a suppressed payload is a regression in
`page.tsx:164–187`'s guarantee, not a new feature.

A trend is optional for this block. If it is omitted, omit it in both cases
rather than showing it only when it is flattering.

## 6. One test, and it must bite

Create `platform/__tests__/unit/analytics/test_fleet_net_revenue.test.tsx` —
that name matches the single `creatable_paths` glob in
`contracts/dd-analytics-frontend.yaml`, and `.test.tsx` rather than `.tsx` is
what `vitest.config.ts` collects. No existing test file may be edited, and no
new fixture may be added, so the three payloads below are built inline in the
test file. Follow the MSW pattern in
`platform/__tests__/unit/analytics/overview.render.test.tsx`: `server.use` an
`http.get('*/api/analytics/dashboard', …)` and render the default export of
`platform/app/(dashboard)/analytics/page.tsx`.

Three cases, which are requirements 3.1, 3.2 and 4 read back:

* a payload with `orders_with_refund > 0` and `net_revenue < revenue` renders
  the net amount **and** the `… refunded across N orders` sentence, and `Total
  Revenue` still renders the gross figure unchanged;
* a payload with `orders_with_refund === 0` and `net_revenue === revenue`
  renders the exact sentence from 3.1 — asserted as the full string, not a
  substring, for the reason the sibling test file gives at its line 60;
* a payload shaped like the shipped fixtures, with none of the three keys,
  renders nothing about refunds at all — `queryByText(/refund/i)` is null.

The middle case is the one that makes this file worth writing: it is the only
one that fails against a page which renders a bare net number, and a bare net
number is the outcome this spec exists to prevent.
`contracts/checks/new_test_bites.sh` proves the file discriminates between the
two trees; it cannot prove it discriminates on *that*, which is why the case is
named here.

## How this is checked, and what the checks cannot say

`contracts/dd-analytics-frontend.yaml` runs, in order:
`contracts/checks/spec_requirements_cited.py` (every numbered requirement above
must be cited as `spec:1` … `spec:6` on a line the diff adds), `tsc --noEmit`,
the full 21-file vitest run, `contracts/checks/new_test_bites.sh` against the
new file, and `contracts/checks/proxy_passthrough.py`.

`auto_merge` is `true` on this contract, so unless someone opens the task page,
nothing compares this document to the diff after the citation check. The
contract's own header says what that costs and names task 53, which shipped a
requirement unbuilt with every gate green. The requirement most likely to be
lost that way here is 3.1: a diff that renders the net figure, passes tsc,
passes the suite and adds a biting test can still have dropped the sentence.

## Before this is queued

`research/refund-coverage.md` opens with a **no-go** — *"do not surface net
revenue until a host check has run"* — and that verdict has not been withdrawn.
It rests on two things: the coverage date it could not produce (its evidence
pack never ran), and the impossibility of distinguishing "this store has almost
no refunds" from "this build never sent the field" from inside the database.

This spec is written to be buildable under that verdict rather than in defiance
of it, and whoever queues it is making the call, so here is what is actually
being decided. The no-go was about a *tile that makes a claim about refund
capture*. Requirements 3 and 4 build a surface that makes no such claim: it
reports the three numbers the API returned and says, in words, that no refund is
recorded against the orders counted — which is true whether the cause is a store
with no refunds or a connector that never sent the field. What it does **not**
carry is §3.2's third caveat, *"Refund capture before <date> is unverified"*,
because no date exists to put in it. If the person queueing this thinks the
surface needs that sentence to be honest, this task waits on the host check in
`specs/refund-hook.md`; if they think the population-scoped wording carries the
uncertainty adequately, it does not.

## Out of scope

* **A net series on the revenue chart.** `trends_data` carries the three keys
  per day and a second line is a real follow-up, but it is a different
  legibility problem — a net line indistinguishable from the gross line is the
  chart's version of the collapsed sentence — and it belongs in its own spec.
* **`platform/app/(dashboard)/analytics/revenue/page.tsx`.** `revenue_report`
  and `revenue_summary` return the same three keys and that page shows none of
  them. Same argument, different file, different task.
* **Anything in `api/`.** The engine half merged and this contract protects
  `api/**` outright. `research/refund-coverage.md` flags two genuine API defects
  — the docstring at `api/analytics/services/analytics_engine.py:961–964` being
  off by one about the fourth tenant-2 refund, and the unguarded
  `refund_total = EXCLUDED.refund_total` in the upsert at
  `api/analytics/services/sync_engine.py:512–541` that lets a re-sync erase
  refund history. Both are `dd_api` work with their own specs.
* **Editing either shipped fixture, or re-capturing them.** Protected, and
  requirement 4 is written so that nothing needs it.
