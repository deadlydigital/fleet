# Put the per-campaign source timeline in front of somebody

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
contract: dd-analytics-frontend.yaml
title: Render the per-campaign source timeline on the sources page
writable_paths:
  - platform/app/(dashboard)/analytics/sources/page.tsx
```

## What is wrong

`GET /api/analytics/sources/timeline-by-campaign` is declared in
`api/analytics/routes/sources.py` and returns a daily per-campaign breakdown —
`{periods, campaigns: {name: [{period, customers, orders, revenue, ad_spend,
cpa}]}}`. A Next.js proxy for it exists at
`platform/app/api/analytics/sources/timeline-by-campaign/route.ts` and forwards
the window. The sources page fetches `/api/analytics/sources`,
`/sources/insights`, `/sources/timeline` and `/sources/budget/...`, and never
this one: the string `timeline-by-campaign` appears zero times in its 1,194
lines.

So the capability is built, deployed and proxied, the door is cut, and no page
walks through it. This is FEAT-035 in its purest form — the same shape
`drafts/render-the-coupon-block-on-the-revenue-page.md` and
`drafts/net-revenue-on-the-analytics-overview.md` describe, minus their proxy
half, because that half is already written.

**No API change and no proxy change.** The work is one request and one render,
on the page that already shows the aggregate version of the same series.

## Why this one rather than another cheap row

`specs/metorik-gap.md` calls UTM source attribution **"Has, and ahead"** and
names it as one of only two things worth *protecting* rather than closing, on
the strength of CPA and LTV by source. The per-campaign series with spend and
CPA on it is the part of that claim a person can look at, and it is the part
currently unreachable. The page today renders blended ROAS and a best/worst CPA
over the aggregate; which *campaign* is carrying the blend is the question that
figure raises and cannot answer.

## The one property that decides whether this is worth shipping

**`ad_spend` is Meta-only.** `specs/metorik-gap.md` records ad-platform
integration as Partial: `api/services/meta_ads.py` is the whole of it, imported
by `api/analytics/routes/sources.py`, and there is no Google, TikTok, Pinterest,
Snapchat, Reddit or Microsoft path at all.

So a campaign row with no Meta spend behind it is a campaign whose cost is
**unknown**, not a campaign that cost nothing. Rendered as `£0.00`, it is a
free campaign with an infinite return, and it will sort to the top of any
efficiency ranking on the page. That is not a cosmetic defect: it is a page
telling an agency to spend more on the channel it has the least information
about. Requirement 2.3 is the reason this spec exists in the form it does, and
it is the requirement most likely to be quietly dropped, because the page looks
finished without it.

## What the user sees

On `/analytics/sources`, below the existing source table and inside the same
date window the page already uses:

* **A per-campaign section** listing the campaigns in the window, each with its
  totals for the window — customers, orders, revenue, spend and CPA.
* **A daily series** for the campaigns a reader selects, over the same periods
  the aggregate timeline above it covers.
* **"no spend recorded"** wherever spend was never ingested, and **no CPA at
  all** on those rows.
* **A line saying what share of orders carries UTM data**, so the section is not
  read as the whole store.
* In a window with no campaigns, or when the endpoint does not answer: one
  sentence, and the rest of the page unchanged.

---

### 1. The page requests the endpoint

In `platform/app/(dashboard)/analytics/sources/page.tsx`, add one fetch of
`/api/analytics/sources/timeline-by-campaign`, alongside the fetches the page
already makes and in whatever mechanism they already use — the same loader, the
same window state, the same error handling. **Read the file and follow its own
shape.** Do not introduce a second fetching pattern, a client-side cache, or a
new state container beside the one that is there.

It is a separate request because it is a separate endpoint; it is **not** a
separate window. It takes its `start` and `end` from the page's existing date
range, and it re-issues when that range changes, exactly as
`/sources/timeline` does. Do not touch
`platform/components/analytics/DateRangePicker.tsx`.

**Read the payload's key names out of `api/analytics/routes/sources.py`.** The
names in this spec are descriptions of the figures, not a claim about the
payload's spelling. `api/**` is protected under this contract; it is being read,
never edited.

### 2. What renders

All of this is in `platform/app/(dashboard)/analytics/sources/page.tsx`, below
the existing source-level content. Everything already on that page keeps its
name, its value and its position.

**2.1 The campaign list, with every denominator printed.** One row per campaign
in the window: the campaign name as attributed, its customers, its orders, its
revenue, its spend and its CPA. Where the row shows a CPA, the two numbers it is
derived from — spend and customers — are on the same row, so a reader can divide
them and get the third. Amounts are GBP, named rather than implied;
`specs/metorik-gap.md` records every production order as GBP and multi-currency
as out of scope.

**Take the row totals from the payload's own series rather than inventing a
second lineage.** If the endpoint returns per-period rows only, the window total
is a sum of those rows and nothing else — do not blend it with a figure from
`/api/analytics/sources`, which is attributed at source level and over a
different grouping. Two numbers for one campaign that disagree by a rounding
step is worse than one number.

**The order is the payload's, or it is stated.** If the page sorts the list at
all, the sort key is visible and the reader can see it. A list ordered by one
rule and captioned as another reads as a ranking and is not one. Do not rank by
CPA by default — see 2.3 for why that particular default is dangerous here.

**2.2 The series, over the periods the endpoint returned.** The payload carries
`periods` alongside the per-campaign rows; render against **those**, not against
dates derived in the client from the picker. A campaign with no row for a period
is a gap in that campaign's data, and it renders as a gap — not as zero, and not
by carrying the previous day's value forward.

Reuse `platform/components/analytics/TimeSeriesChart.tsx` if it takes the shape
this payload has; it is writable under this contract, and the aggregate timeline
above already uses the page's charting. If it does not fit, render the series as
a table rather than widening a shared component to suit one caller — that
component renders on more than this page and ten analytics render tests would
not show what a change to it did to the others.

**Bound what is drawn, and say so when you do.** A store with hundreds of
campaigns is not a chart. Default to a small number of series — the largest by
customers — and let the reader choose others from the list in 2.1. Whatever is
left out is stated in a sentence beside the chart: how many campaigns are not
drawn. A silent top-N reads as the whole store.

**2.3 Spend that was never recorded is not spend of zero.** This is the
requirement the candidate names and the one that must not be softened.

`ad_spend` comes from Meta and from nowhere else. A campaign with no Meta spend
joined to it has **no cost information**, and the page says so:

* Render the spend cell as **"no spend recorded"** — or the page's existing
  wording for an unavailable figure — never as `£0.00`, never as `—` with no
  explanation, and never as a blank.
* Render **no CPA at all** on such a row. A CPA computed from an absent spend is
  zero, and zero CPA is the best possible score. Leave the cell empty with the
  same wording, and exclude the row from any best/worst or efficiency comparison
  the section makes.
* Do not let such a row contribute to any total, average or blended figure the
  section renders. A denominator that silently includes cost-free campaigns is
  the same lie one step removed.
* **Distinguish absent from zero at the payload level, not by testing for
  falsiness.** `ad_spend === 0` and `ad_spend == null` are different facts and
  `!ad_spend` erases the difference. Read
  `api/analytics/routes/sources.py` and establish which one the endpoint emits
  for an unjoined campaign before writing the condition. A genuine zero — spend
  ingested and equal to zero — renders as `£0.00` and keeps its CPA.
* One sentence in the section says why, once: spend is ingested from Meta only,
  so campaigns run elsewhere show no cost. Once, not per row.

**2.4 The attribution denominator is on screen.** `specs/metorik-gap.md` records
`utm_source`, `utm_medium` and `utm_campaign` as populated on 2,010,699 of
2,844,177 orders on this tenant, as of 2026-08-28. Roughly 71% of orders carry
UTM data and 29% do not, and the 29% is not distributed evenly across campaigns
— it is orders with no campaign at all.

The section states the share of orders it covers, in prose a merchant reads.
Prefer a coverage figure from the payload if the endpoint returns one; if it
does not, state the fact qualitatively — *"campaign figures cover only orders
carrying UTM data"* — rather than hard-coding 71%, which would be a
seventeen-day-old reading of one store frozen into a page. **Do not compute a
coverage percentage in the client** from figures that do not have the
unattributed population in them.

**2.5 Empty, unavailable and absent are three different things.** They look
identical to a user and mean different things, and the page must already
distinguish at least two of them —
`platform/__tests__/fixtures/analytics/sources-timeline-unavailable.json` and
`platform/__tests__/fixtures/analytics/sources-insights-unavailable.json` exist,
so read how the page handles those and follow it rather than inventing a fourth
convention.

* **A window with no campaigns**: render the section with one sentence in place
  of the list — *"no campaign activity in this window"*.
* **The request fails, or the endpoint is not there**: render the section's
  unavailable state, the way the page already does for the timeline and the
  insights. Do not throw, do not blank the page, and do not let it take the
  source table down with it.
* **This is not hypothetical, and it is the single largest regression risk in
  this task.** `platform/__tests__/mocks/handlers.ts` is protected under this
  contract and cannot be edited, so it has no handler for this URL. Whatever
  `platform/__tests__/unit/analytics/sources.render.test.tsx` renders this page
  against today, it will render it against a **failed or unhandled** request for
  the new endpoint. That test must keep passing untouched. Read it and the MSW
  configuration first: if an unhandled request is configured to error, the
  section's unavailable path is the one the whole existing suite will exercise,
  and it has to be silent enough not to break nine other assertions.

### 3. The window is the only thing this page sends

The request carries `start` and `end` and nothing else — the same two names the
proxy at `platform/app/api/analytics/sources/timeline-by-campaign/route.ts`
already forwards, and the same two `/sources/timeline` is sent today. **No new
parameter is introduced anywhere in this task**: no limit, no campaign filter,
no granularity. A name the proxy does not forward is dropped silently, and a
name the FastAPI signature does not declare is dropped after that, with no error
and no log line — which is the defect this whole family is named for.

Selecting which campaigns to chart (2.2) is **client-side, over rows already
returned**. It does not re-request. If the returned set is too large to be
useful that is a reason to open a follow-up for a server-side bound, not a
reason to invent a parameter here.

Everything else the page requests is byte-for-byte unchanged: same URLs, same
query strings, same number of calls. The one addition is this fetch.

### 4. A test that fails without this change

One new file,
`platform/__tests__/unit/analytics/test_fleet_source_campaign_timeline.test.tsx`.
This contract's `creatable_paths` admits
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx` and nothing else, the
extension must be `.test.tsx` or vitest never collects it, and
`contracts/checks/new_test_bites.sh` runs it against the tree as it was before
the change and refuses the branch if it passes there.

**No existing test file, fixture or handler may be edited.**
`platform/__tests__/**` is protected. The new test supplies its own payload by
overriding the handler from inside itself through
`platform/__tests__/mocks/server.ts`, following the pattern
`platform/__tests__/unit/analytics/sources.render.test.tsx` already uses for
this page's other endpoints.

Assert four things, because a test that only checks the section renders passes
against a page that renders a zero-cost campaign as a triumph:

1. **A campaign with no spend says so and shows no CPA.** Given a payload with
   one campaign carrying spend and one carrying none, the rendered output shows
   the money figure for the first and the *"no spend recorded"* wording for the
   second, and **no CPA value anywhere on the second row** — requirement 2.3.
   Assert the negative explicitly: `£0.00` and a zero CPA must not appear for
   that campaign. This is the assertion that makes the defect impossible to
   ship, and it is the reason this file exists.
2. **A genuine zero is not the same cell.** A campaign whose payload carries a
   spend of zero renders as a money figure and keeps its CPA — requirement 2.3's
   last clause. Without this half, a page that renders every campaign as "no
   spend recorded" passes test 1.
3. **The request goes out with the window and nothing else.** Asserted on the
   URL the MSW handler received: one request to
   `/api/analytics/sources/timeline-by-campaign` carrying `start` and `end`, and
   no other query key — requirements 1 and 3.
4. **An unavailable response leaves the page standing.** With the endpoint
   erroring, the section renders its unavailable state and the source-level
   content beside it still renders — requirement 2.5. This is the one that
   protects the nine existing analytics render tests from the new fetch.

**Cite every requirement in the diff.**
`contracts/checks/spec_requirements_cited.py` runs first in this contract's
verification list and fails the task if a numbered requirement appears nowhere
in the lines the diff adds: `// spec:2.3` on the line choosing between "no spend
recorded" and a money figure, and so on. The leaves are 1, 2.1, 2.2, 2.3, 2.4,
2.5, 3 and 4 — eight, and the parsed list including the parent `2` is nine,
against a `max_requirements` of 12.

---

## What must not change

* **Everything already on the sources page.** The source table, the blended
  ROAS, the best/worst CPA, the insights block and the budget controls keep
  their names, their values and their positions. This section is additive and
  sits below them.
* **The date window mechanism.** The new request uses the window the page
  already asks for.
* **Any proxy.** `platform/app/api/analytics/sources/timeline-by-campaign/route.ts`
  already forwards the window and is not touched. Neither is
  `platform/app/api/analytics/sources/timeline/route.ts`.
* **No figure recomputed in the client** beyond summing the payload's own
  per-period rows for a campaign. Not CPA, not ROAS, not coverage.

## Out of scope

* **Any backend change.** `api/**` is protected under this contract and every
  figure this task renders is already deployed. The API files named above are
  being read.
* **Ad platforms other than Meta.** `specs/metorik-gap.md` records the
  integration as Meta-only and the other seven as absent. This task makes that
  absence *visible*; closing it is a connector, not a render.
* **A campaign filter or a campaign-level budget control.** The budget endpoint
  is source-level today and the page already reaches it. Wiring a per-campaign
  budget is a second task with a backend half.
* **Last-click attribution.** `research/metorik-gap-2026-08-30.md` records the
  model as each customer's first revenue-status order in range, with no
  alternative. This section inherits that model; it does not offer a choice of
  one.
* **Campaign-name aliasing.** `contracts/dd-utm-source-alias.yaml` and
  `specs/data/utm_source_alias_seed.sql` exist for *source* names. Extending
  aliasing to campaign names is a decision about data, taken elsewhere, and a
  name prettified here is a name that matches nothing when pasted into a filter.
* **Editing `specs/metorik-gap.md`.** It is in the fleet repository, which this
  contract cannot reach.

## How it is checked

Two contracts declare `work_type: dd_frontend`. This runs under
`contracts/dd-analytics-frontend.yaml`, which makes
`platform/app/(dashboard)/analytics/sources/**` writable. The other,
`contracts/dd-acquiring-page.yaml`, makes only the products route, the products
page and the nav component writable, so the declared path is not writable under
it.

In the order the contract runs them:

    spec_requirements_cited.py    every numbered leaf cited in the diff
    cd platform && tsc --noEmit
    cd platform && vitest run     21 files, 319 tests
    new_test_bites.sh             the added test fails without the change
    proxy_passthrough.py          two pairs, and neither of them is this one

## Before this is queued

* **`proxy_passthrough.py` does not cover the sources pair.** `PAIRS` in
  `contracts/checks/proxy_passthrough.py` names the orders page and the
  analytics overview and nothing else; its own docstring lists `sources`,
  `sources/insights` and `sources/timeline` among thirteen unchecked pairs of
  the same shape, and `sources/timeline-by-campaign` is not even on that list.
  So the one gate that exists for *"the page sends a name the proxy drops"* will
  go green without reading either file this task is about. That is tolerable
  **only because requirement 3 introduces no new parameter** — the window is
  already forwarded. If whoever queues this relaxes requirement 3, the gate
  protecting the relaxation does not exist.
* **There is a second, live risk that check cannot see**, and it is the one in
  2.5: adding a fetch to a page whose MSW handlers cannot be extended.
  `platform/__tests__/mocks/handlers.ts` is protected and
  `platform/__tests__/unit/analytics/sources.render.test.tsx` is protected, so
  the existing suite will run this page with the new endpoint unmocked. Read
  both before deciding the section's unavailable path is right. If the suite
  turns red for this reason, the answer is a page that tolerates the failure —
  not a widened contract.
* **Every key name in requirement 2 is a description, not a quotation.** This
  spec was written from `specs/metorik-gap.md`, from
  `research/candidates-metorik-gap-2026-09-14.md` and from the runner's listing
  of the tree. The shipped source of the page, the proxy and the route was not
  readable during this run. The payload's shape —
  `{periods, campaigns: {name: [...]}}` — is quoted from the candidate and must
  be confirmed against `api/analytics/routes/sources.py`.
* **In particular, confirm what the endpoint emits for an unjoined campaign**
  before implementing 2.3. Whether it is `null`, an omitted key or a literal
  zero decides whether this task is a two-line condition or a real distinction
  the page has to carry, and it is the difference between the feature being
  worth shipping and being actively misleading.
* **This merges with nobody reading it.** `auto_merge` is `true` on
  `contracts/dd-analytics-frontend.yaml` since 10 Sep 2026, and that file's own
  header sets out the cost: requirements can ship unbuilt with every check green
  and no revert triggered, because there is nothing to revert. The `spec:N`
  tokens in the diff are the only trace. The requirement most likely to go
  missing that way is 2.3, for the reason at the top of this document — the page
  looks finished without it, and wrong only to somebody who knows that spend
  comes from one platform out of eight.
* **The coverage figures are a reading of production on 2026-08-28**, quoted
  rather than re-measured, tenant 2 only. Nothing above depends on their exact
  values — only on the shape: most orders carry UTM data, a large minority do
  not, and requirement 2.4 exists to keep that minority visible rather than to
  print a particular percentage.
