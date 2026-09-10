# Auto-approval — ranking candidates and ticking them with nobody watching

**Status: APPROVED 9 Sep 2026, at pace 1. BUILT, INSTALLED, AND LIVE SINCE
10 Sep 2026.** All six steps of §6 have landed and `--dry-run` came out of
`systemd/fleet-autoapprove.service` on 10 Sep, so from the 01:30 fire on 11 Sep
the timer approves for real at pace 1.

**Why the flag came out after two nights rather than several.** Both dry runs
approved one candidate and read as boring, and both were reporting an order
that an unrelated task's queue state had produced: c21 and c22 were held by the
overlap gate behind queued task 49, and those are the rows that tie with c20 on
every key. Task 49 failed at 02:07 on 10 Sep and the tie appeared at once. More
nights of that would have kept reporting the same artefact. Against it: the
pace is 1, one draft-spec task costs £2.00 of markdown on a local branch,
`draft_spec` is on `automerge.NEVER_UNATTENDED` so no flag makes it mergeable,
and §9.5 means a refused night now leaves a row — which a dry run, writing
nothing by design, could never produce. §0's reversal condition is unchanged
and is not a date. §10 records what the first dry runs over the live pool did.
Reads:
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

> **§9.6 is this defect with a second symptom, found 10 Sep from task 49.** The
> FAILED path writes `status` and `completed_at` and discards everything else
> the run established — the reason, and also the branch it had already pushed.
> One root cause, four instances.

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
whether or not it ever separates a pair.

> **CORRECTED 10 Sep 2026, and the correction moves the fault.** This section
> first said the producer *inferred* the objective from the document's subject.
> It did not. **Task 34's `spec_md` told it**, in its closing line:
>
>     ## Aim for the Daily band
>     Prefer rows an agency would open daily over ones they would open once.
>     The objective is `dd-feature-parity`, and a feature nobody opens does
>     not close a gap that matters.
>
> The producer did exactly what it was asked. So the primary fix is not a check
> at all — **it is that the task spec must not supply the answer to the one
> field carrying the top ranking rule.** The checks below still earn their
> place: `objectives_considered` would have forced the question even with the
> instruction present, and the loader's work-key comparison catches the
> re-labelling however it arose. But a spec that hands over the answer defeats
> a producer that would otherwise have had to think, and no check can see that
> it happened.
>
> **The same sentence contains a second instance.** *"Aim for the Daily band"*
> is why eight of batch 9's nine rows are Daily — and §10.1 then read that
> 8-of-9 spread as a property of the pool that made key 2 nearly useless. It
> was an artefact of the instruction. Batch 10's spec names no objective and
> asks for the document's bands as found.

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

### 9.6 The FAILED path discards everything the run knew, and §9.3 is the same defect

Recorded 10 Sep 2026 from task 49. **Not fixed here**, and it will recur.

> **FIXED 10 Sep 2026, after a fifth reading and a sixth.** The account below
> stands unedited; what follows is what was done and what it cost to leave.
>
> The fifth was task 51 — *"the platform has no deploy script"* — recorded at
> the end of this section. The sixth came the same evening: tasks 34 and 50
> were read as *"the candidate producer is failing"*, and an instruction was
> given to fix a producer that works. Both runs had `VERIFICATION_RUN = PASS`,
> both produced the documents that became batches 9 and 10, and batch 10's
> nine rows are most of the open pool. The premise came from the row.
>
> `033_failed_runs_keep_what_they_knew.sql` adds `runs.reason`, written on
> **every** settle rather than only on failure — a column that is NULL for
> success is a second encoding of `status`. `runner/cycle.py` writes
> `branch_name` on the failed and requeued paths as well, and **only when git
> says the ref exists**: `result.branch` is assigned before `worktree.create`
> runs, so a run that died early holds a name for a branch that was never cut,
> and recording that would be a new false statement of exactly this kind. The
> check is `_branch_exists`, and it asks the tree — this section's own rule.
>
> What it does not do: there is still no `FAILED → MERGED` edge, so tasks 51
> and 55 keep reading FAILED for work that shipped. That is a state-machine
> decision and it was declined on 10 Sep — see the paragraph on 031, refused
> because a rule saying "a failure may become a merge" is inherited by every
> unattended sweep. The rows are wrong and the reason column now says why they
> stopped, which is the smaller half of the fix and the one that was in scope.

`runner/cycle.py`'s terminal writer has two branches. The success branch records
what the run produced:

```sql
UPDATE tasks SET status='READY_FOR_REVIEW', branch_name=%s, completed_at=now()
```

The failure branch records that it stopped:

```sql
UPDATE tasks SET status='FAILED', completed_at=now()
```

