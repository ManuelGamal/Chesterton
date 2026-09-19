"""Run each mutant against the tests that execute its hunk, and say honestly
what happened.

The verdict rules are the spec's, and they are where fabricated evidence
would enter:

- only pytest exit code 1 (TESTS_FAILED) is a kill;
- exit 0 means survived: no selected test failed;
- every other exit code is an error. That covers 2 (interrupted, including a
  collection error), 3 (internal), 4 (usage) and 5 (no tests collected). A
  mutant that stops a module importing makes tests error, and the spec
  counts that reading-as-killed as a silent false negative;
- a sandbox operation that failed is an error, and it is checked before
  exit_code is read, which is None exactly then.

Errors and uncovered mutants are excluded from the score. A mutant with no
selectable covering test is `uncovered` and costs no sandbox op.
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from chesterton.defended import covering_tests
from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.models import Hunk
from chesterton.mutation.model import Mutant
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.record import SeedRecord

Verdict = Literal["killed", "survived", "uncovered", "error"]

#: Coverage-selected tests are few; this bounds a mutant that hangs them.
MUTANT_TIMEOUT_S = 120.0

#: pytest.ExitCode, spelled out so an error names what happened.
_PYTEST_EXIT = {
    2: "INTERRUPTED",
    3: "INTERNAL_ERROR",
    4: "USAGE_ERROR",
    5: "NO_TESTS_COLLECTED",
}


@dataclass(frozen=True)
class MutantResult:
    mutant: Mutant
    verdict: Verdict
    tests: tuple[str, ...]
    duration_s: float | None = None
    detail: str | None = None
    stdout_tail: str = ""


def select_tests(mutant: Mutant, seed: SeedRecord) -> tuple[str, ...]:
    hunk = Hunk(mutant.file, mutant.start_line, mutant.end_line)
    return tuple(
        test for test in covering_tests(hunk, seed.coverage) if test in seed.selectable
    )


def classify(result: RunResult) -> tuple[Verdict, str | None]:
    if result.error is not None:
        return "error", result.error
    if result.exit_code == 1:
        return "killed", None
    if result.exit_code == 0:
        return "survived", None
    name = _PYTEST_EXIT.get(result.exit_code, "UNKNOWN")
    return "error", (
        f"pytest exited {result.exit_code} ({name}); that is not a test "
        "failure, so it is not a kill"
    )


def _tail(text: str, lines: int = 15) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def _command(seed: SeedRecord, tests: Sequence[str]) -> str:
    return (
        f"cd {shlex.quote(seed.workdir)} && {seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {shlex.join(tests)}"
    )


async def _execute(pool: SandboxPool, seed: SeedRecord, mutant: Mutant) -> MutantResult:
    tests = select_tests(mutant, seed)
    if not tests:
        return MutantResult(
            mutant, "uncovered", (), detail="no selectable test executes this hunk"
        )
    try:
        result = await pool.run(
            seed.checkpoint_id,
            _command(seed, tests),
            files={f"{seed.workdir}/{mutant.file}": mutant.mutated_src},
            timeout=MUTANT_TIMEOUT_S,
        )
    except BudgetExhausted as exc:
        return MutantResult(mutant, "error", tests, detail=str(exc))

    verdict, detail = classify(result)
    return MutantResult(
        mutant, verdict, tests, result.duration_s, detail, _tail(result.stdout)
    )


async def execute_mutants(
    pool: SandboxPool, seed: SeedRecord, mutants: Sequence[Mutant]
) -> list[MutantResult]:
    return list(await asyncio.gather(*(_execute(pool, seed, m) for m in mutants)))


@dataclass(frozen=True)
class VerdictCounts:
    killed: int
    survived: int
    uncovered: int
    error: int

    @property
    def score(self) -> float | None:
        ran = self.killed + self.survived
        return self.killed / ran if ran else None


def count_verdicts(results: Sequence[MutantResult]) -> VerdictCounts:
    tally = {"killed": 0, "survived": 0, "uncovered": 0, "error": 0}
    for result in results:
        tally[result.verdict] += 1
    return VerdictCounts(**tally)
