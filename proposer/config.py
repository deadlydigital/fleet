"""Connections and thresholds for the proposal layer.

Two DSNs, not one. FLEET_READER_DSN reads track 1; FLEET_PROPOSER_DSN writes
proposals. A single principal holding both would make the read path and the
write path the same identity, and the separation is the only reason the
database can say "this row was written by something that cannot read what it
is judging".

Thresholds live in cycle.yaml for the same reason track 1 keeps them in
detector_registry: deciding that an issue open three days is worth mentioning
is a judgement that gets retuned, and retuning it must not be a redeploy.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from detectors import config as base_config

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
QUERY_DIR = PACKAGE_ROOT / "queries"
CYCLE_CONFIG_PATH = PROJECT_ROOT / "cycle.yaml"


def get(name: str, default: str | None = None) -> str | None:
    return base_config.get(name, default)


def reader_dsn() -> str:
    """Track 1's tables, SELECT only, as fleet_detector_reader."""
    return base_config.require("FLEET_READER_DSN")


def proposer_dsn() -> str:
    """proposals and proposal_evidence, INSERT only, as fleet_proposer."""
    return base_config.require("FLEET_PROPOSER_DSN")


def precedent_dsn() -> str:
    """The decision log, read as the identity 012 granted it to.

    Deliberately NOT `reader_dsn()`. 010 refuses `fleet_detector_reader` any
    sight of `decision_log` -- the layer being graded does not see the grade
    -- and that refusal is kept. This is the detector identity the daily
    brief already reads the log with, which can read it and write nothing.
    """
    return base_config.require("FLEET_DSN")


def console_dsn() -> str:
    """The review command, as fleet_console: the only role that may decide.

    A separate login from the migration identity on purpose. 001 says
    listmonk is a migration identity and never a runtime principal, and a
    review tool run every morning is a runtime principal.
    """
    return base_config.require("FLEET_CONSOLE_DSN")


def parse_interval(text: str | timedelta) -> timedelta:
    """'3 days', '90 minutes' -> timedelta. Postgres spelling, one unit."""
    if isinstance(text, timedelta):
        return text
    parts = str(text).split()
    if len(parts) != 2:
        raise ValueError(f"interval {text!r} must read like '3 days'")
    amount, unit = parts
    unit = unit.rstrip("s") + "s"
    if unit not in {"seconds", "minutes", "hours", "days", "weeks"}:
        raise ValueError(f"unsupported interval unit in {text!r}")
    return timedelta(**{unit: float(amount)})


def load_cycle_config(path: Path | None = None) -> dict[str, Any]:
    path = path or Path(os.environ.get("FLEET_CYCLE_CONFIG", CYCLE_CONFIG_PATH))
    if not path.exists():
        raise RuntimeError(f"cycle configuration missing: {path}")
    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} is not a mapping")
    return loaded
