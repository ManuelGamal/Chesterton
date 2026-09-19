import builtins
import inspect
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from chesterton.sandbox.contree import ConTreeSandboxRunner
from chesterton.sandbox.protocol import SandboxRunner


def test_adapter_satisfies_the_protocol():
    assert issubclass(ConTreeSandboxRunner, SandboxRunner)


def test_run_signature_matches_the_protocol():
    sig = inspect.signature(ConTreeSandboxRunner.run)
    params = list(sig.parameters)
    assert params[:3] == ["self", "checkpoint_id", "shell"]
    assert "files" in params
    assert "disposable" in params


def test_the_async_methods_are_actually_coroutines():
    assert inspect.iscoroutinefunction(ConTreeSandboxRunner.use_image)
    assert inspect.iscoroutinefunction(ConTreeSandboxRunner.run)
    assert inspect.iscoroutinefunction(ConTreeSandboxRunner.aclose)


def test_defaults_to_the_documented_sandboxes_base_url():
    # Trailing slash matches the SDK's own ContreeEndpoint default.
    runner = ConTreeSandboxRunner(api_key="unused")
    assert runner.base_url == "https://api.tokenfactory.nebius.com/sandboxes/"


async def test_missing_sdk_raises_an_actionable_error(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("contree"):
            raise ImportError("no module named contree")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    runner = ConTreeSandboxRunner(api_key="unused")

    with pytest.raises(RuntimeError, match="contree-sdk is not installed"):
        await runner.use_image("ubuntu:latest")


def test_the_sdk_surface_this_adapter_depends_on_actually_exists():
    """Pin the real contree-sdk API, offline, with no network or credentials.

    The shape-only tests above cannot catch a wrong import path, a wrong
    constructor signature, or a wrong attribute type — and an earlier version
    of the adapter was wrong in all three ways while every test passed. This
    test builds a real client and asserts the surface the adapter calls.
    """
    pytest.importorskip("contree_sdk", reason="sandbox extra not installed")

    import inspect

    from contree_sdk import Contree
    from contree_sdk.sdk.objects.image import ContreeImage

    # The constructor takes base_url/token directly — there is no separate
    # client package to build and hand in.
    params = inspect.signature(Contree.__init__).parameters
    assert "base_url" in params
    assert "token" in params

    sdk = Contree(base_url="https://example.invalid", token="unused")
    assert hasattr(sdk.images, "use")
    assert hasattr(sdk.images, "oci")

    # run() must accept every keyword the adapter passes.
    run_params = inspect.signature(ContreeImage.run).parameters
    for keyword in ("shell", "files", "disposable", "tag"):
        assert keyword in run_params, f"ContreeImage.run lost the {keyword} keyword"

    # The adapter awaits run(); ContreeImage is awaitable even though run
    # itself is not a coroutine function.
    assert hasattr(ContreeImage, "__await__")

    # Results are read off the returned image, not a separate result object.
    for prop in ("stdout", "stderr", "exit_code"):
        assert isinstance(getattr(ContreeImage, prop), property)

    # A failed operation is signalled by these, and the adapter catches their
    # common base — if the hierarchy moves, errors would escape as crashes.
    from contree_sdk.sdk import exceptions

    for name in (
        "OperationTimedOutError",
        "FailedOperationError",
        "CancelledOperationError",
    ):
        assert issubclass(getattr(exceptions, name), exceptions.ContreeError)


def test_the_adapter_builds_a_real_client_without_network_or_credentials():
    pytest.importorskip("contree_sdk", reason="sandbox extra not installed")

    runner = ConTreeSandboxRunner(api_key="unused", project_id="project-unused")
    sdk = runner._handle()

    assert sdk is not None
    assert runner._handle() is sdk  # built once, cached


def test_a_missing_project_id_fails_with_a_legible_error(monkeypatch):
    """Sandboxes authorises on a Project header as well as a bearer token.

    Without one the API returns a bare ForbiddenError, which reads as "your
    account lacks permission" when the real cause is "you sent no project".
    That misdiagnosis cost real time, so the adapter refuses up front.
    """
    pytest.importorskip("contree_sdk", reason="sandbox extra not installed")
    monkeypatch.delenv("NEBIUS_PROJECT_ID", raising=False)

    runner = ConTreeSandboxRunner(api_key="unused")

    with pytest.raises(RuntimeError, match="NEBIUS_PROJECT_ID"):
        runner._handle()


class _FakeImage:
    """A ContreeImage double that records what run() was handed.

    Injected through `runner._sdk`, so the adapter's own run() body executes
    with no network and no credentials.
    """

    def __init__(self, *, exit_code: int = 0, raises: Exception | None = None):
        self.run_kwargs: dict | None = None
        self._exit_code = exit_code
        self._raises = raises

    async def run(self, **kwargs):
        self.run_kwargs = kwargs
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(
            stdout="out",
            stderr="err",
            exit_code=self._exit_code,
            elapsed=timedelta(seconds=1.5),
            uuid=UUID(int=7),
        )


def a_runner_over(image: _FakeImage) -> ConTreeSandboxRunner:
    async def use(ref, strict=False):
        return image

    runner = ConTreeSandboxRunner(api_key="unused", project_id="project-unused")
    runner._sdk = SimpleNamespace(images=SimpleNamespace(use=use))
    return runner


async def test_file_contents_reach_the_sdk_as_bytes_not_as_a_path():
    # contree-sdk treats a str value as a LOCAL PATH to open (it wraps it in
    # Path()); only bytes is uploaded as contents. Asserting the mapping was
    # merely "passed through" is what let the str version survive.
    image = _FakeImage()
    source = "def charge(amount):\n    return amount\n"

    await a_runner_over(image).run(
        "ckpt", "pytest -q", files={"/repo/pay.py": source}
    )

    handed = image.run_kwargs["files"]
    assert isinstance(handed, dict)
    assert isinstance(handed["/repo/pay.py"], bytes)
    assert handed["/repo/pay.py"].decode("utf-8") == source


async def test_bytes_pass_through_and_destinations_use_forward_slashes():
    # The SDK builds image paths with PurePosixPath, which reads a backslash
    # as part of one flat filename rather than as a separator.
    image = _FakeImage()

    await a_runner_over(image).run(
        "ckpt", "pytest -q", files={"repo\\widgets\\pay.py": b"x = 1\n"}
    )

    assert image.run_kwargs["files"] == {"repo/widgets/pay.py": b"x = 1\n"}


@pytest.mark.parametrize(
    "name, extra",
    [
        ("OperationTimedOutError", {}),
        ("FailedOperationError", {"error": "boom"}),
        ("CancelledOperationError", {}),
    ],
)
async def test_a_failed_sandbox_operation_is_an_error_never_a_pass_or_a_kill(
    name, extra
):
    # Measured live: a timeout raises OperationTimedOutError out of
    # `await image.run(...)`. Propagating it crashed the adapter; reporting it
    # with any exit code would count it as a pass (0) or a kill (non-zero).
    exceptions = pytest.importorskip("contree_sdk.sdk.exceptions")
    failure = getattr(exceptions, name)(operation_uuid=UUID(int=1), **extra)
    image = _FakeImage(raises=failure)

    result = await a_runner_over(image).run("ckpt", "pytest -q", timeout=5)

    assert result.error is not None
    assert type(failure).__name__ in result.error
    assert result.exit_code is None
    assert result.duration_s is None
    assert result.checkpoint_id is None


async def test_a_command_exiting_non_zero_is_an_ordinary_result_not_an_error():
    # Measured live: `exit 1` comes back SUCCEEDED with exit_code=1. That is
    # a killed mutant, and it must read as one.
    image = _FakeImage(exit_code=1)

    result = await a_runner_over(image).run("ckpt", "pytest -q")

    assert result.error is None
    assert result.exit_code == 1
    assert result.stdout == "out"
    assert result.duration_s == 1.5


async def test_the_adapter_refuses_to_persist_an_untagged_checkpoint():
    image = _FakeImage()

    with pytest.raises(ValueError, match="must be tagged"):
        await a_runner_over(image).run("ckpt", "pip install -e .", disposable=False)

    assert image.run_kwargs is None  # refused before the SDK was touched


async def test_the_adapter_forwards_the_tag_of_a_persisted_run():
    image = _FakeImage()

    await a_runner_over(image).run(
        "ckpt", "pip install -e .", disposable=False, tag="chesterton:base"
    )

    assert image.run_kwargs["disposable"] is False
    assert image.run_kwargs["tag"] == "chesterton:base"


async def test_an_error_outside_the_sdk_still_propagates():
    # Only the SDK's own errors become `error`; a bug here must surface.
    image = _FakeImage(raises=TypeError("a bug in our own code"))

    with pytest.raises(TypeError, match="a bug in our own code"):
        await a_runner_over(image).run("ckpt", "pytest -q")
