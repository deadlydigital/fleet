# Stop the orders page resetting its own pagination on mount

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
contract: dd-analytics-frontend.yaml
title: The orders page stops resetting its own pagination on mount
writable_paths:
  - platform/app/(dashboard)/analytics/orders/page.tsx
```

## Why this contract

`contracts/dd-analytics-frontend.yaml` is the only contract in `contracts/`
that makes `platform/app/(dashboard)/analytics/orders/**` writable — the
backend contracts `contracts/dd-order-filters.yaml` and
`contracts/deadly-digital-platform-api.yaml` each list `platform/**` among
their protected paths, because neither of them can run anything that renders a
page. So the choice here is not between two
boundaries that both fit; it is the one boundary whose verification list
contains `vitest run` and `new_test_bites.sh`, which is what this change needs.

The price of that choice is worth stating, because it is the whole shape of
the work. `platform/__tests__/**` is protected under that contract and is on
`023_platform_floor.sql`, so **the existing test cannot be edited**.
`creatable_paths` allows exactly one new file matching
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx`, and
`contracts/checks/new_test_bites.sh` requires that file to fail against the
pre-change tree. §2 below is therefore not optional colour — it is the only
part of this task that can establish the defect is gone.

## What is wrong

`platform/app/(dashboard)/analytics/orders/page.tsx` debounces its filter
state: when a filter changes, a timer starts, and ~300ms later the page sends
the request and resets the pager to page 1. Resetting the pager is correct and
is required by `drafts/order-filters-frontend.md` §2.2 — *"Filtering from page
7 of an unfiltered list into a two-page result renders an empty table over a
summary saying there are hundreds of matches."*

The bug is *when* it runs, not *what* it does. A `useEffect` runs on mount, as
every `useEffect` does. So the page mounts, the timer starts against the
initial filter values, and 300ms later it resets the page to 1 — having been
given no filter change at all. Nothing on screen changed, and the page issued
a state write anyway.

A reader who clicks a pager button inside that 300ms window loses the click.
The sequence is: mount → click page 3 → page state becomes 3, a request for
page 3 goes out → the mount timer fires → page state becomes 1 → a request for
page 1 goes out → the table renders page 1. The user asked for page 3, watched
something load, and is sitting on page 1. **There is no error state, no toast
and no console warning**, so the only signal available to them is that the
pager did not do what pagers do. For a merchant scanning an order list that is
a wrong page presented as a right one.

Two things about the provenance, because both change how this should be read:

* **This is shipped behaviour on `main`, not a regression from a pending
  branch.** The `setPage(1)` inside the debounce timer arrived in `0f2a254` on
  23 Aug 2026. Task 53 — the four order filters, specified in
  `drafts/order-filters-frontend.md` — only added three more filter values to
  the same timer's dependency list on 10 Sep 2026, which widens the set of
  values that can start the timer but does not create the mount-run. Reverting
  task 53 would not fix this.

* **It is provable without a browser, and it has already cost the fleet a
  run.** `platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx`
  clicks pager button 3 and fails roughly one run in three — measured at 4
  failures in 6 runs on one worktree and 6 in 6 on another. Raising its
  `waitFor` from 3s to 20s does not help, which is the diagnostic that matters:
  a late click eventually arrives, and a lost one never does. Task 84's
  re-verification failed on this test on 13 Sep 2026, while the same suite
  passed for tasks 83 and 86 inside the following 25 minutes. So the defect is
  two things at once — a wrong page for a merchant, and a check that cannot be
  trusted to judge anything else that touches this page.

The finding this spec is drawn from cites section *"The orders page resets its
own pagination on mount"* of `research/` document
`candidates-orders-pagination-reset-2026-09-13.md` at `71bd403`. That file is
not present in this worktree, so nothing above is quoted from it; the timings
and run outcomes are restated from the candidate as given and should be
re-measured by whoever implements this rather than treated as settled.

## What was and was not read for this spec

The runner's path listing for this run was read, and every path cited in this
document comes from it. **The contents of
`platform/app/(dashboard)/analytics/orders/page.tsx` were not** — no source
checkout of `deadly-digital-platform` existed in this worktree while this was
written. So this spec deliberately names no line numbers, no hook variable
names and no local identifiers. It states the behaviour to change and the
behaviour to preserve; the implementer reads the file and chooses the shape.

Where the two rules below could be satisfied by more than one implementation,
that is intentional and §1.3 says which properties the choice must have.

## What to build

All of it is in `platform/app/(dashboard)/analytics/orders/page.tsx`, plus one
new test file. There is **no** proxy change, no backend change, no new
endpoint and no new dependency. `platform/app/api/analytics/orders/route.ts`
is not touched, and no parameter name is added, removed or renamed — so
`contracts/checks/proxy_passthrough.py` has nothing to react to and must stay
green.

### 1. The page reset stops firing when nothing was filtered

**1.1 The debounced effect must not reset the pager on its first run.**
Mounting the page, touching nothing, must produce zero calls that set the page
number. The page's initial page value is whatever it is today; it is not
re-asserted.

**1.2 The reset must be driven by a filter value actually changing, not by the
effect running.** The two acceptable shapes are a first-run guard (a ref that
is `false` until after the first effect run, checked before the reset) or
splitting the page reset out of the debounce so it is triggered by the filter
setters themselves. Either is fine. What is not fine is comparing the current
filter values against a hard-coded "defaults" object: a page opened from a URL
carrying filters, or from any persisted state, would then read as "not
default" on mount and reset the pager — the same bug with a narrower trigger.

**1.3 A pager click during the debounce window must survive it.** This is the
property the change exists for, and it is the one to test against. After
mount, a click on a pager button leaves the page state at the clicked page and
leaves it there — no later timer, from that mount or from any filter-derived
effect that did not observe a changed filter, may overwrite it. Whichever
shape §1.2 takes must hold this even when the click lands 1ms after mount and
when it lands 299ms after mount.

**1.4 Changing a filter must still reset the pager to page 1.** This is
`drafts/order-filters-frontend.md` §2.2 and it does not change. All of
`search`, `status`, `payment_method`, `country`, `coupon` and `has_discount`
reset the pager when their value changes, and clicking the value in a table
cell to set a filter — the affordance specified in
`drafts/order-table-cells-set-the-filters.md` — goes through the same state and
inherits the same reset. Do not introduce a second path to the request that
bypasses it. A fix that stops the mount reset by stopping the reset is a worse
bug than the one it replaces, because an empty table over a summary claiming
hundreds of matches is also silent.

**1.5 The debounce itself does not change.** Same delay, same set of values
watched, same request shape, same cleanup on unmount. This task is about one
unconditional call on one run of one effect. Widening it into a rewrite of the
page's filter state is out of scope and there is no check here that would
catch a regression introduced by one.

### 2. One new test, and it must bite

**2.1 Add exactly one file,
`platform/__tests__/unit/analytics/test_fleet_orders_pager_mount.test.tsx`.**
The name matches `test_fleet_*.test.tsx`, which is the only glob
`contracts/dd-analytics-frontend.yaml` makes creatable, and it ends in
`.test.tsx` rather than `.tsx` because `platform/vitest.config.ts` collects
`__tests__/unit/**/*.{test,spec}.{ts,tsx}` and would never run the latter.

**2.2 Do not modify
`platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx`, or any
other existing test.** `platform/__tests__/**` is protected by the contract and
floored by `023_platform_floor.sql`; a diff that touches it is refused at the
boundary, before any check runs. If that file's flakiness disappears as a
consequence of §1 — it should, since the lost click is what it is failing on —
that is a welcome side effect and is **not** evidence to cite. The reason is in
`specs/unattended-operation.md` and is the argument
`contracts/dd-analytics-frontend.yaml` makes for `new_test_bites.sh`: a test
that already exists passing more often is not a discriminator between two
trees.

**2.3 The new test asserts §1.3 directly, not a proxy for it.** Render the
orders page, click a pager button for page 2 or later immediately on mount, and
assert that after the debounce window has fully elapsed — advance past 300ms,
do not merely `waitFor` — the request the page issued last, and the page the
pager reports as current, are the clicked page and not page 1. Asserting "page
3 rendered at some point" is what the existing test does and it is exactly the
assertion the bug slips past, because page 3 *does* render, briefly, before
page 1 replaces it. **The assertion must be about the state after the window
closes.**

**2.4 It must fail against the pre-change tree.**
`contracts/checks/new_test_bites.sh`, driven by
`contracts/checks/vitest_one_file.sh`, runs this file against the tree without
the change and requires a failure. A test written with real timers and a
`waitFor` will *sometimes* fail there, which is not the same thing — an
intermittent bite is a check that passes the contract by luck. Use fake timers,
or otherwise make the ordering deterministic, so the test fails on the old tree
every run and passes on the new one every run.

**2.5 Cite the requirements.** `contracts/checks/spec_requirements_cited.py`
runs first in this contract's verification list and fails the run if a numbered
requirement above is cited by no added line. Annotate the lines that implement
each one — `// spec:1.2` and so on — in both the page and the test. It proves a
claim was made rather than met, which is the point: an omission becomes
written and attributable instead of silent.

## Before this is queued

Two things a person should decide, because nothing on the unattended path will.

**The existing test stays flaky if §1 is wrong in a way §2 does not catch.**
`platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx` runs in
the same `vitest run` that gates this task, so a run of this contract is also a
sample of that test. One green run is one sample of something that failed 4
times in 6; it is not a demonstration. If the intent is to close the
false-refusal problem as well as the merchant-facing one, somebody should run
that file 10 times after the merge and record the result — that is a decision
about a check's trustworthiness, not a line of code, and it does not belong in
this diff.

**This is small, and the contract's cap is not.**
`contracts/dd-analytics-frontend.yaml` allows 600 production lines and 1200
test lines. The change described in §1 is plausibly under 10 lines of the page.
A diff that arrives much larger than that has done something this spec did not
ask for — which is what happened on task 55, and what §1.5 exists to forbid —
and is worth reading before it merges rather than after.
