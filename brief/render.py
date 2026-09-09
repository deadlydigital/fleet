"""Rendering the brief, and the two things it refuses to write.

NO LOOKS_WRONG SECTION, DECIDED 7 SEP 2026
-------------------------------------------
The vocabulary carries `LOOKS_WRONG` and this renderer emits none, because
judging needs something to judge against and there is nothing yet. Deriving
thresholds from history blesses whatever today's numbers happen to be; typing
them by hand creates the same hand-maintained tally that was wrong three times
in a single day. So the brief ships as DESCRIPTION ONLY -- what changed, and
what it could not check -- and judgement waits for a baseline worth having.

The section exists in the schema so that adding judgement later is not a
migration. It is empty on purpose, and the brief says so rather than leaving a
reader to assume nothing looked wrong.

NO SUMMARY VERDICT
-------------------
No "all healthy", no score, no ranking. A ranked brief reads as a
recommendation, and this pass does not recommend. "Nothing looks wrong" would
also be false: nothing it CHECKED looked wrong, and the uncomputed list beside
it is how a reader sizes the difference.
"""
from __future__ import annotations

from typing import List

from .claims import CHANGED, LOOKS_WRONG, OVERNIGHT, UNCOMPUTED, Claim


def render(claims: List[Claim], *, generated_at, compares_since,
           sources_ok: int, sources_failed: int) -> str:
    overnight = [c for c in claims if c.section == OVERNIGHT]
    changed = [c for c in claims if c.section == CHANGED]
    wrong = [c for c in claims if c.section == LOOKS_WRONG]
    uncomputed = [c for c in claims if c.section == UNCOMPUTED]

    since = compares_since.isoformat() if compares_since else "the beginning"
    out = [
        f"# Daily brief — {generated_at.date().isoformat()}",
        "",
        f"Compares against: {since}",
        f"Sources reached: {sources_ok}. Sources that did not answer: "
        f"{sources_failed}.",
        f"Claims: {len(claims)}, of which **{len(uncomputed)} could not be "
        f"computed**.",
        "",
    ]

    # OVERNIGHT FIRST, and it is the only section that leads with a summary
    # line. specs/unattended-operation.md §4: a brief of counts cannot tell you
    # a bad night happened, and on most mornings this is three lines saying
    # there is nothing to do. Putting it under "What changed" would bury the
    # one section a reader must not miss beneath thirteen counts.
    out += ["## Overnight", ""]
    if not overnight:
        out.append("_Nothing is reported here. That is not the same as a quiet "
                   "night — check the uncomputed list below for whether this "
                   "pass could read the runs at all._")
    else:
        # The roll-up before the detail, then per-task lines in the order they
        # finished. Sorted by metric_key would interleave the summary with the
        # tasks and put task 10 before task 9.
        def _bullet(c):
            return (f"- **{c.statement}**  \n  _source: {c.source} · as of "
                    f"{c.as_of.isoformat() if c.as_of else 'unknown'}_")

        # The per-task lines belong DIRECTLY under the run roll-up they
        # itemise. Anywhere else and the indentation reads as though they
        # nest under whatever bullet happens to precede them.
        runs = [c for c in overnight if c.metric_key == "overnight.runs"]
        detail = [c for c in overnight
                  if c.metric_key.startswith("overnight.task.")]
        deploys = [c for c in overnight
                   if c.metric_key.startswith("overnight.deployed.")]
        rest = [c for c in overnight
                if c not in runs and c not in detail and c not in deploys]

        for c in runs:
            out.append(_bullet(c))
        for c in sorted(detail, key=lambda c: c.as_of or c.metric_key):
            out.append(f"  - {c.statement}")
        for c in sorted(rest, key=lambda c: c.metric_key):
            out.append(_bullet(c))
        for c in sorted(deploys, key=lambda c: c.metric_key):
            out.append(_bullet(c))

    out += ["", "## What changed", ""]

    if not changed:
        # Distinguishable from "did not look". The run row exists and the
        # source counts are above it.
        out.append("_Nothing changed among the figures this pass can read. "
                   "That is not the same as nothing changing — see what it "
                   "could not check, below._")
    for c in sorted(changed, key=lambda c: c.metric_key):
        line = f"- **{c.statement}**"
        if c.delta_num is not None:
            sign = "+" if c.delta_num >= 0 else ""
            line += f" ({sign}{c.delta_num} since the last brief)"
        elif c.previous_num is None:
            line += " (no previous brief to compare against)"
        # Every claim states its source and its recency. This is the rule.
        line += (f"  \n  _source: {c.source} · as of "
                 f"{c.as_of.isoformat() if c.as_of else 'unknown'}_")
        out.append(line)

    out += ["", "## What looks wrong", ""]
    if not wrong:
        out.append(
            "_Nothing is reported here, and nothing can be yet: this brief "
            "carries no judgement until there are thresholds worth judging "
            "against. Deriving them from history would bless today's numbers. "
            "Read the section above as description, not as reassurance._")
    for c in sorted(wrong, key=lambda c: c.metric_key):
        out.append(f"- **{c.statement}**  \n  _source: {c.source} · as of "
                   f"{c.as_of.isoformat() if c.as_of else 'unknown'}_")

    out += ["", "## What it could not check", ""]
    if not uncomputed:
        out.append("_Nothing. Treat this with suspicion — on the current "
                   "grants there should always be something._")
    for c in sorted(uncomputed, key=lambda c: c.metric_key):
        out.append(f"- **{c.statement}** — {c.uncomputed_reason}")

    out += ["", "---", "",
            "_Every figure above states where it came from and how old it is. "
            "Anything this pass could not compute is listed rather than "
            "omitted. It decides nothing and proposes nothing._"]
    return "\n".join(out) + "\n"
