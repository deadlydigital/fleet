# Produce candidates from the Metorik gap list (batch 14)

Read `specs/metorik-gap.md` and emit one ```fleet-candidates block into
`research/candidates-metorik-gap-2026-09-13.md`.

## What this is for, and it is different from the last three times

**The pool has 18 open rows and not one of them can be approved.** That is not
a backlog, it is a pool with nothing in it that works. Measured this morning:

    probes_failed     8   three of them carry no probes at all
    unwritable_path   4
    premise_missing   2
    protected_path    2
    premise_failed    1
    not_pending       1   a person's NOT_NOW, leave it alone

**Gate 2 was removed on 13 Sep 2026** (`specs/auto-approval.md` §9.11a). Until
today a candidate outside the newest producer batch was held as `older_batch`,
so a new batch shelved the old rows by existing. **It no longer does.** Every
row is now judged on its own evidence, and supersession happens only between
two rows that have BOTH passed every gate.

Two consequences for you, and they run in opposite directions:

* Your rows will not suppress anything. A row you do not carry forward stays in
  the pool being judged on its own probes, and a row you do carry forward wins
  only if it is better.
* **A row with no premise can no longer be approved at all.** Sixteen of the
  eighteen open rows predate `premise` and are unapprovable for that reason
  alone. Giving the live work a premise is the single most valuable thing this
  run does.

## The two rows that are one sentence away from shipping

These have been ranked every pass for days, their probes re-execute and hold at
platform HEAD, and I confirmed both gaps are still open in the checkout by
hand. They are held **only** because they carry no premise:

* **c21 — net revenue beside gross on the analytics dashboard.**
  `platform/app/(dashboard)/analytics/page.tsx` mentions `net_revenue` zero
  times. Note that c31 was approved for this work and its tasks merged —
  they established refund coverage, they did not surface the figure.
* **c37 — payment-method breakdown.**
  `platform/app/(dashboard)/analytics/payment-methods/page.tsx` does not
  exist. c50 was approved for this in batch 13 and its spec task 66 FAILED.

Carry both forward with a premise, or say in your "could not establish"
section why you did not.

## Work that no batch has re-emitted since 9 September

Four pieces of work have been sitting in batches 8 and 9 with nobody looking at
them, because gate 2 hid them behind a rule that said a newer batch had
re-verified them. **No newer batch ever mentioned them.** Re-verify each and
either carry it forward properly or drop it and say why:

    c18   export with chosen columns rather than a fixed header  (carries no probes)
    c24   scheduled digests of the dashboard                     (names a directory)
    c25   segment orders and products, not only customers        (names an unwritable file)
    c26   cross-store roll-up for an agency                      (names an unwritable file)
    c27   profit dashboard: revenue, COGS, ad spend, fees        (names a migration)

Three of those five are unbuildable *because of how the row was written*, not
because the work is wrong. That is the next section.

## Six rows in the pool name paths no contract can write

`specs/candidate-paths-must-be-buildable.md` has the measurement. The shape
check does **not** catch this yet — it asks whether a path resolves in the
tree, and `api/analytics/routes` resolves because it is a directory. So this is
yours to get right, and batch 13 got it right, which is the standard:

1. **A suggested path is a FILE, not a directory.** `api/analytics/routes` and
   `platform/app/(dashboard)/analytics` are both directories and neither can
   ever be written.
2. **It must be inside some contract's `writable_paths`.** Read
   `contracts/*.yaml` for `repo: deadly-digital-platform` and check.
   `deadly-digital-platform-api.yaml` lists files, not globs, so a path under
   `api/analytics/` that is not one of them cannot be written by any api task.
3. **It must not be on that contract's `protected_paths`.** Anything under
   `api/analytics/migrations/**` is floored. c27's profit dashboard needs a
   product-cost column and therefore a migration: **if the work needs a
   migration, that row cannot be unattended work however it is scoped.** Say so
   in the rationale rather than naming the migration and letting the gate find
   it.

The predicate, if you want to check a path directly: *at least one contract for
the repo makes it writable and does not protect it.*

## What the contract enforces, so you are not told twice

`contracts/checks/candidate_block_shape.py` runs on your diff. It refuses a
block that sets a disposition, a work_type, a batch_id or a task id; it caps
the batch at ten; it re-executes every declared predicate against the platform
repository at HEAD; and **it refuses any candidate without a `premise`.**

**`probes` and `premise` are different things and the check wants both:**

* `probes` show the **gap is real** — the thing is missing and still missing.
* `premise` shows the **ground is there** — what must ALREADY be true for this
  to be the work the rationale describes, as a claim in words plus one
  predicate from the same closed vocabulary.

Candidate 38 is why. Its four probes all held and it rested on the order table
having three columns it had never had. £2.25, and an agent that correctly built
something nobody had asked for. A premise that restates the probe is worth
nothing; state the assumption the *rationale* leans on.

## One thing that has cost a run twice

`contracts/checks/research_document_shape.py` requires a section saying what
you could **not** establish, of at least 40 words. Task 64 wrote one, titled it
`## 8. What I could not establish`, and was refused because the pattern did not
allow the number — £4.90. The pattern accepts numbered headings now, but write
the section and make it real: it is the section that makes the rest readable.

## Do not deduplicate against previous batches

`specs/approval-surface.md` §7, and the contract enforces it. A candidate that
reappears is a signal. If a row in batches 8–10 is still real work, emit it
again with today's paths, probes and premise — that is the repair, not an
edit to the old row.

## What a good row looks like

One contract's worth of work, on files that exist and are writable and
unprotected, with a probe that re-executes true today and a premise that states
what the rationale actually rests on. **A row that ships is worth more than a
row that is ambitious**, and the pool has had enough of the second kind.

## Objectives

`dd-feature-parity`.
