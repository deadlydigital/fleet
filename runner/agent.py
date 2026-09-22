"""Invoking the coding agent, and stopping it.

Two caps are enforced here, by the runner, and neither by asking the agent to
mind them. A stuck agent burning budget in a loop is the failure mode this
guards, and an agent that is stuck is by definition not going to notice that
it is.

  the wall clock       the runner's own deadline, against communicate().
  the output ceiling   tasks.max_output_tokens, counted by the runner from
                       the transcript the CLI is writing.

THE SECOND CAP WAS --max-budget-usd UNTIL 22 Sep 2026, AND IT WAS A PHANTOM.
It was derived from `max_cost_gbp` at a stated exchange rate, and the figure
at the end of that chain describes no account: these runs authenticate against
a Claude Max subscription with usage credits off and a zero balance, so the
money was notional list price all the way down (048). A notional number that
DELETES WORK is worse than one that merely gets recorded -- decision 102 is
task 118's GBP 6.00, and task 140 on 21 Sep was stopped at GBP 2.50 having
produced 35,441 output tokens, a run of thoroughly ordinary size. Nothing was
saved by stopping it, because nothing was being spent.

What is actually metered is output tokens against a window that resets on
Sunday, which is 049's finding and the unit the ledger there already counts
in. So the backstop is now denominated in the same unit as the constraint,
and the runner enforces it itself rather than delegating it.

IT IS A BACKSTOP AND NOT A BUDGET, which is the point 049 makes at length and
the property the old cap did not have. The default ceiling is 100,000 output
tokens, 1.37x the largest run on record; a ceiling at the p90 this module also
tracks would have destroyed 5 verified runs to stop 9 failing ones. If this
fires, something is wrong with the run, not merely large.

What the ceiling is NOT is exact. The count comes from the session transcript,
which is written as the run goes, and it is read on a poll: overshoot is
bounded by one poll interval plus whatever a turn writes after the last flush,
not by zero. That is the same shape of inexactness the old cap had -- it gated
between turns -- and it is fine for a runaway bound.

The kill is against the process group, not the child: the CLI spawns its own
children, and terminating only the process the runner can see leaves them
running with the budget already spent. That applies to an agent that exited on
its own as much as to one the runner killed, so the group is reaped either
way.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TOOLS = ("Read", "Edit", "Write", "Grep", "Glob")

# Overridable so the timeout can be tested against a process that is
# guaranteed to hang, and so production can pin an absolute path rather than
# whatever `claude` resolves to on PATH.
CLAUDE_BIN = os.environ.get("FLEET_CLAUDE_BIN", "claude")

REPORT_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


@dataclass
class AgentResult:
    exit_code: int
    timed_out: bool
    duration_ms: int
    #: Stopped by the runner for crossing the task's output ceiling. Its own
    #: field and not a generic non-zero exit, because a run stopped for being
    #: a runaway and a run stopped by a crash need different answers from
    #: whoever reads the queue.
    output_capped: bool = False
    #: Output tokens the watcher counted while the run was in flight, or None
    #: if it never got a reading. AN OBSERVATION, and the only one available
    #: for a capped run: the CLI writes its usage figures to stdout when it
    #: exits normally, and a run the runner killed does not exit normally.
    output_tokens: int | None = None
    #: Why the ceiling could not be enforced on this run, or None. The watcher
    #: swallows its own failures -- it must, it is a thread beside a task --
    #: so the silence has to be reportable or an unenforced cap looks exactly
    #: like a cap that did not need to fire.
    watcher_failed: str | None = None
    #: Why the run produced no evidence about the task, or None if it did.
    #: A STRING rather than a bool so the reason reaches the row: "could not
    #: run" is only useful to a reader who is told what stopped it.
    could_not_run: str | None = None
    #: What the agent said when it declined to change anything, or None.
    #: Carried in the SAME fenced json block `changed_files` uses -- a second
    #: convention would be a second thing for a spec author to get wrong.
    refused: str | None = None
    text: str = ""
    cost_usd: float | None = None
    num_turns: int | None = None
    session_id: str | None = None
    reported_paths: list[str] | None = None
    stderr: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (self.exit_code == 0 and not self.timed_out
                and not self.output_capped
                and self.could_not_run is None)



def _creatable_note(contract: dict) -> str:
    """The one exception to the protected list, stated where it is read.

    ADD, never modify. The exception is granted by runner.boundary on the diff
    STATUS git reports, so an agent that edits an existing file under one of
    these globs is refused exactly as before.
    """
    globs = list(contract.get("creatable_paths") or [])
    if not globs:
        return ""
    listed = "\n".join(f"  - {g}" for g in globs)
    return f"""