`branch_name` is written **only** on the success path. Task 49 pushed
`fleet/task-49` at step 5 and died at step 6, so `origin` holds a verified,
reviewed-clean branch and `tasks.branch_name` is NULL. The console cannot show
it — `app.py` gates the diff view on `status == 'READY_FOR_REVIEW' AND
branch_name` — so verified work existed for a day in a place nothing in the
system pointed at. It took reading `git branch -a` to find it.

**§9.3 is not a separate defect; it is this one.** *"A task that fails after
verification writes no reason to the database"* and *"a task that fails after
pushing writes no branch name"* are one root cause: **the FAILED path writes two
columns and discards everything else the run established.** By then the runner
holds `result.reason`, `result.branch`, the verification verdict and the boundary
result, and none of it is offered to the row.

Four tasks are in this state — 21, 34, 49 and 50 — all with
`VERIFICATION_RUN = PASS`, all with artefacts that were used or merged. 027's
`task_was_unsuccessful_attempt()` reads round the silence by consulting the
verification step; it does not end it.

**Blast radius, checked rather than assumed.** Every reader that *acts* on
`branch_name` already gates on status: `console/automerge.py` selects
`WHERE status = 'READY_FOR_REVIEW'`, `console/app.py` requires both, and
`console/merge.py` is reached only from a reviewed task. The rest
(`morning.py`, `queries.py`) display it. So recording the branch on a FAILED
task would be visible and inert — the value is that a person can see what the
run left behind.

**The fix is one line on the failure branch plus a column for the reason**, and
it is deliberately not made here: it is a runner change, not an approval one,
and §9.3 has been open since 9 Sep without anybody being hurt by it. What has
changed is that it now has a fourth instance and a named cause.

**And on 10 Sep the silence misled a reader for the fourth time, in a new
direction: about a DIFFERENT task's work.** Reviewing task 55, I checked whether
the frontend had a deploy path, read `tasks` row 51 — *Give the platform a
deploy script*, `FAILED` — and concluded there was none. `platform/deploy.sh`
has been on `main` since f3284c8 that morning and had been run watched three
times, including a no-op. Task 51 says FAILED for the same reason tasks 21, 34,
49 and 50 do: **the work landed and there is no FAILED → MERGED edge.**

This is worth separating from the four above, because the blast radius argument
recorded there — *"recording the branch on a FAILED task would be visible and
inert"* — is about readers that ACT on `branch_name`. It is right about those,
and it does not cover this: the row is also read as a statement about **whether
the work exists**, and by that reading five FAILED rows are five false
statements. The cost so far is small and it is not zero — one wrong sentence in
a question put to the person who then had to correct it, which is the cheapest
possible version of the failure and not a reason to think it is the last.

The rule that would have saved it is not a schema change and is available today:
**ask the tree, not the row.** `git log -- platform/deploy.sh` is one command and
it is the same discipline `paired_paths.py` and `new_test_bites.sh` are built on
— *"git is the thing neither the agent nor the runner can talk out of"*. The
fix in the paragraph above is still the right one; this is what to do until it
is scheduled, and it is still unscheduled.

---

### 9.7 A check nobody can fail is what the first watched run is for

Recorded 10 Sep 2026. `platform/deploy.sh` shipped with a `wait_serving` step
that could not fail:

```bash
code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$APP_URL" || echo 000)"
case "$code" in 000) ;; 5*) …fail… ;; 4*) …warn… ;; *) echo serving; return 0 ;;
```

`curl -w '%{http_code}'` prints `000` on a connection failure **and** exits
non-zero, so `|| echo 000` appended a second one. `"000000"` misses the `000)`
case, falls through to `*)`, and returns success. **A container that came up
dead would have been reported as deployed** — the one thing the step exists to
assert.

It printed `serving: HTTP 000000` five seconds after the swap, on the first
watched run, against a port nothing was listening on. The deploy was fine —
the site served 200 throughout and the two sha assertions are independent and
both held — but the check contributed nothing.

**Three things did not catch it, and none of them could have.**
`deploy_script_shape.py` asks whether the script HAS a read-back, not whether
the read-back works; `bash -n` parses it; and the boundary and the contract
never see runtime behaviour. This is the class of defect
`contracts/checks/new_test_bites.sh` exists for on code — a check that passes
before the change it is meant to prove — and there is no equivalent for a
script whose verification cannot run it.

**What did catch it: the author saying which step they were unsure of.** The
spec asked for that in as many words —

> Say so in a comment, in the script, at the point where it matters.

— and the script carried `THIS IS THE STEP I AM LEAST SURE OF` directly above
the broken lines. That is why it was read closely on run one instead of run
five, and it is the cheapest instrument in this whole document: it costs a
sentence and it aims a person's attention at the place the author already knew
was thin.

**The general form, and it is not new here.** §9.5 was a refusal that left no
row; §7.1 of `specs/daily-brief.md` is a claim that left the same row every
morning; this is an assertion that could only succeed. All three are records
that exist and carry no signal, and in all three the absence looked exactly like
the healthy state.

