# Chesterton Phase 1 — Foundations and Fan-Out Spike

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the offline-testable core — sandbox abstraction, GitHub PR ingest, diff parsing, coverage inversion — and answer the go/no-go question of whether forking a ConTree checkpoint 24 ways is fast enough to feel live.

**Architecture:** Every component is a pure function or a protocol-backed adapter, so the whole pipeline runs offline against a fake sandbox in milliseconds. The real ConTree adapter is one thin implementation of the same protocol, exercised deliberately. The phase deliverable is a function that takes a seeded PR and returns, for each changed line, the tests that defend it — plus a measured fan-out latency number that decides the architecture.

**Tech Stack:** Python 3.12, `httpx`, `libcst`, `coverage`, `pytest`, `pytest-asyncio`, `contree-sdk`.

**Spec:** `docs/superpowers/specs/2026-09-18-chesterton-design.md`

## Global Constraints

- Repository ships under **MIT**. No AGPL dependencies (Mutahunter is AGPL-3.0 — never vendor, copy, or install). Hypothesis is MPL-2.0 and is used unmodified only.
- **Python repositories only.** No JS/TS support.
- Sandbox concurrency is capped at **`asyncio.Semaphore(24)`** — the ConTree beta cap is 50 total simultaneous operations and must leave headroom for retries and a second concurrent visitor.
- A failed or timed-out sandbox operation is **`error`** and is excluded from statistics. It is **never** counted as `killed`.
- The absence of a detected behavioural difference is **never** rendered as "equivalent" — the wording is "no difference found within budget".
- Every persisted checkpoint must be **tagged**; untagged images may be garbage-collected and judging runs six weeks after submission.
- Baseline coverage runs **single-threaded** — `--cov-context=test_function` is unreliable under `pytest-xdist`.
- GitHub diffs are computed against the **merge base**, not `base.sha`. Every line number derives from the merge base.
- No network calls in unit tests. All external responses are recorded fixtures.

---

## File Structure

```
pyproject.toml                          # deps, pytest config, Python 3.12 floor
src/chesterton/
  models.py                             # Hunk, PullRequest, CoverageMap types
  sandbox/protocol.py                   # SandboxRunner Protocol, RunResult
  sandbox/fake.py                       # FakeSandboxRunner for offline tests
  sandbox/contree.py                    # real ConTree adapter
  github/pr.py                          # PR metadata + diff + merge base
  diffing/parse.py                      # unified diff -> changed line numbers
  diffing/semantic.py                   # ast-based hunk grouping
  covmap/invert.py                      # coverage.json -> {file: {line: [tests]}}
  defended.py                           # joins hunks to coverage (phase deliverable)
scripts/spike_fanout.py                 # the go/no-go measurement
tests/fixtures/                         # recorded API responses, diffs, coverage
tests/test_*.py                         # one test module per source module
```

Each module has one responsibility and no knowledge of the others' internals.
`defended.py` is the only place that composes them.

---

### Task 1: Sandbox protocol and fake runner

**Files:**
- Create: `pyproject.toml`
- Create: `src/chesterton/__init__.py`
- Create: `src/chesterton/sandbox/__init__.py`
- Create: `src/chesterton/sandbox/protocol.py`
- Create: `src/chesterton/sandbox/fake.py`
- Test: `tests/test_sandbox_fake.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RunResult(stdout: str, stderr: str, exit_code: int, checkpoint_id: str)`; `SandboxRunner` protocol with `async use_image(ref: str) -> str` and `async run(checkpoint_id: str, shell: str, *, files: Mapping[str, str] | None = None, disposable: bool = True) -> RunResult`; `FakeSandboxRunner(responses: Mapping[str, RunResult] | None = None, latency: float = 0.0)` exposing `.calls: list[tuple[str, str]]`.

- [ ] **Step 1: Create the project scaffold**

`pyproject.toml`:

