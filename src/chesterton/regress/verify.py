"""Run a generated test twice, in two forks of the seed checkpoint.

On the pull request's code it must PASS (pytest exit 0). With the mutant
written over its file it must FAIL (exit 1: tests failed). Anything else
proves nothing, and an unverified test is never rendered (spec §9). This is
the answer to "an uncritical agent may encode a bug as correct behaviour":
execution, not a disclaimer.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from typing import Literal

from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.mutation.model import Mutant
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.record import SeedRecord

Status = Literal["verified", "fails_on_patch", "passes_on_mutant", "invalid_on_mutant", "error"]

VERIFY_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class Verification:
    status: Status
    detail: str
    patch_tail: str = ""
    mutant_tail: str = ""

    def feedback(self) -> str:
        tail = self.patch_tail if self.status == "fails_on_patch" else self.mutant_tail
        return f"{self.status}: {self.detail}\nThe run's output ended:\n{tail}"


def _tail(result: RunResult | None, lines: int = 30) -> str:
    if result is None:
        return ""
    text = "\n".join(s for s in (result.stdout, result.stderr) if s)
    return "\n".join(text.strip().splitlines()[-lines:])


async def _run(pool, seed, command, files) -> RunResult | str:
    try:
        return await pool.run(seed.checkpoint_id, command, files=files, timeout=VERIFY_TIMEOUT_S)
    except BudgetExhausted as exc:
        return str(exc)


async def verify_regression_test(
    pool: SandboxPool, seed: SeedRecord, mutant: Mutant, test_path: str, test_src: str
) -> Verification:
    command = (
        f"cd {shlex.quote(seed.workdir)} && {seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {shlex.quote(test_path)}"
    )
    test_file = {f"{seed.workdir}/{test_path}": test_src}
    on_patch, on_mutant = await asyncio.gather(
        _run(pool, seed, command, test_file),
        _run(pool, seed, command, {**test_file, f"{seed.workdir}/{mutant.file}": mutant.mutated_src}),
    )
    for name, result in (("pull request", on_patch), ("mutant", on_mutant)):
        if isinstance(result, str):
            return Verification("error", f"the {name} run was not made: {result}")
        if result.error is not None:
            return Verification("error", f"the {name} run failed: {result.error}")
    tails = {"patch_tail": _tail(on_patch), "mutant_tail": _tail(on_mutant)}
    if on_patch.exit_code != 0:
        return Verification(
            "fails_on_patch",
            f"pytest exited {on_patch.exit_code} on the pull request's code; it must pass there",
            **tails,
        )
    if on_mutant.exit_code == 0:
        return Verification("passes_on_mutant", "the mutant passes it too, so it catches nothing", **tails)
    if on_mutant.exit_code != 1:
        return Verification(
            "invalid_on_mutant",
            f"pytest exited {on_mutant.exit_code} on the mutant; only a test failure (1) counts",
            **tails,
        )
    return Verification("verified", "passes on the pull request, fails on the mutant", **tails)
