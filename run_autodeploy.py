#!/usr/bin/env python
"""Entrypoint: deploy what the fleet merged, if the five refusals allow it.

    python run_autodeploy.py [--dry-run]

specs/unattended-operation.md §6.2. It decides WHETHER; api/deploy.sh decides
HOW, and is invoked rather than reimplemented -- it tags rollback images from
the running containers, migrates before the code swap, and asserts the alembic
head while the old containers still serve. Every one of those is a lesson
somebody paid for.
"""
from __future__ import annotations

import argparse
import logging

from console import autodeploy

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="decide and say so; do not invoke deploy.sh")
    args = ap.parse_args()
    autodeploy.run(dry_run=args.dry_run)
    # Exit 0 on a refusal: "not today" is the ordinary night and must not page.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