```toml
[project]
name = "chesterton"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "libcst>=1.4",
    "coverage>=7.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24"]
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

Then run: `python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"`
(on POSIX: `.venv/bin/pip install -e ".[dev]"`)

Create empty `src/chesterton/__init__.py` and `src/chesterton/sandbox/__init__.py`.

- [ ] **Step 2: Write the failing test**

`tests/test_sandbox_fake.py`:

```python
import pytest

from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult


async def test_fake_returns_scripted_result_for_known_command():
    runner = FakeSandboxRunner(
        responses={"pytest -q": RunResult("2 passed", "", 0, "ckpt-1")}
    )
    base = await runner.use_image("python:3.12")

    result = await runner.run(base, "pytest -q")

    assert result.exit_code == 0
    assert result.stdout == "2 passed"


async def test_fake_returns_default_success_for_unscripted_command():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.12")

    result = await runner.run(base, "echo hello")

    assert result.exit_code == 0


async def test_fake_records_every_call_in_order():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.12")

    await runner.run(base, "first")
    await runner.run(base, "second")

    assert runner.calls == [(base, "first"), (base, "second")]


async def test_non_disposable_run_yields_a_new_checkpoint_id():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.12")

    result = await runner.run(base, "pip install -e .", disposable=False)

    assert result.checkpoint_id != base


async def test_disposable_run_does_not_create_a_reusable_checkpoint():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.12")

    result = await runner.run(base, "pytest -q", disposable=True)

    assert result.checkpoint_id == base
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
from typing import Protocol


@dataclass(frozen=True)
class RunResult:
    """The outcome of one command executed inside a sandbox.

    `checkpoint_id` identifies the filesystem state after the command. For a
    disposable run it is the parent's id, because nothing was persisted.
    """

    stdout: str
    stderr: str
    exit_code: int
    checkpoint_id: str


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
        `disposable=False` persists the resulting filesystem as a new checkpoint.
        """
        ...
```

- [ ] **Step 5: Write the fake**

`src/chesterton/sandbox/fake.py`:

```python
"""In-memory SandboxRunner for tests.

Deterministic, instant, and records every call so tests can assert on the
commands the pipeline issued.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Mapping

from chesterton.sandbox.protocol import RunResult


class FakeSandboxRunner:
    def __init__(
        self,
        responses: Mapping[str, RunResult] | None = None,
        latency: float = 0.0,
    ) -> None:
        self._responses = dict(responses or {})
        self._latency = latency
        self._ids = itertools.count(1)
        self.calls: list[tuple[str, str]] = []

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
        if self._latency:
            await asyncio.sleep(self._latency)

        scripted = self._responses.get(shell)
        if scripted is not None:
            return scripted

        new_id = checkpoint_id if disposable else f"ckpt-{next(self._ids)}"
        return RunResult(stdout="", stderr="", exit_code=0, checkpoint_id=new_id)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_fake.py -v`
Expected: PASS — 5 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/chesterton tests/test_sandbox_fake.py
git commit -m "feat: add SandboxRunner protocol and in-memory fake"
```

---

### Task 2: ConTree adapter and the fan-out spike

This task answers the go/no-go question. Do it before anything else that
assumes live fan-out.

**Files:**
- Create: `src/chesterton/sandbox/contree.py`
- Create: `scripts/spike_fanout.py`
- Test: `tests/test_sandbox_contree.py`

**Interfaces:**
- Consumes: `SandboxRunner`, `RunResult` from Task 1.
- Produces: `ConTreeSandboxRunner(api_key: str, base_url: str = "https://api.tokenfactory.nebius.com/sandboxes")` satisfying `SandboxRunner`.

- [ ] **Step 1: Read the SDK's own guide before writing the adapter**

The `contree-sdk` package is weeks old and its docs lag. Run:

```bash
uvx contree-mcp --help
```

Then, in a Python REPL with `CONTREE_API_KEY` set, call the SDK's
`get_guide` equivalent or read
`https://docs.tokenfactory.nebius.com/sandboxes/sdk/python_sdk/branching`.
Confirm the names of `images.use`, `images.oci`, and `run` before coding.
If the SDK surface differs from what this task assumes, adapt the adapter —
the protocol from Task 1 does not change.

