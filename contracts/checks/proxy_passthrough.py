#!/usr/bin/env python3
"""Every parameter the page sends is one the proxy forwards.

Run from the root of the worktree. Exits 0 if each declared page/proxy pair
agrees, 1 naming the parameters that are dropped, 2 if the check could not
establish anything at all.

WHY THIS EXISTS, AND WHAT IT REPLACES

It replaces two `paired_paths` groups in contracts/dd-analytics-frontend.yaml,
removed 10 Sep 2026 with contract_version 5. Both were written to stop one
thing: a page that sends a filter the proxy silently drops, which is FEAT-035 --
a control that appears to work, returns unfiltered rows, and agrees with its own
summary. Neither pairing could say that. What they said was "these two files
move together", which is a proxy for the property and is wrong in both
directions:

  IT REFUSES WORK THAT IS SAFE. A pairing cannot distinguish "the page sends a
  parameter the proxy does not forward" from "the page changed at all". Once
  both halves have landed -- task 49 for the dashboard, task 53 for the orders
  filters -- the parameters agree, and every later single-file change to either
  file is refused for a danger that is no longer reachable. Task 55 was the
  first to meet that: a click-to-filter change that introduced no parameter at
  all, held at a cost of £2.25 and a whole run.

  IT PASSES WORK THAT IS NOT. Co-movement is not agreement. Task 53 could have
  touched both files and still dropped a parameter -- added `has_discount` to
  the page, left it out of PASSTHROUGH -- and the pairing would have gone green
  on both halves having moved. The failure it existed to prevent fits inside a
  diff it accepts.

So this checks the property instead. It is directional, which the pairing could
not be: a proxy that forwards a name no page sends is dead code the next task
notices, and is not refused here. A page that sends a name no proxy forwards is
a merchant reading an unfiltered number as a filtered one, and is.

WHAT IT ESTABLISHES

That for each pair below, the set of query parameters the page attaches to that
proxy's URL is a subset of the set the proxy forwards to the API. Both sets are
read out of the files in the worktree.

WHAT IT DOES NOT

The other half of the chain: `page -> proxy -> API`. This is the first link.
The second -- that the proxy forwards nothing the API does not declare -- is
what FastAPI drops without an error and without a log line, and it is what the
comment at the top of each route.ts is about. contracts/checks/order_filters_shape.py
establishes it for the orders route by reading the FastAPI signature with `ast`.
There is no equivalent for the dashboard route, and this check does not pretend
to be one.

AND IT COVERS TWO PAIRS, NOT THE FRONTEND. `PAIRS` below names the orders page
and the analytics overview -- exactly the two the removed pairings named, and no
more. Measured against main at 6f3525a on 10 Sep 2026, the analytics tree holds
13 FURTHER page/proxy pairs of the same shape that nothing checks (churn
customers, customers, customers/cohorts, customers/top, geography,
geography/cities, orders/statuses, products, products/acquiring, revenue,
sources, sources/insights, sources/timeline), plus 6 with a dynamic path segment
that this check's exact-path matching cannot address at all. Every one of them
can ship the same silently-dropped filter.

They are not added here because replacing the pairings and widening the gate are
two decisions, and the second one is not made by the person making the first:
each new pair is a line that can stop every frontend task at could-not-run until
somebody teaches this check a shape. So READ THE GREEN NARROWLY -- it says two
pairs agree, not that the frontend does.

It also says nothing about whether a filter is CORRECT -- whether the value sent
is the row's value or the label rendered from it, whether the pager resets. Those
are behaviour, and only the render tests can speak to them.

HOW IT READS TYPESCRIPT, STATED PLAINLY BECAUSE IT IS THE WEAK PART

By regex, not by parse. There is no TypeScript AST available to a Python check
here, and `order_filters_shape.py` gets to use `ast` only because the files it
reads are Python. So this recognises the ONE shape both pages and both proxies
use today:

    const params = new URLSearchParams({ start: ..., end: ... })
    params.set('status', status)
    fetch(`/api/analytics/orders?${params}`)

    for (const key of PASSTHROUGH) { ... params.set(key, value) }

A page that builds its query some other way is not a page this can read, and
THAT IS REPORTED AS COULD-NOT-RUN (2), NEVER AS A PASS. A check that answers
"nothing to compare" with a green is the failure this codebase keeps making;
the whole reason the pairing it replaces was worth removing is that it had
become one. Every derived set is printed on success, so a green says what was
actually compared rather than leaving it to be assumed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: page, the proxy it calls, and the URL path that ties them together. The
#: `why` is printed in a refusal: it is the sentence about THIS pair, and
#: "payment_method is dropped" means nothing without it.
PAIRS = [
    {
        "page": "platform/app/(dashboard)/analytics/orders/page.tsx",
        "proxy": "platform/app/api/analytics/orders/route.ts",
        "url": "/api/analytics/orders",
        "why": "api/analytics/routes/orders.py has accepted payment_method, "
               "country, coupon and has_discount since task 2. A filter the "
               "page sends and this proxy drops returns EVERY row, with a "
               "summary that agrees with it -- four controls that appear to "
               "work and silently do nothing.",
    },
    {
        "page": "platform/app/(dashboard)/analytics/page.tsx",
        "proxy": "platform/app/api/analytics/dashboard/route.ts",
        "url": "/api/analytics/dashboard",
        "why": "task 28's comparison windows are reached through "
               "comparison_mode, compare_start and compare_end. A mode the "
               "page sends and this proxy drops leaves the API comparing the "
               "previous period while the page labels the answer as something "
               "else -- a page confidently describing a window it did not "
               "compare.",
    },
]

STRING = r"""['"]([^'"]+)['"]"""


def die(code: int, *lines: str) -> None:
    for line in lines:
        print(line)
    sys.exit(code)


def balanced(text: str, start: int, open_ch: str, close_ch: str) -> str:
    """The substring from `start` to the character closing what opens there."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


