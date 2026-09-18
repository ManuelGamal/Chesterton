# Chesterton Phase 1 — Foundations and Fan-Out Spike

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the offline-testable core — sandbox abstraction, GitHub PR ingest, diff parsing, coverage inversion — and answer the go/no-go question of whether forking a ConTree checkpoint 24 ways *and running a test suite in each* is fast enough to feel live.

**Architecture:** Every component is a pure function or a protocol-backed adapter, so the whole pipeline runs offline against a fake in milliseconds. The real ConTree adapter is one thin implementation of the same protocol, exercised deliberately. The phase deliverable is a function that takes a seeded PR and returns, for each changed line, the tests that defend it — plus a measured fan-out latency number that decides the architecture.

**Tech Stack:** Python 3.13, `httpx`, `unidiff`, `libcst`, `coverage`, `pytest`, `pytest-asyncio`, `contree-sdk`.

**Spec:** `docs/superpowers/specs/2026-09-18-chesterton-design.md`

**Revision note (2026-09-18):** revised after a seven-agent task-by-task
critique. Tasks 4 and 5 were restructured; every other task took fixes. The
defects corrected here were all of the silent-corruption class — wrong answers
with green tests. Each is called out inline as **[FIX]**.

## Global Constraints

- Repository ships under **MIT**. No AGPL dependencies (Mutahunter is AGPL-3.0 — never vendor, copy, or install). Hypothesis is MPL-2.0 and `unidiff` is MIT; both are used unmodified.
- **Python repositories only.** No JS/TS support.
- Sandbox concurrency is capped at **`asyncio.Semaphore(24)`** — the ConTree beta cap is 50 total simultaneous operations and must leave headroom for retries and a second concurrent visitor.
- A failed or timed-out sandbox operation is **`error`** and is excluded from statistics. It is **never** counted as `killed`.
- The absence of a detected behavioural difference is **never** rendered as "equivalent" — the wording is "no difference found within budget".
- Every persisted checkpoint must be **tagged**; untagged images may be garbage-collected and judging runs six weeks after submission.
- Baseline coverage runs **single-threaded** — dynamic contexts are unreliable under `pytest-xdist`.
- **All file paths are normalised to forward slashes at every boundary.** coverage.py records native separators; GitHub diffs always use `/`. A mismatch makes every hunk look uncovered, silently.
- **A disposable run has no reusable checkpoint.** `RunResult.checkpoint_id` is `None` for `disposable=True` in every implementation, real and fake.
- GitHub diffs are computed against the **merge base**, not `base.sha`. Every line number derives from the merge base.
- No network calls in unit tests. All external responses are recorded fixtures.

---

## File Structure

```
pyproject.toml                          # deps, pytest config, Python 3.13 floor
src/chesterton/
  models.py                             # Hunk, PullRequest, CoverageMap types
  paths.py                              # the one path-normalisation function
  sandbox/protocol.py                   # SandboxRunner Protocol, RunResult
  sandbox/fake.py                       # FakeSandboxRunner for offline tests
  sandbox/contree.py                    # real ConTree adapter
  github/pr.py                          # PR metadata + diff + merge base
  diffing/parse.py                      # unidiff -> changed line numbers
  diffing/semantic.py                   # ast-based hunk grouping
  covmap/invert.py                      # coverage json -> {file: {line: [tests]}}
  defended.py                           # joins hunks to coverage (deliverable)
scripts/spike_fanout.py                 # the go/no-go measurement
tests/fixtures/                         # recorded API responses, diffs, coverage
tests/test_*.py                         # one test module per source module
```

---

### Task 1: Sandbox protocol and fake runner

**[FIX] Three changes from the critique:** `RunResult.checkpoint_id` is now
`str | None` so the fake and the real adapter agree on disposable semantics;
`aclose()` is declared on the protocol so consumers can write correct lifecycle
code over both implementations; the unused `latency` parameter is cut.

**Files:**
- Create: `pyproject.toml`
- Create: `src/chesterton/__init__.py`
- Create: `src/chesterton/sandbox/__init__.py`
- Create: `src/chesterton/sandbox/protocol.py`
- Create: `src/chesterton/sandbox/fake.py`
- Test: `tests/test_sandbox_fake.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RunResult(stdout: str, stderr: str, exit_code: int, checkpoint_id: str | None)`; `SandboxRunner` protocol (runtime-checkable) with `async use_image(ref: str) -> str`, `async run(checkpoint_id: str, shell: str, *, files: Mapping[str, str] | None = None, disposable: bool = True) -> RunResult`, and `async aclose() -> None`; `FakeSandboxRunner(responses: Mapping[str, RunResult] | None = None)` exposing `.calls: list[tuple[str, str]]` and `.files_written: list[dict[str, str]]`.

- [ ] **Step 1: Create the project scaffold**

`pyproject.toml`:

```toml
[project]
name = "chesterton"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "unidiff>=0.7.5",
    "libcst>=1.4",
    "coverage>=7.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "pytest-cov>=5.0"]
sandbox = ["contree-sdk"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.hatch.build.targets.wheel]
packages = ["src/chesterton"]
```

Create the venv with **`py -3.13`** — the default `python` on this machine is
3.10.6, below the floor:

```bash
py -3.13 -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python --version    # must report 3.13.x
```

Create empty `src/chesterton/__init__.py` and `src/chesterton/sandbox/__init__.py`.

- [ ] **Step 2: Write the failing test**

`tests/test_sandbox_fake.py`:

```python
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

    result = await runner.run(base, "pip install -e .", disposable=False)

    assert result.checkpoint_id is not None
    assert result.checkpoint_id != base


async def test_disposable_run_has_no_reusable_checkpoint():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q", disposable=True)

    assert result.checkpoint_id is None


async def test_aclose_is_safe_to_call():
    runner = FakeSandboxRunner()
    await runner.aclose()
    await runner.aclose()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_fake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.sandbox.fake'`

- [ ] **Step 4: Write the protocol**

`src/chesterton/sandbox/protocol.py`:

