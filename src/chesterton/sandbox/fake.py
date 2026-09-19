"""In-memory SandboxRunner for tests.

Deterministic, instant, and records every call so tests can assert on the
commands and files the pipeline issued.

A persisted run keeps the files it was handed, layered over its parent's, so
reading a file back from a fork sees what the parent wrote. That is the
inheritance the live service was measured to provide on 2026-09-18.
`artifacts` stands in for files a real command would have produced (a
coverage report, a test log), readable from any checkpoint.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import replace

from chesterton.paths import normalise_path
from chesterton.sandbox.protocol import (
    RunResult,
    SandboxReadError,
    require_tag_when_persisting,
)

#: Decides a run's result from (checkpoint_id, shell, files). Lets a test
#: script behaviour that depends on the files written, which a table keyed on
#: the shell string cannot express.
Handler = Callable[[str, str, Mapping[str, str | bytes]], RunResult]


def _as_bytes(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content


class FakeSandboxRunner:
    def __init__(
        self,
        responses: Mapping[str, RunResult] | None = None,
        *,
        artifacts: Mapping[str, str | bytes] | None = None,
        handler: Handler | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._artifacts = {
            normalise_path(path): _as_bytes(content)
            for path, content in (artifacts or {}).items()
        }
        self._handler = handler
        self._ids = itertools.count(1)
        self._stored: dict[str, dict[str, bytes]] = {}
        self.calls: list[tuple[str, str]] = []
        self.files_written: list[dict[str, str | bytes]] = []
        self.options: list[dict] = []
        self.reads: list[tuple[str, str]] = []

    async def use_image(self, ref: str) -> str:
        return f"img-{ref}"

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str | bytes] | None = None,
        disposable: bool = True,
        tag: str | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        require_tag_when_persisting(disposable, tag)
        self.calls.append((checkpoint_id, shell))
        written = dict(files or {})
        if files:
            self.files_written.append(written)

        self.options.append(
            {"disposable": disposable, "tag": tag, "timeout": timeout}
        )

        if self._handler is not None:
            result = self._handler(checkpoint_id, shell, written)
        else:
            result = self._responses.get(shell) or RunResult(
                stdout="", stderr="", exit_code=0, checkpoint_id=None, duration_s=0.0
            )

        # A disposable run leaves nothing to fork from, and a failed operation
        # persists nothing.
        if disposable or result.error is not None:
            return replace(result, checkpoint_id=None)

        new_id = result.checkpoint_id or f"ckpt-{next(self._ids)}"
        self._stored[new_id] = {
            **self._stored.get(checkpoint_id, {}),
            **{normalise_path(p): _as_bytes(c) for p, c in written.items()},
        }
        return replace(result, checkpoint_id=new_id)

    async def read_file(self, checkpoint_id: str, path: str) -> bytes:
        path = normalise_path(path)
        self.reads.append((checkpoint_id, path))
        stored = self._stored.get(checkpoint_id, {})
        if path in stored:
            return stored[path]
        if path in self._artifacts:
            return self._artifacts[path]
        raise SandboxReadError(f"{path} not found in checkpoint {checkpoint_id}")

    async def aclose(self) -> None:
        return None