## One exception, and it is an obligation rather than a permission

You MUST ADD exactly one new file matching one of these:

{listed}

That is a test, and it is the only thing in this run that can show the new
behaviour WORKS rather than that nothing broke. The suite passing proves the
second; only a test that fails without your change proves the first, and the
gate runs your test against the tree as it was before you touched it and
refuses the branch if it passes there.

So it must assert the behaviour the spec asked for, specifically enough to
fail if that behaviour is absent. A test that would pass against either tree
fails this run.

ADD, never modify. Creating a file here is permitted; editing any file that
already exists under these paths is refused exactly as the protected list
says. Add ONE file, not several -- each extra is another thing that has to be
shown to bite, and the gate refuses a change that adds more than one.
"""


def _paired_note(contract: dict) -> str:
    """Files that must land together, with the contract's own reason.

    The `why` is printed rather than summarised: it is the sentence somebody
    wrote about this specific pair, and an agent deciding what "together"
    means needs the reason, not the rule.
    """
    groups = list(contract.get("paired_paths") or [])
    if not groups:
        return ""
    blocks = []
    for group in groups:
        paths = "\n".join(f"  - {p}" for p in (group.get("paths") or []))
        why = (group.get("why") or "").strip()
        blocks.append(f"{paths}\n\n  Why: {why}")
    body = "\n\n".join(blocks)
    return f"""
## These change together, or not at all

{body}

A run that changes some of a group and not the rest is REFUSED, however good
the part it did. This is not a style rule: half of such a change is usually
worse than none of it, which is what the reason above says.

If you conclude the whole group cannot be changed, change none of it and say
why. That is a real answer. Landing the easy half is not.
"""


CITE_CHECK = "spec_requirements_cited.py"


def _cite_note(task: dict, contract: dict) -> str:
    """The requirement ids, listed, when the contract runs the citation gate.

    THE IDS ARE PRINTED RATHER THAN LEFT TO BE PARSED, for the reason
    `_paired_note` prints the pairs and `paths_pack` prints the tree: three
    specs failed on paths and every failing one had a real sibling in the
    same directory, because recall is not knowledge. An agent asked to
    "cite every numbered requirement" will miss one, and the one it misses
    costs a whole run.

    The list comes from `console.requirements.parse` -- the same parser the
    check enforces with and the same one the console renders. If the prompt
    listed a different set from the gate, the agent would satisfy the prompt
    and fail the gate.

    Keyed on the contract actually running the check, so a contract without
    it gets no paragraph and no annotation burden.
    """
    if not any(CITE_CHECK in c for c in (contract.get("verification") or [])):
        return ""
    import sys
    sys.path.insert(0, "/home/ubuntu/fleet")
    from console import requirements
    reqs = requirements.parse(task.get("spec_md"))
    if not reqs:
        return ""
    # LEAVES ONLY, because that is what the check asks for: it satisfies a
    # parent from any cited child, so `### 2. The page sends them` needs no
    # token of its own when 2.1 and 2.5 carry theirs. Listing it anyway would
    # ask for a citation the gate does not want, and a prompt that asks for
    # more than the gate enforces teaches the agent that the list is
    # approximate.
    ids = [q.id for q in reqs]
    leaves = [q for q in reqs
              if not any(r.startswith(q.id + ".") for r in ids)]
    listed = "\n".join(f"  - `spec:{q.id}`  {q.title}" for q in leaves)
    return f"""
## Cite every numbered requirement

This spec numbers {len(leaves)} requirement(s). For each one, put its token on
a line THIS CHANGE ADDS -- in a comment, a test name, or a docstring:

{listed}

Example: `// spec:2.5 clicking a Payment cell sets the filter`.

WHY, STATED PLAINLY, BECAUSE THE RULE IS ONLY WORTH FOLLOWING IF YOU KNOW
WHAT IT IS FOR. Nothing else in this run reads the spec. `tsc` proves it
compiles, the suite proves nothing broke, and the added-test gate proves one
test discriminates -- none of them can tell that a numbered requirement was
skipped. Task 53 shipped its §2.5 unbuilt with all four green.

