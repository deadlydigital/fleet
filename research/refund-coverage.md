# What coverage `net_revenue` actually has, and whether a net-revenue surface can be built yet

**Verdict: no-go — do not surface net revenue until a host check has run, because
the database cannot settle the coverage question even in principle, and in this
run it was not asked.**

Investigated 2026-09-11, read-only, against the fleet worktree for this task and
`~/deadly-digital-platform`. Nothing was written to any database. Nothing in the
platform checkout was changed. The diff is this one file.

---

## The evidence pack does not exist for this run, and that is the first finding

The spec for this task assumed the runner would execute queries 1.1–1.5 as a
read-only role and write the results into the worktree before the agent started.
It did not, because the task was queued against `contracts/research.yaml`, which
declares neither `evidence_pack` nor `evidence_queries`. The narrowing the spec
asked for — copy the `evidence_queries` shape from
`contracts/research-metorik-gap.yaml`, narrow `writable_paths` to one file — was
not applied: this run's writable path is the whole of `research/**`.

The comparison is direct. `contracts/research-metorik-gap.yaml` carries five
`evidence_queries`, and task 5's readings landed in
`research/EVIDENCE-metorik.md` as tables the agent could read. There is no
equivalent file here, and the agent for this contract has no shell and no
credential by design, so there was no second route to a number.

**Consequence: requirements 2.1, 2.2 and 2.3 are unanswered.** No coverage date,
no re-measured full-against-partial count, and no timestamp evidence. Every
number below that describes the data is a *prior reading*, carries the date it
was taken, and was **not** re-measured in this run. Per requirement 4.1, that
disagreement with the spec's own standard is itself the finding, not something to
paper over by quoting August as though it were today.

Requirements 2.4, 2.5, 3.2, 3.3 and 3.4 are answerable from the tree, and are
answered below.

---

## The coverage question cannot be settled by any query against `orders`

This is the load-bearing result, and it would hold even if the pack had run.

`api/analytics/models.py:87` declares the column as
`refund_total = Column(Numeric(10, 2), nullable=False, server_default="0")`, and
the writer at `api/analytics/services/sync_engine.py:408` stores
`_num(order_data.get("refund_total"), Decimal("0"))`. `_num` returns its default
for `None` and for `""` (`sync_engine.py:114-125`). So a payload that omits
`refund_total` entirely and an order that genuinely had no refund produce the
**identical stored value, `0.00`**. The column has no state meaning "not
reported".

`specs/empty-columns.md:42-48` already named this as a design flaw on
2026-08-28 — the same code block deliberately keeps `coupon_code` NULL because
*"'not reported' and 'no coupon' are different facts"*, and does not extend that
to the four money columns. What that document called a reason the investigation
took a day instead of a query is, for this question, fatal: **no census of
`analytics_1.orders` or `analytics_2.orders` can distinguish "this store has
almost no refunds" from "this build never sent the field".** Queries 1.2–1.5
would have produced numbers; they could not have produced the verdict.

There is a second hazard on the same path. The upsert at
`sync_engine.py:512-541` includes `refund_total = EXCLUDED.refund_total` in its
`ON CONFLICT DO UPDATE` set-list, with no COALESCE guard. That is what a refund
needs — a re-push overwrites — but it runs the other way too: a re-sync whose
payload omits the field writes `0.00` over a refund that was previously captured.
Any full re-sync from a build without the hooks silently erases refund history.
Flagged, not fixed; it is a `dd_api` question with its own spec.

---

## What the API returns today, read from the tree (requirement 2.4)

Four functions compute a net figure, all in
`api/analytics/services/analytics_engine.py`. The spec for the merged change
named three; the candidate's count of four is the correct one, and the fourth is
a private helper rather than a fifth surface.

