#!/usr/bin/env python3
"""Acceptance check for a DRAFT SPEC task.

Run from the root of the worktree. Reads FLEET_CHANGED_FILES, which the runner
derived from git.

WHY THIS CHECK IS THE REASON THE DRAFT-SPEC STEP EXISTS AT ALL

`specs/approval-surface.md` §3 chose option B -- a tick produces a draft spec
that a human reviews -- over queueing the code task directly. The evidence was
that two hand-written specs contained factual errors about FILE PATHS, and an
overnight batch would have built five branches against wrong ones.

That error class is factual claims about the repository, and it is checkable
without judgement. So this check is what converts it from something a reviewer
must catch into something a task cannot pass with.

WHY A DECLARED BLOCK AND NOT PROSE SCRAPING

`research_document_shape.py` records what prose scraping costs, measured rather
than assumed: applied loosely to `metorik-gap.md` it flagged ten citations and
all ten were false positives -- URL routes, MIME types, field lists. Narrowed to
citations with a directory component AND an extension it flagged zero there, but
then checked 8 of 48 citations and nothing at all in another document.

A spec does not need scraping, because a spec has to declare its paths anyway:
the task it produces cannot exist without `writable_paths`. So this check reads
a fenced `fleet-spec` YAML block and checks THAT, which is exact. The prose
check is kept as a second, narrow pass using the same measured heuristic, for
paths mentioned in the body but not declared.

WHAT IT ENFORCES

  1. the declared block parses and carries the fields a task needs
  2. `work_type` NAMES A CONTRACT THAT EXISTS. Nothing upstream establishes
     this any more: `candidates` deliberately has no work_type column, because
     a producer reading a findings document would be guessing at what this step
     exists to determine. So this check owns it.
  3. every declared writable path resolves in the tree, or its parent directory
     does -- a spec may legitimately create a new file, but not in a directory
     that does not exist
  4. no declared writable path is on `protected_path_floor` for that repo
  5. the writable paths are inside the repo the spec names
  6. paths cited in prose, narrowly, resolve
  7. the spec NUMBERS ITS REQUIREMENTS, so the task it produces can be held
     to them. specs/auto-approval.md §9.12 step 1: the specs already number
     them and this makes the convention enforceable rather than habitual.
     contracts/checks/spec_requirements_cited.py refuses a code task whose
     numbered requirements are cited nowhere in its diff, and that check
     reports could-not-run against a spec that numbers nothing -- so without
     this rule, a spec-writer that stopped numbering would silently remove
     the only gate that reads a spec at all.

WHAT IT CANNOT ENFORCE, and the asymmetry is why review is still required.
It cannot tell whether the spec describes work worth doing, whether the
approach is right, whether the paths it names are the RELEVANT ones, or whether
a path that resolves today is the one the author meant. A spec that names
`api/app.py` for work belonging in `analytics/services/` passes every check
here. Rule 7 counts requirements; it cannot tell whether they are the right
ones, or whether the numbering carves the work sensibly.

THAT HUMAN READ IS GONE. §3 traded a hand path-check for a human review of the
spec, and on 10 Sep 2026 `draft_spec` came off console/automerge's
NEVER_UNATTENDED, so a draft merges at 03:30 with nobody reading it. The
asymmetry above did not change; what changed is that nothing on the other side
of it is covered any more. See console/automerge.py's docstring for what that
costs and console/morning.py's unread_specs() for the after-the-fact list that
is all that is left.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

FLEET = Path("/home/ubuntu/fleet")

#: One parser for what counts as a numbered requirement, shared by this
#: check, contracts/checks/spec_requirements_cited.py, and the console. See
#: rule 7 above.
sys.path.insert(0, str(FLEET))
from console import requirements                              # noqa: E402
CONTRACTS = FLEET / "contracts"
REPO_ROOT = Path("/home/ubuntu")

BLOCK_RE = re.compile(r"```fleet-spec\s*\n(.*?)\n```", re.S)

#: The same narrowing research_document_shape.py measured: a directory
#: component AND an extension. Loose matching produced ten false positives out
#: of ten on the gold-standard document.
PROSE_PATH_RE = re.compile(r"`([A-Za-z0-9_][\w./-]*/[\w.-]+\.[A-Za-z0-9]{1,5})`")

#: `contract` is REQUIRED, since 11 Sep 2026 and specs/auto-approval.md §14.
#:
#: The resolution it replaces was not "ambiguous work is refused" -- it was
#: "work whose declared paths happen to fall inside a narrow contract is
#: refused". Three contracts have matched (dd_api, deadly-digital-platform)
#: since 30 Aug and five tasks queued fine, because their paths did not fit the
#: narrow one. Task 63's did, two survived, and the draft merged having queued
#: nothing. Whether the queue works was downstream of which paths a draft
#: happened to name.
#:
#: Required rather than optional: "unambiguous" is a property of the paths a
#: draft chose, not of the work, so a field filled in only when something
#: already broke is filled in by whoever is debugging rather than whoever knows.
REQUIRED = ("work_type", "repo", "title", "writable_paths", "contract")


def _repo_files_ending(root, suffix: str, limit: int = 4000) -> list[str]:
    """Real repo-relative paths ending in `suffix`, for the abbreviation hint.

    Bounded: a spec cites a handful of paths and this only runs for one that
    already failed, so walking is affordable, but a runaway tree should not
    hang the check.
    """
    out: list[str] = []
    tail = "/" + suffix.lstrip("/")
    seen = 0
    for p in root.rglob("*" + suffix.rsplit("/", 1)[-1]):
        seen += 1
        if seen > limit:
            break
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel.endswith(tail):
            out.append(rel)
    return out


def fail(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def _inside(path: str, globs) -> bool:
    """The prefix test console/autoqueue.py and console/rank.py both use.

    Copied rather than imported for the reason those two copy it from each
    other: this file runs inside the agent's worktree, where `console` is not
    importable. Eight lines, and the tests assert all three agree on the paths
    that matter -- which is the only thing that makes a copy acceptable.
    """
    for g in globs:
        pre = str(g).split("*", 1)[0].rstrip("/")
        if pre and (path == pre or path.startswith(pre + "/")):
            return True
    return False


def _covers(contract_path, work_type: str, repo: str, declared) -> bool:
    """Does this contract match the work AND cover every declared path?"""
    try:
        d = yaml.safe_load(contract_path.read_text()) or {}
    except Exception:
        return False
    if d.get("work_type") != work_type or d.get("repo") != repo:
        return False
    globs = [str(g) for g in (d.get("writable_paths") or [])]
    return bool(globs) and all(_inside(p, globs) for p in declared)


def load_protected(work_type: str, repo: str) -> list[str]:
    """The protected paths of the contract this spec's work would run under.

    NOT the union of every contract for the repo, which is what the first
    version did and which was wrong in a way worth recording: contracts are
    deliberately narrow and protect each other's territory. The api contract
    protects `platform/**` precisely because it cannot verify frontend work, so
    unioning them made every legitimate frontend path look protected and the
    check refused a correct spec.

    A spec declares its work_type, so it is judged against THAT contract --
    which is also the contract the resulting task will actually run under, so
    this asks the question that will be asked later rather than a stricter one
    nobody enforces.
    """
    for y in CONTRACTS.glob("*.yaml"):
        try:
            data = yaml.safe_load(y.read_text()) or {}
        except Exception:
            continue
        if data.get("work_type") == work_type and data.get("repo") == repo:
            return sorted(data.get("protected_paths") or [])
    return []


def glob_matches(path: str, pattern: str) -> bool:
    """`a/**` covers `a/b/c`. Deliberately simple and deliberately generous:
    a false positive here refuses a spec, which is recoverable; a false
    negative lets a spec declare a protected path writable, which is not."""
    p = pattern.rstrip("*").rstrip("/")
    return path == pattern or path.startswith(p + "/") or path == p


def main() -> int:
    changed = [c for c in os.environ.get("FLEET_CHANGED_FILES", "").split("\n") if c]
    specs = [c for c in changed if c.endswith(".md")]
    if not specs:
        return fail("no markdown file in the diff; a draft-spec task produces "
                    "one spec and nothing else")
    if len(changed) > len(specs):
        return fail(f"the diff contains non-markdown files {sorted(set(changed) - set(specs))}; "
                    "a draft spec is a document, and anything else is something "
                    "nobody asked for")

    for rel in specs:
        text = Path(rel).read_text(encoding="utf-8", errors="replace")

        # ONE BLOCK PER TASK, AND A DRAFT MAY DECLARE MORE THAN ONE.
        #
        # specs/auto-approval.md §12. A candidate whose paths no single
        # contract covers is split by the draft that describes it, into an
        # ordered chain that merges together or not at all. EVERY block is
        # held to every rule below; a chain is not a way to get a looser one
        # past them.
        raw_blocks = BLOCK_RE.findall(text)
        if not raw_blocks:
            return fail(f"{rel} has no ```fleet-spec block. The spec must "
                        "declare work_type, repo, title and writable_paths in "
                        "machine-readable form -- prose cannot be checked, and "
                        "checking it is the reason this step exists.")
        blocks = []
        for n, raw in enumerate(raw_blocks, start=1):
            where = (f"{rel}: fleet-spec block {n} of {len(raw_blocks)}"
                     if len(raw_blocks) > 1 else f"{rel}: the fleet-spec block")
            try:
                b = yaml.safe_load(raw) or {}
            except Exception as exc:
                return fail(f"{where} is not valid YAML ({exc})")
            if not isinstance(b, dict):
                return fail(f"{where} must be a mapping")
            missing = [k for k in REQUIRED if not b.get(k)]
            if missing == ["contract"] and b.get("work_type") and b.get("repo"):
                # THE USEFUL HALF OF THE REFUSAL. A bare "you are missing
                # contract" makes the author guess which one; this names every
                # contract that matches the work AND covers every declared
                # path, which is exactly the set the old rule refused to choose
                # between. §14.4: task 63's silent queue-time refusal becomes a
                # draft-time message asking for a choice.
                fits = [y.name for y in sorted(CONTRACTS.glob("*.yaml"))
                        if _covers(y, str(b["work_type"]), str(b["repo"]),
                                   [str(x) for x in (b.get("writable_paths") or [])])]
                if len(fits) > 1:
                    return fail(
                        f"{where} declares no contract, and {len(fits)} cover "
                        f"its paths: {fits}. They are different boundaries — "
                        f"different verification, different diff limits, and "
                        f"whether a test can be created at all — so this is a "
                        f"choice and not a tiebreak. Name one as `contract:`.")
                if len(fits) == 1:
                    return fail(
                        f"{where} declares no contract. {fits[0]} covers every "
                        f"declared path; name it as `contract: {fits[0]}` so "
                        f"the boundary is stated rather than derived from "
                        f"which paths this spec happened to list.")
                return fail(
                    f"{where} declares no contract, and none in contracts/ "
                    f"matches work_type '{b['work_type']}' on repo "
                    f"'{b['repo']}' and covers every declared path.")
            if missing:
                return fail(f"{where} is missing {missing}. A task cannot be "
                            "created without them.")
            blocks.append(b)

        # PAIRWISE DISJOINT, AND IT IS LOAD BEARING. Each link is built and
        # verified WITHOUT its siblings' changes, which is sound only while no
        # two can write the same file -- otherwise both are checked against a
        # tree that is not the tree that ships.
        owner: dict = {}
        for n, b in enumerate(blocks, start=1):
            for w in (b.get("writable_paths") or []):
                if w in owner:
                    return fail(f"{rel}: fleet-spec blocks {owner[w]} and {n} "
                                f"both declare '{w}'. Links are verified "
                                f"independently, which is only sound while "
                                f"they are disjoint.")
                owner[w] = n

        for block in blocks:
            repo = str(block["repo"])
            work_type = str(block["work_type"])
            named = str(block["contract"])

            # 2a. THE DECLARED CONTRACT, CHECKED HERE AND NOT AT QUEUE TIME.
            #
            # §14.4. This check is the draft task's own verification, so a
            # wrong contract fails the DRAFT -- before it merges and before the
            # code task is queued or paid for. console/autoqueue.py finds the
            # same mistake after the draft has merged, which is money spent to
            # discover that a spec cannot be used.
            cpath = CONTRACTS / named
            if "/" in named or not named.endswith(".yaml"):
                return fail(f"{rel}: contract '{named}' is not a bare filename "
                            f"in contracts/ -- name it as e.g. "
                            f"'deadly-digital-platform-api.yaml'")
            if not cpath.is_file():
                known = sorted(y.name for y in CONTRACTS.glob("*.yaml"))
                return fail(f"{rel}: contract '{named}' is not in contracts/. "
                            f"A typo is refused rather than fallen back from. "
                            f"Known: {known}")
            try:
                chosen = yaml.safe_load(cpath.read_text()) or {}
            except Exception as exc:
                return fail(f"{rel}: contract '{named}' is not valid YAML ({exc})")

            if chosen.get("work_type") != work_type or chosen.get("repo") != repo:
                return fail(
                    f"{rel}: the block says work_type '{work_type}' repo "
                    f"'{repo}', and {named} is work_type "
                    f"'{chosen.get('work_type')}' repo '{chosen.get('repo')}'. "
                    f"A block that says two things decides nothing.")

            # 2. WORK TYPE NAMES A REAL CONTRACT. This check owns it because the
            # candidate row deliberately does not carry a work_type.
            contracts = {}
            for y in CONTRACTS.glob("*.yaml"):
                try:
                    d = yaml.safe_load(y.read_text()) or {}
                except Exception:
                    continue
                if d.get("work_type"):
                    contracts.setdefault(d["work_type"], []).append((y.name, d.get("repo")))
            if work_type not in contracts:
                return fail(f"{rel}: work_type '{work_type}' names no contract in "
                            f"contracts/. Known: {sorted(contracts)}. Nothing "
                            "upstream checks this -- a candidate has no work_type, "
                            "deliberately -- so a wrong one here becomes a task "
                            "that cannot be created.")
            repos_for_type = {r for _, r in contracts[work_type] if r}
            if repos_for_type and repo not in repos_for_type:
                return fail(f"{rel}: work_type '{work_type}' is contracted for "
                            f"{sorted(repos_for_type)}, but the spec names repo "
                            f"'{repo}'.")

            checkout = REPO_ROOT / repo
            if not checkout.is_dir():
                return fail(f"{rel}: repo '{repo}' is not a checkout under {REPO_ROOT}")

            writable = [str(p) for p in (block.get("writable_paths") or [])]

            # 2b. THE DECLARED CONTRACT MUST COVER THE DECLARED PATHS.
            #
            # The same predicate console/autoqueue.py applies at queue time --
            # a prefix test over the contract's writable globs -- so the two
            # cannot disagree about what "covers" means. Naming a contract that
            # does not cover the work is the one way the declaration could be
            # worse than the derivation it replaces, so it is refused here.
            cglobs = [str(g) for g in (chosen.get("writable_paths") or [])]
            outside = [w for w in writable if not _inside(w, cglobs)]
            if outside:
                also = [y.name for y in sorted(CONTRACTS.glob("*.yaml"))
                        if _covers(y, work_type, repo, writable)]
                return fail(
                    f"{rel}: declares {outside} writable, and {named} does not "
                    f"make {'them' if len(outside) > 1 else 'it'} writable. A "
                    f"spec cannot widen the contract its work runs under."
                    + (f" These do cover every declared path: {also}."
                       if also else
                       " No contract for this work_type and repo covers all of"
                       " them, so the paths are wrong or the work spans two"
                       " contracts."))

            # The floor is the NAMED contract's, not the work_type's. Stricter
            # and more honest: it is the contract the task will actually run
            # under, which is the whole point of naming it.
            floor = [str(g) for g in (chosen.get("protected_paths") or [])]

            for w in writable:
                # 4. Not on the floor.
                for g in floor:
                    if glob_matches(w.rstrip("*").rstrip("/"), g):
                        return fail(f"{rel}: declares '{w}' writable, but '{g}' is "
                                    "a protected path for this repo. Editing what "
                                    "judges the work is how a task passes anything.")
                # 5. Inside the repo.
                if w.startswith("/") or ".." in w:
                    return fail(f"{rel}: writable path '{w}' is not repo-relative")

                # 3. Resolves, or its parent does -- a new file is legitimate, a
                # new file in a directory nobody has is a wrong path.
                probe = w.split("*")[0].rstrip("/")
                target = checkout / probe
                if target.exists():
                    continue
                if target.parent.is_dir():
                    continue
                return fail(f"{rel}: writable path '{w}' does not resolve in {repo} "
                            f"and neither does its parent directory. THIS IS THE "
                            "CHECK THAT EXISTS BECAUSE TWO HAND-WRITTEN SPECS GOT "
                            "PATHS WRONG.")

            # 6. Prose paths, narrowly -- AND ON THE SAME TERMS AS THE DECLARED
            # ONES ABOVE.
            #
            # This used to require bare existence, while rule 3 four lines up
            # allows a declared path whose parent directory exists. Two rules for
            # one string, and the contradiction was not theoretical: task 23
            # DECLARED `api/analytics/routes/coupons.py` writable, the check
            # accepted it there, and then failed the identical string for
            # appearing in the prose. Of the six paths that failed tasks 23, 24
            # and 25, five were files the spec proposed to CREATE and three of
            # those were declared in the same document.
            #
            # A spec that may not name the files it is about to write cannot
            # describe the work. So: exists, or its directory does.
            cited = {c for c in PROSE_PATH_RE.findall(text)}
            declared = {w.split("*")[0].rstrip("/") for w in writable}

            abbreviated: list[str] = []
            unknown: list[str] = []
            for c in sorted(cited):
                if (checkout / c).exists() or (FLEET / c).exists():
                    continue
                if (checkout / c).parent.is_dir() or (FLEET / c).parent.is_dir():
                    continue                      # a file this spec will create
                # THE REMAINING REAL ERROR, named for what it is. `routes/orders.py`
                # is not a path; `api/analytics/routes/orders.py` is, and the same
                # document declared it correctly. Recall, not knowledge -- so the
                # message supplies the thing that was not recalled.
                match = next((d for d in sorted(declared)
                              if d.endswith("/" + c) or d == c), None)
                if match is None:
                    match = next((d for d in sorted(_repo_files_ending(checkout, c))),
                                 None)
                if match:
                    abbreviated.append(f"{c} -> {match}")
                else:
                    unknown.append(c)

            if abbreviated or unknown:
                parts = []
                if abbreviated:
                    parts.append("cites abbreviated paths; write them in full from "
                                 f"the repository root: {abbreviated}")
                if unknown:
                    parts.append(f"cites paths that do not exist in {repo} or fleet "
                                 f"and whose directory does not either: {unknown}")
                return fail(f"{rel} " + "; and ".join(parts))

            # 7. NUMBERED REQUIREMENTS, parsed by the same function the console
            #    renders and spec_requirements_cited.py enforces. Imported, not
            #    reimplemented: three readers agreeing on what a requirement is
            #    is the whole point, and a fourth definition here would be the
            #    one that disagrees.
            reqs = requirements.parse(text)
            if not reqs:
                return fail(
                    f"{rel} numbers no requirements, so nothing downstream can "
                    f"be held to it. Number them as `### 2. The page sends them` "
                    f"or `**2.5 The table cells set the filters.**` -- a bare "
                    f"`**1. Something**` does not count, because that is how a "
                    f"paragraph is emphasised. The code task this produces is "
                    f"refused by spec_requirements_cited.py unless each numbered "
                    f"requirement is cited in its diff, and a spec with none "
                    f"turns that gate off.")

            print(f"ok: {rel} block {blocks.index(block) + 1}/{len(blocks)} -- "
                  f"work_type '{work_type}' has a contract, "
                  f"{len(writable)} writable path(s) resolve and none is "
                  f"protected, {len(cited)} prose path(s) checked, "
                  f"{len(reqs)} numbered requirement(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