```python
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
        files: Mapping[str, str] | None = None,
        disposable: bool = True,
    ) -> RunResult:
        """Fork `checkpoint_id`, write `files`, run `shell`.

        `files` maps destination path to file contents.
        `disposable=False` persists the resulting filesystem as a new
        checkpoint and returns its id; `disposable=True` returns None.
        """
        ...

    async def aclose(self) -> None:
        """Release any transport resources. Safe to call more than once."""
        ...
```

- [ ] **Step 5: Write the fake**

`src/chesterton/sandbox/fake.py`:

```python
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_fake.py -v`
Expected: PASS — 8 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/chesterton tests/test_sandbox_fake.py
git commit -m "feat: add SandboxRunner protocol and in-memory fake"
```

---

### Task 2: ConTree adapter and the fan-out spike

**[FIX] Three changes from the critique:** the adapter returns `None` for
disposable runs, matching the protocol; a missing SDK now fails with a clear,
actionable error instead of a bare `ImportError` at first use; and **the spike
runs a real test suite in each fork rather than a no-op**, because forking a
checkpoint to print an integer measures nothing the architecture depends on.

**Files:**
- Create: `src/chesterton/sandbox/contree.py`
- Create: `scripts/spike_fanout.py`
- Test: `tests/test_sandbox_contree.py`

**Interfaces:**
- Consumes: `SandboxRunner`, `RunResult` from Task 1.
- Produces: `ConTreeSandboxRunner(api_key: str, base_url: str = "https://api.tokenfactory.nebius.com/sandboxes")` satisfying `SandboxRunner`.

- [ ] **Step 1: Write the failing test**

The adapter is tested for shape, not behaviour — real calls cost credits.

`tests/test_sandbox_contree.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_contree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.sandbox.contree'`

- [ ] **Step 3: Write the adapter**

`src/chesterton/sandbox/contree.py`:

