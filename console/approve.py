"""Turning ticked candidates into queued draft-spec tasks.

ONE TRANSACTION, AND THE ORDER INSIDE IT IS THE DESIGN
-------------------------------------------------------
A batch approval is four writes that must not be able to disagree:

    1. the decision_log row, with the batch reason
    2. the candidates marked APPROVED, each citing that decision
    3. one draft-spec task per approved candidate
    4. the candidates marked NOT_NOW or REJECTED

If the tasks were created outside the transaction, a failure between 2 and 3
would leave candidates approved with nothing queued -- a state nobody tracks and
nobody would notice, because the page would show it as done.

WHAT THIS DELIBERATELY DOES NOT DO
-----------------------------------
It does not create a CODE task. A tick produces a draft spec, which a human
reviews through the accept/reject flow that already exists. specs/approval-
surface.md §3: two hand-written specs contained factual errors about file paths,
and the check in contracts/checks/draft_spec_shape.py is what turns that class
into something a task cannot pass with.

It also does not choose a work_type. The draft spec chooses it, and the check
verifies the choice names a real contract -- because `candidates` has no
work_type column, deliberately.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from . import db


class ApprovalRefused(Exception):
    """The batch was not written. The message is shown to the reviewer."""


def _draft_spec_contract() -> tuple[Dict[str, Any], float, int, str]:
    """The stored contract for a draft-spec task, and the limits beside it.

    Read from contracts/draft-spec.yaml at approval time rather than embedded,
    so a contract change does not need a code change -- and frozen into the
    task row, because the database freezes a contract once the task is RUNNING
    and the agent must not be able to change what was asked.

    max_cost_gbp and timeout_seconds come from the same file rather than being
    written here as literals. They used to be 2.00 and 1800 inline, which
    happened to match the contract and would have stopped matching it silently
    -- and max_cost_gbp is no longer only a per-task cap. Since 014 it is the
    number the monthly ceiling reserves against, so a copy that drifts low
    would let a batch through against a pool it cannot actually afford.

    base_branch comes from the contract for the same reason and a sharper one.
    It was the literal 'track-2-foundation' in the INSERT below. A task's base
    branch is IMMUTABLE once the row exists -- contracts/candidate-producer.yaml
    says so where it records the trunk -- so the repair for a wrong one is
    abandoning the task, not editing it. The literal and the trunk happen to be
    the same commit today; the morning master moves and the literal does not,
    every task queued here branches from a stale base and nothing reports it.
    tests/revert_guards.py already guards this shape elsewhere: a constant
    answers wrongly.
    """
    import yaml
    from . import config
    path = config.PROJECT_ROOT / "contracts" / "draft-spec.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    contract = {
        "work_type": data["work_type"],
        "writable_paths": data["writable_paths"],
        "protected_paths": data["protected_paths"],
        "verification": data["verification"],
        "worktree_links": data.get("worktree_links", {}),
        "max_diff_lines": data["max_diff_lines"],
    }
    return (contract, float(data["max_cost_gbp"]),
            int(data["timeout_seconds"]), str(data["base_branch"]))


def _spec_md(cand: Dict[str, Any]) -> str:
    """What the draft-spec task is asked to do.

    The candidate's own rationale and evidence go in verbatim. The agent is told
    what the check will require, because a check the agent cannot see is a gate
    it fails by accident rather than a standard it writes to.
    """
    ev = json.dumps(cand.get("evidence") or [], indent=2)
    paths = "\n".join(f"  - `{p}`" for p in (cand.get("suggested_paths") or [])) \
        or "  _(the finding named none; establish them by reading the tree)_"
    return f"""# Write a draft spec: {cand['title']}

You are writing a SPEC for a later task, not the change itself. Produce one
markdown file under `drafts/`.

## The candidate

**{cand['title']}**

{cand['rationale']}

Repository: `{cand['repo']}`
Objective: `{cand.get('objective_ref') or 'none stated'}`

## Evidence the finding cited

```json
{ev}
```

## Paths the finding suggested — advisory, not authoritative

{paths}

The suggested paths above came from a findings document and may be wrong.

**The runner lists the real tree for you and names the file in a section
below.** Read that listing; it is the authority, and it is generated fresh for
this run.

This prompt used to promise a read-only checkout at
`reference/{cand['repo']}`. **That was not true during the run** — the runner
creates those links after the agent exits, deliberately, so the agent cannot
write through them. Three specs died on paths written from memory, and one of
them said so in its own words: *"the reference checkout named in the task was
not present in this worktree ... no path or line number below was read from
the tree for this spec."* It was failed for the consequence of a capability it
had been promised and did not have.

