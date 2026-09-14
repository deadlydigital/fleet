# Produce candidates from the Metorik gap list (batch 15)

Read `specs/metorik-gap.md` and emit one ```fleet-candidates block into
`research/candidates-metorik-gap-2026-09-14.md`.

## What changed since batch 14, and it is the whole reason for this run

**Batch 14 worked.** Its two headline rows — the ones it said were "one
sentence away from shipping" and held only for want of a premise — have both
shipped, along with three more. Merged into `deadly-digital-platform` main
between 13 Sep 21:58 and 14 Sep 10:03:

| shipped | merge |
|---|---|
| net revenue after refunds, beside gross, on the analytics overview (c21) | `ab65311` |
| coupon and discount block on the revenue page | `04a3a17` |
| revenue broken down by payment method (c37) | `e45036d` |
| the order CSV export reachable from the orders page | `1354e90` |
| product performance grouped by category, reachable from the products page | `1f8b7fe` |

A sixth change shipped in the same window and is not a gap-list row: the orders
page no longer resets its own pagination on mount (`8dceed9`).

**None of these five may be proposed again.** Do not take that from this
document — take it from the tree. Every one of them is a claim you can check,
and `candidate_block_shape.py` re-executes your probes at HEAD, so a row whose
gap has closed cannot be emitted even if you write it. **If a probe of yours
says one of these gaps is still open, that is a finding: say so explicitly in
your "could not establish" section rather than quietly emitting the row.**

## The pool as it stands, measured 14 Sep 2026 10:15

    rank_v2 at platform ab65311; 18 open candidate(s), newest batch 14
    probes re-executed: 21 of 34 held (across the 11 of 18 that reached gate 7)
    premise re-executed:  0 of 0  held (across the  1 of 18 that reached gate 8)

    WOULD APPROVE NOTHING: no candidate passed the gates

    probes_failed    10
    unwritable_path   4
    protected_path    2
    premise_missing   1
    not_pending       1   a person's NOT_NOW, leave it alone

**Eighteen open rows and not one can be approved.** Read the two numbers in the
middle together: ten rows are held because the world moved under them, and only
one row in the whole pool has ever reached the premise gate at all.

The ten `probes_failed` are not a complaint about those rows — that is
re-verification doing its job, and five of the ten are held because the work
shipped this week. The six held on `unwritable_path` and `protected_path` are
different, and they are the ones worth your attention: **those rows describe
work that may well be real, and they are unbuildable because of how the row was
written.** That is the failure this run can actually prevent.

## Paths: a file, writable, unprotected

Six of eighteen rows die here, and the shape check does not catch it — it asks
whether a path resolves, and `api/analytics/routes` resolves because it is a
directory. Live examples from the pool this morning:

* `api/analytics/routes` — a directory, so nothing can ever write it (c24, c28)
* `platform/app/(dashboard)/segments/builder/page.tsx` — a file, resolves, and
  no contract on the platform makes it writable (c25)
* `api/analytics/migrations/versions/v0008_product_categories.py` — on the
  protected floor (c35). **If the work needs a migration it is not unattended
  work however it is scoped.** Say that in the rationale rather than naming the
  migration and letting the gate find it.

The predicate: *at least one contract for the repo makes this path writable and
does not protect it.* Read `contracts/*.yaml` for `repo:
deadly-digital-platform` and check. `deadly-digital-platform-api.yaml` lists
files rather than globs, so a path under `api/analytics/` that is not one of
them cannot be written by any api task.

## `probes` and `premise` are different, and the check wants both

Stated here because `contracts/candidate-producer.yaml` requires whoever queues
this task to state it, and an agent that has not been told spends a run finding
out.

* **`probes`** show the **gap is real** — the thing is missing, and still
  missing at HEAD.
* **`premise`** shows the **ground is there** — what must ALREADY be true for
  this to be the work the rationale describes, as a claim in words plus one
  predicate from the same closed vocabulary.

The check **refuses any candidate without a premise**, and one row in eighteen
has ever satisfied it. Candidate 38 is why the gate exists: its four probes all
held, and it rested on the order table having three columns it had never had —
£2.25 and an agent that correctly built something nobody asked for. **A premise
that restates the probe is worth nothing.** State the assumption the
*rationale* leans on.

## What the contract enforces, so you are not told twice

`contracts/checks/candidate_block_shape.py` runs on your diff: it refuses a
block that sets a disposition, a work_type, a batch_id or a task id; it caps
the batch at ten; it re-executes every declared predicate at HEAD; and it
refuses any candidate without a premise.

`contracts/checks/research_document_shape.py` requires a section saying what
you could **not** establish, of at least 40 words. Write it and make it real —
it is the section that makes the rest readable, and it is where the finding
described at the top of this document belongs if you hit it.

## Do not deduplicate against previous batches

`specs/approval-surface.md` §7, and the contract enforces it — you have no
route to the `candidates` table and cannot see what came before. A candidate
that reappears is a signal. If a row from an earlier batch is still real work,
emit it again with today's paths, probes and premise. That is the repair, not
an edit to the old row.

Note what this means for the six unbuildable rows above: **re-emitting them
correctly is the highest-value thing in this run**, because the work may be
real and the row is what is broken.

## What a good row looks like

One contract's worth of work, on files that exist and are writable and
unprotected, with a probe that re-executes true today and a premise that states
what the rationale actually rests on. A row that ships is worth more than a row
that is ambitious.

## Objectives

`dd-feature-parity`.