```python
"""Real SandboxRunner backed by Nebius Token Factory Sandboxes (ConTree).

The SDK is young and its surface is unverified against the live service. If it
shifts, change only this file — the protocol is the stable boundary.
"""

from __future__ import annotations

from collections.abc import Mapping

from chesterton.sandbox.protocol import RunResult

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes"

_MISSING_SDK = (
    "contree-sdk is not installed. Install the sandbox extra with "
    'pip install -e ".[sandbox]" before using ConTreeSandboxRunner.'
)


class ConTreeSandboxRunner:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self._client = None
        self._sdk = None

    async def _sdk_handle(self):
        if self._sdk is None:
            try:
                from contree_client.httpx import ContreeAsyncClient
                from contree_sdk import Contree
            except ImportError as exc:  # fail loudly, at first use, with a fix
                raise RuntimeError(_MISSING_SDK) from exc

            self._client = ContreeAsyncClient(
                self.api_key, base_url=self.base_url, timeout=120.0
            )
            self._sdk = Contree(self._client)
        return self._sdk

    async def use_image(self, ref: str) -> str:
        sdk = await self._sdk_handle()
        if ref.startswith("docker://"):
            image = await sdk.images.oci(ref)
        else:
            image = await sdk.images.use(ref)
        return image.uuid

    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str] | None = None,
        disposable: bool = True,
        tag: str | None = None,
    ) -> RunResult:
        sdk = await self._sdk_handle()
        image = await sdk.images.use(checkpoint_id)
        result = await image.run(
            shell=shell,
            files=dict(files) if files else None,
            disposable=disposable,
            tag=tag,
        )
        # A disposable run persists nothing, so there is no id to fork from.
        # Reporting result.uuid here would let offline code depend on
        # something the fake cannot honestly provide.
        return RunResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            checkpoint_id=None if disposable else result.uuid,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._sdk = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_contree.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Write the spike script**

**[FIX] This measures fork + a real test run.** The previous version forked 24
ways to run `python -c 'print(i)'`, which measures fork latency for a workload
nothing in the architecture resembles. Every real fan-out runs a test suite.

`scripts/spike_fanout.py`:

```python
"""Go/no-go measurement: forking one checkpoint 24 ways and running tests.

Usage:
    python scripts/spike_fanout.py <image-ref> "<test-command>" [rounds]

Example:
    python scripts/spike_fanout.py docker://<swe-rebench-image> "pytest -q -x" 3

Reports wall clock, per-fork distribution, failure count, and round-to-round
variance. Phase 2's tier design depends on all four.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time

from chesterton.sandbox.contree import ConTreeSandboxRunner

FANOUT = 24
TARGET_SECONDS = 20.0


async def one_fork(runner, checkpoint_id: str, test_cmd: str) -> tuple[float, bool]:
    start = time.perf_counter()
    try:
        result = await runner.run(checkpoint_id, test_cmd, disposable=True)
        ok = result.exit_code in (0, 1)  # 1 == tests ran and failed; still a run
    except Exception as exc:  # an errored op is never a result
        print(f"  fork errored: {type(exc).__name__}: {exc}")
        return time.perf_counter() - start, False
    return time.perf_counter() - start, ok


async def one_round(runner, checkpoint_id: str, test_cmd: str) -> dict:
    sem = asyncio.Semaphore(FANOUT)

    async def guarded() -> tuple[float, bool]:
        async with sem:
            return await one_fork(runner, checkpoint_id, test_cmd)

    start = time.perf_counter()
    outcomes = await asyncio.gather(*(guarded() for _ in range(FANOUT)))
    wall = time.perf_counter() - start

    timings = [t for t, _ in outcomes]
    failures = sum(1 for _, ok in outcomes if not ok)
    return {
        "wall": wall,
        "median": statistics.median(timings),
        "p_slowest": max(timings),
        "failures": failures,
    }


async def main(image_ref: str, test_cmd: str, rounds: int) -> None:
    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        sys.exit("NEBIUS_API_KEY is not set — the spike needs a real key.")

    runner = ConTreeSandboxRunner(api_key)

    print(f"Resolving {image_ref} ...")
    t0 = time.perf_counter()
    base = await runner.use_image(image_ref)
    print(f"  resolved in {time.perf_counter() - t0:.1f}s")

    print("Building and TAGGING the baseline checkpoint ...")
    t0 = time.perf_counter()
    prepped = await runner.run(
        base, test_cmd, disposable=False, tag="chesterton:spike-base"
    )
    build = time.perf_counter() - t0
    if prepped.checkpoint_id is None:
        sys.exit("Non-disposable run returned no checkpoint id — adapter bug.")
    print(f"  built in {build:.1f}s -> {prepped.checkpoint_id}")
    print("  (tagged: untagged checkpoints may be garbage-collected)")

    results = []
    for i in range(rounds):
        print(f"\nRound {i + 1}/{rounds}: forking {FANOUT} ways, running tests ...")
        r = await one_round(runner, prepped.checkpoint_id, test_cmd)
        results.append(r)
        print(
            f"  wall {r['wall']:.1f}s | median fork {r['median']:.2f}s | "
            f"slowest {r['p_slowest']:.2f}s | failed {r['failures']}/{FANOUT}"
        )

    walls = [r["wall"] for r in results]
    worst = max(walls)
    spread = max(walls) - min(walls)
    total_failures = sum(r["failures"] for r in results)

    print("\n=== SPIKE RESULT ===")
    print(f"  baseline build     : {build:.1f}s (one-time, cached)")
    print(f"  worst-case wall    : {worst:.1f}s over {rounds} round(s)")
    print(f"  round-to-round spread: {spread:.1f}s")
    print(f"  failed forks       : {total_failures}/{FANOUT * rounds}")
    print(f"\n  VERDICT: {'GO' if worst < TARGET_SECONDS else 'REDESIGN — see spec section 15'}")
    print("  Record all four numbers in spec section 15.")

    await runner.aclose()


if __name__ == "__main__":
    cmd = sys.argv[2] if len(sys.argv) > 2 else "pytest -q"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    asyncio.run(main(sys.argv[1], cmd, n))
```

- [ ] **Step 6: Verify the script parses (the live run is deferred)**

Run: `.venv/Scripts/python -c "import ast,pathlib; ast.parse(pathlib.Path('scripts/spike_fanout.py').read_text()); print('ok')"`
Expected: `ok`

**The live spike requires `NEBIUS_API_KEY` and is deferred until credentials
exist.** When it runs, write all four numbers into spec section 15, replacing
"This is unmeasured." If worst-case wall exceeds 20s, stop and revisit the spec
before planning Phase 2.

- [ ] **Step 7: Commit**

```bash
git add src/chesterton/sandbox/contree.py scripts/spike_fanout.py tests/test_sandbox_contree.py
git commit -m "feat: add ConTree sandbox adapter and fan-out spike script"
```

---

### Task 3: GitHub PR ingest with correct merge base

**[FIX] Error handling added throughout.** The previous version called `.json()`
on unchecked responses and indexed `merge_base_commit["sha"]` unguarded — a 403
rate-limit reply would crash, and a shape change would silently put every
mutation on the wrong line. The anonymous quota is 60/hr and the hosted demo
shares one IP across all judges, so this path *will* be rate-limited.

**Files:**
- Create: `src/chesterton/models.py`
- Create: `src/chesterton/paths.py`
- Create: `src/chesterton/github/__init__.py`
- Create: `src/chesterton/github/pr.py`
- Create: `tests/fixtures/pr_meta.json`
- Create: `tests/fixtures/pr_compare.json`
- Create: `tests/fixtures/pr.diff`
- Test: `tests/test_github_pr.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PullRequest` dataclass (`owner, repo, number, title, base_sha, head_sha, merge_base_sha, clone_url, diff`); `Hunk`; `CoverageMap`; `normalise_path(p: str) -> str`; `parse_pr_url(url) -> tuple[str, str, int]`; `async fetch_pull_request(owner, repo, number, *, client) -> PullRequest`; `GitHubError`.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/pr_meta.json`:

```json
{
  "number": 42,
  "title": "Speed up user lookup",
  "base": {
    "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "repo": {"clone_url": "https://github.com/acme/widgets.git"}
  },
  "head": {"sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
}
```

`tests/fixtures/pr_compare.json` — **the merge base differs from `base.sha`;
that is the entire point of this task:**

```json
{
  "merge_base_commit": {
    "sha": "cccccccccccccccccccccccccccccccccccccccc"
  }
}
```

`tests/fixtures/pr.diff`:

```
diff --git a/widgets/users.py b/widgets/users.py
index 1111111..2222222 100644
--- a/widgets/users.py
+++ b/widgets/users.py
@@ -10,7 +10,6 @@ def get_user(user_id):
     cached = _cache.get(user_id)
     if cached is not None:
         return cached
-    if not user_id:
-        raise ValueError("user_id required")
     row = _db.fetch(user_id)
     return row
@@ -30,3 +29,4 @@ def list_users(limit):
     rows = _db.fetch_all()
+    rows = rows[:limit]
     return rows
```

- [ ] **Step 2: Write the failing test**

`tests/test_github_pr.py`:

```python
import json
from pathlib import Path

import httpx
import pytest

from chesterton.github.pr import GitHubError, fetch_pull_request, parse_pr_url

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_pr_url_extracts_owner_repo_and_number():
    assert parse_pr_url("https://github.com/acme/widgets/pull/42") == (
        "acme",
        "widgets",
        42,
    )


def test_parse_pr_url_rejects_a_non_pr_url():
    with pytest.raises(ValueError):
        parse_pr_url("https://github.com/acme/widgets")


def _ok_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/pulls/42") and "diff" in request.headers.get("accept", ""):
        return httpx.Response(200, text=(FIXTURES / "pr.diff").read_text())
    if path.endswith("/pulls/42"):
        return httpx.Response(
            200, json=json.loads((FIXTURES / "pr_meta.json").read_text())
        )
    if "/compare/" in path:
        return httpx.Response(
            200, json=json.loads((FIXTURES / "pr_compare.json").read_text())
        )
    return httpx.Response(404)


async def test_fetch_uses_merge_base_not_base_sha():
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler)) as c:
        pr = await fetch_pull_request("acme", "widgets", 42, client=c)

    assert pr.base_sha == "a" * 40
    assert pr.merge_base_sha == "c" * 40
    assert pr.merge_base_sha != pr.base_sha


async def test_fetch_returns_title_clone_url_and_diff():
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler)) as c:
        pr = await fetch_pull_request("acme", "widgets", 42, client=c)

    assert pr.title == "Speed up user lookup"
    assert pr.clone_url == "https://github.com/acme/widgets.git"
    assert "def get_user" in pr.diff


async def test_a_missing_pull_request_raises_github_error():
    def handler(request):
        return httpx.Response(404, json={"message": "Not Found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(GitHubError, match="404"):
            await fetch_pull_request("acme", "ghost", 1, client=c)


async def test_rate_limit_is_retried_then_surfaces_as_github_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(GitHubError, match="rate limit"):
            await fetch_pull_request("acme", "widgets", 42, client=c, max_retries=2)

    assert calls["n"] == 2


async def test_a_missing_merge_base_field_raises_a_clear_error():
    def handler(request):
        path = request.url.path
        if "/compare/" in path:
            return httpx.Response(200, json={})
        return httpx.Response(
            200, json=json.loads((FIXTURES / "pr_meta.json").read_text())
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(GitHubError, match="merge_base_commit"):
            await fetch_pull_request("acme", "widgets", 42, client=c)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_github_pr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.github'`

- [ ] **Step 4: Write the models and the path helper**

`src/chesterton/models.py`:

```python
"""Shared value types. Frozen dataclasses — nothing here mutates."""

from __future__ import annotations

from dataclasses import dataclass

# file path (forward slashes) -> line number -> test ids executing that line
CoverageMap = dict[str, dict[int, list[str]]]


@dataclass(frozen=True)
class PullRequest:
    owner: str
    repo: str
    number: int
    title: str
    base_sha: str
    head_sha: str
    merge_base_sha: str
    clone_url: str
    diff: str


@dataclass(frozen=True)
class Hunk:
    """A contiguous group of changed lines, in post-patch coordinates."""

    file: str
    start_line: int
    end_line: int

    @property
    def lines(self) -> list[int]:
        return list(range(self.start_line, self.end_line + 1))
```

`src/chesterton/paths.py`:

```python
"""One path spelling, everywhere.