So this does not check that you implemented anything. It makes each
requirement a claim you signed. **Do not cite a requirement you did not
implement.** If one is genuinely out of scope, leave it uncited and say so
in your reply: a refused branch that explains itself is useful, and a token
written over work that was not done is a lie rather than an oversight.
"""


def build_prompt(task: dict, contract: dict, *, paths_file=None) -> str:
    """The spec, plus the boundary stated plainly.

    The contract is in the prompt so the agent can succeed, not so the runner
    can rely on it having read it. Everything here is re-derived from git
    afterwards; this text buys a better first attempt, nothing more.

    `paths_file` is named here rather than in the spec text because it is
    generated per run and its location is not knowable when the task is
    written. The spec used to hardcode `reference/PATHS.md`, which was a
    guess about a file the runner had not yet decided where to put.

    CREATABLE AND PAIRED PATHS ARE STATED BECAUSE OMITTING THEM MADE THE
    PROMPT WRONG, not merely incomplete.

    The protected list is introduced with "must not edit under any
    circumstances", and `platform/__tests__/**` and `api/tests/**` are on it.
    A contract with `creatable_paths` and `new_test_bites.sh` in its
    verification requires the agent to ADD a file inside exactly that tree --
    so an agent that believed the sentence above could not pass the gate, and
    one that passed it did so by disregarding the only line in the prompt
    written in absolute terms. Neither is a thing to build a fleet on.

    `paired_paths` is the same argument with a worse failure: an agent that
    does not know two files must move together will land one of them, and the
    check will refuse a branch that is otherwise good. Telling it after the
    fact costs a whole run.

    No decision rests on this text. Everything is re-derived from git and
    judged by runner.boundary and the contract's own checks.
    """
    writable = "\n".join(f"  - {p}" for p in contract["writable_paths"])
    protected = "\n".join(f"  - {p}" for p in contract["protected_paths"])
    creatable_note = _creatable_note(contract)
    paired_note = _paired_note(contract)
    size_note = _size_note(contract)
    cite_note = _cite_note(task, contract)
    paths_note = ""
    if paths_file:
        paths_note = f"""

## The real paths, listed for this run

`{paths_file}` lists every file in the read-only trees this task may see,
generated by the runner before you started. It is current for this run and
exists nowhere else.

**Cite paths IN FULL from the repository root.** `routes/orders.py` is not a
path; `api/analytics/routes/orders.py` is.
"""
    return f"""{task['spec_md']}{paths_note}

---

## The boundary for this task

You may edit only these paths:

{writable}

You must not edit these paths under any circumstances:

{protected}

The test suite and the migrations are on that second list. Do not edit tests
to make them pass, and do not change any migration. If the task appears to
require editing a protected path, stop and say so instead: a branch that
explains why it could not be done is useful, and one that quietly widened its
own boundary is not.
{creatable_note}{paired_note}{cite_note}
{size_note}
Do not commit anything. Do not create branches. Do not run git.

When you are finished, end your reply with a JSON block listing every file
you changed, relative to the repository root:

```json
{{"changed_files": ["path/one.py", "path/two.tsx"]}}
```

