# Chesterton Phase 3 — Execution and Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a curated pull request into a tagged baseline checkpoint, then execute a full run against it: tier-0 findings, mutant fan-out with honest verdicts, and a ddmin search for the minimal set of hunks the tests actually need. The run is bounded by a concurrency cap and a per-run op budget.

**Architecture:** Build time and run time are separate. At build time `build_seed` applies the PR diff inside a prebuilt SWE-rebench image. It runs the suite three times, the first under coverage contexts, and persists one tagged checkpoint. It then reads the artifacts back as files, so the SDK's 64 KiB stdout limit never truncates them. At run time every sandbox operation goes through one `SandboxPool`, which holds `asyncio.Semaphore(24)` and a hard op budget. Mutant fan-out and ddmin probes share that pool.

**Tech Stack:** Python 3.13, asyncio, unidiff, LibCST (via Phase 2), contree-sdk 0.3.6, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-09-18-chesterton-design.md`. It is the binding authority: §4 covers the phases and data model, §6 the budget, §7 test selection, §8 ddmin, §14 failure modes, §15 risks and live measurements. Read `docs/superpowers/phase-2-handoff.md` too, because its "Required in Phase 3" list is folded into Tasks 2, 5, 6 and 10.

## Global Constraints

- The repository ships under **MIT**. No AGPL dependencies.
- **Python repositories only.**
- Sandbox concurrency is capped at **`asyncio.Semaphore(24)`**.
- A failed or timed-out sandbox operation is **`error`**. It is excluded from statistics and is **never** counted as `killed`.
- **Only pytest exit code 1 is a kill.** Exit 0 means survived. Every other exit code (2 interrupted or collection error, 3 internal, 4 usage, 5 no tests collected) is `error`.
- **Check `RunResult.error` before reading `exit_code`.** `exit_code` is `None` exactly when `error` is set.
- The absence of a detected behavioural difference is **never** rendered as "equivalent". A mutant that no selected test fails is "survived", and the wording is "no selected test failed".
- Every persisted checkpoint must be **tagged**.
- **All file paths are normalised to forward slashes at every boundary.**
- **A disposable run has no reusable checkpoint** (`checkpoint_id is None`).
- **Every run-time sandbox op goes through `SandboxPool`.** Only the build-time seed build calls the runner directly.
- **A test is selectable only if it passed in all three baseline runs.**
- **Refuse to start rather than overspend.** If a run's mutant ops alone exceed its op budget, it raises `RunRefused` before issuing a single sandbox op.
- No network calls in unit tests. The single exception is `tests/live/`, which is skipped unless `CHESTERTON_LIVE=1`.
- **No public symbol a test module imports may begin with `test`.** pytest's `python_functions` glob is `test*`.
- Write every file as plain UTF-8 with LF and **no BOM**.
- Commits are authored as the user, with **no `Co-Authored-By`, `Claude-Session` or "Generated with Claude Code" trailer.**

## Rulings baked into this plan

These settle questions the spec leaves open. Each one records what it costs if it is wrong.

**P3-1: what ddmin minimises.** Spec §8 says ddmin "isolates the minimal subset of hunks the test suite fails to defend", with the example "Of 11 hunks, these 2 are the entire undefended surface". The plan makes that operational like this:

> A probe applies only a subset *S* of the PR's source hunks, reverting every other source hunk to its pre-patch text, then runs the selectable suite. The property is **"the suite passes"**. ddmin finds a 1-minimal *S* for which the property holds: the hunks the tests actually **need**. Every other hunk is the **undefended surface**, a change the suite would not notice if it were undone.

The search starts from the full PR, which holds by construction because every selectable test passed at head three times. It checks the empty set first. If the suite passes with the whole PR reverted, the entire PR is undefended, and that costs one probe. Test-file hunks are never reverted, because the PR's own tests are the oracle. *Cost if wrong:* Task 9's probe predicate. ddmin (Task 7) and the revert machinery (Task 8) are generic and survive a different reading.

**P3-2: the budget guard counts ops, not dollars.** §14 asks for "a hard per-run budget cap in dollars and ops", but sandboxes are free during the beta (§11). The only priced model the spec has verified is Ultra, which Phase 3 does not call, and Lightning's price is not recorded anywhere. A dollar cap built on an invented price would be a fabricated guarantee. Phase 3 caps **sandbox ops**, which protect the beta op quota, and **model calls** (one retry per hunk). The dollar cap arrives in Phase 4 with Super and Ultra, after their prices are read from `GET /v1/models?verbose=true`. *Cost if wrong:* one cap to add later.

**P3-3: artifacts come back as files, not stdout.** The SDK truncates stdout at 65,535 bytes by default (`default_truncate_output_at`), and a real coverage-contexts report is larger than that. `ContreeImage.read(path) -> bytes` is public in contree-sdk 0.3.6. The protocol grows `read_file`, and the seed build persists its checkpoint so the artifacts can be read back. *Cost if wrong:* nothing structural. The live test in Task 2 confirms it.

**P3-4: the seed build is one persisted operation.** Applying the diff, installing `pytest-cov`, the coverage run and two plain runs all happen in one tagged op. That gives one checkpoint to protect from garbage collection and one place to fail with a legible error. *Cost if wrong:* a longer single op. It is build-time only, and the judge never waits on it.

**P3-5: the head state comes from `git apply` of the PR diff**, not from `git fetch`. It needs no egress to GitHub, which is unverified from inside a sandbox, and it matches §4 ("resolve base SHA and diff"). If the diff does not apply to the image's commit, the build fails with git's own message. Task 12 records whether it applies for the first real seed. *Cost if wrong:* switch the one shell line to fetch `pull/N/head`.

**P3-6: tier 0 and test selection use the same coverage.** Coverage is restricted to selectable tests before either one reads it. A line executed only by a flaky or always-failing test is not defended, so it is reported as uncovered. *Cost if wrong:* a few more tier-0 findings, all of them honest.

**P3-7: ddmin probes each granularity concurrently.** Every candidate subset at one granularity is probed at once through the shared pool, and the first one that holds, in a fixed order, is chosen. The result is exactly what sequential ddmin would reach, at the price of extra probes. That trade favours the live demo's wall clock. Probes are cached by subset, so a revisited subset costs nothing. *Cost if wrong:* switch to sequential ddmin, which is cheaper in ops.

**P3-8: running out of budget mid-search is reported, not hidden.** ddmin's current set always satisfies the property, so a search cut short still returns a set the suite needs *at most*. Everything outside it is undefended *at least*. The result carries `exhausted=True`, and the CLI prints that caveat.

---

## File structure

| File | Responsibility |
|---|---|
| `src/chesterton/sandbox/protocol.py` (modify) | `read_file` on the protocol; `SandboxReadError` |
| `src/chesterton/sandbox/fake.py` (modify) | fork-inheriting stored files, `artifacts`, `handler`, `read_file` |
| `src/chesterton/sandbox/contree.py` (modify) | `read_file` via `ContreeImage.read` |
| `tests/live/test_contree_live.py` (create) | opt-in live tests of the real adapter |
| `src/chesterton/seed/outcomes.py` | parse pytest `-rA` summaries; classify selectable, flaky, failing |
| `src/chesterton/seed/record.py` | `SeedRecord` and its JSON form |
| `src/chesterton/seed/build.py` | the build-time pipeline |
| `src/chesterton/execute/pool.py` | `SandboxPool`: semaphore plus op budget |
| `src/chesterton/execute/mutants.py` | test selection, verdict classification, fan-out |
| `src/chesterton/reduce/ddmin.py` | generic concurrent, cached ddmin |
| `src/chesterton/reduce/patch.py` | PR diff hunks and exact revert |
| `src/chesterton/reduce/surface.py` | ddmin over hunks with sandbox probes |
| `src/chesterton/run.py` | the run orchestrator and `RunReport` |
| `src/chesterton/__main__.py` | the `python -m chesterton seed|run` CLI |
| `tests/conftest.py` (create) | the `demo_seed` fixture shared by Tasks 6, 9, 10 and 11 |

---

### Task 1: The protocol learns to read files back

**Files:**
- Modify: `src/chesterton/sandbox/protocol.py`
- Modify: `src/chesterton/sandbox/fake.py`
- Modify: `src/chesterton/sandbox/contree.py`
- Test: `tests/test_sandbox_fake.py` (append), `tests/test_sandbox_contree.py` (append)

**Interfaces:**
- Consumes: `RunResult`, `require_tag_when_persisting` (Phase 1/2); `normalise_path` from `chesterton.paths`.
- Produces: `SandboxReadError(RuntimeError)` in `chesterton.sandbox.protocol`; `SandboxRunner.read_file(checkpoint_id: str, path: str) -> bytes`; `FakeSandboxRunner(responses=None, *, artifacts: Mapping[str, str | bytes] | None = None, handler: Handler | None = None)` with `.reads: list[tuple[str, str]]`; `Handler = Callable[[str, str, Mapping[str, str | bytes]], RunResult]` in `chesterton.sandbox.fake`.

Every existing test in `tests/test_sandbox_fake.py` and `tests/test_sandbox_contree.py` must pass **unchanged**. If one breaks, stop and report BLOCKED. Do not edit it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sandbox_fake.py`:

```python
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
```

Append to `tests/test_sandbox_contree.py`:

```python
from chesterton.sandbox.protocol import SandboxReadError


class _ReadableImage:
    def __init__(self, *, content: bytes = b"", raises: Exception | None = None):
        self.read_paths: list[str] = []
        self._content = content
        self._raises = raises

    async def read(self, path):
        self.read_paths.append(path)
        if self._raises is not None:
            raise self._raises
        return self._content


def a_reader_over(image: _ReadableImage) -> ConTreeSandboxRunner:
    async def use(ref, strict=False):
        return image

    runner = ConTreeSandboxRunner(api_key="unused", project_id="project-unused")
    runner._sdk = SimpleNamespace(images=SimpleNamespace(use=use))
    return runner


def test_read_file_is_part_of_the_protocol_and_a_coroutine():
    assert inspect.iscoroutinefunction(ConTreeSandboxRunner.read_file)
    assert "read_file" in dir(SandboxRunner)


async def test_read_file_returns_the_bytes_and_uses_forward_slashes():
    image = _ReadableImage(content=b'{"files": {}}')

    data = await a_reader_over(image).read_file("ckpt", "\\chesterton\\coverage.json")

    assert data == b'{"files": {}}'
    assert image.read_paths == ["/chesterton/coverage.json"]


async def test_an_sdk_read_failure_becomes_a_sandbox_read_error():
    exceptions = pytest.importorskip("contree_sdk.sdk.exceptions")
    failure = exceptions.OperationTimedOutError(operation_uuid=UUID(int=1))
    image = _ReadableImage(raises=failure)

    with pytest.raises(SandboxReadError, match="OperationTimedOutError"):
        await a_reader_over(image).read_file("ckpt", "/chesterton/run1.txt")


async def test_a_non_sdk_error_while_reading_still_propagates():
    image = _ReadableImage(raises=TypeError("a bug in our own code"))

    with pytest.raises(TypeError, match="a bug in our own code"):
        await a_reader_over(image).read_file("ckpt", "/x")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_fake.py tests/test_sandbox_contree.py -q`
Expected: FAIL. `SandboxReadError` cannot be imported, and `read_file` does not exist.

- [ ] **Step 3: Extend the protocol**

In `src/chesterton/sandbox/protocol.py`, add after `RunResult`:

```python
class SandboxReadError(RuntimeError):
    """A file could not be read back from a checkpoint."""
```

Add this method to `SandboxRunner`, between `run` and `aclose`:

```python
    async def read_file(self, checkpoint_id: str, path: str) -> bytes:
        """Read one file from a PERSISTED checkpoint.

        Artifacts come back through here rather than through stdout, which
        the SDK truncates at 64 KiB by default: a real coverage-contexts
        report is larger than that. A disposable run leaves nothing to read.
        Raises SandboxReadError when the file or checkpoint cannot be read.
        """
        ...
```

- [ ] **Step 4: Rewrite the fake**

Replace `src/chesterton/sandbox/fake.py` with:

```python
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
```

- [ ] **Step 5: Add `read_file` to the adapter**

In `src/chesterton/sandbox/contree.py`, change the protocol import to:

```python
from chesterton.sandbox.protocol import (
    RunResult,
    SandboxReadError,
    require_tag_when_persisting,
)
```

Add this method to `ConTreeSandboxRunner`, between `run` and `aclose`:

