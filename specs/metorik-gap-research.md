# Produce a Metorik feature gap list for DD analytics

Serves `dd-feature-parity` in `objectives-2026-Q4.yaml`, which names a written
gap list as its own first deliverable: *"NEEDS A BASELINE: a written gap list,
Metorik feature vs DD status, ordered by how often an agency would use it.
Without that, this objective ranks 'build another report' forever."*

Write it to `research/metorik-gap-2026-08-30.md`. That file is the only thing
you may create or change.

## What the document must do

1. **Compare Metorik's feature set to what DD has today**, feature by feature,
   in a table.
2. **Order by how often a WooCommerce agency running client stores would use
   each one.** The ordering is the point of the document — a feature DD is
   missing that an agency opens twice a year is not a gap worth a sprint,
   however cheap it is to build. Say plainly that the ordering is your
   estimate and that nothing measured it.
3. **Give each row a status of Has / Partial / Missing**, and define those
   terms. "Has" should mean an endpoint that is mounted *and* a page that
   reaches it — an endpoint nobody can get to is not a feature.
4. **Cite the evidence for every status**, by file path, endpoint, table or
   column. A status nobody can trace is a status nobody can check.

## What you have

- **`research/EVIDENCE-metorik.md`** — readings the runner took from the
  databases before you started, with the SQL that produced each. You cannot
  run queries. If a number you want is not in there, say so rather than
  estimating it.
- **The platform checkout at `~/deadly-digital-platform`, read-only.** Read the
  API routes, the analytics services and the frontend pages. This is where
  Has/Partial/Missing is established.
- **The web.** Metorik's own marketing and help pages are the only source for
  what Metorik does. Record the URLs and the date you read them.

## What you must not do

- Change any file but `research/metorik-gap-2026-08-30.md`.
- Write anything into `~/deadly-digital-platform`. It is readable and the
  runner checks afterwards that it is byte-for-byte unchanged.
- State a population count you did not read from the evidence pack.
- Describe a page or an endpoint as existing without having opened the file.

## What done means

A document that a person can act on without re-deriving it, containing:

- the comparison table, ordered by agency use, with an evidence column
- a summary of what the table says, so the reader knows before the table
- **a section stating what you could not verify** — and it must be real. You
  have no Metorik account, so nothing about Metorik was seen working. The
  database reader can see `analytics_1.orders`, `analytics_2.orders`,
  `public.orders` and `public.tenants` and **nothing else**: no customers, no
  products, no order_items. Every claim that would have needed those tables is
  a claim you could not check, and the document should say which.
- the date the readings were taken

`specs/refund-hook.md` is the standard for how to handle evidence: it names
what it read, quotes it, and is explicit about what remains open. It also
overturned a prior conclusion on evidence — if you find that DD's own
`docs/ANALYTICS-GAP-ANALYSIS.md` is wrong about something, say so and show why.

## How it is checked

    the document exists, is the only changed file, and is substantial
    it states what it could not verify, in a section with real content
    it names its evidence
    every repo path it cites resolves
    it carries a date, and URLs carry retrieval dates

That check enforces form, not correctness. It cannot tell whether the analysis
is right, whether the evidence supports the claim, or whether a URL says what
you say it says. A person has to read it.
