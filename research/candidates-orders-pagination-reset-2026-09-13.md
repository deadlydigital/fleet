# The orders page resets its own pagination 300ms after it loads

**One candidate, by hand.** Found on 13 Sep 2026 while diagnosing why task 84's
re-verification disagreed with the run that built it, not by a producer reading
a gap list. It is a correctness defect in shipped code and it is nobody's task:
the branch that surfaced it does not touch the effect, and the test that caught
it was written by task 53 for something else entirely.

## The orders page resets its own pagination on mount

`platform/app/(dashboard)/analytics/orders/page.tsx:219-228`:

```tsx
useEffect(() => {
  const t = setTimeout(() => {
    setDebouncedSearch(search)
    setDebouncedPayment(paymentMethod)
    setDebouncedCountry(country)
    setDebouncedCoupon(coupon)
    setPage(1)
  }, 300)
  return () => clearTimeout(t)
}, [search, paymentMethod, country, coupon])
```

A `useEffect` runs on mount as well as on change, so this timer is armed the
moment the page renders, with all four filter boxes empty, and fires 300ms
later. `setPage(1)` is unconditional: it does not ask whether a filter actually
changed, and there is nothing in the closure that could tell it. The three
`setDebounced*` calls are harmless on mount — they set empty to empty — and
`setPage(1)` is harmless only while the page is still on page 1.

It is not harmless if the reader got somewhere else first. A click on a pager
button inside that 300ms window sets `page`, fires the fetch for it, and is then
overwritten by the timer: the page requests page 3 and then requests page 1
again, and what the reader is left looking at is page 1.

The `setPage(1)` predates the filters. `git blame` puts it in `0f2a254`
(23 Aug 2026, "orders list and detail (A2)"), when `search` was the only
debounced box; task 53 (`2d51cfd`, 10 Sep) added the other three to the same
timer. Neither change is wrong on its own and the defect belongs to neither.

## How it was found, and the measurement

`platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx > resets to
page 1 when a filter changes` clicks pager button `3` and waits for a request
carrying `page=3`. The click and the timer land in either order, so the test is
a coin flip. Measured 13 Sep 2026, same directory, same commit, same command:

| tree | `vitest run` on that file |
|---|---|
| task 84's merged tree | 4 failed, 2 passed of 6 |
| `main` alone | 6 failed of 6 |
| `main`, the test's `waitFor` raised 3s → 20s | 3 failed of 4 |

Raising the timeout does not help, which is the finding: it is a lost click and
not a slow machine. Instrumenting the MSW handler shows all three requests:

```
?…&page=1…   mount
?…&page=3…   the click
?…&page=1…   the timer, 300ms after mount
```

The fleet saw the same thing from the outside the same evening — the suite
passed task 83's re-verification at 21:05, failed task 84's at 21:07, and passed
task 86's at 21:28, on one box, minutes apart, on trees that differ only in
files this test does not read.

## Why this is its own row and not part of task 84

Task 84 changes `orders/page.tsx`, so the temptation is to fold the fix into it.
Three reasons not to. The defect is on `main` and fails there without task 84's
diff present. Task 84's contract makes the test file protected, so the branch
cannot touch the test that proves the fix. And a correctness change smuggled
into a feature branch is the thing that makes a later `git bisect` useless —
`principles.md` ranks a wrong number above a missing one, and this is a wrong
page rather than a missing one.

## What the work is

Make the mount run of that effect not reset the page: a `useRef` first-run
guard, or splitting the debounce from the reset so the reset is driven by the
filter values actually changing. The test already exists and already bites; it
should stop being a coin flip without its assertions being weakened, and the
`waitFor` on `last()` is worth rereading while there — an assertion on the most
recent request is an assertion that no later request may arrive, which is a
stronger claim than the test means to make.

