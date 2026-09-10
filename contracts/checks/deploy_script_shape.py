#!/usr/bin/env python3
"""Acceptance check for a DEPLOY SCRIPT.

Run from the root of the worktree. Reads FLEET_CHANGED_FILES.

WHY A SHAPE CHECK AND NOT A TEST RUN

A deploy script cannot be exercised in a worktree: running it would build an
image and swap a production container, which is the one thing a verification
step must not do. So this checks the SHAPE, and the shape is not arbitrary --
every requirement below is a failure that has already happened on this host.

    GIT_SHA stamped          contracts/dd-analytics-frontend.yaml's task 49
                             merged on 10 Sep and the merchant still saw the
                             old page, because the running image was built
                             on 3 Sep with a bare `docker compose up --build`.
                             platform/Dockerfile had carried `ARG GIT_SHA`
                             since 26 Aug and platform/docker-compose.yml had
                             carried the build arg and the documented command
                             for just as long. Nothing forced anyone to pass
                             it, so for eight days nobody did.

    refuses an unknown sha   `unknown` is what an unstamped build reports, and
                             drift-check reads it as "not instrumented" rather
                             than as "stale". A deploy that ships one puts
                             production back into the state where nothing can
                             say what is running.

    rollback from the        api/deploy.sh: ":latest is not a safe source" --
    RUNNING container        it may already point at the build you are about
                             to replace it with, in which case the rollback
                             tag rolls back to the thing that broke.

    verifies after the swap  Otherwise the deploy reports success on the same
                             evidence that was wrong for a week: nothing read
                             back from the thing actually serving traffic.

    set -euo pipefail        A deploy that continues past a failed step is
                             worse than one that stops, because it stops
                             halfway and says it worked.

WHAT THIS CANNOT ESTABLISH. That the script works. It reads text and proves
none of it runs correctly -- the first real deploy is the evidence, and it is
why `run_autodeploy.py` still carries --dry-run. This check exists to make that
first run smaller, not to replace it.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

#: Each rule is (name, regex, why). The `why` is printed on failure, because a
#: check that says "missing GIT_SHA" and not what that cost is a check the next
#: person argues with.
RULES = [
    ("a strict shell",
     r"set\s+-[a-z]*e[a-z]*\s|set\s+-euo\s+pipefail",
     "a deploy that continues past a failed step stops halfway and reports "
     "success"),
    ("the sha, read from git",
     r"git\s+rev-parse\s+HEAD",
     "the running image must be able to say which commit it is, and the only "
     "authority for that is git"),
    ("the sha, passed to the build",
     r"GIT_SHA\s*=|--build-arg\s+GIT_SHA",
     "platform/Dockerfile has carried ARG GIT_SHA since 26 Aug and the image "
     "running on 10 Sep still reported `unknown`, because nothing passed it"),
    ("a refusal when the sha is unknown",
     r"(?s)GIT_SHA.{0,120}unknown|unknown.{0,120}GIT_SHA",
     "shipping an unstamped build returns production to the state where no "
     "check can tell whether a merge ever reached a user"),
    ("a rollback tag taken before the build",
     r"docker\s+(image\s+)?tag|docker\s+inspect.{0,80}\.Image",
     "api/deploy.sh: :latest is not a safe source for a rollback tag, because "
     "it may already point at the build being replaced"),
    ("a read-back after the swap",
     r"(printenv|docker\s+exec|docker\s+inspect).{0,200}GIT_SHA",
     "a deploy that does not read the sha back off the running container "
     "reports success on exactly the evidence that was wrong for a week"),
]


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main(argv=None) -> int:
    changed = [p for p in (os.environ.get("FLEET_CHANGED_FILES") or "").split()
               if p.strip()]
    scripts = [p for p in changed if p.endswith(".sh")]
    if not scripts:
        return fail("the change contains no shell script. A deploy task "
                    "produces one; that is its artifact.")
    if len(scripts) > 1:
        return fail(f"the change touches {len(scripts)} shell scripts: "
                    f"{scripts}. One deploy, one script.")

    rel = scripts[0]
    path = Path(rel)
    if not path.exists():
        return fail(f"{rel} is in the diff but not on disk")
    text = path.read_text()

    problems: list[str] = []

    # COMMENTS ARE STRIPPED BEFORE ANY RULE IS APPLIED, and task 51 is why.
    #
    # Its script tags the rollback correctly -- `docker tag "$running_id"`, off
    # the RUNNING container, at line 219 -- and this check called it a
    # violation, because the FIRST text matching a build was the usage example
    # in the header comment on line 14:
    #
    #     #     GIT_SHA=$(git rev-parse HEAD) docker compose up -d --build
    #
    # so the ordering rule compared a comment against code. That is a check
    # failing a correct script for its documentation, which is worse than not
    # checking: it teaches the next author to write fewer comments.
    #
    # And it cuts the other way, which is the stronger reason. Every rule below
    # asks whether the script DOES something. A script that merely mentions
    # GIT_SHA in a comment satisfies none of them in fact, and this stops it
    # satisfying them in text. `api/deploy.sh` passes on its code alone.
    code = "\n".join(
        re.sub(r"(^|\s)#.*$", r"\1", line) if not line.lstrip().startswith("#")
        else "" for line in text.splitlines())

    # It must at least parse. `bash -n` costs nothing and catches the class of
    # error that would otherwise be found halfway through a production deploy.
    r = subprocess.run(["bash", "-n", rel], capture_output=True, text=True)
    if r.returncode != 0:
        problems.append(f"{rel} is not valid bash: {r.stderr.strip()[:200]}")

    if not os.access(path, os.X_OK):
        problems.append(f"{rel} is not executable, so the deploy path is a "
                        f"file somebody has to remember to invoke with `sh`")

    for name, pattern, why in RULES:
        if not re.search(pattern, code, re.I):
            problems.append(f"{rel} is missing {name} -- {why}")

    # ORDERING, not just presence. A rollback tag taken AFTER the build is a
    # tag on the new image, which is not a rollback at all.
    build_at = re.search(r"docker\s+(compose\s+)?build|compose\s+up\b.*--build",
                         code, re.I)
    tag_at = re.search(r"docker\s+(image\s+)?tag", code, re.I)
    if build_at and tag_at and tag_at.start() > build_at.start():
        problems.append(
            f"{rel} tags its rollback AFTER building. The tag then names the "
            f"image being deployed rather than the one being replaced, which "
            f"is a rollback to the thing that broke.")

    if problems:
        print(f"FAIL: {rel} -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"ok: {rel} -- valid bash, executable, stamps GIT_SHA from git, "
          f"refuses an unknown sha, tags a rollback before building, and reads "
          f"the sha back off the running container.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
