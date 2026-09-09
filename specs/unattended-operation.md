# Unattended operation — the producer to production, with nobody in the loop

**Status: SPEC. Nothing built.** Reads: `contracts/deadly-digital-platform-api.yaml`,
`contracts/checks/pytest_unit_per_file.sh`, `003_tasks.sql` §2 and §6,
`013_approval_surface.sql` §1, `proposer/cycle.py`, `runner/cycle.py`,
`brief/claims.py`, `api/deploy.sh`, `api/drift-check.sh`.

---

## 0. What changed, and what the gates were sized for

The gates in this system were sized for a product with customers. Deadly Digital
has none, HIB is not using it, and every change is reversible through git. The
goal is Metorik parity on analytics, quickly, and the constraint that matters is
**how many nights it takes**, not how carefully each night is reviewed.

So the loop becomes: the producer emits candidates, specs get drafted, code gets
built, verified, merged and deployed, and a person reads the morning brief and
reverts anything wrong.

**This is a temporary posture and the spec says so in the one place that
matters — §7 is the list of what has to go back, and it is written now rather
than reconstructed later.**

### What does NOT change, and is not negotiable

1. **A task can only write the files its spec declares.** The contract boundary
   and the diff-judged-against-the-row property stay exactly as they are. Every
   widening below is to `verification`, never to `writable_paths`.
2. **Nothing touches email.** §2, and it is built as a refusal rather than an
   instruction.

---

## 1. The two findings that shape the rest

### 1.1 The analytics gate is one contract line away, not a build

`contracts/checks/pytest_unit_per_file.sh` already takes its target as an
argument — `pytest_unit_per_file.sh api tests/analytics` runs today. Its own
header records that the blocker was removed on 8 Sep 2026:

> *the test-db tmpfs was raised from 384 MiB to 1536 MiB on 8 Sep 2026, and a
> whole tests/analytics directory run peaks at 648 MiB — so it no longer
> exhausts the disk after about eight files... What remains is time.*

`tests/analytics` is 675 tests across 36 files, ~7.5 minutes, and green as of
`7375d0a`. **NOT RE-MEASURED SINCE**, and `main` has moved (task 26 merged, plus
deploys). §3.1 re-measures before relying on it.

### 1.2 "Nothing touches email" cannot be enforced by the contract as it stands

`api/app.py` is **19,300 lines and 180 endpoints, 39 of them email** — 16
`/api/flows`, 14 `/api/campaigns`, 6 `/api/deliverability`, 3
`/api/suppression`. And `api/app.py` is in the api contract's
`writable_paths`.

So a task under today's contract can rewrite the campaign sender and the
boundary check passes clean. **The email platform is not a module that can be
excluded; it is interleaved in the single most-writable file in the
repository.** That is what §2 is shaped by.

---

## 2. Email: a refusal, not an instruction

Three layers. The first is the whole fix; the other two close what it leaves.

**2.1 Drop `api/app.py` from `writable_paths`.** It costs nothing: tasks 26 and
28 both wrote only under `api/analytics/`. Parity work does not need `app.py`.
A task that genuinely needs it is a task a person queues by hand.

**2.2 Put the email surface on `protected_path_floor`**, the table — not in a
contract file. The `tasks_contract_floor` trigger fires for any caller,
including direct inserts, so this becomes a refusal at `INSERT` for every task
in the repository regardless of what contract anyone writes:

```
api/app.py                              the email platform is interleaved here
api/services/email_sender.py            the sender
api/analytics/routes/interventions.py   where analytics grows into email
api/analytics/services/trigger_router.py  ditto -- it already writes channel='email'
```

`api/worker.py` (24 email tasks) and `platform/**` are already protected by the
contract; the floor is where they become unconditional.

**The last two are the ones a path list would miss.** `trigger_router.py` is
inside the analytics tree the fleet owns and already writes intervention rows
with `channel='email'`. It sends nothing today. It is the single most likely
place for an autonomous fleet to grow into the email platform by accident, and
it is floored for that reason and no other.

**2.3 A new-file guard.** A floor cannot stop an agent CREATING
`api/services/email_sender_v2.py`. A contract check refuses any diff that adds
a file whose path or content matches the email domain
(`campaign|flow|subscriber|suppression|deliverability|ses_|smtp|listmonk`).
This is the only route 2.1 and 2.2 leave open.

---

## 3. Verification: what would make auto-merge honest

### 3.1 The tests, which are the easy half

