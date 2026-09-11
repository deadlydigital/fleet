# Decide: seven fixed RFM buckets, or attribute-based segmentation

```fleet-spec
work_type: research
repo: fleet
title: Decide whether analytics segmentation stays seven fixed RFM buckets or becomes attribute-based, having first established what the email-side rule builder can and cannot express
writable_paths:
  - research/segmentation-model-2026-09-11.md
```

## Why this is a research task and not a build

`specs/metorik-gap.md`, Daily band, records the widest single gap on the
document: *"Segment any resource (orders, customers, products, coupons,
subscriptions, carts) by any attribute, AND/OR groups."* Metorik's central
claim is that segmentation is a property of every resource. DD's is a fixed
taxonomy over one resource.

The candidate in `research/candidates-metorik-gap-2026-09-10.md` phrases this as
a **decision** rather than a build, and it is right to. Closing it properly
means a filter grammar, a persisted definition, an evaluator per resource, a
UI, and a migration for the seven names that are already in the product and
already referenced by the email side. That is the most expensive item on the
document. Nobody should queue a code task against it on the strength of a
one-line gap row.

The candidate also names the thing that would narrow the decision and had not
been checked: **whether the email side's rule builder can express analytics
filters.** If it could, the answer would be cheap — point analytics at a
grammar that already exists. That read is the precondition for everything
else, so it is the first requirement below rather than a footnote.

## A note on how paths are written here

`contracts/checks/draft_spec_shape.py` resolves a backticked prose path against
the checkout named by this block's `repo`, which is `fleet`. A backticked
platform path would therefore fail a check that cannot see the platform tree,
so platform paths below are written in **bold, in full from the repository
root**. Every one of them was read from the platform checkout while this draft
was written and appears in the paths pack the runner generated. The research
task does not inherit this constraint:
`contracts/checks/research_document_shape.py` resolves citations against the
platform checkout as well as fleet, so the document it produces should
backtick them normally.

## What this draft already established, and what it changes

The read was partly done in the course of writing this spec, and the result is
strong enough that the research task should start from it and verify it rather
than rediscover it. Five findings, all from the platform tree:

**There are two rule builders, and they are not the analytics one.** The
email-side builder lives at
**platform/app/(dashboard)/segments/builder/page.tsx** and writes a JSON
`conditions` blob. That blob is then evaluated by **two independent
implementations that do not agree**:
**platform/app/api/segments/preview/route.ts**, which compiles it to a Listmonk
SQL string over `subscribers.attribs`, and `query_segment_customers` in
**api/app.py**, which compiles it to SQLAlchemy filters over the `Customer`
model in the public schema. Neither reads an `analytics_<tenant_id>` schema.

**The builder's vocabulary is seven customer attributes.** `PROPERTY_FIELDS` in
the builder page offers `total_spent`, `order_count`, `avg_order_value`,
`days_since_last_order`, `rfm_segment`, `is_vip` and `is_repeat_customer`,
plus event rules over seven tracked events. There is no order attribute, no
product, no coupon, no cart. So the email side is **also customer-only**: it
does not narrow the resource half of the gap at all.

**The AND/OR is flat.** `conditions` carries a single `combinator` applied to
one array of rules. Metorik's claim is AND/OR *groups*. Nothing in either
evaluator nests.

**The two evaluators disagree on the vocabulary they were given.**
`query_segment_customers` resolves a rule's field with
`getattr(Customer, field, None)` and silently `continue`s when it is absent.
Of the seven `PROPERTY_FIELDS`, only `total_spent` is a `Customer` column;
`order_count`, `avg_order_value`, `days_since_last_order`, `rfm_segment`,
`is_vip` and `is_repeat_customer` are not columns anywhere in **api/app.py**.
The operator vocabularies differ too — the builder emits `=`, `contains`,
`is_true`, `is_false`; the sync path handles `==`, `is_null`, `is_not_null` and
none of those four — and the key differs: the builder writes
`combinator: and|or`, the sync path reads `match: all|any` and defaults to
`all`. An OR segment syncs as an AND.

