"""Collect, gate, rank and budget the mutants for one run.

The budget is the spec's: 30-40 mutants per run (section 6). It is not the
concurrency cap, and must not be derived from it. Execution runs behind
`asyncio.Semaphore(24)` — 24 simultaneous sandbox operations was measured safe
(72/72 across three rounds) — and queueing a short second round is exactly what
that semaphore is for. The budget bounds the run as a whole: one that executed
200 mutants would queue for nine rounds and stop feeling live, which costs the
demo more than the extra coverage buys.

Ranking is by operator weight, because under a tight budget the mutations that
survive should be the ones carrying the most signal. Deleting a guard clause is
the spec's headline case — an agent quietly removing a protection — and it
outranks shifting a comparison boundary.

Model-proposed mutants are passed in rather than fetched here, which keeps this
function synchronous and testable without a client. They are not privileged:
they pass the same gate as everything else.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from chesterton.filters import is_mutable_source
from chesterton.models import Hunk
from chesterton.mutation.gate import MutantGate
from chesterton.mutation.model import Mutant
from chesterton.mutation.operators import apply_candidate, find_candidates
from chesterton.paths import normalise_path

#: Spec section 6: 30-40 mutants per run. Behind Semaphore(24) that is one
#: full round and a short second one; concurrency is the semaphore's job.
MUTANT_BUDGET = 32

#: Higher is kept first when the budget bites.
OPERATOR_WEIGHT = {
    "delete_guard": 100,
    "strip_decorator": 90,
    "remove_cleanup": 85,
    "drop_await": 80,
    "widen_except": 70,
    #: Model-proposed. Plausible, but unproven next to the named safety
    #: operators above, which target specific known deletion shapes.
    "semantic": 60,
    "invert_condition": 50,
    "off_by_one": 40,
}


def generate(
    hunks: Sequence[Hunk],
    sources: Mapping[str, str],
    *,
    llm_mutants: Sequence[Mutant] = (),
    budget: int = MUTANT_BUDGET,
) -> tuple[list[Mutant], dict[str, int]]:
    gate = MutantGate()
    skipped: dict[str, int] = {}
    collected: list[Mutant] = []

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    # One spelling on both sides of the lookup. A `sources` mapping built from
    # a filesystem walk on Windows is keyed with backslashes while hunks come
    # from a diff with forward slashes; unnormalised, every file silently
    # yields zero mutants, reported as `no_source` — "the file was missing",
    # not "the keys were spelled differently".
    sources = {normalise_path(path): text for path, text in sources.items()}
    hunks = [replace(hunk, file=normalise_path(hunk.file)) for hunk in hunks]

    for hunk in hunks:
        if not is_mutable_source(hunk.file):
            skip("not_mutable_source")
            continue

        source = sources.get(hunk.file)
        if source is None:
            skip("no_source")
            continue

        for candidate in find_candidates(source, hunk.lines):
            mutated = apply_candidate(source, candidate)
            mutant = Mutant(
                file=hunk.file,
                start_line=hunk.start_line,
                end_line=hunk.end_line,
                operator=candidate.operator,
                original_src=source,
                mutated_src=mutated,
                rationale=candidate.description,
                source="deterministic",
            )
            if gate.admit(mutant):
                collected.append(mutant)

    for mutant in llm_mutants:
        # Model replies carry whatever path the prompt showed them. Left
        # unnormalised, the same file with different separators hashes to two
        # distinct mutants and misses every lookup keyed on forward slashes.
        mutant = replace(mutant, file=normalise_path(mutant.file))
        if not is_mutable_source(mutant.file):
            skip("not_mutable_source")
            continue
        if gate.admit(mutant):
            collected.append(mutant)

    collected.sort(key=lambda m: OPERATOR_WEIGHT.get(m.operator, 0), reverse=True)
    return collected[:budget], {**skipped, **gate.rejected}
