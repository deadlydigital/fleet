"""Environment and connection configuration.

Secrets live in ~/fleet/.env and nowhere else. The process environment wins
over the file so tests can point FLEET_DSN / DD_DSN at a throwaway cluster
without touching the file that holds production credentials.
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
ENV_PATH = PROJECT_ROOT / ".env"
QUERY_DIR = PACKAGE_ROOT / "queries"

# The dead-man's switch endpoint. Absent from .env today; the heartbeat logs
# and continues rather than failing a run over a missing optional endpoint.
DEADMAN_URL_KEYS = ("HEARTBEAT_DEADMAN_URL", "DEADMAN_URL", "DEAD_MANS_SWITCH_URL")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def get(name: str, default: str | None = None) -> str | None:
    """Process environment first, then .env, then default."""
    if name in os.environ:
        return os.environ[name]
    return _parse_env_file(ENV_PATH).get(name, default)


def require(name: str) -> str:
    value = get(name)
    if not value:
        raise RuntimeError(f"{name} is not set (checked environment and {ENV_PATH})")
    return value


def fleet_dsn() -> str:
    """Fleet database: detector state. Written by this package."""
    return require("FLEET_DSN")


def dd_dsn() -> str:
    """deadly_digital: the observed system. Read-only, by role and by intent."""
    return require("DD_DSN")


def deadman_url() -> str | None:
    for key in DEADMAN_URL_KEYS:
        value = get(key)
        if value:
            return value
    return None
