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
class Ceiling:
    """A spending limit an objective declares, with its unit stated.

    `currency` is not optional and there is no default. A ceiling of "200"
    with an assumed unit is the defect this class exists to prevent: the
    biller answers in USD, this quarter's objective is in GBP, and the gap
    between them is about 25% -- comfortably enough to move a figure from one
    side of the line to the other while reading as precise.
    """
    amount: Decimal
    currency: str
    period: str

    def describe(self) -> str:
        return f"{self.amount} {self.currency}/{self.period}"


@dataclass(frozen=True)
class Objective:
    id: str
    statement: str
    weight: Decimal
    signals: tuple[str, ...]
    ceiling: "Ceiling | None" = None


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


def _ceiling(path: Path, entry: dict[str, Any]) -> "Ceiling | None":
    """Parse a ceiling block, REFUSING one that does not state its unit.

    Raising rather than defaulting is the whole value of the block. A missing
    currency is not a small omission to be filled in with the likely answer --
    it is the one field whose absence makes the number mean two things.
    """
    raw = entry.get("ceiling")
    if raw is None:
        return None
    missing = [k for k in ("amount", "currency", "period") if not raw.get(k)]
    if missing:
        raise RuntimeError(
            f"{path}: objective {entry['id']} declares a ceiling missing "
            f"{', '.join(missing)}. A ceiling without a currency is a number "
            f"whose unit has to be guessed, and guessing it wrong is a 25% "
            f"error in the direction of looking fine.")
    return Ceiling(amount=Decimal(str(raw["amount"])),
                   currency=str(raw["currency"]).strip().upper(),
                   period=str(raw["period"]).strip().lower())


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
                        signals=tuple(entry.get("signals") or ()),
                        ceiling=_ceiling(path, entry))
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
