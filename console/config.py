"""The console's one connection, and the repositories it reads diffs from.

One DSN, and it belongs to `fleet_console_reader_login`, which holds SELECT
and nothing else. That is checked at startup rather than trusted: a console
running as a role that could write is the failure this design exists to make
impossible, and it would be invisible until something went wrong.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from detectors import config as base_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def console_reader_dsn() -> str:
    """SELECT on the sixteen tables the three pages need, and nothing else.

    Deliberately not FLEET_READER_DSN: that role is the proposal cycle's read
    identity, and widening it would give that layer sight of `decisions` --
    the property 002's assertion B7 exists to keep. Deliberately not
    FLEET_CONSOLE_DSN either: it can insert a decision and update a task, and
    a page that cannot write should not hold a credential that can.
    """
    return base_config.require("FLEET_CONSOLE_READER_DSN")


def repo_root() -> Path:
    """Where the checkouts live, so a diff can be read off disk.

    The branch is the artifact and the database records what happened to it,
    so the diff is never stored -- it is read from git at render time.
    """
    path = Path(__file__).resolve().parent.parent / "runner.yaml"
    settings: dict[str, Any] = yaml.safe_load(path.read_text())
    return Path(settings["repo_root"])