That list is recorded but is not what decides whether the branch is accepted.
The runner derives the real diff from git and judges that.
"""


#: Legacy only: the target as a fraction of the ceiling.
#:
#: `test_diff_target` is a contract field now, and this is what a contract
#: FROZEN BEFORE 12 Sep 2026 falls back to. Task 69's own row was frozen
#: without the field while all of this was being worked out, so the fallback
#: is not hypothetical -- it is the path that row takes.
#:
#: It cannot be the main route any more, and the reason is the same change
#: that made it legacy: max_test_diff_lines is no longer a calibrated ceiling
#: but a runaway bound sitting far above any plausible test, so a fraction of
#: it is a fraction of a number chosen not to bind. 0.75 of 1200 is 900, which
#: would anchor the agent at three times the figure anyone wants.
TEST_TARGET_FRACTION = 0.75


def test_target(contract: dict) -> int:
    """The test figure the PROMPT carries. Not the figure the gate enforces.

    THE NUMBER IN THE PROMPT IS AN ANCHOR, NOT A CONSTRAINT, and that is
    measured rather than supposed. Task 69 ran the same spec off the same base
    three times, with nothing different between them but this sentence:

        told 300  ->  wrote 377   ceiling 300, refused
        told 600  ->  wrote 606   ceiling 600, refused
        told 300  ->  wrote 439   ceiling 400, refused -- ALL CHECKS PASSED

    and task 67 landed at 298 against 300. An agent with no meter, keeping a
    rough hand tally, writes toward the figure it is given; it does not hit it
    precisely, and the same target produced 377 and 439 on two runs. So the
    target SHAPES the test and cannot BOUND it, and the two jobs belong to two
    numbers: this one is told and exceedable, max_test_diff_lines is enforced,
    never told, and set far enough away that overshoot is not a dead run.
    """
    target = contract.get("test_diff_target")
    if target:
        return int(target)
    return int(int(contract.get("max_test_diff_lines") or 0)
               * TEST_TARGET_FRACTION)


def _size_note(contract: dict) -> str:
    """The size budget, in the units the runner actually counts.

    TWO NUMBERS, BECAUSE A SINGLE ONE PENALISED THE TEST. Measured 11 Sep
    2026: the two dd_api tasks refused on size were 494 = 300 production + 194
    test and 459 = 272 + 187. Both were ordinary changes whose mandated test
    pushed the total over a limit set before tests were mandated. An agent
    rationing one budget across both thins the test, and the test is the one
    artefact new_test_bites.sh exists to make mean something.

    THE TEST FIGURE HERE IS A TARGET AND NOT A CEILING, and there no longer is
    a ceiling worth naming: max_test_diff_lines is a runaway bound an order of
    magnitude away, and the contract's `test_diff_target` is what this prints.
    See test_target() for the three runs that established the difference. The
    agent is told the target and not the bound, deliberately -- naming both
    would put the anchor back on the larger number.

    SAYING "ADDED AND DELETED" IS THE POINT. The runner counts
    `git diff --numstat` added PLUS deleted, so rewriting 200 lines scores 400.
    "Changed lines" read as "lines of change" to anyone who had not read
    boundary.derive, which is everyone the prompt is addressed to.

    The agent has Read/Edit/Write/Grep/Glob and no Bash, and is told not to run
    git, so it cannot measure any of this. These are estimates it is being
    asked to keep, and the wording says so rather than implying a meter.
    """
    limit = contract["max_diff_lines"]
    test_limit = contract.get("max_test_diff_lines")
    counted = ("Lines are counted as added PLUS deleted, so replacing a line "
               "costs two. You cannot run git, so keep a rough tally as you "
               "go rather than checking.")
    if not test_limit:
        return (f"Keep the whole change under {limit} changed lines. {counted}")
    target = test_target(contract)
    return f"""## Two size budgets, and they do not share

Keep the change under {limit} changed lines, NOT counting the test file you
add. {counted}

The test file has its own budget of about {target} lines and does not come out
of the {limit}. Write the test the change deserves: a thorough test is the point
of being allowed to add one, and thinning it to save room buys you nothing
here. {target} is a target rather than a hard edge -- going a little over it is
better than cutting a case that earns its place, and much better than padding
one that does not."""


def parse_refusal(text: str) -> str | None:
    """Why the agent declined to change anything, if it said so.

    THE SAME BLOCK AS `changed_files`, deliberately. The agent already ends a
    run with a fenced json object; a refusal is another key in it rather than
    a second protocol, so a spec that wants one has nothing new to teach.

    DECLARED, NOT INFERRED. The alternative is guessing from the reply -- its
    length, its turn count, whether it "sounds like" a refusal -- and a guess
    here decides whether a task spends an attempt. An agent that refuses
    without saying so in the block is recorded as having changed nothing,
    which is what it did.
    """
    for match in reversed(list(REPORT_RE.finditer(text or ""))):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        reason = payload.get("refused")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()[:500]
    return None


def parse_report(text: str) -> list[str] | None:
    """The agent's account of what it changed, if it gave one."""
    for match in reversed(list(REPORT_RE.finditer(text or ""))):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        files = payload.get("changed_files")
        if isinstance(files, list) and all(isinstance(f, str) for f in files):
            return files
    return None