**The seven names do not even match across the two sides.** `VALID_SEGMENTS` in
**api/analytics/services/segment_engine.py** is `Champions`, `Loyal`,
`Potential Loyalists`, `At Risk`, `Hibernating`, `Lost`, `New`. The
`rfm_segment` select in the builder page offers `Champions`,
`Loyal Customers`, `Potential Loyalists`, `New Customers`, `At Risk`, `Lost`,
`Other`. Three of seven differ. An email segment targeting
*"RFM Segment equals Loyal Customers"* matches a string the analytics side
never writes.

**This means the flagged question has a negative answer, and the decision does
not get cheaper.** There is no reusable grammar on the email side to point
analytics at. What is there is a narrower vocabulary over a different data
store, compiled twice, inconsistently. The research task's job is to confirm
that at line level and then price the options against it — not to look for a
shortcut this draft has already failed to find.

## What the task must produce

One document at `research/segmentation-model-2026-09-11.md`, meeting
`contracts/checks/research_document_shape.py`. Five numbered requirements.

### 1. Confirm the flagged read, at line level

Answer the question `specs/metorik-gap.md` left open — *can the email side's
rule builder express analytics filters?* — with file-and-line citations rather
than a summary. Every one of the five findings above is a claim the document
must either confirm with a citation or overturn with one. Overturning any of
them is a **more** valuable outcome than confirming all five, and the document
should say plainly which it did.

**1.1 Read all four surfaces, not one.** The builder page, the preview route,
`query_segment_customers` in **api/app.py**, and the stored shape — the
`Segment` model in the same file, whose `conditions` column is what actually
persists. A conclusion drawn from the builder UI alone will be wrong about
what runs.

**1.2 State what a saved segment does when a rule is dropped.**
`query_segment_customers` builds an empty filter list when no rule resolves,
and an empty list applies no `WHERE` at all — so the return is every customer
of the tenant. Establish whether `POST /api/segments/{id}/sync` then pushes
that whole list to the linked Listmonk list. If it does, a segment saying
*"is_repeat_customer is true"* mails the entire customer base. **This is a
severity finding, not a design input.** Record it with evidence, say in one
line that it needs its own task, and do not let it pull the document off the
decision it exists to make.

**1.3 Do not propose fixes to any of it.** This requirement establishes what is
there. What to do about it is requirement 4.

### 2. State what analytics segmentation can express today

The counterpart read, on the analytics side, to the same standard.

**2.1 The taxonomy is closed at three layers.** `VALID_SEGMENTS` is a literal
list in **api/analytics/services/segment_engine.py**; `_validate_segment_name`
in **api/analytics/routes/segments.py** returns 400 for anything outside it;
and the `CASE` ladder in `compute_rfm_segments` is the only writer of
`segment_name`. Name all three, because a spec that changes one and not the
others is the obvious wrong build.

**2.2 The scores are quintiles of a population, not thresholds.** `NTILE(5)`
over recency, frequency and monetary within a 180-day lookback, restricted to
orders with status `completed` or `processing`, with `New` overriding on a
30-day first-order window and a default fallback of `Hibernating`. Say what
that means for a user: the buckets are relative, so a store's Champions are its
own top quintile and the boundary moves when the population does. An
attribute-based model would replace that with absolute thresholds a user
chooses, and **the two answer different questions**. This is the substance of
the decision and it is not a UI difference.

**2.3 What is segmentable at all.** Only customers, and only via the
precomputed `analytics_<tenant_id>.customer_segments` table. Note what already
exists as a real per-resource filter implementation — the order filters in
**api/analytics/services/order_query.py**, reached through
**api/analytics/routes/orders.py** — because if anything on the platform is the
seed of a filter grammar, it is that, and not the email builder. Establish
whether it is: what its parameters are, whether they are a fixed list or
composable, and whether it supports OR at all.

### 3. Price three options, on the same axes

Not a recommendation yet. Three options, each costed on: what a user gains,
what it costs to build, what it breaks, and what it forecloses.

**3.1 Keep the seven buckets.** Cost is zero and the gap row stays Red. State
what an agency evaluating DD cannot do, in the words they would use.

**3.2 Attribute-based segmentation for customers only.** A filter grammar over
customer attributes, saved definitions, evaluated against the analytics schema
— roughly what the email builder gestures at and does not deliver. Say what
happens to the seven names: whether they survive as seeded definitions, and
whether the `rfm_segment` field on the email side then points at user-defined
names, which is a migration this option owns.

