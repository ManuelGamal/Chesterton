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
    runner = ConTreeSandboxRunner(api_key="unused")
    assert runner.base_url == "https://api.tokenfactory.nebius.com/sandboxes"


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