coverage.py records native separators; GitHub diffs always use forward
slashes. If the two ever meet unnormalised, every lookup misses and every
hunk looks uncovered — silently, with green tests. Normalise at the boundary.
"""

from __future__ import annotations


def normalise_path(path: str) -> str:
    # removeprefix, not lstrip: lstrip strips CHARACTERS, so lstrip("./")
    # would turn ".hidden/x.py" into "hidden/x.py".
    return path.replace("\\", "/").removeprefix("./")
```

- [ ] **Step 5: Write the ingest**

`src/chesterton/github/__init__.py` — empty.

`src/chesterton/github/pr.py`:

```python
"""Fetch a public pull request with plain HTTPS GETs.

No Octokit, no GitHub App, no OAuth — judges must not install anything.
Set GITHUB_TOKEN in the server environment to lift the 60 req/hr anonymous
limit to 5,000; the token is never required for correctness, but the hosted
demo shares one IP across all judges and will be throttled without it.
"""

from __future__ import annotations

import asyncio
import os
import re

import httpx

from chesterton.models import PullRequest

API = "https://api.github.com"
_PR_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_RETRY_STATUS = {403, 429, 500, 502, 503, 504}


class GitHubError(RuntimeError):
    """Any failure reaching or understanding the GitHub API."""


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = _PR_URL.search(url)
    if match is None:
        raise ValueError(f"not a GitHub pull request URL: {url}")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    accept: str | None = None,
    max_retries: int = 3,
) -> httpx.Response:
    headers = _auth_headers()
    if accept:
        headers["Accept"] = accept

    last: httpx.Response | None = None
    for attempt in range(max_retries):
        response = await client.get(url, headers=headers)
        if response.status_code < 400:
            return response

        last = response
        if response.status_code not in _RETRY_STATUS:
            break
        if attempt < max_retries - 1:
            await asyncio.sleep(2**attempt)

    assert last is not None
    remaining = last.headers.get("x-ratelimit-remaining")
    if last.status_code == 403 and remaining == "0":
        raise GitHubError(
            f"GitHub rate limit exhausted for {url}. "
            "Set GITHUB_TOKEN to raise the quota from 60/hr to 5,000/hr."
        )
    raise GitHubError(f"GitHub returned {last.status_code} for {url}")


def _dig(payload: dict, *keys: str, url: str) -> object:
    node: object = payload
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise GitHubError(
                f"GitHub response from {url} is missing {'.'.join(keys)}"
            )
        node = node[key]
    return node


async def fetch_pull_request(
    owner: str,
    repo: str,
    number: int,
    *,
    client: httpx.AsyncClient,
    max_retries: int = 3,
) -> PullRequest:
    meta_url = f"{API}/repos/{owner}/{repo}/pulls/{number}"
    meta = (await _get(client, meta_url, max_retries=max_retries)).json()

    base_sha = _dig(meta, "base", "sha", url=meta_url)
    head_sha = _dig(meta, "head", "sha", url=meta_url)
    clone_url = _dig(meta, "base", "repo", "clone_url", url=meta_url)
    title = _dig(meta, "title", url=meta_url)

    # GitHub computes .diff against the MERGE BASE, not base.sha. Using
    # base.sha here puts every downstream mutation on the wrong line.
    compare_url = f"{API}/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    compare = (await _get(client, compare_url, max_retries=max_retries)).json()
    merge_base_sha = _dig(compare, "merge_base_commit", "sha", url=compare_url)

    # A second request to the same URL: the diff needs a different Accept
    # header, and GitHub will not return both representations at once.
    diff = (
        await _get(
            client,
            meta_url,
            accept="application/vnd.github.diff",
            max_retries=max_retries,
        )
    ).text

    return PullRequest(
        owner=owner,
        repo=repo,
        number=number,
        title=str(title),
        base_sha=str(base_sha),
        head_sha=str(head_sha),
        merge_base_sha=str(merge_base_sha),
        clone_url=str(clone_url),
        diff=diff,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_github_pr.py -v`
Expected: PASS — 7 passed

- [ ] **Step 7: Commit**

```bash
git add src/chesterton/models.py src/chesterton/paths.py src/chesterton/github tests/fixtures tests/test_github_pr.py
git commit -m "feat: fetch pull requests using the merge base, with retries and clear errors"
```

---

### Task 4: Parse a unified diff into changed lines

**[FIX] RESTRUCTURED — the hand-rolled parser is replaced with `unidiff`
(MIT).** The previous version recorded phantom added lines for deleted files
(`+++ /dev/null` fell through to the `startswith("+")` branch and was attributed
to the *previous* file), and drifted by one line for the rest of any hunk
containing `\ No newline at end of file`. Both corrupt line numbers silently,
which the spec calls the catastrophic failure mode. `deleted_line_counts` is
also cut — nothing in the plan or spec consumes it.

**Files:**
- Create: `src/chesterton/diffing/__init__.py`
- Create: `src/chesterton/diffing/parse.py`
- Test: `tests/test_diff_parse.py`

**Interfaces:**
- Consumes: `tests/fixtures/pr.diff` from Task 3; `normalise_path` from Task 3.
- Produces: `changed_lines(diff: str) -> dict[str, list[int]]` — post-patch line numbers of added lines per file, paths forward-slashed.

- [ ] **Step 1: Write the failing test**

`tests/test_diff_parse.py`:

```python
from pathlib import Path

from chesterton.diffing.parse import changed_lines

FIXTURES = Path(__file__).parent / "fixtures"
DIFF = (FIXTURES / "pr.diff").read_text()


def test_reports_added_lines_in_post_patch_coordinates():
    # Hunk header @@ -30,3 +29,4 @@ resumes the new file at line 29, so the
    # context line is 29 and the added line is 30.
    assert changed_lines(DIFF)["widgets/users.py"] == [30]


def test_ignores_context_and_removed_lines():
    result = changed_lines(DIFF)["widgets/users.py"]
    assert 10 not in result
    assert 11 not in result


def test_handles_a_diff_with_no_added_lines():
    pure_deletion = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,2 +1,1 @@\n"
        " keep\n"
        "-drop\n"
    )
    assert changed_lines(pure_deletion) == {"x.py": []}


def test_a_deleted_file_contributes_no_added_lines():
    deleted = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-one\n"
        "-two\n"
    )
    assert changed_lines(deleted) == {}


def test_a_deleted_file_does_not_pollute_the_next_file():
    combined = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-one\n"
        "diff --git a/kept.py b/kept.py\n"
        "--- a/kept.py\n"
        "+++ b/kept.py\n"
        "@@ -1,1 +1,2 @@\n"
        " keep\n"
        "+added\n"
    )
    result = changed_lines(combined)
    assert result == {"kept.py": [2]}


def test_no_newline_marker_does_not_shift_later_lines():
    with_marker = (
        "diff --git a/y.py b/y.py\n"
        "--- a/y.py\n"
        "+++ b/y.py\n"
        "@@ -1,2 +1,3 @@\n"
        " first\n"
        "-old\n"
        "\\ No newline at end of file\n"
        "+new\n"
        "+last\n"
    )
    assert changed_lines(with_marker)["y.py"] == [2, 3]


def test_a_new_file_reports_all_its_lines():
    added_file = (
        "diff --git a/fresh.py b/fresh.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/fresh.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+alpha\n"
        "+beta\n"
    )
    assert changed_lines(added_file)["fresh.py"] == [1, 2]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_diff_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.diffing'`

- [ ] **Step 3: Write the parser**

`src/chesterton/diffing/__init__.py` — empty.

`src/chesterton/diffing/parse.py`:

```python
"""Unified-diff parsing, delegated to unidiff (MIT).