def invoke(worktree: Path, prompt: str, timeout_seconds: int,
           model: str | None = None,
           allowed_tools: tuple[str, ...] = DEFAULT_TOOLS,
           readable: tuple[Path, ...] = (),
           max_output_tokens: int | None = None) -> AgentResult:
    """Run the agent in the worktree under a hard wall clock and an output
    ceiling.

    `max_output_tokens` is the task's own ceiling, enforced here by counting
    the transcript and killing the group. NOTHING IS PASSED TO THE CLI FOR
    IT: there is no flag that caps output tokens, and there is deliberately no
    longer one passed that caps money. See the module docstring.

    `readable` adds directories the agent may look at -- a research task reads
    the platform checkout. --add-dir grants READ, but it does not make the
    directory read-only, so the runner snapshots every one of them before and
    after: a write there would land outside the worktree's git index entirely
    and the derived diff would show nothing.
    """
    cmd = [
        os.environ.get("FLEET_CLAUDE_BIN", CLAUDE_BIN), "-p", prompt,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--add-dir", str(worktree),
        *[a for d in readable for a in ("--add-dir", str(d))],
        "--allowedTools", *allowed_tools,
    ]
    if model:
        cmd += ["--model", model]

    started = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=str(worktree),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True)

    # start_new_session put the child in a new group it leads, so the group
    # id is its pid. Captured now rather than derived later: after the child
    # is reaped there is no pid left to ask.
    pgid = proc.pid

    # COUNT WHILE IT RUNS, AND STOP IT AT THE CEILING. Daemon so it can never
    # hold the process open, and stopped in the same `finally` that reaps the
    # group.
    #
    # `observed` is written by the watcher thread and read here after it is
    # stopped. A plain dict rather than a lock: the writes are whole-key
    # rebinds of small values, the reader does not run until `watch_stop` is
    # set, and a torn reading of a token count is not worth a mutex.
    observed: dict[str, Any] = {"total": None, "turns": None, "failed": None,
                                "capped": False}

    def _report(total=None, turns=None, failed=None) -> None:
        if total is not None:
            observed["total"], observed["turns"] = total, turns
        if failed is not None:
            observed["failed"] = failed

    def _over_ceiling(total: int, turns: int) -> None:
        # THE KILL IS THE WHOLE POINT and it happens here, from the watcher's
        # own thread, while the main thread is blocked in communicate(). The
        # group, not the child, for the reason the module docstring gives:
        # the CLI's children outlive it and keep producing.
        observed["capped"] = True
        observed["total"], observed["turns"] = total, turns
        _kill_group(pgid, proc)

    watch_stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_output_tokens, daemon=True,
        args=(worktree, time.time(), watch_stop,
              lambda tokens, turns: (on_notable_run(tokens, turns)
                                     if on_notable_run else None)),
        kwargs={"ceiling": max_output_tokens,
                "on_ceiling": _over_ceiling,
                "report": _report})
    watcher.start()

    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(pgid, proc)
        out, err = proc.communicate()
    finally:
        watch_stop.set()
        # Whichever way the agent ended. A CLI that stops itself on its
        # budget, or exits cleanly, can still leave a tool child behind, and
        # a surviving child is spend the reservation no longer bounds.
        _reap_group(pgid)

    duration_ms = int((time.monotonic() - started) * 1000)
    result = AgentResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        duration_ms=duration_ms,
        stderr=(err or "")[-4000:],
    )

    try:
        payload = json.loads(out) if out else {}
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        result.raw = payload
        result.text = payload.get("result") or ""
        result.cost_usd = payload.get("total_cost_usd")
        result.num_turns = payload.get("num_turns")
        result.session_id = payload.get("session_id")
    # WHAT STOPPED IT IS THE RUNNER'S OWN ANSWER NOW, not something read back
    # out of the CLI's payload. The old cap was the CLI's, so the CLI was the
    # only thing that could report it having fired; this one is enforced here,
    # and a killed CLI writes no payload to report anything in.
    result.output_capped = bool(observed["capped"])
    result.output_tokens = observed["total"]
    result.watcher_failed = observed["failed"]
    # A WATCHER THAT READ NOTHING IS AS UNENFORCED AS ONE THAT CRASHED, and it
    # is the quieter of the two failures: no exception, no reading, no cap,
    # and a run that looks like it stayed inside a limit nothing measured.
    # This is what the CLI changing where it writes its transcript would look
    # like from here, so it is worth a sentence rather than a silence.
    #
    # ZERO COUNTS AS NOTHING, because zero is not a reading a real run
    # produces: a CLI that answered at all wrote output tokens. And the run
    # has to have lasted long enough for silence to mean something -- two
    # polls, not one, so an ordinary flush lag is not reported as a defect.
    if (max_output_tokens is not None and not result.output_tokens
            and not result.watcher_failed
            and duration_ms > WATCH_INTERVAL_SECONDS * 2 * 1000):
        result.watcher_failed = (
            f"no usage was ever read from {transcript_dir(worktree)} in "
            f"{duration_ms // 1000}s, so nothing was counted")
    if not result.text:
        result.text = (out or "")[-8000:]
    # CLASSIFIED AFTER `text` IS FINAL, so the fallback is covered: a run the
    # provider refused outright may never produce parseable JSON at all, and
    # that is exactly the run whose reason is only in the raw output.
    #
    # Read AFTER output_capped and never over it, which matters more than it
    # did: the ceiling is fleet's own and is a real verdict about the run,
    # while a usage-window refusal is the provider declining to run. Only the
    # second is a could-not-run. A run the runner KILLED leaves truncated
    # output, and truncated output is exactly where a stray phrase match would
    # turn a runaway into a free requeue.
    if not result.output_capped:
        result.could_not_run = classify_could_not_run(result.raw, result.text)
    result.reported_paths = parse_report(result.text)
    result.refused = parse_refusal(result.text)
    return result