- [ ] **Step 2: Write the failing test**

The adapter is tested for shape, not behaviour — real calls cost credits.

`tests/test_sandbox_contree.py`:

```python
import inspect

from chesterton.sandbox.contree import ConTreeSandboxRunner
from chesterton.sandbox.protocol import SandboxRunner


def test_adapter_satisfies_the_protocol():
    assert isinstance(ConTreeSandboxRunner, type)
    assert issubclass(ConTreeSandboxRunner, SandboxRunner) or hasattr(
        ConTreeSandboxRunner, "run"
    )


def test_run_signature_matches_the_protocol():
    sig = inspect.signature(ConTreeSandboxRunner.run)
    params = list(sig.parameters)
    assert params[:3] == ["self", "checkpoint_id", "shell"]
    assert "files" in params
    assert "disposable" in params


def test_defaults_to_the_documented_sandboxes_base_url():
    runner = ConTreeSandboxRunner(api_key="unused")
    assert runner.base_url == "https://api.tokenfactory.nebius.com/sandboxes"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_contree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.sandbox.contree'`

- [ ] **Step 4: Write the adapter**

`src/chesterton/sandbox/contree.py`:

```python
"""Real SandboxRunner backed by Nebius Token Factory Sandboxes (ConTree).

The SDK is young. If its surface shifts, change only this file — the
protocol in protocol.py is the stable boundary.
"""

from __future__ import annotations

from collections.abc import Mapping

from chesterton.sandbox.protocol import RunResult

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes"


class ConTreeSandboxRunner:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self._client = None
        self._sdk = None

    async def _sdk_handle(self):
        if self._sdk is None:
            from contree_client.httpx import ContreeAsyncClient
            from contree_sdk import Contree

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
    ) -> RunResult:
        sdk = await self._sdk_handle()
        image = await sdk.images.use(checkpoint_id, strict=True)
        result = await image.run(
            shell=shell,
            files=dict(files) if files else None,
            disposable=disposable,
        )
        return RunResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            checkpoint_id=result.uuid,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_contree.py -v`
Expected: PASS — 3 passed

- [ ] **Step 6: Write the spike script**

`scripts/spike_fanout.py`:

```python
"""Go/no-go measurement: how long does forking one checkpoint 24 ways take?

Usage:
    python scripts/spike_fanout.py docker://<prebuilt-swe-rebench-image>

Prints per-fork and wall-clock timings. The architecture in the spec assumes
the wall clock for 24 concurrent forks feels live (target: under ~20s).
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time

from chesterton.sandbox.contree import ConTreeSandboxRunner

FANOUT = 24


async def one_fork(runner, checkpoint_id: str, index: int) -> float:
    start = time.perf_counter()
    result = await runner.run(
        checkpoint_id, f"python -c 'print({index})'", disposable=True
    )
    elapsed = time.perf_counter() - start
    if result.exit_code != 0:
        print(f"  fork {index} FAILED: {result.stderr[:200]}")
    return elapsed


async def main(image_ref: str) -> None:
    api_key = os.environ["NEBIUS_API_KEY"]
    runner = ConTreeSandboxRunner(api_key)

    print(f"Resolving {image_ref} ...")
    t0 = time.perf_counter()
    base = await runner.use_image(image_ref)
    print(f"  resolved in {time.perf_counter() - t0:.1f}s -> {base}")

    print("Building baseline checkpoint ...")
    t0 = time.perf_counter()
    prepped = await runner.run(base, "python -c 'print(1)'", disposable=False)
    print(f"  checkpoint built in {time.perf_counter() - t0:.1f}s")

    print(f"Forking {FANOUT} ways ...")
    sem = asyncio.Semaphore(FANOUT)

    async def guarded(i: int) -> float:
        async with sem:
            return await one_fork(runner, prepped.checkpoint_id, i)

    t0 = time.perf_counter()
    timings = await asyncio.gather(*(guarded(i) for i in range(FANOUT)))
    wall = time.perf_counter() - t0

    print(f"\n  wall clock : {wall:.1f}s")
    print(f"  median fork: {statistics.median(timings):.2f}s")
    print(f"  slowest    : {max(timings):.2f}s")
    print(f"\n  VERDICT: {'GO' if wall < 20 else 'REDESIGN — see spec section 15'}")

    await runner.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 7: Run the spike and record the result**

Run: `NEBIUS_API_KEY=... .venv/Scripts/python scripts/spike_fanout.py docker://<image>`

