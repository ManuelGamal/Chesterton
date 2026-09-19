"""One run against a built seed: tier 0, then mutation, then reduction.

The order is the spec's run-time pipeline (§4). Tier 1 (CrossHair) is
Phase 2b and slots in between tier 0 and mutation when it lands.

Budget (ruling P3-2): sandbox ops and model calls are capped. Dollars are
not, because sandboxes are free during the beta and no price is recorded
for the one model tier Phase 3 calls. If the mutant ops alone exceed the op
budget, the run refuses to start (spec §14). ddmin probes spend what is
left, and a search the budget cuts short says so.

Model proposals are retried once, then the run falls back to deterministic
mutants only (spec §14). Every failure is counted by kind, so a total model
outage reads as an outage and never as "the model had nothing to say".
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from collections.abc import Collection
from dataclasses import asdict, dataclass

from chesterton.covmap.invert import IMPORT_TIME
from chesterton.defended import uncovered_findings
from chesterton.diffing.parse import changed_lines
from chesterton.diffing.semantic import semantic_hunks
from chesterton.execute.mutants import (
    MutantResult,
    VerdictCounts,
    count_verdicts,
    execute_mutants,
    select_tests,
)
from chesterton.execute.pool import CONCURRENCY, RUN_OP_BUDGET, SandboxPool
from chesterton.llm.mutants import propose
from chesterton.models import CoverageMap, Hunk
from chesterton.mutation.generate import generate
from chesterton.mutation.model import Mutant
from chesterton.reduce.surface import SurfaceResult, undefended_surface
from chesterton.seed.record import SeedRecord

#: Lightning is the high-volume tier; this keeps a burst polite.
MODEL_CONCURRENCY = 8

#: The model call raised rather than replying, e.g. a connection error.
UNAVAILABLE = "unavailable"


class RunRefused(RuntimeError):
    """The run would overspend its budget, so it did not start."""


@dataclass(frozen=True)
class ModelStats:
    calls: int
    retried: int
    failures: dict[str, int]


@dataclass(frozen=True)
class RunReport:
    slug: str
    wall_s: float
    tier0: list[tuple[str, int]]
    hunks: int
    generated: int
    rejected: dict[str, int]
    model: ModelStats | None
    results: list[MutantResult]
    counts: VerdictCounts
    surface: SurfaceResult | None
    ops_used: int
    op_budget: int

    def to_json(self) -> str:
        payload = asdict(self)
        payload["score"] = self.counts.score
        return json.dumps(payload, indent=2)


def restrict_coverage(coverage: CoverageMap, allowed: Collection[str]) -> CoverageMap:
    """Ruling P3-6: a line run only by a flaky or failing test is undefended.

    IMPORT_TIME survives the restriction. It is not a test that can be flaky,
    and dropping it here would bring back the false tier-0 finding on
    import-time lines.
    """
    return {
        file: {
            line: [t for t in tests if t in allowed or t == IMPORT_TIME]
            for line, tests in lines.items()
        }
        for file, lines in coverage.items()
    }


def _semantic_hunks(seed: SeedRecord, changed: dict[str, list[int]]) -> list[Hunk]:
    hunks: list[Hunk] = []
    for file, source in sorted(seed.sources.items()):
        lines = changed.get(file)
        if lines:  # a pure deletion adds no line to mutate
            hunks.extend(semantic_hunks(source, file, lines))
    return hunks


async def _propose_all(
    client, hunks: list[Hunk], sources: dict[str, str]
) -> tuple[list[Mutant], ModelStats]:
    import openai

    semaphore = asyncio.Semaphore(MODEL_CONCURRENCY)
    calls = retried = 0
    failures: Counter[str] = Counter()

    async def one(hunk: Hunk) -> list[Mutant]:
        nonlocal calls, retried
        async with semaphore:
            failure = None
            for attempt in (1, 2):
                calls += 1
                try:
                    proposal = await propose(
                        client,
                        file=hunk.file,
                        module_src=sources[hunk.file],
                        start_line=hunk.start_line,
                        end_line=hunk.end_line,
                    )
                except openai.OpenAIError:
                    failure = UNAVAILABLE
                else:
                    if proposal.failure is None:
                        return proposal.mutants
                    failure = proposal.failure
                if attempt == 1:
                    retried += 1
            failures[failure] += 1
            return []

    batches = await asyncio.gather(*(one(h) for h in hunks))
    mutants = [m for batch in batches for m in batch]
    return mutants, ModelStats(calls, retried, dict(failures))


async def run_seed(
    seed: SeedRecord,
    runner,
    *,
    client=None,
    op_budget: int = RUN_OP_BUDGET,
    concurrency: int = CONCURRENCY,
    reduce: bool = True,
) -> RunReport:
    started = time.perf_counter()
    changed = changed_lines(seed.pr.diff)
    hunks = _semantic_hunks(seed, changed)
    defended = restrict_coverage(seed.coverage, seed.selectable)
    tier0 = uncovered_findings(hunks, defended, changed)

    llm_mutants: list[Mutant] = []
    model = None
    if client is not None:
        llm_mutants, model = await _propose_all(client, hunks, seed.sources)

    mutants, rejected = generate(hunks, seed.sources, llm_mutants=llm_mutants)

    pool = SandboxPool(runner, concurrency=concurrency, op_budget=op_budget)
    needed = sum(1 for m in mutants if select_tests(m, seed))
    if needed > pool.remaining:
        raise RunRefused(
            f"this run needs {needed} sandbox ops for its mutants alone and its "
            f"budget is {op_budget}; refusing to start rather than overspend"
        )

    results = await execute_mutants(pool, seed, mutants)
    surface = None
    if reduce and pool.remaining > 0:
        surface = await undefended_surface(pool, seed)

    return RunReport(
        slug=seed.slug,
        wall_s=round(time.perf_counter() - started, 3),
        tier0=tier0,
        hunks=len(hunks),
        generated=len(mutants),
        rejected=rejected,
        model=model,
        results=results,
        counts=count_verdicts(results),
        surface=surface,
        ops_used=pool.ops_used,
        op_budget=op_budget,
    )
