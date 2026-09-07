# The daily brief — a pass that reads what is there and writes down what it saw

**Status: SPEC. Nothing built.** Companion to `objectives-2026-Q4.yaml` and to
`deadly-digital-platform/docs/RECONCILIATION-RUNS.md` §4, whose run-table
reasoning applies here unchanged and is not re-argued.

---

## 0. What this is, and the one thing it must never become

Fleet can execute and cannot observe. The proposer has one substantive detector
and has correctly proposed nothing, so there is nothing to reason about. This is
the other half: a pass that **reads what is already queryable and writes down
what it saw**, so that tomorrow's pass has something to compare against.

It decides nothing, proposes nothing, and writes to `fleet` and nowhere else.

**The failure mode it must avoid is being plausible.** A daily brief is read
quickly, trusted by default, and almost never checked — which makes a confident
sentence about a number nobody computed more damaging than silence. Every
mechanism below exists for that: sourced claims, recency on every one, and
uncomputed things named rather than dropped.

---

## 1. What it can actually read — verified, not assumed

**The brief was specified against a list of sources that is wider than the
detector role's reach.** Measured 7 Sep 2026 against the live grants, not read
off a schema file:

### 1.1 `deadly_digital` — three tables and one column of orders

| schema | readable by `dd_detector_login` |
|---|---|
| `public` | **`orders`, `tenants`, `utm_source_alias`. That is all.** |
| `analytics_1` | **`orders`. Only.** |
| `analytics_2` | **`orders`. Only.** |

Not readable, and each is something a brief would obviously want: `customers`,
`sync_jobs`, `sync_log`, `campaigns`, `billing_usage`, `meta_ad_metrics`,
`import_history`, `consent_audit`, and every `analytics_<t>` table other than
`orders` — including `daily_metrics` and `reconciliation_manifests`.

### 1.2 `fleet` — ten of the twenty-five tables

`dd_detector_login` can `SELECT`: `observations`, `issues`, `issue_occurrences`,
`observation_coverage`, `detector_runs`, `detector_registry`,
`detector_definition_boundaries`, `routing_policy`, `source_registry`,
`verdict_coverage_policy`.

**Four of the six fleet sources named in the brief for this work are not among
them:** `decision_log`, `decision_outcomes`, `tasks`, `runs`. Also unreachable:
`proposals`, `proposal_evidence`, `decisions`, `observation_verdicts`,
`run_steps`, `task_transitions`, `task_reclaims`, `model_calls`, `infra_costs`,
`budget_reservations`, `scheduled_checks`, `step_authority`,
`protected_path_floor`.

### 1.3 The filesystem, which needs no grant

Git history of both repos; `capacity-samples/` (`drift.log`,
`drift-frontend.log`, `memory.csv` and the `.state` files the drift checker
maintains); the repos' own documents — `docs/TODO.md` is the issue tracker,
`objectives-2026-Q4.yaml`, `cycle.yaml`, `runner.yaml`, `api/CLAUDE.md`;
systemd unit and timer state; `docker ps` and container health.

---

## 2. What else exists that the brief did not name

Answering the question directly. Everything here is real and reachable **today**
without a new grant, unless marked.

1. **`capacity-samples/`.** A cron writes `drift.log` every 15 minutes. It
   already answers "is the running image the same commit as `origin/main`", and
   it moves: at 16:15 UTC on 7 Sep 2026 it reported the API 3 commits ahead and
   unpushed; by 21:15 the same day it reported `resolved — production matches
   origin/main`. **Both readings were written into this spec five hours apart,
   and the first was stale by the time it was committed** — which is the whole
   argument for `as_of` on every claim, demonstrated at the spec's own expense.
2. **`docs/TODO.md`.** The real issue tracker: `CI-002`, `TEST-003`, `DATA-002`,
   `BUG-020` and the rest live there as prose with dates and OPEN/PARKED status —
   46 dated entries as of 7 Sep 2026. Counting open entries and naming ones whose
   date has not moved is a genuine signal and needs no database.
3. **Container and unit state.** Seven production containers; `docker ps`
   reports uptime and health. `deadly-digital-api` is the only one with a
   healthcheck.