| Function | Line | Keys returned | Exposed by |
|---|---|---|---|
| `_query_period_stats` | 226 | `net_revenue`, `refunded_amount`, `orders_with_refund` | indirectly — it computes `period` and `previous` |
| `dashboard_overview` (`trends_data` block) | 720-750 | same three, per day | `GET /api/analytics/dashboard` |
| `revenue_report` | 787 | same three, per period | `GET /api/analytics/revenue` (`data`) |
| `revenue_summary` | 928 | same three, window totals | `GET /api/analytics/revenue` (`summary`) |

`dashboard_overview` also emits a `trends.net_revenue` percentage
(`analytics_engine.py:629`), computed from `_query_period_stats` on both sides,
so the comparison is net against net. `revenue_report_hourly`
(`analytics_engine.py:1047`) delegates to `revenue_report` and inherits the keys.

Only two routes expose any of it: `api/analytics/routes/revenue.py` and
`api/analytics/routes/dashboard.py`. Neither file mentions the keys itself —
both pass the engine's dict through. `api/analytics/services/order_query.py`
returns `refund_total` on the order list and detail but computes no aggregate.
`compute_daily_metrics` (`analytics_engine.py:35`) persists a gross `revenue` and
no net field; no analytics route reads `daily_metrics` for a figure, so it is not
a surface today, and it is the place a future net tile would go wrong if it were
built on the stored table instead of on read.

## Requirement 2.5 — all three keys travel together, and nothing checks that they do

Read per function: yes in all four cases. Every net figure is
`SUM(total) - SUM(refund_total)` with both terms carrying the identical
`FILTER (WHERE status IN ('completed','processing'))`, in one query, over one
window, with one join. `refunded_amount` and `orders_with_refund` sit beside it
in the same SELECT and the same returned dict. Requirement 4 of
`specs/net-revenue-after-refunds.md` is satisfied as merged.

**It is satisfied by care, not by a gate.** A grep for `net_revenue`,
`refunded_amount` and `orders_with_refund` across `api/tests/` returns nothing.
The verification block of `contracts/deadly-digital-platform-api.yaml` runs
`compileall`, `ruff_no_new_findings.py` and per-file pytest — none of which knows
these keys exist. The contract's fourth requirement has no test anywhere in the
repository, so a later edit dropping `orders_with_refund` from one of the four
would merge clean.

---

## The finding that matters most: on tenant 2 the net figure is gross by construction

`_REVENUE_STATUSES` is the literal `('completed', 'processing')`
(`analytics_engine.py:32`). Every net term in all four functions is filtered to
it.

`research/gap-list-open-questions.md:202-207` lists, as of **2026-08-30**, every
tenant-2 order carrying either refund signal. There are four: three `cancelled`
and one `refunded`. **None of those statuses is in `('completed','processing')`.**

So on tenant 2, on that reading, `refunded_amount` is zero in *every* window,
`orders_with_refund` is zero in *every* window, and `net_revenue == revenue`
everywhere — not as today's coincidence, but structurally, for as long as the
store's only refunds sit on excluded statuses.

The docstring at `analytics_engine.py:961-964` says *"three of the four refunds
on the second live tenant sit on `cancelled` orders, outside the revenue-status
filter, so neither term sees them"*, which implies the fourth is seen. It is not:
the fourth is `status = 'refunded'`, equally outside the filter. The arithmetic
is still right — netting a refund against gross its order never contributed to
would remove money that was never added — but the code's own account of why is
off by one, and that is worth correcting in the `dd_api` follow-up.

The consequence for a tile is sharper than the spec anticipated.
Requirement 4's legibility mechanism makes `net_revenue == revenue` read as *"no
refund is recorded in this window"*. On tenant 2 that sentence would be shown
over a store that **does** have recorded refunds, on orders the revenue
population excludes. The number is defensible; the sentence a merchant reads off
it is not. `principles.md:39-42` ranks a wrong number above a missing one, and
this is that shape.

Tenant 1 is not covered by this argument. `research/EVIDENCE-metorik.md` records
4 refunded orders there on 2026-08-30 and
`research/gap-list-open-questions.md:211-213` says the 1-against-4 split is
identical, but the per-row statuses for tenant 1 have never been published. If
any of those four is `completed`, tenant 1's net figure does move and the
coverage sentence for it differs. Query 1.3 would have settled it.