#: Output tokens at which a run is worth a human's attention, measured rather
#: than chosen: p90 of the 95 runs on record after 048's backfill (median
#: 25,106, p75 38,688, p90 49,495, max 72,932).
#:
#: OBSERVED, NOT ENFORCED, and that is the finding rather than a compromise.
#: Size does predict failure -- runs past ~40k output fail about 60% of the
#: time against a 37% baseline -- but a cap there is a coin flip on real work:
#: tested against all 95 runs, a 45k ceiling would have stopped 9 failures and
#: destroyed 5 verified runs. A signal that good is worth surfacing and not
#: worth firing on. The spend cap remains the only thing that stops a run.
NOTABLE_OUTPUT_TOKENS = 49_495

#: Called with (output_tokens, turns) the first time a run in flight
#: passes the threshold. A hook rather than a parameter to `invoke` so
#: the signature every caller and test fake already implements is not
#: widened for something that only reports.
on_notable_run = None

#: How often the watcher reads the transcript. This is the overshoot bound on
#: the ceiling: a run can produce up to one poll's worth of output past its
#: limit before anything notices. 15s against a ceiling of 100,000 is a
#: fraction of a percent, and a tighter poll would buy nothing but syscalls.
WATCH_INTERVAL_SECONDS = 15


def transcript_dir(worktree: Path) -> Path:
    """Where the CLI writes this worktree's session JSONL.

    The CLI keys its project directory on the working directory with every
    "/" and "." replaced by "-", so the runner can find the transcript of a
    run that is still going without being told the session id -- which the
    result only carries once the run is over.
    """
    mangled = str(worktree).replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / mangled


