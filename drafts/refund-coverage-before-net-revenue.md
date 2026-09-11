# Draft spec — establish what coverage `net_revenue` actually has, before a surface shows it

```fleet-spec
work_type: research
repo: fleet
title: Establish the refund coverage behind net_revenue, and whether a net-revenue surface can be built yet
writable_paths:
  - research/refund-coverage.md
```

## Why this is an investigation and not a code change

The netting is built. `specs/net-revenue-after-refunds.md` specified it, the
task merged under `contracts/deadly-digital-platform-api.yaml`, and the report
functions in the analytics engine now return a net figure, a refunded amount
and a count of orders carrying a refund. There is no code gap left on that
side, so a `dd_api` task here would have nothing to write.

What the merged change cannot do is say what its own number means. `refund_total`
is non-zero on a handful of orders out of 2.85 million, so `net_revenue` equals
gross in every window on every tenant, and the API now emits a field named
`net_revenue` that is silently gross. `principles.md` is explicit about the
ranking that puts this ahead of the parity rows around it: *"a row where the
product reports a wrong number outranks a row where it reports no number"*. The
frontend has not surfaced it, which is the only reason the cheap correction is
still available.

So the work is knowledge, and the deliverable is a document: what coverage the
column has, per tenant, with dates; whether the zero is the truth about these
stores or a capture gap; and an explicit go / no-go with the wording any tile
must carry if it goes. That is a `research` task, and `contracts/research.yaml`
is the shape — the runner runs the SQL before the agent starts, the agent reads
the platform tree read-only, and it writes one document.

## The candidate's premise is half spent, and the spec says so rather than reopening it

The candidate asks to establish two things. One is already answered and the
other has been overtaken:

* **"Whether the connector hooks WooCommerce refund events at all."**
  `specs/refund-hook.md` answers this from the connector's own git history:
  `woocommerce_order_refunded` and `woocommerce_refund_created` are registered
  at every commit in the repository, both handlers pass `$force = true` and so
  bypass the dedup guards, the payload carries `get_total_refunded()`, and the
  refund-driven backfill pass exists as `wp dd sync-refunds`. What is
  unevidenced is whether that pass was ever **run**, and whether the *installed*
  build matches the source — and that needs a WordPress host this fleet does not
  reach. **Do not re-derive the registration answer. Cite it.**
* **"Whether the empty history is the backfill artefact `specs/empty-columns.md`
  traced it to."** `research/gap-list-open-questions.md` §6 already retired that
  explanation: the 25–26 August re-sync put every historical row through the
  writer, and the three 2025 refunds came through it correctly. Four refunds in
  2.85M orders is not a backfill artefact. The live hypothesis is narrower and
  sharper — **every refund in the database is a full refund, and there is not
  one partial refund in 2.85 million orders**, which is either the truth about
  this store or the signature of a capture gap.

Both readings are older than a week and both are stale by the standard
`principles.md` sets for written-down numbers. Re-measure rather than quote.

## 1. The evidence pack the contract must carry

The agent has no shell and no credential; the runner runs these as a read-only
role before the agent starts. Whoever queues this task copies the
`evidence_queries` shape from `contracts/research-metorik-gap.yaml` and narrows
`writable_paths` to the single file declared above.

**1.1 Read the column list first, then run every query against both tenants.**
`analytics_1.orders` and `analytics_2.orders`, separately, never
`UNION`ed — the tenants are different stores and a combined figure hides which
one is broken.

```sql
SELECT table_schema, column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema IN ('analytics_1','analytics_2') AND table_name = 'orders'
 ORDER BY table_schema, ordinal_position;
```

This is first because queries 1.2–1.5 name timestamp columns that this
document cannot confirm exist from outside the database, and a query naming an
absent column fails the whole pack.

**1.2 The refund census, per tenant.** Full against partial is the finding, not
the total.

```sql
SELECT count(*)                                                        AS orders,
       count(*) FILTER (WHERE refund_total > 0)                        AS with_refund,
       count(*) FILTER (WHERE refund_total > 0 AND refund_total < total)  AS partial,
       count(*) FILTER (WHERE refund_total > 0 AND refund_total = total)  AS full,
       count(*) FILTER (WHERE status = 'refunded')                     AS status_refunded,
       sum(refund_total)                                               AS refunded_amount,
       min(created_at) AS earliest, max(created_at) AS latest
  FROM analytics_2.orders;
```

**1.3 Every row carrying either signal, with its timestamps.** Few enough rows
to list in full, and the timestamps are the point: a refund that arrived by
hook is an order written once and updated later, and a refund that arrived with
the row is not. Select `wc_order_id, status, total, refund_total, created_at`
plus whichever of `updated_at`, `synced_at` and `order_date` query 1.1 reports,
`WHERE refund_total > 0 OR status = 'refunded'`.

**1.4 When each status starts appearing.** `SELECT status, count(*),
min(created_at), max(created_at) ... GROUP BY status` — this is the coverage
window in one query, and it is the query that either reproduces or refutes the
`specs/empty-columns.md` reading that non-completed statuses appear only from
around 2026-08-21.

**1.5 Refunds by month, against gross.** `date_trunc('month', created_at)`,
with `count(*)`, `count(*) FILTER (WHERE refund_total > 0)`, `sum(total)` and
`sum(refund_total)`. This is the shape a net-revenue chart would draw, and it
is what tells a reader whether any window exists in which netting moves a
figure at all.

**1.6 Stay inside the two `orders` tables.** `research/gap-list-open-questions.md`
records that the detector reader holds `SELECT` on `analytics_1.orders` and
`analytics_2.orders` and nothing else, and that the readings that went beyond
them were taken by hand with a migration identity. If the pack needs a table
outside that grant, the right move is a deliberate widening of the reader, not
a query the runner cannot execute; and if a query comes back empty or errored,
the document reports that rather than filling the gap from an older number.