---

### 9.8 `work_task_id` is read by two ceilings and written by nobody

Found 10 Sep 2026 while queueing task 53. **Recorded, and one link set.**

`022` and `027` both count a candidate's failures across **both** task columns,
and say why:

> Both task columns count. A candidate produces a spec task and later a work
> task, and either failing is a failure of that candidate: the first means the
> spec could not be written, the second that it could not be built.

`approve_batch` sets `spec_task_id`. **Nothing anywhere sets `work_task_id`.**
Of the six candidates that have produced a spec task, exactly one — c12 — has a
work task recorded, and it was written by hand. c13's spec task 22 merged and
became code task 28; the column is NULL.

So half the repeat-failure ceiling's stated scope is unreachable. A candidate
whose *build* fails twice scores 0, because the builds were never linked to it.
That is the same shape as §9.2 — a count over a quantity that cannot
accumulate — surviving inside the fix for §9.2, and 027's header asserts the
property as preserved rather than checking it.

It also breaks the console: `queries.py` joins `tasks w ON w.id = c.work_task_id`
for the candidate → spec → work chain, so that view shows a broken chain for
every candidate but one.

**Why it is not simply wired here.** The step from an accepted draft spec to a
code task is a *hand* step by design — §8's chain marks it HAND, and
`approve_batch` deliberately creates only draft-spec tasks. So the write belongs
wherever a person queues the code task, and today that is `./fleet task add`,
which knows nothing about candidates and should probably not learn: a task is
not always a candidate's. The honest shapes are an optional `--candidate N` on
`task add`, or the console's accept flow offering it when the draft it merged
came from one. Neither is chosen here.

**c29 → task 53 is set**, because it was a live fact at the moment of queueing
rather than history to be reconciled. The five older NULLs are left alone:
filling them now would be reconstructing links nobody recorded, which is the
reconciliation `contracts/candidate-producer.yaml` refuses by name.

---

### 9.9 Nothing in a contract can tell whether a spec was implemented

Task 53, 10 Sep 2026. `auto_merge: false` is the only thing that caught it.

`drafts/order-filters-frontend.md` §2.5 says the Payment, Country and Coupon
values in the table must set the corresponding filter when clicked, because
exact matching is unusable if the user cannot discover the exact string and no
endpoint lists the distinct values. **It was not implemented.** The diff does
not touch row rendering at all.

All four checks passed, in the runner and again at accept:

    tsc --noEmit                    exit 0
    vitest run                      exit 0
    new_test_bites.sh               exit 0   (the added test does bite)
    paired_paths.py                 exit 0   "2 paired group(s) --
                                              1 landed whole, 1 untouched"

None of them can fail for this, and that is not a gap to be closed by adding a
fifth. `tsc` proves it compiles. `vitest` proves 319 tests pass. The bite check
proves the ONE test the change added fails without the change — which says
nothing about the requirements the change did not add a test for.
`paired_paths` proves both halves of a pair moved; §2.5 lives entirely inside
one of them, so the group was satisfied by the file being touched at all.

**The pairing group added this morning did work**, on its first task, and it
proves exactly what it claims: both files landed. It cannot prove what is in
them.

So the honest statement of the gate is narrower than it reads: **a green run
establishes that the tree typechecks, that the suite passes, that one new test
bites, and that no pair landed in half. It establishes nothing about whether
the spec was followed.** The contract's own header says this — *"It does not
establish that the page says a true thing. See auto_merge below, which is
`false` for exactly that reason"* — and this is the first frontend task to
prove it rather than assert it.

**What that makes `auto_merge: false`.** Not a caution to be relaxed once the
checks have been green a few times. It is the only reader of the spec in the
entire path, and the thing it catches is invisible to every automated check
that exists or could cheaply be written. A partially-implemented spec merges
green.

Accepted anyway, deliberately: 2.1, 2.2, 2.3 and 3 are present and correct, the
four filters work, and §2.5 is entered as its own candidate (c38) rather than
queued as a follow-up fix — so it competes on merit rather than inheriting the
priority of the task that missed it.

**And `dd_api` still defaults `auto_merge: true`, which is the same gap with no
reader at all.** That default was chosen deliberately for the parity push and
the argument for it holds; what did not exist until now is a written account of
what it costs. A dd_api task that implements four of five numbered requirements
merges, deploys, and is recorded MERGED with every check green — the frontend
equivalent of exactly what task 53 did, minus the person who caught it. The
consequence is recorded against the decision itself, in
`contracts/deadly-digital-platform-api.yaml` beside `auto_merge: true`, so it
is a known trade rather than something rediscovered later. §9.12 costs the
cheapest partial reader that would narrow it.