---

## Prior readings, quoted as prior readings and not re-measured

| Reading | Value | Taken | Status now |
|---|---|---|---|
| `analytics_2.orders` total | 2,846,280 | 2026-08-30 | stale, not re-measured |
| `analytics_2` orders with `refund_total > 0` | 4 | 2026-08-30 | stale |
| `analytics_1` orders with `refund_total > 0` | 4 of 679,912 | 2026-08-30 | stale |
| Partial refunds (`0 < refund_total < total`), tenant 2 | **0** | 2026-08-30 | stale |
| `status = 'refunded'`, tenant 2 | 1 | 2026-08-30 | stale |
| Non-`completed` statuses first appear | ~2026-08-21 | 2026-08-28 | stale, and contested |

The last row is the one a tile would have to quote and the one least safe to.
`specs/empty-columns.md:126-147` read the status mix as proof of a backfill
coverage artefact; `research/gap-list-open-questions.md:249-254` retired that
explanation two days later, on the ground that the 25–26 August re-sync put every
historical row through the writer and the three 2025 refunds came through it
correctly. Both are now twelve days old. Requirement 2.1 asked for a coverage
date; the honest answer is that this run cannot supply one, and that the two
documents on file disagree about what the last measured one meant.

---

## If it later becomes a go: the exact caveat text (requirement 3.2)

Written out so the `dd_frontend` task lifts it rather than inventing it. These
are conditional on a go that has not been given.

* When `orders_with_refund == 0`, the tile label is:
  **"Net revenue — no refunds recorded in this window"**. Not "Net revenue"
  alone.
* When `orders_with_refund > 0`, the tile label is **"Net revenue"**, with the
  subline **"£X refunded across N orders"**.
* Any window beginning before the coverage date — which this document does not
  have — carries: **"Refund capture before <date> is unverified; this figure may
  be gross."**
* The tile must never render without `refunded_amount` and `orders_with_refund`
  available to it. A net figure whose companion fields were dropped is the wrong
  number this whole thread is about.

---

## What would settle it, costed, and whose work it is (requirement 3.3)

`specs/refund-hook.md:264-295` already sets these out; restated with what each
settles that the database cannot.

| Check | Cost | Settles |
|---|---|---|
| **V1** — grep the installed plugin on each WordPress host for `woocommerce_order_refunded` / `woocommerce_refund_created`, plus header vs constant | ~15 min per tenant | Whether the deployed build can capture refunds at all. Bears on 2.2. Does not settle 2.1. |
| **V2** — a genuine **partial** refund on a `completed` order, watching `refund_total` and `updated_at` | ~30 min incl. observation | 2.2 and 2.3 together, and it is the only instrument that does. The only behavioural proof the hook fires in production. |
| **R1** — `wp dd sync-refunds --dry-run`, then for real, per tenant | ~10 min plus runtime | 2.1, retroactively: the dry run reports the refund count the store actually holds, which is the store's own answer to "is the zero true". |
| **F1** — contingency, if V1 finds a build without the hooks | ~0.5–1 day | — |

Owner-shaped: this needs someone with filesystem or WP-admin access to each
WordPress host, and for V2, merchant consent to refund a real order. No fleet
task can do it. V1 before V2, per that spec's sequencing note.

**A cheaper instrument exists that nobody has costed, and it needs no host
access.** `api/analytics/services/reconciliation.py` records
`source_refund_total` and a `source_status_breakdown` carrying per-status
`count`, `gross` and `refund_total`, written from the connector's own manifest
(`api/analytics/models.py:361-367`, `reconciliation.py:344-372`). That is the
store asserting its own refund total, independently of whether the order-level
field was ever sent. If manifests exist for these tenants, comparing
`source_refund_total` against the platform's own sum answers requirement 2.1
directly. It is outside the current reader grant, so it is a deliberate widening
of `dd_detector_login` — one table — and per §1.6 that is the right move rather
than a query the runner cannot execute. **Recommended as the next step, ahead of
V1.**

