"""The sandbox boundary.

Everything downstream talks to this protocol, never to ConTree directly.
That is what lets the whole pipeline run offline against a fake.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RunResult:
    """The outcome of one command executed inside a sandbox.

    `checkpoint_id` is the id of the persisted filesystem state, or None when
    the run was disposable. A disposable run leaves nothing to fork from, and
    both the fake and the real adapter must report that the same way — a fake
    that invents an id here would let offline code depend on something the
    live service cannot provide.
    """

    stdout: str
    stderr: str
    exit_code: int
    checkpoint_id: str | None
    #: Wall time of the execution, when the backend reports one. None when the
    #: run errored — a failed operation has no meaningful duration, and the
    #: real SDK raises rather than returning one.
    duration_s: float | None = None


@runtime_checkable
class SandboxRunner(Protocol):
    async def use_image(self, ref: str) -> str:
        """Resolve an image reference to a checkpoint id."""
        ...

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
        """Fork `checkpoint_id`, write `files`, run `shell`.

        `files` maps destination path to file CONTENTS — text or bytes,
        never a local path to read from. Text is written as UTF-8.
        `disposable=False` persists the resulting filesystem as a new
        checkpoint and returns its id; `disposable=True` returns None.
        `tag` names the resulting checkpoint so it survives garbage collection.
        `timeout` bounds the execution in seconds.
        """
        ...

    async def aclose(self) -> None:
        """Release any transport resources. Safe to call more than once."""
        ...
