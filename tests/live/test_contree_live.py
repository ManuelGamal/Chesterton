"""Opt-in integration tests against the real Token Factory Sandboxes service.

Skipped unless CHESTERTON_LIVE=1 and both credentials are set. They exist
because no offline test can prove the service agrees with the adapter. Every
fake here was written from a reading of the SDK, and three defects on this
project came from reading that SDK wrong.

Each test costs one to three sandbox ops against ubuntu:latest. Run with:

    CHESTERTON_LIVE=1 python -m pytest tests/live -q
"""

from __future__ import annotations

import os

import pytest

from chesterton.sandbox.contree import ConTreeSandboxRunner
from chesterton.sandbox.protocol import SandboxReadError

LIVE = os.environ.get("CHESTERTON_LIVE") == "1" and all(
    os.environ.get(name) for name in ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID")
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not LIVE,
        reason="live: set CHESTERTON_LIVE=1, NEBIUS_API_KEY and NEBIUS_PROJECT_ID",
    ),
]

IMAGE = "ubuntu:latest"
TAG = "chesterton:live-test"


@pytest.fixture
async def runner():
    live = ConTreeSandboxRunner()
    yield live
    await live.aclose()


@pytest.fixture
async def base(runner):
    return await runner.use_image(IMAGE)


async def test_a_disposable_run_executes_and_leaves_no_checkpoint(runner, base):
    result = await runner.run(base, "echo hello")

    assert result.error is None
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.checkpoint_id is None
    assert result.duration_s is not None and result.duration_s > 0


async def test_a_non_zero_exit_is_an_ordinary_result(runner, base):
    result = await runner.run(base, "echo out; echo err >&2; exit 3")

    assert result.error is None
    assert result.exit_code == 3
    assert "err" in result.stderr


async def test_a_timeout_is_an_error_never_an_exit_code(runner, base):
    result = await runner.run(base, "sleep 60", timeout=5)

    assert result.error is not None
    assert "TimedOut" in result.error
    assert result.exit_code is None


async def test_files_are_uploaded_as_contents_into_a_new_directory(runner, base):
    # Task 4 writes the PR diff to /chesterton/pr.diff before its script runs,
    # so the upload itself must create /chesterton.
    result = await runner.run(
        base, "cat /chesterton/probe.txt",
        files={"/chesterton/probe.txt": "written by chesterton\n"},
    )

    assert result.error is None
    assert result.exit_code == 0
    assert result.stdout == "written by chesterton\n"


async def test_a_persisted_run_can_be_read_back_and_forked(runner, base):
    built = await runner.run(
        base, "mkdir -p /chesterton && echo persisted > /chesterton/state.txt",
        disposable=False, tag=TAG,
    )
    assert built.error is None
    assert built.checkpoint_id not in (None, base)

    data = await runner.read_file(built.checkpoint_id, "/chesterton/state.txt")
    fork = await runner.run(built.checkpoint_id, "cat /chesterton/state.txt")

    assert data == b"persisted\n"
    assert fork.stdout == "persisted\n"


async def test_reading_a_missing_file_raises_a_read_error(runner, base):
    built = await runner.run(base, "true", disposable=False, tag=TAG)

    with pytest.raises(SandboxReadError):
        await runner.read_file(built.checkpoint_id, "/no/such/file")


async def test_an_untagged_persisted_run_is_refused_before_the_network(runner, base):
    with pytest.raises(ValueError, match="must be tagged"):
        await runner.run(base, "true", disposable=False)
