# Fleet Task Runner — spec

The problem this solves is not "an agent that writes features". It is that a
solo operator spends more time driving a session than scoping the work. You
write specs when you have context loaded; the runner executes them when you
don't; you review in one batch instead of five sittings.

**It never merges and never deploys.** Every task ends as a branch with tests
and a summary. The merge decision stays with you.

---

## Why this and not the autonomous agent

The V1 design's agent takes a *detected issue* to a verified fix — narrow,
because tests can score it. Feature work has no such arbiter: nothing fires,
and "is this the right feature" is judgement.

So the runner doesn't try to be verified in that sense. Its verification is
the test suite plus your review, and its safety is that a bad branch costs
nothing because it never lands. DD having no customers is what makes this the
right first environment, not a reason to skip the boundaries.

The pieces already built carry over: `runs`, `run_steps`, acceptance contracts,
the rule that an agent cannot edit what judges it, budget reservation.

---

## Schema — `003_tasks.sql` on the `fleet` database

```
tasks
  id, queue, title, spec_md, repo, base_branch,
  acceptance_contract, status, priority, objective_ref,
  max_cost_gbp, created_at, claimed_at, completed_at,
  branch_name, attempts, max_attempts
```

`status`: QUEUED → RUNNING → READY_FOR_REVIEW | FAILED | ABANDONED
Then, from review: MERGED | REJECTED | REWORK.

A REWORK task returns to QUEUED with your feedback appended to `spec_md`, so
the next attempt sees why the last one was wrong. That is the only learning
signal available here, and it costs nothing to capture.

Reuse `runs` and `run_steps` for execution history rather than inventing a
parallel log. One task maps to one run; the agent's steps are
`PATCH_PROPOSED`, `VERIFICATION_RUN`, and so on, exactly as designed.

Claiming uses `FOR UPDATE SKIP LOCKED` — same pattern as `scheduled_checks`,
so two runners can never take the same task.

---

## Acceptance contract, per task

```yaml
work_type: dd_feature
repo: deadly-digital-platform
base_branch: main
writable_paths:
  - api/app.py
  - api/services/**
  - platform/app/**
  - platform/components/**
protected_paths:
  - api/tests/**
  - alembic/**
  - docker-compose.yml
  - dd/detectors/**
verification:
  - pytest api/tests/
  - ruff check api/
max_diff_lines: 800
max_cost_gbp: 3.00
```

Tests are protected. An agent that can edit the suite that judges it can pass
anything, and that rule cost several rounds to arrive at — it applies here
unchanged.

Migrations are protected too. A schema change is a separate decision from a
feature, and folding one into the other is how a review misses it.

---

## The runner

A systemd timer, hourly, on `dd-prod`. Each tick:

1. Claim one QUEUED task by priority (SKIP LOCKED).
2. `git worktree add` a fresh branch off `base_branch` (the default branch is `main`, not `master`) — worktrees, not clones,
   so the repo isn't duplicated and the working tree is never touched.
3. Reserve budget via `reserve_model_budget`, using the existing functions.
4. Invoke Claude CLI headless in that worktree with the spec and contract.
5. Run the contract's verification commands.
6. Derive the diff **itself** and reject if it touched protected paths — never
   trust the agent's report of what it changed.
7. Record steps, settle budget, push the branch, set READY_FOR_REVIEW.
8. On failure: record it, increment attempts, requeue below `max_attempts`,
   otherwise FAILED.

One task per tick. Serial, not parallel — you review in batches, so there is no
value in racing, and serial keeps cost and blast radius obvious.

Hard timeout per task. A stuck agent burning budget in a loop is the failure
mode the research flagged, and a wall-clock cap is the cheap guard.

---

## Writing tasks

```bash
fleet task add --title "Refund reporting" --spec specs/refunds.md \
  --objective dd-feature-parity --max-cost 3.00
fleet task list
fleet review          # branches ready, diffstat, test results, cost
fleet task rework 7 --note "wrong table; use analytics_N not public"
```

The spec file is the input that decides whether this works. A vague spec
produces a branch you throw away and the week is lost. Each should state what
the feature does, which Metorik behaviour it matches, what the user sees, and
what "done" means concretely.

---

## What to watch, and when to stop

Track from the first week, because these decide whether it continues:

- **merge rate** — branches merged as a fraction of READY_FOR_REVIEW
- **rework rate** — and whether reworks converge or loop
- **your minutes per merged branch**, against doing it yourself in a session
- **£ per merged branch**

The stopping rule, set now while it is cheap to accept: if merge rate is under
about a third after ten tasks, the specs are the problem, not the runner. Fix
the specs or stop. A runner producing branches you reject is slower than doing
the work yourself, and it will not feel that way while it is happening.

---

## Build order

1. `003_tasks.sql` plus the CLI: add, list, claim, status.
2. The runner against **one trivial task** — a docstring fix — to prove the
   worktree, contract, verification and branch mechanics end to end.
3. A real DD feature from the gap list.
4. Timer on, once three tasks have gone through by hand.

Step 2 matters. Prove the plumbing on something where a wrong answer is
obvious before pointing it at work you cannot check at a glance.

---

## Deliberately not in V1

No merging or deploying. No parallel tasks. No schema or migration changes by
the agent. No cross-repo tasks. No self-generated tasks — the queue is written
by you, from the gap list, until there is evidence the merge rate justifies
more.