Add to the api contract's `verification`:

    contracts/checks/pytest_unit_per_file.sh api tests/analytics

Before it is relied on, re-measure `tests/analytics` file by file at current
`main` — §1.1's green is a day old and against a moved tree. If files fail, they
are fixed or the gate does not go in. **A gate added over a red suite is a gate
that gets disabled the first morning it is inconvenient.**

### 3.2 The hard half, and the reason "675 tests passed" would be a lie

**The agent cannot write tests.** `api/tests/**` is on the floor — *"the suite
that judges the work"*. So a new feature lands with no test covering the new
behaviour, and running all 675 analytics tests proves the change **broke
nothing**. It cannot prove **the new thing works**.

Task 28's own spec says this about itself: a passing run does not establish that
any comparison window it computes is the right one. On full auto, "passed 675
tests" reads as verified and means *not obviously regressed*. **That is nominal,
not honest, and it is the failure this whole codebase has been bitten by four
times — a check that could not fail.**

So: **the agent writes a test, and the test must be proven to bite.**

1. The spec declares, in prose, what the acceptance test must assert.
2. The contract permits **creating — never modifying** — one file matching
   `api/tests/analytics/test_fleet_<task_id>_*.py`. Modification of any existing
   test remains floored.
3. The gate runs three things:
   - the new test **passes** against the change;
   - the new test **FAILS against the pre-change tree** — a mutation run, done
     automatically;
   - all 675 analytics tests **stay green**.

Without the middle check an agent writes `assert True` and the gate blesses it.
With it, the agent must produce a test that discriminates. This is §6.2 Rule 2 —
*a check must be demonstrated to fail against the broken state before its pass
is believed* — applied by machine instead of by hand, and it is the single
thing that separates auto-merge from rubber-stamping.

### 3.3 The budget this leaves

| step | measured |
|---|---|
| compileall + ruff | ~1s |
| `tests/unit`, 31 files | **226s** (task 28, 9 Sep) |
| `tests/analytics`, 36 files | ~450s (8 Sep, to re-measure) |
| mutation re-run, one file | ~15s |
| agent work | ~165s (task 28) |
| **total** | **~14 min against the 1800s cap** |

---

## 4. The morning brief

Today's brief is 19 descriptive counts and says outright that it *"carries no
judgement until there are thresholds worth judging against"*. That is right for
an attended system and wrong for an unattended one: **a brief of counts cannot
tell you a bad night happened.**

A new section, above everything else, readable in one glance:

```
OVERNIGHT: 3 merged, 1 failed, 0 reverted.        £7.43 spent, £141 left (19 nights)
  #29  comparison windows        merged 03:12  deployed 03:20  green   test bit
  #30  coupon report             merged 04:01  deployed 04:08  green   test bit
  #31  product perf              FAILED  02:40  boundary: wrote outside spec
  main == production                                          drift-check ok
```

Four things it must show that nothing currently computes:

- **merged and deployed per task, with the deploy outcome.** `drift-check.sh`
  already answers "is production running what `main` says"; the brief does not
  read it.
- **spend as a RATE.** "£141 left" is useless without "19 more nights at last
  night's rate". A number that only becomes alarming on the last day is not a
  control.
- **failures by REASON CLASS.** Boundary violation, verification failure, and
  could-not-run are three different mornings and must not read alike.
- **the mutation result per merged task** — `test bit` or `test did not bite`.
  One line, and it is the only line that says whether the gate meant anything.

**"What it could not check" stays.** It is the best thing about the current
brief and the first thing an autonomous system would be tempted to drop.

---

## 5. What stops a runaway

| control | now | after |
|---|---|---|
| queue depth | 5 | 5 |
| approval batch | 5 | 5 |
| proposer items per cycle | 5 | 5 |
| repropose suppression | 14 days | 14 days |
| `max_attempts` | 1 | 1 |
| per task | £3.00 | £3.00 |
| monthly pool | £158, stop at 100% | **stop at 60%** |
| repeated failure of the same finding | *nothing* | **§5.2** |

**5.1 The pool stops at 60%, not 100%.** Stopping at the ceiling means finding
out when the month's work is already spent. At 60% the fleet stops queuing and
the brief says why, leaving £63 for work a person chooses.

**5.2 A candidate that has failed twice is not approved automatically.**

**CORRECTED 9 Sep 2026 while building it.** This section originally read *"a
finding whose last two tasks both FAILED is not re-proposed"*, with the check
going beside the existing suppression in `proposer/cycle.py`. That does not fit
the system, in two ways found by tracing the chain rather than assuming it:

