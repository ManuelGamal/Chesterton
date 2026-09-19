from dataclasses import replace

from chesterton.execute.pool import SandboxPool
from chesterton.reduce.surface import suite_command, undefended_surface
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import T_FLAKY

HEAD_ONE = "a = 10\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6\ng = 7\nh = 8\ni = 90\n"
HEAD_TWO = "x = 10\ny = 2\nz = 30\n"

# Zero-context hunks: two per file, far enough apart to stay separate.
DIFF = (
    "--- a/one.py\n+++ b/one.py\n"
    "@@ -1 +1 @@\n-a = 1\n+a = 10\n"
    "@@ -9 +9 @@\n-i = 9\n+i = 90\n"
    "--- a/two.py\n+++ b/two.py\n"
    "@@ -1 +1 @@\n-x = 1\n+x = 10\n"
    "@@ -3 +3 @@\n-z = 3\n+z = 30\n"
    "--- a/README.md\n+++ b/README.md\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)


def a_multi_hunk_seed(demo_seed):
    return replace(
        demo_seed,
        pr=replace(demo_seed.pr, diff=DIFF),
        sources={"one.py": HEAD_ONE, "two.py": HEAD_TWO},
    )


def suite_needs_a_and_z(checkpoint, shell, files):
    """The suite passes only while `a = 10` and `z = 30` are both applied."""
    one = files.get("/testbed/one.py", HEAD_ONE)
    two = files.get("/testbed/two.py", HEAD_TWO)
    ok = "a = 10\n" in one and "z = 30\n" in two
    return RunResult("", "", 0 if ok else 1, None)


async def test_the_hunks_the_tests_do_not_need_are_the_undefended_surface(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=suite_needs_a_and_z)

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.hunks == ("one.py#0", "one.py#1", "two.py#0", "two.py#1")
    assert result.needed == ("one.py#0", "two.py#1")
    assert result.undefended == ("one.py#1", "two.py#0")
    assert result.exhausted is False
    assert result.skipped == {"not_mutable_source": 1}


async def test_every_probe_forks_the_seed_and_persists_nothing(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=suite_needs_a_and_z)

    result = await undefended_surface(SandboxPool(runner), seed)

    assert len(runner.calls) == result.probes
    assert {checkpoint for checkpoint, _ in runner.calls} == {seed.checkpoint_id}
    assert all(option["disposable"] for option in runner.options)


async def test_when_the_suite_needs_nothing_the_whole_pr_is_undefended(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=lambda c, s, f: RunResult("", "", 0, None))

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.needed == ()
    assert len(result.undefended) == 4
    assert result.probes == 1


async def test_probes_that_error_prove_nothing_undefended(demo_seed):
    # UNRESOLVED never counts as holding, so nothing is claimed undefended.
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(
        handler=lambda c, s, f: RunResult("", "", None, None, error="TimedOut")
    )

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.undefended == ()
    assert result.needed == result.hunks


async def test_a_spent_budget_claims_no_more_than_is_proven(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=suite_needs_a_and_z)

    result = await undefended_surface(SandboxPool(runner, op_budget=2), seed)

    assert result.exhausted is True
    assert set(result.undefended) <= {"one.py#1", "two.py#0"}


async def test_a_pr_with_no_source_hunks_costs_nothing(demo_seed):
    seed = replace(
        demo_seed,
        pr=replace(demo_seed.pr, diff="--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-a\n+b\n"),
        sources={},
    )
    runner = FakeSandboxRunner()

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.hunks == ()
    assert result.note
    assert runner.calls == []


def test_the_suite_command_deselects_every_unselectable_test(demo_seed):
    command = suite_command(demo_seed)

    assert f"--deselect {T_FLAKY}" in command
    assert command.startswith("cd /testbed && python -m pytest")