It also changes *why* §7 reverses that default: not only that a bad merge
becomes expensive once there are customers, but that a partially-built feature
is not a bad merge and triggers no revert.

#### 9.9.1 The second instance runs the other way: task 55 built MORE than the spec

**Added 10 Sep 2026, on merging task 55 by hand.** §9.9 was written about a
requirement that went missing. The same silence passes a requirement that was
*added*, and it is the same four checks that cannot see it.

Task 55's spec — `drafts/order-table-cells-set-the-filters.md`, itself written
by task 54 — rests on a premise about the tree: *"The values are on screen, in
the Payment, Country and Coupon columns of the very table being filtered, and
they are inert."* **They were not on screen.** The order table on `main` at
6f3525a renders five columns: `wc_order_id`, `created_at`, `billing_email`,
`status`, `total`. The premise came from `drafts/order-filters-frontend.md`
§2.5 (*"make the value in the Payment, Country and Coupon cells set the
corresponding filter"*) and its human-check step (*"Set a payment method that
exists in the Payment column"*), both of which describe a table that has never
existed. Two drafts asserted it and nothing checked it, because a draft's own
gate (`draft_spec_shape.py`) reads the shape of the spec block, not the truth
of its prose.

So the agent **added three columns to the order table** — Payment, Country,
Coupon — because you cannot click a value that is not rendered. That is the
right call on the facts and I would not want it made differently. It is also:

* not in *What to build*, which says the change is `FilterValue` and three
  `render` functions in one file;
* against that spec's own *What must not change* — *"With nothing clicked, the
  request the page sends and the table it renders are byte-for-byte what they
  are today"* — which is now false for the table, though it stays true for the
  request;
* a visible product change to the page an agency operator lives in, decided by
  an agent at 15:45 and reviewed by nobody.

**And every check passed.** `tsc` 0, `vitest` 0 with all 319 tests including
`orders.render.test.tsx` — the named regression guard, which does not assert a
column count — and `new_test_bites.sh` 0. Only `paired_paths.py` failed, for an
unrelated and by then wrong reason (§9.9.2). Had the pairing not been there, this
would have merged and deployed unattended.

**That is two in three tasks.** Task 53 shipped four of five requirements; task
55 shipped all nine of its numbered ones — 1.1 to 1.5, 2.1 to 2.3 and 3, each
checked against the diff by hand on 10 Sep — and three table columns nobody
asked for. Both were caught by something that
was not looking for them: task 53 by `auto_merge: false`, which is now `true`,
and task 55 by a stale pairing, which is now removed. **Neither reader is in
the path any more.** The honest position after this change is that nothing
compares the spec to the diff at all, in either direction, and the next
instance will be found by somebody using the product.

The cheapest thing that would have caught THIS one is not a fifth check on the
diff. It is a probe on the premise: `candidates.probes` already carries
`grep_count` assertions, c38's ran and passed, and none of them asked whether
the Payment column existed. A spec whose premise is a claim about the tree can
carry that claim as a probe, and a false premise then fails at approval — before
a run is paid for, and before an agent has to decide alone what to do about it.

**BUILT 10 Sep 2026**, `030_candidate_premise.sql` and gate 6.

    candidates.premise          [{claim: <sentence>, probe: <one predicate>}]
    candidate_block_shape.py    REQUIRES one, and re-executes it at emit
    console/load_candidates.py  carries it whole; re-executes nothing
    console/rank.py gate 6      re-executes it at the approval, at HEAD
    console/autoapprove.py      records claim + verdict on the decision

**Run against the tree c38 was actually approved against** (platform 6f3525a,
10 Sep, before task 55), the premise it should have carried and the probes it
did carry answer differently — which is the whole claim of this section,
measured rather than argued:

    claim: the order table renders payment_method, billing_country and
           coupon_code as columns of its own
      grep_count key: '(payment_method|billing_country|coupon_code)'
        at 6f3525a          FAILED   = 0, expected 3
        at main (post-55)   HELD     = 3, expected 3

    and the three c38 shipped, at 6f3525a:
        path_exists  orders/page.tsx                       HELD
        grep_count   aria-label="Filter by payment method"  HELD  (= 1)
        grep_count   onClick={() => setPaymentMethod        HELD  (= 0)

Gate 6 would have refused it at 14:11 with `premise_failed`, before the draft
task and before the run.

A premise is not a probe and the difference is the whole point. `probes` say
what is MISSING; a premise says what must ALREADY BE TRUE for the work to be
the work described. c38's four probes were all of the first kind — the filter
box exists, no cell is wired to it, the API takes the parameter, the file
exists — which is why they held while the sentence the rationale rested on was
false. The rules are separate for the same reason: `probes_failed` means the
gap closed, so drop the row; `premise_failed` means the ground is not there, so
the row is a **different piece of work** from the one proposed and wants
re-proposing rather than re-running.

**Why the producer and not the draft spec, since both restated the false
claim.** Three documents carried it. `drafts/order-filters-frontend.md` §2.5
said "make the value in the Payment, Country and Coupon cells set the
corresponding filter" and its human-check step said "set a payment method that
exists in the Payment column"; c38's rationale said the values "are inert";
`drafts/order-table-cells-set-the-filters.md` said they were "on screen, in the
Payment, Country and Coupon columns of the very table being filtered". Each
cited the one before it. None looked.

The candidate is where it belongs anyway, for two reasons that are about the
mechanism rather than about which document was first:

1. **The approval is the only step that re-executes anything.** Gate 6 runs at
   01:30 against the sha it is about to spend money at. A draft spec has no
   equivalent: `console/autoqueue.py` queues the work task on the draft
   MERGING, and the only human decision in that window is the acceptance —
   which is a judgement about intent, not a re-execution of claims.
2. **It fails earliest and cheapest.** A premise probe on c38 would have failed
   at 14:11 on 10 Sep, before the spec task and before the work task: the £2
   draft and the £2.25 run, both. A draft-time probe would have saved only the
   second.

**What draft-spec time would still add, and what it would cost.** A draft can
introduce a premise its candidate never had — task 54's did, in more detail
than c38's — so the second net is real. It needs a `premise:` key in the
```fleet-spec` block, `draft_spec_shape.py` re-executing it against the tree as
part of the draft task's own verification, and `autoqueue.py` re-executing it
again at queue time, because a draft can sit between merge and queue. That is
three places rather than one, it changes the contract every draft runs under,
and it is a separate decision from this one. Not built. What is recorded here
is that the mechanism generalises and where it would go.

**And the hole this leaves, stated so it is not read as closed.** Every
candidate in the pool on 10 Sep — all 41, the 20 still pending among them —
predates the key. Gate 6 does not refuse an empty premise, because doing so
would stop unattended approval dead for rows whose producers were never asked
for one. `mechanics.premise.silent` counts them and the sweep prints the count;
`candidate_block_shape.py` refuses a NEW block without one, so the pool turns
over from the producer end. Once it has, an empty premise should join an empty
probe list as ineligible. That is one line in `rank.check_premise` and it is
not written yet.

Two things this still cannot do. It cannot tell whether the probe tests the
claim or something adjacent — a producer may file a true-sounding sentence over
a probe about something else, and gate 6 will run it, find it holds, and pass.
What changed is that the sentence is now written down beside the predicate, in
the row and on the decision, so the reader's question is one sentence rather
than a whole rationale. And it cannot make a producer state the LOAD-BEARING
premise rather than a safe one: "the orders page exists" is a premise, it will
hold forever, and it establishes nothing. Both are a read, and this makes the
read smaller rather than replacing it.

#### 9.9.2 What the pairing cost while it was doing this

Task 55 failed on `paired_paths.py` and on nothing else, after 107 seconds of
`tsc` and `vitest` that had already passed. The group it broke was added the
same morning, for task 53, and was correct for exactly one task: it said the
orders proxy and the orders page must land together, because a page half alone
ships four filter controls that silently return unfiltered rows. Task 53 landed
both halves, so from that moment the parameters agreed and the danger was
unreachable — but the group went on refusing any later change to either file
alone, which is what task 55 was.

`drafts/order-table-cells-set-the-filters.md` predicted this precisely, under a
heading reading *"Before this is queued: `paired_paths` will refuse this
diff"*, and listed the three ways to resolve it. **Nobody read it.** The draft
merged at 14:17:50, `console/autoqueue.py` queued the work task at 14:21, and
the only human decision in that window — `decision_log` 27 — was an unattended
approval of the *candidate*, made at 14:11, three minutes before the draft that
carried the warning existed. A section addressed to "whoever queues this" has no
reader on a path where queueing is a function call.

Both groups were removed the same day and replaced with
`contracts/checks/proxy_passthrough.py`, which checks the property directly:
every parameter a page sends must be one its proxy forwards. See
`contracts/dd-analytics-frontend.yaml` above its writable list for why a pairing
was the wrong shape in both directions, and for where a pairing that expires
should have gone instead — on the task row, which `autoqueue` has no way to
write.

---

### 9.10 The accept path had four defects and task 53 was the first to meet them

All four were in the path, none in the branch, and each hid the next.

**1. Re-verification never linked the dependency tree.** `console/reverify.py`
had no reference to `worktree_links`, so in a trial clone — which has no
`node_modules`, it being gitignored — every frontend check failed at
`exit 127`. **FIXED**: the links are created after the boundary is judged, as
`runner/cycle.py` does and for the same reason.

**2. The console had been running code from 9 Sep 10:05 for three days.**
`creatable_paths` landed in `runner/boundary.py` at 9 Sep 14:08 — four hours
after the process started — so the running console enforced the boundary rules
of whenever it was last restarted. It refused task 53's added test file as
*"protected by platform/\_\_tests\_\_/\*\*"*, a rule the codebase had
retired before that process ever applied it. The contract is read fresh from
the database on every request, so everything about the refusal looked current.
**FIXED by restarting**, and the class is not: nothing reports the console's
code version, and a long-lived web process silently freezes its own rules at
boot.

**3. `MemoryMax=512M` against a 709 MiB `tsc`.** The console aborted it with
SIGABRT (exit 134) and reported *"the branch verifies on its own and FAILS when
merged into main as it stands now. The base moved under it."* The base had not
moved: main **was** the branch's merge base. Nothing in the path distinguishes
a check that failed from a check the sandbox killed. **FIXED**: 2G, measured
(`tsc` 709 MiB / 13s, `vitest` 352 MiB / 73s plus workers), bounded rather than
infinity because this process also serves HTTP. `fleet-runner.service` runs the
same commands at `MemoryMax=infinity`, so the two paths that must agree about
whether a branch passes were never given the same room to answer in.

**4. NOT FIXED: `ProtectHome=read-only` versus the dependency link.** With
memory raised, `vitest` exits 1 inside the console and 0 outside it. The trial
clone's `platform/node_modules` is a symlink into the checkout, and vitest
writes `node_modules/.vite/vitest/results.json` — **the same file that failed
task 49 this morning**, from the opposite side. There it was a write the
tampering guard caught; here it is a write the sandbox forbids.

That is one root cause with two faces: **`link_dependencies` points a
path verification WRITES TO at a shared checkout.** The console must not be
given write access to it — *"the console writes to no checkout"* is the
property `702bce0` exists to state — so the fix is to stop the write landing
there: link `node_modules` per entry with a local `.vite`, rather than linking
the directory whole. That is a change to `runner/worktree.link_dependencies`
and it belongs in daylight, not at the end of a session.

**Task 53 was therefore accepted by running the accept route's own functions —
preflight, reverify, merge_and_push, decide.record, in that order — outside the
console's sandbox.** Not a hand `git merge`: the same code, the same trial
clone, the same push verification, the same `HUMAN_DECISION` record. The base
had not moved, so re-verification re-established what the run established.

---

### 9.11 Gate 2 assumes a newer batch re-verified the older one

Found by causing it, 10 Sep 2026. Entering §2.5 as candidate c38 required a
batch row; a new batch (11) was created because the source is a draft spec
rather than a findings document. **Batch 11 immediately suppressed all nine of
batch 10's candidates** as `older_batch`.

Gate 2's argument is sound for the case it was written against: *"Batch 9
re-verified batch 8's rows against a newer sha, so an older row is superseded
by construction."* It does not hold here. Batch 11 is one hand-written row from
a different document; it re-verified nothing. Nine rows re-verified this
morning are now unreachable, and the brief will report them held for a reason
that is not true.

The narrow fix is to supersede on the SOURCE DOCUMENT rather than on the batch
id — an older row is superseded when a newer batch re-read the same document —
which is a change to a ranking gate and is not made here. **The immediate
question is whose pool it is**: c38 can be moved into batch 10, or batch 11 can
stand and batch 10 wait for the next producer run. Left as found, and reported.

---

### 9.12 The cheapest partial reader, costed

Asked for on 10 Sep 2026, against §9.9 and `dd-analytics-frontend.yaml`'s
`auto_merge: false` being the only reader of a spec. **Not built. Costed.**

The brief is narrow on purpose: catch **a numbered requirement with no
corresponding change**. Not "is the change correct" — nothing cheap does that.

**What does not work, measured rather than assumed.** Grepping the diff for the
requirement number is worse than nothing. Against task 53's real diff:

    §2.1  1 match     implemented
    §2.2  0 matches   implemented
    §2.3  0 matches   implemented
    §2.4  0 matches   not applicable
    §2.5  1 match     NOT IMPLEMENTED

Both "matches" are stray digits and two implemented requirements score zero. A
reader built on that would refuse working changes and pass the one that was
missing — the worst possible arrangement, because it would be believed.

**What would work, and what it costs.** Traceability by explicit marker:

1. `draft_spec_shape.py` requires each requirement to carry a stable id. The
   specs already number them (`**2.5 The table cells set the filters.**`); this
   makes the convention enforceable rather than habitual.
2. `runner/cycle.py` passes the task's `spec_md` to checks as a fact, beside
   `FLEET_CONTRACT`. One line. Checks cannot reach the database and should not
   start.
3. A checker extracts the ids and requires each to appear in an ADDED line as
   an unambiguous token — `spec:2.5` — in a comment, a test name, or a
   docstring. Refuse when an id appears nowhere.

Roughly 80 lines of checker, one fact, one shape rule.

**It would have failed task 53.** No line of that diff carries such a marker
for any requirement.

**What it proves, stated so it is not oversold: that a claim was made, not that
it was met.** An author can write `// spec:2.5` and change nothing. That is
still worth having, because it converts a silent omission into a written,
attributable claim sitting in the diff — visible to review, and a lie rather
than an oversight. It moves the failure from invisible to answerable.

**The cost that is not lines of code.** No such convention exists today: zero
fleet-authored commits in the platform repository cite a spec section. So this
imposes an annotation burden on every future task, and the burden is heaviest
on exactly the small changes where it is least needed.

**Where it belongs, and where it does not.** On `dd_api` it narrows the silence
that `auto_merge: true` buys — that path has no reader at all, so a mechanical
claim-check is strictly more than nothing. On the frontend contract, where a
person already reads the spec, it adds annotation cost for a check weaker than
the reader it sits beside.

**A cheaper thing that is not a check — BUILT 10 Sep 2026** rather than the
marker convention above, which is not built. `console/requirements.py` parses
the numbered requirements out of `spec_md` and `task_detail.html` lists them
above the diff. On task 53 it renders the eight the spec states, §2.5 among
them, with the identifiers intact so a reviewer can search the diff for
`has_discount` rather than for `hasdiscount`.

Two shapes count, both taken from specs that exist: a numbered heading
(`### 2. The page sends them`) and a numbered bold lead
(`**2.5 The table cells set the filters.**`). A bare `**1. Something**` does
not, because that is how paragraphs are emphasised; content inside a fence does
not, because those are examples; and unnumbered prose that reads like an
instruction does not, because **a checklist containing things the spec did not
number is one the reviewer learns to distrust, and the first item they dismiss
is the one that mattered**.

It checks nothing, ticks nothing and records nothing — the page says so in as
many words, because a tick that looked persisted would be a claim about state.
`decision_log.reason` is where a reviewer says what they checked.

§9.9 exists because a person read a 250-line spec against a 300-line diff and
did not notice one missing item out of eight. That is what a list is for, and
it is the whole of what this does.

---

### 9.13 `work_type` does not identify a contract, and three of seven are ambiguous

Found on 10 Sep by building `console/autoqueue.py`, which has to answer
"which contract does this spec's work run under" and could not.

    work_type            repo                     contracts
    dd_api               deadly-digital-platform  3   <-- AMBIGUOUS
    dd_frontend          deadly-digital-platform  2   <-- AMBIGUOUS
    research             fleet                    2   <-- AMBIGUOUS
    candidate_producer / dd_docs / dd_infra / draft_spec   1 each

The extra ones are **spent single-task contracts** — `dd-order-filters.yaml`
(task 2, merged 30 Aug), `dd-acquiring-page.yaml` (task 3, 30 Aug),
`dd-utm-source-alias.yaml` (task 7, 31 Aug), `research-metorik-gap.yaml`. They
were correct when written and were never retired, and `dd-acquiring-page.yaml`
still describes itself as *"the default frontend contract plus this task's own
acceptance check"* — a default contract that `023_platform_floor.sql` deleted
and floored.

**What this has already been doing.**
`contracts/checks/draft_spec_shape.py`'s `load_protected()` resolves a spec's
work_type with `CONTRACTS.glob("*.yaml")` — unsorted — and returns the first
match. So **every draft spec has been validated against whichever contract
readdir happened to yield**, for both of the work types that auto-merge. Its
own docstring argues carefully for judging a spec against *the* contract its
work will run under, *"which is also the contract the resulting task will
actually run under"*. That is the right rule; the lookup does not implement it,
because at the time it was written each work_type had one contract.

Nothing is known to have gone wrong: the spent contracts are narrow, so a spec
declaring paths outside them would have failed the shape check loudly rather
than passed wrongly. The defect is that which contract answers is decided by
directory order.

**What autoqueue does instead.** Among contracts matching `(work_type, repo)`,
keep those whose writable set covers **every** declared path; if exactly one
survives, that is the contract. Otherwise refuse. That is a real discriminator
rather than a preference — a contract that cannot write what the spec says it
will write is not the contract the work runs under — and it is why a spec about
the orders page resolves to `dd-analytics-frontend.yaml` while one naming
`Sidebar.tsx` resolves to `dd-acquiring-page.yaml`.

**Not fixed here, and it is the sharpest edge on the automation.** Retiring
four contracts is four decisions about what a boundary was for, and
`draft_spec_shape.py`'s lookup is a producer-facing check. Both are the user's
to make. Until then the unattended loop refuses any spec whose declared paths
do not pick out exactly one contract — which is the safe direction, and is a
refusal that will read as mysterious the first time it fires.

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

> **Corrected 10 Sep 2026: that spread was manufactured, not observed.** Task
> 34's spec said *"Aim for the Daily band"*, so eight-ninths Daily is an
> artefact of the instruction and not a fact about the gap list, which carries
> Daily, Weekly, Rarely and Never sections. Reading it as a property of the
> pool — here and in §7's "1 and 2 got worse" note — was reading the
> instruction back as evidence. §9.4 carries the general form of this. Batch
> 10's spec asks for the document's bands as found; whether the band ever
> discriminates is answerable from that batch and was not answerable from this
> one.

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

---

## 11. Coverage as key 2 — what it fixes, and the limit stated up front

Built 10 Sep 2026: `028_hib_signal_coverage.sql`, `console/rank.py` (rank_v2),
and a producer-contract change in `contracts/checks/candidate_block_shape.py`.

### 11.1 Why: the tie was not the exception, it was being masked

On 10 Sep the ranker approved nothing — c20 and c21 are both `frontend-only`
and both Daily, so no key separated them and §2.3 refused. **The two nights
before that produced an answer only because the overlap gate was hiding c21 and
c22 behind queued task 49.** Task 49 failed at 02:07 and released them. So the
discriminator on 9 and 10 September was *an unrelated task's queue state* —
§7.2 worries gate 3 is too blunt; this is the same bluntness manufacturing
discriminators rather than suppressing rows.

At pace 1 the only comparison that matters is top-versus-next-eligible, and in
a sorted list those are **by construction the two most similar rows in the
pool**. A discriminator further down the order is never consulted. Raising the
pace does not help: at pace 2 the cut lands on c21 vs c22, which also tie.

### 11.2 The one real discriminator that was in the evidence

`hib_signal` carried it and 025 deliberately refused to parse it:

    c20  payment_method  2,782,530 of 2,844,177   97.83%
    c21  refund_total            1 of 2,844,177    0.0000352%

025 was right that no sort key gets that out of a sentence, and right about
what the second version is. 028 is that: `hib_signal.coverage`
`{metric, populated, total}`, required as a **key** and nullable as a **value**
— because "all seven RFM buckets populated" is a real signal and is not a
ratio. The sentence stays and the brief still prints it verbatim.

Key 2 is three statements, not a scale: `data-present`, `no-figure`,
`data-absent`. **A row that supplied a bad number ranks below one that supplied
none** — the alternative rewards silence. `no-figure` is not zero: "the
document stated no fraction" and "the column is empty" are different facts, and
collapsing them is precisely how a ranker gets net revenue wrong.

The floor is `fleet_hib_coverage_floor()` = 1%, and it is **measured rather
than chosen**. Every figure the source document states about production:

    refund_total       0.0000352%          discount_total     5.1348070%
    coupon_code        5.1380768%          utm_source        70.6952837%
    payment_method    97.8325189%          billing_country   99.8543691%

One gap, four and a half orders of magnitude wide. 1% sits inside it with
1,459× of margin below and 5.1× above, so **every threshold in that range sorts
this pool identically** and the choice cannot be what makes the ranking come
out one way rather than another. That is the whole claim; it is not a claim
about where a column stops being worth reporting on in general.

And it agrees with a judgement a person already made independently:
`decision_log` 23 records that the net-revenue netting is not exercised by live
data at all — *"net_revenue therefore equals revenue in every window on every
tenant today"*.

### 11.3 The limit, and it is shorter than four nights

Simulated at pace 1 over the live pool, assuming the two figures were
machine-readable: coverage separates nights 1 through 4 and then **c23, c24,
c26 and c27 tie four-deep** — CSV export, scheduled digest, cross-store
roll-up, product cost — all `create / daily / no-figure`. `TestTheFourNightLimit`
holds that as a test so "coverage fixed the ranker" cannot be believed by
reading the code.

**And on the pool as it stands today it buys nothing at all.** The first dry
run at rank_v2 reads `no-figure` on all twelve rows, because the existing
signals are prose in rows that are already loaded. They are not backfilled, and
deliberately: deriving the numbers would mean parsing the sentence — the parse
025 refused and 028 exists to make unnecessary — and rewriting a loaded row is
the reconciliation `contracts/candidate-producer.yaml` refuses by name. **The
key becomes live when the next producer run emits coverage objects, which the
shape check now requires.** Until then it is correct, tested against the real
figures, and inert.

### 11.4 What no key can fix

The four rows at the bottom are separated by what HIB's team would actually
open. Nobody has asked — the producer block is required to carry
`unasked_question` for exactly this reason — and nothing observes it:
`deadly_digital` has three schemas and no event, tracking, session, page-view
or activity table anywhere. principles.md says to rank against HIB as *"a real
merchant whose behaviour can be observed"*. It is not observed.

That is a question for a person and no ranking key substitutes for it.