**3.3 Attribute-based segmentation across resources.** The full Metorik claim:
orders, products, coupons, carts, with AND/OR groups. Break the cost down far
enough to be arguable — grammar, persistence, one evaluator per resource, UI,
and the export and count paths that every existing segment surface already has.
A single number for this is not a costing.

**3.4 Cost the convergence separately.** Whatever is chosen, the two segment
surfaces disagree today (finding five). Merging them is a cost that belongs to
3.2 and 3.3 and not to 3.1, and it should appear as its own line rather than
being folded into a total.

### 4. Recommend one, and say what would change your mind

A single recommendation, argued from requirements 1–3, with a named condition
under which it would be wrong. A document that lists three options and declines
to choose has not made the decision this task exists to make.

**4.1 Say whether the email builder is a foundation or a warning.** It is the
only attribute-based segmentation on the platform and it is broken in the ways
finding four describes. Argue explicitly whether its `conditions` JSON shape is
worth adopting as the grammar — with nesting and a single evaluator added — or
whether reusing it inherits a vocabulary that was never checked against a
schema. This is the crux and it should not be left implicit.

**4.2 Argue from the store, not from the feature list.** Tenant order volumes
and column population are in `research/EVIDENCE-metorik.md` and
`research/metorik-gap-2026-08-30.md`. A segmentation model whose most-used
attributes are null on both tenants is a worse recommendation than a narrower
one that is not.

### 5. Name the first buildable task, and its contract

Whatever is recommended, end with the smallest next task that is worth queueing
on its own — one that is useful even if the larger decision is later reversed,
and whose writable paths fall inside exactly one contract in `contracts/`.
Name that contract. If nothing qualifies — if every first step is large — say
that in as many words. That is a finding, and it is the one that tells a
reader this candidate should stay a decision for another cycle.

## What the document must not do

* **Propose a schema or an API.** This is a decision document. A worked design
  inside it will be read as approved, and requirement 3 exists precisely
  because the design is not yet chosen.
* **Fix anything.** The contract makes one file writable and that file is under
  `research/`. The platform tree is readable and nothing else.
* **Treat the email builder's field list as a requirements list.** It is seven
  names, six of which resolve to nothing in the sync path. It is evidence of
  what somebody once wanted, not of what works.
* **Edit `specs/metorik-gap.md`.** It is on the fleet floor and protected by
  `contracts/research.yaml`. The gap row changes when a build merges, not when
  a decision is written.
* **Cite a URL without a retrieval date.** If any Metorik documentation is
  fetched, `contracts/checks/research_document_shape.py` requires the date.
  Prefer the platform tree: everything the decision turns on is in it.

## What could not be established in this draft, and is left to the task

* **Whether the sync path actually mails the whole list.** Requirement 1.2. The
  code path reads that way — empty filters, no `WHERE` — but the call site in
  `sync_segment` and whatever Listmonk does with the result were not traced
  here, and a guess would be the wrong kind of finding.
* **Whether the order filter implementation is composable.**
  **api/analytics/services/order_query.py** was identified as the candidate
  seed for a grammar and not read. Requirement 2.3.
* **What is already stored.** How many segments exist across tenants, which
  fields their `conditions` actually use, and how many of those fields resolve.
  The research contract has no database access and the agent has no shell, so
  this needs `evidence_queries` on the contract that queues the task —
  `public.segments`, grouped by tenant, with the `conditions` column — or it
  stays unanswered. **Whoever queues this should add that query.** Without it
  the document can say the sync path drops rules; it cannot say how many live
  segments are affected, and that number is the difference between a severity
  finding and an incident.

## How it is checked

`contracts/research.yaml` is the only contract with `work_type: research` and
`repo: fleet`, so that is what this runs under. Its verification is
`contracts/checks/research_document_shape.py`: a floor on form — 800 words, 60
lines, three headings, five evidence tokens, a dated document, a section
admitting what was not established, and every backticked repo path resolving.

The check's own docstring says what it cannot do, and it applies squarely here:
it cannot tell whether the recommendation in requirement 4 is right. Nothing
mechanical can. This document is queued to be read.
