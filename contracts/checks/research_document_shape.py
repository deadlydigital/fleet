#!/usr/bin/env python3
"""Acceptance check for a research task.

Run from the root of the worktree. Reads FLEET_CHANGED_FILES, which the runner
derived from git.

WHAT THIS CAN ENFORCE, AND WHAT IT CANNOT

It enforces a floor on FORM, and one narrow kind of groundedness. It checks
that the document exists, is substantial, is dated, names evidence, says what
it could not establish, and that every repo path it cites in a checkable form
actually resolves.

It cannot check whether the analysis is correct, whether the evidence supports
the claim, whether a cited URL says what the document says it says, whether
the "could not verify" section is honest or perfunctory, or whether the
ordering reflects real judgement. `specs/metorik-gap.md` is the standard
because it overturned DD's own gap document in four places on evidence. No
mechanical check can require that.

So this keeps out documents that are obviously ungrounded. It cannot certify
one that is grounded, and a research branch therefore needs reading in a way a
code branch does not. That asymmetry is the point of writing it down here
rather than letting a green tick imply more than it establishes.

THE PATH CHECK IS DELIBERATELY NARROW, and it was measured before it was
chosen. Applied loosely to `metorik-gap.md` it flagged 10 citations, all ten
false positives: URL routes (`/analytics/coupons`), MIME types (`text/csv`),
field lists (`utm_source/medium/campaign`). It would have failed the gold
standard. Narrowed to citations with a directory component AND a file
extension it flags zero there -- but it then checks 8 of 48 citations in that
document and NOTHING at all in `refund-hook.md`, whose evidence is database
queries and shell output. A check that fires on nothing is not a check; it is
just not a false alarm.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

MIN_WORDS = 800
MIN_LINES = 60
MIN_SECTIONS = 3
MIN_EVIDENCE = 5
MIN_LIMITS_WORDS = 40
DATE_MAX_AGE_DAYS = 7

PLATFORM = Path.home() / "deadly-digital-platform"
FLEET = Path.home() / "fleet"

# A heading that admits the limits of the work. Both exemplars carry one and
# they phrase it differently, which is why this is a set rather than a
# sentence: metorik-gap.md says "What I could not verify"; refund-hook.md says
# "What remains" and "What would settle the question definitively". Requiring
# one wording would have failed the second document, and it is the standard.
#: A NUMBERED HEADING IS STILL A HEADING, and this cost £4.90 to learn.
#:
#: Task 64 produced a 669-line batch-11 document with `## 8. What I could not
#: establish` and was refused for "no section saying what could not be
#: verified". The section was there; the `8.` sat between the hashes and the
#: words this pattern looks for. The two documents it was modelled on number
#: nothing, so the requirement had only ever been met by imitation -- and no
#: spec states it, including the one that produced batch 10 successfully.
#:
#: `(?:\d+[.)]?\s*)?` rather than a looser prefix: a number and its
#: punctuation, and nothing else, so a heading that merely CONTAINS these words
#: further along still does not count as the section.
LIMITS_RE = re.compile(
    r"^(?P<hashes>#{1,4})\s*(?:\d+[.)]?\s*)?("
    r"(what\s+)?(i|we)?\s*(could\s+not|couldn'?t|cannot|can'?t)\s+"
    r"(verify|establish|check|confirm|determine)"
    r"|limitations?\b"
    r"|what\s+(is|was)\s+not\s+(verified|established|checked)"
    r"|what\s+remains?\b"
    r"|what\s+would\s+settle"
    r"|open\s+questions?\b"
    r"|unresolved\b"
    r")", re.I | re.M)

BACKTICKED = re.compile(r"`([^`\n]+)`")
URL_RE = re.compile(r"https?://[^\s)>\]]+")
CODE_EXT = (".py", ".sql", ".ts", ".tsx", ".md", ".yaml", ".yml", ".js",
            ".json", ".ini", ".toml", ".sh")
DATE_RE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b|"
                     r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(20\d\d)\b")


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def repo_roots() -> set[str]:
    """Top-level directory names of the repositories actually on disk.

    The resolve check applies ONLY to citations beginning with one of these.
    `refund-hook.md` cites `deadly-digital-connector.php:1264` and says in as
    many words that the plugin source is not in this repository -- demanding
    that it resolve would fail a document for being honest about where its
    evidence came from.
    """
    roots = set()
    for repo in (Path.cwd(), PLATFORM, FLEET):
        if repo.exists():
            roots |= {d.name for d in repo.iterdir()
                      if d.is_dir() and not d.name.startswith(".")}
    return roots


def path_citations(text: str) -> set[str]:
    """Backticked strings that are unambiguously paths INTO a repo we hold.

    Must begin with a real top-level directory of one of those repos, have a
    directory component, and end in a file extension. Everything else -- URL
    routes, MIME types, field lists, references to code that lives elsewhere --
    is not checkable and is not pretended to be.
    """
    roots = repo_roots()
    out = set()
    for raw in BACKTICKED.findall(text):
        s = raw.split(":")[0].strip()
        if not s or s[0] in "/~…$" or s.startswith(("http", "SELECT")):
            continue
        if " " in s or "{" in s or "*" in s:
            continue
        if "/" not in s or not s.endswith(CODE_EXT):
            continue
        if s.split("/", 1)[0] not in roots:
            continue
        out.add(s)
    return out


# A backticked token that is a reference rather than prose: a path, a
# dotted identifier, a file:line, a commit sha, a column name. Counted as
# evidence whether or not it is checkable -- refund-hook.md's evidence is
# line numbers in a plugin that is not in this repository, and that is still
# evidence somebody can go and look at.
REFERENCE_RE = re.compile(r"^[A-Za-z0-9_./:@-]{3,80}$")


def evidence_tokens(text: str) -> set[str]:
    out = set()
    for raw in BACKTICKED.findall(text):
        t = raw.strip()
        if " " in t or not REFERENCE_RE.match(t):
            continue
        if not any(ch in t for ch in "./:_-"):
            continue
        out.add(t)
    return out


def resolves(rel: str) -> bool:
    # The worktree FIRST. A document citing a file in its own change -- the
    # evidence pack, a sibling document -- must resolve against the tree being
    # checked, not against the main checkout where that file does not exist
    # yet. Omitting this failed a correct document for citing the readings it
    # was given.
    for root in (Path.cwd(), PLATFORM, FLEET):
        if (root / rel).exists():
            return True
        if next(iter(root.rglob(Path(rel).name)), None):
            return True
    return False


def main() -> int:
    changed = [p for p in os.environ.get("FLEET_CHANGED_FILES", "").splitlines()
               if p.strip()]
    docs = [p for p in changed if p.endswith(".md")]
    if not docs:
        return fail("the change contains no markdown document. A research task "
                    "produces a document; that is its artifact.")
    if len(changed) > len(docs):
        return fail(f"the change touches non-markdown files: "
                    f"{sorted(set(changed) - set(docs))}")

    for rel in docs:
        path = Path(rel)
        if not path.exists():
            return fail(f"{rel} is in the diff but not on disk")
        text = path.read_text()
        words = len(text.split())
        lines = text.strip().splitlines()
        sections = len(re.findall(r"^#{1,4}\s+\S", text, re.M))

        if words < MIN_WORDS or len(lines) < MIN_LINES:
            return fail(f"{rel} is {words} words over {len(lines)} lines, under "
                        f"the {MIN_WORDS}/{MIN_LINES} a research document needs. "
                        f"A short answer to a research question is usually an "
                        f"unresearched one.")
        if sections < MIN_SECTIONS:
            return fail(f"{rel} has {sections} headings, under {MIN_SECTIONS}")

        limits = LIMITS_RE.search(text)
        if not limits:
            return fail(
                f"{rel} has no section saying what could not be verified. Both "
                f"documents this is modelled on carry one, and it is the "
                f"section that makes the rest readable: a document whose "
                f"weakest claim is unlabelled will be read as though every "
                f"claim were equally solid.")
        # The section body runs to the next heading of the SAME or a HIGHER
        # level. Searching for a top-level heading was the bug: "## What I
        # could not verify" is followed by more "##" sections, and a naive
        # scan cut the body to nothing and then complained it was empty.
        level = len(limits.group("hashes"))
        # From the END of the heading's own line. Searching from one character
        # in matched the heading's own remaining hashes -- "## What ..." minus
        # its first character is "# What ...", which is itself a heading -- and
        # cut every section body to a single word.
        line_end = text.find("\n", limits.start())
        body_start = len(text) if line_end == -1 else line_end + 1
        nxt = re.search(rf"^#{{1,{level}}}\s+\S", text[body_start:], re.M)
        limits_body = (text[body_start:body_start + nxt.start()]
                       if nxt else text[body_start:])
        if len(limits_body.split()) < MIN_LIMITS_WORDS:
            return fail(f"{rel}'s limitations section is "
                        f"{len(limits_body.split())} words. That is a heading, "
                        f"not an admission.")

        cited = path_citations(text)
        urls = set(URL_RE.findall(text))
        evidence = len(evidence_tokens(text) | urls)
        if evidence < MIN_EVIDENCE:
            return fail(f"{rel} names {evidence} pieces of evidence (paths, "
                        f"tables, URLs), under {MIN_EVIDENCE}. A claim nobody "
                        f"can trace is a claim nobody can check.")

        unresolved = sorted(p for p in cited if not resolves(p))
        if unresolved:
            return fail(f"{rel} cites repo paths that do not exist: "
                        f"{unresolved}. A document written from memory contains "
                        f"wrong paths, which is the failure this catches.")

        dates = DATE_RE.findall(text)
        if not dates:
            return fail(f"{rel} carries no date. A reading of a system is true "
                        f"as of a moment, and one that does not say when will "
                        f"be quoted long after it stopped being true.")
        if urls and not re.search(r"retriev|accessed|as of|fetched|read on", text, re.I):
            return fail(f"{rel} cites {len(urls)} URLs but never says when they "
                        f"were read. A page cited today may not say the same "
                        f"thing tomorrow.")

        print(f"ok: {rel} -- {words} words, {sections} sections, {evidence} "
              f"evidence references ({len(cited)} checkable repo paths, all "
              f"resolving; {len(urls)} URLs), and it states its limits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