4. **The API's own `/health/deps`**, on `localhost:8000`. It reports database
   and Listmonk reachability from inside the app, which is a different question
   from whether the brief's own connection works.
5. **`git log` as a work record.** Commits per repo per day, files touched,
   which branches exist and how far each is from `main`. This is the only
   available measure of engineering time, which `objectives-2026-Q4.yaml` names
   as the binding constraint.
6. **Unpushed and unmerged work.** Branches that exist locally and not on the
   remote, or vice versa. As of 7 Sep 2026: seven `fix/*` branches on the
   platform repo, none merged to `main`.
7. **`utm_source_alias`** — readable, and the only attribution-shaped table the
   detector can see.
8. **`infra_costs` and `model_calls`** (fleet, **grant needed**). These are the
   only sources for `cost-discipline`, which is an objective with a hard number
   (£200/month) and no other evidence path.
9. **AWS billing** — not reachable from this host at all, no credentials. Named
   so the cost objective's evidence gap is explicit rather than discovered.
10. **GitHub Actions** — not reachable. `gh` is not installed and the repo is
    private, so CI results cannot be read programmatically. The brief cannot say
    whether the build is green.

---

## 3. Grants it would need — named, not taken

Nothing below is applied by this spec. Each is a decision.

| grant | unlocks | without it |
|---|---|---|
| `GRANT SELECT ON decision_log, decision_outcomes TO dd_detector_login` | decisions made, and their derived outcomes | the brief cannot mention decisions at all |
| `GRANT SELECT ON tasks, runs, run_steps TO dd_detector_login` | what fleet executed, attempts, cost per task | no execution reporting |
| `GRANT SELECT ON model_calls, infra_costs TO dd_detector_login` | AI spend and infrastructure cost | `cost-discipline` has **no** evidence path |
| `GRANT SELECT ON proposals, proposal_evidence TO dd_detector_login` | what the proposer said | cannot report "proposed nothing" as a fact rather than an assumption |
| `GRANT SELECT ON <schema>.daily_metrics TO dd_detector_login` (per tenant) | revenue and order trends without scanning `orders` | every trend is a live aggregate over 2.8M rows |
| `GRANT INSERT ON brief_runs, brief_claims TO <writer>` | the brief can be written at all | **required**; see §4.1 |

**The write identity is a decision, not a detail.** §4.2 of `RECONCILIATION-RUNS`
settled that the auditor must not hold write access to what it audits, and the
same argument applies: this pass reads `deadly_digital` and must keep being
unable to write there. It writes only to `fleet`, and the cleanest arrangement is
the one the reconciliation runs already imply — **read `deadly_digital` as
`dd_detector_login`, write `fleet` as a separate identity**, so no single role
both reads the business and writes the record of it.

---

## 4. Where a brief goes

### 4.1 Two tables, for the reason §4 already gives

`fleet.public.brief_runs` and `fleet.public.brief_claims`. In `fleet` because a
brief is **a record about the business, not business data** — the same boundary
argument as the reconciliation run tables, and the same one that keeps
`observations` and `detector_runs` where they are.

Two tables rather than one, for the reason the level-3 receipt exists: **"the
brief found nothing to report" and "the brief did not run" must not look
alike.** A run row with zero claims is a positive assertion that a pass happened
and had nothing to say. No run row means no pass. One table cannot express that.

Append-only, immutable after insert, on the same terms as `decision_log` and
`reconciliation_runs`. A corrected brief is a new brief; the sequence is the
signal.

### 4.2 `brief_runs` — one row per pass

