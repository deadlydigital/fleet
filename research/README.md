# research/

Output, not instruction.

`specs/` holds documents that tell a task what to do. This directory holds
documents a task produced. Mixing them means the next person cannot tell which
is which — and a task that could edit its own spec could edit the instructions
it is judged against, which is why `specs/**` is on the fleet repository's
protected floor.

Each document here is the artifact of one research task, the way a branch is
the artifact of a code task. It arrives on a branch, is reviewed in the
console, and is accepted or rejected there.

**A green check on one of these means less than it looks.** The acceptance
check enforces a floor on form — the document exists, is substantial, is
dated, names its evidence, states what it could not verify, and cites no repo
path that does not exist. It cannot check whether the analysis is correct,
whether the evidence supports the claim, or whether the limits section is
honest. These need reading in a way a code branch does not.
