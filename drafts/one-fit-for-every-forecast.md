# Draft spec — one fit for every forecast, and a third forecast to prove the seam

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Move each forecast's measure, horizon, method sentence and caveat off the module and onto the call, then add the order-volume forecast at three, six and twelve months over the monthly order count the revenue report already returns
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/orders.py
auto_merge: false
```

## What could not be read this run, first, because everything else rests on it

**The platform tree was not readable.** `contracts/draft-spec.yaml` declares
`worktree_links: reference/deadly-digital-platform`, and its own header states
why that does not help: *"The agent never sees it — the runner creates it after
the diff is derived, deliberately, and three specs died believing otherwise."*
No `reference/` directory existed in this worktree. The runner's paths pack
(`PATHS.md`) was the only view of the repository, and it lists names, not
contents.

So **nothing below was read from `api/analytics/services/analytics_engine.py`.**
Every claim about `_ols_fit`, the `FORECAST_` constants, `revenue_forecast`'s
body and task 147's test file is quoted from the task statement that queued this
draft and is recorded here as *given*, on the same terms the sibling drafts
record their timings. The paths are real; the contents are second hand.
**The build agent does get the tree, and requirement 2 turns that into the
governing rule:** read both shipping forecasts and task 147's test file and
preserve what they do. Where this document and the file disagree, the file wins,
and the disagreement is worth reporting in the branch's reply.

## Figures and readings, given

Nothing here is to be measured.

| Reading | Value | Where it comes from |
|---|---|---|
| The fitting routine | `_ols_fit(ys)` — measure-agnostic OLS line over a series indexed `0..n-1`, stdlib only, returning `{n, slope, intercept, mean_x, sxx, s}` with `s = sqrt(SSE / (n-2))` | task 147, merged `74b07f5`, quoted in this draft's own task statement |
| The second copy | `revenue_forecast` inlined the same arithmetic on branch fleet/task-142.2, and **142 was narrowed to call `_ols_fit` instead** | the same statement |
| Names bound twice | `FORECAST_HORIZON_MONTHS`, `FORECAST_MEASURE`, `FORECAST_METHOD` — same name in both forecasts, and `FORECAST_MEASURE` differs in value (`"new_customers"` against `"net_revenue"`) | the same statement |
| Names spelled twice | `MIN_FORECAST_HISTORY_MONTHS`/`FORECAST_MIN_MONTHS` (both 24), `FORECAST_Z_95`/`FORECAST_Z` (**1.959964 against 1.959963984540054**), `FORECAST_CONFIDENCE`/`FORECAST_CONFIDENCE_LEVEL` (both 0.95) | the same statement |
| What `revenue_report()` returns per period | `orders` and `aov`, beside `net_revenue`, `refunded_amount`, `orders_with_refund`, at a granularity the caller chooses from hour/day/week/month | `research/candidates-metorik-gap-2026-09-16.md` (*"orders per period in `revenue_report`, rendered on the overview"*); `research/refund-coverage.md`, *What the API returns today* |
| The third forecast, unbuilt | *Order volume forecast at three, six and twelve months*, a bucket-A row, `suggested_paths` `api/analytics/services/analytics_engine.py` and `api/analytics/routes/orders.py` | `research/candidates-metorik-gap-2026-09-21.md` |
| Forecasting code in the orders surface | `[Ff]orecast` matched zero times across `api/analytics/routes/*.py` at `fd5a404` | that candidate's probes |
| Orders, and the span | 2,889,850 rows over 1,283 days, 2023-03-12 to 2026-09-15, every one carrying a `created_at` | that candidate's `hib_signal`, as of 2026-09-15 |

1,283 days is about forty-two months, so twelve months is extrapolated from
roughly three and a half times its own length — the ratio that makes the band
the interesting part of the answer in the two forecasts already built.

## The defect this draft describes, which is about names and not about arithmetic

A property of a forecast is stored as a property of the module. Git merges both
definitions cleanly, because they sit in different parts of the file; Python
keeps the last. `new_customer_forecast` therefore begins reading
`row["net_revenue"]` out of a `customer_report` row that has no such key, and
**nothing caught it**: 147's tests import none of the overwritten names, and the
damage runs through 147's production code at call time. It was found by
re-verification at the merge, not by any check on either branch. Two spellings
of one constant — `FORECAST_Z_95` beside `FORECAST_Z`, differing in the sixth
decimal place — is the same defect one step before it bites. And a third
forecast collides again; that third forecast is already on the candidate list.

## What test bites, and it is the first thing this draft settles

`contracts/deadly-digital-platform-api.yaml` check 5 is
`contracts/checks/new_test_bites.sh`. It requires the added test to FAIL against
the pre-change tree, and it refuses a real diff that adds no test at all: *"a
real branch that changes code and adds no test has a non-empty diff and must
still be refused with 1"*. Only a wholly empty diff is could-not-run.

**The pure extraction has no such test, and it cannot be a fleet task.** Delete
the duplicate constants, point both forecasts at one `_ols_fit`, change nothing
observable — and every test of what the module computes passes at both ends of
the branch. The arithmetic is identical before and after by construction; that
is the *point* of the change and it is also what makes it ungateable here. Check
1, `contracts/checks/spec_requirements_cited.py`, is unavailable for a second
reason: it needs a task row and a spec, which a hand change does not have.

**So the pure extraction is a hand change, and what gates it is `afcff19`'s
standard**, not this contract: the checks that do apply (`compileall`,
`contracts/checks/ruff_no_new_findings.py`, and
`contracts/checks/pytest_unit_per_file.sh` over `tests/unit` and
`tests/analytics`), plus identical collected test counts file by file on either
side of the change so nothing was dropped, plus a mutation per touched routine
showing the tests still bite. The commit message says which checks were omitted
and why; a silently partial gate reads as a full one.

**That conclusion cannot be delivered as this draft.**
`contracts/checks/draft_spec_shape.py` fails a draft carrying no fenced
`fleet-spec` block — *"The spec must declare work_type, repo, title and
writable_paths in machine-readable form"* — so a draft whose honest answer is
"do this by hand, do not queue it" is refused for being right. That is a defect
in the contract, recorded here rather than worked around by writing a block
nobody believes in.

**The reshaping that does carry an observable change is the third forecast, and
that is what the block above describes.** Once the measure, horizon, method
sentence and caveat travel with the call, a third forecast is addable without
touching either existing one — and *that* is testable by adding it. The test
bites in the ordinary way: `order_volume_forecast` and
`GET /api/analytics/orders/forecast` exist on no tree today. `[Ff]orecast`
matched zero times across `api/analytics/routes/*.py` at `fd5a404`, and neither
task 142 nor task 147 declares `api/analytics/routes/orders.py` writable, so
neither can have added one. The added test fails against the pre-change tree on
an import or a 404, and passes after. The refactor stops being a
behaviour-preserving cleanup nobody can gate and becomes the first half of a
feature that gates itself.

**The rejected alternative, and it is a near miss worth naming.** If task 142
merges with `FORECAST_MEASURE` bound twice, `new_customer_forecast` is broken at
call time on `main`, and a test asserting `result["measure"] == "new_customers"`
fails before the change and passes after it — a shape-1 bite with no new feature
attached, and a cheaper task than this one. It is **not** what the block rests
on, for a reason this draft cannot argue its way out of: the collision could not
be verified from here, and 142's narrowing may already have removed it. If it
has, that test passes against the pre-change tree, check 5 refuses the branch,
and £6 buys a refusal. The third forecast's test bites whether the collision is
live or not, which is why it was chosen. If the build agent finds the collision
live, requirement 1 repairs it and the assertion goes in as another case in the
**same** test file — `new_test_bites.sh` refuses a change that adds two.

## The judgement this spec makes, stated so a reviewer can disagree with it

**The order-volume series comes from `revenue_report()` at month granularity,
not from `daily_metrics`** — and the candidate's own rationale says the
opposite, so the disagreement is stated rather than buried. That row calls the
stored count the reason this is the cheapest of the three forecasts.
`drafts/sales-forecast-twelve-months.md` refuses the stored table for three
reasons that are facts about the tree, and two of them apply to a count exactly
as they apply to money: no analytics route reads `daily_metrics` for a figure,
and it is a cache with a repair path in
`api/analytics/services/dirty_dates.py` and
`api/analytics/services/metrics_repair.py`, so a fit on it inherits whatever
state the cache is in. The third reason — the stored column is gross where the
page is net — does not apply to a count, and is replaced by one that does: the
order count a merchant sees is `revenue_report()`'s, so a forecast whose last
historical point differs from the last bar on the page is wrong on the screen
even when the arithmetic is right. The cost is the one 142 accepted: an
aggregate over `orders` across the whole history rather than a read of forty-odd
stored rows — the query shape `GET /api/analytics/revenue` already runs for any
window a merchant picks, run once over the widest one.

**Why this contract.** `contracts/dd-order-filters.yaml` also makes
`api/analytics/routes/orders.py` writable and is ineligible twice over: it does
not make `api/analytics/services/analytics_engine.py` writable, which is where
every line of the fit lives, and it permits no new test file at all. The helper
goes in the engine rather than in a new `api/analytics/services/forecast.py`
because the named contract enumerates its writable paths instead of globbing
them and that file is not on the list.

---

### 1. Each forecast's measure, horizon, method sentence and caveat travel with the call

Those four, and the confidence level, the `z` constant and the minimum-history
floor beside them, stop being module-level names that one forecast can rebind
out from under another. They become properties of a particular forecast, bound
where that forecast is defined and passed to the shared arithmetic — a small
declared structure per forecast, a keyword argument set, or whatever the file's
own idiom makes readable. The mechanism is the agent's choice; the property is
not.

**The property to hold, and it is the whole requirement: no two forecasts share
a module-level name whose value differs between them, and adding a fourth
forecast requires adding no module-level name that could collide with a third.**
If any name in the readings table survives as a module-level binding that two
forecasts read with different intended values, this requirement is not met
however tidy the result looks.

`FORECAST_Z_95 = 1.959964` and `FORECAST_Z = 1.959963984540054` are **not** to
be unified into one value. They differ in the sixth decimal place, `z` is a
field in both payloads, and task 147's test file is on `protected_paths` and may
assert it. Each shipping forecast keeps the constant it ships today, carried as
its own property. Unifying them is a one-line change for a person who can edit
that test, and it is not this task's.

If a second fitting routine is on the tree — 142 was narrowed to bring none, and
that narrowing was not verifiable from here — collapse it into `_ols_fit` and
delete it. Its docstring asks for exactly that. If there is only one, this
paragraph costs nothing.

### 2. The two forecasts that already ship return exactly what they return today

`new_customer_forecast`'s response comes back key for key and value for value,
and the same holds for `revenue_forecast`. `api/tests/**` is on
`protected_paths` and `creatable_paths` admits only a **new**
`api/tests/analytics/test_fleet_*.py`, so task 147's test file cannot be touched:
it asserts `result["measure"] == "new_customers"` and reads
`point["new_customers"]`, and it must pass unedited.

**Read those test files before editing the engine.** The build agent can read
`api/tests/**` even though it cannot write there, and the files under it are the
specification of what must not move: every literal they assert — the measure
name, the point key, `z`, the confidence level, the field names — is a value
requirement 1 must carry rather than change.

Share only what the two functions already do identically. Where their payloads
differ, the difference is carried as a per-forecast property or left in the
per-forecast function; it is not reconciled by making one emit the other's
shape. **If making the fit shared requires editing a test, the design is wrong,
not the test.**

### 3. The order-volume series is the monthly `orders` count `revenue_report()` already returns

A helper in `api/analytics/services/analytics_engine.py` calls
`revenue_report()` at month granularity over the tenant's full order span and
reads the per-period order count from the rows it returns. It defines no second
order history: no `GROUP BY` of its own over `orders`, no read of
`daily_metrics`, no count derived from anything else.

**The tenant's span is obtained the way `revenue_forecast` already obtains it**,
by calling whatever that function calls rather than by writing a second way to
ask the same question. Two derivations of "the tenant's history" that can
disagree is the defect this draft is about, one level up.

**The key's name is to be read from the file, not from this spec.**
`research/candidates-metorik-gap-2026-09-16.md` and `research/refund-coverage.md`
both describe `revenue_report()`'s period rows and neither is the tree.

### 4. The partial month, the band and the short-history refusal follow the two forecasts that already ship

Three behaviours, each already decided — the requirement is that the third
forecast does not decide them again differently:

* **The incomplete month is excluded from the fit and named in the response**
  with its partial count beside it, rather than dropped silently.
* **Every emitted point carries a lower and an upper bound** from the textbook
  prediction interval for an OLS line — `se = s * sqrt(1 + 1/n + (x0 -
  mean_x)^2 / sxx)`, `band = yhat ± z * se` — computed from the `s`, `n`,
  `mean_x` and `sxx` `_ols_fit` already returns. No point is emitted without a
  band. **The lower bound is not clamped at zero**, for the reason
  `drafts/new-customers-forecast.md` gives about counts: a negative lower bound
  is the model saying a straight line with normal residuals does not generate
  this series, and clamping narrows the stated uncertainty exactly where the
  model is least believable.
* **Fewer than twenty-four complete months, or fewer than two distinct counts
  among them, and the response carries the history and a stated reason with the
  forecast list empty** — not a flat line, not zeros, not a band of infinite
  width. Twenty-four because the longest horizon is twelve. The real tenant has
  about forty-two months and never reaches this path, which is why it must be
  built and tested rather than assumed unreachable: a new tenant hits it on day
  one.

Emitted values are not rounded: the fit is over integers and produces reals, and
rounding for display belongs where the axis is.

### 5. Three horizons are three reads of one fit, and the twelve monthly points ship beside them

One fit, one `_ols_fit` call, one residual standard deviation. The three
horizons are the point estimate and band read off that fit at months three, six
and twelve — named as such in the response so a caller does not have to index
into a list and count — and the twelve consecutive monthly points ship beside
them so the curve is drawable.

Emitting both settles the candidate's unasked question cheaply on the API side —
*"whether the three horizons are wanted as three numbers or as one curve with
three markers"* — without settling it on the screen, where the decision stays
open.

Beside the points: the fitted history as the list of (period, count) pairs
actually used, `n`, the slope, the intercept, the residual standard deviation,
the confidence level, `z`, the measure name, the excluded partial month, the
method sentence and the caveat. A forecast that arrives without the series it
was fitted on cannot be argued with.

The measure is the order count per month. The caveat is that the fit carries no
campaign or promotion term, so the interval covers scatter around a straight
line through this history rather than the effect of a draw being run or not run;
it is a field in the payload, where whoever holds the chart reads it, not a
docstring. **`z` is 1.959963984540054**, the fuller of the two constants, so a
new forecast takes the more precise value rather than propagating a truncation —
requirement 1 is why the two that ship keep theirs.

### 6. `GET /api/analytics/orders/forecast`, declared ahead of any path-parameter route

Add the route to `api/analytics/routes/orders.py`, mounted beside the routes
already there and taking its tenant resolution on the same terms. No existing
route's response changes shape, no key is renamed, and `revenue_report()`'s own
return value is unchanged — the helper calls it, it does not learn about
forecasting.

**This module very likely has a path-parameter route, so the ordering hazard is
live** — the analytics dashboard has an order detail page, so something serves
it. FastAPI matches in declaration order, so a literal `/orders/forecast`
declared after a route capturing an order identifier is never reached: the
request lands in the detail handler with `forecast` as the id and the caller
gets a 404 or a validation error, with nothing in the diff looking wrong.
**Read the module's route list and declare the literal first** — the same trap
`drafts/new-customers-forecast.md` documents for
`api/analytics/routes/customers.py`. Record the new endpoint wherever that
module lists its endpoints.

### 7. One new test file, and what it must assert

One new file under `api/tests/analytics/`, matching `test_fleet_*.py` — e.g.
`api/tests/analytics/test_fleet_order_volume_forecast.py`. The contract's
`creatable_paths` allows that glob and nothing else, no existing test may be
touched, and `new_test_bites.sh` refuses a change that adds two files. Over
fixtures whose monthly order series is known, it asserts the properties that
would otherwise ship silently:

* the monthly series the helper fits equals `revenue_report()`'s own per-period
  order counts over the same span, month for month, summed in the test
  independently (requirement 3);
* a series with a known slope recovers that slope, and the three horizon
  readouts are **identical** to the third, sixth and twelfth of the twelve
  monthly points — one fit read three times, not three fits (requirement 5);
* the band at month twelve is strictly wider than at month six, and month six
  strictly wider than month three (requirement 4);
* a partial final month is excluded from the fit and reported separately, and
  the fitted slope is identical to the slope over the same series with that
  month absent (requirement 4);
* a twelve-month history returns the requirement 4 refusal with an empty
  forecast list, rather than three numbers;
* **and, in one process, that two forecasts report two different measures** —
  call the new forecast and `new_customer_forecast` over the same fixtures and
  assert each returns its own measure name and its own point key. That is the
  assertion that would have caught the collision at the top of this document,
  and it is requirement 1's only externally visible property.

A test that asserts only that the endpoint returns 200 satisfies the bite check
and establishes none of this.

---

## What this task must not do

* **No migration, no new column, no write of any kind.** Every series is read.
* **No second definition of "an order".** An agent that writes its own
  `GROUP BY` because it is easier than calling `revenue_report()` has built the
  disagreement this row exists to avoid, in the file this draft is about.
* **No second fitting routine, and no second forecasting model.** `_ols_fit` is
  the arithmetic. An agent adding an exponential-smoothing variant "for
  comparison" has built two numbers for one question.
* **No change to any existing response.** Requirement 2 is a gate, not a
  preference. `revenue_report()` keeps its keys and gains no argument beyond the
  granularity and window it already accepts.
* **No page and no proxy.** `platform/**` is protected here. The candidate
  suggests `platform/app/(dashboard)/analytics/orders/page.tsx`; that path is
  correct and belongs to `contracts/dd-analytics-frontend.yaml`. The surface is
  a separate draft, written once this response shape can be quoted rather than
  predicted. **Until it lands this reaches nobody**, stated rather than
  discovered.
* **No touching `api/app.py`, the email surface or the GDPR path.** All floored,
  none needed.
* **No unifying the two `z` constants.** Requirement 1 says why.

## What this task does NOT include, and must not claim

**Nobody has timed `revenue_report()` at month granularity over the full
history.** No figure for it exists in this fleet, the build agent has no shell
and no database, and a requirement asking for one would be a requirement that
cannot be cited — `contracts/draft-spec.yaml` records two dead runs, £9.89, that
were exactly that mistake. So it is not numbered, and the agent must not cite it,
claim it, or write a `spec:` token over it.
`drafts/restrict-the-acquiring-order-cte-to-the-window.md` records that the
acquiring-order lookup in these aggregates is unbounded in history by design, so
the full-span call is the widest case of a shape nobody has read a clock on.
Whoever reviews the branch should call the endpoint once against the real tenant
and read the wall-clock; if it is slow, fit on a narrower span and say so in the
payload.

**Nor is the size of this diff established.** The refactor's deletions count
against `max_diff_lines: 400` as well as its additions, and a third forecast
plus a route is most of the rest. Requirement 1 is worded as it is partly for
that reason: rebind properties, do not rewrite two working functions.

## Before this is queued

* **Task 142 merges first, and this must not be queued against a tree it has not
  landed in.** Both write `api/analytics/services/analytics_engine.py`.
  Requirement 1's subject is the *pair* of constant sets and one of them arrives
  with 142; requirement 2 names two shipping forecasts to preserve. Queued
  first, the agent finds one forecast, no collision, and a requirement with
  nothing to hold. The queue-time check is cheap: `[Ff]orecast` matches in
  `api/analytics/routes/revenue.py`.
* **Read the collision before believing this document about it.** Whether
  `FORECAST_MEASURE` is bound twice on `main` decides whether requirement 1
  repairs a live defect or prevents a future one, and it was not verifiable from
  this run. Either way the block stands; only the branch's reply changes.
* **`auto_merge: false` is set above, against this contract's default.** It is
  wrong for this one for a sharper reason than it was for the two forecasts
  before it: this task edits two functions that already ship, and requirement 2
  — that their responses are unchanged — is exactly the kind of property every
  gate in the list can pass over. `pytest_unit_per_file.sh` catches a changed
  value that a protected test happens to assert, and says nothing about the
  fields no test names.
* **The unasked question from all three forecast rows is still unasked:**
  whether a twelve-month forecast over a prize-competition store is a number HIB
  would act on or a chart it would glance at. Order volume is the row where a
  campaign term matters most and a linear fit sees least; requirement 5's caveat
  labels that absence and does not remove it.
* **The pure extraction is still owed, by hand.** This task makes the seam and
  proves it with a third forecast. It does not remove the two shipping
  forecasts' private divergence in `z`, and it should not — that tidy-up is
  three lines and a mutation test under the standard named above.
