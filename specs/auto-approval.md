# Auto-approval — ranking candidates and ticking them with nobody watching

**Status: APPROVED 9 Sep 2026, at pace 1. BUILT AND INSTALLED, RUNNING
`--dry-run`.** All six steps of §6 have landed; `fleet-autoapprove.timer` is
enabled for 01:30 with `--dry-run` in the unit, so the mechanism runs on
schedule, the brief reports what it *would* have done, and nothing is spent.
Taking the flag out is a separate, deliberate edit after several nights of
reading. §10 records what the first real dry run over the live pool did. Reads:
`console/approve.py`, `013_approval_surface.sql`,
`022_repeat_failure_stop.sql`, `010_decision_log.sql`, `console/decide.py`,
`console/automerge.py`, `contracts/candidate-producer.yaml`,
`contracts/checks/candidate_block_shape.py`, `brief/pass_.py`,
`specs/approval-surface.md` §4 §6 §7, `specs/unattended-operation.md` §5 §6 §7 §8.

`specs/unattended-operation.md` §5.2 promises this section — *"it applies to the
human surface today and to auto-approval in §6.1 tomorrow"* — and §6.1 turned
out to be auto-merge. Auto-approval was never written down. This is it.

**What changed when it was approved.** The design below is unchanged from the
version that was read and approved; the decisions that were open in §7 are now
settled and are marked where they sit. The pace is 1 (§2.4). Key 1 is labelled
a guess at the key itself and not only in §7 (§2.2). Cost does not rank and
`hib_signal` is displayed rather than ranked (§2.2). §8, §9 and §10 are new:
§8 is what removing this step does and does not do, §9 records three defects
found while tracing the chain that are deliberately **not** being fixed here,
and §10 is the first dry run over the live pool — including the five things it
established that this document had wrong or unsaid.

---

## 0. The scope sentence, and it is the same one auto-merge carries

Deadly Digital has no customers, HIB is not using it, and every change here is
reversible through git. The work is Metorik parity on analytics and the
constraint that matters is how many nights it takes.

**This is scoped to the parity push and it is reversed once there are
customers.** It is the same argument `console/automerge.py` makes for
`auto_merge: true` defaulting on, and it is written here as well because a
default is inherited by whoever reads the code next and they may read neither
spec. `specs/unattended-operation.md` §7 is the list of what goes back; **this
document adds itself to that list**: auto-approval off, ticking returns to the
console, and the `decided_via='unattended'` rows in `decision_log` stay as the
record of the period when it was on.

A bad auto-approval costs a draft spec — markdown on a local branch, £2, and a
night. It cannot cost a merge, because `draft_spec` is on
`automerge.NEVER_UNATTENDED` and no flag makes it eligible. That asymmetry is
what makes this cheap enough to do and it is the reason the rest of this
document can be as short as it is.

**Said once more, plainly, because a default outlives the argument for it.**
This is a temporary measure with a stated end condition, and the end condition
is the first customer — not a date, not a review, and not "when it stops being
useful", because it will not stop being useful. Whoever finds this running and
wonders whether it was designed this way: it was not. It was chosen for a
three-week window in which there is nobody to harm, every branch is local, and
the only scarce thing is nights. **If Deadly Digital has a customer and
`fleet-autoapprove.timer` is still enabled, that is the bug**, and §5's
correction 5 is the fix.

---

## 1. Six facts found by tracing the chain, and three of them change the shape

### 1.1 The ranking inputs asked for are not in the database

The request names four: the gap list's band, `hib_signal`, cost, and whether the
API half already exists and only the frontend is missing. Measured against the
twelve candidates open on 9 Sep 2026:

| input | where it is | rankable today |
|---|---|---|
| band | `candidates.evidence[].section`, as a free-text prefix — *"Daily — Order filtering: …"* | yes, by parsing a string nothing validates |
| `hib_signal` | **the producer's markdown block only.** No column. Batch 9 was loaded by hand and all four signals were dropped | **no** |
| cost | `est_cost_gbp` is NULL on every row, deliberately — `specs/approval-surface.md` §7 refuses to require it. Every draft-spec task reserves the same £2.00 | **no, and it should not** |
| API-half-exists | the `probes:` list in the block. **No column.** Dropped at load, same as `hib_signal` | **no** |

Two of the four never reach the database, and the one that does reaches it as a
string prefix. `contracts/checks/candidate_block_shape.py` requires
`hib_signal` on every candidate and re-executes every probe at HEAD — so the
producer is doing its half. The loss is at the load.

**This table describes 9 Sep 2026 before step 1 and is kept as the finding.**
Since 025 and `console/load_candidates.py`, band, `hib_signal` and `probes` are
columns and reach the database from the block. Cost is unchanged and still
should not rank (§2.2).

### 1.2 There is no loader

`candidate_batches.note` on batch 9 says it plainly: *"Loaded by hand: there is
no loader, and batch 8 was loaded the same way."* The producer writes markdown;
a person turns it into rows.

**So auto-approval alone does not make a feature build unattended.** The chain,
with the human steps marked:

    queue the producer task        HAND (no timer; the contract's writable_paths
                                        is one dated filename, so the next run
                                        needs a contract edit)
    runner runs it                 auto
    block -> candidate rows        HAND (no loader)
    tick                           HAND  <- this document
    runner runs the draft spec     auto
    read the draft spec            HAND (hard rule, §6.1: draft_spec never
                                         merges unattended, and that reading is
                                         the designed last gate)
    create the code task           HAND (approve_batch is the ONLY production
                                        path that inserts a task and it makes
                                        only draft-spec tasks; task 49 was a
                                        hand INSERT)
    build, merge, deploy           auto

Ticking is one of five. It is worth removing anyway — it is the one blocking
tonight — but the write-up should not claim it is the last. **§8 is that
accounting**, and it is where the chain above is restated with step 1 built:
the load is automated now, the tick is not yet, and the draft-spec read never
will be.

### 1.3 The pace is already decided, and depth-fill is four times it

`specs/unattended-operation.md` §8 costs three paces against the £158 pool and
chooses **one chain a night, £4.20**, rejecting two chains as *"exceeds the pool
on day 19"*. Approving up to the queue depth is four tonight (depth 5, one task
already queued): £8.00 of draft specs, and £16.80 if each one's code task
follows. That is the pace §8 rejected, twice over.

The ask — *"approved automatically up to the queue depth"* — and §8 cannot both
stand. §2.4 below builds the pace as a database function so it is one migration
either way, defaults it to §8's answer, and prints what a change costs.

### 1.4 Idle fires are not the problem

`systemd/fleet-runner.timer` says *"Nine fires for a queue that holds five"* and
sizes the window to clear a 13m40s worst case with four fires spare. A fire
against an empty queue exits 0 and costs nothing. What idles on an empty queue
is the **night**, not the fires — so the question this document has to answer is
"how many chains per night", not "how do we fill nine slots". Sizing to the
fires would be sizing to the wrong number.

### 1.5 Nothing deduplicates, and the person was the dedupe

`specs/approval-surface.md` §7 forbids the producer to deduplicate — *"a
candidate that reappears is a signal"* — and §5 has the surface show the
repetition to a reviewer who judges it. Remove the reviewer and nothing is left
that can see a duplicate. Two are open right now:

