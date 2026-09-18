"""In-memory SandboxRunner for tests.

Deterministic, instant, and records every call so tests can assert on the
commands and files the pipeline issued.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping

from chesterton.sandbox.protocol import RunResult


class FakeSandboxRunner:
    def __init__(self, responses: Mapping[str, RunResult] | None = None) -> None:
        self._responses = dict(responses or {})
        self._ids = itertools.count(1)
        self.calls: list[tuple[str, str]] = []
        self.files_written: list[dict[str, str]] = []

    async def use_image(self, ref: str) -> str:
        return f"img-{ref}"

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str] | None = None,
        disposable: bool = True,
    ) -> RunResult:
        self.calls.append((checkpoint_id, shell))
        if files:
            self.files_written.append(dict(files))

        scripted = self._responses.get(shell)
        if scripted is not None:
            return scripted

        new_id = None if disposable else f"ckpt-{next(self._ids)}"
        return RunResult(stdout="", stderr="", exit_code=0, checkpoint_id=new_id)

    async def aclose(self) -> None:
        return None
