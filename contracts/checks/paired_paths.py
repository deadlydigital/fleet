#!/usr/bin/env python3
"""Both files, or neither.

Run from the root of the worktree. Exits 0 if every pair the contract declares
is whole, 1 naming the ones that are not, 2 if the check could not run at all.

WHY THIS EXISTS

specs/dashboard-comparison-windows.md ends with a requirement that no contract
could express:

  "The follow-up frontend task -- separate, dd_frontend, not in scope here --
   must land the label change and the proxy change TOGETHER. Widening
   platform/app/api/analytics/dashboard/route.ts first would let
   platform/app/(dashboard)/analytics/page.tsx render 'vs previous 366 days'
   over a year-on-year comparison, which is a worse sentence than the
   unqualified one this change exists to fix."

Writable and protected say where a task may write. Neither says that two
places must move together, so that paragraph was a note in a spec with nothing
behind it. `paired_paths` is the contract key, 024_paired_paths.sql is what
refuses a malformed one, and this is what reads it against the diff.

WHAT IT ESTABLISHES

That the change touched all of a group's paths or none of them. That is a fact
about the diff, and the diff comes from git.

WHAT IT DOES NOT, SO NOBODY READS MORE INTO A GREEN

That the label is RIGHT. Both files moving together is necessary and nowhere
near sufficient: an agent can widen the proxy, touch the page, and still render
a sentence that describes the wrong window. Only a render test asserting the
behaviour can say otherwise, and the agent chooses what its test asserts --
new_test_bites.sh then proves that test discriminates between two trees, not
that it discriminates on the property the spec asked for.

So the first spec to use this key carries `auto_merge: false`. This check
narrows the failure to one a reader can see in a diff; it does not remove the
reader. See contracts/dd-analytics-frontend.yaml.

WHY IT ASKS GIT RATHER THAN READING FLEET_CHANGED_FILES

The same reason new_test_bites.sh re-derives its own list: a check that depends
on another component having got its list right is a check about that component.
Git is the thing neither the agent nor the runner can talk out of.

It also counts DELETIONS. FLEET_CHANGED_FILES drops them, and a pair half of
which was deleted is exactly the half-landed change this refuses.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def die(code: int, *lines: str) -> None:
    for line in lines:
        print(line)
    sys.exit(code)


def main() -> None:
    raw = os.environ.get("FLEET_CONTRACT")
    if not raw:
        die(2, "FAIL: FLEET_CONTRACT is not set, so this check does not know "
               "what is paired.",
               "      Reported as 'could not run' (2), never as a pass.")
    try:
        contract = json.loads(raw)
    except (TypeError, ValueError) as exc:
        die(2, f"FAIL: FLEET_CONTRACT is not readable JSON: {exc}",
               "      Reported as 'could not run' (2), never as a pass.")

    groups = contract.get("paired_paths") or []
    if not groups:
        # A CONTRACT THAT RUNS THIS AND DECLARES NOTHING IS A CHECK THAT CANNOT
        # FAIL, and it would sit in the verification list looking like a gate.
        # Refused as could-not-run rather than passed: verify.Verification
        # treats a run in which nothing was established as a failure, which is
        # the reading this wants.
        die(2, "FAIL: the contract declares no paired_paths, so there is "
               "nothing for this check to establish.",
               "      A check that cannot fail is worse than an absent one.",
               "      Reported as 'could not run' (2), never as a pass.")

    base = os.environ.get("FLEET_BASE_SHA")
    if not base:
        die(2, "FAIL: FLEET_BASE_SHA is not set, so there is nothing to diff "
               "against.",
               "      Reported as 'could not run' (2), never as a pass.")

    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..HEAD"],
            capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        die(2, f"FAIL: could not derive the diff from git: {exc}",
               "      Reported as 'could not run' (2), never as a pass.")

    changed = {line.strip() for line in out.splitlines() if line.strip()}

    broken: list[str] = []
    whole = 0
    untouched = 0
    for group in groups:
        paths = list(group.get("paths") or [])
        why = (group.get("why") or "").strip()
        touched = [p for p in paths if p in changed]
        if not touched:
            untouched += 1
            continue
        missing = [p for p in paths if p not in changed]
        if not missing:
            whole += 1
            continue
        broken.append(
            "\n".join([
                "  these must land together and did not:",
                *(f"      changed  {p}" for p in touched),
                *(f"      MISSING  {p}" for p in missing),
                f"      why: {why}",
            ]))

    if broken:
        print("FAIL: a paired group landed in part.")
        print()
        for b in broken:
            print(b)
            print()
        print("      Land every path in the group in this change, or none of "
              "them. Half of a pair is not a smaller version of the change; "
              "it is a different change, and usually a worse one than doing "
              "nothing.")
        sys.exit(1)

    print(f"PASS: {len(groups)} paired group(s) -- {whole} landed whole, "
          f"{untouched} untouched.")
    if whole == 0:
        # Said out loud rather than left to be inferred from a green. A run in
        # which every group was untouched has checked something real (nothing
        # half-landed) and has not exercised the pairing at all.
        print("      No group was touched, so nothing here was pairing "
              "anything. That is a pass about this diff, not evidence that "
              "the pairing works.")


if __name__ == "__main__":
    main()
