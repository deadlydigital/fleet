#!/usr/bin/env python3
"""Entrypoint: python run_detector.py <detector_key>

Shadow mode. This process writes detector state to the fleet database, reads
deadly_digital, and alerts nobody.

Exit codes:
    0  the run closed OK or PARTIAL, or the window was already done
    1  the run closed ERROR, or it could not be opened at all
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from detectors import base
from detectors.heartbeat import HeartbeatDetector
from detectors.reconciliation import ReconciliationDetector

DETECTORS = {
    ReconciliationDetector.key: ReconciliationDetector,
    HeartbeatDetector.key: HeartbeatDetector,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("detector_key", choices=sorted(DETECTORS))
    parser.add_argument("--issue-key-version", type=int, default=None,
                        help="disambiguate when the registry holds several versions")
    parser.add_argument("--product", default=None)
    parser.add_argument("--slot-end", type=datetime.fromisoformat, default=None,
                        help="execute a specific settled slot instead of the current one")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("run_detector")

    detector = DETECTORS[args.detector_key]()
    with base.connect_fleet() as fleet:
        try:
            result = base.execute(detector, fleet,
                                  issue_key_version=args.issue_key_version,
                                  product=args.product, slot_end=args.slot_end)
        except Exception as exc:
            log.exception("%s could not run: %s", args.detector_key, exc)
            return 1

    log.info("%s run=%s status=%s observations=%s evaluated=%s failed=%s",
             args.detector_key, result.run_id, result.status,
             result.observations_created, result.subjects_evaluated,
             result.subjects_failed)
    return 1 if result.status == base.STATUS_ERROR else 0


if __name__ == "__main__":
    sys.exit(main())