1. **There is no `finding` → `task` link.** Findings become `proposals`;
   candidates are read from a findings DOCUMENT by the producer task and carry
   no `finding_key`. The proposer's 14-day suppression is about proposals and
   never reaches a task, so a check there would have suppressed the wrong thing
   and changed nothing about cost.
2. **The producer must not deduplicate, and that is enforced rather than
   asked** — no Bash, no credential, one writable file, and a shape check that
   refuses `batch_id`. §7 of `specs/approval-surface.md`: *"a candidate that
   reappears is a signal, and a producer that silently dropped repeats would
   erase it."* Suppressing at production would have broken a designed property
   to fix a problem that lives elsewhere.

So the stop is at **approval**, which is the single path from a candidate to a
task, and it withholds only the AUTOMATIC approval. The candidate still appears
in the batch; a person may still tick it by naming it with a reason, which is
recorded. The signal survives and the money loop does not.

Identity is `(title, repo)` — candidates carry no stable key across batches,
deliberately, because a batch two weeks old is a new batch. Both task columns
count: a candidate produces a spec task and later a work task, and either
failing is a failure of that candidate.

Built as `022_repeat_failure_stop.sql` (`candidate_prior_failures`) and the
`REPEAT_FAILURE_STOP` guard in `console/approve.py`. **It applies to the human
surface today and to auto-approval in §6.1 tomorrow, because both go through
`approve_batch`.**

**This is the only unbounded loop I can find in the system.**

---

## 6. Auto-merge and auto-deploy

**6.1 Auto-merge** on: preflight clean, re-verification green, boundary clean,
the new test present and bitten. Everything else refuses, and refusing records
nothing — the existing behaviour.

**6.2 Auto-deploy is a timer, and it is the most conditional thing here.** It
deploys only when ALL of:

- the merge was clean and pushed;
- the mutation check bit;
- `drift-check.sh` was green BEFORE it started — deploying onto an already
  drifted production compounds two problems;
- **no migration is in the diff.** `api/alembic/**` and
  `api/analytics/migrations/**` are floored, so an auto-task cannot write one.
  If a spec needs a migration, that is a task a person runs. This is not a
  safety margin, it is a hard exclusion: `deploy.sh` migrates before the code
  swap, and an unattended migration is the one action here that git does not
  make reversible.

---

## 7. What goes back, and when

Written now because a temporary posture with no written end becomes the
permanent one.

The trigger is **Metorik parity on analytics reached, or the first customer,
whichever is first.** Then:

- auto-deploy off; deploys become a person running `deploy.sh`;
- auto-merge off; Accept returns to the console;
- the pool ceiling returns to a number chosen for a product with customers;
- `api/app.py` may return to `writable_paths` — **but the email floor does
  not come off.** It was correct before this posture and stays correct after.
- §3.2's mutation check **stays**. It is the only part of this spec that is
  better than what preceded it, and it should never have needed an autonomy
  push to arrive.

---

## 8. Pace, and what it costs

Measured over 15 settled runs, £39.99 total:

| | |
|---|---|
| dd_api code task | £2.31 – £3.00 (task 28: £2.31; task 26: £2.50) |
| draft_spec task | £1.15 – £1.93 |
| average, all runs | £2.67 |

A full chain — candidate → draft spec → code task — is **~£4.20**.

| pace | £/night | £/month | verdict |
|---|---|---|---|
| **1 chain/night** | **£4.20** | **£126** | **chosen** — 80% of the £158 pool |
| 2 chains/night | £8.40 | £252 | exceeds the pool on day 19 |
| 3 chains/night | £12.60 | £378 | pool gone in 12 days |

**One chain a night.** Three weeks of it working is worth more than double the
spend before it has run unattended once.

Machine time matters as much as money: ~14 minutes of verification per task, on
a box serving production traffic. One chain a night is ~30 minutes of Postgres
and pytest at 02:00. Three would be 90 minutes beside the live API, which is
what `api/CLAUDE.md` was written about after incident 3.

---

## 9. Build order

Each step runs attended for a few nights before the next lands. Nothing after
step 2 runs unattended until 1 and 2 have.

1. **The email floor** (§2) — a refusal, and cheap.
2. **The analytics gate and the mutation check** (§3).
3. **The brief** (§4) — before autonomy, not after, because it is how autonomy
   is watched.
4. **The repropose stop** (§5.2).
5. **Auto-merge** (§6.1).
6. **Auto-deploy** (§6.2).
