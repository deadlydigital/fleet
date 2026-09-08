#!/usr/bin/env python3
"""Entrypoint: python run_cycle.py [--dry-run]

The daily observation cycle. Reads track 1 as fleet_detector_reader, reads
the decision log as dd_detector_login, writes proposals as fleet_proposer,
and does nothing else. No model is called, no row outside proposals and
proposal_evidence is written, and deadly_digital is not touched at all --
none of the three roles can reach it.

THE THIRD READ IS PRECEDENT, AND IT IS AN OUTPUT. The log is stated above
the ranking and never given to it: `rank()` is not passed it and
`findings.compute()` has already run by the time it is fetched. 010 refuses
fleet_detector_reader any sight of the log precisely so that a layer cannot
learn what gets approved and propose that instead, and that refusal stands
-- the read side of this layer still cannot see it and the write side
certainly cannot. What replaces the process-level half of it is the
structural property, which is proven in tests/revert_guards.py rather than
promised here.

Exit codes:
    0  the cycle completed, whether or not it had anything to say
    1  the cycle could not read its inputs or could not write its output
    2  a reading was stale, so part of the morning's answer is missing
"""
from __future__ import annotations

import argparse
import logging
import sys

from proposer import config, cycle as cycle_module
from proposer.objectives import load as load_objectives

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_STALE = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="compute and print, write nothing")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("run_cycle")

    cycle_config = config.load_cycle_config()
    objectives = load_objectives(config.PROJECT_ROOT / cycle_config["objectives_file"])

    try:
        result = cycle_module.run_cycle(cycle_config=cycle_config,
                                        objectives=objectives,
                                        dry_run=args.dry_run)
    except Exception as exc:
        log.exception("cycle failed: %s", exc)
        return EXIT_FAILED

    print(cycle_module.report(result, objectives))

    if result.adapter_output.stale:
        log.warning("%d reading(s) were stale; findings resting on them were "
                    "not computed", len(result.adapter_output.stale))
        return EXIT_STALE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
