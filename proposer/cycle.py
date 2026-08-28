"""The observation-only cycle.

Daily. Reads the detectors adapter and this layer's own record, computes
findings that are arithmetic, ranks them by the weight the objectives file
gives their objective, cuts at five, and writes them as OBSERVATION
proposals.

What it deliberately does not do:

  * recommend anything. An observation says what is true; deciding what to do
    about it is the next layer's job and the human's call.
  * rank by anything except objective weight. No severity score, no impact
    estimate, no composite. The database refuses an OBSERVATION carrying an
    effort or impact estimate, so this is enforced and not merely intended.
  * call a model. Every finding is a count against a threshold.
  * write anywhere except proposals and proposal_evidence, as two roles that
    cannot do anything else.

The five-item cap is the mechanism, not a limitation. A layer that can say
twenty things a day will be ignored by the second week; being forced to cut
is what makes the ranking mean something. Everything cut is printed, so the
cut is visible rather than silent.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Sequence

import psycopg
from psycopg.types.json import Json

from . import config, detector_adapter, findings as findings_module
from .adapter import AdapterOutput
from .detector_adapter import DetectorsAdapter
from .findings import KIND_RISK, Finding, FindingRun
from .history import ProposalHistory
from .objectives import Objectives, load as load_objectives

log = logging.getLogger(__name__)

# The database enforces this. It is repeated here so the cycle can report
# what it cut instead of discovering the cap by having an INSERT rejected.
MAX_ITEMS = 5


@dataclass
class Ranked:
    finding: Finding
    weight: Any  # Decimal, or None for a RISK


@dataclass
class CycleResult:
    cycle_id: uuid.UUID
    started_at: datetime
    adapter_output: AdapterOutput
    computed: list[Finding] = field(default_factory=list)
    suppressed: list[tuple[Finding, datetime]] = field(default_factory=list)
    proposed: list[Finding] = field(default_factory=list)
    dropped: list[Finding] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    written: list[int] = field(default_factory=list)
    dry_run: bool = False


def validate_config(cycle_config: dict[str, Any], objectives: Objectives) -> None:
    """Every objective the mapping names must exist in the file.

    A typo here would otherwise produce a proposal pointing at an objective
    nobody has, which reads exactly like a real one. Checked before anything
    is read, so the cycle fails at the start rather than at the INSERT.
    """
    problems: list[str] = []
    for finding_type, mapping in (cycle_config.get("objective_map") or {}).items():
        refs = [mapping] if isinstance(mapping, str) else list(mapping.values())
        for ref in refs:
            if not objectives.contains(ref):
                problems.append(f"objective_map[{finding_type}] -> {ref!r}")
    if problems:
        raise RuntimeError(
            f"cycle.yaml names objectives that {objectives.path.name} does not "
            f"contain: {', '.join(problems)}")


def rank(finding: Finding, objectives: Objectives):
    """Order: risks, then objective weight, then finding key.

    Weight is the only score. A RISK has no objective by construction and so
    cannot be weighed at all, which leaves two choices: always above the
    weighted items or always below them. Below means the cap can silently
    drop something actively breaking in favour of a well-weighted
    observation, so risks go first. That is a categorical rule, not a
    priority score, and it is the only ordering here that weight does not
    decide.

    The final term is the finding key: arbitrary, but the same arbitrary
    order every morning, so two runs over the same facts propose the same
    five things.
    """
    if finding.kind == KIND_RISK:
        return (0, 0, finding.finding_key)
    return (1, -objectives.weight(finding.objective_ref), finding.finding_key)


def _demote_out_of_scope(finding: Finding, cycle_config: dict[str, Any]) -> Finding:
    out_of_scope = set(cycle_config.get("out_of_scope_products") or ())
    if finding.area in out_of_scope:
        return finding.as_risk(
            f"{finding.area} is out of scope for the quarter; the objectives "
            f"file allows it to be raised only as something actively breaking "
            f"or costing money")
    return finding


def _as_risk_if_unmapped(finding: Finding) -> Finding:
    if finding.objective_ref is not None:
        return finding
    return finding.as_risk(
        f"no objective is mapped to {finding.finding_type} in cycle.yaml, and "
        f"the objectives file says a proposal that names no objective is a risk")


def run_cycle(*, reader_dsn: str | None = None, proposer_dsn: str | None = None,
              cycle_config: dict[str, Any] | None = None,
              objectives: Objectives | None = None,
              dry_run: bool = False) -> CycleResult:
    cycle_config = cycle_config if cycle_config is not None else config.load_cycle_config()
    objectives = objectives or load_objectives(
        config.PROJECT_ROOT / cycle_config["objectives_file"])
    validate_config(cycle_config, objectives)

    adapter = DetectorsAdapter(reader_dsn, cycle_config)
    with detector_adapter.connect(reader_dsn) as reader:
        out = adapter.read(reader)
        history = ProposalHistory.read(reader)

    now = out.fetched_at
    result = CycleResult(cycle_id=uuid.uuid4(), started_at=now,
                         adapter_output=out, dry_run=dry_run)

    run: FindingRun = findings_module.compute(out, history, objectives,
                                              cycle_config, now)
    result.skipped = list(run.skipped)

    prepared = [_as_risk_if_unmapped(_demote_out_of_scope(f, cycle_config))
                for f in run.findings]
    result.computed = prepared

    # Suppression before ranking: a finding already said is not competing for
    # one of today's five.
    repropose_after = config.parse_interval(cycle_config["repropose_after"])
    fresh: list[Finding] = []
    for finding in prepared:
        last = history.last_proposed(finding.finding_key)
        if last is not None and (now - last) <= repropose_after:
            result.suppressed.append((finding, last))
        else:
            fresh.append(finding)

    ordered = sorted(fresh, key=lambda f: rank(f, objectives))
    result.proposed = ordered[:MAX_ITEMS]
    result.dropped = ordered[MAX_ITEMS:]

    if not dry_run and result.proposed:
        result.written = write(result.proposed, result.cycle_id, proposer_dsn)

    return result


def write(proposals: Sequence[Finding], cycle_id: uuid.UUID,
          dsn: str | None = None) -> list[int]:
    """Insert as fleet_proposer: proposals and their evidence, nothing else.

    One transaction per proposal. The evidence constraint is checked at
    commit, so a proposal whose evidence fails to insert takes only itself
    down and the rest of the morning still gets said.
    """
    written: list[int] = []
    with psycopg.connect(dsn or config.proposer_dsn()) as conn:
        for finding in proposals:
            if not finding.evidence:
                # The database would refuse this at commit anyway. Refusing
                # it here means the reason appears in the log rather than as
                # a constraint violation.
                raise ValueError(
                    f"{finding.finding_key} carries no evidence and would be "
                    f"rejected at commit")
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO proposals
                        (cycle_id, kind, area, finding_key, title, body,
                         objective_ref, reversibility, confidence)
                    VALUES (%(cycle)s, %(kind)s, %(area)s, %(key)s, %(title)s,
                            %(body)s, %(objective)s, %(rev)s, %(confidence)s)
                    RETURNING id
                    """,
                    {"cycle": cycle_id, "kind": finding.kind,
                     "area": finding.area, "key": finding.finding_key,
                     "title": finding.title, "body": finding.body,
                     "objective": finding.objective_ref,
                     "rev": finding.reversibility,
                     "confidence": finding.confidence}).fetchone()
                proposal_id = row[0]
                for evidence in finding.evidence:
                    conn.execute(
                        """
                        INSERT INTO proposal_evidence
                            (proposal_id, adapter, query_key, value,
                             fetched_at, freshness_bound, stale)
                        VALUES (%(pid)s, %(adapter)s, %(key)s, %(value)s,
                                %(fetched)s, %(bound)s, %(stale)s)
                        """,
                        {"pid": proposal_id, "adapter": evidence.adapter,
                         "key": evidence.query_key, "value": Json(evidence.value),
                         "fetched": evidence.fetched_at,
                         "bound": evidence.freshness_bound,
                         "stale": evidence.stale})
            written.append(proposal_id)
            log.info("proposal %s %s", proposal_id, finding.finding_key)
    return written