## What your spec must contain

A fenced ```fleet-spec block with `work_type`, `repo`, `title` and
`writable_paths`, followed by prose describing the change.

**You choose the `work_type`**, and it must name a contract that exists in
`contracts/`. Nothing upstream decided this: a candidate carries no work_type,
because a producer reading a findings document cannot know whether an item is a
code change or an investigation. That determination is your job.

## What the check will refuse

`contracts/checks/draft_spec_shape.py` runs on your diff and fails if:

- there is no `fleet-spec` block, or it lacks a required field
- `work_type` names no contract, or names one contracted for another repo
- a declared writable path does not resolve in the repo, and neither does its
  parent directory
- a declared writable path is protected by the contract you named
- a path cited in prose does not resolve AND its directory does not either —
  naming a file you intend to CREATE is fine, in a directory that exists
- a path cited in prose is an abbreviation of a real one (it will tell you
  which)
- the diff contains anything other than markdown

## Run the check before you finish

    /home/ubuntu/fleet/contracts/checks/spec_selfcheck.sh

That is the same command the runner will run on your diff, so what it says is
what you will be judged on. **You may run it three times.** Use one to see
where you are, fix what it names, and run it again to confirm.

The cap is deliberate and it is not a budget to spend. If the check still fails
on the third run, the remaining problem is one to think about rather than to
iterate against — read the tree and establish what the path IS, rather than
trying another spelling. Every invocation and its verdict is recorded on the
run, so a sequence of different failing paths is visible to whoever reviews
this.

**The path checks are why this step exists.** Two hand-written specs contained
wrong file paths and would have sent builds at directories that do not exist.
Read the tree; do not write paths from memory.
"""


#: A candidate that has produced this many FAILED tasks is not approved
#: without somebody saying why. specs/unattended-operation.md §5.2 as
#: corrected in 022: two is where a repeat stops being bad luck.
REPEAT_FAILURE_STOP = 2


#: How a batch decision was arrived at. 026's vocabulary and console/decide.py's,
#: and the same word for the same reason: "unattended" says NOBODY WAS WATCHING,
#: where "auto" would only say a machine did it.
DECIDED_VIA = ("console", "by_hand", "unattended")


def approve_batch(*, reason: str, approve_ids: List[int],
                  reject: Dict[int, str], not_now_ids: List[int],
                  decided_by: str | None,
                  repeat_overrides: Dict[int, str] | None = None,
                  decided_via: str = "console",
                  mechanics: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Record one batch decision and queue its draft-spec tasks.

    Raises ApprovalRefused with a reviewer-facing message rather than letting a
    constraint violation reach the page as a 500 -- the ceilings are a designed
    answer, not an error.

    `decided_via` and `mechanics` default to the console's values, so every
    existing caller is unchanged. console/autoapprove.py is the only thing that
    passes anything else, and it ADDS NO CEILING OF ITS OWN AND BYPASSES NONE:
    the repeat-failure stop, the batch cap, the queue depth, the credit check
    and the one-transaction ordering are all already here, and were put here on
    the grounds that auto-approval would have to meet them.
    """
    if not reason or not reason.strip():
        raise ApprovalRefused(
            "A batch needs a reason, and it is about the SELECTION rather than "
            "each row. Ten paraphrases of 'yes' would satisfy the NOT NULL "
            "while emptying the column.")

    if decided_via not in DECIDED_VIA:
        raise ApprovalRefused(
            f"{decided_via!r} is not a way a decision can be arrived at; "
            f"known: {', '.join(DECIDED_VIA)}")

    if decided_via == "unattended":
        # 026's constraint refuses this at the database too. It is checked here
        # as well so the refusal is a sentence rather than a check violation --
        # and because the caller that would get this wrong is a cron job whose
        # stderr somebody reads in the morning.
        if not mechanics:
            raise ApprovalRefused(
                "an unattended approval must carry its mechanics. `reason` is "
                "NOT NULL on every decision_log row, so a machine writing prose "
                "into it with nothing to check the prose against is exactly how "
                "010's UNRECORDED problem returns by a new route.")
        if repeat_overrides:
            # An override is a person saying "it is different this time". There
            # is no such sentence when nobody is there, and a machine that can
            # write one has removed the only ceiling that stops it buying the
            # same failure at the same price, repeatedly.
            raise ApprovalRefused(
                "an unattended approval cannot carry repeat_overrides. An "
                "override is a person saying it is different this time; with "
                "nobody there, the repeat stop is the answer and it stands.")
    elif mechanics:
        raise ApprovalRefused(
            f"a {decided_via!r} decision cannot carry mechanics: a person's "
            f"reasons belong in `reason`, and a mechanics object on a row a "
            f"person decided would read as a machine having decided it.")

    # db.writer(), NOT db.connect(). The latter is the read-only session the
    # render path uses, and pointing this at it would fail at the first INSERT
    # -- the console keeps the two apart deliberately so a GET handler can
    # never acquire a credential that writes.
    with db.writer() as conn, conn.transaction():
        # db.writer() uses row_factory=dict_row, so every fetchone() here is a
        # DICT and must be read by name. Unpacking one as a tuple binds the
        # column names instead of the values, which fails later and elsewhere
        # as a type error rather than at the line that got it wrong.
        caps = conn.execute(
            "SELECT fleet_max_queued_tasks() AS max_queued,"
            " fleet_max_approval_batch() AS max_batch,"
            " (SELECT count(*) FROM tasks WHERE status='QUEUED') AS queued_now"
        ).fetchone()
        max_queued = caps["max_queued"]
        max_batch = caps["max_batch"]
        queued_now = caps["queued_now"]

        # THE REPEAT-FAILURE STOP. 022, and it is the ceiling that matters
        # once nothing is watching.
        #
        # max_attempts is 1, so a task does not retry itself. The loop is one
        # level up: the producer is FORBIDDEN to deduplicate against previous
        # batches -- specs/approval-surface.md §7, "a candidate that reappears
        # is a signal" -- so the same candidate returns every time the producer
        # runs, and each approval buys another failing run at the same price.
        # Over a quarter that is the same wrong idea, six times, each one
        # looking like a fresh proposal.
        #
        # It withholds APPROVAL, never the candidate. The row still appears in
        # the batch and a person may still tick it by naming it in
        # repeat_overrides with a reason -- which is recorded, so "we did this
        # anyway" is a sentence somebody wrote rather than a silence.
        overrides = repeat_overrides or {}
        if approve_ids:
            repeats = conn.execute(
                "SELECT c.id, c.title, c.repo,"
                " candidate_prior_failures(c.title, c.repo) AS fails"
                " FROM candidates c WHERE c.id = ANY(%s)",
                (list(approve_ids),)).fetchall()
            blocked = [r for r in repeats
                       if r["fails"] >= REPEAT_FAILURE_STOP
                       and not (overrides.get(r["id"]) or "").strip()]
            if blocked:
                lines = "; ".join(
                    f"{r['title']!r} has already produced {r['fails']} failed "
                    f"task(s)" for r in blocked)
                raise ApprovalRefused(
                    f"{len(blocked)} candidate(s) have failed "
                    f"{REPEAT_FAILURE_STOP} times or more and are not approved "
                    f"automatically: {lines}. The candidate keeps reappearing "
                    f"because the producer is not allowed to hide it, which is "
                    f"working as intended -- but approving it again buys the "
                    f"same failure at the same price. Say why it is different "
                    f"this time, or leave it.")

        if len(approve_ids) > max_batch:
            raise ApprovalRefused(
                f"{len(approve_ids)} ticked, and the cap is {max_batch}. The cap "
                "keeps one batch reason honest: a larger batch needs more than "
                "one reason, not a bigger cap.")
        if queued_now + len(approve_ids) > max_queued:
            raise ApprovalRefused(
                f"{queued_now} task(s) are already QUEUED and the depth is "
                f"{max_queued}, so {len(approve_ids)} more cannot be queued. "
                "Draft-spec tasks and the code tasks they produce share this "
                "queue deliberately. Let some drain, or raise the depth in a "
                "migration.")

        contract, task_max_cost, task_timeout, base_branch = _draft_spec_contract()

        # THE THIRD CEILING (spec section 6, ceiling 2; built in 014).
        #
        # Checked here AND enforced by a trigger on `tasks`, the same pairing
        # the queue depth already has. The trigger is what makes it a ceiling
        # rather than a convention -- it fires for any caller, including the
        # direct inserts that exist because this function only makes draft-spec
        # tasks. This pre-check is what makes the refusal a sentence the
        # reviewer can act on instead of a constraint violation arriving as a
        # 500.
        #
        # Reserved at max_cost_gbp, NOT at the candidate's est_cost_gbp, which
        # is why est_cost_gbp is still only displayed. Two of the eight settled
        # runs on this host landed at exactly their max_cost_gbp, because
        # settle_model_budget() refuses an actual above the reservation and
        # settles at the bound. An estimate calibrated against figures that are
        # themselves clipped at the cap under-counts precisely the runs worth
        # counting.
        if approve_ids:
            credit = conn.execute("SELECT * FROM fleet_month_credit()").fetchone()
            if credit["status"] == "UNCOMPUTED":
                raise ApprovalRefused(
                    "The monthly credit position is unknown, so nothing can be "
                    "approved. " + credit["uncomputed_reason"] + " This refuses "
                    "rather than assuming, because the pool does not roll over "
                    "and a batch approved against a number nobody read is the "
                    "one mistake this ceiling exists to prevent.")
            wanted = task_max_cost * len(approve_ids)
            if wanted > credit["remaining_gbp"]:
                raise ApprovalRefused(
                    f"£{credit['remaining_gbp']:.2f} remains of the "
                    f"£{credit['pool_gbp']:.2f} pool for "
                    f"{credit['period_month']:%Y-%m} "
                    f"(£{credit['committed_gbp']:.2f} already committed, "
                    f"counting queued and running tasks at what they may "
                    f"spend). {len(approve_ids)} draft-spec task(s) at "
                    f"£{task_max_cost:.2f} each would need £{wanted:.2f}. "
                    "Tick fewer, let some drain, or record a new reading if "
                    "the pool has actually changed — the figure was read at "
                    f"{credit['read_at']:%Y-%m-%d %H:%M} from "
                    f"{credit['source']}.")

        decision_id = None

        if approve_ids:
            conn.execute(
                # decided_by falls back to `current_user` -- the identity that
                # is WRITING this row -- when the caller passes None. That is
                # what the unattended path passes, so the login is recorded by
                # construction rather than typed: console/app.py defaults this
                # field to "eamonn", and a machine inheriting that default would
                # produce a log that reads as a person's decision, which is the
                # one thing this record exists to prevent.
                "INSERT INTO decision_log (product, subject, decision, reason,"
                " decided_by, evidence, decided_via, mechanics)"
                " VALUES (%s,%s,'APPROVED',%s,coalesce(%s, current_user),%s,%s,%s)",
                ("fleet",
                 f"Approve {len(approve_ids)} candidate(s) for draft specs",
                 reason.strip(), decided_by,
                 json.dumps([{"kind": "candidate", "id": i} for i in approve_ids]),
                 decided_via,
                 json.dumps(mechanics) if mechanics else None))
            decision_id = conn.execute(
                "SELECT currval('decision_log_id_seq') AS id").fetchone()["id"]

        queued = []
        for cid in approve_ids:
            c = conn.execute(
                "SELECT id, title, rationale, repo, objective_ref, evidence,"
                " suggested_paths FROM candidates WHERE id=%s AND disposition IN"
                " ('PENDING','NOT_NOW')", (cid,)).fetchone()
            if c is None:
                raise ApprovalRefused(
                    f"candidate {cid} is not open for decision; the page may be "
                    "stale. Reload and tick again.")
            conn.execute(
                "INSERT INTO tasks (title, spec_md, repo, base_branch,"
                " acceptance_contract, max_cost_gbp, timeout_seconds,"
                " objective_ref) VALUES (%s,%s,'fleet',%s,"
                " %s,%s,%s,%s)",
                (f"Draft spec: {c['title']}"[:200], _spec_md(c),
                 base_branch, json.dumps(contract), task_max_cost,
                 task_timeout, c.get("objective_ref")))
            task_id = conn.execute(
                "SELECT currval('tasks_id_seq') AS id").fetchone()["id"]
            conn.execute(
                "UPDATE candidates SET disposition='APPROVED',"
                " approval_decision_id=%s, spec_task_id=%s, decided_at=now()"
                " WHERE id=%s", (decision_id, task_id, cid))
            queued.append(task_id)

        for cid, why in reject.items():
            if not why or not why.strip():
                raise ApprovalRefused(
                    f"candidate {cid} was rejected with no reason. Rejections "
                    "are the informative half; this is the one place a sentence "
                    "is the point.")
            conn.execute(
                "UPDATE candidates SET disposition='REJECTED',"
                " disposition_reason=%s, decided_at=now() WHERE id=%s",
                (why.strip(), cid))

        # NOT_NOW is not a rejection and is not discarded. It keeps its original
        # batch_id so the number of times it has been passed over stays visible.
        for cid in not_now_ids:
            conn.execute(
                "UPDATE candidates SET disposition='NOT_NOW', decided_at=now()"
                " WHERE id=%s AND disposition='PENDING'", (cid,))

    return {"decision_id": decision_id, "queued_task_ids": queued,
            "rejected": len(reject), "not_now": len(not_now_ids)}