Chesterton mutates the PATCH, so every line number here is a post-patch
(new file) coordinate. A hand-rolled parser was tried and rejected: it
recorded phantom added lines for deleted files and drifted by one line on
`\\ No newline at end of file`. Both corrupt line numbers with no visible
failure, and the spec treats that as the catastrophic case.

Deleted and binary files contribute nothing — there is no post-patch line
to mutate.
"""

from __future__ import annotations

from unidiff import PatchSet

from chesterton.paths import normalise_path


def changed_lines(diff: str) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}

    for patched_file in PatchSet(diff):
        if patched_file.is_binary_file or patched_file.is_removed_file:
            continue

        lines = [
            line.target_line_no
            for hunk in patched_file
            for line in hunk
            if line.is_added and line.target_line_no is not None
        ]
        result[normalise_path(patched_file.path)] = lines

    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_diff_parse.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/diffing tests/test_diff_parse.py
git commit -m "feat: parse unified diffs with unidiff into post-patch line numbers"
```

---

### Task 5: Group changed lines into semantic hunks

**[FIX] RESTRUCTURED — widest-first selection is replaced with tightest-fit
plus a bounded one-level expansion.** Widest-first was introduced to make a
changed line inside `if not user: raise ...` expand to the whole guard clause.
It did — and also made any line inside a 200-line `try` block expand to the
entire `try`, producing hunks nothing can usefully mutate. Tightest-fit with a
guard-shaped parent expansion capped at `MAX_HUNK_LINES` gets the guard without
swallowing the block. `ast.ExceptHandler` is tracked explicitly because it is
not an `ast.stmt` subclass, so without it every `except` header line expanded
to its whole `Try`.

**Files:**
- Create: `src/chesterton/diffing/semantic.py`
- Test: `tests/test_diff_semantic.py`

**Interfaces:**
- Consumes: `changed_lines` output from Task 4, `Hunk` from Task 3.
- Produces: `semantic_hunks(source: str, path: str, lines: Sequence[int]) -> list[Hunk]`; `MAX_HUNK_LINES: int`.

- [ ] **Step 1: Write the failing test**

`tests/test_diff_semantic.py`:

```python
from chesterton.diffing.semantic import semantic_hunks

SOURCE = '''\
def get_user(user_id):
    if not user_id:
        raise ValueError("required")
    return _db.fetch(user_id)


def list_users(limit):
    rows = _db.fetch_all()
    return rows[:limit]
'''

BIG_TRY = "def f():\n    try:\n" + "".join(
    f"        step_{i}()\n" for i in range(60)
) + "    except ValueError:\n        handle()\n"

DECORATED = '''\
@rate_limit(10)
def charge(amount):
    return _gateway.charge(amount)
'''


def test_a_changed_line_expands_to_its_guard_clause():
    # Line 3 is the raise inside the if on line 2; the guard spans 2-3.
    hunks = semantic_hunks(SOURCE, "users.py", [3])
    assert len(hunks) == 1
    assert (hunks[0].start_line, hunks[0].end_line) == (2, 3)


def test_adjacent_lines_in_one_guard_produce_one_hunk():
    assert len(semantic_hunks(SOURCE, "users.py", [2, 3])) == 1


def test_lines_in_different_functions_produce_separate_hunks():
    hunks = semantic_hunks(SOURCE, "users.py", [4, 8])
    assert len(hunks) == 2
    assert {h.start_line for h in hunks} == {4, 8}


def test_a_line_inside_a_large_try_does_not_swallow_the_block():
    # step_30() is at line 32; the enclosing try is far over the cap.
    hunks = semantic_hunks(BIG_TRY, "big.py", [32])
    assert len(hunks) == 1
    assert hunks[0].end_line - hunks[0].start_line + 1 <= 3


def test_an_except_header_maps_to_the_handler_not_the_whole_try():
    except_line = BIG_TRY.splitlines().index("    except ValueError:") + 1
    hunks = semantic_hunks(BIG_TRY, "big.py", [except_line])
    assert hunks[0].start_line == except_line


def test_a_decorator_line_yields_a_single_line_hunk():
    # Stripping @rate_limit means deleting exactly that line.
    hunks = semantic_hunks(DECORATED, "pay.py", [1])
    assert (hunks[0].start_line, hunks[0].end_line) == (1, 1)


def test_unparseable_source_falls_back_to_one_hunk_per_line():
    hunks = semantic_hunks("def broken(:\n", "x.py", [1])
    assert (hunks[0].start_line, hunks[0].end_line) == (1, 1)


def test_a_line_outside_any_statement_still_yields_a_hunk():
    hunks = semantic_hunks(SOURCE, "users.py", [5])
    assert (hunks[0].start_line, hunks[0].end_line) == (5, 5)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_diff_semantic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.diffing.semantic'`

- [ ] **Step 3: Write the grouper**

`src/chesterton/diffing/semantic.py`:

```python
"""Group changed lines into whole statements.

