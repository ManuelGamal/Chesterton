from dataclasses import replace

from chesterton.covmap.invert import IMPORT_TIME
from chesterton.execute.mutants import (
    MutantResult,
    classify,
    count_verdicts,
    execute_mutants,
    needs_op,
    select_tests,
)
from chesterton.execute.pool import SandboxPool
from chesterton.mutation.model import Mutant
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import HEAD_PAY, T_CHARGE, T_FLAKY


def a_mutant(start: int = 2, end: int = 3, mutated: str = "def charge(amount):\n    return amount\n") -> Mutant:
    return Mutant(
        file="pay.py", start_line=start, end_line=end, operator="delete_guard",
        original_src=HEAD_PAY, mutated_src=mutated, rationale="r",
        source="deterministic",
    )


def exits(code):
    return FakeSandboxRunner(handler=lambda c, s, f: RunResult("out", "", code, None))


def test_only_exit_1_is_a_kill():
    assert classify(RunResult("", "", 1, None)) == ("killed", None)
    assert classify(RunResult("", "", 0, None)) == ("survived", None)


def test_other_exit_codes_are_errors_that_name_the_code():
    for code in (2, 3, 4, 5):
        verdict, detail = classify(RunResult("", "", code, None))
        assert verdict == "error"
        assert f"exited {code}" in detail


def test_a_sandbox_error_is_an_error_before_exit_code_is_read():
    verdict, detail = classify(RunResult("", "", None, None, error="TimedOut"))
    assert (verdict, detail) == ("error", "TimedOut")


def test_selection_keeps_only_selectable_covering_tests(demo_seed):
    # Lines 2-3: line 2 is covered by T_CHARGE, line 3 only by T_FLAKY.
    assert select_tests(a_mutant(), demo_seed) == (T_CHARGE,)


async def test_a_mutant_the_tests_fail_on_is_killed(demo_seed):
    [result] = await execute_mutants(SandboxPool(exits(1)), demo_seed, [a_mutant()])
    assert result.verdict == "killed"
    assert result.tests == (T_CHARGE,)


async def test_a_mutant_no_selected_test_fails_on_survives(demo_seed):
    [result] = await execute_mutants(SandboxPool(exits(0)), demo_seed, [a_mutant()])
    assert result.verdict == "survived"


async def test_the_mutant_is_written_into_the_repo_and_only_selected_tests_run(demo_seed):
    runner = exits(1)
    mutant = a_mutant()

    await execute_mutants(SandboxPool(runner), demo_seed, [mutant])

    [(checkpoint, shell)] = runner.calls
    assert checkpoint == demo_seed.checkpoint_id
    assert runner.files_written == [{"/testbed/pay.py": mutant.mutated_src}]
    assert T_CHARGE in shell
    assert T_FLAKY not in shell


async def test_a_mutant_covered_only_by_flaky_tests_is_uncovered_and_costs_nothing(demo_seed):
    runner = exits(1)
    pool = SandboxPool(runner)

    [result] = await execute_mutants(pool, demo_seed, [a_mutant(start=3, end=3)])

    assert result.verdict == "uncovered"
    assert result.detail
    assert runner.calls == []
    assert pool.ops_used == 0


async def test_an_import_time_hunk_runs_the_whole_selectable_suite(demo_seed):
    # Live, nomenclature-284: four model mutants on a changed import line went
    # untested. The line runs on every import, so coverage cannot name the
    # tests that depend on it; the whole selectable suite is the honest set.
    seed = replace(demo_seed, coverage={"pay.py": {1: [IMPORT_TIME]}})
    runner = exits(1)
    pool = SandboxPool(runner)

    [result] = await execute_mutants(pool, seed, [a_mutant(start=1, end=1)])

    assert result.verdict == "killed"
    assert "import time" in result.detail
    [(_, shell)] = runner.calls
    assert f"--deselect {T_FLAKY}" in shell  # unselectable tests still excluded
    assert T_CHARGE not in shell  # no coverage-picked ids: the whole suite
    assert pool.ops_used == 1


def test_an_import_time_hunk_needs_an_op_and_an_unexecuted_one_does_not(demo_seed):
    imported = replace(demo_seed, coverage={"pay.py": {1: [IMPORT_TIME]}})
    assert needs_op(a_mutant(start=1, end=1), imported) is True

    # Line 3 is covered only by the flaky test: nothing selectable, not import.
    assert needs_op(a_mutant(start=3, end=3), demo_seed) is False


async def test_a_spent_budget_is_an_error_never_a_kill(demo_seed):
    [result] = await execute_mutants(
        SandboxPool(exits(1), op_budget=0), demo_seed, [a_mutant()]
    )
    assert result.verdict == "error"
    assert "budget" in result.detail


def a_result(verdict):
    return MutantResult(a_mutant(), verdict, ())


def test_the_score_excludes_errors_and_uncovered_mutants():
    results = [
        a_result("killed"), a_result("killed"), a_result("survived"),
        a_result("error"), a_result("uncovered"),
    ]

    counts = count_verdicts(results)

    assert (counts.killed, counts.survived, counts.error, counts.uncovered) == (2, 1, 1, 1)
    assert counts.score == 2 / 3


def test_there_is_no_score_when_nothing_ran():
    assert count_verdicts([]).score is None