Record the three timings in `docs/superpowers/specs/2026-09-18-chesterton-design.md`
section 15, replacing "This is unmeasured."

**If wall clock exceeds ~20s, stop and revisit the spec before continuing.**
The remaining tasks are still valid — they are all offline — but Phase 2's
tier design depends on this number.

- [ ] **Step 8: Commit**

```bash
git add src/chesterton/sandbox/contree.py scripts/spike_fanout.py tests/test_sandbox_contree.py docs/superpowers/specs
git commit -m "feat: add ConTree sandbox adapter and fan-out spike script"
```

---

### Task 3: GitHub PR ingest with correct merge base

**Files:**
- Create: `src/chesterton/models.py`
- Create: `src/chesterton/github/__init__.py`
- Create: `src/chesterton/github/pr.py`
- Create: `tests/fixtures/pr_meta.json`
- Create: `tests/fixtures/pr_compare.json`
- Create: `tests/fixtures/pr.diff`
- Test: `tests/test_github_pr.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PullRequest` dataclass with fields `owner, repo, number, title, base_sha, head_sha, merge_base_sha, clone_url, diff`; `parse_pr_url(url: str) -> tuple[str, str, int]`; `async fetch_pull_request(owner: str, repo: str, number: int, *, client: httpx.AsyncClient) -> PullRequest`.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/pr_meta.json` — a trimmed `GET /repos/{o}/{r}/pulls/{n}` response:

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

`tests/fixtures/pr_compare.json` — a trimmed `GET /repos/{o}/{r}/compare/{base}...{head}` response. **The merge base differs from `base.sha` — that is the whole point of this task:**

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

from chesterton.github.pr import fetch_pull_request, parse_pr_url

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


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/pulls/42") and "diff" in request.headers.get("accept", ""):
        return httpx.Response(200, text=(FIXTURES / "pr.diff").read_text())
    if path.endswith("/pulls/42"):
        return httpx.Response(200, json=json.loads((FIXTURES / "pr_meta.json").read_text()))
    if "/compare/" in path:
        return httpx.Response(
            200, json=json.loads((FIXTURES / "pr_compare.json").read_text())
        )
    return httpx.Response(404)


async def test_fetch_uses_merge_base_not_base_sha():
    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        pr = await fetch_pull_request("acme", "widgets", 42, client=client)

    assert pr.base_sha == "a" * 40
    assert pr.merge_base_sha == "c" * 40
    assert pr.merge_base_sha != pr.base_sha


async def test_fetch_returns_title_clone_url_and_diff():
    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        pr = await fetch_pull_request("acme", "widgets", 42, client=client)

    assert pr.title == "Speed up user lookup"
    assert pr.clone_url == "https://github.com/acme/widgets.git"
    assert "def get_user" in pr.diff
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_github_pr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.github'`

- [ ] **Step 4: Write the models**

`src/chesterton/models.py`:

```python
"""Shared value types. Frozen dataclasses — nothing here mutates."""

from __future__ import annotations

from dataclasses import dataclass

# file path -> line number -> test ids that execute that line
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

- [ ] **Step 5: Write the ingest**

`src/chesterton/github/__init__.py` — empty.

`src/chesterton/github/pr.py`:

```python
"""Fetch a public pull request with two unauthenticated-capable GETs.

No Octokit, no GitHub App, no OAuth — judges must not install anything.
Set GITHUB_TOKEN in the server environment to lift the 60 req/hr anonymous
limit to 5,000; the token is never required for correctness.
"""