Mutating half a statement produces garbage, and reformatting-only hunks waste
sandbox forks. Two rules, and the tension between them is the whole design:

1. Tightest fit. A changed line maps to the SMALLEST statement containing it.
2. One bounded expansion. If that statement's parent is guard-shaped (if,
   while, for, with, try) and the parent is at most MAX_HUNK_LINES long,
   expand once. That turns a bare `raise` into the whole `if not user: raise`
   guard — the spec's headline mutation operator — without letting a line
   inside a 200-line try block swallow the entire block.

Function and class bodies are never candidates; they would swallow everything.
Decorators are not statements at all, so a changed decorator line falls through
to a single-line hunk, which is exactly what stripping @rate_limit needs.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence

from chesterton.models import Hunk

#: Bodies too coarse to ever be a hunk.
_TOO_COARSE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

#: Parents worth expanding into — these are the guard shapes.
_GUARD_PARENTS = (
    ast.If,
    ast.While,
    ast.For,
    ast.AsyncFor,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.ExceptHandler,
)

#: An expansion wider than this stops being a reviewable unit.
MAX_HUNK_LINES = 12


def _span(node: ast.AST) -> tuple[int, int]:
    start = node.lineno
    return start, getattr(node, "end_lineno", None) or start


def _candidates(source: str) -> list[tuple[int, int, ast.AST]]:
    """(start, end, parent) for every mutable statement, plus except handlers.

    ExceptHandler is included explicitly: it is not an ast.stmt subclass, so
    without it an `except X:` header line finds no tighter span than the whole
    Try and expands to the entire block.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: list[tuple[int, int, ast.AST]] = []
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            is_stmt = isinstance(child, ast.stmt) and not isinstance(
                child, _TOO_COARSE
            )
            if not (is_stmt or isinstance(child, ast.ExceptHandler)):
                continue
            start, end = _span(child)
            found.append((start, end, parent))
    return found


def _resolve(line: int, candidates: list[tuple[int, int, ast.AST]]) -> tuple[int, int]:
    containing = [c for c in candidates if c[0] <= line <= c[1]]
    if not containing:
        return line, line

    start, end, parent = min(containing, key=lambda c: c[1] - c[0])

    if isinstance(parent, _GUARD_PARENTS):
        p_start, p_end = _span(parent)
        if p_end - p_start + 1 <= MAX_HUNK_LINES:
            return p_start, p_end

    return start, end


def semantic_hunks(source: str, path: str, lines: Sequence[int]) -> list[Hunk]:
    candidates = _candidates(source)
    spans = {_resolve(line, candidates) for line in lines}

    # Tightest-fit can select nested spans for different lines; keep only the
    # outermost of any nested pair so hunks do not overlap.
    kept = [
        span
        for span in spans
        if not any(
            other != span and other[0] <= span[0] and span[1] <= other[1]
            for other in spans
        )
    ]

    return [Hunk(file=path, start_line=s, end_line=e) for s, e in sorted(kept)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_diff_semantic.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/diffing/semantic.py tests/test_diff_semantic.py
git commit -m "feat: group changed lines into semantic hunks with bounded guard expansion"
```

---

### Task 6: Invert coverage contexts into a line-to-tests map

**[FIX] Two corrections.** The pytest-cov flag is `--cov-context=test`, not
`--cov-context=test_function` — the latter is coverage.py's `dynamic_context`
*setting* value, a different config surface, and the wrong one errors out the
baseline capture. And paths are now normalised to forward slashes on ingest:
coverage.py records native separators, so on Windows every lookup from Task 7
would miss and every hunk would appear uncovered, silently.

**Files:**
- Create: `src/chesterton/covmap/__init__.py`
- Create: `src/chesterton/covmap/invert.py`
- Create: `tests/fixtures/coverage.json`
- Test: `tests/test_covmap_invert.py`

**Interfaces:**
- Consumes: `CoverageMap` and `normalise_path` from Task 3.
- Produces: `invert_coverage(report: dict) -> CoverageMap`; `load_coverage(path: Path) -> CoverageMap`; `COVERAGE_CAPTURE_COMMANDS: tuple[str, str]`.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/coverage.json` — note the **backslash path**, which is what
coverage.py emits on Windows and the reason normalisation exists:

```json
{
  "files": {
    "widgets/users.py": {
      "contexts": {
        "1": ["tests/test_users.py::test_get_user|run"],
        "2": [
          "tests/test_users.py::test_get_user|run",
          "tests/test_users.py::test_rejects_blank|run"
        ],
        "8": [""],
        "9": ["tests/test_users.py::test_list_users|run"]
      }
    },
    "widgets\\billing.py": {
      "contexts": {
        "4": ["tests/test_billing.py::test_charge|run"]
      }
    }
  }
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_covmap_invert.py`:

```python
import json
from pathlib import Path

from chesterton.covmap.invert import (
    COVERAGE_CAPTURE_COMMANDS,
    invert_coverage,
    load_coverage,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = json.loads((FIXTURES / "coverage.json").read_text())


def test_maps_a_line_to_the_tests_that_execute_it():
    covmap = invert_coverage(REPORT)
    assert covmap["widgets/users.py"][2] == [
        "tests/test_users.py::test_get_user",
        "tests/test_users.py::test_rejects_blank",
    ]


def test_strips_the_phase_suffix_from_context_names():
    covmap = invert_coverage(REPORT)
    assert all(
        "|" not in test
        for tests in covmap["widgets/users.py"].values()
        for test in tests
    )


def test_drops_the_empty_context_which_means_no_test():
    assert invert_coverage(REPORT)["widgets/users.py"].get(8, []) == []


def test_line_numbers_are_integers_not_strings():
    covmap = invert_coverage(REPORT)
    assert all(isinstance(line, int) for line in covmap["widgets/users.py"])


def test_windows_paths_are_normalised_to_forward_slashes():
    # coverage.py emits native separators; GitHub diffs never do. Without
    # this, every lookup misses and every hunk looks uncovered.
    covmap = invert_coverage(REPORT)
    assert "widgets/billing.py" in covmap
    assert "widgets\\billing.py" not in covmap
    assert covmap["widgets/billing.py"][4] == ["tests/test_billing.py::test_charge"]


def test_load_coverage_reads_from_disk():
    covmap = load_coverage(FIXTURES / "coverage.json")
    assert covmap["widgets/users.py"][9] == ["tests/test_users.py::test_list_users"]


def test_the_documented_capture_command_uses_the_real_pytest_cov_flag():
    # --cov-context=test_function is coverage.py's dynamic_context setting,
    # not a pytest-cov flag value. Using it errors the baseline capture.
    assert "--cov-context=test" in COVERAGE_CAPTURE_COMMANDS[0]
    assert "test_function" not in COVERAGE_CAPTURE_COMMANDS[0]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_covmap_invert.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.covmap'`

- [ ] **Step 4: Write the inverter**

`src/chesterton/covmap/__init__.py` — empty.

`src/chesterton/covmap/invert.py`:

```python
"""Turn a coverage contexts report into {file: {line: [test ids]}}.

