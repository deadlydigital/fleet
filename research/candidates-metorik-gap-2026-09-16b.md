# Candidates from the parity re-read — batch 22

Produced 2026-09-16, after reading `deadly-digital-platform` at `b29c630`
rather than reading a status column. Serves `dd-feature-parity`.

## Why this batch is two rows and not four

The re-read named four parity rows as unblocked — buildable today, needing no
new column and fitting an existing contract. Asked to queue all four, I checked
the pool first, and **three of the four were already in it**:

| Row | Already in the pool as | State |
|---|---|---|
| Order value distribution | **#70**, batch 20 | PENDING, loaded today |
| Item count distribution | **#71**, batch 20 | PENDING, loaded today |
| LTV distribution / retention curve | **#36**, batch 10 | NOT_NOW — spec merged (task 61), work task 62 ABANDONED |

Re-emitting #70 and #71 would not be the repetition `specs/approval-surface.md`
§7 protects. That rule exists because a candidate that reappears *across
re-verifications* is a signal; re-emitting a row loaded the same day is noise
wearing a signal's clothes, and it would move `work_key`'s repeat counter for a
reason that says nothing about the work. **They need an approval decision, not
a second candidate.**

**#36 is not a candidate question at all, and the re-read was wrong to call it
unblocked.** It has been attempted twice. Run 31 hit the then-£3.00 cap with no
branch; run 32 spent £5.02, the agent exited 0, and the boundary refused it.
Decision 42 rejected the merge in terms that were correct at the time.

What has changed since is not the work and not the budget. It is the boundary.
`fleet/task-62.2` is **300 production lines and 194 test lines**, measured at
`d564126`; the 494 it was refused on was a COMBINED count taken before
`f5c06f6` ("Count the mandated test against its own budget") separated them.
Against today's `max_diff_lines: 400` and `max_test_diff_lines: 1200` it is
inside both. It also still merges into `main` at `b29c630` with no conflict,
checked in a throwaway worktree. **The stated blocker has evaporated and the
work is on disk, so proposing it as new work would be paying twice.** That is a
decision about an existing branch and it is recorded here rather than converted
into a candidate.

So this batch carries the two rows that genuinely have no candidate.

## Why these two cite the gap list and not the classification

`research/metorik-report-classification-2026-09-15.md` is the better document
and batch 16 was right to move to it — but **it has no export rows at all.**
It classifies Metorik's *reports*, and an export is not a report. Grep it for
`export` and nothing comes back. Exports are a category the newer document does
not cover, which is why every export candidate this pipeline has produced has
been read off `specs/metorik-gap.md`, and why the two below are too.

## What shipped since these rows were last proposed, stated so neither is re-won

`#32` (batch 10) asked for "a CSV export of orders, customers and products".
Two thirds of it has since shipped — orders at tasks 67/84/96, products at task
108 — so it cannot be approved as written without re-proposing work that is in
production. Candidate 1 is the remaining third, narrowed.

`#18` (batch 8) asked for "export with chosen columns rather than a fixed
header" against a single export. There are three now. Segments gained the
choice at task 111. Orders is `#54`, APPROVED, whose spec task 77 FAILED
`draft_spec_shape.py` at a cost of £1.28, so no work task was ever created —
**that is a spec to re-run, not a row to re-propose**. Products is uncovered by
any candidate and is candidate 2.