* **Candidate 17** *("CSV export of the order list", batch 8)* and **candidate
  23** *("CSV export of the order list, honouring the filters in force", batch
  9)* are the same feature, re-verified eleven days apart. Candidate 18
  *("Export with chosen columns")* is a subset of both. A rank on band and id
  approves 17 and 18 and leaves 23 — the best-verified of the three — behind,
  and pays for two overlapping specs.
* **Candidate 22** *("Let the dashboard comparison window be chosen")* is
  already in flight. Task 49 is QUEUED, its `fleet-spec` block declares exactly
  candidate 22's two suggested paths, and its title is *"Reach task 28's
  comparison windows from the overview"*. Nothing links them, because task 49
  was a hand INSERT and carries no candidate id.

Any ranking that does not refuse these is wrong on night one regardless of what
it ranks on. §2.3.

### 1.6 The repeat-failure ceiling is looser than it reads

`candidate_prior_failures(title, repo)` is exact-match on the title, and the
producer rewrites titles every run: 17 and 23 are the same work with different
titles, so each scores 0. It also counts `tasks.status = 'FAILED'`, and two of
this host's FAILED tasks produced accepted artefacts — **task 21**'s draft was
promoted (`abf4856 spec: net revenue after refunds — drafted by task 21,
reviewed`) and **task 34**'s block became batch 9. Both passed verification and
were recorded FAILED anyway.

So the ceiling under-counts real repeats and over-counts fake ones. It should
still be reused exactly as it is — it is the only thing between a wrong
candidate and an unbounded spend — but it must not be described as the thing
that catches the duplicates in §1.5. It catches neither of them.

**§9.2 carries this as a recorded finding with the verification results
measured**, along with §9.3, which is why the two miscounted rows have no
explanation attached to them.

> **Fixed 10 Sep 2026** — `027_repeat_failure_identity.sql` and
> `console/work_key.py`. The ceiling now counts unsuccessful attempts at the
> same **document row** rather than the same title, and does not count a FAILED
> task whose acceptance check passed. It still does not catch §1.5's
> duplicates — gates 2 and 3 do, and that sentence above stands. See §9.2.

---

## 2. What is proposed

### 2.1 The loader comes first, in the same piece of work — **BUILT**

The ranking asked for cannot be built on top of a hand-load. So:

**A loader (`console/load_candidates.py`) that reads the `fleet-candidates`
block and writes the batch and its rows in one transaction**, reusing the YAML
parse and the probe vocabulary already in
`contracts/checks/candidate_block_shape.py` rather than writing a second one.

**Three columns on `candidates`**, migration `025`:

    band       text  CHECK (band IN ('daily','weekly','monthly','rarely'))
                     -- NULL allowed and means the section named none
    hib_signal jsonb -- {value, as_of, source} verbatim, or NULL. NULL is a
                     -- claim that the gap list stated no figure, per the
                     -- producer contract, and never a lost value
    probes     jsonb NOT NULL DEFAULT '[]' -- the closed-vocabulary list, as
                     -- emitted, so it can be re-executed later

`band` is derived at load from the evidence section prefix and stored, rather
than parsed at approval time. Parsing a free-text string is a thing to do once,
in the place that can refuse the row, not every night in the ranker.

The producer needs no change. It already emits all three.

#### What shipped, and the four things building it established

`025_candidate_load.sql`, `025_candidate_load_assertions.sql` (nine assertions,
all passing), `console/load_candidates.py`, `tests/test_candidate_loader.py`
(twenty-four tests, all passing), and one exported constant — `PROBE_KINDS` in
`contracts/checks/candidate_block_shape.py`, so the loader can check the
vocabulary without holding a second copy of it that drifts.

Parsing batch 9's document with the finished loader returns **9 candidates, 32
probes, 4 hib_signals, 8 Daily and 1 Weekly** — which is the arithmetic §4's
brief line predicted, from the other side.

**1. The loader must not re-execute the probes, and this is the load/approve
split.** A block is read from a document verified at some sha and the tree has
moved since. A loader that refused an aged claim would refuse to record the
fact that the claim *had* aged — which is the fact worth keeping. Shape is
checked at load; truth is re-checked at approval, against the sha about to be
spent money on. `TestTheLoaderDoesNotReExecute` is the guard.

**2. An empty `probes` list is a gate case, not a data case.** The hand-loaded
rows (12–28) get `'[]'` from the column default, and *zero probes all holding*
is a check that cannot fail — this codebase's recurring defect, named in 024's
header. Two answers, deliberately in two places: the **loader refuses** a block
whose candidate declares no probes, and **`rank()`'s gate 4 treats an empty
list as ineligible** rather than as a pass. It is not a `CHECK (length > 0)` on
the column, because that would make the hand-loaded history unrepresentable and
this table is the record of it.

**3. The band discriminates almost nothing tonight.** Eight of batch 9's nine
rows are Daily and the ninth is Weekly. Key 2 separates exactly one candidate
from the other eight, so tonight the ordering is very nearly key 1 then key 3 —
which raises the weight on the key §7.1 already calls the most likely to be
wrong. It is an argument for `--dry-run` for several nights, not against the
key: a batch whose bands do spread is the batch the key exists for.

**4. The three columns do not reach batch 9's rows by loading — they have to be
filled.** The nine rows already exist, hand-loaded, so a fresh load would create
duplicates of them. `load_candidates.py --backfill-batch N` fills **only** band,
`hib_signal` and `probes`, on rows where all three are empty, and refuses unless
every title in the document matches exactly one row and every row is matched.
All nine of batch 9's titles match the block exactly, so the repair is verified
rather than hoped for.

This is **not** the reconcile `contracts/candidate-producer.yaml` forbids. That
rule is about *content* — "a candidate that reappears is signal, and quietly
refreshing it erases that" — and it is why a changed claim must arrive as a new
batch. These three fields never arrived at all. Filling them completes a load
that a missing column interrupted; it does not refresh a candidate, and the
backfill refuses to overwrite any value that is already there.

### 2.2 The ranking

A pure function, `console/rank.py`:

    RANK_VERSION = 1
    def rank(candidate, platform_head) -> tuple   # lower sorts first

Four eligibility gates first. **A gate is not a rank**: a candidate that fails
one is not rejected and not marked — it is simply not approved by the machine,
stays `PENDING`, and appears in the morning brief with the rule that held it.
This is the shape §5.2 already chose for the repeat stop: withhold the automatic
approval, never the candidate.

1. **`PENDING` only, never `NOT_NOW`.** §5 has the surface carry `NOT_NOW`
   forward so a person can see it again. A `NOT_NOW` is the only record of a
   human judgement about one specific candidate, and a machine that can overrule
   it leaves no veto short of editing code. This is also the cheapest correction
   in §5 — one click, no deploy.
2. **The newest batch only.** This is the dedupe of §1.5's first case, and it is
   one `WHERE`. Batch 9 re-verified batch 8's rows against a newer platform sha;
   the older row is superseded by construction. Rows left behind from an older
   batch are exactly the repetition §5 wants a person to look at.