from __future__ import annotations

import os
import re

import httpx

from chesterton.models import PullRequest

API = "https://api.github.com"
_PR_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = _PR_URL.search(url)
    if match is None:
        raise ValueError(f"not a GitHub pull request URL: {url}")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def fetch_pull_request(
    owner: str, repo: str, number: int, *, client: httpx.AsyncClient
) -> PullRequest:
    headers = _auth_headers()

    meta = (
        await client.get(f"{API}/repos/{owner}/{repo}/pulls/{number}", headers=headers)
    ).json()
    base_sha = meta["base"]["sha"]
    head_sha = meta["head"]["sha"]

    # GitHub computes .diff against the MERGE BASE, not base.sha. Using
    # base.sha here puts every downstream mutation on the wrong line.
    compare = (
        await client.get(
            f"{API}/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}",
            headers=headers,
        )
    ).json()
    merge_base_sha = compare["merge_base_commit"]["sha"]

    diff = (
        await client.get(
            f"{API}/repos/{owner}/{repo}/pulls/{number}",
            headers={**headers, "Accept": "application/vnd.github.diff"},
        )
    ).text

    return PullRequest(
        owner=owner,
        repo=repo,
        number=number,
        title=meta["title"],
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base_sha=merge_base_sha,
        clone_url=meta["base"]["repo"]["clone_url"],
        diff=diff,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_github_pr.py -v`
Expected: PASS — 4 passed

- [ ] **Step 7: Commit**

```bash
git add src/chesterton/models.py src/chesterton/github tests/fixtures tests/test_github_pr.py
git commit -m "feat: fetch pull requests using the merge base for line coordinates"
```

---

### Task 4: Parse a unified diff into changed lines

**Files:**
- Create: `src/chesterton/diffing/__init__.py`
- Create: `src/chesterton/diffing/parse.py`
- Test: `tests/test_diff_parse.py`

**Interfaces:**
- Consumes: `tests/fixtures/pr.diff` from Task 3.
- Produces: `changed_lines(diff: str) -> dict[str, list[int]]` returning post-patch line numbers of added lines per file; `deleted_line_counts(diff: str) -> dict[str, int]`.

- [ ] **Step 1: Write the failing test**

`tests/test_diff_parse.py`:

```python
from pathlib import Path

from chesterton.diffing.parse import changed_lines, deleted_line_counts

FIXTURES = Path(__file__).parent / "fixtures"
DIFF = (FIXTURES / "pr.diff").read_text()


def test_reports_added_lines_in_post_patch_coordinates():
    result = changed_lines(DIFF)
    # The second hunk header is @@ -30,3 +29,4 @@ so the new file resumes at
    # line 29: 'rows = _db.fetch_all()' is 29, the added line is 30.
    assert result["widgets/users.py"] == [30]


def test_ignores_context_and_removed_lines():
    result = changed_lines(DIFF)
    assert 10 not in result["widgets/users.py"]
    assert 11 not in result["widgets/users.py"]


def test_counts_deletions_per_file():
    assert deleted_line_counts(DIFF)["widgets/users.py"] == 2


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


def test_ignores_the_plus_plus_plus_file_header():
    result = changed_lines(DIFF)
    assert all(line > 0 for line in result["widgets/users.py"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_diff_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.diffing'`

- [ ] **Step 3: Write the parser**

`src/chesterton/diffing/__init__.py` — empty.

`src/chesterton/diffing/parse.py`:

```python
"""Unified-diff parsing.

Chesterton mutates the PATCH, so every line number here is a post-patch
(new file) coordinate. Deletions are counted but carry no line number,
because the line no longer exists to mutate.
"""

from __future__ import annotations

import re

_FILE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _walk(diff: str):
    """Yield (path, line_no_or_None, kind) for every payload line."""
    path: str | None = None
    new_line = 0

    for raw in diff.splitlines():
        file_match = _FILE.match(raw)
        if file_match:
            path = file_match.group(1)
            continue

        hunk_match = _HUNK.match(raw)
        if hunk_match:
            new_line = int(hunk_match.group(1))
            continue

        if path is None or raw.startswith(("diff --git", "index ", "--- ")):
            continue

        if raw.startswith("+"):
            yield path, new_line, "added"
            new_line += 1
        elif raw.startswith("-"):
            yield path, None, "deleted"
        else:
            new_line += 1


def changed_lines(diff: str) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for path, line_no, kind in _walk(diff):
        result.setdefault(path, [])
        if kind == "added" and line_no is not None:
            result[path].append(line_no)
    return result


def deleted_line_counts(diff: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for path, _line_no, kind in _walk(diff):
        result.setdefault(path, 0)
        if kind == "deleted":
            result[path] += 1
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_diff_parse.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/diffing tests/test_diff_parse.py
git commit -m "feat: parse unified diffs into post-patch changed line numbers"
```

---

### Task 5: Group changed lines into semantic hunks

**Files:**
- Create: `src/chesterton/diffing/semantic.py`
- Test: `tests/test_diff_semantic.py`

**Interfaces:**
- Consumes: `changed_lines` output from Task 4, `Hunk` from Task 3.
- Produces: `semantic_hunks(source: str, path: str, lines: Sequence[int]) -> list[Hunk]`.

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


def test_a_changed_line_expands_to_its_whole_statement():
    # Line 3 is the raise inside the if on line 2; the statement spans 2-3.
    hunks = semantic_hunks(SOURCE, "users.py", [3])
    assert len(hunks) == 1
    assert hunks[0].start_line == 2
    assert hunks[0].end_line == 3


def test_adjacent_lines_in_one_statement_produce_one_hunk():
    hunks = semantic_hunks(SOURCE, "users.py", [2, 3])
    assert len(hunks) == 1


def test_lines_in_different_functions_produce_separate_hunks():
    hunks = semantic_hunks(SOURCE, "users.py", [4, 8])
    assert len(hunks) == 2
    assert {h.start_line for h in hunks} == {4, 8}


def test_unparseable_source_falls_back_to_one_hunk_per_line():
    hunks = semantic_hunks("def broken(:\n", "x.py", [1])
    assert len(hunks) == 1
    assert hunks[0].start_line == 1
    assert hunks[0].end_line == 1


def test_a_line_outside_any_statement_still_yields_a_hunk():
    hunks = semantic_hunks(SOURCE, "users.py", [5])
    assert len(hunks) == 1
    assert hunks[0].start_line == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_diff_semantic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.diffing.semantic'`

- [ ] **Step 3: Write the grouper**

`src/chesterton/diffing/semantic.py`:

```python
"""Group changed lines into whole statements.

Mutating half a statement produces garbage, and reformatting-only hunks
waste sandbox forks. The stdlib `ast` module is enough here — no dependency.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence

from chesterton.models import Hunk


#: Too coarse to be useful as a hunk — a whole function would swallow the diff.
_TOO_COARSE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _statement_spans(source: str) -> list[tuple[int, int]]:
    """Every statement's (start, end) line span, widest first.

    Widest-first matters: a line inside `if not user_id: raise ...` should
    expand to the whole guard clause, not to the bare `raise`. Deleting a
    guard is the operator we care most about, and half a guard is garbage.
    Function and class bodies are excluded — they would swallow everything.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or isinstance(node, _TOO_COARSE):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        spans.append((node.lineno, end))

    spans.sort(key=lambda span: span[1] - span[0], reverse=True)
    return spans


def semantic_hunks(source: str, path: str, lines: Sequence[int]) -> list[Hunk]:
    spans = _statement_spans(source)

    expanded: set[tuple[int, int]] = set()
    for line in lines:
        enclosing = next(
            (span for span in spans if span[0] <= line <= span[1]), (line, line)
        )
        expanded.add(enclosing)

    # Drop spans fully contained in another selected span.
    kept = [
        span
        for span in expanded
        if not any(
            other != span and other[0] <= span[0] and span[1] <= other[1]
            for other in expanded
        )
    ]

    return [
        Hunk(file=path, start_line=start, end_line=end)
        for start, end in sorted(kept)
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_diff_semantic.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/diffing/semantic.py tests/test_diff_semantic.py
git commit -m "feat: group changed lines into semantic statement hunks"
```

---

### Task 6: Invert coverage contexts into a line-to-tests map

**Files:**
- Create: `src/chesterton/covmap/__init__.py`
- Create: `src/chesterton/covmap/invert.py`
- Create: `tests/fixtures/coverage.json`
- Test: `tests/test_covmap_invert.py`

**Interfaces:**
- Consumes: `CoverageMap` type from Task 3.
- Produces: `invert_coverage(report: dict) -> CoverageMap`; `load_coverage(path: Path) -> CoverageMap`.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/coverage.json` — the shape `coverage json --show-contexts` emits:

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
    }
  }
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_covmap_invert.py`:

```python
import json
from pathlib import Path

from chesterton.covmap.invert import invert_coverage, load_coverage

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = json.loads((FIXTURES / "coverage.json").read_text())


def test_maps_a_line_to_the_tests_that_execute_it():
    covmap = invert_coverage(REPORT)
    assert covmap["widgets/users.py"][2] == [
        "tests/test_users.py::test_get_user",
        "tests/test_users.py::test_rejects_blank",
    ]


def test_strips_the_run_suffix_from_context_names():
    covmap = invert_coverage(REPORT)
    assert all(
        "|" not in test
        for tests in covmap["widgets/users.py"].values()
        for test in tests
    )


def test_drops_the_empty_context_which_means_no_test():
    covmap = invert_coverage(REPORT)
    assert covmap["widgets/users.py"].get(8, []) == []


def test_line_numbers_are_integers_not_strings():
    covmap = invert_coverage(REPORT)
    assert all(isinstance(line, int) for line in covmap["widgets/users.py"])


def test_load_coverage_reads_from_disk():
    covmap = load_coverage(FIXTURES / "coverage.json")
    assert covmap["widgets/users.py"][9] == ["tests/test_users.py::test_list_users"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_covmap_invert.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.covmap'`

- [ ] **Step 4: Write the inverter**

`src/chesterton/covmap/__init__.py` — empty.

`src/chesterton/covmap/invert.py`:

```python
"""Turn a coverage contexts report into {file: {line: [test ids]}}.

Produced by:  pytest --cov --cov-context=test_function
              coverage json --show-contexts -o coverage.json

The empty-string context means "executed outside any test", which for our
purposes is the same as undefended.
"""

from __future__ import annotations

import json
from pathlib import Path

from chesterton.models import CoverageMap


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
        covmap[path] = lines
    return covmap


def load_coverage(path: Path) -> CoverageMap:
    return invert_coverage(json.loads(Path(path).read_text()))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_covmap_invert.py -v`
Expected: PASS — 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/covmap tests/fixtures/coverage.json tests/test_covmap_invert.py
git commit -m "feat: invert coverage contexts into a line-to-tests map"
```

---

### Task 7: Join hunks to coverage — the phase deliverable

**Files:**
- Create: `src/chesterton/defended.py`
- Test: `tests/test_defended.py`

**Interfaces:**
- Consumes: `Hunk`, `CoverageMap` (Task 3), `semantic_hunks` (Task 5), `invert_coverage` (Task 6).
- Produces: `HunkDefence(hunk: Hunk, tests: list[str], uncovered_lines: list[int])` with property `is_uncovered: bool`; `defended_hunks(hunks: Sequence[Hunk], covmap: CoverageMap) -> list[HunkDefence]`; `select_tests(hunks, covmap) -> list[str]`.

- [ ] **Step 1: Write the failing test**

`tests/test_defended.py`:

```python
from chesterton.defended import HunkDefence, defended_hunks, select_tests
from chesterton.models import Hunk

COVMAP = {
    "users.py": {
        2: ["tests/test_users.py::test_get_user"],
        3: ["tests/test_users.py::test_get_user", "tests/test_users.py::test_blank"],
        8: [],
    }
}


def test_collects_the_union_of_tests_covering_a_hunk():
    hunks = [Hunk("users.py", 2, 3)]
    result = defended_hunks(hunks, COVMAP)
    assert result[0].tests == [
        "tests/test_users.py::test_blank",
        "tests/test_users.py::test_get_user",
    ]


def test_reports_lines_no_test_executes():
    hunks = [Hunk("users.py", 8, 8)]
    result = defended_hunks(hunks, COVMAP)
    assert result[0].uncovered_lines == [8]
    assert result[0].is_uncovered is True


def test_a_line_absent_from_the_map_counts_as_uncovered():
    hunks = [Hunk("users.py", 99, 99)]
    result = defended_hunks(hunks, COVMAP)
    assert result[0].uncovered_lines == [99]


def test_a_hunk_in_an_unknown_file_is_entirely_uncovered():
    hunks = [Hunk("ghost.py", 1, 2)]
    result = defended_hunks(hunks, COVMAP)
    assert result[0].uncovered_lines == [1, 2]
    assert result[0].tests == []


def test_a_partly_covered_hunk_is_not_flagged_uncovered():
    hunks = [Hunk("users.py", 2, 8)]
    result = defended_hunks(hunks, COVMAP)
    assert result[0].is_uncovered is False
    assert result[0].uncovered_lines == [4, 5, 6, 7, 8]


def test_select_tests_deduplicates_across_hunks():
    hunks = [Hunk("users.py", 2, 2), Hunk("users.py", 3, 3)]
    assert select_tests(hunks, COVMAP) == [
        "tests/test_users.py::test_blank",
        "tests/test_users.py::test_get_user",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_defended.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.defended'`

- [ ] **Step 3: Write the join**

`src/chesterton/defended.py`:

```python
"""Which tests, if any, defend each changed hunk.

A hunk with no covering tests is tier 0 in the spec's evidence ladder: it is
undefended without running anything, at zero sandbox cost.
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
    def is_uncovered(self) -> bool:
        """True when NO line in the hunk is executed by any test."""
        return len(self.uncovered_lines) == len(self.hunk.lines)


def defended_hunks(
    hunks: Sequence[Hunk], covmap: CoverageMap
) -> list[HunkDefence]:
    results: list[HunkDefence] = []
    for hunk in hunks:
        by_line = covmap.get(hunk.file, {})
        tests: set[str] = set()
        uncovered: list[int] = []

        for line in hunk.lines:
            covering = by_line.get(line, [])
            if covering:
                tests.update(covering)
            else:
                uncovered.append(line)

        results.append(
            HunkDefence(hunk=hunk, tests=sorted(tests), uncovered_lines=uncovered)
        )
    return results


def select_tests(hunks: Sequence[Hunk], covmap: CoverageMap) -> list[str]:
    """The deduplicated test set to run for a mutant touching these hunks."""
    selected: set[str] = set()
    for defence in defended_hunks(hunks, covmap):
        selected.update(defence.tests)
    return sorted(selected)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_defended.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS — 33 passed

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/defended.py tests/test_defended.py
git commit -m "feat: join semantic hunks to coverage to find undefended lines"
```

---

## Phase 1 Done When

- `pytest` is green with no network access.
- `scripts/spike_fanout.py` has produced a recorded wall-clock number, written
  into spec section 15.
- Given a PR URL, source at head, and a coverage report, `defended_hunks`
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
