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

    `error` is set when the sandbox OPERATION failed — it timed out, was
    cancelled, or the service reported it failed — as opposed to the command
    running and exiting non-zero, which is an ordinary result. An errored run
    has no exit code: 0 would read as "tests passed" (a survivor) and anything
    else as "tests failed" (a kill), and it is neither. Consumers must check
    `error` first and exclude errored runs from statistics entirely.
    """

    stdout: str
    stderr: str
    #: The command's exit status. None exactly when `error` is set.
    exit_code: int | None
    checkpoint_id: str | None
    #: Wall time of the execution, when the backend reports one. None when the
    #: run errored — a failed operation has no meaningful duration.
    duration_s: float | None = None
    #: Why the sandbox operation produced no result, or None when it did.
    error: str | None = None


class SandboxReadError(RuntimeError):
    """A file could not be read back from a checkpoint."""


def require_tag_when_persisting(disposable: bool, tag: str | None) -> None:
    """Refuse to persist an untagged checkpoint.

    An untagged image can be garbage-collected, and judging runs for weeks
    after submission: a checkpoint that vanishes mid-judging takes the demo
    with it. Every implementation calls this first, so the constraint holds
    offline as well as live rather than being a convention callers remember.
    """
    if not disposable and not tag:
        raise ValueError(
            "every persisted checkpoint must be tagged: disposable=False "
            "requires tag=..., or the image may be garbage-collected"
        )


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
        `tag` names the resulting checkpoint so it survives garbage collection,
        and is required whenever `disposable=False` (ValueError otherwise).
        `timeout` bounds the execution in seconds.
        """
        ...

    async def read_file(self, checkpoint_id: str, path: str) -> bytes:
        """Read one file from a PERSISTED checkpoint."""
        ...

    async def aclose(self) -> None:
        """Release any transport resources. Safe to call more than once."""
        ...