```
id                bigserial PRIMARY KEY
generated_at      timestamptz NOT NULL DEFAULT now()

-- The window this brief compares against: the previous run's generated_at.
-- NULL on the first ever run, which is a fact rather than a gap.
compares_since    timestamptz

code_version      text NOT NULL          -- git sha of the fleet repo
objectives_version text NOT NULL         -- sha256 of objectives-2026-Q4.yaml,
                                         -- so a brief written against changed
                                         -- objectives is detectable

-- Which sources the pass could actually reach, AS IT FOUND THEM. A source that
-- was unreachable today and reachable yesterday is the finding, and it is only
-- visible if each run records its own answer rather than assuming the roster.
sources_reachable   jsonb NOT NULL       -- [{name, dsn_role, as_of, ok, detail}]
sources_unreachable jsonb NOT NULL

claims_total      integer NOT NULL
claims_uncomputed integer NOT NULL       -- see §5; zero is a claim in itself

-- The brief as issued, rendered from the claims below. Stored because it is the
-- artefact a person read, and it is immutable, so it cannot drift from them.
-- The CLAIMS are canonical for comparison; this is the copy of record.
rendered_markdown text NOT NULL

started_at        timestamptz NOT NULL
completed_at      timestamptz NOT NULL

CONSTRAINT brief_runs_counts_ck
    CHECK (claims_total >= 0 AND claims_uncomputed BETWEEN 0 AND claims_total)
```

### 4.3 `brief_claims` — one row per claim, and the rule lives here

One row means: *"the pass asserts this, from this source, as of this instant —
or states that it could not."*

```
id            bigserial PRIMARY KEY
run_id        bigint NOT NULL REFERENCES brief_runs(id) ON DELETE CASCADE

section       text NOT NULL   -- 'CHANGED' | 'LOOKS_WRONG' | 'UNCOMPUTED'

-- Stable across runs, and the mechanism that makes accumulation useful: today's
-- row joins to yesterday's on this key. Without it, comparing briefs is prose
-- diffing and nobody does it twice.
metric_key    text NOT NULL   -- e.g. 'dd.analytics_2.orders.count'

statement     text NOT NULL   -- one sentence, as it appears in the brief

-- THE RULE. Both NOT NULL on every COMPUTED claim. A claim that cannot say
-- where it came from or how old it is does not go in the brief.
source        text            -- 'deadly_digital:analytics_2.orders', 'git:fleet', ...
as_of         timestamptz     -- the instant the value describes, NOT now().
                              -- A snapshot read at 03:00 of a table last written
                              -- at 21:00 yesterday is as_of 21:00.

value_num     numeric         -- populated when the claim is a number
value_text    text            -- populated when it is not
previous_num  numeric         -- yesterday's value for this metric_key, copied
                              -- from the previous run's row, NOT recomputed
delta_num     numeric         -- value_num - previous_num, when both exist

-- Reproducibility, on the same terms detectors/reconciliation.py already sets:
-- "evidence whose query text cannot be recovered is not evidence".
query_key     text            -- the named query that produced it
query_version integer

status        text NOT NULL CHECK (status IN ('COMPUTED','UNCOMPUTED'))
uncomputed_reason text        -- NOT NULL when status = 'UNCOMPUTED'

CONSTRAINT brief_claims_computed_is_sourced_ck CHECK (
    status <> 'COMPUTED'
    OR (source IS NOT NULL AND as_of IS NOT NULL
        AND (value_num IS NOT NULL OR value_text IS NOT NULL))),

CONSTRAINT brief_claims_uncomputed_says_why_ck CHECK (
    status <> 'UNCOMPUTED'
    OR (length(btrim(uncomputed_reason)) > 0
        AND value_num IS NULL AND value_text IS NULL)),

CONSTRAINT brief_claims_uncomputed_section_ck CHECK (
    (section = 'UNCOMPUTED') = (status = 'UNCOMPUTED'))
```

**The two check constraints are the spec.** A computed claim without a source or
a recency cannot be inserted; an uncomputed one that does not say why cannot
either, and cannot smuggle a value in beside the excuse. The discipline is in the
schema rather than in the renderer, because a renderer is one refactor away from
dropping a field and a constraint is not.

---

## 5. What it deliberately does not claim

1. **It does not say the business is healthy.** It reports what changed and what
   looks wrong against thresholds it was given. "Nothing looks wrong" means
   nothing it checked looked wrong, and the uncomputed list is printed beside it
   so the reader can see the size of what was not checked.
2. **It does not compute anything from a source it could not reach.** No
   fallbacks, no last-known-good, no interpolation. Unreachable is `UNCOMPUTED`
   with the reason, every day, until the grant exists or the source returns.
