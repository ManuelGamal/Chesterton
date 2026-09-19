import json

import pytest

from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.build import (
    COVERAGE_PATH,
    DIFF_PATH,
    RUN_LOGS,
    SeedBuildError,
    build_script,
    build_seed,
    relative_to_workdir,
)
from chesterton.seed.record import SeedRecord, is_valid_slug, seed_tag

from conftest import HEAD_PAY, T_CHARGE, T_FLAKY

T_BROKEN = "tests/test_pay.py::test_broken"

STABLE = f"""\
=========================== short test summary info ===========================
PASSED {T_CHARGE}
PASSED {T_FLAKY}
FAILED {T_BROKEN} - AssertionError: no
1 failed, 2 passed in 0.10s
"""
WOBBLY = STABLE.replace(f"PASSED {T_FLAKY}", f"FAILED {T_FLAKY} - AssertionError")

COVERAGE = {
    "files": {
        "/testbed/pay.py": {
            "contexts": {
                "1": [f"{T_CHARGE}|run"],
                "2": [f"{T_CHARGE}|run"],
                "3": [f"{T_FLAKY}|run"],
                "4": [f"{T_CHARGE}|run"],
            }
        }
    }
}


def a_built_runner(**overrides) -> FakeSandboxRunner:
    artifacts = {
        RUN_LOGS[0]: STABLE,
        RUN_LOGS[1]: WOBBLY,
        RUN_LOGS[2]: STABLE,
        COVERAGE_PATH: json.dumps(COVERAGE),
        "/testbed/pay.py": HEAD_PAY,
    }
    artifacts.update(overrides)
    return FakeSandboxRunner(artifacts=artifacts)


async def a_seed_from(runner, demo_seed):
    return await build_seed(
        runner, demo_seed.pr, slug="demo", image_ref="docker://example/pay"
    )


async def test_a_built_seed_records_what_the_run_phase_needs(demo_seed):
    seed = await a_seed_from(a_built_runner(), demo_seed)

    assert seed.checkpoint_tag == "chesterton:seed-demo"
    assert seed.checkpoint_id.startswith("ckpt-")
    assert seed.selectable == {T_CHARGE}
    assert seed.flaky == {T_FLAKY}
    assert seed.failing == {T_BROKEN}
    # Coverage paths are repo-relative, so they join the diff's paths.
    assert seed.coverage["pay.py"][3] == [T_FLAKY]
    # Only changed MUTABLE sources are captured: not the README.
    assert seed.sources == {"pay.py": HEAD_PAY}


async def test_the_build_uploads_the_diff_and_persists_one_tagged_checkpoint(demo_seed):
    runner = a_built_runner()

    await a_seed_from(runner, demo_seed)

    assert len(runner.calls) == 1
    assert runner.options[0]["disposable"] is False
    assert runner.options[0]["tag"] == seed_tag("demo")
    assert runner.files_written[0] == {DIFF_PATH: demo_seed.pr.diff}


async def test_an_errored_build_operation_is_reported_with_its_error(demo_seed):
    runner = FakeSandboxRunner(
        handler=lambda c, s, f: RunResult("", "", None, None, error="OperationTimedOutError: x")
    )

    with pytest.raises(SeedBuildError, match="OperationTimedOutError"):
        await a_seed_from(runner, demo_seed)


async def test_a_failing_build_script_is_reported_with_its_stderr(demo_seed):
    runner = FakeSandboxRunner(
        handler=lambda c, s, f: RunResult("", "error: patch failed: pay.py:1", 1, None)
    )

    with pytest.raises(SeedBuildError, match="patch failed"):
        await a_seed_from(runner, demo_seed)


async def test_a_baseline_where_nothing_passes_every_run_is_refused(demo_seed):
    runner = a_built_runner(**{RUN_LOGS[1]: STABLE.replace("PASSED", "FAILED")})

    with pytest.raises(SeedBuildError, match="no test passed"):
        await a_seed_from(runner, demo_seed)


async def test_an_invalid_slug_is_refused_before_any_sandbox_op(demo_seed):
    runner = a_built_runner()

    with pytest.raises(ValueError, match="slug"):
        await build_seed(runner, demo_seed.pr, slug="Bad Slug!", image_ref="x")

    assert runner.calls == []


def test_the_script_applies_the_diff_and_runs_the_suite_three_times():
    script = build_script("/testbed", "python -m pytest")

    assert f"git apply --whitespace=nowarn {DIFF_PATH}" in script
    assert script.count("python -m pytest") == 3
    assert script.count("--cov-context=test") == 1
    for log in RUN_LOGS:
        assert log in script


def test_coverage_paths_are_made_relative_to_the_repository():
    assert relative_to_workdir("/testbed/pkg/a.py", "/testbed") == "pkg/a.py"
    assert relative_to_workdir("pkg/a.py", "/testbed") == "pkg/a.py"
    assert relative_to_workdir("\\testbed\\pkg\\a.py", "/testbed/") == "pkg/a.py"


def test_slugs_are_restricted_to_a_tag_safe_alphabet():
    assert is_valid_slug("nomenclature-284")
    assert not is_valid_slug("")
    assert not is_valid_slug("Upper")
    assert not is_valid_slug("has space")


def test_a_seed_record_survives_a_json_round_trip(demo_seed):
    assert SeedRecord.from_json(demo_seed.to_json()) == demo_seed