---

## What this supersedes, and where (requirement 3.4)

Neither file may be edited by this task; `specs/**` is on the fleet floor.
Naming the sentences that are now wrong:

* `specs/metorik-gap.md:82` — the *Missing* row for "Net revenue (gross less
  refunds)" says the column is *"non-zero on 1 of 2,844,177 orders — traced
  2026-08-28 to backfill coverage, not to the sync"*. Both halves are spent. The
  count is 4, not 1 (`refund_total > 0`, not `status = 'refunded'`), and
  `research/gap-list-open-questions.md:249-254` retired the backfill explanation.
  The row's *ranking* still holds; its stated reason does not.
* `specs/metorik-gap.md:50-53`, the Daily-band prose, repeats the same
  1-of-2,844,177 figure and the same backfill attribution.
* `specs/metorik-gap.md:164-171`, item 3 of the open questions, records refunds
  as *"resolved 2026-08-28"* with the backfill reading. It is not resolved.
* `specs/empty-columns.md:126-154`, the whole "backfill coverage artefact"
  passage, including the claim that the refund-driven pass *"appears never to
  have run; nothing in the repo implements one"* — `specs/refund-hook.md:36`
  found `wp dd sync-refunds` in the connector source.
* `specs/empty-columns.md:13`, the table row giving `refund_total` the verdict
  *"the history is a backfill coverage artefact"* at Medium confidence.

Promoting these corrections is a human act.

## What I could not establish

**The whole of the database side.** Queries 1.1 through 1.5 did not run, because
this task was queued against a contract carrying no `evidence_queries`. There is
no column list, no refund census, no per-status first-appearance dates and no
monthly series from this run. Requirement 2.1's coverage date is therefore
**unknown for both tenants**, and no date should be quoted from this document by
the frontend task, because there is none in it.

**Requirement 2.3 could not be attempted at all.** Whether any refund arrived
after its order was first written needs the per-row timestamps from query 1.3.
Beyond that, the instrument itself is doubtful even when it runs: the 25–26
August re-sync put every historical row through the writer, so `synced_at` and
any `updated_at` are expected to be uniformly recent regardless of what the hook
did. The spec anticipated this and asked for it to be said plainly rather than
inferred around. It is said plainly: on the evidence available, the timestamps
probably cannot separate the two cases, and that is a prediction, not a reading.

**Requirement 2.2 is not closed by any result the database can produce.**
`refund_total` is `NOT NULL DEFAULT 0` and the writer coerces an absent field to
zero, so a partial-refund count of zero is consistent both with a store that has
never issued one and with a build that never sent the column. Re-measuring it
would have been worth doing — it is the number the spec most wanted — but a
non-zero result would have been informative and a zero result would not.

**The reader grant excluded everything except two tables.**
`research/gap-list-open-questions.md:11-19` records that `dd_detector_login`
holds SELECT on `analytics_1.orders` and `analytics_2.orders` and nothing else,
and that the readings which went beyond them were taken by hand with a migration
identity. `reconciliation_manifests` — the one table that could answer 2.1
without host access — is outside it.

**No claim is made about the deployed plugin.** Nothing in this task's reach can
read an installed WordPress file, and `plugin_version` is self-reported by the
connector. `specs/refund-hook.md` refuses that evidence class and so does this.

**Tenant 1 is weaker throughout.** Its per-row refund statuses have never been
published, so the "net is gross by construction" argument is established for
tenant 2 only and is genuinely open for tenant 1.

**The claim that no test covers the three keys is a grep, not a run.** No test
suite was executed; `api/CLAUDE.md` forbids suite runs on this host and this task
has no shell for it. A test referencing the keys indirectly — through a
response-shape fixture that does not name them — would not have been found.
