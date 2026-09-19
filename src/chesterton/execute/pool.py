"""Every run-time sandbox operation goes through one pool.

It enforces two limits, for different reasons.

Concurrency, via asyncio.Semaphore(24). 24 simultaneous operations was
measured safe: 72/72 across three rounds, 4.7 s worst case with real pytest
(spec §15). Above that the fan-out leaves measured territory, and the beta's
op cap comes into play.

A per-run op budget. The spec's failure-mode table says to refuse to start
rather than overspend. Mutant fan-out and ddmin probes share one budget
because they share one quota.

Run time only ever forks and throws away, so every op here is disposable and
none needs a tag. The build-time seed build is the one caller that persists,
and it calls the runner directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from chesterton.sandbox.protocol import RunResult

#: Measured safe (spec §15). This is the Global Constraint, not a tunable.
CONCURRENCY = 24

#: 32 mutant ops (MUTANT_BUDGET) plus about n² = 121 ddmin probes for the
#: spec's own 11-hunk example (§8), rounded up.
RUN_OP_BUDGET = 160


class BudgetExhausted(RuntimeError):
    """The run's op budget is spent; this op was not issued."""


class SandboxPool:
    def __init__(
        self,
        runner,
        *,
        concurrency: int = CONCURRENCY,
        op_budget: int = RUN_OP_BUDGET,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if op_budget < 0:
            raise ValueError("op_budget cannot be negative")
        self.runner = runner
        self.op_budget = op_budget
        self.ops_used = 0
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def remaining(self) -> int:
        return self.op_budget - self.ops_used

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str | bytes] | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        # Charged BEFORE waiting on the semaphore, with no await between the
        # check and the charge, so concurrent callers cannot all pass the
        # check and overspend together.
        if self.remaining <= 0:
            raise BudgetExhausted(
                f"the run's budget of {self.op_budget} sandbox ops is spent"
            )
        self.ops_used += 1
        async with self._semaphore:
            return await self.runner.run(
                checkpoint_id, shell, files=files, disposable=True, timeout=timeout
            )