## 2. What the document must establish

**2.1 The coverage statement, per tenant, with dates.** The earliest date from
which a refunded amount could have been captured for orders in the window, and
the earliest date from which orders in non-`completed` statuses are carried at
all. A net figure over a window that starts before those dates is gross wearing
a different name, and this is the sentence the frontend task will quote.

**2.2 Full against partial, re-measured.** Whether any order now carries
`refund_total` strictly between zero and `total`. One such row on either tenant
changes the answer to the capture question, because it is the case that only a
live hook can produce. Report the count even when it is zero — and note what
zero over 2.85M orders is evidence of.

**2.3 Whether any refund arrived after its order was first written.** From 1.3's
timestamps. An order created in 2025 whose row was last updated in 2026 by a
refund is the closest thing to behavioural proof of the hook firing in
production that these machines can produce. If the timestamps cannot separate
the two cases — for instance because the 25–26 August re-sync touched every row
— say so plainly and do not infer.

**2.4 What the API returns today, read from the tree, not from the spec.** Name
each report function that computes a net figure, the exact key names it returns,
and which routes expose them. `specs/net-revenue-after-refunds.md` specified
three functions and the candidate observes four; the document settles which,
by reading:

```
api/analytics/services/analytics_engine.py
api/analytics/routes/revenue.py
api/analytics/routes/dashboard.py
api/analytics/services/order_query.py
api/analytics/services/sync_engine.py
api/analytics/models.py
```

**2.5 Whether the refunded amount and count accompany every net figure.**
Requirement 4 of `specs/net-revenue-after-refunds.md`
made them mandatory precisely so that a net figure equal to gross reads as *"no
refunds are recorded here"*. That contract has no test gate, so nothing has
checked it. Read the merged code and report, per function, whether all three
keys are present and computed over the same rows in the same query.

## 3. The verdict the document has to reach

**3.1 A go or a no-go on surfacing net revenue, in one sentence, at the top.**
Not a list of considerations. The three admissible answers are: surface it with
the caveat in 3.2; surface it only over windows after a stated date; or do not
surface it until a host check has run.

**3.2 If it is a go, the exact caveat text.** The words a tile must carry when
the refunded amount is zero, written out so the frontend task can lift them
rather than invent them. "Net revenue" alone on a tile is the wrong number this
whole candidate is about; "Net revenue — no refunds recorded in this window" is
not.

**3.3 What a host check would add, costed, and named as somebody else's work.**
`specs/refund-hook.md` already sets out V1 (grep the installed plugin), V2 (a
genuine partial refund on a `completed` order) and R1 (`wp dd sync-refunds`,
dry run first). Restate them as the follow-up with an owner-shaped description,
and record which of 2.1–2.3 they would settle that the database cannot.

**3.4 Say which of the two documents this supersedes, and where.** The refund
paragraphs of `specs/empty-columns.md` and the *Missing* row in
`specs/metorik-gap.md` both rest on the backfill explanation and on the
1-in-2,844,177 figure. Neither file may be edited by this task — `specs/**` is
on the fleet floor — so the document names the sentences that are now wrong and
leaves the promotion to a person.

## 4. What must not happen

**4.1 No number is carried forward without being re-measured.** Every figure in
the cited documents is dated 28 or 30 August. Quote them as prior readings, with
their dates, and put this run's own numbers beside them. Where they disagree,
the disagreement is a finding.

**4.2 No claim about the deployed plugin.** Nothing in this task's reach can
read an installed WordPress file. Inference from a self-reported
`plugin_version` is exactly the evidence class `specs/refund-hook.md` refuses,
and this codebase has been burned twice by treating it as settled.

**4.3 Nothing is written anywhere but the one document.** No database is
written to, no file in the platform checkout is modified, and the diff contains
one markdown file. `contracts/checks/research_document_shape.py` refuses
anything else.

**4.4 The limits section is not a formality.** The check requires a heading that
admits what the work could not establish, and it cannot tell a real one from a
perfunctory one. At minimum it carries: whether the timestamps could separate
2.3's two cases, what the reader grant excluded, and that the partial-refund
question is not closed by any result the database can produce.

## How it is checked

`contracts/research.yaml` runs
`/home/ubuntu/fleet/contracts/checks/research_document_shape.py`, which enforces
a floor on form: the document exists and is substantial, it carries a date
within the last seven days, it names at least five pieces of evidence, it has a
limitations heading with real content, and every repository path it cites in a
checkable form resolves. It cannot tell whether the analysis is right — the
check's own docstring says so — which is why the verdict in section 3 is written
as one sentence at the top, where a reviewer can disagree with it cheaply.

## Out of scope

* **Any change to the analytics engine or the routes.** The netting merged; if
  this investigation finds a defect in it, that is a `dd_api` task with its own
  spec, and requirement 2.5 exists to produce exactly that finding rather than
  to fix it.
* **The frontend tile.** It is the task this one gates, under `dd_frontend`, and
  it should quote 2.1 and 3.2 rather than re-deciding them.
* **Running `wp dd sync-refunds`, and any connector change.** Host access, per
  3.3. A research task with no shell cannot do it and must not imply it did.
* **Editing `specs/metorik-gap.md`, `specs/empty-columns.md` or
  `specs/net-revenue-after-refunds.md`**, all of which sit behind the fleet
  floor. 3.4 names what is now wrong in them; promoting the correction is a
  human act.
* **The other empty-column questions.** Tax and shipping are settled — the
  store charges neither — and `order_items.price` and `sku` are a separate live
  defect with their own thread.
