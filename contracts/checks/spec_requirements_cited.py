#!/usr/bin/env python3
"""Every numbered requirement is cited somewhere in the change.

Run from the root of the worktree. Exits 0 if every requirement the spec
numbers is cited by an added line, 1 naming the ones that are not, 2 if the
check could not run at all.

WHY THIS EXISTS

specs/auto-approval.md §9.9. Four green checks establish that the tree
typechecks, that the suite passes, that one new test bites, and that no pair
landed in half. None of them reads the spec, and task 53 shipped §2.5 of its
own spec unbuilt through all four. `auto_merge: false` caught it, and that
was the only reader of a spec in the entire path.

That reader is gone. `auto_merge` went `true` on the frontend contract on
10 Sep 2026 and `draft_spec` came off console/automerge.NEVER_UNATTENDED the
same day, so nothing reads a spec at any point. §9.12 costed the cheapest
thing that would notice and did not build it, on the grounds that "on the
frontend contract, where a person already reads the spec, it adds annotation
cost for a check weaker than the reader it sits beside". There is no longer a
reader for it to be weaker than, so it is built here.

WHAT IT ESTABLISHES, STATED SO IT IS NOT OVERSOLD

**That a claim was made, not that it was met.** An agent can write
`// spec:2.5` and change nothing. That is still worth having: it converts a
silent omission into a written, attributable claim sitting in the diff --
visible to review, and a lie rather than an oversight. It moves the failure
from invisible to answerable.

It would have failed task 53. No line of that diff carries such a marker for
any requirement, including the four that were implemented.

WHAT IT DOES NOT ESTABLISH, so nobody reads more into a green:

  * that the requirement was implemented correctly, or at all;
  * that the citing line is even related to the requirement -- this does not
    check that the token sits in a comment rather than in a string literal.
    Enforcing that means parsing four languages, and a parser that is wrong
    about TSX would refuse working changes, which is the failure mode §9.12
    measured on the grep-the-number approach and rejected;
  * that the spec was worth following.

WHY THE PARSER IS IMPORTED AND NOT COPIED

`console/requirements.py` is what renders the checklist on /tasks/{id} and in
the morning page's "a feature shipped and nobody read its spec" ask. If this
check recognised a different set of ids from the list a person is shown, the
reader would be walking one list while the gate enforced another -- and the
requirement that fell between them is exactly the one nobody would catch.
One parser, two readers.

WHY A PARENT IS SATISFIED BY ITS CHILDREN

`requirements.parse` returns both `### 2. The page sends them` and
`**2.5 The table cells set the filters.**`. Demanding `spec:2` as well as
`spec:2.5` would require citing a heading whose whole content is its
subsections, and an agent doing that learns to sprinkle tokens rather than to
mean them. So `2` is satisfied by any of `2.x`. A requirement with no
children must be cited itself.

WHY NO REQUIREMENTS IS COULD-NOT-RUN AND NOT A PASS

A spec that numbers nothing has nothing for this to establish, and a check
that cannot fail is worse than an absent one -- it sits in the verification
list looking like a gate. Reported as 2, which the runner records as "could
not be verified" rather than as the code being wrong.

That is only safe because contracts/checks/draft_spec_shape.py now REFUSES a
draft that numbers no requirement, so anything arriving by the draft-spec
route has them. A task queued by hand under a contract that runs this must
number its requirements too, and the message below says so rather than
leaving it to be discovered.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

#: The console is on this host and this check runs under its interpreter.
#: Imported for `requirements.parse` alone -- see the docstring above for why
#: this is an import and not a second copy of the two regexes.
sys.path.insert(0, "/home/ubuntu/fleet")

try:
    from console import requirements
except ImportError as exc:                                    # pragma: no cover
    print(f"FAIL: cannot import console.requirements ({exc}), so the "
          f"requirement list this check enforces would not be the list the "
          f"console shows.")
    print("      Reported as 'could not run' (2), never as a pass.")
    sys.exit(2)


def die(code: int, *lines: str) -> None:
    for line in lines:
        print(line)
    sys.exit(code)


def token(rid: str) -> re.Pattern:
    """`spec:2.5`, and not `spec:2.50`.

    The trailing guard excludes a digit and a dot, so `spec:2.5` does not
    match inside `spec:2.51`; the leading guard excludes word characters and
    dots, so it does not match the tail of `myspec:2.5` either. Case is
    ignored because `SPEC:2.5` in a heading comment is the same claim.
    """
    return re.compile(rf"(?<![\w.])spec:{re.escape(rid)}(?![\w.\d])",
                      re.IGNORECASE)


def added_lines(base: str) -> list[str]:
    """Lines this change ADDED, from git.

    Asks git rather than reading FLEET_CHANGED_FILES, for the reason
    paired_paths.py gives: a check that depends on another component having
    got its list right is a check about that component.

    Added only. A token that was already in the tree is not a claim this
    change made, and counting it would let a task inherit its predecessor's
    citations -- which on a parity push, where consecutive tasks touch the
    same files, is not a hypothetical.
    """
    out = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}..HEAD"],
        capture_output=True, text=True, check=True).stdout
    return [ln[1:] for ln in out.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")]


def main() -> None:
    spec = os.environ.get("FLEET_SPEC_MD")
    if not spec:
        die(2, "FAIL: FLEET_SPEC_MD is not set, so this check does not know "
               "what the spec asked for.",
               "      The runner sets it beside FLEET_CONTRACT; see "
               "runner/cycle.py and console/reverify.py.",
               "      Reported as 'could not run' (2), never as a pass.")

    reqs = requirements.parse(spec)
    if not reqs:
        die(2, "FAIL: this spec numbers no requirements, so there is nothing "
               "for this check to establish.",
               "      A check that cannot fail is worse than an absent one.",
               "",
               "      Number them as `### 2. The page sends them` or "
               "`**2.5 The table cells set the filters.**`.",
               "      A draft spec cannot pass draft_spec_shape.py without "
               "them; a task queued by hand needs them typed.",
               "      Reported as 'could not run' (2), never as a pass.")

    base = os.environ.get("FLEET_BASE_SHA")
    if not base:
        die(2, "FAIL: FLEET_BASE_SHA is not set, so there is nothing to diff "
               "against.",
               "      Reported as 'could not run' (2), never as a pass.")

    try:
        lines = added_lines(base)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        die(2, f"FAIL: could not derive the diff from git: {exc}",
               "      Reported as 'could not run' (2), never as a pass.")

    ids = [q.id for q in reqs]
    cited = {rid for rid in ids
             if any(token(rid).search(ln) for ln in lines)}
    # A parent is carried by any child that was cited. Computed against every
    # id in the spec rather than against the cited set alone, so a heading
    # whose only child is itself uncited stays uncited.
    covered = set(cited)
    for q in reqs:
        kids = [r for r in ids if r.startswith(q.id + ".")]
        if kids and any(k in cited for k in kids):
            covered.add(q.id)

    missing = [q for q in reqs if q.id not in covered]
    if missing:
        print(f"FAIL: {len(missing)} of {len(reqs)} numbered requirement(s) "
              f"are cited nowhere in this change.")
        print()
        for q in missing:
            print(f"      {q.id}  {q.title}")
        print()
        print("      Put `spec:<id>` on a line this change ADDS -- in a "
              "comment, a test name, or a docstring -- for every requirement "
              "above.")
        print("      Example: `// spec:2.5 clicking a Payment cell sets the "
              "filter`.")
        print()
        print("      THIS PROVES A CLAIM WAS MADE, NOT THAT IT WAS MET. If a "
              "requirement is genuinely not in scope for this change, say so "
              "in your reply and leave it uncited: a refused branch that "
              "explains itself is useful, and a token written over work that "
              "was not done is a lie rather than an oversight. Do not cite a "
              "requirement you did not implement.")
        sys.exit(1)

    print(f"PASS: all {len(reqs)} numbered requirement(s) are cited by an "
          f"added line.")
    print("      This establishes that a claim was made about each one. It "
          "does not establish that any of them was implemented.")


if __name__ == "__main__":
    main()