```python
    async def read_file(self, checkpoint_id: str, path: str) -> bytes:
        """Read one file from a persisted checkpoint via `ContreeImage.read`.

        Only the SDK's own errors become SandboxReadError; a bug in this code
        must still surface, as it does in run().
        """
        sdk = self._handle()
        from contree_sdk.sdk.exceptions import ContreeError

        path = normalise_path(path)
        try:
            image = await sdk.images.use(checkpoint_id)
            return await image.read(path)
        except ContreeError as exc:
            raise SandboxReadError(
                f"could not read {path} from checkpoint {checkpoint_id}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_fake.py tests/test_sandbox_contree.py -q`
Expected: PASS. Every pre-existing test is unchanged and green.

Then run: `.venv/Scripts/python -m pytest -q`
Expected: the full suite is green.

- [ ] **Step 7: Commit**

```bash
git add src/chesterton/sandbox tests/test_sandbox_fake.py tests/test_sandbox_contree.py
git commit -m "feat: read files back from persisted checkpoints"
```

---

### Task 2: Opt-in live tests of the real adapter

This closes ruling P15 from Phase 2. `ConTreeSandboxRunner.run`'s body is still exercised by nothing that talks to the real service. These tests also confirm P3-3 (`read_file`) and the assumption Task 4 rests on: that `files=` can write into a directory that does not exist yet.

**Files:**
- Create: `tests/live/__init__.py` (empty)
- Create: `tests/live/test_contree_live.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `ConTreeSandboxRunner`, `SandboxReadError`.
- Produces: the `live` pytest marker.

- [ ] **Step 1: Register the marker**

In `pyproject.toml`, under `[tool.pytest.ini_options]`, add:

```toml
markers = [
    "live: talks to the real Token Factory Sandboxes service; opt in with CHESTERTON_LIVE=1",
]
```

- [ ] **Step 2: Write the live tests**

`tests/live/test_contree_live.py`:

```python
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
```

- [ ] **Step 3: Verify they are skipped offline**

Run: `.venv/Scripts/python -m pytest tests/live -q`
Expected: `7 skipped`. No network call is made.

Then run: `.venv/Scripts/python -m pytest -q`
Expected: the full suite is green, with the 7 live tests skipped.

- [ ] **Step 4: Commit**

```bash
git add tests/live pyproject.toml
git commit -m "test: add opt-in live tests of the ConTree adapter"
```

The **controller**, not the implementer, runs these live with the user's credentials after the task review. Record the outcome in the ledger. Any failure is a defect in the adapter or the fake, and it is fixed before Task 4 starts.

---

### Task 3: Per-test outcomes and which tests are selectable

**Files:**
- Create: `src/chesterton/seed/__init__.py` (empty)
- Create: `src/chesterton/seed/outcomes.py`
- Test: `tests/test_seed_outcomes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PASSED: str`; `parse_outcomes(report: str) -> dict[str, str]`; `Selectability(selectable: frozenset[str], flaky: frozenset[str], failing: frozenset[str])`; `classify_runs(runs: Sequence[Mapping[str, str]]) -> Selectability`.

- [ ] **Step 1: Write the failing test**

`tests/test_seed_outcomes.py`:

```python
import pytest

from chesterton.seed.outcomes import classify_runs, parse_outcomes

REPORT = """\
============================= test session starts =============================
collected 3 items

tests/test_pay.py .F.                                                     [100%]

=========================== short test summary info ===========================
PASSED tests/test_pay.py::test_charge
PASSED tests/test_pay.py::test_refund[zero]
FAILED tests/test_pay.py::test_broken - AssertionError: expected 3
SKIPPED [1] tests/test_pay.py:40: needs a network
1 failed, 2 passed, 1 skipped in 0.12s
"""


def test_summary_lines_become_node_id_outcomes():
    assert parse_outcomes(REPORT) == {
        "tests/test_pay.py::test_charge": "PASSED",
        "tests/test_pay.py::test_refund[zero]": "PASSED",
        "tests/test_pay.py::test_broken": "FAILED",
    }


def test_a_teardown_error_after_a_pass_is_not_a_pass():
    # -rA reports both phases for one test; any non-pass must win.
    report = "PASSED tests/t.py::test_x\nERROR tests/t.py::test_x - RuntimeError\n"
    assert parse_outcomes(report) == {"tests/t.py::test_x": "ERROR"}


def test_a_non_pass_is_not_overwritten_by_a_later_pass():
    report = "ERROR tests/t.py::test_x - boom\nPASSED tests/t.py::test_x\n"
    assert parse_outcomes(report) == {"tests/t.py::test_x": "ERROR"}


def test_only_tests_passing_every_run_are_selectable():
    stable = {"t::a": "PASSED", "t::b": "PASSED", "t::c": "FAILED"}
    wobbly = {"t::a": "PASSED", "t::b": "FAILED", "t::c": "FAILED"}

    result = classify_runs([stable, wobbly, stable])

    assert result.selectable == {"t::a"}
    assert result.flaky == {"t::b"}
    assert result.failing == {"t::c"}


def test_a_test_missing_from_one_run_is_flaky():
    # Not collected every time is a disagreement between runs.
    result = classify_runs([{"t::a": "PASSED"}, {}, {"t::a": "PASSED"}])

    assert result.flaky == {"t::a"}
    assert result.selectable == frozenset()


def test_an_expected_failure_is_never_selectable():
    result = classify_runs([{"t::x": "XFAIL"}] * 3)

    assert result.failing == {"t::x"}
    assert result.selectable == frozenset()


def test_classifying_no_runs_is_refused():
    with pytest.raises(ValueError):
        classify_runs([])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_seed_outcomes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.seed'`.

- [ ] **Step 3: Write the module**

`src/chesterton/seed/outcomes.py`:

```python
"""Per-test outcomes from pytest's `-rA` short summary, and which tests are
safe to select.

A test is SELECTABLE only if it passed in every baseline run. Two other kinds
are excluded, for different reasons:

- flaky: its outcome differed between runs, or it was not collected every
  time. A mutant "killed" by a flaky test may have been killed by chance,
  which is a fabricated kill.
- failing: it never passed (failed, errored, xfailed). It fails with or
  without the mutant, so it would report every mutant as killed.

The ids are pytest node ids. That is what `-rA` prints and what pytest-cov
records as a coverage context, so the two join without translation. JUnit XML
was rejected: its dotted classnames do not round-trip to node ids for test
classes or parametrised tests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

PASSED = "PASSED"

#: "PASSED tests/t.py::test_x" or "FAILED tests/t.py::test_y - Error: ...".
#: SKIPPED lines have a different shape ("SKIPPED [1] file:line: reason") and
#: are deliberately not matched: a skipped test defends nothing.
_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS)\s+(\S+)")


def parse_outcomes(report: str) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for line in report.splitlines():
        match = _LINE.match(line)
        if match is None:
            continue
        status, node = match.groups()
        # One test can be reported twice (a pass in call, then an error in
        # teardown). Any non-pass is sticky.
        if outcomes.get(node, PASSED) == PASSED:
            outcomes[node] = status
    return outcomes


@dataclass(frozen=True)
class Selectability:
    selectable: frozenset[str]
    flaky: frozenset[str]
    failing: frozenset[str]


def classify_runs(runs: Sequence[Mapping[str, str]]) -> Selectability:
    if not runs:
        raise ValueError("classify_runs needs at least one run")

    every: set[str] = set()
    for run in runs:
        every.update(run)

    selectable: set[str] = set()
    flaky: set[str] = set()
    failing: set[str] = set()
    for node in every:
        seen = [run.get(node) for run in runs]
        if all(status == PASSED for status in seen):
            selectable.add(node)
        elif None in seen or PASSED in seen:
            flaky.add(node)
        else:
            failing.add(node)

    return Selectability(frozenset(selectable), frozenset(flaky), frozenset(failing))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_seed_outcomes.py -q`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/seed tests/test_seed_outcomes.py
git commit -m "feat: parse per-test outcomes and classify selectable tests"
```

---

### Task 4: The seed record and the build-time pipeline

**Files:**
- Create: `src/chesterton/seed/record.py`
- Create: `src/chesterton/seed/build.py`
- Create: `tests/conftest.py`
- Test: `tests/test_seed_build.py`

**Interfaces:**
- Consumes: `SandboxRunner`, `SandboxReadError` (Task 1); `parse_outcomes`, `classify_runs` (Task 3); `PullRequest`, `CoverageMap` from `chesterton.models`; `invert_coverage` from `chesterton.covmap.invert`; `changed_lines` from `chesterton.diffing.parse`; `is_mutable_source` from `chesterton.filters`; `normalise_path` from `chesterton.paths`.
- Produces: in `chesterton.seed.record`, `SeedRecord` (fields below), `SeedRecord.to_json() -> str`, `SeedRecord.from_json(text: str) -> SeedRecord`, `is_valid_slug(slug: str) -> bool`, `seed_tag(slug: str) -> str`. In `chesterton.seed.build`: `DEFAULT_WORKDIR = "/testbed"`, `DEFAULT_TEST_COMMAND = "python -m pytest"`, `DIFF_PATH`, `COVERAGE_PATH`, `RUN_LOGS: tuple[str, str, str]`, `SeedBuildError(RuntimeError)`, `build_script(workdir: str, test_command: str) -> str`, `relative_to_workdir(path: str, workdir: str) -> str`, `async build_seed(runner, pr, *, slug, image_ref, workdir=DEFAULT_WORKDIR, test_command=DEFAULT_TEST_COMMAND, timeout=SEED_TIMEOUT_S) -> SeedRecord`. In `tests/conftest.py`, the fixture `demo_seed` and the module constants `DEMO_DIFF` and `HEAD_PAY`.

`SeedRecord` fields, in order: `slug: str`, `pr: PullRequest`, `image_ref: str`, `workdir: str`, `test_command: str`, `checkpoint_id: str`, `checkpoint_tag: str`, `coverage: CoverageMap`, `selectable: frozenset[str]`, `flaky: frozenset[str]`, `failing: frozenset[str]`, `sources: dict[str, str]`, `built_at: str`.

- [ ] **Step 1: Write the shared fixture**

`tests/conftest.py`:

```python
"""Fixtures shared across the Phase 3 test modules.

The demo seed is small enough to reason about by hand. It is a PR that adds
a guard to `charge`, plus a README line. The guard's `raise` is executed only
by a flaky test, which makes it a real tier-0 finding once coverage is
restricted to selectable tests (ruling P3-6).
"""

from __future__ import annotations

import pytest

from chesterton.models import PullRequest
from chesterton.seed.record import SeedRecord

DEMO_DIFF = (
    "--- a/pay.py\n"
    "+++ b/pay.py\n"
    "@@ -1,2 +1,4 @@\n"
    " def charge(amount):\n"
    "+    if not amount:\n"
    '+        raise ValueError("required")\n'
    "     return amount\n"
    "--- a/README.md\n"
    "+++ b/README.md\n"
    "@@ -1 +1,2 @@\n"
    " # Pay\n"
    "+Charges must be non-zero.\n"
)

HEAD_PAY = (
    "def charge(amount):\n"
    "    if not amount:\n"
    '        raise ValueError("required")\n'
    "    return amount\n"
)

T_CHARGE = "tests/test_pay.py::test_charge"
T_FLAKY = "tests/test_pay.py::test_flaky"


@pytest.fixture
def demo_seed() -> SeedRecord:
    pr = PullRequest(
        owner="acme",
        repo="pay",
        number=1,
        title="Require a non-zero amount",
        base_sha="b" * 40,
        head_sha="h" * 40,
        merge_base_sha="b" * 40,
        clone_url="https://github.com/acme/pay.git",
        diff=DEMO_DIFF,
    )
    return SeedRecord(
        slug="demo",
        pr=pr,
        image_ref="docker://example/pay",
        workdir="/testbed",
        test_command="python -m pytest",
        checkpoint_id="ckpt-seed",
        checkpoint_tag="chesterton:seed-demo",
        coverage={"pay.py": {1: [T_CHARGE], 2: [T_CHARGE], 3: [T_FLAKY], 4: [T_CHARGE]}},
        selectable=frozenset({T_CHARGE}),
        flaky=frozenset({T_FLAKY}),
        failing=frozenset(),
        sources={"pay.py": HEAD_PAY},
        built_at="2026-09-19T00:00:00+00:00",
    )
```

- [ ] **Step 2: Write the failing test**

`tests/test_seed_build.py`:

```python
import json

import pytest

