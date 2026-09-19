import asyncio

import pytest

from chesterton.execute.pool import (
    CONCURRENCY,
    RUN_OP_BUDGET,
    BudgetExhausted,
    SandboxPool,
)
from chesterton.mutation.generate import MUTANT_BUDGET
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult


class _SlowRunner:
    """Holds each op open briefly so overlapping ops can be counted."""

    def __init__(self):
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    async def run(self, checkpoint_id, shell, *, files=None, disposable=True,
                  tag=None, timeout=None):
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return RunResult("", "", 0, None)


async def test_concurrency_reaches_but_never_exceeds_the_cap():
    # == rather than <=: the test must also prove ops really run side by side.
    runner = _SlowRunner()
    pool = SandboxPool(runner, concurrency=24, op_budget=100)

    await asyncio.gather(*(pool.run("ckpt", "pytest") for _ in range(60)))

    assert runner.peak == 24


async def test_the_budget_refuses_ops_beyond_it_without_calling_the_runner():
    runner = _SlowRunner()
    pool = SandboxPool(runner, op_budget=3)

    outcomes = await asyncio.gather(
        *(pool.run("ckpt", "pytest") for _ in range(5)), return_exceptions=True
    )

    assert sum(isinstance(o, BudgetExhausted) for o in outcomes) == 2
    assert runner.calls == 3
    assert pool.ops_used == 3
    assert pool.remaining == 0


async def test_every_pool_op_is_disposable():
    # Run time never persists anything, so it never needs a tag.
    runner = FakeSandboxRunner()
    pool = SandboxPool(runner)

    await pool.run("ckpt", "pytest", files={"/testbed/a.py": "x = 1\n"}, timeout=5)

    assert runner.options == [{"disposable": True, "tag": None, "timeout": 5}]


def test_the_defaults_match_the_measured_cap_and_cover_a_full_mutant_budget():
    assert CONCURRENCY == 24
    assert RUN_OP_BUDGET >= MUTANT_BUDGET


def test_nonsense_limits_are_refused():
    with pytest.raises(ValueError):
        SandboxPool(FakeSandboxRunner(), concurrency=0)
    with pytest.raises(ValueError):
        SandboxPool(FakeSandboxRunner(), op_budget=-1)
