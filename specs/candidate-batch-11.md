# Produce candidates from the Metorik gap list (batch 11)

Read `specs/metorik-gap.md` and emit one ```fleet-candidates block into
`research/candidates-metorik-gap-2026-09-11.md`.

## What this is for

Batch 10 is exhausted, and twelve rows in batches 8 and 9 are held only because
gate 2 says a newer producer batch superseded them. They have been ranked every
night since and never chosen. A new batch is what releases them: it either
carries their claim forward re-verified, or it does not and they stay held for a
reason somebody can read.

Batch 10's nine rows, and where each went — this is the record of what one batch
actually produced, and it is the thing to do better than:

    c29  APPROVED   shipped
    c30  PENDING    its probes stopped holding when main moved
    c31  APPROVED   shipped
    c32  PENDING    untried
    c33  APPROVED   shipped as a research document
    c34  APPROVED   its draft was refused: two contracts covered its paths
    c35  PENDING    names a migration, which is on the protected floor
    c36  NOT_NOW    its draft was too big for one task, twice, and was abandoned
    c37  PENDING    untried

Two of nine shipped code. Four were stopped by something about the row itself
rather than by the work being wrong.

## What the contract already enforces, so you need not be told twice

`contracts/checks/candidate_block_shape.py` runs on your diff. It refuses a
block that sets a disposition, a work_type, a batch_id or a task id; it caps the
batch at ten; and it RE-EXECUTES each candidate's declared predicates against
the platform repository at HEAD. A row whose claim has stopped being true cannot
be emitted.

**That re-verification is the work, not the parsing.** It matters more for this
batch than the last: `main` moved a great deal on 11 Sep. `analytics_engine.py`
gained `refund_total` handling and a guard in the orders upsert, and several
gap-document claims about refunds are now wrong in the other direction. Probe
every claim you carry forward, and drop the rows whose claim has closed.

## Four things batch 10 got wrong that the checks do not catch

These cost real money on 11 Sep. None is refused by `candidate_block_shape.py`,
so they are yours to get right.

**1. A suggested path must be a FILE, not a directory.** c24, c26 and c28 name
`api/analytics/routes`. `console/rank.py`'s gate 6 reports `unwritable_path` for
those — no contract makes a directory writable, so no task can be queued for one
at all. Name the file the work would edit.

**2. A suggested path must be inside some contract's writable set.** Check it.
`contracts/deadly-digital-platform-api.yaml` lists twenty-seven files and no
glob, so a path in `api/analytics/` that is not one of those twenty-seven cannot
be written by any api task — including `api/analytics/schema_context.py`, which
c26 names. See specs/auto-approval.md §15.

**3. A path on `protected_path_floor` can never be worked on.** c35 names
`api/analytics/migrations/versions/v0008_product_categories.py`. A migration is
floored and no contract can make it writable, so that row can only ever be
refused. Query the floor before suggesting a path under `api/analytics/
migrations/`, `api/tests/`, or anything named in §9.19's list.

**4. Work that spans the api and the frontend is expensive right now.** It is
allowed — gate 6 no longer refuses it — but §12's chaining cannot split a seam
whose halves share a file or call each other, and §13 records that nothing can
turn one candidate into several specs. **Prefer rows whose work sits on one side
of the api/frontend line.** If a row genuinely needs both, say so in its
rationale so the reader knows the cost before approving it.

## What a good row looks like now

One contract's worth of work, on files that exist and are writable, with a
predicate that a machine can re-execute and that is true today. A row that ships
is worth more than a row that is ambitious, and the pool has had enough of the
second kind this week.

## Objectives

Carry `objectives_considered` on the block, as batch 10 did, and name the
objective each row serves from `objectives-2026-Q4.yaml`.
