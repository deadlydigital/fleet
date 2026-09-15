# Draft spec — the dashboard runs one reconciliation query per manifest ever received

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Answer whether the manifest loop can be window-bounded, then fold the 36 per-manifest platform-breakdown queries into one grouped query
writable_paths:
  - api/analytics/services/reconciliation.py
```

## What is wrong

A dashboard request issues **48 statements and 36 of them are the same one** —
the platform-side status breakdown, 2.5 ms each, **91 ms total**. The count is
**36 at a 30-day window and 36 at a 180-day window**, so it is not a function of
what was asked for. It is one query per row in
`analytics_2.reconciliation_manifests`, which holds exactly 36, all at `day`
grain.

`_platform_breakdown` in `api/analytics/services/reconciliation.py` is called
once per period from `verify_period`, and the loop above it iterates every
manifest with no window bound:

    for m in manifests:
        v = verify_period(db, tenant_id, m, coverage, tenant_timezone, settle_hours)

The comment beside that code anticipates the growth itself — "~40 rows for a
two-year store instead of ~730" — and **730 is the day-grain number**. At 2.5 ms
a query that is **~1.8 s per dashboard request**, arriving one manifest a day, on
a page that is **1.71 s today**.

`research/candidates-dashboard-remaining-2026-09-14.md` §"Daily — the dashboard
runs one query per manifest ever received" carries the instrumented run, at
verified sha `fd201331bb7c322c05d5074a8b2139c8cf0a92e9`. The line numbers it
gives — `_platform_breakdown` at `:415`, the `verify_period` call at `:618` — are
**as recorded in that document and were not re-read for this spec**; no
read-only checkout of the repository was present in the worktree this spec was
written in. Re-locate both before trusting the offsets. The function and the loop
are what the candidate's probes assert exist, not the line numbers.

## The correctness question comes first, and the answer does not decide the change

The candidate was filed with an open question in front of it: **can the loop be
bounded by the request window at all**, or does narrowing it silently turn an
unverified period into an unmentioned one? The block answers "is what we were
told complete?", which is a question about coverage over **all history**, not
over the window. A manifest the store sent for March that the platform never
reconciled is a discrepancy whether or not the reader is looking at March, and a
window bound would delete it from the page rather than report it.

That question must be answered in writing (requirement 1). **It does not decide
what this task builds**, and stating why is the point of this section:

* **Bounding the loop is worth almost nothing today.** 36 manifests at day grain,
  a 30-day window: bounding takes 36 queries to about 30. That is ~15 ms off a
  1.71 s page, and it buys only a slower growth rate later.
* **The fold is worth the whole of it.** One grouped query takes 36 to **1**, and
  takes the two-year figure from ~730 to **1**. It changes no semantics, it
  survives whatever the answer to the coverage question turns out to be, and it
  is the shape the candidate itself names as the fallback.

So: **fold regardless**. If requirement 1 concludes the loop *can* be bounded
without loss of meaning, that is a finding to file as its own task with its own
spec — not a change to add here. This contract auto-merges with nobody reading
the spec (`contracts/deadly-digital-platform-api.yaml`, and the trade is written
out at length in that file and in `specs/unattended-operation.md` §7), which is
exactly the wrong place to land a change to what a trustworthiness page reports.

## Requirements

### 1. State, in the branch, whether the loop can be bounded by the window

Read what the reconciliation block actually renders and answer the question with
the reading beside the answer, not as an opinion. At minimum:

* What the loop's result is used for downstream of `verify_period` — whether
  every manifest reaches the response or only ones that fail verification.
* Whether the dashboard payload presents the block as coverage over all history
  or over the requested window, and whether any consumer of
  `api/analytics/routes/dashboard.py` or `api/analytics/routes/manifest.py`
  distinguishes "verified clean" from "not examined".
* What a reader of the page would conclude about a period that a window bound
  would drop.

Then state the verdict in one of two forms: **"bounding changes what the block
means, because …"** or **"bounding preserves what the block means, because …,
and is filed as a separate task"**. Either verdict satisfies this requirement.
**Neither verdict authorises a window bound in this diff.**

### 2. One grouped query replaces the per-manifest calls

`_platform_breakdown` is currently one statement per period. Replace the 36
single-period executions with **one** execution that returns the same breakdown
for all periods at once, keyed so each period can be handed back to
`verify_period` unchanged.

`verify_period`'s own contract — what it takes, what it compares, what it returns
per manifest — **does not change**. This is a change to where the platform-side
numbers come from, not to what is done with them.

### 3. Periods are keyed by manifest, not by date_trunc, and the reason is not stylistic

The grouping key must be the **manifest's identity**, with the period's resolved
boundaries carried in the query as data — a `VALUES` list or `unnest` of
`(manifest_id, period_start, period_end)` joined against orders, grouped by
`manifest_id` and status.

Grouping by `date_trunc(grain, created_at)` is the obvious shortcut and it is
wrong here, for two reasons that both exist in the data today or in the schema
today:

* **Manifests may overlap.** Nothing in
  `api/analytics/migrations/versions/v0012_reconciliation_manifests.py` makes the
  periods disjoint, and a re-send or a backfill produces two rows covering the
  same day. An order inside both must be counted for both, which a single
  `GROUP BY` over a truncated timestamp cannot do.
* **Grain is a column, not a constant.** All 36 rows are `day` today. The code
  path supports others, and a mixed-grain table breaks any single truncation.

Resolve `tenant_timezone` and `settle_hours` into the boundary values **in
Python, per manifest, exactly as the current per-period path does**, and put the
resolved timestamps in the rows. Do not re-derive boundaries inside the SQL. That
keeps this change away from the one piece of the calculation that is easy to get
subtly wrong and impossible to notice.

### 4. A period with no matching orders still produces a breakdown, and this is how the fold breaks

The per-period query returns an empty-or-zero breakdown for a period the platform
has no orders in. A grouped query returns **no row at all** for that period.

If the fold lets those periods fall out of the result, a manifest that says "the
store sent us 400 orders" and a platform that holds none stops being a
**discrepancy** and becomes a **missing entry** — the single most consequential
way this change can pass every test and still lie on the page. Every manifest in
the input must appear in the output of the folded call, with the same
zero-or-empty value the per-period call produced.

Assert this on a fixture, not by inspection. It is requirement 7's first case.

### 5. Nothing else in the reconciliation service moves

Not the status set the breakdown is computed over, not the settle-hours
handling, not `coverage`, not the comparison `verify_period` performs, not the
manifest ordering in the response, not the shape of any value returned to the
route. One query becomes one grouped query; that is the whole diff.

In particular: **do not filter the manifest list**, do not add a `LIMIT`, and do
not skip manifests that verified clean on a previous request. Each of those is a
defensible idea and each is a different task.

### 6. The identity is proved on production data, per period, with the dataset named

Run the reconciliation block against the tree before the change and against the
tree after it, on a real tenant schema, and show the per-manifest results agree
**manifest for manifest and status for status** — not in aggregate. An aggregate
comparison is precisely the mistake
`research/EVIDENCE-refund-coverage-manifests.md` §"Reading 1" documents avoiding
on this same table, and for the same reason: totals can agree while the periods
they are attributed to do not.

Cover, and say so explicitly:

* all 36 manifests on the tenant used, not a sample;
* at least one period the platform holds no orders in, per requirement 4 — and if
  no such period exists on the real schema, say that and prove the case on a
  fixture instead;
* both a 30-day and a 180-day window, to demonstrate the count is now 1 at each
  and the results are unchanged at each.

Name the schema and the windows in the branch. `analytics_1` and `analytics_2`
hold different manifest counts and very different coverage — an identity claim
with no named dataset is not a claim.

### 7. Report the statement count and the time, before and after

Give, on the same box and the same windows as the figures at the top:

| | before | after |
|---|---|---|
| statements per dashboard request | 48 | |
| executions of the platform breakdown | 36 | |
| time in those statements | 91 ms | |
| whole-page time | 1.71 s | |

and state the projected two-year figure that replaces "~1.8 s per request".

If the page time does not move measurably, **say so**. 91 ms of 1.71 s is 5%, and
the honest result of this task may well be "the growth curve is fixed and today's
page is unchanged". That is the finding, not a failure, and the research document
already records that at 1.71 s the page is not urgent.

### 8. One new test, and it fails against the tree before the change

Create **one** file, `api/tests/analytics/test_fleet_reconciliation_breakdown.py`.
This contract's `creatable_paths` admits `api/tests/analytics/test_fleet_*.py`
and nothing else; every existing file under `api/tests/**` is protected and none
may be edited — including `api/tests/analytics/test_reconciliation_manifest.py`
and `api/tests/analytics/test_reconciliation_level3.py`, which are the existing
coverage this change must keep green.

`new_test_bites.sh` runs the new file against the tree before the change and
requires it to **fail** there. An identity test passes before and after and
proves nothing. What discriminates is **the number of statements executed**:
build a tenant with N manifests, count the platform-breakdown executions for one
verification pass, and assert the count does not scale with N. That assertion is
false on the current tree by construction.

Alongside it, in the same file, assert requirement 4 — a manifest whose period
contains no platform orders is present in the result with a zero breakdown, not
absent from it. That case is the one a careless fold drops, and it is the one
nobody will notice without a test.

## What this does not cover

* **Bounding the loop by the window.** Requirement 1 answers whether it is
  possible; it is out of scope to do it either way. See the section above for
  why the answer does not change what gets built.
* **`api/analytics/routes/dashboard.py` and `api/analytics/routes/manifest.py`.**
  Neither changes. The response is identical by requirements 2 and 5, so no route
  and no frontend page moves — which is also why neither is declared writable.
* **An index or a migration.** The statement is 2.5 ms; there is nothing here for
  an index to fix, and `api/analytics/migrations/**` is protected by this
  contract in any case. A branch that proposes one has misread the problem — it
  is 36 executions of a fast query, not one slow query.
* **The other 12 statements on the dashboard.** `top_products` is the largest of
  them and is its own candidate, drafted in
  `drafts/price-the-top-products-covering-index.md`. Nothing here touches it.
* **Whether anyone reads the reconciliation block at all.** The research document
  records this as an unasked question, and it is the one that would decide
  whether the block is worth a line of work or none. Deadly Digital holds no
  event, session or page-view table on any schema, so it cannot be answered from
  the database and is not answerable inside this task.

## How this will be checked

`contracts/deadly-digital-platform-api.yaml` runs, in order: the
requirement-citation check, `compileall` on the changed Python, ruff with no new
findings, `tests/unit` per file, `new_test_bites.sh`, and `tests/analytics` per
file (34 files, 675 tests). `max_diff_lines` is 400 production lines, with the
added test budgeted separately; this change should be a small fraction of that,
and a diff approaching the cap is a signal the scope grew past requirement 5.

Cite the numbered requirements above in the diff. The first check reads the spec
and reports requirements cited nowhere, and **it is the only check that reads it
at all** — this contract sets `auto_merge: true`, so no person compares the diff
to this document before it ships.

`api/CLAUDE.md` forbids suite and directory pytest runs on this host; the
per-file runner exists for that reason and is what the contract calls.

## Objectives

`dd-trustworthy`. Not cost-discipline: the queries run on a box that is already
paid for and the change adds no request, no fixed cost and no dependency. What
this affects is whether the page a merchant opens to check that their data is
complete stays openable as their history grows — 36 queries today, 730 in two
years, for an answer one query can give.
