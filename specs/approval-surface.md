# The approval surface — from a findings list to a queued task

**Status: SPEC. Nothing built.** Reads: `003_tasks.sql`, `010_decision_log.sql`,
`contracts/`, `console/app.py`, `console/decide.py`, `run_task.py`,
`docs/RECONCILIATION-RUNS.md` §5.1, `contracts/research.yaml`.

---

## 0. Two facts that change the shape of this

Found while reading, and both alter what the surface has to be.

**1. There is no production path that creates a task.** `INSERT INTO tasks`
appears five times in the repository and every one is in `tests/`. `run_task.py`
claims and runs; it does not enqueue. So the approval surface is not a
convenience layer over an existing mechanism — **it is the first thing that will
ever create a task outside a test**, and it inherits responsibility for every
invariant the tasks table currently gets by nobody exercising it.

**2. There is no runner timer.** Installed units are `fleet-brief`,
`fleet-proposer-cycle`, `fleet-heartbeat`, `fleet-reconciliation`,
`fleet-console` and `fleet-detector@`. The runner is hand-invoked. The
"overnight batch of five branches against wrong paths" is therefore not
currently possible, and the thing that prevents it is that a person types a
command — which is a control nobody chose and which disappears the moment
someone adds a timer.

Both mean this spec has to say what the ceiling is explicitly, because the
ceiling today is an accident.

---

## 1. What a candidate row holds

One row per work item, in `fleet.public.candidates`. Enough to decide from
without opening anything, and enough that a spec can be written from it after.

```
id            bigserial PRIMARY KEY
batch_id      bigint NOT NULL REFERENCES candidate_batches(id)

title         text NOT NULL          -- one line, imperative
rationale     text NOT NULL          -- why this is worth doing, from the finding
repo          text NOT NULL
work_type     text NOT NULL          -- must match a contract in contracts/
objective_ref text                   -- an id from objectives-2026-Q4.yaml

-- WHERE THE EVIDENCE LIVES, and it is a citation rather than a copy.
-- The finding is a document (RECONCILIATION-RUNS.md section 5.1, the Metorik
-- gap list) and documents move. So the row carries the source AND the commit
-- it was read at, which is the same discipline the daily brief's `as_of` and
-- `observations`' evidence_query_version already enforce: a claim that cannot
-- be re-derived is not evidence.
evidence      jsonb NOT NULL DEFAULT '[]'::jsonb
              -- [{kind: document, repo, path, section, read_at_sha},
              --  {kind: query, key, version, value, as_of}, ...]

-- The paths the finding SAYS this touches. Advisory, and explicitly not the
-- contract: the contract comes from contracts/<work_type>.yaml at queue time.
-- Recorded because it is what a reviewer needs to judge scope, and because
-- section 3's check compares it against the repository.
suggested_paths text[] NOT NULL DEFAULT '{}'

est_cost_gbp  numeric(10,4)          -- for the batch ceiling in section 5
est_diff_lines int

disposition   text NOT NULL DEFAULT 'PENDING'
              CHECK (disposition IN ('PENDING','APPROVED','NOT_NOW','REJECTED'))
disposition_reason text               -- NOT NULL when REJECTED; see section 4
decided_at    timestamptz
spec_task_id  bigint REFERENCES tasks(id)   -- the draft-spec task, section 3
work_task_id  bigint REFERENCES tasks(id)   -- the code task, if it got that far

CONSTRAINT candidates_rejection_says_why_ck CHECK (
    disposition <> 'REJECTED'
    OR (disposition_reason IS NOT NULL
        AND length(btrim(disposition_reason)) > 0))
```

`candidate_batches` holds where the list came from (`source_document`,
`source_sha`, `generated_at`, `generated_by`) so a batch is attributable to a
finding at a commit, not to a morning.

**What it deliberately does not hold: a spec.** A candidate is a proposal to
write one. Section 3 is about why those are different.

---

## 2. What the surface is

A console page, `/candidates`, following the shape the console already has: a
list, a form, `same_origin` CSRF, and `rendered_at` so the decision clock is
measured rather than assumed — exactly as `/tasks/{id}/accept` does today.

