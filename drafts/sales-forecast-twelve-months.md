# Draft spec — a twelve-month sales forecast whose band is a returned number rather than a chart decoration

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Forecast revenue twelve months ahead from the monthly series the revenue report already computes, with a prediction interval on every point
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
auto_merge: false
```

## Figures, given

Nothing below is to be measured. These are readings other people took, quoted so
that the requirements can be argued from them and cited truthfully by an agent
that has no shell, no database and no network.

| Reading | Value | Where it comes from |
|---|---|---|
| Orders, and the span they cover | 2,889,850 rows over 1,283 days, 2023-03-12 to 2026-09-15 | `research/metorik-report-classification-2026-09-15.md`, *Monthly — Forecasts (3 of 3)*, at `80677a2` |
| `orders.total` populated | NOT NULL on 2,890,319; non-zero on 2,823,569 | `research/candidates-metorik-gap-2026-09-21.md`, this candidate's `hib_signal`, as of 2026-09-16 |
| Zero-total orders | 66,764, and they are the legal free-entry route rather than failed checkouts | the same classification document, *Correction (16 September 2026), third entry* |
| Forecasting code in the product | none: `[Ff]orecast` matches zero times under `api/analytics` and zero times under the analytics dashboard | this candidate's probes, at `fd5a404` |

1,283 days is about forty-two months, so a twelve-month horizon is extrapolated
from roughly three and a half times its own length. That ratio is the reason
this is worth building at all, and it is also the reason requirement 5 exists:
at that range the interesting part of the answer is the width of the band.

## Why this is a code change

The gap is an absent computation over a series the product already serves. It
needs no new column and no migration, and `api/analytics/migrations/**` is
protected under the contract named above in any case.

`contracts/deadly-digital-platform-api.yaml` makes both declared paths writable
and runs the verification that can judge this: `compileall`,
`ruff_no_new_findings.py`, `tests/unit` and `tests/analytics` file by file, and
one added test proven to fail against the tree before the change.

**The helper goes in `api/analytics/services/analytics_engine.py` rather than in
a new module, and that is forced rather than preferred.** That contract
enumerates its writable paths instead of globbing them — its own header explains
why — and `api/analytics/services/forecast.py` is not on the list. A new service
file would be outside the boundary, so the fit lives beside the series it reads.

## The judgement this spec makes, stated so a reviewer can disagree with it

The candidate says the history is already materialised: `DailyMetrics`
(`api/analytics/models.py`) stores `date`, `revenue`, `orders` and
`new_customers` per day, and `backfill_daily_metrics` in
`api/analytics/services/analytics_engine.py` fills it across the whole span.
That is true and **this spec still does not fit that table**, for three reasons
that are facts about the tree rather than preferences:

* **It stores the wrong measure.** `research/refund-coverage.md` records that
  `compute_daily_metrics` persists a gross `revenue` and no net field, while
  every revenue figure the product prints today — `revenue_report`,
  `revenue_summary`, the dashboard trend — is net of refunds. A forecast fitted
  on the stored column would extend a line the revenue page does not draw.
* **No route reads it.** The same document: *"no analytics route reads
  `daily_metrics` for a figure, so it is not a surface today, and it is the
  place a future net tile would go wrong if it were built on the stored table
  instead of on read."* This would be that tile.
* **It is a cache with a repair path.** `metrics_dirty_dates` is one of the
  thirteen tables `EXPECTED_TABLES` lists, and
  `api/analytics/services/dirty_dates.py` and
  `api/analytics/services/metrics_repair.py` exist to mark and mend it. A
  forecast fitted on a cache inherits whatever state the cache is in, and says
  nothing about it.

So the series comes from `revenue_report()` at month granularity. The cost of
that choice is stated rather than hidden: it is an aggregate over `orders`
across the whole history instead of a read of forty-odd stored rows. It is the
same query shape `GET /api/analytics/revenue` already runs for any window a
merchant picks, run once over the widest window — not a new access pattern, and
not one anybody in this fleet has timed. See *Before this is queued*.

---

### 1. The forecast fits the monthly series the revenue report already computes

A helper in `api/analytics/services/analytics_engine.py` obtains the history by
calling `revenue_report()` at month granularity over the tenant's full order
span, and fits that. It does not define a second revenue history, does not read
`daily_metrics`, and does not write its own `GROUP BY` over `orders`.

Two numbers for one question that can disagree is the defect this avoids: a
forecast whose last historical point differs from the last bar on the revenue
chart is wrong on the screen even when the arithmetic is right.

### 2. An incomplete month is excluded from the fit and is never emitted as history

The month a request lands in is partial, and a partial month is a smaller number
for a reason that has nothing to do with the trend. Included, it drags the line
down; drawn as the last historical point, it reads as a collapse.

So the fitted series ends with the last month that has fully elapsed at the time
of the request. The excluded month is named in the response as such, with its
partial figure beside it, rather than being dropped silently — an absent month
and an omitted month read identically to whoever renders this.

### 3. One quantity is forecast, and the response says which

The measure is the net revenue figure `revenue_report()` already returns per
period — the one the summary prints as the headline. The response carries the
measure's name as a field, so no reader has to infer from magnitude whether the
line is gross or net.

`research/refund-coverage.md` records that on this tenant the refund signal sits
on statuses outside `('completed','processing')`, so net and gross coincide
today. That makes naming the measure cheap and makes it matter later: if a
refund ever lands on a revenue status, the forecast moves with the page instead
of drifting away from it.

Free entries need no split here. 66,764 zero-total orders contribute zero to a
sum of money, so the series is unaffected — which is a different answer from the
one AOV needed (`drafts/say-whether-aov-includes-free-entries.md`), and it is
written down rather than left as an assumption a later reader has to redo.

### 4. The fit is an ordinary least-squares straight line, computed in plain Python

One model, stated in full so it can be checked by reading:

* index the fitted months `0 … n-1` and regress the measure on the index;
* slope `Sxy / Sxx`, intercept `mean(y) - slope * mean(x)`;
* nothing else — no seasonal term, no smoothing, no differencing.

**No seasonal term, deliberately.** Forty-two months gives three or four
observations per calendar month, and this store's revenue is driven by which
draws are running rather than by the month name. A twelve-factor seasonal fitted
on three points per factor would manufacture structure out of campaign timing
and then project it forward as if it were a calendar effect. Leaving it out
pushes that variation into the residuals, where requirement 5 turns it into a
wider band — which is the truthful place for it.

**Standard library only.** The arithmetic above needs `math` and nothing more.
The agent building this has Read, Edit, Write, Grep and Glob, so it cannot
install a package, cannot check whether one is already present, and cannot run
anything that would tell it. A fit that needs `numpy` is a fit this task cannot
honestly claim to have working.

### 5. The band is a prediction interval derived from the fit's own residuals

Every forecast point carries a lower bound and an upper bound, computed as the
textbook prediction interval for an OLS line:

    s   = sqrt( SSE / (n - 2) )
    se  = s * sqrt( 1 + 1/n + (x0 - mean(x))^2 / Sxx )
    band = yhat +/- z * se

with `z` a fixed constant for a 95% interval under the normal approximation.
The response carries `z`, the confidence level, `s`, and `n`, so the width is
reconstructible from the payload rather than taken on trust.

Three properties this shape buys, and each is a requirement of its own standing:

* **It widens with the horizon.** The `(x0 - mean(x))^2 / Sxx` term grows as the
  forecast moves away from the fitted centre, so month twelve is visibly less
  certain than month one. A constant band would be the lie this candidate's
  title is about.
* **It is not clamped at zero.** A lower bound below zero is reported as it
  falls. Clamping would narrow the stated uncertainty at exactly the point where
  the linear model is least believable, and the honest reading of a negative
  lower bound is "this model does not know", which is worth showing.
* **It is a statement about the fit, not about the future.** The interval covers
  scatter around a straight line through this history. It cannot cover a draw
  being cancelled. Requirement 6's `method` field says so in the payload.

### 6. Twelve monthly points, each with its band, and the fitted history beside them

The response carries exactly twelve forecast points, one per month after the
last fitted month, each with its period key in the same format the revenue
series already uses, its point estimate, its lower bound and its upper bound.
No point is emitted without a band.

Beside them: the fitted history as the list of (period, value) pairs actually
used, the count `n`, the slope and intercept, the residual standard deviation,
the confidence level, the `z` constant, the measure name from requirement 3, the
excluded partial month from requirement 2, and a short `method` string naming
the model. A forecast that arrives without the series it was fitted on cannot be
argued with.

### 7. A history too short to fit returns a refusal rather than numbers

Fewer than twenty-four complete months, or fewer than two distinct values among
them, and the endpoint returns the history and a stated reason with the forecast
list empty — not a flat line, not zeros, not a band of infinite width.

Twenty-four because the horizon is twelve: extrapolating a straight line a year
forward from less than two years of it is the case where the band would be doing
all the work and the point estimate none. The real tenant has about forty-two
months and never reaches this path, which is precisely why it must be built and
tested rather than assumed unreachable — a new tenant hits it on day one.

### 8. A new endpoint, additive, on the revenue router

`GET /api/analytics/revenue/forecast` in `api/analytics/routes/revenue.py`,
mounted beside the routes already there and taking its tenant resolution on the
same terms. No existing route's response changes shape, no existing key is
renamed, and `revenue_report()`'s own return value is unchanged — the helper
calls it, it does not learn about forecasting.

The horizon is twelve months and is not a parameter in this task. Candidate 2 of
the same batch asks for three, six and twelve, and requirement 1's helper is
where that argument goes when somebody takes that row; guessing at its shape now
would be designing an interface for work nobody has approved.

### 9. One new test, and what it must assert

One new file, `api/tests/analytics/test_fleet_revenue_forecast.py`. The
contract's `creatable_paths` allows `api/tests/analytics/test_fleet_*.py` and
nothing else, no existing test may be touched, and `new_test_bites.sh` proves
the added file fails against the tree before this change.

Over fixtures whose monthly series is known, it asserts the four properties that
would otherwise ship silently:

* a series with a known slope recovers that slope, and the twelve point
  estimates continue it (requirement 4);
* the band at month twelve is strictly wider than the band at month one
  (requirement 5);
* a partial final month is excluded from the fit and reported separately, and
  the fitted slope is identical to the slope over the same series with that
  month absent (requirement 2);
* a twelve-month history returns the requirement 7 refusal with an empty
  forecast list, rather than twelve numbers.

A test that asserts only that the endpoint returns 200 satisfies the bite check
and establishes none of this.

---

## What this task must not do

* **No migration, no new column, no write of any kind.** The series is read.
* **No page and no proxy.** `platform/**` is protected under this contract, and
  the surface is a second draft written after this response shape exists and can
  be quoted rather than predicted — the way drafts/order-filters-frontend.md was
  written. The candidate suggests the revenue page at
  platform/app/(dashboard)/analytics/revenue/page.tsx; that path is correct and
  it belongs to `contracts/dd-analytics-frontend.yaml`, not here. **Until that
  draft lands this reaches nobody**, which is stated rather than discovered.
* **No second forecasting model.** Requirement 4 is the whole of the design. An
  agent that adds an exponential-smoothing variant "for comparison" has built
  two numbers for one question.
* **No change to `revenue_report()`'s existing keys**, and no new argument to it
  beyond the granularity and window it already accepts.
* **No touching `api/app.py`, the email surface or the GDPR path.** All floored,
  none needed.

## What this task does NOT include, and must not claim

**Nobody has timed `revenue_report()` at month granularity over the full
history.** No figure for it exists in this fleet, the build agent has no shell
and no database, and a requirement asking for one would be a requirement that
cannot be cited — the two dead runs recorded in `contracts/draft-spec.yaml` were
exactly that mistake. So it is not numbered and the agent must not cite it,
claim it, or write a `spec:` token over it. Whoever reviews the branch should
run the endpoint once against the real tenant and read the wall-clock; if it is
slow, the fix is a narrower window or the stored table with its gross/net
mismatch confronted, and that is a second task with this one's response shape in
hand.

## Before this is queued

* **The unasked question is real and this spec does not answer it.** The
  candidate says it plainly: *"whether a twelve-month sales forecast is a number
  HIB would act on or a chart it would glance at. A prize competition's revenue
  is driven by which draws are running, which no time-series fit can see."* One
  sentence from HIB's team either promotes all three forecast rows above
  everything in the pool or kills them. Nothing in requirements 1–9 substitutes
  for asking.
* **The band is the deliverable, and it may come back embarrassingly wide.**
  That is the correct outcome for a campaign-driven store fitted with no
  campaign term, and requirement 5 exists so that it is visible rather than
  smoothed away. A reviewer who wants a narrower band is asking for a different
  model, not a different constant.
* **`auto_merge: false` is set above, against this contract's default.** The
  contract merges dd_api work unattended and its own header explains the trade.
  It is wrong for this one: every gate here can pass over a fit that is
  arithmetically clean and methodologically silly, because no check in the list
  reads a slope. The choice of model in requirement 4 and the width in
  requirement 5 are the whole of the work, and they want one person's eyes.
* **Candidates 2 and 3 get cheaper after this, not free.** The helper in
  requirement 1 is measure-agnostic in shape — it fits a series of monthly
  values — but the order-volume row takes three horizons and the new-customers
  row fits a count with a different zero behaviour. Expect thin work, not no
  work, and expect each to declare its own route file.
