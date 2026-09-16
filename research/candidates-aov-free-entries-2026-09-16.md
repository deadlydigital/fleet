# Every shipped AOV mixes free entries with paid ones, and nothing says so

Produced 2026-09-16. Serves `dd-trustworthy`. **One candidate, by hand, and not
a producer batch** — the same shape as batches 11, 15, 17 and 18. It is filed
separately from batch 16 because batch 16 is a parity batch and this is not a
parity row: the report already exists and the figure it prints is wrong.

## Daily — AOV on the revenue surface, and what is wrong with it

The band word leads this heading because `console/load_candidates.band_of` reads
a candidate's band from the heading of the evidence section it cites, and
`console/rank.py` sorts a band-less row LAST (`NO_BAND = 4`) forever. Three of
the rows open in the pool this morning are band-less, and all three are
hand-loaded ones like this. `Daily` because AOV sits on the revenue surface an
agency opens before it does anything else, which is the band
`research/metorik-report-classification-2026-09-15.md` gives *Average order
gross over time*.

`analytics_2.orders` holds **66,764 orders with `total = 0`**, of which
**66,676 carry status `completed`**. On 2026-09-16 Eamonn stated the fact that
explains them: HIB runs prize competitions, and a prize competition must offer a
free entry route by law. Those orders are that route. They are recorded
correctly and they are real orders.

`_REVENUE_STATUSES` is `('completed', 'processing', 'on-hold')`, so **all
66,676 sit inside the population every revenue figure is computed over**. For a
sum that is right: a free entry contributes £0, so gross revenue, net revenue
and every total are already correct and this candidate does not touch them.

For a **mean** it is not right. Measured over the revenue statuses on
2026-09-16:

| Figure | Value |
|---|---|
| Orders | 2,888,343 |
| Of those, non-zero total | 2,821,656 |
| **AOV as shipped** | **£8.23** |
| **AOV over paid entries only** | **£8.43** |
| Understatement | **2.4%** |

**This is a figure already in front of a user.** `revenue_report` returns
`aov` per period, `GET /revenue` serves it, and the revenue page renders it —
17 mentions of AOV in
`platform/app/(dashboard)/analytics/revenue/page.tsx`. The payment-method
breakdown carries a per-method AOV column with the same defect.

## Why this is `dd-trustworthy` and not `dd-feature-parity`

`objectives-2026-Q4.yaml` states the objective as *"DD's numbers are correct
and provably so - no silent data loss, no metric telling two stories"*, and
notes that *"one wrong figure in front of a client costs more than any
feature"* and that *"parity work must not outrank correctness work by
default"*. A metric telling two stories is exactly what this is: the same
column means "a sale" and "a free entry" depending on the row, and the mean
does not distinguish them.

Bucket A of `research/metorik-report-classification-2026-09-15.md` has three
rows and one bucket-C row carrying a `MUST SPLIT FREE ENTRIES` mark for the
same reason. This candidate is the shipped half of that problem; those rows are
the unbuilt half.

## The repair, and what it must not be

**Do not filter the free entries out.** Dropping 66,764 orders from the
denominator silently changes what "orders" means on the same page that prints an
order count, and a reader comparing the two would find them inconsistent. The
repair is to **label**: show AOV over paid entries beside AOV over all orders,
or name the free bucket, the way `product_category_report` already leads its
response with a `coverage` block rather than quietly dropping uncategorised
lines. That precedent is in this repository and should be followed rather than
reinvented.

## What I could not establish

**Whether the 2.4% is stable or seasonal.** It is one measurement over the
whole history to 2026-09-16 and free entries span 2023-03-15 onward, but nothing
here says whether the ratio moves with a promotion, a specific competition or a
weekend, and a figure quoted per period could differ materially from the
lifetime one. **Whether `analytics_1` has the same shape** — it was not read for
this, and the tenant that matters for HIB is `analytics_2`. **Whether any
consumer outside the revenue surface reads `aov`**; `daily_metrics.aov` holds a
precomputed value that this candidate does not touch and that may carry the same
mixing, which is a second question and possibly a second row. **Whether the
right default is paid-only or all-orders** — that is a product decision for
Eamonn and this candidate deliberately does not make it, proposing only that the
page stop being silent about which one it shows.

## The candidate

```fleet-candidates
source:
  document: research/candidates-aov-free-entries-2026-09-16.md
  sha: "b0b20da"
ordering: unranked
unasked_question: >-
  Nobody has asked whether HIB's team already knows the AOV on the revenue page
  includes free entries. If they do and have mentally adjusted for it, this is a
  labelling nicety worth little; if they have ever quoted 8.23 to anyone as an
  average order value, it has already cost something. That question is one
  message and it was not sent before this row was written.
objectives_considered: >-
  dd-trustworthy over dd-feature-parity, and the choice is the point rather
  than a formality. dd-feature-parity covers reports Metorik has and DD lacks;
  this report exists and is served. What is wrong is the number, and
  objectives-2026-Q4.yaml separates the two deliberately so that parity work
  cannot outrank correctness work by default. dd-first-revenue and
  cost-discipline were considered and rejected: this changes no pricing surface
  and costs nothing measurable to run.
candidates:
  - title: Say whether AOV includes free entries, on every surface that prints it
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    rationale: >-
      66,676 completed orders carry total = 0 and are the legal free-entry route
      a prize competition must offer. They sit inside _REVENUE_STATUSES, so the
      shipped AOV averages them with paid entries and reads 8.23 where paid-only
      is 8.43, understated by 2.4 percent, with nothing on the page saying which
      population it used. Sums are unaffected and must not be touched. The
      repair is to label rather than to filter: show both figures or name the
      free bucket, following the coverage block product_category_report already
      leads its response with. Dropping the orders would silently disagree with
      the order count on the same page.
    evidence:
      - document: research/candidates-aov-free-entries-2026-09-16.md
        sha: "b0b20da"
        section: "Daily — AOV on the revenue surface, and what is wrong with it"
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/routes/revenue.py
      - platform/app/(dashboard)/analytics/revenue/page.tsx
    verified_sha: "7a09b92e192d952e82d218303777a90acfafafd4"
    hib_signal:
      value: >-
        66,764 of 2,890,319 orders on analytics_2 carry total = 0 and 66,676 of
        those are completed, so 2.3 percent of the order book is free entries
        sitting inside the revenue statuses. AOV over the revenue statuses is
        8.23 across all orders and 8.43 across the 2,821,656 with a non-zero
        total.
      as_of: "2026-09-16"
      coverage:
        metric: orders with total = 0 among the revenue statuses
        populated: 66676
        total: 2888343
    measured_impact: null
    probes:
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: '(?<![_a-zA-Z])total\s*(!=|>|<>)\s*0'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/revenue/page.tsx
          pattern: free
          expected: 0
    premise:
      - claim: >-
          AOV is already computed and already served, so this is a change to a
          figure that exists rather than a new report. revenue_report returns an
          aov key and the revenue page renders it.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: '"aov"'
            expected: 12
```