# ---- reporting ------------------------------------------------------------

def report(result: CycleResult, objectives: Objectives) -> str:
    lines: list[str] = []
    lines.append(f"fleet observation cycle {result.cycle_id}")
    lines.append(f"{result.started_at.isoformat(timespec='seconds')}"
                 f"{'  (dry run, nothing written)' if result.dry_run else ''}")
    lines.append("")
    lines.append(result.adapter_output.describe())

    stale = result.adapter_output.stale
    if stale:
        lines.append("")
        lines.append("STALE READINGS -- no finding was computed from these:")
        for reading in stale:
            lines.append(f"  {reading.describe()}")

    lines.append("")
    lines.append(f"{len(result.computed)} findings computed, "
                 f"{len(result.suppressed)} suppressed, "
                 f"{len(result.dropped)} cut by the {MAX_ITEMS}-item cap, "
                 f"{len(result.proposed)} proposed")

    if result.skipped:
        lines.append("")
        lines.append("not computed:")
        for finding_type, reason in result.skipped:
            lines.append(f"  {finding_type}: {reason}")

    if result.proposed:
        lines.append("")
        lines.append("proposed:")
        for n, finding in enumerate(result.proposed, start=1):
            lines.extend(_render(n, finding, objectives, result))
    else:
        lines.append("")
        lines.append("proposed: nothing. Nothing crossed a threshold today.")

    if result.dropped:
        lines.append("")
        lines.append(f"cut by the {MAX_ITEMS}-item cap (not written, not lost -- "
                     f"they will rank again tomorrow):")
        for finding in result.dropped:
            lines.append(f"  [{_label(finding, objectives)}] {finding.title}")

    if result.suppressed:
        lines.append("")
        lines.append("suppressed, already proposed:")
        for finding, last in result.suppressed:
            lines.append(f"  [{last:%Y-%m-%d}] {finding.title}")

    return "\n".join(lines)


def _label(finding: Finding, objectives: Objectives) -> str:
    if finding.kind == KIND_RISK:
        return "RISK"
    weight = objectives.weight(finding.objective_ref)
    return f"{finding.objective_ref} w={weight}"


def _render(n: int, finding: Finding, objectives: Objectives,
            result: CycleResult) -> list[str]:
    written = ""
    if not result.dry_run and result.written:
        index = result.proposed.index(finding)
        if index < len(result.written):
            written = f"  -> proposal {result.written[index]}"
    lines = [f"  {n}. [{finding.kind} {_label(finding, objectives)}] "
             f"{finding.title}{written}"]
    lines += [f"     {line}" for line in finding.body.splitlines()]
    for evidence in finding.evidence:
        flag = " STALE" if evidence.stale else ""
        lines.append(f"     evidence: {evidence.adapter}.{evidence.query_key} "
                     f"@ {evidence.fetched_at.isoformat(timespec='seconds')}{flag}")
    return lines
