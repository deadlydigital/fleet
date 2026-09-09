"""The console's one connection, and the repositories it reads diffs from.

One DSN, and it belongs to `fleet_console_reader_login`, which holds SELECT
and nothing else. That is checked at startup rather than trusted: a console
running as a role that could write is the failure this design exists to make
impossible, and it would be invisible until something went wrong.
"""
from __future__ import annotations

import os
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


def console_writer_dsn() -> str:
    """fleet_console: the only identity the database accepts a task verdict from.

    Used by exactly two routes, accept and reject, and by nothing that renders
    a page. Every read on every page goes through console_reader_dsn(). Two
    connections rather than one role widened -- the same rule the proposal
    layer follows, and for the same reason: the separation is only real if the
    reading identity and the writing identity are different principals.
    """
    return base_config.require("FLEET_CONSOLE_DSN")


# Where the accept route builds its throwaway trial merge.
#
# Deliberately NOT runner.yaml's worktree_root, which is /home/ubuntu/.fleet-
# worktrees. The console runs under ProtectHome=read-only with ReadWritePaths
# naming the platform repository and nothing else -- that grant exists so a
# merge can write to the checkout, and widening it so scratch data has
# somewhere to live would trade a real boundary for a temporary directory.
#
# PrivateTmp=true gives the unit a /tmp no other process can see. It is
# writable, it is invisible to the runner and to anything else on the box, and
# systemd destroys it when the service stops.
#
# THIS SETTING WAS ONCE MISTAKEN FOR THE WHOLE FIX, and the comment here said
# so: that a writable private /tmp was "the whole of what a trial worktree
# needs". It was not. A linked worktree also writes into the repository it
# links from -- its admin directory, and its merge objects -- so pointing the
# worktree's directory at a writable place left the half that fails untouched.
# The trial is a clone now, which is what actually confines it here; see
# runner.worktree.create_trial_clone. Choosing the root is still a real
# choice, but it was never sufficient on its own.
#
# test_console_decide.py ties this to the unit file, so pointing it back into
# home fails a test rather than failing an Accept.
TRIAL_ROOT = Path("/tmp/fleet-console-trials")


def trial_root() -> Path:
    """The trial root, overridable so tests need not write to the real one."""
    return Path(os.environ.get("FLEET_CONSOLE_TRIAL_ROOT", TRIAL_ROOT))
