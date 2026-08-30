#!/usr/bin/env python3
"""Acceptance check for the acquiring-products page task.

Run from the root of the worktree. Lives in the fleet repository, so the
agent -- which works in a worktree of the platform repo -- cannot write to
what judges it.

It checks the two files exist and that the page surfaces the parts of the
response the endpoint went to trouble to provide. That last part is the
whole point: `tsc` and the existing 298 tests would both pass for a page
that renders the ranking and silently drops the truncation notice, and such
a page reads as "here is everything" while showing the top 200 of 785.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROUTE = Path("platform/app/api/analytics/products/acquiring/route.ts")
PAGE = Path("platform/app/(dashboard)/analytics/products/acquiring/page.tsx")
SIDEBAR = Path("platform/components/layout/Sidebar.tsx")


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if not ROUTE.exists():
        return fail(f"{ROUTE} does not exist; the endpoint is still unreachable")
    if not PAGE.exists():
        return fail(f"{PAGE} does not exist")

    route = ROUTE.read_text()
    for needle, why in [
        ("/api/analytics/products/acquiring", "the proxy does not call the endpoint"),
        ("X-DD-API-Key", "the proxy does not pass the tenant api key"),
        ("tenantId", "the proxy does not guard on the session's tenant"),
        ("401", "the proxy does not return 401 without a session"),
    ]:
        if needle not in route:
            return fail(f"{ROUTE.name}: {why}")
    for param in ("start", "end", "limit"):
        if f"'{param}'" not in route and f'"{param}"' not in route:
            return fail(f"{ROUTE.name} does not forward {param!r}")

    page = PAGE.read_text()

    # The reconciliation and the cap. A ranking on its own is the failure the
    # endpoint's "No silent caps" comment exists to prevent.
    for needle, why in [
        ("coverage", "the page does not reference `coverage`"),
        ("truncation", "the page does not reference `truncation`"),
        ("is_truncated", "the page never tests `truncation.is_truncated`, so a "
                         "truncated ranking renders as though it were complete"),
        ("products_total", "the page does not show how many products exist"),
    ]:
        if needle not in page:
            return fail(f"{PAGE.name}: {why}")

    # Both customer counts, which are different numbers on purpose.
    for needle in ("customers_acquired", "customers_present_on_first_order"):
        if needle not in page:
            return fail(f"{PAGE.name} does not render {needle}; the two counts "
                        f"answer different questions and only one of them sums")

    if SIDEBAR.exists():
        sidebar = SIDEBAR.read_text()
        if "/analytics/products/acquiring" not in sidebar:
            return fail("Sidebar.tsx does not link the new page, so it is "
                        "reachable only by typing the URL")

    print("ok: proxy and page exist, the proxy guards and forwards, and the page "
          "surfaces coverage, truncation and both customer counts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