def page_params(text: str, url: str) -> tuple[set[str], str]:
    """What the page attaches to `url`, and why it could not tell if it cannot.

    Attribution is BY THE VARIABLE THE FETCH USES, not by every `params.set`
    in the file. The orders page calls two proxies -- /orders and
    /orders/statuses -- and a check that collected both files' worth of names
    into one set would report the statuses call's parameters against the orders
    route and be wrong in whichever direction the day fell.
    """
    fetches = re.findall(r"fetch\(\s*`([^`]*)`", text)
    matching = [f for f in fetches if f.split("?", 1)[0] == url]
    if len(matching) != 1:
        return set(), (f"found {len(matching)} fetch(`{url}?...`) calls in the "
                       f"page, expected exactly 1")

    query = matching[0].split("?", 1)[1] if "?" in matching[0] else ""
    if not query:
        return set(), f"the fetch of {url} attaches no query string"

    # `?${params}` -- the whole query is one URLSearchParams.
    var = re.fullmatch(r"\$\{(\w+)\}", query.strip())
    if not var:
        # `?start=${a}&end=${b}` -- names are literal in the template.
        inline = set(re.findall(r"[?&]?(\w+)=", query))
        if not inline:
            return set(), (f"could not read the query of {url}: it is neither "
                           f"${{params}} nor name=${{value}} pairs")
        return inline, ""

    name = var.group(1)
    found: set[str] = set()

    # The object literal it was constructed with.
    ctor = re.search(rf"\b{name}\s*=\s*new URLSearchParams\(", text)
    if not ctor:
        return set(), (f"the fetch of {url} sends `{name}`, and no "
                       f"`new URLSearchParams` is assigned to it")
    args = balanced(text, ctor.end() - 1, "(", ")")
    brace = args.find("{")
    if brace != -1:
        literal = balanced(args, brace, "{", "}")
        depth = 0
        for line in literal.splitlines():
            if depth <= 1:
                key = re.match(rf"\s*(?:{STRING}|(\w+))\s*:", line)
                if key:
                    found.add(key.group(1) or key.group(2))
            depth += line.count("{") + line.count("[")
            depth -= line.count("}") + line.count("]")

    # And everything set on it afterwards.
    found |= set(re.findall(rf"\b{name}\.(?:set|append)\(\s*{STRING}", text))

    if not found:
        return set(), (f"read no parameters at all from the {url} request. "
                       f"Either the page stopped sending any, or this check "
                       f"stopped being able to see them")
    return found, ""