The capture is two commands, run single-threaded inside the baseline
checkpoint. Dynamic contexts are unreliable under pytest-xdist.

Note the flag: pytest-cov takes `--cov-context=test`. `test_function` is
coverage.py's own `dynamic_context` setting value and is not valid here.

The empty-string context means "executed outside any test", which for our
purposes is the same as undefended.
"""

from __future__ import annotations

import json
from pathlib import Path

from chesterton.models import CoverageMap
from chesterton.paths import normalise_path

COVERAGE_CAPTURE_COMMANDS = (
    "pytest --cov --cov-context=test -p no:randomly",
    "coverage json --show-contexts -o coverage.json",
)


def _clean(context: str) -> str | None:
    """'tests/t.py::test_x|run' -> 'tests/t.py::test_x'; '' -> None."""
    name = context.split("|", 1)[0]
    return name or None


def invert_coverage(report: dict) -> CoverageMap:
    covmap: CoverageMap = {}
    for path, file_report in report.get("files", {}).items():
        lines: dict[int, list[str]] = {}
        for line_str, contexts in file_report.get("contexts", {}).items():
            cleaned = [name for name in (_clean(c) for c in contexts) if name]
            lines[int(line_str)] = sorted(set(cleaned))
        covmap[normalise_path(path)] = lines
    return covmap


def load_coverage(path: Path) -> CoverageMap:
    return invert_coverage(json.loads(Path(path).read_text()))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_covmap_invert.py -v`
Expected: PASS — 7 passed

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/covmap tests/fixtures/coverage.json tests/test_covmap_invert.py
git commit -m "feat: invert coverage contexts into a normalised line-to-tests map"
```

---

### Task 7: Join hunks to coverage — the phase deliverable

**[FIX] Two corrections.** `select_tests` returned a flat union across every
hunk, but each mutant targets **one** hunk and must run only that hunk's tests
— the union would run the whole suite per mutant and destroy the performance
lever this phase exists to build. And `is_uncovered` was true only when *every*
line in a hunk was uncovered, hiding per-line tier-0 findings; it is renamed
`fully_uncovered`, and tier-0 findings are emitted per uncovered line.

**Files:**
- Create: `src/chesterton/defended.py`
- Test: `tests/test_defended.py`

**Interfaces:**
- Consumes: `Hunk`, `CoverageMap` (Task 3), `semantic_hunks` (Task 5), `invert_coverage` (Task 6).
- Produces: `HunkDefence(hunk, tests, uncovered_lines)` with `.fully_uncovered: bool`; `defended_hunks(hunks, covmap) -> list[HunkDefence]`; `tests_for_hunk(hunk, covmap) -> list[str]`; `uncovered_findings(hunks, covmap) -> list[tuple[str, int]]`.

- [ ] **Step 1: Write the failing test**

`tests/test_defended.py`:

```python
from chesterton.defended import (
    defended_hunks,
    tests_for_hunk,
    uncovered_findings,
)
from chesterton.models import Hunk

COVMAP = {
    "users.py": {
        2: ["tests/test_users.py::test_get_user"],
        3: ["tests/test_users.py::test_get_user", "tests/test_users.py::test_blank"],
        8: [],
    }
}


def test_collects_the_union_of_tests_covering_a_hunk():
    result = defended_hunks([Hunk("users.py", 2, 3)], COVMAP)
    assert result[0].tests == [
        "tests/test_users.py::test_blank",
        "tests/test_users.py::test_get_user",
    ]


def test_reports_lines_no_test_executes():
    result = defended_hunks([Hunk("users.py", 8, 8)], COVMAP)
    assert result[0].uncovered_lines == [8]
    assert result[0].fully_uncovered is True


def test_a_line_absent_from_the_map_counts_as_uncovered():
    result = defended_hunks([Hunk("users.py", 99, 99)], COVMAP)
    assert result[0].uncovered_lines == [99]


def test_a_hunk_in_an_unknown_file_is_entirely_uncovered():
    result = defended_hunks([Hunk("ghost.py", 1, 2)], COVMAP)
    assert result[0].uncovered_lines == [1, 2]
    assert result[0].tests == []


def test_a_partly_covered_hunk_is_not_fully_uncovered():
    result = defended_hunks([Hunk("users.py", 2, 8)], COVMAP)
    assert result[0].fully_uncovered is False
    assert result[0].uncovered_lines == [4, 5, 6, 7, 8]


def test_tier_zero_findings_are_reported_per_line_not_per_hunk():
    # A partly covered hunk still contains undefended lines, and each one is
    # a finding. Rolling them into one boolean hides most of them.
    findings = uncovered_findings([Hunk("users.py", 2, 8)], COVMAP)
    assert findings == [
        ("users.py", 4),
        ("users.py", 5),
        ("users.py", 6),
        ("users.py", 7),
        ("users.py", 8),
    ]


def test_tests_are_selected_per_hunk_not_unioned_across_hunks():
    # Each mutant targets ONE hunk and must run only that hunk's tests.
    assert tests_for_hunk(Hunk("users.py", 2, 2), COVMAP) == [
        "tests/test_users.py::test_get_user"
    ]
    assert tests_for_hunk(Hunk("users.py", 3, 3), COVMAP) == [
        "tests/test_users.py::test_blank",
        "tests/test_users.py::test_get_user",
    ]


def test_an_empty_hunk_list_yields_no_defences_and_no_findings():
    assert defended_hunks([], COVMAP) == []
    assert uncovered_findings([], COVMAP) == []


def test_an_empty_coverage_map_makes_everything_uncovered():
    result = defended_hunks([Hunk("users.py", 1, 2)], {})
    assert result[0].uncovered_lines == [1, 2]
    assert result[0].fully_uncovered is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_defended.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.defended'`

- [ ] **Step 3: Write the join**

`src/chesterton/defended.py`:

```python
"""Which tests, if any, defend each changed hunk.