from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.build import (
    COVERAGE_PATH,
    DIFF_PATH,
    RUN_LOGS,
    SeedBuildError,
    build_script,
    build_seed,
    relative_to_workdir,
)
from chesterton.seed.record import SeedRecord, is_valid_slug, seed_tag

from conftest import HEAD_PAY, T_CHARGE, T_FLAKY

T_BROKEN = "tests/test_pay.py::test_broken"

STABLE = f"""\
=========================== short test summary info ===========================
PASSED {T_CHARGE}
PASSED {T_FLAKY}
FAILED {T_BROKEN} - AssertionError: no
1 failed, 2 passed in 0.10s
"""
WOBBLY = STABLE.replace(f"PASSED {T_FLAKY}", f"FAILED {T_FLAKY} - AssertionError")

COVERAGE = {
    "files": {
        "/testbed/pay.py": {
            "contexts": {
                "1": [f"{T_CHARGE}|run"],
                "2": [f"{T_CHARGE}|run"],
                "3": [f"{T_FLAKY}|run"],
                "4": [f"{T_CHARGE}|run"],
            }
        }
    }
}


def a_built_runner(**overrides) -> FakeSandboxRunner:
    artifacts = {
        RUN_LOGS[0]: STABLE,
        RUN_LOGS[1]: WOBBLY,
        RUN_LOGS[2]: STABLE,
        COVERAGE_PATH: json.dumps(COVERAGE),
        "/testbed/pay.py": HEAD_PAY,
    }
    artifacts.update(overrides)
    return FakeSandboxRunner(artifacts=artifacts)


async def a_seed_from(runner, demo_seed):
    return await build_seed(
        runner, demo_seed.pr, slug="demo", image_ref="docker://example/pay"
    )


async def test_a_built_seed_records_what_the_run_phase_needs(demo_seed):
    seed = await a_seed_from(a_built_runner(), demo_seed)

    assert seed.checkpoint_tag == "chesterton:seed-demo"
    assert seed.checkpoint_id.startswith("ckpt-")
    assert seed.selectable == {T_CHARGE}
    assert seed.flaky == {T_FLAKY}
    assert seed.failing == {T_BROKEN}
    # Coverage paths are repo-relative, so they join the diff's paths.
    assert seed.coverage["pay.py"][3] == [T_FLAKY]
    # Only changed MUTABLE sources are captured: not the README.
    assert seed.sources == {"pay.py": HEAD_PAY}


async def test_the_build_uploads_the_diff_and_persists_one_tagged_checkpoint(demo_seed):
    runner = a_built_runner()

    await a_seed_from(runner, demo_seed)

    assert len(runner.calls) == 1
    assert runner.options[0]["disposable"] is False
    assert runner.options[0]["tag"] == seed_tag("demo")
    assert runner.files_written[0] == {DIFF_PATH: demo_seed.pr.diff}


async def test_an_errored_build_operation_is_reported_with_its_error(demo_seed):
    runner = FakeSandboxRunner(
        handler=lambda c, s, f: RunResult("", "", None, None, error="OperationTimedOutError: x")
    )

    with pytest.raises(SeedBuildError, match="OperationTimedOutError"):
        await a_seed_from(runner, demo_seed)


async def test_a_failing_build_script_is_reported_with_its_stderr(demo_seed):
    runner = FakeSandboxRunner(
        handler=lambda c, s, f: RunResult("", "error: patch failed: pay.py:1", 1, None)
    )

    with pytest.raises(SeedBuildError, match="patch failed"):
        await a_seed_from(runner, demo_seed)


async def test_a_baseline_where_nothing_passes_every_run_is_refused(demo_seed):
    runner = a_built_runner(**{RUN_LOGS[1]: STABLE.replace("PASSED", "FAILED")})

    with pytest.raises(SeedBuildError, match="no test passed"):
        await a_seed_from(runner, demo_seed)


async def test_an_invalid_slug_is_refused_before_any_sandbox_op(demo_seed):
    runner = a_built_runner()

    with pytest.raises(ValueError, match="slug"):
        await build_seed(runner, demo_seed.pr, slug="Bad Slug!", image_ref="x")

    assert runner.calls == []


def test_the_script_applies_the_diff_and_runs_the_suite_three_times():
    script = build_script("/testbed", "python -m pytest")

    assert f"git apply --whitespace=nowarn {DIFF_PATH}" in script
    assert script.count("python -m pytest") == 3
    assert script.count("--cov-context=test") == 1
    for log in RUN_LOGS:
        assert log in script


def test_coverage_paths_are_made_relative_to_the_repository():
    assert relative_to_workdir("/testbed/pkg/a.py", "/testbed") == "pkg/a.py"
    assert relative_to_workdir("pkg/a.py", "/testbed") == "pkg/a.py"
    assert relative_to_workdir("\\testbed\\pkg\\a.py", "/testbed/") == "pkg/a.py"


def test_slugs_are_restricted_to_a_tag_safe_alphabet():
    assert is_valid_slug("nomenclature-284")
    assert not is_valid_slug("")
    assert not is_valid_slug("Upper")
    assert not is_valid_slug("has space")


def test_a_seed_record_survives_a_json_round_trip(demo_seed):
    assert SeedRecord.from_json(demo_seed.to_json()) == demo_seed
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_seed_build.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.seed.record'`.

- [ ] **Step 4: Write the record**

`src/chesterton/seed/record.py`:

```python
"""Everything a run needs from build time, in one serialisable record.

A seed is built once, ahead of the demo, and never on a judge's clock:
prebuilt image pulls alone measured 88-225 s (spec §15). The record carries
the tagged checkpoint to fork from, the coverage map, which tests are safe
to select, and the post-patch text of every changed source file. A run needs
nothing else, and needs no GitHub call.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from chesterton.models import CoverageMap, PullRequest

#: Lowercase letters, digits and hyphens: safe inside a checkpoint tag.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG.match(slug))


def seed_tag(slug: str) -> str:
    return f"chesterton:seed-{slug}"


@dataclass(frozen=True)
class SeedRecord:
    slug: str
    pr: PullRequest
    image_ref: str
    workdir: str
    test_command: str
    checkpoint_id: str
    checkpoint_tag: str
    coverage: CoverageMap
    selectable: frozenset[str]
    flaky: frozenset[str]
    failing: frozenset[str]
    sources: dict[str, str]
    built_at: str

    def to_json(self) -> str:
        payload = asdict(self)
        for name in ("selectable", "flaky", "failing"):
            payload[name] = sorted(payload[name])
        # JSON object keys are strings; line numbers are restored on load.
        payload["coverage"] = {
            file: {str(line): tests for line, tests in lines.items()}
            for file, lines in self.coverage.items()
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> SeedRecord:
        payload = json.loads(text)
        payload["pr"] = PullRequest(**payload["pr"])
        for name in ("selectable", "flaky", "failing"):
            payload[name] = frozenset(payload[name])
        payload["coverage"] = {
            file: {int(line): tests for line, tests in lines.items()}
            for file, lines in payload["coverage"].items()
        }
        return cls(**payload)
```

- [ ] **Step 5: Write the build**

`src/chesterton/seed/build.py`:

```python
"""Build a seed: the tagged baseline checkpoint every run forks from.

One persisted operation (ruling P3-4) applies the PR diff, installs
pytest-cov, and runs the suite three times. The first run is under coverage
contexts, single-threaded because contexts are unreliable under xdist
(spec §7). The results are read back as FILES (ruling P3-3): stdout is
truncated at 64 KiB, and a real coverage-contexts report is larger than that.

The three runs are what make a kill mean something. A test is selectable only
if it passed all three; flaky and always-failing tests would turn chance or
pre-existing failure into fabricated kills.
"""

from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone

from chesterton.covmap.invert import invert_coverage
from chesterton.diffing.parse import changed_lines
from chesterton.filters import is_mutable_source
from chesterton.models import PullRequest
from chesterton.paths import normalise_path
from chesterton.seed.outcomes import classify_runs, parse_outcomes
from chesterton.seed.record import SeedRecord, is_valid_slug, seed_tag

#: Where SWE-rebench images check the repository out (probe_images.py).
DEFAULT_WORKDIR = "/testbed"
DEFAULT_TEST_COMMAND = "python -m pytest"

#: Outside the repository, so nothing here can leak into a test run.
ARTIFACT_DIR = "/chesterton"
DIFF_PATH = f"{ARTIFACT_DIR}/pr.diff"
COVERAGE_PATH = f"{ARTIFACT_DIR}/coverage.json"
RUN_LOGS = (
    f"{ARTIFACT_DIR}/run1.txt",
    f"{ARTIFACT_DIR}/run2.txt",
    f"{ARTIFACT_DIR}/run3.txt",
)

#: Build time only. It is never on a judge's clock.
SEED_TIMEOUT_S = 1800.0

#: -rA prints one node-id line per test; the rest keeps runs deterministic
#: and leaves no cache behind in the checkpoint.
_PYTEST_FLAGS = "-q -rA -p no:randomly -p no:cacheprovider"


class SeedBuildError(RuntimeError):
    """The seed could not be built; the message says which stage failed."""


def build_script(workdir: str, test_command: str) -> str:
    q = shlex.quote
    return "\n".join(
        [
            "set -e",
            f"mkdir -p {ARTIFACT_DIR}",
            f"cd {q(workdir)}",
            f"git apply --whitespace=nowarn {DIFF_PATH}",
            "python -m pip install -q pytest-cov",
            # `|| true` on every test run: a failing test is data here, not a
            # build failure. classify_runs sorts the outcomes out.
            f"{test_command} {_PYTEST_FLAGS} --cov --cov-context=test "
            f"--cov-report= > {RUN_LOGS[0]} 2>&1 || true",
            f"python -m coverage json --show-contexts -o {COVERAGE_PATH}",
            f"{test_command} {_PYTEST_FLAGS} > {RUN_LOGS[1]} 2>&1 || true",
            f"{test_command} {_PYTEST_FLAGS} > {RUN_LOGS[2]} 2>&1 || true",
        ]
    )


def relative_to_workdir(path: str, workdir: str) -> str:
    prefix = normalise_path(workdir).rstrip("/") + "/"
    return normalise_path(path).removeprefix(prefix)


def _tail(text: str, lines: int = 20) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


async def build_seed(
    runner,
    pr: PullRequest,
    *,
    slug: str,
    image_ref: str,
    workdir: str = DEFAULT_WORKDIR,
    test_command: str = DEFAULT_TEST_COMMAND,
    timeout: float = SEED_TIMEOUT_S,
) -> SeedRecord:
    if not is_valid_slug(slug):
        raise ValueError(
            f"invalid slug {slug!r}: use lowercase letters, digits and hyphens"
        )

    base = await runner.use_image(image_ref)
    tag = seed_tag(slug)
    result = await runner.run(
        base,
        build_script(workdir, test_command),
        files={DIFF_PATH: pr.diff},
        disposable=False,
        tag=tag,
        timeout=timeout,
    )

    if result.error is not None:
        raise SeedBuildError(f"the seed build operation failed: {result.error}")
    if result.exit_code != 0:
        raise SeedBuildError(
            f"the seed build script exited {result.exit_code}: the diff did not "
            "apply, pytest-cov could not be installed, or coverage recorded no "
            "data.\n" + _tail(result.stderr or result.stdout)
        )
    checkpoint = result.checkpoint_id
    if checkpoint is None:
        raise SeedBuildError("the persisted build returned no checkpoint id")

    runs = [
        parse_outcomes((await runner.read_file(checkpoint, log)).decode("utf-8", "replace"))
        for log in RUN_LOGS
    ]
    selection = classify_runs(runs)
    if not selection.selectable:
        raise SeedBuildError(
            "no test passed in all three baseline runs, so nothing can be "
            "selected and every mutant would be uncovered"
        )

    report = json.loads((await runner.read_file(checkpoint, COVERAGE_PATH)).decode("utf-8"))
    coverage = {
        relative_to_workdir(path, workdir): lines
        for path, lines in invert_coverage(report).items()
    }

    sources: dict[str, str] = {}
    for file in sorted(changed_lines(pr.diff)):
        if is_mutable_source(file):
            raw = await runner.read_file(checkpoint, f"{workdir}/{file}")
            sources[file] = raw.decode("utf-8")

    return SeedRecord(
        slug=slug,
        pr=pr,
        image_ref=image_ref,
        workdir=workdir,
        test_command=test_command,
        checkpoint_id=checkpoint,
        checkpoint_tag=tag,
        coverage=coverage,
        selectable=selection.selectable,
        flaky=selection.flaky,
        failing=selection.failing,
        sources=sources,
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_seed_build.py -q`
Expected: PASS, 10 passed.