def proxy_params(text: str) -> tuple[set[str], str]:
    """What the proxy forwards.

    Only arrays that are ITERATED count. A `const KNOWN_STATUSES = [...]` sitting
    beside the passthrough list is not a forwarding rule, and counting it would
    make this pass for a name nothing forwards.
    """
    arrays: dict[str, set[str]] = {}
    for m in re.finditer(r"\bconst\s+(\w+)\s*=\s*\[", text):
        literal = balanced(text, m.end() - 1, "[", "]")
        arrays[m.group(1)] = set(re.findall(STRING, literal))

    found: set[str] = set()
    for m in re.finditer(r"for\s*\(\s*const\s+\w+\s+of\s+", text):
        rest = text[m.end():]
        if rest.lstrip().startswith("["):
            start = m.end() + (len(rest) - len(rest.lstrip()))
            found |= set(re.findall(STRING, balanced(text, start, "[", "]")))
            continue
        ident = re.match(r"(\w+)", rest)
        if ident and ident.group(1) in arrays:
            found |= arrays[ident.group(1)]

    # A name forwarded on its own, outside any loop.
    found |= set(re.findall(rf"\bparams\.(?:set|append)\(\s*{STRING}", text))

    if not found:
        return set(), ("read no forwarded parameters at all. Either this proxy "
                       "forwards nothing, or it stopped using the shape this "
                       "check can read")
    return found, ""


def main() -> None:
    unreadable: list[str] = []
    broken: list[str] = []
    lines: list[str] = []

    for pair in PAIRS:
        page, proxy = Path(pair["page"]), Path(pair["proxy"])
        missing = [p for p in (page, proxy) if not p.exists()]
        if missing:
            unreadable += [f"  {p} does not exist" for p in missing]
            continue

        sends, why_not = page_params(page.read_text(), pair["url"])
        if why_not:
            unreadable.append(f"  {page}: {why_not}")
            continue
        forwards, why_not = proxy_params(proxy.read_text())
        if why_not:
            unreadable.append(f"  {proxy}: {why_not}")
            continue

        dropped = sorted(sends - forwards)
        if dropped:
            broken.append("\n".join([
                f"  {pair['url']}",
                *(f"      DROPPED  {name}" for name in dropped),
                f"      the page sends it and {proxy} does not forward it.",
                f"      why: {pair['why']}",
            ]))
        else:
            lines.append(f"  {pair['url']}: {len(sends)} sent, all forwarded "
                         f"({', '.join(sorted(sends))})")

    if unreadable:
        die(2, "FAIL: this check could not read what it compares.", "",
            *unreadable, "",
            "      Reported as 'could not run' (2), never as a pass. The shape "
            "it reads is in the docstring; a page or proxy that has moved away "
            "from it needs this check taught the new one, not deleted.")

    if broken:
        print("FAIL: the page sends a parameter its proxy drops.")
        print()
        for b in broken:
            print(b)
            print()
        die(1, "      FastAPI discards an undeclared name with no error and no "
               "log line, and the proxy discards it before that. Nothing fails, "
               "nothing is logged, and the table comes back unfiltered with a "
               "summary that agrees. Add the name to the proxy's forwarded "
               "list, or stop sending it.")

    print(f"PASS: {len(PAIRS)} page/proxy pair(s) agree.")
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