Every changed line with no covering test is a tier-0 finding from the spec's
evidence ladder: undefended without running anything, at zero sandbox cost.
Findings are per LINE, not per hunk — a hunk where only the guard-clause line
is uncovered still contains a real finding, and a hunk-level boolean would
hide it.

Test selection is per HUNK. Each mutant changes one hunk and must run only
the tests that execute it; unioning across hunks would run the whole suite
per mutant and throw away the reason coverage contexts were captured at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from chesterton.models import CoverageMap, Hunk


@dataclass(frozen=True)
class HunkDefence:
    hunk: Hunk
    tests: list[str]
    uncovered_lines: list[int]

    @property
    def fully_uncovered(self) -> bool:
        """True when NO line in the hunk is executed by any test."""
        return len(self.uncovered_lines) == len(self.hunk.lines)


def _defence(hunk: Hunk, covmap: CoverageMap) -> HunkDefence:
    by_line = covmap.get(hunk.file, {})
    tests: set[str] = set()
    uncovered: list[int] = []

    for line in hunk.lines:
        covering = by_line.get(line, [])
        if covering:
            tests.update(covering)
        else:
            uncovered.append(line)

    return HunkDefence(hunk=hunk, tests=sorted(tests), uncovered_lines=uncovered)


def defended_hunks(
    hunks: Sequence[Hunk], covmap: CoverageMap
) -> list[HunkDefence]:
    return [_defence(hunk, covmap) for hunk in hunks]


def tests_for_hunk(hunk: Hunk, covmap: CoverageMap) -> list[str]:
    """The tests one mutant of this hunk must run. Never a cross-hunk union."""
    return _defence(hunk, covmap).tests


def uncovered_findings(
    hunks: Sequence[Hunk], covmap: CoverageMap
) -> list[tuple[str, int]]:
    """Tier-0 findings: (file, line) for every changed line no test executes."""
    return [
        (defence.hunk.file, line)
        for defence in defended_hunks(hunks, covmap)
        for line in defence.uncovered_lines
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_defended.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS — 51 passed

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/defended.py tests/test_defended.py
git commit -m "feat: join semantic hunks to coverage with per-hunk test selection"
```

---

## Phase 1 Done When

- `pytest` is green with no network access (51 tests).
- `scripts/spike_fanout.py` exists and parses. The live run is deferred until
  `NEBIUS_API_KEY` exists; when it runs, all four numbers go into spec §15.
- Given a PR URL, source at head, and a coverage report, `uncovered_findings`
  returns the tier-0 findings with no sandbox involved.

## Follow-on Plans

Written after the spike result is known, because the fan-out number changes
the tier design:

- **Phase 2 — Analysis tiers.** LibCST mutation operators and the validation
  gate; Nemotron Nano semantic mutant generation; CrossHair `diffbehavior`
  tier 1; Hypothesis `ghostwriter.equivalent()` tier 1b; tier routing.
- **Phase 3 — Execution and reduction.** The seed pipeline: build and tag the
  baseline checkpoint, run the base suite three times, and exclude flaky tests
  from selection (spec §4 build-time step 4). Then semaphore-bounded fan-out
  over the real runner; ddmin over hunks; the budget guard.
- **Phase 4 — Triage and review.** Deterministic equivalence pre-filter;
  Nemotron Super classification with abstention; regression-test generation
  and two-way execution verification.
- **Phase 5 — Product surface.** FastAPI, SSE event log, the diff-hero UI,
  swimlanes, warm-run replay, hosted deploy.
- **Phase 6 — Evidence.** UTBoost benchmark sweep as a Nebius Serverless Job;
  README; demo video.
