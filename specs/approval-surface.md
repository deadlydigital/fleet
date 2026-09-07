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
ceiling today is an accident. **§6.1 makes the ordering a requirement: the
ceilings must exist before a timer does, not after.**

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

-- NO work_type. DECIDED 7 Sep 2026: the draft spec chooses it, not the
-- candidate. A producer reading a findings document does not know whether an
-- item is a code change or an investigation — that is what the spec-writing
-- step exists to determine, and requiring it here would make the producer
-- guess at exactly the thing the next step is for.
--
-- Consequence for the check in section 3: it must now also verify that the
-- work_type the draft spec chose names a contract that exists, because nothing
-- upstream has established that any more.
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

## 3. What a ticked row produces — DECIDED: option B

Three options. The middle one, and the reason is your own evidence.

| | what a tick does | why not |
|---|---|---|
| **A** | queues the code task directly, spec generated inline | Two hand-written specs contained factual errors about file paths. A generated one is not better-informed than a hand-written one; it is faster at being wrong. Five branches against wrong paths is the observed cost. |
| **C** | produces nothing; you write the spec by hand as now | This is the bottleneck the task exists to close. |
| **B** | **queues a research task that writes a DRAFT SPEC, which you review through the accept/reject flow that already exists** | **DECIDED 7 Sep 2026.** The path check is the reason: the error class hit twice is machine-checkable, so it becomes something a task cannot pass with rather than something a reviewer must catch. Two review cycles is the accepted price. |

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

### 3.1 DECIDED — the spec-writer gets a read-only worktree

**This is a deliberate change to `contracts/research.yaml`'s central property,
and it is worth naming as one rather than letting it arrive as a config
difference.**

The research contract gives the agent no shell, no credential and no database
reach, and assembles an evidence pack *before* the agent starts. That design
buys three things: the agent cannot act, cannot leak, and cannot follow a hunch
into a query nobody wrote. Its cost, stated in the contract itself, is that
*"when the pack is wrong the task is reworked"*.

For a research document that trade is right. **For a spec it is not**, and the
reason is the whole argument for option B: a spec-writer that cannot read the
code it specifies will get paths wrong, which is precisely the failure this
design exists to prevent. Handing it a pre-assembled pack would mean the pack
author has to already know which files matter — and if they knew that, they
could have written the spec.

So the draft-spec contract adds **read access to a worktree of the base
commit, and nothing else**:

| research contract property | draft-spec contract |
|---|---|
| no shell | **unchanged** — no shell |
| no credential, no database | **unchanged** — none, and `.env` is gitignored so absent from a fresh worktree |
| one writable file | **unchanged** — the spec, and nothing else |
| contract frozen once RUNNING | **unchanged** |
| **evidence pack, repository unseen** | **replaced by a read-only checkout of the base commit** |

**Only the blindness goes.** The agent can read the tree it is writing a spec
about; it still cannot run anything in it, reach anything outside it, or write
to it. The blast-radius argument the research contract makes about web access
holds unchanged here and for the same reason: a file it reads is untrusted
input that can make the document wrong, and that is what review is for. It
cannot do anything, because there is still one writable file, no shell and no
secret.

**What this costs, and it is real.** Reading the tree is how the agent learns
which paths exist; it is also how a wrong or stale file teaches it something
untrue. The path check in §3 is what catches the first class. Nothing catches
the second, and that is what the human review is for — which is why option B
has two gates and not one.

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

### 6.1 A STATED DEPENDENCY: the ceilings must exist before a timer does

Today the thing that prevents an overnight batch of five branches against wrong
paths is **that a person types `run_task.py`**. That is not a control anyone
chose. It is the absence of a timer, and it holds only until someone adds one.

**The ceilings in this section are what replace it.** They are not defence in
depth on top of a human in the loop; they are the human in the loop, expressed
as constraints, for the moment that human stops being in it.

So the ordering is a requirement rather than a preference:

> **Queue depth, the approval-time credit check, and the per-task caps must all
> be in place and tested BEFORE `fleet-runner.timer` is installed — not
> afterwards.**

Installing a timer first would create exactly the window this spec was written
to close, and it would create it silently: nothing would fail, nothing would
alert, and the first evidence would be five branches in the morning. A timer is
a one-line unit file and is therefore the easiest thing here to add casually,
which is why the dependency is written down rather than assumed.

If a timer is ever added while these are absent, the honest description of the
system is that it has no ceiling at all — the earlier one having been removed
and the later one not yet built.