def _watch_output_tokens(worktree: Path, started: float, stop: threading.Event,
                         on_notable, *, ceiling: int | None = None,
                         on_ceiling=None, report=None) -> None:
    """Count a run's output while it runs: report at p90, STOP at the ceiling.

    Reads the transcript the CLI is writing. Deduplicated by message id for
    the reason tools/backfill_token_classes.py documents: one turn is written
    as one record per content block, each repeating the same usage, so
    counting records overstates a run by about a factor of two.

    TWO THRESHOLDS, AND THEY ARE NOT THE SAME KIND OF THING.
    `NOTABLE_OUTPUT_TOKENS` is p90 of recorded runs and only reports -- 049
    measured that firing there would destroy more verified work than it saved.
    `ceiling` is the task's `max_output_tokens`, sits far above every run on
    record, and stops the run. Passing the first no longer ends the watch: the
    second still has to be enforced.

    EVERY FAILURE HERE IS SWALLOWED, AND SAYING SO IS NOW PART OF THE JOB.
    While this only observed, a watcher that died in silence cost nothing. Now
    it holds the only ceiling there is, and a dead watcher is an uncapped run
    that looks exactly like a run that stayed within its cap. So the reason is
    handed back through `report` rather than logged here -- this thread has no
    business writing to the run's log -- and the caller decides what to say.
    """
    seen: set[str] = set()
    total = 0
    notable_reported = False
    while not stop.is_set():
        stop.wait(WATCH_INTERVAL_SECONDS)
        try:
            base = transcript_dir(worktree)
            files = [f for f in base.glob("*.jsonl")
                     if f.stat().st_mtime >= started - 5]
            for f in files:
                with f.open() as fh:
                    for line in fh:
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("type") != "assistant":
                            continue
                        msg = rec.get("message") or {}
                        usage = msg.get("usage") or {}
                        mid = msg.get("id")
                        if not usage or not mid or mid in seen:
                            continue
                        seen.add(mid)
                        total += int(usage.get("output_tokens") or 0)
            if report:
                report(total=total, turns=len(seen))
            if not notable_reported and total >= NOTABLE_OUTPUT_TOKENS:
                notable_reported = True
                on_notable(total, len(seen))
                if ceiling is None:
                    # Nothing left to watch for. With a ceiling the watch
                    # continues past p90, because p90 is where this starts
                    # being worth reading and not where it stops.
                    return
            if ceiling is not None and total >= ceiling:
                on_ceiling(total, len(seen))
                return
        except Exception as exc:
            if report:
                report(failed=f"{type(exc).__name__}: {exc}"[:200])
            return
    # A clean stop is the run ending, which is the ordinary case and not a
    # failure: `report` already carries the last reading.


#: What the provider says when the plan's usage window is spent. The account
#: these runs authenticate as has usage credits OFF and a zero balance, so
#: there is no spend path past the window: the request is refused and the run
#: stops where it stands. See 048 for why nothing here is billed.
_USAGE_LIMIT_TEXT = (
    "hit your session limit",
    "hit your weekly limit",
    "hit your usage limit",
    "usage limit reached",
)


def classify_could_not_run(payload: dict, text: str) -> str | None:
    """Why this run produced no evidence about the task, or None.

    THE DISTINCTION IS runner/verify.py's, ONE LAYER UP. That module separates
    a check that FAILED from a check that COULD NOT RUN -- "a check that cannot
    write is not a check that failed" -- and records the second as undecided
    rather than as a verdict. An agent stopped because the plan's usage window
    was spent is the same class: the tree was never judged, so the run is not
    evidence about it, and a task must not spend an attempt on it.

    DELIBERATELY NARROW. A false positive here is worse than a false negative:
    it requeues a task that genuinely failed, forever. Only signals that can
    ONLY mean the provider refused the request count, and the reason names
    which one matched so a reader can check the call rather than trust it.
    """
    status = payload.get("api_error_status")
    if status == 429:
        return "the provider rate-limited the request (HTTP 429)"

    for field in ("subtype", "terminal_reason", "stop_reason"):
        value = payload.get(field)
        if isinstance(value, str) and value in (
                "usage_limit_reached", "rate_limit_error", "error_usage_limit"):
            return f"the provider reported {field}={value!r}"

    low = (text or "").lower()
    for phrase in _USAGE_LIMIT_TEXT:
        if phrase in low:
            return f"the provider said {phrase!r}"
    return None


def _own_group(pgid: int) -> bool:
    """Guard: never signal the runner's own group.

    start_new_session should make this impossible. It is checked anyway
    because the failure mode is the runner killing itself and every other
    task in the tick, and the check costs one syscall.
    """
    try:
        return pgid == os.getpgid(0)
    except OSError:
        return True


def _kill_group(pgid: int, proc: subprocess.Popen) -> None:
    """TERM the group, then KILL what is left.

    A plain proc.kill() would leave the CLI's children running: they were
    started in the same new session, which is why the runner asked for one.
    """
    if _own_group(pgid):
        return
    for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        if grace:
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    return
                time.sleep(0.1)


def _reap_group(pgid: int) -> None:
    """Clear out whatever the agent left in its group.

    Called after every run, not only after a timeout. The leader is already
    gone by this point, so there is no process to poll and no reason to wait
    five seconds: anything still in the group outlived its parent and is not
    going to be talked down. ProcessLookupError is the normal case -- it
    means the group emptied itself, which is what should happen.
    """
    if _own_group(pgid):
        return
    for sig, grace in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        if grace:
            time.sleep(grace)