3. **No overlap with a task that is not terminal.** §1.5's second case. Compare
   `suggested_paths` against the `writable_paths` declared in the `fleet-spec`
   block of every QUEUED / CLAIMED / RUNNING / READY_FOR_REVIEW task, falling
   back to the task's contract paths when the block will not parse — and record
   which of the two matched, because the contract paths are deliberately wide
   (task 49's contract claims the whole analytics frontend) and a fallback match
   is a much weaker statement than a spec match.
4. **The probes still hold at the current platform HEAD.** Re-execute the stored
   `probes` with `candidate_block_shape.run_probe` at approval time. The producer
   re-verified at `4619a76`; HEAD is `6fd8ddd` and moves nightly. This is the
   single most valuable gate here and it is the cheapest: the code exists, it is
   pure pathlib and `re`, and it is the whole reason the producer is a task
   rather than a parser. A claim that has stopped being true does not get built.

   **An empty `probes` list fails this gate rather than passing it vacuously.**
   Every hand-loaded row carries `'[]'`, and "all zero of its probes held" is a
   check that cannot fail — 024's header names that as the recurring defect
   here. A row with no probes is not eligible for unattended approval, stays
   `PENDING`, and appears in the brief with that as the rule that held it. It is
   also, separately, the reason key 1 cannot rank such a row: key 1 is *read off
   the probes*, so a row without them has no discriminator, and §2.3 refuses to
   approve on the absence of one.

Plus the two ceilings already in `approve_batch`: the repeat-failure stop and
the credit check.

Then the sort, in order:

**Key 1 — modify before create, read off the probes. THIS KEY IS A GUESS, and
the label belongs here rather than only in §7.1**, because §7 is the section a
reader skips. It rests on five runs whose outcomes are confounded — the three
that failed are also the three largest — and it is the key most likely to be
wrong. It is first anyway, on the evidence below and because the alternative
first key is an estimate nobody has tested; but it is first *as a hypothesis
being run*, and `RANK_VERSION` on every decision is what makes reversing it
cost one line rather than an archaeology. See the end of this key, and §7.1.

A candidate whose probes
assert that something **already exists** — a `path_exists`, or a `grep_count`
with `expected >= 1` — is a change to code that is there. A candidate whose
probes only assert absence (`path_absent`, `expected: 0`) is a new report with
nothing behind it. The first sorts before the second.

**The frontend-only gap is the strongest case of this and sorts at the top of
it**: presence under `api/**` together with absence under `platform/**` means the
value is computed, returned, and dropped one layer from a person. Three of the
nine in batch 9 are exactly that, and the producer's own document is what found
it — *"the API gained the capability and the Next.js layer did not carry it to a
person"*.

Why this key first, and why not `suggested_paths`: I ran the obvious version —
resolve `suggested_paths` against the tree and prefer the ones that all exist —
over the twelve open candidates. **All twelve came back MODIFY.** The producer
names directories and engines to read, not the file the work would create, so
the paths discriminate nothing. The probes do, because they were written to
assert absence.

And it earns first place empirically. Of batch 8's five approved candidates,
four spec tasks are recorded FAILED, and **three failed on the same check for
the same reason** — `draft_spec_shape.py` refusing prose paths that resolve
nowhere:

    task 23  api/analytics/routes/coupons.py, api/analytics/services/coupon_report.py
    task 24  api/analytics/services/category_report.py, routes/categories.py
    task 25  routes/orders.py, routes/payments.py

Every one is a plausible filename for a report that does not exist. Those three
candidates were a coupon report, a product-by-category report and a
payment-method report — three new pages with nothing behind them. The two whose
specs passed the path check were "net refunds from the headline figures" and
"compare any period to any other": both changes to figures an existing engine
already computed, both written against files the agent could read. The agent
invented a filename exactly when the candidate gave it nothing to read.

**Stated as the guess it is:** that is five runs, not a study, and the split is
confounded — the three that failed are also the three largest. It is labelled
in §7 with the queue depth and the settle lag.

**Key 2 — the band.** Daily before Weekly before Monthly before Rarely; a NULL
band sorts last and does not gate. Second and not first because it is one
person's estimate of agency use, the gap list says so, and the producer's own
document says so again: *"No agency was asked, no usage was measured, and the
agency-partner deal is not signed."* A measurement outranks an estimate.

**Key 3 — the candidate id, ascending.** Oldest first. Deterministic, so the
same inputs give the same batch, so a dry run means something.

**What does not rank, and why it is written down rather than left out:**

* **Cost does not rank.** Every draft-spec task reserves `max_cost_gbp` = £2.00
  from `contracts/draft-spec.yaml`, `est_cost_gbp` is NULL on every row, and §7
  refuses to require it because *"a producer that guesses these badly makes the
  §6 credit ceiling wrong in a way nobody would notice"*. Cost is a **ceiling**
  here — the credit check, the per-task cap, and §2.4's pace — and a ceiling is
  not a rank. Ranking on a number that is the same for every row is a way of
  looking like a decision was made.
* **`hib_signal` does not rank. It is displayed.** Its `value` is free text —
  *"payment_method populated on 2,782,530 of 2,844,177 orders"*,
  *"refund_total non-zero on 1 of 2,844,177 orders"* — and the two say opposite
  things about whether the work is worth doing. The second is the net-revenue
  candidate, and it is an argument **against** it: a net figure over refunds
  that were never captured is a confident wrong number, which is worse than no
  figure. No sort key extracts that from a sentence, and a ranker that scored
  "has a signal" as a positive would rank net revenue **up** on the strength of
  the fact that argues it down.

  So the signal is carried into the decision record and printed verbatim in the
  brief beside every approved row, where the reader who can judge it sees it.
  **What would make it rank:** a numerator and a denominator in the block —
  `{metric, populated, total, as_of}` — which is a producer-contract change and
  a shape-check change, and is the right second version. Not this one.

### 2.3 The reason, and the refusal to invent one

`decision_log.reason` is `NOT NULL` on every row and §4 is explicit that ten
paraphrases of "yes" satisfy the constraint while emptying the column. An
approval nobody made is exactly where that failure arrives by a new route.

So: **the ranker generates the reason from the discriminator that actually
separated the top row from the one below it, and if there is no discriminator it
approves nothing.**

    Approved 1 of 12 open candidates (rank_v1). Candidate 20 is the highest of
    the three whose probes show the API already returns the value and the
    frontend drops it: api/analytics/routes/orders.py declares payment_method
    and has_discount, platform/app/api/analytics/orders/route.ts forwards
    neither. The other two, 21 and 22, were held — both name
    platform/app/(dashboard)/analytics/page.tsx, which queued task 49 declares.
    The seven below the line create report routes that do not exist, which is
    what spec tasks 23, 24 and 25 failed on.

A night where the top two are indistinguishable on every key produces no
approval and a brief line saying why. That is the right answer: "it was first"
is not a reason, and a system that will not say why it chose is the one thing
§4 was written to prevent.

### 2.4 The pace — **DECIDED: 1**

    --: The most candidates auto-approval may tick in one night. NOT the queue
    --: depth: specs/unattended-operation.md §8 costs three paces against the
    --: £158 pool and chooses one chain a night. Depth-fill is four.
    CREATE FUNCTION fleet_autoapprove_per_night() RETURNS int
    LANGUAGE sql IMMUTABLE AS $$ SELECT 1 $$;

In the database with the other ceilings, on the same precedent — *"a cap that
can be raised without a migration will be raised on the morning something needs
longer"*. The effective number is
`min(per_night, max_approval_batch, max_queued - queued_now)`, so the existing
ceilings still bind above it.

Tonight, at each setting, against £139.09 remaining:

| per_night | specs/night | with code tasks | nights of pool |
|---|---|---|---|
| **1 — `specs/unattended-operation.md` §8's answer, and the one in force** | £2.00 | £4.20 | 33 |
| 2 | £4.00 | £8.40 | 16 |
| 4 (depth-fill tonight) | £8.00 | £16.80 | 8 |

**The other two rows stay in the table on purpose.** 1 was chosen; 2 and 4 are
what it was chosen *over*, and a cap whose alternatives are not written down
next to it reads as the only number anyone considered. Raising it is a
migration — one line, one commit — and this table is the argument that has to
be answered to justify one, not a menu.

**And §5.1's 60% pool stop does not exist.** The spec sets it — *"At 60% the
fleet stops queuing and the brief says why, leaving £63 for work a person
chooses"* — and `approve.py` checks `wanted > remaining_gbp`, which is the 100%
ceiling. It was specified for exactly this: a ceiling consulted when nobody is
reading. Build it as `fleet_month_credit()` gaining an `autonomous_remaining`
(`pool * 0.6 - committed`) that **only the unattended path** reserves against;
a person keeps the 100% ceiling, which is what "leaving £63 for work a person
chooses" means.

### 2.5 Reusing `approve_batch`

`console/autoapprove.py` selects, gates, ranks, and calls `approve.approve_batch`
with the ranked ids. It adds no ceiling of its own and bypasses none. The
repeat-failure stop, the batch cap, the queue-depth check, the credit check and
the one-transaction ordering are already there and were put there on the
grounds that auto-approval would meet them.

Three changes inside `approve.py`, all small:

1. **`decided_via` and `mechanics` parameters**, defaulting to `console` and
   `None`, so every existing caller is unchanged. §3.
2. **`repeat_overrides` stays refused for the unattended path.** An override is
   a person saying "it is different this time"; there is no such sentence when
   nobody is there. Pass none and let the stop refuse.
3. **`base_branch` is hard-coded to `'track-2-foundation'`** — **FIXED, ahead of
   everything else, and it needed a second half this section did not
   anticipate.** Reading the trunk from `contracts/draft-spec.yaml` was the
   proposed fix, and on its own it would have changed nothing: **the contract
   said `track-2-foundation` too**, having copied the line from
   `contracts/research.yaml`, which was written before the 9 Sep consolidation.
   The literal and the contract were both stale and agreed with each other,
   which is why nothing looked wrong. The fix is both halves — `approve.py`
   reads the key, and the key now says `master` — plus a test asserting the
   queued task's base branch equals whatever the contract calls the trunk,
   rather than equalling the string `master`, so moving the trunk again is one
   edit in one place.

   Note for whoever moves it next: `contracts/research.yaml` and
   `contracts/research-metorik-gap.yaml` still carry `track-2-foundation` and
   the same pre-consolidation comment. They are outside the approval path and
   were left alone deliberately rather than swept up in a fix to this one; the
   local refs are the same commit today, so they are latent in exactly the way
   this was.

   The original argument, unchanged and still the reason it was worth doing
   first: `contracts/candidate-producer.yaml` records that the trunk became
   `master` on 9 Sep 2026 when track-2-foundation was consolidated into it.
   They are the same commit today (`ce90c57`), so nothing is broken yet — but a
   task's base branch is immutable once the row exists, so the morning master
   moves and this literal does not, **every task `approve_batch` queues** —
   console-ticked as much as auto-approved — branches from a stale base, and
   the only repair is abandoning it. Read the trunk from the contract, as
   `_draft_spec_contract()` already reads the cost and the timeout, and for the
   same reason it was changed to.

   It is `git rev-parse <base_branch>` in `runner/worktree.py` that resolves
   this, so it is the **local** ref that matters and the bug is genuinely
   latent rather than already biting. Worth knowing because
   `origin/track-2-foundation` has *already* diverged — it sits at `4041d15`
   while `origin/master` is at `ce90c57` — so the two refs look equal only from
   where the runner stands.

### 2.6 The unit

`run_autoapprove.py` and `fleet-autoapprove.timer`, at **01:30** — before the
runner window opens at 02:00, so the night's work is queued when the first fire
lands.

A **separate unit from the runner**, for the reason `run_automerge.py` gives:
*"so it can be stopped on its own — which is what you want at 3am on a bad
night, and not something you want to have to think about."*

`--dry-run` ranks everything, approves nothing, and prints the order with every
key value and every gate that fired. Same argument as automerge's: *"the honest
way to watch this for a few nights before letting it write, and it is what the
first nights should use."*

---

## 3. What an auto-approval records — **BUILT** (026, `console/autoapprove.py`)

An approval is not a run step, so `decide.py`'s `decided_via` cannot carry it —
that column lives in `run_steps.payload` and belongs to a task verdict. The
vocabulary is right; the location is not.

**`decision_log` gains two columns**, migration `026` — renumbered from `025`,
which step 1 spent on the loader's three columns. Everything else in this
section is approved as written and is not built.

    decided_via text NOT NULL DEFAULT 'console'
                CHECK (decided_via IN ('console','by_hand','unattended'))
    mechanics   jsonb   -- what the decision rested on. NULL for console rows.

    CONSTRAINT decision_log_unattended_shows_its_work_ck
        CHECK (decided_via <> 'unattended'
               OR (mechanics IS NOT NULL AND mechanics <> '{}'::jsonb))

The constraint is `decide.py`'s rule moved to the other table and it is the same
sentence: *"an unattended decision must carry its gates. A merge nobody watched,
with no record of what was checked, is unreviewable afterwards."* Same word
too — `unattended`, not `auto`: **a reader who sees "auto" asks which
automation; a reader who sees "unattended" knows what to check.**

An unattended approval writes:

| field | value |
|---|---|
| `decision` | `APPROVED`. 001's vocabulary, fourteen readers know it, and provenance belongs in `decided_via`. A fourth status would be the `MERGED_OUTSIDE` mistake again |
| `decided_by` | the login that ran it — **never a person's name.** The console route defaults `decided_by` to `"eamonn"`; the unattended path must not inherit that, because a log that reads as a person's decision is the one thing this record exists to prevent |
| `decided_via` | `unattended` |
| `reason` | §2.3 — generated from the discriminator, and the run refuses rather than writing filler |
| `evidence` | unchanged: `[{kind: candidate, id: …}]` per approved row, the snapshot §4 already specifies |
| `mechanics` | `rank_version`; the platform sha the probes were re-executed at and each probe's result; the full ordered list with every key value; the cut line; for every row below it the exact rule that held it; the credit reading (`pool`, `committed`, `remaining`, `read_at`, `source`) and the pace in force |
| `origin` / `confidence` | `RECORDED` / `STATED`. It was recorded live and it states what it did. `INFERRED` is for a decision written up from memory, which this is the opposite of |

`candidates.approval_decision_id` already ties each row to it, so the
existing `candidates_approved_cites_decision_ck` does the rest.

**What is not recorded, deliberately:** no per-item reason. §4 allows one where a
person deviates from the ranking, and the machine cannot deviate from it — the
ranking is what it did. A human override typed into the console still writes
one, unchanged.

---

## 4. What the morning brief shows — **BUILT** (`brief/pass_.py`, `brief/render.py`)

`brief/pass_.py` builds `overnight.runs` from `runs` completed since the last
brief. An approval produces no run, so today it would be invisible; a night
where auto-approval queued four wrong specs and the runner then ran them reads
as four ordinary failures with no clue where they came from.

**A new claim group, `overnight.approvals`, rendered before the runs**, because
the approval is what caused them. `dd_detector_login` can already read
`candidates` and `decision_log`; no grant is needed.

    approvals: 1 of 12 open candidates auto-approved (rank_v1) — GBP 2.00
    reserved, GBP 139.09 remains (33 nights at this rate; the 60% stop is at
    GBP 94.80 committed, GBP 18.91 now)

      approved  c20 -> task 51  frontend-only, daily
                "Forward the four order filters the API already accepts …"
                hib_signal: payment_method populated on 2,782,530 of
                2,844,177 orders (tenant 2, as of 2026-08-28, specs/metorik-gap.md)

      below the line, highest first
        c21  HELD  names platform/app/(dashboard)/analytics/page.tsx, which
                   queued task 49 declares
        c22  HELD  same file, same task
        c23  next  new-route class, daily — would be first tomorrow

      probes re-executed at platform 6fd8ddd: 18 of 18 held
        (across the 5 of 12 candidates that reached gate 4 — the gates
         short-circuit, so a row held for overlapping a live task never has
         its probes rerun. This example said "32 of 32" before the code
         existed, which would have been the whole pool; §10.1 has the
         correction.)

Four properties, each there for a reason:

1. **The reserved spend against the pool and the 60% stop**, in the same shape
   the runs section already uses — *"a number that only becomes alarming on the
   last day is not a control"*.
2. **`hib_signal` verbatim.** §2.2 said the ranker cannot read it. This is where
   it goes instead: in front of the one reader who can, on the morning the work
   has not been built yet. *"refund_total non-zero on 1 of 2,844,177 orders"*
   under an approved net-revenue candidate is a line that stops a wrong number
   before it ships, and it is worth the space.
3. **The line below the line.** A ranking is wrong in what it *passed over*, and
   a list of what it took cannot show that. Printing the top held row and the
   exact rule that held it is what makes a bad ranking visible in one read
   rather than in a query.
4. **The probe re-execution count**, because a night where a gate silently
   stopped running reads identically to a night where everything held.

**And the undo, copy-paste**, on the same argument as the revert line: *"the
command to do that should be copy-paste rather than a lookup at the moment
somebody is annoyed."*

    undo: ./fleet candidates undo 47   # decision 47: abandons the unclaimed
                                       # spec task(s) and returns the
                                       # candidate(s) to PENDING

**Stated rather than discovered: the brief is a review, not a gate.** It renders
at 07:45 and the window closes at 04:40, so by the time it is read the specs are
written. Nothing in it stops a bad batch. What stops one is §5.

---

## 5. What stops it, and the cheapest correction

**The blast radius, stated as a number.** Auto-approval creates draft-spec tasks
and nothing else. `draft_spec` is on `NEVER_UNATTENDED`, so the output is
markdown on a local branch that no auto-merge will touch. A wrong ranking every
night for a week costs £14 at the proposed pace, £56 at depth-fill, and lands
nothing in either repository.

**It cannot run away.** Twelve candidates are open, there is no producer timer
and no loader, so the pool is finite and unfed: at depth-fill it is exhausted in
three nights and then the unit approves nothing. The failure mode is a drain,
not a loop. The one thing that could make it a loop is a producer on a timer
feeding a ranker that keeps choosing the same wrong class — and that is what the
repeat-failure stop is for, with §1.6's caveat that it will not catch a rewritten
title.

**The corrections, cheapest first.**

1. **`--dry-run`, before it writes at all.** Costs nothing, runs in a second,
   and prints tonight's order over today's twelve candidates. The first nights
   should use it, as automerge's did. This is the only check that happens before
   money.
2. **Mark it `NOT_NOW` in the console.** The ranker considers `PENDING` only, so
   `NOT_NOW` is a permanent veto on one candidate. One click, no deploy, no
   migration, and it uses a disposition that already exists and already means
   this.
3. **Change the key order.** `rank()` is one pure function returning a tuple.
   Reordering the keys is one line, and `RANK_VERSION` is recorded on every
   decision, so last week's batches stay attributable to the ranking that made
   them instead of being silently re-explained by this week's.
4. **Undo one night.** `./fleet candidates undo <decision_id>` — abandon the
   unclaimed spec tasks, return the candidates to `PENDING`, leave the
   `decision_log` row in place with a follow-up row saying why. Complete before
   the task is claimed; after that it costs the £2 and the branch.

   **BUILT, and it had to be** (`console/undo.py`). §4 prints this command in
   the brief, and no such subcommand existed when that was written — a
   copy-paste undo that is not a real command is worse than no line at all,
   because it reads as a safety net right up until somebody needs it. Past the
   claim it refuses and says which task stopped it, rather than reporting a
   clean undo over a task that is already running.
5. **Stop it.** `systemctl disable --now fleet-autoapprove.timer`. A separate
   unit, so this does not touch the runner, the merge or the deploy.

**What would make the ranking wrong in a way none of these catches:** the band
is an estimate nobody has tested, and every candidate in the pool inherits it.
`research/candidates-metorik-gap-2026-09-09.md` says it in its own
`unasked_question`: *"one conversation with the prospective partner would be
worth more than the whole re-verification above."* Auto-approval ranks a list
whose ordering nobody has validated against a user. It makes the fleet faster at
building what the gap list guessed. That is a fair trade for three weeks with no
customers and it is not a trade that survives the first one — which is the same
sentence as §0, arriving from the other end.

---

## 6. Build order

Each step runs `--dry-run` for a night before the next lands.

**All six are done.** What each landed as:

| step | landed as |
|---|---|
| 0 | `console/approve.py`, `contracts/draft-spec.yaml` |
| 1 | `025_candidate_load.sql` (+assertions), `console/load_candidates.py` |
| 2 | `026_unattended_approval.sql` (+assertions) — pace, 60% stop, `decided_via`, `mechanics` |
| 3 | `console/rank.py` |
| 4 | `console/autoapprove.py`, `approve_batch`'s two parameters |
| 5 | `brief/pass_.py` `_approval_claims`, `brief/render.py` ordering, `console/undo.py`, `fleet candidates undo` |
| 6 | `run_autoapprove.py`, `systemd/fleet-autoapprove.{service,timer}` at 01:30, `--dry-run` |

0. **DONE, ahead of everything: the `base_branch` literal** (§2.5.3).
   Independent of auto-approval, latent rather than broken, and one line — so
   it went first rather than riding in on step 4 where a rollback of the
   feature would take the repair with it.
1. **DONE: the loader and the three columns** (§2.1). Without it the ranking
   has two of its four inputs and one of those is a string parse. Migration
   `025`, `console/load_candidates.py`, and the tests for both.
2. **`decision_log.decided_via` and `mechanics`** (§3), migration `026`, and
   the 60% stop (§2.4). The record before the thing that writes it, on
   `specs/unattended-operation.md` §9's principle that the brief was built
   before autonomy because it is how autonomy is watched.
3. **`rank()` and `--dry-run`** (§2.2). Run it against the open pool and read the
   order before anything writes.
4. **`autoapprove.sweep()` and the `approve_batch` parameters** (§2.5).
5. **The brief section** (§4).
6. **The timer** (§2.6), at pace 1.

**The unit installs with `--dry-run` first, as auto-merge did.** Step 6 lands
`fleet-autoapprove.timer` with `--dry-run` in the unit's `ExecStart`, and
removing that flag is a separate, deliberate edit made after several nights of
reading what it would have done. That is auto-merge's own sequence and its
argument: *"the honest way to watch this for a few nights before letting it
write, and it is what the first nights should use."* A dry-run night costs
nothing and produces the one artefact that matters here — the ranked order over
a real pool, which is the only way to find out that key 1 is wrong before it
has spent anything.

---

## 7. What I am unsure about

1. **Key 1 rests on five runs and they are confounded.** The three spec tasks
   that failed on invented paths were the three new-report candidates; the two
   that passed were changes to figures an engine already computed. The three
   that failed were also the three largest, so size and class move together and
   nothing here separates them. It is a guess in the way the queue depth and the
   settle lag are guesses, and it is the key most likely to be wrong.
2. **The overlap gate may be too blunt.** It compares against spec-declared
   paths where it can and contract paths where it cannot, and the contract paths
   are wide enough that one open frontend task could hold every frontend
   candidate. The `mechanics` record says which rule matched, so a week of
   nights answers this rather than an argument now.
3. **Whether the pace should be 1 or 2.** §8 chose 1 and costed it. The queue
   drains a draft spec in four to five minutes and the window has nine fires, so
   the machine is not the constraint — the pool is. Left at 1, changeable in one
   migration, with §2.4's table as the argument.
4. **Whether the band prefix is stable.** `candidate_block_shape.py` does not
   require the evidence section to start with a band, so the loader's derivation
   is a convention the producer happens to follow in batches 8 and 9. If it
   should be guaranteed, it belongs in the shape check, which is a producer
   contract change and is not in this document.

**Settled since this list was written:** 3 is decided — the pace is 1, and
§2.4's table keeps 2 and 4 next to it as what it was chosen over. 1, 2 and 4
remain open, and 4 gained an answer of sorts at the load: the loader now
refuses an unrecognised band word rather than storing NULL for it, so the
convention breaking is an error instead of a silently unranked batch. That
narrows the risk; it does not close the question, which is still whether the
shape check should require the prefix.

**And 1 and 2 got worse, not better, once the code ran.** §10.1: the band
separates one row from eight on this pool, so key 1 carries more of the order
than §2.2 assumed — which raises the cost of 1 being wrong. And 2 has an
instance now: c26 and c28 are held because they name a *directory* that queued
task 49 writes one file inside, so one open frontend task holds four
candidates. Both are why the unit ships with `--dry-run` rather than despite it.

---

## 8. This removes one of five human steps, and it is not the last one

§1.2 traced the chain and found **five** hand steps between a findings document
and a merged feature. This document removes one of them. It is worth being
exact about which, because "the fleet builds features unattended" is the
sentence this could be misread as supporting, and it would be false.

    queue the producer task     HAND   no timer, and the contract's
                                       writable_paths is one dated filename
    runner runs it              auto
    block -> candidate rows     HAND   -> REMOVED, step 1, built
    tick                        HAND   -> removed by this document, NOT BUILT
                                          (steps 2-6)
    runner runs the draft spec  auto
    read the draft spec         HAND   NEVER REMOVED, by design
    create the code task        HAND   approve_batch only makes draft-spec
                                       tasks; task 49 was a hand INSERT
    build, merge, deploy        auto

**What is true tonight:** the *load* is automated and the *tick* is not. Step 1
is built and steps 2 through 6 are specified. When they land, two of the five
are gone, three remain, and one of those three is permanent.

### 8.1 Which of the remaining three I would do next, and what each costs

**Next: the producer timer.** It is the only one of the three that is both
removable and cheap, and it is the one that makes the loader worth having —
a loader with no producer feeding it automates a step that happens once a week
by hand.

The blocker is not the timer, which is a one-line unit. It is that
`contracts/candidate-producer.yaml` declares `writable_paths` as a single dated
filename — `research/candidates-metorik-gap-2026-09-09.md` — so **the next run
needs a contract edit**, and a timer firing against an unedited contract
produces a task that cannot write its output. The work is a dated *pattern*
(`research/candidates-metorik-gap-*.md`) plus the shape check learning to
resolve the day's filename, plus the unit.

Cost: **£5.00 per run** (`max_cost_gbp` in the producer contract), a 3600s
timeout, and roughly a half-night of building. Cadence is the real decision and
it is not nightly: batch 9 re-verified batch 8 eleven days later and the pool
is still not drained. Weekly is the honest starting number, which is £5/week
against a £158 pool.

**The one I would not do: the code task after a draft spec.** It is the biggest
remaining lever and it is the one place where the asymmetry in §0 stops
holding. Every step automated so far produces *markdown on a local branch that
no auto-merge will touch* — `draft_spec`, `research` and `candidate_producer`
are all on `automerge.NEVER_UNATTENDED`. A code task is not: it is a work type
that **can** merge unattended, and automating its creation would join a chain
that starts at an unread findings document to one that ends at a deploy, with
`draft_spec`'s human read as the only thing in between. Doing this before the
producer timer would also mean automating the expensive end of the chain before
the cheap one. Cost if it were built: a route from an accepted draft spec to a
task INSERT, which is small; the real cost is that §5's blast-radius argument —
"a wrong ranking every night for a week costs £14 and lands nothing in either
repository" — stops being true, and every correction in §5 would need
rewriting against a different worst case.

**The one that is not work: reading the draft spec.** `draft_spec` is on
`NEVER_UNATTENDED` and no flag makes it eligible; §1.2 calls that read "the
designed last gate". Cost of removing it: not costed, because it is not a
backlog item. It is the thing the rest of this is safe *because of*. If it is
ever removed, every argument in §0 and §5 needs rewriting first, and this
sentence is here so that whoever proposes it has to notice that.

---

## 9. Three findings recorded here and deliberately not fixed

Found while tracing the chain for §1. None is caused by this document, each
would be a separate change with its own argument, and each is written down here
because the alternative is finding it again in three weeks.

### 9.1 §5.1's 60% pool stop does not exist

`specs/unattended-operation.md` §5.1 sets it — *"At 60% the fleet stops queuing
and the brief says why, leaving £63 for work a person chooses"* — and
`console/approve.py` checks `wanted > remaining_gbp`, which is the **100%**
ceiling. There is no 60% stop anywhere.

It was specified for exactly the situation this document creates: a ceiling
consulted when nobody is reading. §2.4 carries the build — `fleet_month_credit()`
gaining an `autonomous_remaining` of `pool * 0.6 - committed`, reserved against
by **the unattended path only**, so a person keeps the 100% ceiling, which is
what "leaving £63 for work a person chooses" means. It is step 2 of §6 and it
should land before the timer does, not after.

### 9.2 The repeat-failure ceiling is looser than it reads, and miscounts in both directions — **FIXED 10 Sep 2026** (`027`, `console/work_key.py`)

> **What was built.** The finding below stands as written; this is what
> answered it, after the first live dry run proved it on the real pool.
>
> **The identity.** `candidates.work_key`, derived at load by
> `console/work_key.py` from `evidence[].document`, `evidence[].sha` and
> `evidence[].section` — the row of the findings document the candidate IS.
> The heading is not compared to another heading: it is **resolved against the
> document at the sha the candidate cites**, so batch 8's *"Weekly — coupon and
> discount performance"* and batch 9's verbatim cell land on one row. All five
> repeat pairs in the pool collapse; 16 of the 17 rows resolve, and c25 (whose
> heading elides a parenthetical the document carries) falls back to its
> heading. A NULL key falls back to 022's `(title, repo)`, so this is never
> weaker than what it replaced.
>
> **The outcome rule, frozen.** An *unsuccessful attempt* is a task in a
> terminal `FAILED` state **whose acceptance verification did not record
> `PASS`**. Tasks 21, 34 and 49 are FAILED with a passing check and do not
> count; 23, 24 and 25 failed their check and do. A FAILED task that never
> reached verification counts — it produced nothing, and treating silence as a
> pass would let a task that died before it was checked buy the next one.
>
> **The threshold is unchanged at 2**, and so are the band, the path-overlap
> rule, `per_night`, the pool ceilings and the ranking keys.
>
> **And the dry run now evaluates it.** The stop lived only inside
> `approve_batch()`, which `sweep(dry_run=True)` never calls — which is why the
> first dry run could not show that the ceiling was broken and it had to be
> found by hand against production. `plan()` reads the same
> `candidate_prior_failures(id)` the approval enforces with, gate 4 in
> `console/rank.py` holds the row, and `approve.py` still refuses inside the
> transaction as the backstop.
>
> **Corrected counts on the live pool** (dry run, 10 Sep 2026): c28 = **1**,
> where it read 0. Nothing reaches 2 yet, so nothing is held by this rule
> tonight — which is the honest outcome and not the same as the rule being
> untested; `tests/test_repeat_failure.py` and
> `tools/mutation-repeat-failure.sh` are what test it.
>
> **What is NOT fixed:** §9.3. A task that fails after passing verification
> still writes no reason to the database. This migration reads round that
> silence; it does not end it.

`candidate_prior_failures(title, repo)` is **exact-match on the title**, and the
producer rewrites titles every run. Candidates 17 and 23 are the same CSV export
eleven days apart under different titles, so each scores 0 — the ceiling does
not see the repeat it exists to catch.

**Measured on the live pool, 9 Sep 2026, and it is worse than "does not see it":**

    c14  "Coupon and discount performance report"            prior_failures = 1
         (batch 8, APPROVED, produced task 23, which FAILED)
    c28  "Coupon and discount performance report, over a
          column that is already populated"                  prior_failures = 0
         (batch 9 — the same work, re-verified, retitled)

Every one of batch 9's nine candidates scores 0. The stop fires at 2, and **the
counter can never reach 2**, because each producer run supplies a fresh title
that starts again from nothing. It is not a ceiling that is set too high; it is
a ceiling on a quantity that is reset before it can accumulate. c28 is held
tonight by gate 3 — it names a path queued task 49 declares — and when task 49
merges, nothing here will stop it being approved and buying task 23's failure a
second time.

The fix is a stable identity for "the same candidate", which the producer
contract deliberately does not provide (*"a candidate that reappears is a
signal"* — §7 forbids deduplication). That is a producer-contract change with
its own argument and it is not made here.

It also counts `tasks.status = 'FAILED'`, and two of this host's five FAILED
tasks produced accepted artefacts: **task 21**'s draft was promoted (`abf4856
spec: net revenue after refunds — drafted by task 21, reviewed`) and **task
34**'s block became batch 9.

**Checked against the database rather than inferred**, because "passed
verification and was recorded FAILED" is the kind of claim that is usually a
misreading. Each task's last `VERIFICATION_RUN` step:

| task | checks | `result` | task status |
|---|---|---|---|
| 21 | `draft_spec_shape.py` exit 0 | `PASS` | FAILED |
| 34 | `research_document_shape.py` exit 0, `candidate_block_shape.py` exit 0 | `PASS` | FAILED |
| 23, 24, 25 | `draft_spec_shape.py` exit 1 | `FAIL` | FAILED |

So three of the five are honest failures and two are not, and the ceiling
under-counts real repeats and over-counts fake ones at the same time.

**It should still be reused exactly as it is** — it is the only thing between a
wrong candidate and an unbounded spend, and §2.5 passes no `repeat_overrides`
on the unattended path. What must not happen is describing it as the thing that
catches §1.5's duplicates. It catches neither. Gates 2 and 3 do.

### 9.3 A task that fails after verification writes no reason to the database

Which is *why* 21 and 34 are unexplained. A task that fails a check records what
the check said; a task that fails after passing verification records nothing,
so the row reads FAILED with no account of what happened — and the two rows
that produced accepted artefacts are exactly the two in that state.

**Where the reason is not:** `tasks` has no failure column at all, and
`runs.final_outcome` is **NULL on all five** of the FAILED runs, including the
three that genuinely failed their check. The only account of any of them is the
`VERIFICATION_RUN` payload, which is why 23, 24 and 25 are explicable at all —
their check exited 1 and said so. For 21 and 34 the last thing written is
`result: PASS`, and then the run is FAILED with nothing in between. The
database records the verdict of the check and not the fate of the task, and
those are the same thing only when the check is what killed it.

This is the reason 9.2's over-count is invisible rather than merely wrong: a
person reading `tasks` cannot tell a task that failed from one that succeeded
and was recorded badly, and neither can `candidate_prior_failures`. Fixing it
is a change to the runner's terminal-state handling, not to anything here.

---


---

### 9.4 The producer flattened `objective_ref`, and it carries the top ranking rule — **FIXED 10 Sep 2026** (shape check, loader)

Batch 9 emitted `objective_ref: dd-feature-parity` on **all nine** candidates,
with no justification anywhere in the block. Two of those nine are document
rows a **person** labelled `dd-trustworthy` when batch 8 was loaded by hand —
provably the same work, since 027's work key matches them:

    c12 -> c21   net revenue                dd-trustworthy -> dd-feature-parity
    c13 -> c22   compare any period         dd-trustworthy -> dd-feature-parity

`objectives-2026-Q4.yaml` predicted this in its own comments, twice:
*"without a baseline, this objective ranks 'build another report' forever"*
(dd-feature-parity) and *"parity work must not outrank correctness work by
default"* (dd-trustworthy). principles.md makes trust-above-parity the first
ranking rule, and `objective_ref` is the only field carrying which of the two a
row serves. It was flattened to a constant and nothing noticed.

**This is a producer defect, not a ranking question**, and it is worth fixing
whether or not it ever separates a pair. The producer is not at fault for being
unable to see batch 8 — §7 forbids that deliberately. It is at fault for
inferring the objective from the document's subject and writing nothing down.

**What was built**, in the two places that can each see half of it:

* **`contracts/checks/candidate_block_shape.py`** requires a block-level
  `objectives_considered`: at least 25 words naming at least **two** real
  objective ids. It does not check that a label is *right* — no check can, that
  is the judgement the field exists to record — it checks that more than one
  objective was weighed in writing, on the same argument `unasked_question`
  rests on. The objective spread is printed on every passing run, with
  "EVERY ROW" called out when a batch is flat.
* **`console/load_candidates.py`** refuses a batch that changes the objective of
  work already loaded under a different one, matched on `work_key`. The
  producer cannot catch this; the loader can. A deliberate re-scoping is
  permitted by `--objective-change-note`, which costs a sentence and records it
  on `candidate_batches.note` — the same discipline `repeat_overrides` carry.
* **`--audit-objectives`** reports rows already loaded that disagree, read-only.

**The two live rows are NOT corrected.** `contracts/candidate-producer.yaml`
refuses reconciliation by name — *"a candidate that reappears is signal, and
quietly refreshing it erases that"* — and an UPDATE here would be exactly that.
c21 and c22 are superseded the next time the producer runs, and that run can no
longer re-label silently.

---

### 9.5 A refused night wrote nothing, so the ranker was silent for the same reason breakage would be — **FIXED 10 Sep 2026** (`console/approve.record_unattended_refusal`)

`approve_batch` is the only thing that touches `decision_log` on the unattended
path, and it is not called when there is nothing to approve. So a night where
§2.3 correctly declined to choose left **no row anywhere**, and the brief said
*"nothing was auto-approved since the last brief"* — the same sentence it would
print if the timer had never fired.

Refusing is the designed behaviour, not an error: the pace is 1, the pool has a
60% line, and §2.3 approves nothing when no key separates the top two. That is
exactly why it has to be recorded. **A correct refusal every night for a week is
a fact about the pool** — the keys have stopped separating it — and it is only
readable if each night leaves a row to count.

`record_unattended_refusal()` writes one `decision_log` row: `DEFERRED`,
`decided_via='unattended'`, the refusal sentence as `reason`, the ranked order
and the cut as `mechanics` (required, on 026's argument — a machine writing
prose into a NOT NULL column with nothing to check it against is 010's
UNRECORDED problem by a new route), and the candidates considered as evidence.
It queues nothing and touches no candidate. `brief/pass_.py` reads it and
prints the **streak**: how many nights running have gone without an unattended
approval between them.

**It is inert while the unit carries `--dry-run`, and that is deliberate.** A
dry run writes nothing — the invariant that makes a dry run worth reading — so
during the observation period a refusal is still recorded only in the journal.
Relaxing that to make the refusal visible would be a dry run with a side
effect. The fix takes effect the day the flag comes off; until then,
`journalctl -u fleet-autoapprove.service` is the record.

---

## 10. The first dry run over the live pool, and what it found

Run 9 Sep 2026 against the twelve open candidates, at platform `6fd8ddd`,
£139.09 remaining of the £158 pool.

    rank_v1 at platform 6fd8ddd; 12 open candidate(s), newest batch 9
    probes re-executed: 18 of 18 held  (across the 5 of 12 candidates that
                                        reached gate 4)
    cut: 1, bound by per_night
         {per_night: 1, max_approval_batch: 5, queue_room: 4,
          autonomous_credit: 37}

      c20  frontend-only  daily   Forward the four order filters …
      c25  modify         daily   Segment orders and products …
      c23  create         daily   CSV export of the order list …
      c24  create         daily   Scheduled digest of the dashboard …
      c27  create         daily   Establish where product cost would come from …
    x c21  HELD path_overlap  names platform/app/(dashboard)/analytics/page.tsx,
                              which queued task 49 declares
    x c22  HELD path_overlap  names platform/app/api/analytics/dashboard/route.ts,
                              which queued task 49 declares
    x c26  HELD path_overlap  names platform/app/(dashboard)/analytics …
    x c28  HELD path_overlap  names platform/app/(dashboard)/analytics …
    x c17  HELD older_batch   batch 8, and the newest is 9
    x c18  HELD older_batch
    x c19  HELD older_batch

    WOULD APPROVE: [20] reserving GBP 2.00

**It reached §2.3's answer**, which was written before any of this existed:
candidate 20 taken, 21 and 22 held on task 49's declared paths, and 17/18/19 —
the CSV-export duplicates — held as the older batch. The two dedupe cases §1.5
named are both refused, by two different gates, for the reasons given.

### 10.1 Five things the run established that the spec had wrong or unsaid

**1. Key 1 classifies exactly three rows as frontend-only, and §2.2 predicted
three.** c20, c21, c22. That is the only quantitative prediction in this
document that could be checked against the finished code, and it held.

**2. The band separates one row from eight.** Eight of batch 9 are Daily. Key 2
does almost no work tonight, so the order is very nearly key 1 then candidate
id — which puts more weight on the key §7.1 calls the most likely to be wrong,
not less. This is the argument for the `--dry-run` nights, and it is a stronger
one than the spec made.

**3. §7.2's worry about the overlap gate is real and now has an instance.**
c26 and c28 are held because they name the *directory*
`platform/app/(dashboard)/analytics` and task 49 declares one file inside it.
That is the gate being blunt exactly as predicted: one open frontend task holds
four candidates. It is the conservative direction — a missed overlap queues two
tasks against one file, a spurious one costs a night and prints why — and
`mechanics` records `matched_via` on every one, so a week of nights answers
this rather than an argument now.

**4. The probe count is "of the rows that reached gate 4", not of the pool.**
The gates short-circuit: a row held at gate 2 or 3 never has its probes
re-executed, because nothing will be spent on it either way. So the honest
figure is 18 of 18 across 5 of 12 candidates, not the 32 of 32 §4's example
line imagined. Both numbers are now printed, because "18 of 18 held" alone
reads as though the whole pool was re-verified.

**5. The brief's undo line had to become a real command.** §4 prints
`./fleet candidates undo <id>` beside every approval and §5 lists it as
correction 4. No such subcommand existed. A copy-paste undo that is not a real
command is worse than no line at all — it reads as a safety net right up until
somebody needs it — so `console/undo.py` and `fleet candidates undo` were built
with the brief section rather than after it. It abandons the unclaimed spec
tasks, returns the candidates to `PENDING`, **leaves the original
`decision_log` row untouched**, and writes a second decision citing it. §0 says
the `decided_via='unattended'` rows stay as the record of this period; a log
that can be tidied afterwards is not a record.

### 10.2 What the dry-run nights are for, specifically

Not "watching it work". Three questions, in the order they will be answerable:

1. **Does key 1 pick work that succeeds?** The class it prefers is the class
   whose specs passed the path check on five runs. A frontend-only candidate
   approved and specced without failing `draft_spec_shape.py` is one datum
   against a guess that currently has five, confounded.
2. **Does the overlap gate free up?** Task 49 is holding four candidates. When
   it merges, the next dry run should rank them, and if it does not, the gate
   is matching something it should not.
3. **Does the band ever discriminate?** It cannot on this pool. It needs a
   batch that is not eight-ninths Daily, which needs a producer run, which
   needs §8.1's producer timer.