5. **Approval batch size: 5, DECIDED 7 Sep 2026.** Cap the batch, not the
   reason. Four related items can share one honest rationale; twenty unrelated
   ones cannot, and the reason becomes a paragraph pretending to be one. Set to
   the same 5 as queue depth, because a batch that cannot be queued is a batch
   that should not have been approved.

**What is NOT a ceiling:** the number of candidates in a BATCH LISTED for
review. Generating twenty candidates for consideration is cheap and reviewing
them is the work; the cap is on how many may be **ticked at once**, which is
where money is spent.

### 6.2 A consequence of capping approval at the queue depth

Under §3 a tick produces a **draft-spec task**, and an approved draft spec then
produces a **code task**. Both are rows in `tasks`, so both count against the
same queue depth of 5.

Ticking five candidates therefore fills the queue, and no code task can be
queued until some of those spec tasks drain. **That is the correct behaviour
and worth stating rather than discovering:** it means the system cannot be
running five specs and five builds at once, and the natural rhythm is a batch of
specs, then a batch of builds, rather than both at once.

If that proves too tight in practice the lever is raising the depth
deliberately, with the number re-labelled as measured rather than guessed — not
exempting one kind of task from the count, which would make the ceiling
describe something other than what is running.

---

## 7. The producer interface — stated, not solved

**Nothing produces candidate rows today.** §5.1 and the Metorik gap list are
prose in documents, and this spec does not say how they become rows. It is
deliberately not solved here: turning a findings document into structured rows
is its own piece of work, and doing it badly inside this spec would bury it.

What is stated is **the interface a producer must emit**, so that whatever
writes the Metorik list — a person with a SQL client, a research task, or the
proposer later — has something to write against rather than a shape invented at
the time.

### The contract a producer must satisfy

A producer emits **one batch and one or more candidates**, in one transaction.
A batch with no candidates is a producer that ran and found nothing, which is a
different fact from a producer that did not run — the same distinction
`brief_runs` makes against `brief_claims`, and it is worth keeping here for the
same reason.

**Required of every candidate**, and each is required because the review is
impossible without it:

| field | why the reviewer needs it |
|---|---|
| `title` | one line, imperative. It is what is ticked. |
| `rationale` | why this is worth doing. Without it a tick is a guess. |
| `repo` | which repository the work is in. A producer reading a findings document knows this; it is in the finding. |
| `evidence` | at least one entry, with the document path **and the sha it was read at**. A candidate that cannot be traced back to the finding it came from is an assertion. |
| `suggested_paths` | advisory, and the input to §3's path check. May be empty; empty is a claim that the finding named none, not that none exist. |
| `objective_ref` | an id from `objectives-2026-Q4.yaml`, or explicitly null. Null means "does not serve a stated objective", which is a thing worth being able to see in a list. |

**Not required, and deliberately:** `est_cost_gbp` and `est_diff_lines`. A
producer that guesses these badly makes the §6 credit ceiling wrong in a way
nobody would notice. Where they are absent the surface uses the contract's
`max_cost_gbp` as the estimate — which over-reserves, and over-reserving is the
safe direction.

### What a producer must NOT do

- **Not set `disposition`.** Every candidate arrives `PENDING`. A producer that
  could pre-approve would be the autonomy this design refuses.
- **Not write to `tasks`.** Only the approval surface creates tasks, and only
  from a ticked row. This is the invariant that makes the surface the single
  path.
- **Not deduplicate against previous batches.** A candidate that reappears is a
  signal (§5), and a producer that silently dropped repeats would erase it. The
  surface shows the repetition; the producer just emits what it found.

### The one thing a producer inherits from §5

`NOT_NOW` candidates are carried forward **by the surface, not by the
producer** — the surface copies them into the new batch retaining their original
`batch_id`. A producer therefore does not need to know what happened to
anything it emitted before, and should not look. Keeping that asymmetry is what
lets a producer stay a pure function of a findings document.

---

## 8. What this is not

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

## 9. What I am unsure about

Resolved 7 Sep 2026 and recorded above: option B and its path check (§3), the
read-only worktree (§3.1), the batch reason plus per-deviation rows (§4), the
three dispositions with `NOT_NOW` carried forward (§5), and the ceilings (§6).
What remains:

1. **Queue depth of 5, and now the approval batch cap of 5, are guesses** — in
   the way the settle lag and the level-3 cap are guesses. Both stay labelled as
   such until something measures them. §6.2 says which way to move the first one
   if it binds.
2. **Who writes the first producer, and by hand or not.** §7 says what one must
   emit; it does not say that turning the Metorik list into rows by hand with a
   SQL client is a perfectly good first producer. It probably is, and the
   interface exists so that the second one does not have to guess what the
   first assumed.
