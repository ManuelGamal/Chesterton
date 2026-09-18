import builtins
import inspect

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
