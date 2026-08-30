#!/usr/bin/env python3
"""Acceptance check for the order-list filter task.

Run from the root of the worktree. Reads both files with `ast` rather than
importing them, so it needs no database, no FastAPI and no settings.

Lives in the fleet repository. The agent works in a worktree of the platform
repo and cannot write here, so what judges it is out of reach by
construction rather than by being on a protected-path list.

It checks shape, not behaviour, and that limit is the point: there is no test
gate for backend work (`TEST-004`), so this establishes that the parameters
exist, reach the query, and bind rather than interpolate. Whether the SQL
returns the right rows is a question for a human reading the diff.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROUTE = Path("api/analytics/routes/orders.py")
QUERY = Path("api/analytics/services/order_query.py")
PARAMS = ("payment_method", "country", "coupon", "has_discount")
COLUMNS = ("payment_method", "billing_country", "coupon_code", "discount_total")


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def find_function(tree: ast.AST, name: str):
    return next((n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == name), None)


def main() -> int:
    for path in (ROUTE, QUERY):
        if not path.exists():
            return fail(f"{path} does not exist")

    route_tree = ast.parse(ROUTE.read_text())
    query_tree = ast.parse(QUERY.read_text())

    # 1. The route declares all four.
    get_orders = find_function(route_tree, "get_orders")
    if get_orders is None:
        return fail("get_orders is gone from the route")
    route_args = {a.arg for a in get_orders.args.args + get_orders.args.kwonlyargs}
    missing = [p for p in PARAMS if p not in route_args]
    if missing:
        return fail(f"get_orders does not declare {missing}")

    # 2. list_orders accepts all four.
    list_orders = find_function(query_tree, "list_orders")
    if list_orders is None:
        return fail("list_orders is gone")
    q_args = {a.arg for a in list_orders.args.args + list_orders.args.kwonlyargs}
    missing = [p for p in PARAMS if p not in q_args]
    if missing:
        return fail(f"list_orders does not accept {missing}")

    # 3. The route forwards them. A parameter declared and dropped is worse
    #    than one that is absent: the caller is told it was applied.
    call = next((n for n in ast.walk(get_orders)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "list_orders"), None)
    if call is None:
        return fail("get_orders no longer calls list_orders")
    forwarded = {kw.arg for kw in call.keywords if kw.arg}
    missing = [p for p in PARAMS if p not in forwarded]
    if missing:
        return fail(f"get_orders declares but does not forward {missing}")

    # 4. Every predicate mentioning one of the four columns binds its value.
    #    An f-string here would be caller input concatenated into SQL.
    for node in ast.walk(list_orders):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "where"):
            continue
        arg = node.args[0] if node.args else None
        if isinstance(arg, ast.JoinedStr):
            return fail("a WHERE predicate is an f-string; caller values must bind")
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            text = arg.value
            if any(c in text for c in COLUMNS) and ":" not in text:
                # discount_total > 0 is a literal comparison with no caller
                # value in it, so it needs no bind.
                if "discount_total" not in text:
                    return fail(f"predicate {text!r} names a column but binds nothing")

    # 5. The summary and the row query must describe the same rows.
    source = QUERY.read_text()
    if source.count("where_clause") < 3:
        return fail("where_clause is no longer built once and used for both the "
                    "summary aggregate and the row query")

    print(f"ok: {', '.join(PARAMS)} are declared, accepted, forwarded and bound; "
          f"the summary shares the row query's WHERE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