```fleet-candidates
source:
  document: specs/metorik-gap.md
  sha: 4926937
ordering: unranked
unasked_question: >-
  Nobody has asked whether anyone exports from DD at all. Both rows below are
  export ergonomics, and the whole category is justified by a Metorik marketing
  page rather than by a request: the gap list's own Agency-use column is stated
  there to be an estimate and the single most falsifiable thing in the document.
  DD has no telemetry that would say whether the three exports already shipped
  have ever been downloaded. One question to HIB's team would decide whether
  this category deserves a fourth and fifth task or none.
objectives_considered: >-
  dd-feature-parity and dd-trustworthy were both weighed. Neither row changes a
  figure DD prints: candidate 1 adds a file that does not exist, and candidate 2
  adds a parameter that narrows a file that does. So dd-trustworthy, which covers
  correctness of figures already shown, has no claim on either. cost-discipline
  was considered and rejected — these are report-surface rows, not spend. Both
  land on dd-feature-parity.
candidates:
  - title: Add a CSV export of the customer report, the one export of the three the gap list named that has not shipped
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: b29c630
    rationale: >-
      The gap list asked for CSV export of orders, customers and products.
      Orders shipped at task 67 with a proxy and download control at 84 and
      repeated filters at 96; products shipped at task 108. Customers did not,
      and `api/analytics/routes/customers.py` contains no export route at all —
      checked at b29c630. The work is the third instance of a pattern that now
      exists twice: a `/customers/export` route returning a StreamingResponse
      over the same population `customer_report` already selects, so the file a
      merchant downloads is the report they are looking at. Task 108 did exactly
      this for products for £3.10, against £12.85 for orders when the pattern
      was new. No new column, no migration, no new query.
    evidence:
      - document: specs/metorik-gap.md
        sha: 4926937
        section: Daily — CSV export of orders / customers / products
    hib_signal:
      value: >-
        analytics_2 holds 197,407 customers and 2,890,822 orders, so the export
        has a population to write; customers.total_spent and order_count are
        stored per customer, which is what the existing customer report reads.
      as_of: "2026-09-16"
      coverage:
        metric: customers in analytics_2 that a customer export would write
        populated: 197407
        total: 197407
    measured_impact: null
    unasked_question: >-
      Whether an agency wants the customer LIST or the customer REPORT — the
      segment export already writes a list of customers in one fixed segment,
      so a second customer CSV may be the same file with a different filter.
      Nobody has asked, and the answer changes whether this is one route or a
      parameter on the one that exists.
    suggested_paths:
      - api/analytics/routes/customers.py
      - api/analytics/services/analytics_engine.py
    probes:
      - grep_count:
          glob: api/analytics/routes/customers.py
          pattern: 'StreamingResponse|text/csv'
          expected: 0
      - path_exists: api/analytics/routes/products.py
    premise:
      - claim: >-
          The pattern is built and shipped twice, so this is a third instance
          rather than a design — products.py already returns a StreamingResponse
          of text/csv over the population its own report selects.
        probe:
          grep_count:
            glob: api/analytics/routes/products.py
            pattern: 'StreamingResponse'
            expected: 3

  - title: Let the product CSV export choose its columns, as the segment export already can
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: b29c630
    rationale: >-
      Three CSV exports exist and only one lets the caller choose what it
      writes. Task 111 gave the segment export a validated `columns` parameter
      against one declared list, with a 400 naming the permitted columns on a
      typo. `GET /products/export` takes start, end and sort_by and emits a
      fixed header — checked at b29c630, it has no columns parameter. This is
      that same change on the second surface, and the validator to copy is in
      the tree. The orders export is the third and is NOT this candidate: it is
      already covered by #54, whose spec task 77 failed draft_spec_shape.py, so
      it needs its spec re-run rather than a new row.
    evidence:
      - document: specs/metorik-gap.md
        sha: 4926937
        section: Daily — Export with chosen columns, reordered, incl. custom fields
    hib_signal:
      value: >-
        Not a population question — the export writes whatever the product
        report selects, and product_categories holds 4,059 rows against 2,890,822
        orders. The signal is that the surface exists and is reachable: the
        export shipped at task 108 and the products page reaches it.
      as_of: "2026-09-16"
      coverage:
        metric: product category rows the report this export writes can group by
        populated: 4059
        total: 4059
    measured_impact: null
    unasked_question: >-
      Whether column choice is wanted on exports at all, or whether it was only
      ever wanted on the segment export because that one emits ten columns of
      contact data. Task 111 shipped it for segments without anyone asking for
      it elsewhere.
    suggested_paths:
      - api/analytics/routes/products.py
      - api/analytics/services/analytics_engine.py
    probes:
      - grep_count:
          glob: api/analytics/routes/products.py
          pattern: 'columns'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/segments.py
          pattern: '_validate_export_columns'
          expected: 2
    premise:
      - claim: >-
          The validated-column-list pattern exists and shipped, so this copies a
          built thing onto a second export rather than designing one.
        probe:
          grep_count:
            glob: api/analytics/routes/segments.py
            pattern: '_EXPORT_COLUMNS_HELP|_validate_export_columns'
            expected: 5
```
