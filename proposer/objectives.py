"""The quarter's objectives, read from the file that defines them.

The file is the authority. Nothing here caches it, nothing here stores a
second copy of a weight in the database, and a proposal that names an id the
file does not contain is refused before it reaches an INSERT.

The file states that the weights sum to 1.0. If they stop doing so the
ranking is no longer a ranking, so that is checked on load and the cycle
stops rather than ordering five items by numbers that mean nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from . import config

WEIGHT_SUM_TOLERANCE = Decimal("0.0001")


@dataclass(frozen=True)
class Objective:
    id: str
    statement: str
    weight: Decimal
    signals: tuple[str, ...]


@dataclass(frozen=True)
class Objectives:
    quarter: str
    path: Path
    by_id: dict[str, Objective]
    out_of_scope: tuple[str, ...]
    constraints: tuple[str, ...]

    def weight(self, objective_ref: str | None) -> Decimal:
        if objective_ref is None:
            raise KeyError("a proposal with no objective has no weight")
        return self.by_id[objective_ref].weight

    def contains(self, objective_ref: str) -> bool:
        return objective_ref in self.by_id

    def require(self, objective_ref: str) -> Objective:
        if objective_ref not in self.by_id:
            raise KeyError(
                f"{objective_ref!r} is not an objective in {self.path.name}; "
                f"known: {', '.join(sorted(self.by_id))}")
        return self.by_id[objective_ref]


def load(path: Path | str | None = None) -> Objectives:
    if path is None:
        cycle = config.load_cycle_config()
        path = config.PROJECT_ROOT / cycle["objectives_file"]
    path = Path(path)
    if not path.exists():
        raise RuntimeError(f"objectives file missing: {path}")

    doc: dict[str, Any] = yaml.safe_load(path.read_text())
    raw = doc.get("objectives") or []
    if not raw:
        raise RuntimeError(f"{path} declares no objectives")

    by_id: dict[str, Objective] = {}
    total = Decimal(0)
    for entry in raw:
        weight = Decimal(str(entry["weight"]))
        total += weight
        obj = Objective(id=entry["id"],
                        statement=" ".join(str(entry["statement"]).split()),
                        weight=weight,
                        signals=tuple(entry.get("signals") or ()))
        if obj.id in by_id:
            raise RuntimeError(f"{path}: objective {obj.id} declared twice")
        by_id[obj.id] = obj

    if abs(total - Decimal(1)) > WEIGHT_SUM_TOLERANCE:
        raise RuntimeError(
            f"{path}: objective weights sum to {total}, not 1.0. Ranking by "
            f"weight would be meaningless, so the cycle stops here.")

    return Objectives(quarter=str(doc.get("quarter", "")),
                      path=path,
                      by_id=by_id,
                      out_of_scope=tuple(doc.get("out_of_scope") or ()),
                      constraints=tuple(doc.get("constraints") or ()))