`from conftest import ...` works because pytest's default `prepend` import mode puts `tests/` on `sys.path`. If it fails to import, stop and report it rather than restructuring the fixtures.

Then run: `.venv/Scripts/python -m pytest -q`
Expected: the full suite is green.

- [ ] **Step 7: Commit**

```bash
git add src/chesterton/seed tests/conftest.py tests/test_seed_build.py
git commit -m "feat: build a tagged seed checkpoint with coverage and flake detection"
```

---

### Task 5: The sandbox pool — semaphore and op budget

**Files:**
- Create: `src/chesterton/execute/__init__.py` (empty)
- Create: `src/chesterton/execute/pool.py`
- Test: `tests/test_execute_pool.py`

**Interfaces:**
- Consumes: `SandboxRunner`, `RunResult`.
- Produces: `CONCURRENCY = 24`; `RUN_OP_BUDGET = 160`; `BudgetExhausted(RuntimeError)`; `SandboxPool(runner, *, concurrency=CONCURRENCY, op_budget=RUN_OP_BUDGET)` with `async run(checkpoint_id, shell, *, files=None, timeout=None) -> RunResult`, `.ops_used: int`, `.op_budget: int`, and the property `.remaining: int`.

- [ ] **Step 1: Write the failing test**

`tests/test_execute_pool.py`:

```python
import asyncio

import pytest

from chesterton.execute.pool import (
    CONCURRENCY,
    RUN_OP_BUDGET,
    BudgetExhausted,
    SandboxPool,
)
from chesterton.mutation.generate import MUTANT_BUDGET
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult


class _SlowRunner:
    """Holds each op open briefly so overlapping ops can be counted."""

    def __init__(self):
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    async def run(self, checkpoint_id, shell, *, files=None, disposable=True,
                  tag=None, timeout=None):
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return RunResult("", "", 0, None)


async def test_concurrency_reaches_but_never_exceeds_the_cap():
    # == rather than <=: the test must also prove ops really run side by side.
    runner = _SlowRunner()
    pool = SandboxPool(runner, concurrency=24, op_budget=100)

    await asyncio.gather(*(pool.run("ckpt", "pytest") for _ in range(60)))

    assert runner.peak == 24


async def test_the_budget_refuses_ops_beyond_it_without_calling_the_runner():
    runner = _SlowRunner()
    pool = SandboxPool(runner, op_budget=3)

    outcomes = await asyncio.gather(
        *(pool.run("ckpt", "pytest") for _ in range(5)), return_exceptions=True
    )

    assert sum(isinstance(o, BudgetExhausted) for o in outcomes) == 2
    assert runner.calls == 3
    assert pool.ops_used == 3
    assert pool.remaining == 0


async def test_every_pool_op_is_disposable():
    # Run time never persists anything, so it never needs a tag.
    runner = FakeSandboxRunner()
    pool = SandboxPool(runner)

    await pool.run("ckpt", "pytest", files={"/testbed/a.py": "x = 1\n"}, timeout=5)

    assert runner.options == [{"disposable": True, "tag": None, "timeout": 5}]


def test_the_defaults_match_the_measured_cap_and_cover_a_full_mutant_budget():
    assert CONCURRENCY == 24
    assert RUN_OP_BUDGET >= MUTANT_BUDGET


def test_nonsense_limits_are_refused():
    with pytest.raises(ValueError):
        SandboxPool(FakeSandboxRunner(), concurrency=0)
    with pytest.raises(ValueError):
        SandboxPool(FakeSandboxRunner(), op_budget=-1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_execute_pool.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.execute'`.

- [ ] **Step 3: Write the pool**

`src/chesterton/execute/pool.py`:

```python
"""Every run-time sandbox operation goes through one pool.

It enforces two limits, for different reasons.

Concurrency, via asyncio.Semaphore(24). 24 simultaneous operations was
measured safe: 72/72 across three rounds, 4.7 s worst case with real pytest
(spec §15). Above that the fan-out leaves measured territory, and the beta's
op cap comes into play.

A per-run op budget. The spec's failure-mode table says to refuse to start
rather than overspend. Mutant fan-out and ddmin probes share one budget
because they share one quota.

Run time only ever forks and throws away, so every op here is disposable and
none needs a tag. The build-time seed build is the one caller that persists,
and it calls the runner directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from chesterton.sandbox.protocol import RunResult

#: Measured safe (spec §15). This is the Global Constraint, not a tunable.
CONCURRENCY = 24

#: 32 mutant ops (MUTANT_BUDGET) plus about n² = 121 ddmin probes for the
#: spec's own 11-hunk example (§8), rounded up.
RUN_OP_BUDGET = 160


class BudgetExhausted(RuntimeError):
    """The run's op budget is spent; this op was not issued."""


class SandboxPool:
    def __init__(
        self,
        runner,
        *,
        concurrency: int = CONCURRENCY,
        op_budget: int = RUN_OP_BUDGET,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if op_budget < 0:
            raise ValueError("op_budget cannot be negative")
        self.runner = runner
        self.op_budget = op_budget
        self.ops_used = 0
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def remaining(self) -> int:
        return self.op_budget - self.ops_used

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str | bytes] | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        # Charged BEFORE waiting on the semaphore, with no await between the
        # check and the charge, so concurrent callers cannot all pass the
        # check and overspend together.
        if self.remaining <= 0:
            raise BudgetExhausted(
                f"the run's budget of {self.op_budget} sandbox ops is spent"
            )
        self.ops_used += 1
        async with self._semaphore:
            return await self.runner.run(
                checkpoint_id, shell, files=files, disposable=True, timeout=timeout
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_execute_pool.py -q`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/execute tests/test_execute_pool.py
git commit -m "feat: bound run-time sandbox ops with a semaphore and an op budget"
```

---

### Task 6: Execute mutants and classify verdicts honestly

**Files:**
- Create: `src/chesterton/execute/mutants.py`
- Test: `tests/test_execute_mutants.py`

**Interfaces:**
- Consumes: `SandboxPool`, `BudgetExhausted` (Task 5); `SeedRecord` (Task 4); `Mutant` from `chesterton.mutation.model`; `Hunk` from `chesterton.models`; `covering_tests` from `chesterton.defended`; `RunResult`.
- Produces: `Verdict = Literal["killed", "survived", "uncovered", "error"]`; `MUTANT_TIMEOUT_S = 120.0`; `MutantResult(mutant, verdict, tests: tuple[str, ...], duration_s: float | None = None, detail: str | None = None, stdout_tail: str = "")`; `select_tests(mutant, seed) -> tuple[str, ...]`; `classify(result: RunResult) -> tuple[Verdict, str | None]`; `async execute_mutants(pool, seed, mutants) -> list[MutantResult]`; `VerdictCounts(killed, survived, uncovered, error)` with the property `score -> float | None`; `count_verdicts(results) -> VerdictCounts`.

- [ ] **Step 1: Write the failing test**

`tests/test_execute_mutants.py`:

```python
from chesterton.execute.mutants import (
    MutantResult,
    classify,
    count_verdicts,
    execute_mutants,
    select_tests,
)
from chesterton.execute.pool import SandboxPool
from chesterton.mutation.model import Mutant
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import HEAD_PAY, T_CHARGE, T_FLAKY


def a_mutant(start: int = 2, end: int = 3, mutated: str = "def charge(amount):\n    return amount\n") -> Mutant:
    return Mutant(
        file="pay.py", start_line=start, end_line=end, operator="delete_guard",
        original_src=HEAD_PAY, mutated_src=mutated, rationale="r",
        source="deterministic",
    )


def exits(code):
    return FakeSandboxRunner(handler=lambda c, s, f: RunResult("out", "", code, None))


def test_only_exit_1_is_a_kill():
    assert classify(RunResult("", "", 1, None)) == ("killed", None)
    assert classify(RunResult("", "", 0, None)) == ("survived", None)


def test_other_exit_codes_are_errors_that_name_the_code():
    for code in (2, 3, 4, 5):
        verdict, detail = classify(RunResult("", "", code, None))
        assert verdict == "error"
        assert f"exited {code}" in detail


def test_a_sandbox_error_is_an_error_before_exit_code_is_read():
    verdict, detail = classify(RunResult("", "", None, None, error="TimedOut"))
    assert (verdict, detail) == ("error", "TimedOut")


def test_selection_keeps_only_selectable_covering_tests(demo_seed):
    # Lines 2-3: line 2 is covered by T_CHARGE, line 3 only by T_FLAKY.
    assert select_tests(a_mutant(), demo_seed) == (T_CHARGE,)


async def test_a_mutant_the_tests_fail_on_is_killed(demo_seed):
    [result] = await execute_mutants(SandboxPool(exits(1)), demo_seed, [a_mutant()])
    assert result.verdict == "killed"
    assert result.tests == (T_CHARGE,)


async def test_a_mutant_no_selected_test_fails_on_survives(demo_seed):
    [result] = await execute_mutants(SandboxPool(exits(0)), demo_seed, [a_mutant()])
    assert result.verdict == "survived"


async def test_the_mutant_is_written_into_the_repo_and_only_selected_tests_run(demo_seed):
    runner = exits(1)
    mutant = a_mutant()

    await execute_mutants(SandboxPool(runner), demo_seed, [mutant])

    [(checkpoint, shell)] = runner.calls
    assert checkpoint == demo_seed.checkpoint_id
    assert runner.files_written == [{"/testbed/pay.py": mutant.mutated_src}]
    assert T_CHARGE in shell
    assert T_FLAKY not in shell


async def test_a_mutant_covered_only_by_flaky_tests_is_uncovered_and_costs_nothing(demo_seed):
    runner = exits(1)
    pool = SandboxPool(runner)

    [result] = await execute_mutants(pool, demo_seed, [a_mutant(start=3, end=3)])

    assert result.verdict == "uncovered"
    assert result.detail
    assert runner.calls == []
    assert pool.ops_used == 0


async def test_a_spent_budget_is_an_error_never_a_kill(demo_seed):
    [result] = await execute_mutants(
        SandboxPool(exits(1), op_budget=0), demo_seed, [a_mutant()]
    )
    assert result.verdict == "error"
    assert "budget" in result.detail


def a_result(verdict):
    return MutantResult(a_mutant(), verdict, ())


def test_the_score_excludes_errors_and_uncovered_mutants():
    results = [
        a_result("killed"), a_result("killed"), a_result("survived"),
        a_result("error"), a_result("uncovered"),
    ]

    counts = count_verdicts(results)

    assert (counts.killed, counts.survived, counts.error, counts.uncovered) == (2, 1, 1, 1)
    assert counts.score == 2 / 3


def test_there_is_no_score_when_nothing_ran():
    assert count_verdicts([]).score is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_execute_mutants.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.execute.mutants'`.

- [ ] **Step 3: Write the module**

`src/chesterton/execute/mutants.py`:

