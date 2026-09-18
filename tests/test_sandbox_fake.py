from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult


async def test_fake_returns_scripted_result_for_known_command():
    runner = FakeSandboxRunner(
        responses={"pytest -q": RunResult("2 passed", "", 0, "ckpt-1")}
    )
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q")

    assert result.exit_code == 0
    assert result.stdout == "2 passed"


async def test_fake_returns_scripted_failure_unchanged():
    runner = FakeSandboxRunner(
        responses={"pytest -q": RunResult("", "1 failed", 1, None)}
    )
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q")

    assert result.exit_code == 1
    assert result.stderr == "1 failed"


async def test_fake_returns_default_success_for_unscripted_command():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "echo hello")

    assert result.exit_code == 0


async def test_fake_records_every_call_in_order():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    await runner.run(base, "first")
    await runner.run(base, "second")

    assert runner.calls == [(base, "first"), (base, "second")]


async def test_fake_records_files_written_into_the_sandbox():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    await runner.run(base, "cat /m/0.patch", files={"/m/0.patch": "diff..."})

    assert runner.files_written == [{"/m/0.patch": "diff..."}]


async def test_non_disposable_run_yields_a_new_checkpoint_id():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pip install -e .", disposable=False)

    assert result.checkpoint_id is not None
    assert result.checkpoint_id != base


async def test_disposable_run_has_no_reusable_checkpoint():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q", disposable=True)

    assert result.checkpoint_id is None


async def test_aclose_is_safe_to_call():
    runner = FakeSandboxRunner()
    await runner.aclose()
    await runner.aclose()
