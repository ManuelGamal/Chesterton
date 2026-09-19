import pytest

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

    result = await runner.run(
        base, "pip install -e .", disposable=False, tag="chesterton:base"
    )

    assert result.checkpoint_id is not None
    assert result.checkpoint_id != base


async def test_disposable_run_has_no_reusable_checkpoint():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q", disposable=True)

    assert result.checkpoint_id is None


async def test_a_scripted_result_still_honours_the_disposable_rule():
    # The fake must not promise a checkpoint the live service would not give.
    runner = FakeSandboxRunner(
        responses={"pytest -q": RunResult("2 passed", "", 0, "ckpt-1")}
    )
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q", disposable=True)

    assert result.checkpoint_id is None
    assert result.stdout == "2 passed"


async def test_aclose_is_safe_to_call():
    runner = FakeSandboxRunner()
    await runner.aclose()
    await runner.aclose()


async def test_the_fake_records_tag_and_timeout_on_a_persisted_run():
    # On a persisted run, where the tag is what keeps the checkpoint alive —
    # a disposable run persists nothing, so a tag there proves nothing.
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(
        base, "pip install -e .", disposable=False, tag="chesterton:base",
        timeout=30.0,
    )

    assert result.checkpoint_id is not None
    assert runner.options == [
        {"disposable": False, "tag": "chesterton:base", "timeout": 30.0}
    ]


@pytest.mark.parametrize("tag", [None, ""])
async def test_persisting_an_untagged_checkpoint_is_refused(tag):
    # An untagged image can be garbage-collected mid-judging.
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    with pytest.raises(ValueError, match="must be tagged"):
        await runner.run(base, "pip install -e .", disposable=False, tag=tag)

    assert runner.calls == []  # refused before anything ran


async def test_a_disposable_run_needs_no_tag():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q", disposable=True)

    assert result.checkpoint_id is None


async def test_a_run_reports_a_duration():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q")

    assert result.duration_s is not None
    assert result.duration_s >= 0.0


async def test_a_scripted_result_keeps_its_own_duration():
    runner = FakeSandboxRunner(
        responses={"slow": RunResult("", "", 0, None, duration_s=12.5)}
    )
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "slow")

    assert result.duration_s == 12.5

from chesterton.sandbox.protocol import SandboxReadError


async def test_a_file_written_by_a_persisted_run_can_be_read_back():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    built = await runner.run(
        base, "true", files={"/testbed/a.py": "x = 1\n"},
        disposable=False, tag="chesterton:t",
    )

    assert await runner.read_file(built.checkpoint_id, "/testbed/a.py") == b"x = 1\n"


async def test_a_fork_inherits_the_files_of_its_parent():
    # Measured live 2026-09-18: forks carry the parent's filesystem.
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")
    parent = await runner.run(
        base, "true", files={"/p.txt": b"parent"}, disposable=False, tag="chesterton:p"
    )

    child = await runner.run(
        parent.checkpoint_id, "true", files={"/c.txt": "child"},
        disposable=False, tag="chesterton:c",
    )

    assert await runner.read_file(child.checkpoint_id, "/p.txt") == b"parent"
    assert await runner.read_file(child.checkpoint_id, "/c.txt") == b"child"


async def test_a_disposable_run_stores_nothing_to_read():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")
    await runner.run(base, "true", files={"/gone.txt": "x"})

    with pytest.raises(SandboxReadError):
        await runner.read_file(base, "/gone.txt")


async def test_artifacts_stand_in_for_files_a_command_would_produce():
    runner = FakeSandboxRunner(artifacts={"/chesterton/coverage.json": "{}"})

    assert await runner.read_file("any-ckpt", "/chesterton/coverage.json") == b"{}"
    assert runner.reads == [("any-ckpt", "/chesterton/coverage.json")]


async def test_a_handler_decides_the_result_from_the_files_written():
    def handler(checkpoint_id, shell, files):
        killed = "raise" not in files.get("/testbed/pay.py", "raise")
        return RunResult("", "", 1 if killed else 0, None)

    runner = FakeSandboxRunner(handler=handler)
    base = await runner.use_image("python:3.13")

    kept = await runner.run(base, "pytest", files={"/testbed/pay.py": "raise X\n"})
    dropped = await runner.run(base, "pytest", files={"/testbed/pay.py": "pass\n"})

    assert kept.exit_code == 0
    assert dropped.exit_code == 1


async def test_an_errored_persisted_run_yields_no_checkpoint():
    # A failed operation persists nothing, so there is nothing to fork from.
    runner = FakeSandboxRunner(
        handler=lambda c, s, f: RunResult("", "", None, None, error="TimedOut")
    )
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "build", disposable=False, tag="chesterton:t")

    assert result.error == "TimedOut"
    assert result.checkpoint_id is None