```python
"""Run each mutant against the tests that execute its hunk, and say honestly
what happened.

The verdict rules are the spec's, and they are where fabricated evidence
would enter:

- only pytest exit code 1 (TESTS_FAILED) is a kill;
- exit 0 means survived: no selected test failed;
- every other exit code is an error. That covers 2 (interrupted, including a
  collection error), 3 (internal), 4 (usage) and 5 (no tests collected). A
  mutant that stops a module importing makes tests error, and the spec
  counts that reading-as-killed as a silent false negative;
- a sandbox operation that failed is an error, and it is checked before
  exit_code is read, which is None exactly then.

Errors and uncovered mutants are excluded from the score. A mutant with no
selectable covering test is `uncovered` and costs no sandbox op.
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from chesterton.defended import covering_tests
from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.models import Hunk
from chesterton.mutation.model import Mutant
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.record import SeedRecord

Verdict = Literal["killed", "survived", "uncovered", "error"]

#: Coverage-selected tests are few; this bounds a mutant that hangs them.
MUTANT_TIMEOUT_S = 120.0

#: pytest.ExitCode, spelled out so an error names what happened.
_PYTEST_EXIT = {
    2: "INTERRUPTED",
    3: "INTERNAL_ERROR",
    4: "USAGE_ERROR",
    5: "NO_TESTS_COLLECTED",
}


@dataclass(frozen=True)
class MutantResult:
    mutant: Mutant
    verdict: Verdict
    tests: tuple[str, ...]
    duration_s: float | None = None
    detail: str | None = None
    stdout_tail: str = ""


def select_tests(mutant: Mutant, seed: SeedRecord) -> tuple[str, ...]:
    hunk = Hunk(mutant.file, mutant.start_line, mutant.end_line)
    return tuple(
        test for test in covering_tests(hunk, seed.coverage) if test in seed.selectable
    )


def classify(result: RunResult) -> tuple[Verdict, str | None]:
    if result.error is not None:
        return "error", result.error
    if result.exit_code == 1:
        return "killed", None
    if result.exit_code == 0:
        return "survived", None
    name = _PYTEST_EXIT.get(result.exit_code, "UNKNOWN")
    return "error", (
        f"pytest exited {result.exit_code} ({name}); that is not a test "
        "failure, so it is not a kill"
    )


def _tail(text: str, lines: int = 15) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def _command(seed: SeedRecord, tests: Sequence[str]) -> str:
    return (
        f"cd {shlex.quote(seed.workdir)} && {seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {shlex.join(tests)}"
    )


async def _execute(pool: SandboxPool, seed: SeedRecord, mutant: Mutant) -> MutantResult:
    tests = select_tests(mutant, seed)
    if not tests:
        return MutantResult(
            mutant, "uncovered", (), detail="no selectable test executes this hunk"
        )
    try:
        result = await pool.run(
            seed.checkpoint_id,
            _command(seed, tests),
            files={f"{seed.workdir}/{mutant.file}": mutant.mutated_src},
            timeout=MUTANT_TIMEOUT_S,
        )
    except BudgetExhausted as exc:
        return MutantResult(mutant, "error", tests, detail=str(exc))

    verdict, detail = classify(result)
    return MutantResult(
        mutant, verdict, tests, result.duration_s, detail, _tail(result.stdout)
    )


async def execute_mutants(
    pool: SandboxPool, seed: SeedRecord, mutants: Sequence[Mutant]
) -> list[MutantResult]:
    return list(await asyncio.gather(*(_execute(pool, seed, m) for m in mutants)))


@dataclass(frozen=True)
class VerdictCounts:
    killed: int
    survived: int
    uncovered: int
    error: int

    @property
    def score(self) -> float | None:
        ran = self.killed + self.survived
        return self.killed / ran if ran else None


def count_verdicts(results: Sequence[MutantResult]) -> VerdictCounts:
    tally = {"killed": 0, "survived": 0, "uncovered": 0, "error": 0}
    for result in results:
        tally[result.verdict] += 1
    return VerdictCounts(**tally)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_execute_mutants.py -q`
Expected: PASS, 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/execute/mutants.py tests/test_execute_mutants.py
git commit -m "feat: execute mutants with coverage-selected tests and honest verdicts"
```

---

### Task 7: ddmin — concurrent, cached and budget-aware

**Files:**
- Create: `src/chesterton/reduce/__init__.py` (empty)
- Create: `src/chesterton/reduce/ddmin.py`
- Test: `tests/test_reduce_ddmin.py`

**Interfaces:**
- Consumes: `BudgetExhausted` (Task 5).
- Produces: `Outcome` (an Enum with `HOLDS`, `FAILS`, `UNRESOLVED`); `DdminResult(minimal: frozenset, probes: int, exhausted: bool)`; `async ddmin(elements: Sequence[T], probe: Callable[[frozenset[T]], Awaitable[Outcome]], *, check_empty: bool = True) -> DdminResult`.

This is spec §13 priority 4: "against a synthetic hunk set with a known minimal subset. Pure function over a predicate; no sandbox needed."

- [ ] **Step 1: Write the failing test**

`tests/test_reduce_ddmin.py`:

```python
import asyncio

from chesterton.execute.pool import BudgetExhausted
from chesterton.reduce.ddmin import Outcome, ddmin


def needs(required, *, unresolved_if=frozenset(), log=None, delay=0.0, stats=None):
    """A monotone predicate: holds iff every element of `required` is kept."""

    async def probe(subset):
        if log is not None:
            log.append(subset)
        if stats is not None:
            stats["now"] += 1
            stats["peak"] = max(stats["peak"], stats["now"])
        await asyncio.sleep(delay)
        if stats is not None:
            stats["now"] -= 1
        if subset & unresolved_if:
            return Outcome.UNRESOLVED
        return Outcome.HOLDS if required <= subset else Outcome.FAILS

    return probe


async def test_a_known_minimal_subset_is_found():
    result = await ddmin(range(10), needs({2, 5}))

    assert result.minimal == {2, 5}
    assert result.exhausted is False


async def test_a_single_needed_element_is_found():
    assert (await ddmin(range(8), needs({6}))).minimal == {6}


async def test_when_everything_is_needed_everything_is_returned():
    assert (await ddmin(range(5), needs(set(range(5))))).minimal == set(range(5))


async def test_when_nothing_is_needed_one_probe_says_so():
    # Ruling P3-1: the whole PR reverted and the suite still passes means
    # the entire PR is undefended, at the cost of exactly one probe.
    result = await ddmin(range(10), needs(set()))

    assert result.minimal == frozenset()
    assert result.probes == 1


async def test_an_unresolved_probe_never_counts_as_holding():
    # Any subset containing 2 errors, and 2 sorts BEFORE the needed 7, so at
    # every split the first candidate in order is an unresolved one. If
    # UNRESOLVED counted as holding, ddmin would take it and end on {2}.
    # (With the order reversed this test passed even with that bug.)
    result = await ddmin(range(10), needs({7}, unresolved_if=frozenset({2})))

    assert result.minimal == {7}


async def test_no_subset_is_probed_twice():
    log = []
    await ddmin(range(12), needs({3, 9}, log=log))

    assert len(log) == len(set(log))


async def test_probes_at_one_granularity_run_concurrently():
    stats = {"now": 0, "peak": 0}
    await ddmin(range(8), needs({1, 6}, delay=0.01, stats=stats))

    assert stats["peak"] > 1


async def test_a_spent_budget_returns_a_sound_upper_bound_marked_exhausted():
    calls = {"n": 0}
    inner = needs({2, 5})

    async def budgeted(subset):
        calls["n"] += 1
        if calls["n"] > 3:
            raise BudgetExhausted("spent")
        return await inner(subset)

    result = await ddmin(range(10), budgeted)

    assert result.exhausted is True
    # Cut short, the set in hand still holds: it contains all that is needed.
    assert {2, 5} <= result.minimal


async def test_the_result_is_deterministic():
    first = await ddmin(range(16), needs({0, 7, 15}))
    second = await ddmin(range(16), needs({0, 7, 15}))

    assert first == second


async def test_no_elements_means_no_probes():
    result = await ddmin([], needs(set()))

    assert result.minimal == frozenset()
    assert result.probes == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reduce_ddmin.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.reduce'`.

- [ ] **Step 3: Write ddmin**

`src/chesterton/reduce/ddmin.py`:

```python
"""Delta debugging over a set, with sandbox forks as the oracle (spec §8).

This is Zeller's ddmin, reading "the property holds" where the textbook
reads "the test fails". It returns a 1-minimal subset that still holds:
removing any single element makes it stop holding.

There are two departures from the textbook, both for the platform:

- Every candidate at one granularity is probed CONCURRENTLY (ruling P3-7).
  Forks are cheap and independent, and wall clock is what a live demo
  spends. The choice among candidates is still the first in a fixed order,
  so the result is the one sequential ddmin would reach, at the price of
  extra probes.
- Probes are cached by subset. ddmin revisits subsets, and every probe is a
  sandbox op against a finite budget.

UNRESOLVED (the probe errored, or pytest exited with something other than a
pass or a fail) counts as "does not hold". That preserves the invariant that
the current set always holds, and the invariant is what makes a search cut
short by the budget still sound (ruling P3-8). The set in hand is an upper
bound on what is needed. The result says it was cut short rather than
claiming to be minimal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from chesterton.execute.pool import BudgetExhausted

T = TypeVar("T")


class Outcome(Enum):
    HOLDS = "holds"
    FAILS = "fails"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class DdminResult(Generic[T]):
    minimal: frozenset[T]
    probes: int
    exhausted: bool


def _split(items: list[T], n: int) -> list[list[T]]:
    size, extra = divmod(len(items), n)
    chunks, start = [], 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        chunks.append(items[start:end])
        start = end
    return [chunk for chunk in chunks if chunk]


async def ddmin(
    elements: Sequence[T],
    probe: Callable[[frozenset[T]], Awaitable[Outcome]],
    *,
    check_empty: bool = True,
) -> DdminResult[T]:
    cache: dict[frozenset[T], Outcome] = {}
    exhausted = False

    async def holding(candidates: list[frozenset[T]]) -> list[bool]:
        nonlocal exhausted
        todo = [c for c in dict.fromkeys(candidates) if c not in cache]
        outcomes = await asyncio.gather(
            *(probe(c) for c in todo), return_exceptions=True
        )
        for candidate, outcome in zip(todo, outcomes):
            if isinstance(outcome, BudgetExhausted):
                exhausted = True
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                cache[candidate] = outcome
        return [cache.get(c) is Outcome.HOLDS for c in candidates]

    current = list(elements)

    if check_empty and current:
        [empty_holds] = await holding([frozenset()])
        if empty_holds:
            return DdminResult(frozenset(), len(cache), exhausted)
        if exhausted:
            return DdminResult(frozenset(current), len(cache), True)

    n = 2
    while len(current) >= 2:
        subsets = [frozenset(chunk) for chunk in _split(current, n)]

        results = await holding(subsets)
        if exhausted:
            break
        hit = next((i for i, ok in enumerate(results) if ok), None)
        if hit is not None:
            current = [e for e in current if e in subsets[hit]]
            n = 2
            continue

        complements = [frozenset(e for e in current if e not in s) for s in subsets]
        results = await holding(complements)
        if exhausted:
            break
        hit = next((i for i, ok in enumerate(results) if ok), None)
        if hit is not None:
            current = [e for e in current if e in complements[hit]]
            n = max(n - 1, 2)
            continue

        if n >= len(current):
            break
        n = min(2 * n, len(current))

    return DdminResult(frozenset(current), len(cache), exhausted)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_reduce_ddmin.py -q`
Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/reduce tests/test_reduce_ddmin.py
git commit -m "feat: add concurrent, cached, budget-aware ddmin"
```

---

### Task 8: PR hunks and exact revert

**Files:**
- Create: `src/chesterton/reduce/patch.py`
- Test: `tests/test_reduce_patch.py`

**Interfaces:**
- Consumes: `is_mutable_source`, `normalise_path`.
- Produces: `PatchHunk(file: str, index: int, target_start: int, target_length: int, source_lines: tuple[str, ...])` with the property `label -> str` (`"file#index"`); `patch_hunks(diff: str) -> tuple[list[PatchHunk], dict[str, int]]`; `revert(head_text: str, hunks: Iterable[PatchHunk]) -> str`; `probe_files(sources: Mapping[str, str], workdir: str, hunks: Sequence[PatchHunk], keep: frozenset[PatchHunk]) -> dict[str, str]`.

The unidiff facts this code relies on were measured on 2026-09-19 with unidiff in this venv. Keep them in mind while reading the tests:

- A zero-length target, `@@ -3 +2,0 @@`, reports `target_start=2, target_length=0`. The deletion sits **after** line 2, so it is re-inserted at index 2, not 1.
- An added file reports `source 0,0` and `target 1,n`, so its revert is the empty string.
- `\ No newline at end of file` arrives as its own line of type `'\\'`. The line before it still carries a `\n` in `.value`, so when the marker follows a context or removed line, that source line's `\n` must be stripped.

- [ ] **Step 1: Write the failing test**

`tests/test_reduce_patch.py`:

```python
from chesterton.reduce.patch import patch_hunks, probe_files, revert

BASE = "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"
HEAD = "a = 1\nc = 3\nd = 4\ne = 50"

