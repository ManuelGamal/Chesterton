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

from chesterton.covmap.invert import IMPORT_TIME
from chesterton.defended import covering_tests
from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.models import Hunk
from chesterton.mutation.model import Mutant
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.record import SeedRecord

Verdict = Literal["killed", "survived", "uncovered", "error"]

#: Coverage-selected tests are few; this bounds a mutant that hangs them.
MUTANT_TIMEOUT_S = 120.0

#: A whole-suite run: ddmin probes, and mutants on import-only lines.
SUITE_TIMEOUT_S = 300.0

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


def suite_command(seed: SeedRecord) -> str:
    """The whole selectable suite: the seed's scope, minus flaky and failing tests.

    Scoped to `seed.test_paths` when set. For a SWE-bench seed "the whole
    suite" means the task's test files, or one ddmin probe runs all of sympy.
    """
    scope = " ".join(shlex.quote(path) for path in seed.test_paths)
    deselect = " ".join(
        f"--deselect {shlex.quote(test)}" for test in sorted(seed.flaky | seed.failing)
    )
    return (
        f"cd {shlex.quote(seed.workdir)} && {seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {scope} {deselect}"
    ).rstrip()


def _import_only(mutant: Mutant, seed: SeedRecord) -> bool:
    """No selectable test runs the hunk, but it runs at import time.

    Live, nomenclature-284 (2026-09-19): four model mutants on a changed
    import line went untested, reported as "executed by no test". The line
    runs on every import; coverage just cannot name the tests that depend
    on it. The whole selectable suite is the honest set to run.
    """
    if select_tests(mutant, seed):
        return False
    by_line = seed.coverage.get(mutant.file, {})
    lines = range(mutant.start_line, mutant.end_line + 1)
    return any(IMPORT_TIME in by_line.get(line, []) for line in lines)


def needs_op(mutant: Mutant, seed: SeedRecord) -> bool:
    """Whether executing this mutant spends a sandbox op."""
    return bool(select_tests(mutant, seed)) or _import_only(mutant, seed)


async def _execute(pool: SandboxPool, seed: SeedRecord, mutant: Mutant) -> MutantResult:
    tests = select_tests(mutant, seed)
    if tests:
        command, timeout, note = _command(seed, tests), MUTANT_TIMEOUT_S, None
    elif _import_only(mutant, seed):
        command, timeout = suite_command(seed), SUITE_TIMEOUT_S
        note = (
            "the hunk runs only at import time, so coverage cannot select "
            "the tests that depend on it; the whole selectable suite ran"
        )
    else:
        return MutantResult(
            mutant, "uncovered", (), detail="no selectable test executes this hunk"
        )

    try:
        result = await pool.run(
            seed.checkpoint_id,
            command,
            files={f"{seed.workdir}/{mutant.file}": mutant.mutated_src},
            timeout=timeout,
        )
    except BudgetExhausted as exc:
        return MutantResult(mutant, "error", tests, detail=str(exc))

    verdict, detail = classify(result)
    return MutantResult(
        mutant, verdict, tests, result.duration_s, detail or note, _tail(result.stdout)
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
