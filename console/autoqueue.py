"""Accepting a draft spec queues the code task it describes.

WHAT THIS REMOVES, AND WHAT IT LEAVES
--------------------------------------
specs/auto-approval.md §1.2 traced five hand steps between a findings document
and a merged feature, and §8 restated them with the load automated. Creating the
code task was one of them, and it was the largest: `approve_batch` deliberately
makes ONLY draft-spec tasks, so every code task on this host was a hand INSERT
(task 49 and task 53 both were).

With this, and with `auto_merge: true` on the frontend contract and
`run_autodeploy.py` off `--dry-run`, the chain from an approved candidate to a
deployed feature has ONE human step left: a person accepts the draft spec.

That step is not removed here and cannot be removed by a contract.
`console/automerge.py`'s NEVER_UNATTENDED is keyed on work_type and its own
comment says why: *"draft_spec and research produce artefacts that exist to be
READ. Merging one without a person defeats the only step where intent, rather
than the diff, is judged."* Taking it out is a separate decision with a
separate argument, and it is not made here.

WHAT IS LOST, STATED WHERE THE AUTOMATION IS ARGUED
----------------------------------------------------
specs/auto-approval.md §9.9: no contract check reads the spec. Task 53 shipped
§2.5 of its own spec unbuilt with tsc, vitest, `new_test_bites.sh` and
`paired_paths.py` all green, and it was caught only because the frontend
contract set `auto_merge: false` and a person compared the spec to the diff.

**Once the code task auto-merges, nobody makes that comparison.** The spec is
still read once — at the acceptance this function hangs off — but that reading
judges whether the work is RIGHT, before it exists. Nothing afterwards asks
whether it was DONE.

**And the requirements checklist built on 10 Sep reaches none of this.** It
renders on `/tasks/{id}`, and on the unattended path nobody opens that page:
the code task is queued here, claimed by the runner, merged by `automerge.py`
and deployed by `run_autodeploy.py` without a request ever being made. A reader
that has to be visited is not a reader on a path with no visitor. The brief is
the only surface a person is known to look at afterwards, which is why
`brief/pass_.py` now lists the requirements of anything merged unattended.

The consequence in practice: a feature ships with four of five requirements,
every check green, nothing failed, no revert triggered — because there is
nothing to revert — and the first evidence is somebody using it. That is the
trade. It is defensible while the product has no users and reversed on the day
`specs/unattended-operation.md` §7 says it is.

WHAT THIS REFUSES
-----------------
A spec may not widen its own contract. The `fleet-spec` block declares
`writable_paths`, and `contracts/checks/draft_spec_shape.py` already checked
them against the contract's protected paths when the draft was verified — but
that ran against the contract as it was THEN, and this queues against the
contract as it is NOW. Both are checked here, because the gap between them is
exactly where a widened boundary would enter unattended.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from console import config, db

#: The same block the draft-spec check reads. One shape, one parser.
BLOCK_RE = re.compile(r"```fleet-spec\s*\n(.*?)\n```", re.S)

REQUIRED = ("work_type", "repo", "title", "writable_paths")

#: A draft spec writes here and nowhere else -- contracts/draft-spec.yaml.
DRAFTS = "drafts/"


class QueueRefused(Exception):
    """No task was created. The message is shown to whoever accepted."""


@dataclass
class Queued:
    task_id: int | None = None
    title: str = ""
    repo: str = ""
    work_type: str = ""
    contract_file: str = ""
    spec_path: str = ""
    candidate_id: int | None = None
    detail: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(("git", "-C", str(repo)) + args,
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise QueueRefused(f"git {' '.join(args)} failed: "
                           f"{(r.stderr or '').strip()[:200]}")
    return r.stdout


def _contract_for(work_type: str, repo: str,
                  declared: list[str] | None = None) -> tuple[dict[str, Any], str]:
    """The contract this work will actually run under.

    Not the union of every contract for the repo, for the reason
    draft_spec_shape.load_protected records: contracts are deliberately narrow
    and protect each other's territory.

    WORK_TYPE ALONE DOES NOT IDENTIFY A CONTRACT, and finding that out is what
    this function was written for. `dd_frontend` on `deadly-digital-platform`
    matches TWO: dd-analytics-frontend.yaml, and dd-acquiring-page.yaml, which
    is a spent single-task contract for task 3 (merged 30 Aug) whose header
    still refers to a "default frontend contract" that 023 deleted and floored.

    So the declared paths break the tie, and they are a real discriminator
    rather than a guess: a contract that cannot write what the spec says it
    will write is not the contract the work runs under, whatever its work_type
    says. dd-acquiring-page can write products/** and Sidebar.tsx; a spec about
    the orders page fits only one of the two.

    Ambiguity that the paths do not resolve REFUSES. Choosing by filesystem
    order is what contracts/checks/draft_spec_shape.py's load_protected does --
    `CONTRACTS.glob("*.yaml")`, unsorted, first match wins -- so a draft has
    been validated against whichever contract readdir happened to yield.
    specs/auto-approval.md §9.13 records that; it is not fixed here, and it is
    the reason this refuses rather than copying the behaviour.
    """
    matches = []
    for y in sorted((config.PROJECT_ROOT / "contracts").glob("*.yaml")):
        try:
            data = yaml.safe_load(y.read_text()) or {}
        except Exception:                                     # noqa: BLE001
            continue
        if data.get("work_type") == work_type and data.get("repo") == repo:
            matches.append((data, y.name))
    if not matches:
        raise QueueRefused(
            f"work_type {work_type!r} for repo {repo!r} names no contract in "
            f"contracts/. The draft passed its shape check against the "
            f"contracts as they were when it ran; this queues against them as "
            f"they are now, and one of them has moved.")
    if len(matches) == 1:
        return matches[0]

    fits = [(d, n) for d, n in matches
            if all(_inside(p, list(d.get("writable_paths") or []))
                   for p in (declared or []))]
    if len(fits) == 1:
        return fits[0]
    raise QueueRefused(
        f"work_type {work_type!r} for repo {repo!r} matches "
        f"{len(matches)} contracts ({', '.join(n for _, n in matches)}), and "
        f"the {len(declared or [])} declared path(s) fit {len(fits)} of them. "
        f"Choosing one here would be a guess about which boundary the work "
        f"runs under, and the boundary is the whole of what a contract is.")


def _glob_prefix(g: str) -> str:
    return g.split("*", 1)[0].rstrip("/")


def _inside(path: str, globs: list[str]) -> bool:
    for g in globs:
        pre = _glob_prefix(g)
        if pre and (path == pre or path.startswith(pre + "/")):
            return True
    return False


def spec_blocks(markdown: str) -> list[dict[str, Any]]:
    """Every fleet-spec block, in order, as data.

    ONE BLOCK IS ONE TASK, AND A DRAFT MAY DECLARE MORE THAN ONE. A candidate
    whose paths no single contract covers is split by the draft that describes
    it -- §12.4 -- because the alternative is a splitter that minimises the
    number of contracts, and a minimiser PREFERS a contract whose writable set
    is wide, which is §9.19's hole exactly.

    The blocks become an ordered chain that merges together or not at all. The
    order is the merge order and nothing else: the links do not depend on each
    other to build.
    """
    blocks = BLOCK_RE.findall(markdown or "")
    if not blocks:
        raise QueueRefused(
            "the draft carries no ```fleet-spec block, so there is nothing to "
            "queue; draft_spec_shape.py enforces at least one when it is "
            "written")
    out: list[dict[str, Any]] = []
    for n, raw in enumerate(blocks, start=1):
        where = f"fleet-spec block {n} of {len(blocks)}"
        try:
            block = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise QueueRefused(f"{where} is not valid YAML: {exc}")
        if not isinstance(block, dict):
            raise QueueRefused(f"{where} is not a mapping")
        missing = [f for f in REQUIRED if not block.get(f)]
        if missing:
            raise QueueRefused(f"{where} is missing {missing}")
        if not isinstance(block.get("writable_paths"), list):
            raise QueueRefused(f"{where}'s writable_paths is not a list")
        out.append(block)

    # PAIRWISE DISJOINT, AND IT IS LOAD BEARING RATHER THAN TIDINESS.
    #
    # Each link builds from the base branch and verifies WITHOUT its siblings'
    # changes, which is sound only while no two links can write the same file.
    # Two links touching one file would each be verified against a tree that
    # is not the tree that ships, and both could pass while the merge of the
    # two does not work.
    seen: dict[str, int] = {}
    for n, block in enumerate(out, start=1):
        for path in block["writable_paths"]:
            if path in seen:
                raise QueueRefused(
                    f"fleet-spec blocks {seen[path]} and {n} both declare "
                    f"{path}. Links are verified independently, which is only "
                    f"sound while they are disjoint -- two links sharing a "
                    f"file would each be checked against a tree without the "
                    f"other's change.")
            seen[path] = n
    return out


def spec_block(markdown: str) -> dict[str, Any]:
    """The first fleet-spec block. Kept for callers that want exactly one."""
    return spec_blocks(markdown)[0]


def draft_path(patch_payload: dict[str, Any]) -> str:
    """Which file the draft-spec task added. From the run, not from a guess."""
    files = [p for p in (patch_payload or {}).get("files_changed", [])
             if p.startswith(DRAFTS) and p.endswith(".md")]
    if len(files) != 1:
        raise QueueRefused(
            f"the run changed {len(files)} markdown file(s) under {DRAFTS}: "
            f"{files}. A draft-spec task produces one document.")
    return files[0]


def from_accepted_draft(task: dict[str, Any], patch_payload: dict[str, Any],
                        merged_sha: str) -> Queued:
    """Queue the code task a just-merged draft spec describes.

    `merged_sha` is the base branch AFTER the merge -- the spec is read from
    there rather than from the branch, so what is queued is what landed.
    """
    repo_path = config.repo_root() / task["repo"]
    rel = draft_path(patch_payload)

    # FETCH FIRST, because the merge did not happen here.
    #
    # console/reverify.py merges in a throwaway clone and merge_and_push
    # pushes THAT commit -- "the console writes to no checkout", which is the
    # property 702bce0 exists to state. So `merged_sha` is on origin and is not
    # in this checkout, and the first run of this function failed on exactly
    # that:
    #
    #     git show d7205ca8:drafts/order-table-cells-set-the-filters.md failed:
    #     fatal: path '...' does not exist in 'd7205ca8'
    #
    # The path existed; the COMMIT did not. Reading it from the branch instead
    # would be reading what was proposed rather than what landed, which is the
    # distinction this argument rests on -- so fetch, and read the merge.
    # ONLY WHEN IT IS ACTUALLY ABSENT. An unconditional fetch spends a network
    # round trip on every accept and fails outright in a checkout with no
    # remote -- which is every test fixture, and would be a repository somebody
    # is working in locally.
    have = subprocess.run(
        ("git", "-C", str(repo_path), "cat-file", "-e", f"{merged_sha}^{{commit}}"),
        capture_output=True, timeout=30).returncode == 0
    if not have:
        try:
            _git(repo_path, "fetch", "--quiet", "origin")
        except QueueRefused as exc:
            raise QueueRefused(
                f"the merge {merged_sha[:12]} is not in this checkout and it "
                f"could not be fetched, so the spec that landed cannot be "
                f"read: {exc}")
    markdown = _git(repo_path, "show", f"{merged_sha}:{rel}")
    blocks = spec_blocks(markdown)

    # EVERY BLOCK RESOLVES BEFORE ANY TASK IS CREATED. A chain half-queued is
    # the thing this feature exists to prevent, arriving in the queueing of it:
    # if block 2 names paths no contract covers, block 1 must not already be a
    # row somebody has to clean up.
    resolved = []
    for n, block in enumerate(blocks, start=1):
        work_type = str(block["work_type"])
        target_repo = str(block["repo"])
        declared = [str(p) for p in block["writable_paths"]]
        try:
            contract, contract_file = _contract_for(work_type, target_repo, declared)
        except QueueRefused as exc:
            raise QueueRefused(
                f"fleet-spec block {n} of {len(blocks)} could not be queued, "
                f"so none of them were: {exc}")
        resolved.append((block, work_type, target_repo, declared,
                         contract, contract_file))

    # THE SPEC MAY NOT WIDEN ITS CONTRACT. draft_spec_shape.py checked the
    # declared paths against the contract's PROTECTED list when the draft ran.
    # This checks them against the WRITABLE list as it stands now: a path that
    # is neither protected nor writable passed that check and would still be
    # outside the boundary the task runs under, and the runner would refuse it
    # after the money was spent.
    #
    # EVERY LINK, BEFORE ANY ROW IS WRITTEN, for the same reason the contracts
    # were all resolved above.
    links = []
    for n, (block, work_type, target_repo, declared,
            contract, contract_file) in enumerate(resolved, start=1):
        where = (f"fleet-spec block {n} of {len(resolved)}"
                 if len(resolved) > 1 else "the spec")
        outside = [p for p in declared
                   if not _inside(p, list(contract.get("writable_paths") or []))]
        if outside:
            raise QueueRefused(
                f"{where} declares {outside}, which {contract_file} does not "
                f"make writable. A spec cannot widen the contract its work "
                f"runs under, and queueing this would buy a run the boundary "
                f"refuses.")
        max_cost = contract.get("max_cost_gbp")
        if max_cost is None:
            raise QueueRefused(f"{contract_file} declares no max_cost_gbp")
        frozen = {
            "work_type": work_type,
            "writable_paths": list(contract.get("writable_paths") or []),
            "protected_paths": list(contract.get("protected_paths") or []),
            "verification": list(contract.get("verification") or []),
            "max_diff_lines": contract.get("max_diff_lines"),
        }
        for opt in ("creatable_paths", "paired_paths", "worktree_links",
                    "readable_repos", "agent_tools", "auto_merge",
                    "contract_version"):
            if contract.get(opt) is not None:
                frozen[opt] = contract[opt]
        links.append({"position": n, "block": block, "work_type": work_type,
                      "repo": target_repo, "declared": declared,
                      "contract": contract, "contract_file": contract_file,
                      "max_cost": max_cost, "frozen": frozen})

    # ONE TRANSACTION FOR THE WHOLE CHAIN. A chain half-written is a candidate
    # with one task that will never be held for a sibling that does not exist.
    with db.writer() as conn, conn.transaction():
        cand_row = conn.execute(
            "SELECT id, suggested_paths FROM candidates WHERE spec_task_id=%s"
            " AND work_task_id IS NULL", (task["id"],)).fetchone()

        # THE CHAIN MUST COVER WHAT THE CANDIDATE ASKED FOR.
        #
        # Checked here and not in draft_spec_shape.py because that check runs
        # inside the draft's own worktree with no database and no candidate --
        # the agent has no shell and no credential by design. So a draft that
        # under-declares costs the draft's money and is refused before the
        # BUILD money, which is the expensive half.
        #
        # Only when the blocks were split. A single-block draft narrowing the
        # work is an ordinary editorial decision and always has been.
        if cand_row is not None and len(resolved) > 1:
            wanted = set(cand_row["suggested_paths"] or ())
            got = {p for link in resolved for p in link[3]}
            uncovered = sorted(wanted - got)
            if uncovered:
                raise QueueRefused(
                    f"the draft splits into {len(resolved)} links covering "
                    f"{sorted(got)}, and candidate {cand_row['id']} asked for "
                    f"{uncovered} as well. A chain that drops half the work is "
                    f"the half-shipped feature it exists to prevent, arriving "
                    f"as a narrower spec instead of a failed sibling.")
        ids = []
        for link in links:
            contract = link["contract"]
            conn.execute(
                "INSERT INTO tasks (title, spec_md, repo, base_branch,"
                " acceptance_contract, max_cost_gbp, timeout_seconds,"
                " objective_ref) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (str(link["block"]["title"])[:200], markdown, link["repo"],
                 str(contract.get("base_branch") or "main"),
                 json.dumps(link["frozen"]), link["max_cost"],
                 int(contract.get("timeout_seconds") or 1800),
                 task.get("objective_ref")))
            ids.append(conn.execute(
                "SELECT currval('tasks_id_seq') AS id").fetchone()["id"])

        # §9.8: work_task_id is read by two ceilings and was written by nobody,
        # because the step that should write it was the hand INSERT this
        # function replaces. It names the FIRST link; the chain table carries
        # the rest, so every existing reader keeps working unchanged.
        cand = None
        if cand_row is not None:
            cand = conn.execute(
                "UPDATE candidates SET work_task_id=%s WHERE id=%s RETURNING id",
                (ids[0], cand_row["id"])).fetchone()
            # A CHAIN IS RECORDED ONLY WHEN THERE IS MORE THAN ONE LINK. A
            # single-task candidate is not a chain, and a row saying it is
            # would make automerge hold it for a sibling it does not have.
            if len(links) > 1:
                for link, tid in zip(links, ids):
                    conn.execute(
                        "INSERT INTO task_chain (candidate_id, position,"
                        " contract_file, declared_paths, task_id)"
                        " VALUES (%s,%s,%s,%s,%s)",
                        (cand_row["id"], link["position"],
                         link["contract_file"], link["declared"], tid))
        elif len(links) > 1:
            raise QueueRefused(
                f"the draft declares {len(links)} fleet-spec blocks but no "
                f"candidate names spec task {task['id']}, so there is nothing "
                f"to hang the chain on and the links would merge one at a "
                f"time -- which is the half-shipped feature §12 exists to "
                f"prevent.")

    first = links[0]
    detail = [f"queued task {ids[0]} under {first['contract_file']}",
              f"{len(first['declared'])} declared path(s), all inside the "
              f"contract's writable set",
              f"auto_merge is {first['frozen'].get('auto_merge', True)!r} on "
              f"that contract"]
    if len(links) > 1:
        detail.append(
            f"CHAIN of {len(links)}: " + "; ".join(
                f"{l['position']}. task {t} under {l['contract_file']}"
                for l, t in zip(links, ids)))
        detail.append("no link merges until every link has verified, so a "
                      "failure in one leaves none of them shipped")
    detail.append(f"candidate {cand['id']} now names task {ids[0]} as its "
                  f"work task" if cand else
                  "no candidate names this spec task, so nothing to link")

    return Queued(task_id=ids[0], title=str(first["block"]["title"]),
                  repo=first["repo"], work_type=first["work_type"],
                  contract_file=first["contract_file"], spec_path=rel,
                  candidate_id=cand["id"] if cand else None, detail=detail)