**It is the second write route on the console, and the first that creates
anything.** `/decisions` deliberately has no form on it, and its reasoning
applies here and is worth quoting because it constrains the design:

> *"a textarea on a web page is where a reason becomes 'yes' — whereas `fleet
> decision record --reason` makes the sentence the thing you are typing."*

So the tick boxes are on the page and **the reason is not a textarea beside
them**. Section 4 says what is typed instead.

---

## 3. What a ticked row produces — the argument

Three options. The middle one, and the reason is your own evidence.

| | what a tick does | why not |
|---|---|---|
| **A** | queues the code task directly, spec generated inline | Two hand-written specs contained factual errors about file paths. A generated one is not better-informed than a hand-written one; it is faster at being wrong. Five branches against wrong paths is the observed cost. |
| **C** | produces nothing; you write the spec by hand as now | This is the bottleneck the task exists to close. |
| **B** | **queues a research task that writes a DRAFT SPEC, which you review through the accept/reject flow that already exists** | **Recommended.** |

### Why B, concretely

**It reuses the research contract unchanged.** `contracts/research.yaml` already
describes a task that produces a document rather than a branch of code: one
writable file, no shell, no credential, no database reach, and an evidence pack
the runner assembles *before* the agent starts. A draft spec is that shape
exactly.

**It puts the observed failure behind a machine check.** The errors were
*factual claims about the repository* — paths that do not exist. That class is
checkable without judgement, and `contracts/checks/` is already the place such
checks live. So the draft-spec contract carries a check that fails the task when
the spec names a path absent from the repo at the base commit, and when a path
it declares writable is on `protected_path_floor`. **A spec that cannot be
verified against the tree it describes does not reach review.** That converts
the exact error you observed from something a reviewer must catch into something
a task cannot pass with.

**It keeps the expensive mistake cheap.** A draft-spec task is one file, a small
budget and a short timeout. A code task built on a wrong spec is a branch, a
review and a rework. Paying the small one to avoid the large one is the trade,
and it is the same trade as the settle lag on a manifest: cheaper to find out
before than after.

**The second review is smaller than the first.** Reviewing a spec against a
check that has already confirmed its paths exist is reading for intent, not for
facts. That is the part that cannot be delegated and the part that is quick.

### The cost, stated

Two review cycles per item instead of one, and a day's latency between ticking
and building. **If that is too slow, the honest lever is batching the reviews —
ten draft specs reviewed in one sitting — not removing the gate.** Option A's
speed comes entirely from not checking the thing that was wrong both times.

---

## 4. What approval records

An approval is a decision, and `decision_log` is the right home: unlike `002`'s
`decisions` it does not require a `proposal_id`, it has a `task_id`, and its
`reason` is free text and `NOT NULL` on every row including rejections.

**Ticking ten rows must not write ten reasons.** Ten copies of "yes" is the
`UNRECORDED` problem arriving by a new route, and the constraint would be
satisfied while the column stopped meaning anything.

The honest structure, which loses nothing:

**One `decision_log` row per batch, with one reason — and the reason is about
the selection, not about each item.** *"These four are what the first merchant
onboarding is blocked on; the reporting work waits until there is a merchant to
report to"* is genuine reasoning and is more informative than four
paraphrases of "yes". `evidence` carries the whole candidate list with every
disposition, snapshotted, which is what that column is for: *"the evidence AS IT
STOOD"*.

**Plus a row per item where you deviate.** Two cases, and only two:

- **A rejection.** Reason required, at the item. This is the informative half
  and it is where the typing goes.
- **An approval the ranking did not recommend.** If the list is ordered and you
  tick something below the line, that is a judgement the batch reason does not
  contain.

Everything else — ticking what was recommended, leaving something for later —
is covered by the batch row and its evidence snapshot.

**Where the reason is typed.** Per `/decisions`' own argument, not in a textarea
beside a tick box. The batch reason is the last field of the submit, on its own,
with the ticked list rendered above it — so the sentence is written against a
visible selection rather than beside each checkbox. Rejection reasons are typed
per item, because a rejection is the one place a sentence is the point.

---

## 5. How rejections are kept

**A candidate is never deleted and a batch is never discarded.** Three
dispositions, and the distinction between the middle two is the whole point:

- `APPROVED` — became a draft-spec task.
- `NOT_NOW` — **not rejected, and not gone.** Carried into the next batch
  automatically, with its original `batch_id` retained so its age is visible.
  A candidate that has been carried five times is itself a finding — either it
  is not worth doing or it is being avoided, and both are worth seeing.
- `REJECTED` — will not be done, reason required, and it stays in the table
  forever.

A ticked list that discarded what was not ticked would lose exactly the half you
argue is more informative. It would also lose the *repetition*: the same
candidate reappearing in three batches and never being ticked says something no
single row does.

---

## 6. What stops a bad batch

Four ceilings. **Every one in the database**, on the precedent the tasks table
already sets for `timeout_seconds`: *"a cap that can be raised without a
migration will be raised on the morning something needs longer."*

1. **Queue depth.** A partial index or trigger refusing `INSERT` when the count
   of `QUEUED` tasks is at the cap. Proposed: **5**. Not a config value.
2. **Monthly credit.** The pool does not roll over, so the ceiling is a month's
   remaining credit against `model_calls` and settled `budget_reservations` for
   the current month. **The check happens at approval time, not at claim time**
   — a batch that cannot be afforded should be refused while you are looking at
   it, not discovered half-built at 3am. The surface refuses to queue when
   `SUM(est_cost_gbp)` of the batch exceeds what is left.
3. **Per task.** `max_cost_gbp` is already `NOT NULL CHECK (> 0)` and
   `timeout_seconds` is already ceilinged at 3600. Nothing to add; named so it
   is not re-solved.
4. **One at a time.** The runner does one task per tick and there is no timer,
   so concurrency is one and the batch drains at whatever rate someone runs it.
   **If a timer is added, that is a separate decision and this ceiling changes
   character** — it becomes the real throttle rather than an accident. It should
   be decided deliberately, not inherited.

**What is NOT a ceiling:** the number of candidates in a batch. Generating
twenty for review is cheap and reviewing them is the work. The constraint
belongs at the point where money is spent, which is queueing, not listing.

---

## 7. What this is not

- **Not spec generation for code.** A draft spec is written by a research task,
  checked mechanically, and reviewed by you before any code task exists.
  Generating a spec and building from it in one motion is the thing that would
  have produced five wrong branches.
- **Not autonomy.** Nothing is queued that was not ticked. Nothing merges: the
  runner has never merged and `/tasks/{id}/accept` remains the only path to a
  base branch, driven by a person.
- **Not a proposer replacement.** The proposer reasons about what is worth
  doing from detectors. This surface starts from a findings list that already
  exists. They meet later, if a candidate batch is ever generated from
  proposals rather than from a document.

---

## 8. What I am unsure about

1. **Nothing produces candidate rows yet.** §5.1 and the Metorik gap list are
   prose in documents. Something must turn a findings document into rows —
   by hand at first, or by a research task whose output is the batch. **This
   spec assumes the rows exist and does not say where they come from.** That is
   the largest gap in it.
2. **`work_type` must match a contract, and there are eight.** Whether the
   candidate names the contract or the draft spec chooses it is undecided. If
   the candidate names it, a wrong choice is caught at review; if the spec
   chooses, the check must verify the choice.
3. **Whether the draft-spec task should read the repository at all.** The
   research contract gives the agent no shell and no database. A spec-writing
   task that cannot read the code it specifies will get paths wrong — which is
   the failure this is preventing. Giving it read access to a worktree is
   probably necessary and is a change to the research contract's central
   property. **This needs deciding before anything is built.**
4. **The batch reason's granularity.** One reason for four related items is
   honest. One reason for twenty unrelated ones is a paragraph pretending to be
   a rationale. There may need to be a cap on batch size for the reason to
   remain meaningful, and I do not know where it is.
5. **Queue depth of 5 is a guess**, in the way the settle lag and the level-3
   cap are guesses, and should be labelled as one until something measures it.
