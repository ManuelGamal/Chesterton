"""Only a test that passes on the PR and fails on the mutant is shown (spec §9)."""

from chesterton.execute.pool import SandboxPool
from chesterton.regress.verify import verify_regression_test
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import NO_GUARD, a_survivor

MUTANT = a_survivor(NO_GUARD).mutant
PATH = "tests/test_chesterton_regression.py"
SRC = "def test_x():\n    assert True\n"


def runner(on_patch, on_mutant):
    def handler(checkpoint, shell, files):
        mutated = "/testbed/pay.py" in files
        code = on_mutant if mutated else on_patch
        if isinstance(code, str):
            return RunResult("", "", None, None, error=code)
        return RunResult(f"exit {code}", "", code, None)
    return FakeSandboxRunner(handler=handler)


async def verify(seed, r, budget=2):
    pool = SandboxPool(r, op_budget=budget)
    return await verify_regression_test(pool, seed, MUTANT, PATH, SRC), pool


async def test_passing_on_the_pr_and_failing_on_the_mutant_is_verified(demo_seed):
    r = runner(on_patch=0, on_mutant=1)

    v, pool = await verify(demo_seed, r)

    assert v.status == "verified" and pool.ops_used == 2
    assert all(PATH in shell for _, shell in r.calls)
    for files in r.files_written:
        assert files["/testbed/" + PATH] == SRC


async def test_a_test_that_fails_on_the_pr_is_refused(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=1, on_mutant=1))

    assert v.status == "fails_on_patch" and "exit 1" in v.patch_tail


async def test_a_test_the_mutant_also_passes_catches_nothing(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant=0))

    assert v.status == "passes_on_mutant"


async def test_a_mutant_run_that_errors_proves_nothing(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant=2))

    assert v.status == "invalid_on_mutant" and "2" in v.detail


async def test_a_failed_sandbox_operation_is_an_error_not_a_verdict(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant="OperationTimedOutError"))

    assert v.status == "error" and "OperationTimedOutError" in v.detail


async def test_an_exhausted_budget_is_an_error(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant=1), budget=1)

    assert v.status == "error" and "budget" in v.detail


def test_feedback_names_the_status_and_the_relevant_output():
    from chesterton.regress.verify import Verification

    v = Verification("fails_on_patch", "pytest exited 1", patch_tail="E  AssertionError")

    assert "fails_on_patch" in v.feedback() and "AssertionError" in v.feedback()