DIFF = (
    "--- a/m.py\n"
    "+++ b/m.py\n"
    "@@ -1,2 +1,1 @@\n"
    " a = 1\n"
    "-b = 2\n"
    "@@ -5 +4 @@\n"
    "-e = 5\n"
    "+e = 50\n"
    "\\ No newline at end of file\n"
    "--- /dev/null\n"
    "+++ b/new.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+x = 1\n"
    "+y = 2\n"
    "--- a/gone.py\n"
    "+++ b/gone.py\n"
    "@@ -1,2 +0,0 @@\n"
    "-p = 1\n"
    "-q = 2\n"
    "--- a/tests/test_m.py\n"
    "+++ b/tests/test_m.py\n"
    "@@ -1 +1 @@\n"
    "-assert True\n"
    "+assert 1\n"
    "--- a/README.md\n"
    "+++ b/README.md\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


def test_only_source_hunks_are_kept_and_the_rest_are_counted():
    hunks, skipped = patch_hunks(DIFF)

    assert [h.label for h in hunks] == ["m.py#0", "m.py#1", "new.py#0"]
    assert skipped == {"removed_file": 1, "not_mutable_source": 2}


def test_reverting_every_hunk_of_a_file_restores_the_base_exactly():
    hunks, _ = patch_hunks(DIFF)
    m_hunks = [h for h in hunks if h.file == "m.py"]

    assert revert(HEAD, m_hunks) == BASE


def test_reverting_one_hunk_leaves_the_other_applied():
    hunks, _ = patch_hunks(DIFF)
    first = next(h for h in hunks if h.label == "m.py#0")

    assert revert(HEAD, [first]) == "a = 1\nb = 2\nc = 3\nd = 4\ne = 50"


def test_a_pure_deletion_is_reinserted_after_its_anchor_line():
    # @@ -3 +2,0 @@ : the deletion sits AFTER head line 2.
    diff = "--- a/m.py\n+++ b/m.py\n@@ -3 +2,0 @@\n-c = 3\n"
    [hunk], _ = patch_hunks(diff)

    assert revert("a = 1\nb = 2\nd = 4\n", [hunk]) == "a = 1\nb = 2\nc = 3\nd = 4\n"


def test_reverting_an_added_file_empties_it():
    hunks, _ = patch_hunks(DIFF)
    added = next(h for h in hunks if h.file == "new.py")

    assert revert("x = 1\ny = 2\n", [added]) == ""


def test_a_base_line_without_a_trailing_newline_is_restored_without_one():
    # The marker follows the REMOVED line, so the base had no final newline.
    diff = (
        "--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n"
        "-x = 1\n\\ No newline at end of file\n+x = 2\n"
    )
    [hunk], _ = patch_hunks(diff)

    assert revert("x = 2\n", [hunk]) == "x = 1"


def test_probe_files_writes_only_files_with_a_reverted_hunk():
    hunks, _ = patch_hunks(DIFF)
    sources = {"m.py": HEAD, "new.py": "x = 1\ny = 2\n"}
    keep = frozenset(h for h in hunks if h.file == "new.py")

    files = probe_files(sources, "/testbed", hunks, keep)

    assert files == {"/testbed/m.py": BASE}


def test_keeping_every_hunk_writes_nothing():
    hunks, _ = patch_hunks(DIFF)
    sources = {"m.py": HEAD, "new.py": "x = 1\ny = 2\n"}

    assert probe_files(sources, "/testbed", hunks, frozenset(hunks)) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reduce_patch.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.reduce.patch'`.

- [ ] **Step 3: Write the module**

`src/chesterton/reduce/patch.py`:

```python
"""The PR's hunks as units ddmin can keep or revert.

A ddmin probe applies a subset of the PR by reverting every other source
hunk to its pre-patch text. Reverting is exact splicing on the HEAD text,
bottom-up so earlier edits cannot shift later line numbers. Every
coordinate comes from unidiff, whose conventions were measured rather than
assumed:

- A zero-length target (`@@ -3 +2,0 @@`) reports target_start=2, and the
  deletion sits AFTER that line, so it is re-inserted at index 2, not 1.
- An added file reports target 1,n with no source lines; reverting it
  empties the file.
- `\\ No newline at end of file` arrives as its own line after the line it
  qualifies, and that line's .value still ends in "\\n". Following a context
  or removed line, it means the BASE had no final newline, so the newline
  is stripped from the recorded source text.

Only mutable source files take part. Test files are the oracle, so reverting
them would be circular. Removed and binary files have no head text to
splice into.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from unidiff import PatchSet

from chesterton.filters import is_mutable_source
from chesterton.paths import normalise_path

_NO_NEWLINE = "\\"


@dataclass(frozen=True)
class PatchHunk:
    file: str
    index: int
    target_start: int
    target_length: int
    #: The pre-patch text of this hunk's span, one entry per line, with ends.
    source_lines: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.file}#{self.index}"


def _source_lines(hunk) -> tuple[str, ...]:
    lines: list[str] = []
    previous = None
    for line in hunk:
        if line.line_type == _NO_NEWLINE:
            if previous is not None and (previous.is_context or previous.is_removed) and lines:
                lines[-1] = lines[-1].removesuffix("\n")
        elif line.is_context or line.is_removed:
            lines.append(line.value)
        previous = line
    return tuple(lines)


def patch_hunks(diff: str) -> tuple[list[PatchHunk], dict[str, int]]:
    hunks: list[PatchHunk] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for patched in PatchSet(diff):
        path = normalise_path(patched.path)
        if patched.is_binary_file:
            skip("binary")
            continue
        if patched.is_removed_file:
            skip("removed_file")
            continue
        if not is_mutable_source(path):
            skip("not_mutable_source")
            continue
        for index, hunk in enumerate(patched):
            hunks.append(
                PatchHunk(
                    file=path,
                    index=index,
                    target_start=hunk.target_start,
                    target_length=hunk.target_length,
                    source_lines=_source_lines(hunk),
                )
            )
    return hunks, skipped


def revert(head_text: str, hunks: Iterable[PatchHunk]) -> str:
    lines = head_text.splitlines(keepends=True)
    for hunk in sorted(hunks, key=lambda h: h.target_start, reverse=True):
        start = hunk.target_start if hunk.target_length == 0 else hunk.target_start - 1
        lines[start : start + hunk.target_length] = list(hunk.source_lines)
    return "".join(lines)


def probe_files(
    sources: Mapping[str, str],
    workdir: str,
    hunks: Sequence[PatchHunk],
    keep: frozenset[PatchHunk],
) -> dict[str, str]:
    """The files a probe must write so that only `keep` stays applied.

    A file whose hunks are all kept is not written: the checkpoint already
    holds its head text.
    """
    reverted: dict[str, list[PatchHunk]] = defaultdict(list)
    for hunk in hunks:
        if hunk not in keep:
            reverted[hunk.file].append(hunk)
    return {
        f"{workdir.rstrip('/')}/{file}": revert(sources[file], file_hunks)
        for file, file_hunks in reverted.items()
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_reduce_patch.py -q`
Expected: PASS, 8 passed.

If `test_a_base_line_without_a_trailing_newline_is_restored_without_one` fails, print `[(l.line_type, l.value) for l in hunk]` for that diff and report what unidiff produced. Do not change the expected value.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/reduce/patch.py tests/test_reduce_patch.py
git commit -m "feat: split a PR into revertable source hunks"
```

---

### Task 9: The undefended surface — ddmin over hunks with sandbox probes

**Files:**
- Create: `src/chesterton/reduce/surface.py`
- Test: `tests/test_reduce_surface.py`

**Interfaces:**
- Consumes: `ddmin`, `Outcome` (Task 7); `patch_hunks`, `probe_files` (Task 8); `SandboxPool` (Task 5); `SeedRecord` (Task 4); `RunResult`.
- Produces: `SUITE_TIMEOUT_S = 300.0`; `SurfaceResult(hunks: tuple[str, ...], needed: tuple[str, ...], undefended: tuple[str, ...], probes: int, exhausted: bool, skipped: dict[str, int], note: str | None = None)`; `suite_command(seed) -> str`; `async undefended_surface(pool, seed) -> SurfaceResult`.

- [ ] **Step 1: Write the failing test**

`tests/test_reduce_surface.py`:

```python
from dataclasses import replace

from chesterton.execute.pool import SandboxPool
from chesterton.reduce.surface import suite_command, undefended_surface
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import T_FLAKY

HEAD_ONE = "a = 10\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6\ng = 7\nh = 8\ni = 90\n"
HEAD_TWO = "x = 10\ny = 2\nz = 30\n"

# Zero-context hunks: two per file, far enough apart to stay separate.
DIFF = (
    "--- a/one.py\n+++ b/one.py\n"
    "@@ -1 +1 @@\n-a = 1\n+a = 10\n"
    "@@ -9 +9 @@\n-i = 9\n+i = 90\n"
    "--- a/two.py\n+++ b/two.py\n"
    "@@ -1 +1 @@\n-x = 1\n+x = 10\n"
    "@@ -3 +3 @@\n-z = 3\n+z = 30\n"
    "--- a/README.md\n+++ b/README.md\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)


def a_multi_hunk_seed(demo_seed):
    return replace(
        demo_seed,
        pr=replace(demo_seed.pr, diff=DIFF),
        sources={"one.py": HEAD_ONE, "two.py": HEAD_TWO},
    )


def suite_needs_a_and_z(checkpoint, shell, files):
    """The suite passes only while `a = 10` and `z = 30` are both applied."""
    one = files.get("/testbed/one.py", HEAD_ONE)
    two = files.get("/testbed/two.py", HEAD_TWO)
    ok = "a = 10\n" in one and "z = 30\n" in two
    return RunResult("", "", 0 if ok else 1, None)


async def test_the_hunks_the_tests_do_not_need_are_the_undefended_surface(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=suite_needs_a_and_z)

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.hunks == ("one.py#0", "one.py#1", "two.py#0", "two.py#1")
    assert result.needed == ("one.py#0", "two.py#1")
    assert result.undefended == ("one.py#1", "two.py#0")
    assert result.exhausted is False
    assert result.skipped == {"not_mutable_source": 1}


async def test_every_probe_forks_the_seed_and_persists_nothing(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=suite_needs_a_and_z)

    result = await undefended_surface(SandboxPool(runner), seed)

    assert len(runner.calls) == result.probes
    assert {checkpoint for checkpoint, _ in runner.calls} == {seed.checkpoint_id}
    assert all(option["disposable"] for option in runner.options)


async def test_when_the_suite_needs_nothing_the_whole_pr_is_undefended(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=lambda c, s, f: RunResult("", "", 0, None))

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.needed == ()
    assert len(result.undefended) == 4
    assert result.probes == 1


async def test_probes_that_error_prove_nothing_undefended(demo_seed):
    # UNRESOLVED never counts as holding, so nothing is claimed undefended.
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(
        handler=lambda c, s, f: RunResult("", "", None, None, error="TimedOut")
    )

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.undefended == ()
    assert result.needed == result.hunks


async def test_a_spent_budget_claims_no_more_than_is_proven(demo_seed):
    seed = a_multi_hunk_seed(demo_seed)
    runner = FakeSandboxRunner(handler=suite_needs_a_and_z)

    result = await undefended_surface(SandboxPool(runner, op_budget=2), seed)

    assert result.exhausted is True
    assert set(result.undefended) <= {"one.py#1", "two.py#0"}


async def test_a_pr_with_no_source_hunks_costs_nothing(demo_seed):
    seed = replace(
        demo_seed,
        pr=replace(demo_seed.pr, diff="--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-a\n+b\n"),
        sources={},
    )
    runner = FakeSandboxRunner()

    result = await undefended_surface(SandboxPool(runner), seed)

    assert result.hunks == ()
    assert result.note
    assert runner.calls == []


def test_the_suite_command_deselects_every_unselectable_test(demo_seed):
    command = suite_command(demo_seed)

    assert f"--deselect {T_FLAKY}" in command
    assert command.startswith("cd /testbed && python -m pytest")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reduce_surface.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.reduce.surface'`.

- [ ] **Step 3: Write the module**

`src/chesterton/reduce/surface.py`:

```python
"""The minimal set of hunks the tests need, and so the undefended rest.

Ruling P3-1: a probe applies only a subset S of the PR's source hunks,
reverting the others to their pre-patch text, and runs the selectable
suite. The property is "the suite passes". ddmin finds a 1-minimal S for
which it holds: the hunks the tests NEED. Every other hunk is undefended,
a change the suite would not notice if it were undone.

"Of 11 hunks, these 2 are the entire undefended surface" (spec §8).

The suite is the whole suite minus flaky and always-failing tests, which
are deselected by node id. The full PR holds by construction, since every
selectable test passed at head three times, so the search starts there.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from chesterton.execute.pool import SandboxPool
from chesterton.reduce.ddmin import Outcome, ddmin
from chesterton.reduce.patch import patch_hunks, probe_files
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.record import SeedRecord

#: A probe runs the whole selectable suite, not a coverage selection.
SUITE_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class SurfaceResult:
    hunks: tuple[str, ...]
    needed: tuple[str, ...]
    undefended: tuple[str, ...]
    probes: int
    exhausted: bool
    skipped: dict[str, int]
    note: str | None = None


def suite_command(seed: SeedRecord) -> str:
    deselect = " ".join(
        f"--deselect {shlex.quote(test)}" for test in sorted(seed.flaky | seed.failing)
    )
    return (
        f"cd {shlex.quote(seed.workdir)} && {seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {deselect}"
    ).rstrip()


def _outcome(result: RunResult) -> Outcome:
    if result.error is not None:
        return Outcome.UNRESOLVED
    if result.exit_code == 0:
        return Outcome.HOLDS
    if result.exit_code == 1:
        return Outcome.FAILS
    return Outcome.UNRESOLVED


async def undefended_surface(pool: SandboxPool, seed: SeedRecord) -> SurfaceResult:
    hunks, skipped = patch_hunks(seed.pr.diff)
    labels = tuple(hunk.label for hunk in hunks)
    if not hunks:
        return SurfaceResult(
            labels, (), (), 0, False, skipped, note="no source hunks to reduce"
        )

    command = suite_command(seed)

    async def probe(keep: frozenset) -> Outcome:
        files = probe_files(seed.sources, seed.workdir, hunks, keep)
        result = await pool.run(
            seed.checkpoint_id, command, files=files, timeout=SUITE_TIMEOUT_S
        )
        return _outcome(result)

    found = await ddmin(hunks, probe)
    return SurfaceResult(
        hunks=labels,
        needed=tuple(h.label for h in hunks if h in found.minimal),
        undefended=tuple(h.label for h in hunks if h not in found.minimal),
        probes=found.probes,
        exhausted=found.exhausted,
        skipped=skipped,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_reduce_surface.py -q`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/reduce/surface.py tests/test_reduce_surface.py
git commit -m "feat: find the undefended surface with ddmin over PR hunks"
```

---

### Task 10: The run orchestrator and its report

**Files:**
- Create: `src/chesterton/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: everything above; `semantic_hunks` from `chesterton.diffing.semantic`; `changed_lines`; `uncovered_findings` from `chesterton.defended`; `generate` from `chesterton.mutation.generate`; `propose`, `Proposal` from `chesterton.llm.mutants`.
- Produces: `MODEL_CONCURRENCY = 8`; `RunRefused(RuntimeError)`; `ModelStats(calls: int, retried: int, failures: dict[str, int])`; `RunReport` (fields below) with `to_json() -> str`; `restrict_coverage(coverage, allowed) -> CoverageMap`; `async run_seed(seed, runner, *, client=None, op_budget=RUN_OP_BUDGET, concurrency=CONCURRENCY, reduce=True) -> RunReport`.

`RunReport` fields, in order: `slug: str`, `wall_s: float`, `tier0: list[tuple[str, int]]`, `hunks: int`, `generated: int`, `rejected: dict[str, int]`, `model: ModelStats | None`, `results: list[MutantResult]`, `counts: VerdictCounts`, `surface: SurfaceResult | None`, `ops_used: int`, `op_budget: int`.

- [ ] **Step 1: Write the failing test**

`tests/test_run.py`:

```python
import json

import openai
import pytest

from chesterton.run import RunRefused, restrict_coverage, run_seed
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import T_CHARGE, T_FLAKY


def guard_matters_to_mutants_but_not_to_the_suite(checkpoint, shell, files):
    """Mutant runs name a test id and die unless the guard's raise survives.
    Surface probes deselect tests, and the suite passes either way, so the
    guard is undefended."""
    if "--deselect" in shell:
        return RunResult("", "", 0, None)
    written = files.get("/testbed/pay.py", "")
    return RunResult("", "", 1 if "raise ValueError" in written else 0, None)


class _Client:
    def __init__(self, reply=None, raises=None):
        self.reply, self.raises, self.calls = reply, raises, 0

    async def complete(self, prompt, *, model, max_tokens=2048, thinking=False):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.reply


async def test_a_deterministic_run_reports_verdicts_tier0_and_the_surface(demo_seed):
    runner = FakeSandboxRunner(handler=guard_matters_to_mutants_but_not_to_the_suite)

    report = await run_seed(demo_seed, runner)

    assert report.hunks == 1
    assert report.generated == len(report.results) > 0
    assert report.counts.survived >= 1  # deleting the guard goes unnoticed
    assert report.model is None
    # Line 3 is executed only by a flaky test, so it is undefended (P3-6).
    assert ("pay.py", 3) in report.tier0
    assert report.surface.undefended == ("pay.py#0",)
    assert report.ops_used <= report.op_budget


async def test_a_run_that_cannot_afford_its_mutants_refuses_before_any_op(demo_seed):
    runner = FakeSandboxRunner()

    with pytest.raises(RunRefused, match="refusing to start"):
        await run_seed(demo_seed, runner, op_budget=0)

    assert runner.calls == []


async def test_malformed_model_replies_are_retried_once_then_counted(demo_seed):
    client = _Client(reply="not json at all")

    report = await run_seed(demo_seed, FakeSandboxRunner(), client=client, reduce=False)

    assert client.calls == 2  # one hunk, one retry
    assert report.model.calls == 2
    assert report.model.retried == 1
    assert report.model.failures == {"malformed": 1}
    assert report.generated > 0  # deterministic mutants still ran


async def test_an_unavailable_model_falls_back_to_deterministic_mutants(demo_seed):
    client = _Client(raises=openai.OpenAIError("down"))

    report = await run_seed(demo_seed, FakeSandboxRunner(), client=client, reduce=False)

    assert report.model.failures == {"unavailable": 1}
    assert report.generated > 0


async def test_a_well_formed_proposal_reaches_the_sandbox(demo_seed):
    reply = json.dumps({"mutants": [{
        "mutated_src": "    if amount is None:\n        raise ValueError(\"required\")\n",
        "rationale": "only None is rejected now",
    }]})

    report = await run_seed(
        demo_seed, FakeSandboxRunner(), client=_Client(reply=reply), reduce=False
    )

    assert any(r.mutant.source == "llm" for r in report.results)
    assert report.model.failures == {}


def test_coverage_is_restricted_to_selectable_tests():
    coverage = {"pay.py": {2: [T_CHARGE, T_FLAKY], 3: [T_FLAKY]}}

    assert restrict_coverage(coverage, {T_CHARGE}) == {"pay.py": {2: [T_CHARGE], 3: []}}


async def test_the_report_serialises_and_never_says_equivalent(demo_seed):
    runner = FakeSandboxRunner(handler=guard_matters_to_mutants_but_not_to_the_suite)

    report = await run_seed(demo_seed, runner)
    text = report.to_json()
    payload = json.loads(text)

    assert payload["counts"]["survived"] == report.counts.survived
    assert payload["score"] == report.counts.score
    assert "equivalent" not in text.lower()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_run.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.run'`.

- [ ] **Step 3: Write the orchestrator**

`src/chesterton/run.py`:

```python
"""One run against a built seed: tier 0, then mutation, then reduction.

The order is the spec's run-time pipeline (§4). Tier 1 (CrossHair) is
Phase 2b and slots in between tier 0 and mutation when it lands.

Budget (ruling P3-2): sandbox ops and model calls are capped. Dollars are
not, because sandboxes are free during the beta and no price is recorded
for the one model tier Phase 3 calls. If the mutant ops alone exceed the op
budget, the run refuses to start (spec §14). ddmin probes spend what is
left, and a search the budget cuts short says so.

Model proposals are retried once, then the run falls back to deterministic
mutants only (spec §14). Every failure is counted by kind, so a total model
outage reads as an outage and never as "the model had nothing to say".
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from collections.abc import Collection
from dataclasses import asdict, dataclass

from chesterton.defended import uncovered_findings
from chesterton.diffing.parse import changed_lines
from chesterton.diffing.semantic import semantic_hunks
from chesterton.execute.mutants import (
    MutantResult,
    VerdictCounts,
    count_verdicts,
    execute_mutants,
    select_tests,
)
from chesterton.execute.pool import CONCURRENCY, RUN_OP_BUDGET, SandboxPool
from chesterton.llm.mutants import propose
from chesterton.models import CoverageMap, Hunk
from chesterton.mutation.generate import generate
from chesterton.mutation.model import Mutant
from chesterton.reduce.surface import SurfaceResult, undefended_surface
from chesterton.seed.record import SeedRecord

#: Lightning is the high-volume tier; this keeps a burst polite.
MODEL_CONCURRENCY = 8

#: The model call raised rather than replying, e.g. a connection error.
UNAVAILABLE = "unavailable"


class RunRefused(RuntimeError):
    """The run would overspend its budget, so it did not start."""


@dataclass(frozen=True)
class ModelStats:
    calls: int
    retried: int
    failures: dict[str, int]


@dataclass(frozen=True)
class RunReport:
    slug: str
    wall_s: float
    tier0: list[tuple[str, int]]
    hunks: int
    generated: int
    rejected: dict[str, int]
    model: ModelStats | None
    results: list[MutantResult]
    counts: VerdictCounts
    surface: SurfaceResult | None
    ops_used: int
    op_budget: int

    def to_json(self) -> str:
        payload = asdict(self)
        payload["score"] = self.counts.score
        return json.dumps(payload, indent=2)


def restrict_coverage(coverage: CoverageMap, allowed: Collection[str]) -> CoverageMap:
    """Ruling P3-6: a line run only by a flaky or failing test is undefended."""
    return {
        file: {line: [t for t in tests if t in allowed] for line, tests in lines.items()}
        for file, lines in coverage.items()
    }


def _semantic_hunks(seed: SeedRecord, changed: dict[str, list[int]]) -> list[Hunk]:
    hunks: list[Hunk] = []
    for file, source in sorted(seed.sources.items()):
        lines = changed.get(file)
        if lines:  # a pure deletion adds no line to mutate
            hunks.extend(semantic_hunks(source, file, lines))
    return hunks


async def _propose_all(
    client, hunks: list[Hunk], sources: dict[str, str]
) -> tuple[list[Mutant], ModelStats]:
    import openai

    semaphore = asyncio.Semaphore(MODEL_CONCURRENCY)
    calls = retried = 0
    failures: Counter[str] = Counter()

    async def one(hunk: Hunk) -> list[Mutant]:
        nonlocal calls, retried
        async with semaphore:
            failure = None
            for attempt in (1, 2):
                calls += 1
                try:
                    proposal = await propose(
                        client,
                        file=hunk.file,
                        module_src=sources[hunk.file],
                        start_line=hunk.start_line,
                        end_line=hunk.end_line,
                    )
                except openai.OpenAIError:
                    failure = UNAVAILABLE
                else:
                    if proposal.failure is None:
                        return proposal.mutants
                    failure = proposal.failure
                if attempt == 1:
                    retried += 1
            failures[failure] += 1
            return []

    batches = await asyncio.gather(*(one(h) for h in hunks))
    mutants = [m for batch in batches for m in batch]
    return mutants, ModelStats(calls, retried, dict(failures))


async def run_seed(
    seed: SeedRecord,
    runner,
    *,
    client=None,
    op_budget: int = RUN_OP_BUDGET,
    concurrency: int = CONCURRENCY,
    reduce: bool = True,
) -> RunReport:
    started = time.perf_counter()
    changed = changed_lines(seed.pr.diff)
    hunks = _semantic_hunks(seed, changed)
    defended = restrict_coverage(seed.coverage, seed.selectable)
    tier0 = uncovered_findings(hunks, defended, changed)

    llm_mutants: list[Mutant] = []
    model = None
    if client is not None:
        llm_mutants, model = await _propose_all(client, hunks, seed.sources)

    mutants, rejected = generate(hunks, seed.sources, llm_mutants=llm_mutants)

    pool = SandboxPool(runner, concurrency=concurrency, op_budget=op_budget)
    needed = sum(1 for m in mutants if select_tests(m, seed))
    if needed > pool.remaining:
        raise RunRefused(
            f"this run needs {needed} sandbox ops for its mutants alone and its "
            f"budget is {op_budget}; refusing to start rather than overspend"
        )

    results = await execute_mutants(pool, seed, mutants)
    surface = None
    if reduce and pool.remaining > 0:
        surface = await undefended_surface(pool, seed)

    return RunReport(
        slug=seed.slug,
        wall_s=round(time.perf_counter() - started, 3),
        tier0=tier0,
        hunks=len(hunks),
        generated=len(mutants),
        rejected=rejected,
        model=model,
        results=results,
        counts=count_verdicts(results),
        surface=surface,
        ops_used=pool.ops_used,
        op_budget=op_budget,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_run.py -q`
Expected: PASS, 7 passed.

Then run: `.venv/Scripts/python -m pytest -q`
Expected: the full suite is green.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/run.py tests/test_run.py
git commit -m "feat: orchestrate a run from tier 0 through ddmin under one budget"
```

---

### Task 11: The command line

**Files:**
- Create: `src/chesterton/__main__.py`
- Modify: `.gitignore`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_seed`, `SeedBuildError` (Task 4); `SeedRecord` (Task 4); `run_seed`, `RunRefused`, `RunReport` (Task 10); `parse_pr_url`, `fetch_pull_request` from `chesterton.github.pr`; `ConTreeSandboxRunner`; `NemotronClient`.
- Produces: `main(argv: list[str] | None = None, *, runner_factory=None, client_factory=None, fetch=None) -> int`, invoked as `python -m chesterton seed ...` and `python -m chesterton run ...`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json

import pytest

from chesterton.__main__ import main
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.build import COVERAGE_PATH, RUN_LOGS
from chesterton.seed.record import SeedRecord

from conftest import HEAD_PAY, T_CHARGE


def a_seedable_runner():
    log = f"PASSED {T_CHARGE}\n"
    coverage = {"files": {"pay.py": {"contexts": {"2": [f"{T_CHARGE}|run"]}}}}
    return FakeSandboxRunner(artifacts={
        RUN_LOGS[0]: log, RUN_LOGS[1]: log, RUN_LOGS[2]: log,
        COVERAGE_PATH: json.dumps(coverage), "/testbed/pay.py": HEAD_PAY,
    })


def test_seed_writes_a_loadable_seed_record(tmp_path, demo_seed, capsys):
    out = tmp_path / "seeds" / "demo.json"

    async def fetch(url):
        assert url == "https://github.com/acme/pay/pull/1"
        return demo_seed.pr

    code = main(
        ["seed", "--pr", "https://github.com/acme/pay/pull/1",
         "--image", "docker://example/pay", "--slug", "demo", "--out", str(out)],
        runner_factory=a_seedable_runner, fetch=fetch,
    )

    assert code == 0
    seed = SeedRecord.from_json(out.read_text(encoding="utf-8"))
    assert seed.selectable == {T_CHARGE}
    assert "chesterton:seed-demo" in capsys.readouterr().out


def test_run_writes_a_report_and_names_the_undefended_surface(tmp_path, demo_seed, capsys):
    seed_path = tmp_path / "demo.json"
    seed_path.write_text(demo_seed.to_json(), encoding="utf-8")
    out = tmp_path / "runs" / "demo.json"

    def runner_factory():
        return FakeSandboxRunner(handler=lambda c, s, f: RunResult("", "", 0, None))

    code = main(
        ["run", str(seed_path), "--out", str(out), "--no-llm"],
        runner_factory=runner_factory,
    )

    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["slug"] == "demo"
    printed = capsys.readouterr().out
    assert "undefended" in printed
    assert "equivalent" not in printed.lower()


def test_a_refused_run_exits_2_with_the_reason(tmp_path, demo_seed, capsys):
    seed_path = tmp_path / "demo.json"
    seed_path.write_text(demo_seed.to_json(), encoding="utf-8")

    code = main(
        ["run", str(seed_path), "--out", str(tmp_path / "r.json"),
         "--no-llm", "--op-budget", "0"],
        runner_factory=FakeSandboxRunner,
    )

    assert code == 2
    assert "refusing to start" in capsys.readouterr().err


def test_a_failed_seed_build_exits_1_with_the_reason(tmp_path, demo_seed, capsys):
    async def fetch(url):
        return demo_seed.pr

    def broken():
        return FakeSandboxRunner(
            handler=lambda c, s, f: RunResult("", "error: patch failed", 1, None)
        )

    code = main(
        ["seed", "--pr", "https://github.com/acme/pay/pull/1", "--image", "x",
         "--slug", "demo", "--out", str(tmp_path / "s.json")],
        runner_factory=broken, fetch=fetch,
    )

    assert code == 1
    assert "patch failed" in capsys.readouterr().err


def test_a_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main([])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'chesterton.__main__'`.

- [ ] **Step 3: Write the CLI**

`src/chesterton/__main__.py`:

```python
"""python -m chesterton seed | run

  seed  Build time. Fetch a PR, build its tagged baseline checkpoint and
        write the seed record. Slow (image pulls measured 88-225 s), and
        never on a judge's clock.
  run   Run time. Load a seed record and run tier 0, mutation and ddmin
        against it under one op budget, then write the report.

The factories exist so tests can inject fakes. The real runner and client
read NEBIUS_API_KEY and NEBIUS_PROJECT_ID from the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from chesterton.execute.pool import RUN_OP_BUDGET
from chesterton.run import RunRefused, RunReport, run_seed
from chesterton.seed.build import SeedBuildError, build_seed
from chesterton.seed.record import SeedRecord


async def _fetch_from_github(url: str):
    import httpx

    from chesterton.github.pr import fetch_pull_request, parse_pr_url

    owner, repo, number = parse_pr_url(url)
    async with httpx.AsyncClient(timeout=30) as http:
        return await fetch_pull_request(owner, repo, number, client=http)


def _default_runner():
    from chesterton.sandbox.contree import ConTreeSandboxRunner

    return ConTreeSandboxRunner()


def _default_client():
    from chesterton.llm.client import NemotronClient

    return NemotronClient()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chesterton")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="build a seed checkpoint for a PR")
    seed.add_argument("--pr", required=True, help="GitHub pull request URL")
    seed.add_argument("--image", required=True, help="image ref, e.g. docker://...")
    seed.add_argument("--slug", required=True, help="lowercase letters, digits, hyphens")
    seed.add_argument("--out", required=True, type=Path)

    run = commands.add_parser("run", help="run Chesterton against a seed")
    run.add_argument("seed", type=Path, help="a seed record written by `seed`")
    run.add_argument("--out", required=True, type=Path)
    run.add_argument("--no-llm", action="store_true", help="deterministic mutants only")
    run.add_argument("--no-reduce", action="store_true", help="skip ddmin")
    run.add_argument("--op-budget", type=int, default=RUN_OP_BUDGET)
    return parser


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _summarise(report: RunReport) -> str:
    c = report.counts
    score = "n/a" if c.score is None else f"{c.score:.0%}"
    lines = [
        f"{report.slug}: {report.hunks} hunks, {report.generated} mutants, "
        f"{report.ops_used}/{report.op_budget} sandbox ops, {report.wall_s:.1f}s",
        f"  tier 0: {len(report.tier0)} changed lines no selectable test executes",
        f"  mutants: {c.killed} killed, {c.survived} survived "
        f"(no selected test failed), {c.uncovered} uncovered, {c.error} error; "
        f"score {score} (errors and uncovered excluded)",
    ]
    if report.model is not None:
        failures = ", ".join(f"{k} {v}" for k, v in sorted(report.model.failures.items()))
        lines.append(
            f"  model: {report.model.calls} calls, {report.model.retried} retried, "
            f"failures: {failures or 'none'}"
        )
    surface = report.surface
    if surface is None:
        lines.append("  undefended surface: not computed")
    elif surface.note:
        lines.append(f"  undefended surface: {surface.note}")
    else:
        bound = " (budget ran out: at least these)" if surface.exhausted else ""
        lines.append(
            f"  undefended surface: of {len(surface.hunks)} hunks, "
            f"{len(surface.undefended)} are undefended{bound}: "
            f"{', '.join(surface.undefended) or 'none'} ({surface.probes} probes)"
        )
    return "\n".join(lines)


async def _seed(args, runner_factory, fetch) -> int:
    pr = await fetch(args.pr)
    runner = runner_factory()
    try:
        seed = await build_seed(runner, pr, slug=args.slug, image_ref=args.image)
    except SeedBuildError as exc:
        print(f"seed build failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await runner.aclose()
    _write(args.out, seed.to_json())
    print(
        f"seed {seed.slug}: checkpoint {seed.checkpoint_id} tagged "
        f"{seed.checkpoint_tag}; {len(seed.selectable)} selectable, "
        f"{len(seed.flaky)} flaky, {len(seed.failing)} failing tests -> {args.out}"
    )
    return 0


async def _run(args, runner_factory, client_factory) -> int:
    seed = SeedRecord.from_json(args.seed.read_text(encoding="utf-8"))
    runner = runner_factory()
    client = None if args.no_llm else client_factory()
    try:
        report = await run_seed(
            seed, runner, client=client,
            op_budget=args.op_budget, reduce=not args.no_reduce,
        )
    except RunRefused as exc:
        print(f"run refused: {exc}", file=sys.stderr)
        return 2
    finally:
        await runner.aclose()
    _write(args.out, report.to_json())
    print(_summarise(report))
    return 0


def main(argv=None, *, runner_factory=None, client_factory=None, fetch=None) -> int:
    args = build_parser().parse_args(argv)
    runner_factory = runner_factory or _default_runner
    if args.command == "seed":
        return asyncio.run(_seed(args, runner_factory, fetch or _fetch_from_github))
    return asyncio.run(_run(args, runner_factory, client_factory or _default_client))


if __name__ == "__main__":
    raise SystemExit(main())
```

Append to `.gitignore`:

```
# Seed records and run reports name account-specific checkpoints
/seeds/
/runs/
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q`
Expected: PASS, 5 passed.

Then run: `.venv/Scripts/python -m pytest -q`
Expected: the full suite is green, with the live tests skipped.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/__main__.py .gitignore tests/test_cli.py
git commit -m "feat: add the seed and run command line"
```

---

### Task 12: Live end-to-end on a real seed — measurement

This is not an implementation task. The **controller** runs it with the user's credentials, and code changes only if the live run exposes a defect. Any such defect gets its own fix and review.

It answers the open item in spec §15, "the per-mutant duration is not yet pinned", and it tests rulings P3-3, P3-4 and P3-5 against reality.

- [ ] **Step 1: Confirm the instance**

Confirm in the SWE-rebench dataset that the image `swerebench/sweb.eval.x86_64.iamconsortium_1776_nomenclature-284` is instance `IAMconsortium__nomenclature-284`, which is PR #284. If it is not, find the right PR number before building.

- [ ] **Step 2: Run the live adapter tests**

```powershell
$env:CHESTERTON_LIVE = "1"
.venv\Scripts\python -m pytest tests/live -q
```

Expected: 7 passed. Stop on any failure.

- [ ] **Step 3: Build the seed**

```powershell
.venv\Scripts\python -m chesterton seed --pr https://github.com/IAMconsortium/nomenclature/pull/284 --image docker://swerebench/sweb.eval.x86_64.iamconsortium_1776_nomenclature-284 --slug nomenclature-284 --out seeds/nomenclature-284.json
```

Record the wall time, the selectable, flaky and failing counts, and whether `git apply` succeeded. If it fails, the error names the stage.

- [ ] **Step 4: Run it, deterministic first, then with the model**

```powershell
.venv\Scripts\python -m chesterton run seeds/nomenclature-284.json --out runs/nomenclature-284-det.json --no-llm
.venv\Scripts\python -m chesterton run seeds/nomenclature-284.json --out runs/nomenclature-284.json
```

- [ ] **Step 5: Record the numbers in spec §15**

From the reports, record: seed build time; median and worst per-mutant `duration_s`; verdict counts; the undefended surface with its probe count; total wall time; ops used; and model calls and failures. Replace §15's "the per-mutant duration is not yet pinned" with the measured figure, and date it.

---

## Phase 3 is done when

- `pytest` is green with no network access, and the `tests/live` suite passes live.
- `python -m chesterton seed` builds a tagged checkpoint for a real PR in a real SWE-rebench image.
- `python -m chesterton run` produces honest verdicts under `Semaphore(24)` and an op budget, refuses to start when it cannot afford its mutants, and reports the undefended surface.
- Spec §15 has measured per-mutant durations from a real seed.

## Follow-on

- **Phase 2b: the distinguishing-input tier.** CrossHair `diffbehavior` plus the Hypothesis `ghostwriter.equivalent()` fallback, slotted into `run_seed` between tier 0 and mutation.
- **Phase 4: triage and review.** Survivor classification on Super with abstention, and regression-test generation verified both ways. It also carries the dollar budget (ruling P3-2), with prices read live, and puts `Candidate.line`/`.column` on findings (Phase 2 ruling P16).
- **Phase 5: interface and persistence.** SQLite, the `event` log, and the SSE stream (spec §4, §12). `RunReport` is the payload the event log will carry.