```fleet-candidates
source:
  document: research/candidates-orders-pagination-reset-2026-09-13.md
  sha: 71bd403
  repo: fleet

ordering: unranked

objectives_considered: >
  This is dd-trustworthy and not dd-feature-parity, and the distinction is the
  one principles.md ranks rather than a label chosen for convenience. Nothing is
  missing from the orders page: the pager is built, it works, and a reader who
  waits 300ms before clicking gets the page they asked for. What is wrong is
  that the page silently undoes an action the reader took and shows them
  something other than what they asked for, with no error and nothing in the UI
  to say it happened — which is the shape objectives-2026-Q4.yaml describes when
  it warns that parity work must not outrank correctness work by default. I
  weighed dd-feature-parity and rejected it: no Metorik row asks for this, it
  closes no gap, and filing it as parity would put it behind seven rows that add
  reports. I weighed cost-discipline and it is untouched — the fix is a guard in
  one component and adds no query, no request and no fixed cost. dd-first-revenue
  does not apply: this is HIB's own store, not the unsigned agency partner's.

unasked_question: >
  Nobody has asked whether a merchant has ever hit this, and nothing on this box
  could answer it. DD holds no event, session or page-view table on any schema,
  so there is no way to count how often somebody clicked a pager button within
  300ms of the orders page settling — and that number is the whole case for
  where this should rank. The honest position is that the defect is certain and
  its frequency is unknown: it is provable from the code and from a test that
  fails one run in three, and unmeasurable in production until something records
  what merchants click. It is also worth asking whether anyone opens the orders
  list past page 1 at all, which is the same missing observation one level up,
  and would decide this row's priority rather than its correctness.

candidates:

  - title: Stop the orders page resetting its own pagination on mount
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    verified_sha: 211d24a6a759049c391c80c98f7b8115eabf72d3
    band: daily
    rationale: >
      The debounced filter effect in the orders page runs on mount, as every
      useEffect does, and its timer calls setPage(1) unconditionally 300ms
      later. A reader who clicks a pager button inside that window has their
      click overwritten: the page requests their page, then requests page 1
      again, and leaves them on page 1 having shown no error. This is shipped
      behaviour on main, not a regression from any pending branch — the
      setPage(1) is from 0f2a254 on 23 Aug 2026 and task 53 only added three
      more boxes to the same timer on 10 Sep. It is provable without a browser:
      the existing test at test_fleet_order_filters.test.tsx clicks pager button
      3 and fails about one run in three, measured at 4 failures in 6 runs on one
      tree and 6 in 6 on another, and raising its waitFor from 3s to 20s does not
      help because the click is lost rather than late. That flakiness has already
      cost the fleet a false refusal — task 84's re-verification failed on it on
      13 Sep 2026 while the same suite passed for tasks 83 and 86 within 25
      minutes — so the defect is both a wrong page for a merchant and a check
      that cannot be trusted for anything else. The work is a first-run guard on
      the effect, or splitting the page reset from the debounce so it is driven
      by a filter value actually changing.
    evidence:
      - document: research/candidates-orders-pagination-reset-2026-09-13.md
        sha: 71bd403
        repo: fleet
        section: "The orders page resets its own pagination on mount"
    suggested_paths:
      - platform/app/(dashboard)/analytics/orders/page.tsx
    hib_signal: null
    probes:
      - path_exists: platform/app/(dashboard)/analytics/orders/page.tsx
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/page.tsx
          pattern: '\}, 300\)'
          expected: 1
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/page.tsx
          pattern: 'setPage\(1\)'
          expected: 6
    premise:
      - claim: >
          The debounced filter effect exists in the orders page and carries a
          300ms timer, which is the effect whose mount run resets the page.
        probe:
          grep_count:
            glob: platform/app/(dashboard)/analytics/orders/page.tsx
            pattern: 'const t = setTimeout\(\(\) => \{'
            expected: 1
      - claim: >
          A test that clicks a pager button already exists, so the fix can be
          proved by an existing assertion becoming reliable rather than by a new
          test asserting the same thing twice.
        probe:
          grep_count:
            glob: platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx
            pattern: "resets to page 1 when a filter changes"
            expected: 1
```