3. **It does not report CI status.** Actions is unreadable from this host (§2.10)
   and the brief says so rather than inferring from the last local test run.
4. **It does not report AWS spend** (§2.9). `cost-discipline` has a hard £200
   number and no reachable evidence; the brief carries that as a standing
   uncomputed claim rather than substituting `infra_costs` and implying it is the
   bill.
5. **It does not rank, score or prioritise.** No objective weighting, no "most
   important thing today". Weights exist for the proposer; a reader who sees a
   ranked brief will treat it as a recommendation, which is the line this pass
   does not cross.
6. **It does not deduplicate against yesterday.** A condition that is still true
   is reported again. Suppressing repeats is how a persistent problem becomes
   invisible on day three, and `issue_occurrences` already exists for anyone who
   wants the first-seen date.
7. **It does not read `analytics_2` for anything but `orders`**, because that is
   all it can read, and it does not present order-derived figures as revenue
   without saying they are order-derived.
8. **It makes no claim about a tenant it did not query.** Two tenants exist; a
   brief that reports on one says so.

---

## 6. How to tell a useful brief from a plausible one

The question the spec is judged on. Six tests, in order of how cheaply they
falsify.

**1. Pick any sentence and find its provenance.** Every claim in the rendered
brief carries a source and an `as_of`. If a sentence cannot be traced to a
`brief_claims` row with both, the renderer invented it. This is checkable in
seconds and catches the most common failure.

**2. Check the uncomputed count is not zero.** Today it cannot honestly be: four
of the six named fleet sources need grants, AWS is unreachable, CI is unreadable.
**A brief reporting zero uncomputed claims on current grants is lying**, and that
is the single fastest tell. The count is on the run row precisely so it can be
read without opening the brief.

**3. Break a source and re-run.** Revoke one grant, or stop the container. The
claims that depended on it must move to `UNCOMPUTED` **with the reason**, and the
rest of the brief must still be produced. A pass that dies, or that quietly emits
a shorter brief, has failed the test that matters most — because that is what a
real outage looks like.

**4. Seed a known change and confirm it is named.** Insert an order in
`analytics_1` (safe to break; `analytics_2` is HIB production and read-only for
this work), or land a commit. The next brief must name it with the right
magnitude. A brief that reports "no significant change" after a seeded change is
measuring nothing.

**5. Compare two consecutive briefs on `metric_key`.** Deltas must reconcile:
`value_num - previous_num = delta_num`, and `previous_num` must equal the prior
run's `value_num` for that key. If deltas are recomputed from today's database
instead of carried from yesterday's row, a brief will silently restate history
whenever a source is backfilled — the same defect as a view that recomputes
"the evidence this decision cited".

**6. Read yesterday's brief and today's for a metric that did not change.** Both
should carry it with the same value and *different* `as_of`. A metric whose
`as_of` does not move is being read from a stale cache or a frozen source, and
that is invisible in prose.

**And one anti-test.** A brief that reads well, names no source, and has nothing
in its uncomputed list is the artefact this spec exists to prevent. It will be
the most pleasant to read.

---

## 7. Open questions

1. **Cadence and trigger.** Daily is stated; the time and whether it is systemd
   or the existing cycle runner is not decided.
2. **Thresholds for `LOOKS_WRONG`.** The section needs numbers to compare
   against. Deriving them from history risks blessing whatever is normal today;
   stating them by hand makes them another hand-maintained tally. Undecided, and
   the brief should carry no `LOOKS_WRONG` claims until it is.
3. **Whether the brief may read `docs/TODO.md`.** It is the real issue tracker
   and it is prose. Parsing it is brittle; ignoring it loses the largest record
   of known problems.
4. **Retention.** `decision_log` is kept indefinitely with `DELETE` reserved to
   `fleet_admin`. A daily brief accumulates 365 rows a year plus claims; the same
   terms probably apply but have not been decided.
5. **Who reads it, and where.** A table is not a delivery mechanism. Nothing here
   specifies how the brief reaches a person.
