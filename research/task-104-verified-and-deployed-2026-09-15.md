# Task 104 — requirement 7's proof re-run, and the endpoints after deploy

Companion to `research/task-102-measurement-2026-09-15.md`, which measured the
restriction alone and concluded the `LATERAL` form was justified. This records
what happened when it was built, and is the answer to the last thing task 102's
requirement 7 asked for.

Task 104 merged as `d7a34b3` at 11:05 on 15 Sep 2026 and was deployed by hand at
12:32. Tenant 2 (`analytics_2`): 2,888,640 orders, 157,258 customers.

## Requirement 5's proof, RE-RUN — not reused

Requirement 7 said the identity proof "must be re-run — not reused from the
restriction step". It was. The `LATERAL` CTEs under test were read out of
`_acquiring_order_ctes()` **as merged**, not from the earlier prototype and not
from the restriction: `research/task-104-identity-proof-body.sql`.

Compared against pre-104 `fd20133`, both directions of `EXCEPT ALL`:

| window | result |
|---|---|
| `2026-08-15 .. 2026-09-15` | **0 rows** |
| `2026-07-20 .. 2026-08-11` (spans the month boundary) | **0 rows** |
| `2000-01-01 .. 2100-01-01` (all history) | **0 rows** |
| `2019-01-01 .. 2019-02-01` (no orders) | **0 rows** |

Five statements per window: `revenue_report` at day and month granularity,
`revenue_summary`, and both of `customer_report`'s statements — full result
rows, every column.

History is still unbounded under `LATERAL`: 17,352 acquiring orders predate the
30-day window (earliest 2023-03-15), 16,669 for the boundary window. The outer
projections remain token-identical to `fd20133` in all five statements, checked
mechanically — the merge changed the CTE and nothing else.

## The statements, as merged

Medians of three, `EXPLAIN (ANALYZE, BUFFERS)`, 30-day window.

| statement | base | task 102's restriction | as merged (`LATERAL`) |
|---|---|---|---|
| `revenue_report` day | 5,787 ms | 3,595 ms | **408 ms** |
| `revenue_report` month | 4,307 ms | 3,408 ms | **438 ms** |
| `revenue_summary` | 4,227 ms | 3,477 ms | **354 ms** |
| `customer_report` daily | 4,232 ms | 3,294 ms | **366 ms** |
| `customer_report` totals | 3,951 ms | 3,256 ms | **328 ms** |

## The endpoints — measured, not projected

Three warm runs each, warm-up discarded, tenant 2, 30-day window
(`start=2026-08-15&end=2026-09-14`).

**Before** — taken 11:50, production on `fd20133`:

| endpoint | runs | median |
|---|---|---|
| `/api/analytics/revenue` | 8.329, 7.714, 7.862 s | **7.86 s** |
| `/api/analytics/customers` | 7.033, 7.080, 7.074 s | **7.07 s** |

**After** — taken 12:39 on a settled box (load 0.97), production on `d7a34b3`:

| endpoint | runs | median | factor |
|---|---|---|---|
| `/api/analytics/revenue` | 1.176, 1.175, 1.167 s | **1.18 s** | **6.7×** |
| `/api/analytics/customers` | 0.696, 0.723, 0.704 s | **0.70 s** | **10.0×** |

A first set taken at 12:33 under load 3.30 from the deploy build gave 1.179 s
and 0.662 s — the two sets agree, so the figures are not a quiet-box artefact.

The projection in the earlier document was 1.2–1.3 s and 0.8–1.0 s. Revenue
landed inside it; customers beat it.

Both pages are now below the 1.73 s the dashboard sits at, which is the bar
task 102's spec set for declaring the work finished.

## That the running code is the merged code, established three ways

Because "merged" and "deployed" are different states and the gap between them
has cost this system money twice — `console/deploys.py` says so in its own
header:

* `/health` reports `commit: d7a34b3652c097d91268100480890118adcf4efb`
* the container's `analytics_engine.py` is md5 `87f1209875a281029e15868bdb415903`,
  byte-for-byte the merged file, and contains 5 references to
  `_acquiring_order_ctes` where the previous image had 0
* `api/drift-check.sh` now exits 0 with `status=OK detail=d7a34b3`

Before the deploy, the same three checks all said `fd20133` — which is why the
first measurement above is a genuine before and not a null result.

## AND THE DEPLOY DID NOT HAPPEN BY ITSELF, WHICH IS A DEFECT

`run_autodeploy.py` refused, and has refused every day it has ever run:

    Sep 09  production is already running main
    Sep 10  1 commit(s) ahead and none is a merge this fleet made
    Sep 11  10 commit(s) ahead and none is a merge this fleet made
    Sep 12  production is already running main
    Sep 13  production is already running main
    Sep 14  drift-check says DRIFT before this started
    Sep 15  production is already running fd201331bb7c

**It has never deployed anything.** The 14 Sep refusal and today's are the same
one, and it is structural rather than bad luck:

`api/drift-check.sh` writes three statuses — `OK`, `DRIFT` (production is
BEHIND, exit 1) and `AHEAD` (production runs a commit not on origin/main, exit
4, which is DEPLOY-003). `console/autodeploy.py` refuses on `deployment.status
!= "OK"`, so it treats BEHIND and AHEAD identically.

BEHIND is not a hazard. **BEHIND is the state that means there is something to
deploy.** Refusal 1 is written for the AHEAD case — "deploying onto a production
that already disagrees with main compounds two problems into one incident" —
and that argument is right about AHEAD and does not hold for BEHIND, where
deploying is what resolves the disagreement.

So after any merge that touches `api/`, the 15-minute drift check flips the
state to `DRIFT` and the 04:15 timer refuses. The only window in which
autodeploy can ever fire is the gap between a merge and the next drift check,
which a once-daily timer cannot be expected to hit.

This deploy was therefore done by hand, `api/deploy.sh`, after checking the
other four refusals by hand: no task RUNNING, no migration in the range
(`fd20133..d7a34b3` is task 104's two commits and touches no
`api/alembic/**` or `api/analytics/migrations/**`), and the range is a merge
the fleet made. **The one-line fix — distinguishing `DRIFT` from `AHEAD` — is
not made here**; it wants its own change and its own argument.
