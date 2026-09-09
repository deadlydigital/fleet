# Draft spec — choose the comparison window on the analytics overview

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
title: Let the overview compare against a chosen window, not only the preceding one
writable_paths:
  - api/analytics/services/date_range.py
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/dashboard.py
```

## Why `dd_api` and not `dd_frontend`

The comparison window is computed in `api/analytics/services/analytics_engine.py`
and nowhere else. The page receives bounds and percentages already decided for
it. So the whole of this change is backend, and `contracts/deadly-digital-platform-api.yaml`
is the only contract whose writable paths reach it — `contracts/deadly-digital-platform.yaml`
protects the whole `api` tree outright.

That contract establishes that the changed files parse and introduce no new
ruff finding, and nothing more. It is worth being blunt about what that leaves
unverified here, because this change is date arithmetic and date arithmetic
fails silently: **a passing run of this contract does not establish that any
comparison window computed below is the right one.** See *How a human checks
it*.

## What is there now

`dashboard_overview()` in `api/analytics/services/analytics_engine.py` takes
`start` and `end`, then derives its comparison window with no input from the
caller:

    span_days = (end - start).days
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span_days)

Inclusive bounds both sides, so a 1-day window compares against 1 day and a
90-day window against the 90 days immediately before it. The response returns
`previous`, `previous_start`, `previous_end` and `span_days` beside `period`,
and the trend percentages in `trends` are computed from `period` against
`previous`.

The docstring argues the choice at length under *COMPARISON IS THE PRECEDING
WINDOW OF EQUAL LENGTH*, and the argument is correct: once the range is
user-chosen, "vs last month" is a category error for every range that is not a
calendar month. That reasoning is not being overturned. It rules out making
*calendar month* the fixed comparison. It does not rule out letting the caller
name a different window of the same length.

`GET /api/analytics/dashboard` in `api/analytics/routes/dashboard.py` accepts
`start` and `end` and passes them through.

The gap this closes is the Metorik parity row in the Daily band, *Compare any
period to any other, incl. year-on-year*, recorded as **Partial**: a genuine
like-for-like, but the only comparison there is. The specific risk is not that
the number is wrong — it is right for what it measures — but that a single
unqualified comparison invites a reader to take it as year-on-year when it is
not.

## What to build

### 1. A comparison-window helper in `api/analytics/services/date_range.py`

That module already exists to state date arithmetic once so it cannot drift
into per-query restatements, and it already holds `span_days()` and
`exclusive_end()`. The new arithmetic belongs beside them, not inline in the
engine.

Add:

    COMPARISON_MODES = ("previous_period", "previous_year", "custom")

and a function that, given the chosen `start`/`end`, a mode, and optional
explicit bounds, returns the `(compare_start, compare_end)` pair.

**`previous_period`** — exactly today's arithmetic, moved, not changed. The
window of equal length ending the day before `start`. This is the default and
its output must be byte-identical to what the three lines above produce for
every input.

**`previous_year`** — shift `start` back one calendar year, then derive the end
by adding the *same span*:

    compare_start = start shifted back one calendar year
    compare_end   = compare_start + (end - start)

Deriving the end from the span rather than shifting `end` independently is the
load-bearing decision. Shifting both endpoints separately across a leap
boundary changes the length of the comparison window by a day, and a
like-for-like comparison whose two sides are different lengths is the category
error this endpoint already refuses to make — it would just be a subtler one.
Deriving from the span makes equal length true by construction.

29 February shifts to 28 February. Say so in a comment; it is the only date
where "one calendar year earlier" is not a date, and a reader who finds it
undocumented will assume it was not considered.

Do **not** implement this as `start - timedelta(days=365)`. It is wrong by a
day for any window whose year contains 29 February, which is the failure mode
that makes year-on-year comparisons quietly untrustworthy.

A 364-day shift, which aligns weekdays and which some retail reporting
prefers, is deliberately not offered. Weekday alignment and calendar alignment
are different questions and a mode that silently picks one is worse than two
modes that each say which they are. If it is wanted later it is a fourth mode,
not a change to this one.

**`custom`** — the caller supplies both bounds and they are used as given. No
length matching is imposed. A caller comparing March against a two-week
promotion is asking a real question, and refusing it because the spans differ
would be this endpoint deciding what the caller meant. The mode name is what
tells a reader the two sides may not be commensurable, which is precisely the
qualification the current single fixed comparison lacks.

### 2. `dashboard_overview()` takes the mode

Add parameters to `dashboard_overview()` in
`api/analytics/services/analytics_engine.py` — mode plus optional comparison
bounds — all defaulted so that every existing caller keeps today's behaviour
with no edit.

Replace the inline `prev_start`/`prev_end` arithmetic with a call to the helper.

**Response keys.** `previous`, `previous_start` and `previous_end` keep their
names and keep meaning *the window that was actually compared against*,
whatever the mode. They must not be frozen to the preceding-period window
while the trends are computed against something else: the existing invariant
in this function is that the percentage and the number it describes come from
the same place, and splitting them would break it in a way no test here can
see.

Add one new key, `comparison`, holding at minimum:

    mode        the mode actually used
    start, end  the comparison bounds, ISO dates (same values as previous_*)
    span_days   the INCLUSIVE length of the comparison window

`span_days` at the top level keeps its current meaning — the inclusive length
of the **chosen** window — and must not change. The page reads it.

Why `comparison.span_days` is needed as well as the top-level one: the page
builds its trend label from the top-level `span_days` alone, producing "vs
previous 90 days" from the chosen window's length. That inference is only
sound because the two windows are equal by construction, which stops being
true the moment a mode other than `previous_period` is used. Returning the
comparison's own bounds and length is what lets a page label the trend from
what was compared instead of guessing it from what was asked for.

### 3. Feed-gap suppression must consider both windows

This is the one place where adding modes creates a defect rather than just
adding a feature, and it is easy to miss.

`dashboard_overview()` suppresses trends when the feed is `silent` or
`erroring` **and** the window reaches the gap:

    window_reaches_the_gap = (
        last_order is None or end > date.fromisoformat(last_order[:10])
    )

The comment beside it states the premise plainly: "`previous` sits before
`period`, so if `period` is entirely covered by the data we hold then
`previous` is too."

That premise is true for `previous_period` and for `previous_year`. It is
**false** for `custom`, where the comparison window may end *after* the chosen
window — comparing January against August, say. Under a feed outage that
started in August, the chosen window is fully covered, the check passes, and
the engine returns a confident percentage computed against a window it knows
is missing data. That is the same defect the suppression logic exists to
remove, arriving through a door the new mode opens.

So the coverage test must be applied to whichever of the two windows ends
later — the later of `end` and the comparison end — rather than to `end`.
Under the two ordered modes this changes nothing, because the comparison
window is earlier by construction.

Do not extend `_feed_health()` to the comparison window. It answers "are we
being told anything?" about the window asked about, and `orders_in_window` is
a fact about that window; recomputing it over a second range would change what
the field means for one mode only. The suppression decision needs the later
end date, which is already available without a second query.

### 4. The route validates instead of dropping

`api/analytics/routes/dashboard.py` gains the query parameters: the mode, and
the two optional custom bounds. It already parses and validates `start`/`end`,
raising 400 on a bad format and on `end < start`; the new parameters follow
the same shape.

The route must **reject**, with 400 and a message naming the problem:

- a mode outside the accepted set
- `custom` with either bound missing
- either custom bound unparseable
- a custom range whose end precedes its start
- custom bounds supplied alongside a mode that does not use them, rather than
  accepting and silently ignoring them

Silently ignoring an unrecognised parameter is not an option here, and not for
abstract reasons. It is the exact defect this endpoint was fixed for in
FEAT-035: the page sent `?start=…&end=…`, the proxy forwarded them, this route
declared neither, and FastAPI discarded them — a date picker wired to nothing,
byte-identical responses, nothing logged. Reintroducing a parameter that can be
dropped without complaint would rebuild that trap next to the fix for it. The
docstrings in this file and in `api/tests/analytics/test_dashboard_window.py`
both record how expensive it was to find.

Update the route docstring to say what the comparison is and that it is
selectable. The description strings are what a caller reads in the generated
OpenAPI page, so each new parameter needs one that names its accepted values.

## What the page will and will not see

Nothing on the overview page changes, and it cannot change under this
contract — the whole `platform` tree is protected by
`contracts/deadly-digital-platform-api.yaml`.

That is not merely acceptable, it is what makes this change safe to land alone.
`platform/app/api/analytics/dashboard/route.ts` forwards exactly `start` and
`end` and drops everything else, so no new mode is reachable from the browser
until that proxy is widened. The default path stays byte-identical, the page
keeps reading `span_days` and keeps being right to do so, and there is no
window in which the UI can reach a mode whose label it would get wrong.

The follow-up frontend task — separate, `dd_frontend`, not in scope here — must
land the label change and the proxy change **together**. Widening
`platform/app/api/analytics/dashboard/route.ts` first would let
`platform/app/(dashboard)/analytics/page.tsx` render "vs previous 366 days"
over a year-on-year comparison, which is a worse sentence than the unqualified
one this change exists to fix.

## Out of scope

- **Any frontend change at all.** Both files named above are protected here.
- **A comparison series on the chart.** `trends_data` stays a series over the
  chosen window only. Overlaying the comparison window is a real feature, it
  needs a page that can draw it, and adding a second series to an endpoint
  whose only consumer would ignore it is cost with no reader.
- **Other endpoints.** `revenue_report()`, `customer_report()` and the rest are
  untouched. If the helper proves right here it can be adopted there later;
  adopting it everywhere in one diff would put date arithmetic into five
  endpoints on the strength of a contract that runs no tests.
- **Tests.** `api/tests/analytics/test_dashboard_window.py` is where these
  cases belong, and the `api/tests` tree is protected under every contract in
  this repository. Do not create a test file elsewhere to route around that.
- **Pre-existing lint or formatting** in any file touched. The gate is that the
  change introduces no *new* finding, not that the file becomes clean, and
  arriving with an unrelated import-sort is the diff-widening this repository's
  specs consistently refuse.

## What must not change

- The default behaviour. With no comparison parameters, every field of the
  response is identical to today's, including `previous_start`, `previous_end`
  and `span_days`.
- The `period` / `previous` key names and the populations behind them
  (`orders_revenue_statuses`, `customers_revenue_statuses`, `revenue`, `aov`).
- The no-baseline rule: a comparison window with `prior <= 0` yields `None`,
  never 0 and never 100. It applies unchanged to every mode, and it matters
  more under `previous_year`, where a store younger than a year has no prior
  window at all and inventing a percentage there would be the loudest possible
  version of the failure.
- The number of `_query_period_stats()` calls. Two, as now — one per window.
- The existing docstrings in `api/analytics/services/analytics_engine.py`. The
  *COMPARISON IS THE PRECEDING WINDOW OF EQUAL LENGTH* section should be
  extended to say that the preceding
  window is now the default rather than the only option, and to carry the
  leap-year rule. Its argument against calendar-month comparison stays: that is
  still why "vs last month" is not one of the modes.

## How it is checked

What the contract runs:

    api/analytics/services/date_range.py compiles
    api/analytics/services/analytics_engine.py compiles
    api/analytics/routes/dashboard.py compiles
    ruff introduces no finding that was not already present

## How a human checks it

The contract cannot establish correctness here, so state the manual check in
the branch description rather than implying the gates covered it. Against a
running API with a tenant key:

1. `GET /api/analytics/dashboard?start=…&end=…` with no comparison parameters,
   before and after the change. The two responses must be identical. This is
   the same technique that was the only way to see FEAT-035.
2. The same window with the year-on-year mode. `previous_start` must be one
   calendar year earlier, and `comparison.span_days` must equal the top-level
   `span_days`.
3. A window that spans 29 February 2024, and one that starts on it, in
   year-on-year mode. The comparison window must still be the same length as
   the chosen one.
4. A custom comparison whose window ends *after* the chosen window, on a tenant
   whose feed has gone silent — `analytics_1` stopped receiving on 2026-08-07
   and is the tenant these docstrings are written against. Trends must come
   back `None`, not a percentage.
5. Each rejection case in §4 returns 400 rather than a 200 computed from a
   silently discarded parameter.

Steps 1 and 4 are the two that matter. The first is the regression that would
be invisible; the fourth is the defect the new mode introduces.
