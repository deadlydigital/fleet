# Make the comparison windows reachable

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
title: Reach task 28's comparison windows from the overview, with a label that says which window
writable_paths:
  - platform/app/api/analytics/dashboard/route.ts
  - platform/app/(dashboard)/analytics/page.tsx
```

## What is wrong

Task 28 shipped comparison windows and they are deployed. Read from the
running API's own `/openapi.json` rather than from its source, today:

    comparison_mode   default "previous_period"; one of previous_period,
                      previous_year, custom
    compare_start     required by comparison_mode=custom, rejected by the others
    compare_end       required by comparison_mode=custom, rejected by the others

`platform/app/api/analytics/dashboard/route.ts` builds its query string from
exactly two keys:

    if (searchParams.get('start')) params.set('start', ...)
    if (searchParams.get('end'))   params.set('end', ...)

So no value a user can produce in the browser reaches any of the three new
parameters. The feature is built, deployed, documented in the OpenAPI page,
and unreachable.

`specs/metorik-gap.md` records the Daily-band row *"Compare any period to any
other, incl. year-on-year"* as **Partial**, on the grounds that the only
comparison available is the equal-length window immediately before. The
backend half of that is now false and the frontend half is why the row still
stands.

## Which Metorik behaviour this matches

The row above, and closing it needs all three modes rather than two. *"Any
period to any other"* is `custom`; *"incl. year-on-year"* is `previous_year`.
A change that shipped only year-on-year would leave the row Partial for the
same reason it is Partial now, so all three are in scope.

## What the user sees

Beside the date picker on `/analytics`, a control that chooses what the
figures are compared against:

* **Previous period** — the equal-length window immediately before. The
  default, and what every user sees today.
* **Same period last year** — the same span, one calendar year earlier.
* **Custom** — a second date range, chosen the same way as the first.

And, on every stat card and in every insight sentence, **a label that names
the window actually compared against.**

## Why the label is the point, and not a detail

Task 28's own spec says this, and it is the reason this task exists as a pair
rather than as two:

> Widening `platform/app/api/analytics/dashboard/route.ts` first would let
> `platform/app/(dashboard)/analytics/page.tsx` render "vs previous 366 days"
> over a year-on-year comparison, which is a worse sentence than the
> unqualified one this change exists to fix.

The page builds its label from the top-level `span_days` alone — the length of
the window the user *asked for*. That inference is sound only while the two
windows are equal by construction, which is exactly what stops being true the
moment a mode other than `previous_period` is selected.

**"vs previous 366 days" over a year-on-year comparison is not a rounding
error in the wording. It is a false statement about which numbers were
subtracted**, on a figure whose entire value is being like-for-like, and a
merchant has no way to tell from the page that it is false. That is worse than
today's unqualified label, which is at least true.

So the proxy change and the label change land in one branch or neither. The
contract enforces that with `paired_paths`; this section is why.

## What to build

### 1. The proxy forwards the three parameters

`platform/app/api/analytics/dashboard/route.ts`, alongside `start` and `end`,
forwards `comparison_mode`, `compare_start` and `compare_end` when they are
present, in the same shape as the two already there.

**Forward, do not interpret.** Do not default `comparison_mode` here, do not
drop `compare_start` when the mode is not `custom`, and do not validate any of
them. The API rejects every bad combination with a 400 and a `detail` naming
the problem, and a proxy that quietly fixed up a request would put a second
opinion about the rules in a file that cannot test one.

**Do not add a parameter the API does not declare.** FEAT-035 is recorded in
this endpoint's own docstring: the page sent `start` and `end`, the proxy
forwarded them, the route declared neither, and FastAPI discarded them — a
date picker wired to nothing, no error and no log line. The four names above
are the four the deployed OpenAPI declares.

### 2. The page sends them

`comparison_mode` is sent on every request.

`compare_start` and `compare_end` are sent **only when the mode is `custom`**,
and must be absent otherwise. This is not tidiness: the deployed route returns

    400  compare_start/compare_end are only used by comparison_mode=custom,
         not by 'previous_period'

so leaving stale custom bounds attached after switching back to another mode
turns the page into an error screen.

The response is stored as received, as `start`/`end` already are. Do not map
or rename anything: `comparison` is what the API calls it.

    comparison: {
      mode: 'previous_period' | 'previous_year' | 'custom'
      start: string        // ISO date, inclusive
      end: string          // ISO date, inclusive
      span_days: number    // the COMPARISON window's own inclusive length
    }

`comparison` is optional in the page's type. The API always returns it, but
the ten analytics render tests run against fixtures captured before it
existed, and a type that requires it would make the fallback in §3
unreachable rather than merely unused.

### 3. The label names the window that was compared

Both label sites change, and they are two:

* `generateInsights()` — `trendLabel`, then `priorPhrase`, then the
  `Revenue down …% vs the …` sentences
* the component body — `trendLabel`, passed to every `StatCard` as
  `trend.label`

Replace both derivations with **one** helper, returning both strings, so
there is a single place that decides what the comparison is called. Two
independent derivations of the same sentence is how the revenue page ended up
with four lineages of AOV.

Let `N = data.comparison?.span_days ?? data.span_days`, and `S`, `E` be
`data.comparison.start` and `data.comparison.end`.

| `comparison.mode` | stat-card label | insight phrase, used as ``vs ${phrase}`` |
|---|---|---|
| absent, or `previous_period` | `vs previous {N} days` | `the previous {N} days` |
| `previous_year` | `vs same period last year` | `the same period last year` |
| `custom` | `vs {S} – {E}` | `{S} – {E}` |
| any of the above with `N <= 0` and no `comparison` | `vs previous period` | `the previous period` |

Two things this table is doing on purpose:

**The first row must be byte-identical to today.** `comparison` absent is what
every existing fixture looks like, and
`platform/__tests__/unit/analytics/overview.render.test.tsx` asserts the exact string
`Revenue down 24.1% vs the previous 61 days`. That test is protected and must
keep passing untouched. It is the regression guard for this whole change and
it is worth more than any wording improvement.

**`previous_year` is labelled from the MODE, not from the span.** Deriving it
from `comparison.span_days` would give "vs previous 366 days", which is
arithmetically true about the length and false about the window — it names the
366 days immediately before, and that is not what was compared. This is the
exact sentence the paragraph at the top of this spec is about. Do not render
a day count for `previous_year`.

Dates in the `custom` row are the ISO strings as received. Do not add a date
formatting library or a locale helper for this.

### 4. The control

In the page header, beside the existing `DateRangePicker`.

* It must be operable in a render test through role and accessible name.
  Give it an accessible name containing **"Compare"** and make each option
  selectable by its visible text — the three labels in *What the user sees*.
* When and only when `custom` is selected, a second date range control
  appears for the comparison window. Reuse
  `@/components/analytics/DateRangePicker`; it already offers presets and a
  custom start/end pair, and it needs no change. Give it an accessible name
  that distinguishes it from the primary one.
* Changing the mode refetches, exactly as changing the date range already
  does.
* Switching away from `custom` must clear the comparison bounds from the
  request. See the 400 in §2.

Build it from components that already exist. `components/ui/**` is not
writable under this contract — import from it, do not edit it.

### 5. A 400 must say what was wrong

The page's catch-all currently reports `Failed to load analytics data` for
every failure. A user who picks a comparison window ending before it starts
gets that sentence and no way to know what to change.

When the response is not ok and the body carries a `detail` string, surface
that instead of the generic message. One condition and one string; do not
build an error-handling framework.

## What the added test must assert

The contract permits **creating** exactly one file matching
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx`, and
`new_test_bites.sh` runs it against the tree as it was before this change and
refuses the branch if it passes there. **Modifying any existing test is
refused** — including
`platform/__tests__/unit/analytics/overview.render.test.tsx`, which must keep
passing as it stands.

Follow the pattern already in `platform/__tests__/unit/analytics/overview.render.test.tsx`:
render `AnalyticsPage`, serve `*/api/analytics/dashboard` with MSW, pin
`Date.now`.

It must assert, at minimum:

1. **Year-on-year is labelled as year-on-year.** Served a response whose
   `comparison.mode` is `previous_year` — with `span_days` and
   `comparison.span_days` deliberately *different*, e.g. 365 and 366 — the
   page renders the same-period-last-year wording and renders **no** "previous
   366 days" and **no** "previous 365 days" anywhere. The negative half is
   what makes this test bite; without it the test passes against a page that
   prints a day count.

2. **The default is unchanged.** Served a response with no `comparison` key at
   all, the insight sentence is exactly what it is today.

3. **The mode reaches the request.** Selecting *Same period last year* causes a
   request whose query string carries `comparison_mode=previous_year`. Assert
   on the URL the MSW handler received. This is the half that proves the
   feature is reachable rather than merely renderable, and it is the FEAT-035
   lesson as a test: a parameter that never leaves the browser produces a page
   that looks correct and shows the same numbers.

A test asserting only (2) passes against the pre-change tree and fails this
run. A test asserting only (1) and (2) would pass without the proxy ever being
touched, which is exactly the half-landed change the pairing exists to refuse.

## What must not change

* **The default response path.** With no comparison parameters the request the
  page sends and the label it renders are what they are today.
* **The ten existing analytics render tests**, unmodified and green. They are
  protected; the run is refused if they move.
* `span_days` keeps its meaning — the inclusive length of the **chosen**
  window. The comparison's own length is `comparison.span_days`.
* The `period` / `trends` key names and the populations behind them. No local
  renames and no client-side recomputation of AOV; the API filters both sides
  of it and a second lineage in the client is a known defect class here.
* Feed-health suppression. The API nulls every trend when the feed is silent
  and the window reaches the gap, and the page renders an absent trend as no
  trend. No rendering path here should learn about suppression.

## Out of scope

* **Any backend change.** `api/**` is protected under this contract. Every
  parameter this task sends is already deployed and observable in
  `/openapi.json`.
* **The other analytics pages.** `/analytics/revenue`, `/analytics/orders` and
  the rest have their own endpoints and their own comparison story. This is
  the overview.
* **Net revenue after refunds** (task 26). Also shipped and also unreachable,
  and a separate task under this contract.
* **A comparison series on the chart.** `trends_data` is a series over the
  chosen window only. Overlaying the comparison window needs an endpoint that
  returns it, and it does not.
* **Persisting the chosen mode** across reloads or into the URL. Worth having,
  not worth coupling to this.
* **Editing `specs/metorik-gap.md`.** It is in the fleet repository, which this
  contract cannot reach. The row moves from Partial to Has when this merges;
  that is a note for whoever merges, not work for this branch.

## How it is checked

What the contract runs, in order:

    cd platform && tsc --noEmit
    cd platform && vitest run                    21 files, 319 tests
    new_test_bites.sh                            the added test fails without
                                                 the change and passes with it
    paired_paths.py                              route.ts and page.tsx both, or
                                                 neither

## How a human checks it

`auto_merge` is **false** on this contract, so this branch waits for a person.
The reason is narrow and it is this task specifically: `paired_paths.py`
establishes that both files moved, and it cannot establish that the sentence
the page renders describes the window the proxy asked for. The agent chooses
what its render test asserts. Read the diff for that one thing.

Against the running app, signed in:

1. `/analytics` with no interaction. The stat cards and insights read exactly
   as they did before the branch.
2. Switch to *Same period last year* on a 365-day range. The label must not
   contain a day count, and the percentages must change — if they do not, the
   parameter is not reaching the API, which is FEAT-035 again.
3. Switch to *Custom* and choose a window that ends **after** the chosen one,
   on a tenant whose feed has gone silent. Trends must come back empty rather
   than as percentages: the engine suppresses on whichever window ends later,
   and this is the case task 28 added that check for.
4. Choose a custom comparison whose end precedes its start. The page must show
   what the API said was wrong, not "Failed to load analytics data".
