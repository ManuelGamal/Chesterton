# Chesterton Phase 2 — Mutation Generation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a PR's semantic hunks into a validated, budgeted set of mutants — the candidates the fan-out will execute — without touching a real sandbox.

**Architecture:** Deterministic LibCST operators and Nemotron-proposed semantic mutations feed one validation gate, which rejects anything unparseable, unchanged, or duplicate before it can cost a sandbox operation. Everything runs offline against the fake runner and recorded model responses; the only live dependency is a measurement spike at the end.

**Tech Stack:** Python 3.13, `libcst`, `openai` (against Token Factory), `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-18-chesterton-design.md`

**Builds on:** Phase 1 (merged, `112bfd2`). `changed_lines`, `semantic_hunks`, `covering_tests`, `uncovered_findings`, `SandboxRunner`/`FakeSandboxRunner` all exist and are verified live.

## Global Constraints

- Repository ships under **MIT**. No AGPL dependencies. `unidiff` is MIT, Hypothesis is MPL-2.0; both used unmodified.
- **Python repositories only.**
- Sandbox concurrency is capped at **`asyncio.Semaphore(24)`** — measured safe, 72/72 successful across three rounds.
- A failed or timed-out sandbox operation is **`error`**, excluded from statistics, and **never** counted as `killed`.
- The absence of a detected behavioural difference is **never** rendered as "equivalent" — the wording is "no difference found within budget".
- Every persisted checkpoint must be **tagged**.
- **All file paths are normalised to forward slashes at every boundary.**
- **A disposable run has no reusable checkpoint** (`checkpoint_id is None`).
- No network calls in unit tests. All external responses are recorded fixtures.
- **No public symbol a test module imports may begin with `test`** — pytest's `python_functions` glob is `test*` and will collect it as a test case.
- **Reasoning is ON by default and costs real tokens** (64 for a trivial reply). Set `enable_thinking: false` on every call whose output a parser consumes.
- **Never parse a response whose `finish_reason` is `"length"`** — a call truncated mid-reasoning returns partial thoughts as content.

## Confirmed model IDs (verified live 2026-09-18)

Casing differs between all three. Copy verbatim.

| Tier | Model ID | Context |
|---|---|---|
| execution | `nvidia/Nemotron-3_5-Lightning` | 1,048,576 |
| reasoning | `nvidia/nemotron-3-super-120b-a12b` | 262,144 |
| synthesis | `nvidia/Nemotron-3-Ultra-550b-a55b` | 1,048,576 |

---

## File Structure

```
src/chesterton/
  filters.py                 # which files are worth mutating at all
  sandbox/protocol.py        # MODIFY: timeout, duration_s
  sandbox/fake.py            # MODIFY: record options, synth duration
  sandbox/contree.py         # MODIFY: pass timeout, capture elapsed safely
  mutation/model.py          # Mutant, MutantSource
  mutation/gate.py           # validation gate — the only way a mutant is admitted
  mutation/operators.py      # deterministic LibCST operators
  mutation/generate.py       # orchestration: collect, gate, budget, rank
  llm/client.py              # Nemotron client, thinking off, truncation guard
  llm/mutants.py             # semantic mutant prompting and parsing
scripts/probe_crosshair.py   # measurement spike for Phase 2b
```

---

### Task 1: Widen the sandbox protocol

Closes deferred finding **I2**. The real adapter already takes `tag`; the
protocol and fake do not, so "every checkpoint must be tagged" is the one
constraint the offline fake cannot exercise. Phase 2 is where call sites
multiply, so widen it now. Adding `duration_s` closes the gap the final review
noted: `mutant_result` needs a duration and `RunResult` carries none.

**Files:**
- Modify: `src/chesterton/sandbox/protocol.py`
- Modify: `src/chesterton/sandbox/fake.py`
- Modify: `src/chesterton/sandbox/contree.py`
- Test: `tests/test_sandbox_fake.py`

**Interfaces:**
- Consumes: existing `RunResult`, `SandboxRunner`, `FakeSandboxRunner`.
- Produces: `RunResult(stdout, stderr, exit_code, checkpoint_id, duration_s: float | None = None)`; `SandboxRunner.run(..., tag: str | None = None, timeout: float | None = None)`; `FakeSandboxRunner.options: list[dict]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sandbox_fake.py`:

```python
async def test_the_fake_records_tag_and_timeout():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    await runner.run(base, "pytest -q", tag="chesterton:base", timeout=30.0)

    assert runner.options == [
        {"disposable": True, "tag": "chesterton:base", "timeout": 30.0}
    ]


async def test_a_run_reports_a_duration():
    runner = FakeSandboxRunner()
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "pytest -q")

    assert result.duration_s is not None
    assert result.duration_s >= 0.0


async def test_a_scripted_result_keeps_its_own_duration():
    runner = FakeSandboxRunner(
        responses={"slow": RunResult("", "", 0, None, duration_s=12.5)}
    )
    base = await runner.use_image("python:3.13")

    result = await runner.run(base, "slow")

    assert result.duration_s == 12.5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sandbox_fake.py -q`
Expected: FAIL — `AttributeError: 'FakeSandboxRunner' object has no attribute 'options'`

- [ ] **Step 3: Widen `RunResult` and the protocol**

In `src/chesterton/sandbox/protocol.py`, add the field with a default so every
existing positional construction keeps working:

```python
@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    checkpoint_id: str | None
    #: Wall time of the execution, when the backend reports one. None when the
    #: run errored — a failed operation has no meaningful duration, and the
    #: real SDK raises rather than returning one.
    duration_s: float | None = None
```

and widen the protocol's `run`:

```python
    async def run(
        self,
        checkpoint_id: str,
        shell: str,
        *,
        files: Mapping[str, str] | None = None,
        disposable: bool = True,
        tag: str | None = None,
        timeout: float | None = None,
    ) -> RunResult:
```

Extend its docstring with:

```
        `tag` names the resulting checkpoint so it survives garbage collection.
        `timeout` bounds the execution in seconds.
```

- [ ] **Step 4: Record the options in the fake**

In `src/chesterton/sandbox/fake.py`, add `self.options: list[dict] = []` to
`__init__`, widen `run` to accept `tag` and `timeout`, and record them:

```python
        self.options.append(
            {"disposable": disposable, "tag": tag, "timeout": timeout}
        )
```

Return `duration_s=0.0` on the synthesised result, and leave a scripted result
untouched except for the existing disposable rule.

- [ ] **Step 5: Capture the real duration safely**

In `src/chesterton/sandbox/contree.py`, pass `timeout` through to `image.run`
and capture the elapsed time defensively:

```python
        # ContreeImage.elapsed reads .result.elapsed_time, and .result raises
        # RuntimeError unless the run reached SUCCEEDED. Reading it on a failed
        # run would turn a test failure into a crash.
        duration_s: float | None = None
        try:
            duration_s = result.elapsed.total_seconds()
        except Exception:
            duration_s = None
```

and include `duration_s=duration_s` in the returned `RunResult`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS — 63 passed

- [ ] **Step 7: Commit**

```bash
git add src/chesterton/sandbox tests/test_sandbox_fake.py
git commit -m "feat: widen SandboxRunner with tag, timeout and duration"
```

---

### Task 2: Decide which files are worth mutating

Closes deferred finding **I3**. Without this a README, YAML or lockfile hunk
flows through `semantic_hunks` (which falls back to per-line hunks on a
SyntaxError) and produces confident undefended-line findings on prose.

**Files:**
- Create: `src/chesterton/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_mutable_source(path: str) -> bool`.

- [ ] **Step 1: Write the failing test**

`tests/test_filters.py`:

```python
import pytest

from chesterton.filters import is_mutable_source


@pytest.mark.parametrize(
    "path",
    [
        "widgets/users.py",
        "src/pkg/core.py",
        "a.py",
    ],
)
def test_python_sources_are_mutable(path):
    assert is_mutable_source(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "pyproject.toml",
        "poetry.lock",
        "widgets/data.json",
        "Makefile",
        "",
    ],
)
def test_non_python_files_are_not_mutable(path):
    # A prose hunk would otherwise reach semantic_hunks, fall back to per-line
    # hunks on a SyntaxError, and produce confident findings about a README.
    assert is_mutable_source(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_users.py",
        "widgets/tests/test_core.py",
        "test/test_thing.py",
        "widgets/users_test.py",
        "conftest.py",
        "widgets/conftest.py",
    ],
)
def test_test_files_are_not_mutable(path):
    # Mutating a test and then running that same test is circular: the file
    # covers itself, so the mutant always dies and the finding means nothing.
    assert is_mutable_source(path) is False


def test_a_source_file_merely_containing_test_in_its_name_is_mutable():
    # "latest" and "contest" are not tests. Substring matching would be wrong.
    assert is_mutable_source("widgets/latest_release.py") is True
    assert is_mutable_source("widgets/contest.py") is True


def test_windows_separators_are_handled():
    assert is_mutable_source("widgets\\tests\\test_x.py") is False
    assert is_mutable_source("widgets\\users.py") is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_filters.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.filters'`

- [ ] **Step 3: Write the filter**

`src/chesterton/filters.py`:

```python
"""Which files are worth mutating at all.

Two exclusions, for different reasons.

Non-Python files cannot be parsed, so `semantic_hunks` falls back to one hunk
per line and every changed line of a README becomes a confident "no test
defends this" finding. That is fabricated evidence, which is the one thing
this project must not produce.

Test files are excluded because mutating a test and then running that same
test is circular — the file covers itself, the mutant always dies, and the
result carries no information.
"""

from __future__ import annotations

from chesterton.paths import normalise_path

#: Directory names that mark a test tree.
_TEST_DIRS = {"test", "tests"}


def is_mutable_source(path: str) -> bool:
    if not path:
        return False

    normalised = normalise_path(path)
    if not normalised.endswith(".py"):
        return False

    parts = normalised.split("/")
    name = parts[-1]

    # Whole-segment matching, not substring: "latest_release.py" is not a test.
    if any(part in _TEST_DIRS for part in parts[:-1]):
        return False
    if name == "conftest.py":
        return False
    if name.startswith("test_") or name.endswith("_test.py"):
        return False

    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_filters.py -q`
Expected: PASS — 17 passed

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/filters.py tests/test_filters.py
git commit -m "feat: exclude non-Python and test files from mutation"
```

---

### Task 3: The mutant model and the validation gate

The gate is the only way a mutant becomes eligible for execution. Everything
downstream assumes a mutant has already passed it. A mutant that fails to
compile makes its tests error, which reads as *killed* — a silent false
negative, and the reason this gate is not optional.

**Files:**
- Create: `src/chesterton/mutation/__init__.py`
- Create: `src/chesterton/mutation/model.py`
- Create: `src/chesterton/mutation/gate.py`
- Test: `tests/test_mutation_gate.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Mutant(file, start_line, end_line, operator, original_src, mutated_src, rationale, source)` with `.content_hash: str`; `MutantGate()` with `.admit(mutant: Mutant) -> bool` and `.rejected: dict[str, int]`.

- [ ] **Step 1: Write the failing test**

`tests/test_mutation_gate.py`:

```python
from chesterton.mutation.gate import MutantGate
from chesterton.mutation.model import Mutant


def a_mutant(**overrides) -> Mutant:
    fields = {
        "file": "users.py",
        "start_line": 2,
        "end_line": 3,
        "operator": "strip_decorator",
        "original_src": "x = 1\n",
        "mutated_src": "x = 2\n",
        "rationale": "changed the constant",
        "source": "deterministic",
    }
    fields.update(overrides)
    return Mutant(**fields)


def test_a_well_formed_mutant_is_admitted():
    assert MutantGate().admit(a_mutant()) is True


def test_unparseable_python_is_rejected():
    # A mutant that will not compile makes its tests ERROR, which reads as
    # "killed" — a silent false negative, and the worst outcome available.
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="def broken(:\n")) is False
    assert gate.rejected["unparseable"] == 1


def test_a_mutant_identical_to_the_original_is_rejected():
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="x = 1\n")) is False
    assert gate.rejected["unchanged"] == 1


def test_a_whitespace_only_change_is_rejected():
    # Reformatting is not a mutation; it would burn a sandbox op to prove
    # nothing.
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="x  =  1\n")) is False
    assert gate.rejected["unchanged"] == 1


def test_a_duplicate_mutant_is_rejected_once_seen():
    gate = MutantGate()
    assert gate.admit(a_mutant()) is True
    assert gate.admit(a_mutant(rationale="different words, same code")) is False
    assert gate.rejected["duplicate"] == 1


def test_two_different_mutants_are_both_admitted():
    gate = MutantGate()
    assert gate.admit(a_mutant(mutated_src="x = 2\n")) is True
    assert gate.admit(a_mutant(mutated_src="x = 3\n")) is True
    assert gate.rejected == {}


def test_content_hash_ignores_rationale_and_source():
    # Two generators proposing the same edit are one mutant, not two.
    left = a_mutant(source="deterministic", rationale="a")
    right = a_mutant(source="llm", rationale="b")
    assert left.content_hash == right.content_hash
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mutation_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.mutation'`

- [ ] **Step 3: Write the model**

`src/chesterton/mutation/__init__.py` — empty.

`src/chesterton/mutation/model.py`:

```python
"""What a mutant is.

`content_hash` deliberately covers only the file, the line range and the
mutated code. Two generators proposing the same edit for different stated
reasons are one mutant, and paying for both would waste a sandbox operation
to learn the same thing twice.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

MutantSource = Literal["deterministic", "llm"]


@dataclass(frozen=True)
class Mutant:
    file: str
    start_line: int
    end_line: int
    operator: str
    original_src: str
    mutated_src: str
    rationale: str
    source: MutantSource

    @property
    def content_hash(self) -> str:
        payload = f"{self.file}:{self.start_line}-{self.end_line}:{self.mutated_src}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Write the gate**

`src/chesterton/mutation/gate.py`:

```python
"""The only way a mutant becomes eligible for execution.

Three rejections, cheapest first, each for a concrete reason:

- unparseable: the mutant will not compile, so its tests ERROR, which the
  runner reads as "killed" — a silent false negative;
- unchanged: nothing to learn, and it would still cost a sandbox operation;
- duplicate: the same edit already admitted, from either generator.

Rejections are counted rather than logged so the run can report what it threw
away. A generator quietly producing 90% garbage should be visible.
"""

from __future__ import annotations

import ast

from chesterton.mutation.model import Mutant


def _normalised(source: str) -> str | None:
    """Parsed-and-reprinted source, or None when it does not compile.

    Comparing dumps rather than text means a pure reformatting counts as no
    change, which is exactly what we want — it is not a mutation.
    """
    try:
        return ast.dump(ast.parse(source))
    except SyntaxError:
        return None


class MutantGate:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.rejected: dict[str, int] = {}

    def _reject(self, reason: str) -> bool:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
        return False

    def admit(self, mutant: Mutant) -> bool:
        mutated = _normalised(mutant.mutated_src)
        if mutated is None:
            return self._reject("unparseable")

        original = _normalised(mutant.original_src)
        if original is not None and mutated == original:
            return self._reject("unchanged")

        if mutant.content_hash in self._seen:
            return self._reject("duplicate")

        self._seen.add(mutant.content_hash)
        return True
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_mutation_gate.py -q`
Expected: PASS — 7 passed

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/mutation tests/test_mutation_gate.py
git commit -m "feat: add the mutant model and validation gate"
```

---

### Task 4: Operator framework and replacement operators

Two passes, deliberately. `find_candidates` records every node an operator
could act on; `apply_candidate` rebuilds the module mutating exactly one. A
transformer that mutated every match at once would produce a single unusable
super-mutant that tells you nothing about which change mattered.

**Files:**
- Create: `src/chesterton/mutation/operators.py`
- Test: `tests/test_mutation_operators.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Candidate(operator: str, line: int, description: str)`; `find_candidates(source: str, lines: Sequence[int]) -> list[Candidate]`; `apply_candidate(source: str, candidate: Candidate) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_mutation_operators.py`:

```python
from chesterton.mutation.operators import apply_candidate, find_candidates

DECORATED = '''\
@rate_limit(10)
def charge(amount):
    if amount > 100:
        raise ValueError("too much")
    return amount
'''


def ops_on(source: str, lines: list[int]) -> set[str]:
    return {c.operator for c in find_candidates(source, lines)}


def test_a_decorator_line_offers_a_strip():
    assert "strip_decorator" in ops_on(DECORATED, [1])


def test_stripping_a_decorator_removes_exactly_that_line():
    candidate = next(
        c for c in find_candidates(DECORATED, [1]) if c.operator == "strip_decorator"
    )
    mutated = apply_candidate(DECORATED, candidate)
    assert "@rate_limit" not in mutated
    assert "def charge(amount):" in mutated
    assert "raise ValueError" in mutated


def test_a_condition_offers_an_inversion():
    assert "invert_condition" in ops_on(DECORATED, [3])


def test_inverting_a_condition_negates_the_test():
    candidate = next(
        c for c in find_candidates(DECORATED, [3]) if c.operator == "invert_condition"
    )
    mutated = apply_candidate(DECORATED, candidate)
    assert "if not (amount > 100)" in mutated


def test_a_comparison_offers_an_off_by_one():
    assert "off_by_one" in ops_on(DECORATED, [3])


def test_off_by_one_widens_the_boundary():
    candidate = next(
        c for c in find_candidates(DECORATED, [3]) if c.operator == "off_by_one"
    )
    mutated = apply_candidate(DECORATED, candidate)
    assert "amount >= 100" in mutated


def test_candidates_outside_the_changed_lines_are_ignored():
    # Only the PR's own changes are mutated; the rest of the file is not ours
    # to touch.
    assert find_candidates(DECORATED, [5]) == []


def test_unparseable_source_yields_no_candidates():
    assert find_candidates("def broken(:\n", [1]) == []


def test_every_candidate_carries_a_human_readable_description():
    for candidate in find_candidates(DECORATED, [1, 3]):
        assert candidate.description
        assert candidate.line > 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mutation_operators.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.mutation.operators'`

- [ ] **Step 3: Write the framework and three operators**

`src/chesterton/mutation/operators.py`:

```python
"""Deterministic mutation operators, scoped to changed lines.

Two passes. `find_candidates` walks the module and records every node inside
the target lines an operator can act on. `apply_candidate` then rebuilds the
module mutating exactly one of them. One candidate, one mutant — a transformer
that mutated every match at once would produce a single unusable super-mutant.

LibCST rather than `ast` because it round-trips formatting and comments, so a
mutant differs from its original in exactly one way rather than in one way plus
a reformatting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


@dataclass(frozen=True)
class Candidate:
    operator: str
    line: int
    description: str


#: Boundary flips that produce an off-by-one rather than a negation.
_WIDEN = {
    cst.LessThan: cst.LessThanEqual,
    cst.LessThanEqual: cst.LessThan,
    cst.GreaterThan: cst.GreaterThanEqual,
    cst.GreaterThanEqual: cst.GreaterThan,
}


def _snippet(node: cst.CSTNode) -> str:
    text = cst.Module(body=[]).code_for_node(node).strip()
    return text if len(text) <= 60 else text[:57] + "..."


class _Collector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, lines: set[int]) -> None:
        self.lines = lines
        self.found: list[Candidate] = []

    def _line(self, node: cst.CSTNode) -> int:
        return self.get_metadata(PositionProvider, node).start.line

    def visit_Decorator(self, node: cst.Decorator) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate("strip_decorator", line, f"remove {_snippet(node)}")
            )

    def visit_If(self, node: cst.If) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate(
                    "invert_condition", line, f"negate {_snippet(node.test)}"
                )
            )

    def visit_Comparison(self, node: cst.Comparison) -> None:
        line = self._line(node)
        if line not in self.lines:
            return
        if any(type(c.operator) in _WIDEN for c in node.comparisons):
            self.found.append(
                Candidate("off_by_one", line, f"shift boundary in {_snippet(node)}")
            )


class _Applier(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, target: Candidate) -> None:
        self.target = target
        self.applied = False

    def _hits(self, node: cst.CSTNode, operator: str) -> bool:
        if self.applied or self.target.operator != operator:
            return False
        return self.get_metadata(PositionProvider, node).start.line == self.target.line

    def leave_Decorator(self, original: cst.Decorator, updated: cst.Decorator):
        if self._hits(original, "strip_decorator"):
            self.applied = True
            return cst.RemoveFromParent()
        return updated

    def leave_If(self, original: cst.If, updated: cst.If):
        if self._hits(original, "invert_condition"):
            self.applied = True
            return updated.with_changes(
                test=cst.UnaryOperation(
                    operator=cst.Not(),
                    expression=cst.parse_expression(
                        f"({cst.Module(body=[]).code_for_node(updated.test)})"
                    ),
                )
            )
        return updated

    def leave_Comparison(self, original: cst.Comparison, updated: cst.Comparison):
        if not self._hits(original, "off_by_one"):
            return updated
        self.applied = True
        widened = []
        for target in updated.comparisons:
            replacement = _WIDEN.get(type(target.operator))
            if replacement is not None:
                target = target.with_changes(operator=replacement())
            widened.append(target)
        return updated.with_changes(comparisons=widened)


def find_candidates(source: str, lines: Sequence[int]) -> list[Candidate]:
    try:
        wrapper = MetadataWrapper(cst.parse_module(source))
    except cst.ParserSyntaxError:
        return []

    collector = _Collector(set(lines))
    wrapper.visit(collector)
    return collector.found


def apply_candidate(source: str, candidate: Candidate) -> str:
    wrapper = MetadataWrapper(cst.parse_module(source))
    return wrapper.visit(_Applier(candidate)).code
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_mutation_operators.py -q`
Expected: PASS — 9 passed

**If a test fails, STOP and report it.** Do not weaken the assertion. LibCST's
exact output formatting is the most likely mismatch, and I need to know whether
the expectation or the implementation is wrong.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/mutation/operators.py tests/test_mutation_operators.py
git commit -m "feat: add deterministic mutation operators for decorators, conditions and boundaries"
```

---

### Task 5: Removal operators

The spec's headline operator is *delete a guard clause* — the canonical quiet
deletion an agent makes. These three all remove protection rather than alter
it, which is why they carry the most signal.

**Files:**
- Modify: `src/chesterton/mutation/operators.py`
- Test: `tests/test_mutation_removals.py`

**Interfaces:**
- Consumes: `Candidate`, `find_candidates`, `apply_candidate` from Task 4.
- Produces: three more operator names — `delete_guard`, `drop_await`, `widen_except`.

- [ ] **Step 1: Write the failing test**

`tests/test_mutation_removals.py`:

```python
from chesterton.mutation.operators import apply_candidate, find_candidates

GUARD = '''\
def get_user(user_id):
    if not user_id:
        raise ValueError("required")
    return _db.fetch(user_id)
'''

ASYNC = '''\
async def save(record):
    await _db.write(record)
    return True
'''

NARROW = '''\
def load(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return None
'''

CLEANUP = '''\
def write(path, data):
    fh = open(path, "w")
    try:
        fh.write(data)
    finally:
        fh.close()
'''


def pick(source: str, lines: list[int], operator: str):
    return next(c for c in find_candidates(source, lines) if c.operator == operator)


def test_a_guard_clause_offers_deletion():
    assert apply_candidate(GUARD, pick(GUARD, [2], "delete_guard")) != GUARD


def test_deleting_a_guard_removes_the_whole_clause_not_half_of_it():
    # Half a guard is invalid Python. The gate would reject it, so this
    # operator would silently produce nothing.
    mutated = apply_candidate(GUARD, pick(GUARD, [2], "delete_guard"))
    assert "if not user_id" not in mutated
    assert "raise ValueError" not in mutated
    assert "return _db.fetch(user_id)" in mutated


def test_a_non_guard_if_is_not_offered_for_deletion():
    # Only if-blocks whose body is purely a raise or return are guards. Deleting
    # an if that does real work is a different, much noisier mutation.
    source = "def f(x):\n    if x:\n        y = compute(x)\n        log(y)\n    return 1\n"
    assert all(c.operator != "delete_guard" for c in find_candidates(source, [2]))


def test_an_await_offers_a_drop():
    mutated = apply_candidate(ASYNC, pick(ASYNC, [2], "drop_await"))
    assert "await " not in mutated
    assert "_db.write(record)" in mutated


def test_a_narrow_except_offers_widening():
    mutated = apply_candidate(NARROW, pick(NARROW, [4], "widen_except"))
    assert "except FileNotFoundError" not in mutated
    assert "except:" in mutated or "except Exception" in mutated


def test_a_bare_except_is_not_offered_for_widening():
    source = "def f():\n    try:\n        g()\n    except:\n        pass\n"
    assert all(c.operator != "widen_except" for c in find_candidates(source, [4]))


def test_a_finally_block_offers_cleanup_removal():
    # The `finally:` line is line 5 of CLEANUP.
    mutated = apply_candidate(CLEANUP, pick(CLEANUP, [5], "remove_cleanup"))
    assert "fh.close()" not in mutated
    assert "finally:" in mutated


def test_cleanup_removal_empties_the_block_rather_than_deleting_it():
    # Deleting the clause outright would leave a try with no handler, which is
    # invalid Python — the gate would reject every such mutant and this
    # operator would silently produce nothing.
    import ast

    ast.parse(apply_candidate(CLEANUP, pick(CLEANUP, [5], "remove_cleanup")))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mutation_removals.py -q`
Expected: FAIL — `StopIteration` from `pick`, because no such candidate exists yet

- [ ] **Step 3: Add guard detection and the three operators**

In `src/chesterton/mutation/operators.py`, add a helper above `_Collector`:

```python
def _is_guard(node: cst.If) -> bool:
    """True when an if-block exists only to bail out.

    A guard's body is nothing but a raise or a return. An if that does real
    work is a different mutation entirely — deleting it is noisy rather than
    pointed, and the spec's operator is specifically the quiet removal of a
    bail-out.
    """
    if node.orelse is not None:
        return False
    body = node.body.body if isinstance(node.body, cst.IndentedBlock) else []
    if not body:
        return False
    for statement in body:
        if not isinstance(statement, cst.SimpleStatementLine):
            return False
        for small in statement.body:
            if not isinstance(small, (cst.Raise, cst.Return)):
                return False
    return True
```

Extend `_Collector.visit_If` so it also offers deletion for guards:

```python
        if line in self.lines and _is_guard(node):
            self.found.append(
                Candidate("delete_guard", line, f"delete guard {_snippet(node.test)}")
            )
```

Add two more visitors to `_Collector`:

```python
    def visit_Await(self, node: cst.Await) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate("drop_await", line, f"drop await on {_snippet(node.expression)}")
            )

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> None:
        line = self._line(node)
        if line in self.lines and node.type is not None:
            self.found.append(
                Candidate("widen_except", line, f"widen {_snippet(node.type)} to bare except")
            )

    def visit_Finally(self, node: cst.Finally) -> None:
        line = self._line(node)
        if line in self.lines:
            self.found.append(
                Candidate("remove_cleanup", line, "empty the finally block")
            )
```

Add the matching cases to `_Applier`:

```python
    def leave_Await(self, original: cst.Await, updated: cst.Await):
        if self._hits(original, "drop_await"):
            self.applied = True
            return updated.expression
        return updated

    def leave_ExceptHandler(
        self, original: cst.ExceptHandler, updated: cst.ExceptHandler
    ):
        if self._hits(original, "widen_except"):
            self.applied = True
            return updated.with_changes(type=None, name=None)
        return updated

    def leave_Finally(self, original: cst.Finally, updated: cst.Finally):
        if self._hits(original, "remove_cleanup"):
            self.applied = True
            # Emptied, not deleted: removing the clause from a try that has no
            # except handler would leave invalid Python.
            return updated.with_changes(
                body=cst.IndentedBlock(
                    body=[cst.SimpleStatementLine(body=[cst.Pass()])]
                )
            )
        return updated
```

and extend `leave_If` to handle deletion before inversion:

```python
        if self._hits(original, "delete_guard"):
            self.applied = True
            return cst.RemoveFromParent()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_mutation_removals.py tests/test_mutation_operators.py -q`
Expected: PASS — 17 passed

**If a test fails, STOP and report it** rather than adjusting either side.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/mutation/operators.py tests/test_mutation_removals.py
git commit -m "feat: add guard deletion, await dropping and except widening operators"
```

---

### Task 6: The Nemotron client

Every behaviour here was measured live on 2026-09-18, not assumed. Thinking is
on by default and costs 64 tokens for a trivial reply; `enable_thinking: false`
brings that to zero and returns clean JSON. A response truncated mid-reasoning
returns partial *thoughts* as content, flagged only by `finish_reason`.

**Files:**
- Create: `src/chesterton/llm/__init__.py`
- Create: `src/chesterton/llm/client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EXECUTION_MODEL`, `REASONING_MODEL`, `SYNTHESIS_MODEL`; `TruncatedResponse`; `NemotronClient(api_key: str | None = None)` with `async complete(prompt: str, *, model: str, max_tokens: int = 2048, thinking: bool = False) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_llm_client.py`:

```python
import pytest

from chesterton.llm.client import (
    EXECUTION_MODEL,
    REASONING_MODEL,
    SYNTHESIS_MODEL,
    NemotronClient,
    TruncatedResponse,
)


class _FakeCompletions:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


class _Reply:
    def __init__(self, content, finish_reason="stop"):
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message, "finish_reason": finish_reason})()
        self.choices = [choice]


def a_client(reply) -> tuple[NemotronClient, _FakeCompletions]:
    client = NemotronClient(api_key="unused")
    completions = _FakeCompletions(reply)
    client._chat = completions  # inject; no network in unit tests
    return client, completions


def test_the_confirmed_model_ids_are_exact():
    # Casing differs between all three and was verified against the live
    # /v1/models listing. Inferring them from a catalogue produced wrong values.
    assert EXECUTION_MODEL == "nvidia/Nemotron-3_5-Lightning"
    assert REASONING_MODEL == "nvidia/nemotron-3-super-120b-a12b"
    assert SYNTHESIS_MODEL == "nvidia/Nemotron-3-Ultra-550b-a55b"


async def test_thinking_is_disabled_by_default():
    # Measured: thinking on costs 64 reasoning tokens for a trivial reply.
    client, completions = a_client(_Reply('{"ok": true}'))

    await client.complete("hi", model=EXECUTION_MODEL)

    kwargs = completions.calls[0]
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


async def test_thinking_can_be_enabled_for_judgement_calls():
    client, completions = a_client(_Reply("considered"))

    await client.complete("hi", model=REASONING_MODEL, thinking=True)

    kwargs = completions.calls[0]
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


async def test_a_truncated_response_raises_instead_of_returning_thoughts():
    # Measured: a call cut off mid-reasoning returns partial chain-of-thought
    # as content. Parsing that yields neither JSON nor an answer.
    client, _ = a_client(_Reply("The user wants a single", finish_reason="length"))

    with pytest.raises(TruncatedResponse, match="max_tokens"):
        await client.complete("hi", model=EXECUTION_MODEL)


async def test_content_is_returned_stripped():
    # Measured: a complete response can carry leading whitespace before JSON.
    client, _ = a_client(_Reply('\n\n{"ok": true}'))

    assert await client.complete("hi", model=EXECUTION_MODEL) == '{"ok": true}'
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_llm_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.llm'`

- [ ] **Step 3: Write the client**

`src/chesterton/llm/__init__.py` — empty.

`src/chesterton/llm/client.py`:

```python
"""Nemotron on Nebius Token Factory.

Every behaviour encoded here was measured against the live service on
2026-09-18 rather than read from a catalogue:

- Thinking is ON by default and costs real tokens — 64 for a reply as trivial
  as `{"ok": true}`. `enable_thinking: false` brings that to zero.
- On a COMPLETE response, reasoning does not appear in `content`; the content
  is clean, sometimes with leading whitespace.
- On a response truncated by `max_tokens` mid-reasoning, the partial thought
  IS the content. Nothing flags it except `finish_reason`, so parsing such a
  response yields neither JSON nor an answer. We raise instead.
"""

from __future__ import annotations

import os

#: Verified against GET /v1/models?verbose=true. Casing differs between all
#: three; do not infer these from a third-party catalogue.
EXECUTION_MODEL = "nvidia/Nemotron-3_5-Lightning"
REASONING_MODEL = "nvidia/nemotron-3-super-120b-a12b"
SYNTHESIS_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


class TruncatedResponse(RuntimeError):
    """The model ran out of budget before finishing."""


class NemotronClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL) -> None:
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY", "")
        self.base_url = base_url
        self._chat = None

    def _completions(self):
        if self._chat is None:
            from openai import AsyncOpenAI

            self._chat = AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url
            ).chat.completions
        return self._chat

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int = 2048,
        thinking: bool = False,
    ) -> str:
        reply = await self._completions().create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
        )
        choice = reply.choices[0]
        if choice.finish_reason == "length":
            raise TruncatedResponse(
                f"{model} hit max_tokens ({max_tokens}) before finishing. Its "
                "content is partial reasoning, not an answer — raise max_tokens "
                "or disable thinking rather than parsing this."
            )
        return (choice.message.content or "").strip()
```

- [ ] **Step 4: Add the dependency**

In `pyproject.toml`, add `"openai>=1.40"` to `dependencies`, then:

```bash
.venv/Scripts/pip install -q -e ".[dev]"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_llm_client.py -q`
Expected: PASS — 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/llm pyproject.toml tests/test_llm_client.py
git commit -m "feat: add the Nemotron client with thinking disabled and a truncation guard"
```

---

### Task 7: Semantic mutant generation

The deterministic operators cover the shapes we can name. This asks Nemotron
for the ones we cannot — mutations that are plausible *for this specific code*.
It runs on the execution tier because it is called once per hunk across every
seed, which is exactly the high-volume, low-judgement work that tier is for.

**Files:**
- Create: `src/chesterton/llm/mutants.py`
- Test: `tests/test_llm_mutants.py`

**Interfaces:**
- Consumes: `NemotronClient`, `EXECUTION_MODEL` (Task 6); `Mutant` (Task 3).
- Produces: `build_prompt(file: str, source: str, start_line: int, end_line: int) -> str`; `parse_mutants(reply: str, *, file: str, start_line: int, end_line: int, original_src: str) -> list[Mutant]`; `async propose(client, *, file, source, start_line, end_line) -> list[Mutant]`.

- [ ] **Step 1: Write the failing test**

`tests/test_llm_mutants.py`:

```python
import pytest

from chesterton.llm.mutants import build_prompt, parse_mutants

HUNK = 'def charge(amount):\n    if amount > 100:\n        raise ValueError("no")\n'


def test_the_prompt_carries_the_code_and_the_line_range():
    prompt = build_prompt("pay.py", HUNK, 1, 3)
    assert "pay.py" in prompt
    assert "raise ValueError" in prompt
    assert "1" in prompt and "3" in prompt


def test_the_prompt_asks_for_json_only():
    # The client disables thinking for this call, so the reply should be JSON
    # with no preamble. Saying so in the prompt as well is cheap insurance.
    prompt = build_prompt("pay.py", HUNK, 1, 3)
    assert "JSON" in prompt


def test_well_formed_mutants_are_parsed():
    reply = (
        '{"mutants": [{"mutated_src": "def charge(amount):\\n    pass\\n",'
        ' "rationale": "removed the guard", "operator": "semantic"}]}'
    )
    mutants = parse_mutants(
        reply, file="pay.py", start_line=1, end_line=3, original_src=HUNK
    )
    assert len(mutants) == 1
    assert mutants[0].source == "llm"
    assert mutants[0].file == "pay.py"
    assert mutants[0].rationale == "removed the guard"


def test_a_reply_with_leading_prose_still_parses():
    # Belt and braces: thinking is disabled, but a stray preamble must not
    # cost us the whole batch.
    reply = 'Here you go:\n{"mutants": [{"mutated_src": "x = 1\\n",'
    reply += ' "rationale": "r", "operator": "semantic"}]}'
    assert len(parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                             original_src="y = 2\n")) == 1


def test_malformed_json_yields_no_mutants_rather_than_raising():
    # One bad reply must not abort a run over hundreds of hunks.
    assert parse_mutants("not json at all", file="a.py", start_line=1,
                         end_line=1, original_src="x = 1\n") == []


def test_entries_missing_mutated_src_are_skipped():
    reply = '{"mutants": [{"rationale": "no code"}, {"mutated_src": "x = 9\\n"}]}'
    mutants = parse_mutants(reply, file="a.py", start_line=1, end_line=1,
                            original_src="x = 1\n")
    assert len(mutants) == 1
    assert mutants[0].mutated_src == "x = 9\n"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_llm_mutants.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.llm.mutants'`

- [ ] **Step 3: Write the generator**

`src/chesterton/llm/mutants.py`:

```python
"""Ask Nemotron for mutations the deterministic operators cannot name.

Runs on the execution tier: called once per hunk across every seed, high
volume, low judgement. Thinking is disabled, so the reply should be JSON with
no preamble — but `parse_mutants` tolerates one anyway, because a single stray
sentence must not cost a whole batch.

A malformed reply yields no mutants rather than raising. The deterministic
operators are the floor; the model is upside.
"""

from __future__ import annotations

import json

from chesterton.llm.client import EXECUTION_MODEL
from chesterton.mutation.model import Mutant

_PROMPT = """\
You are helping audit a pull request by proposing small, plausible mutations \
to changed code. A good mutation removes or weakens a protection an author \
might delete by accident: a guard clause, a bounds check, an await, a cleanup \
call, a narrow exception.

File: {file}
Lines {start}-{end}:

```python
{source}
```

Propose up to {limit} mutations. Each must be the FULL replacement text for \
those lines, valid Python, and differ from the original in exactly one way.

Reply with JSON only, no prose:
{{"mutants": [{{"mutated_src": "...", "rationale": "...", \
"operator": "semantic"}}]}}
"""


def build_prompt(file: str, source: str, start_line: int, end_line: int, limit: int = 4) -> str:
    return _PROMPT.format(
        file=file, source=source, start=start_line, end=end_line, limit=limit
    )


def _extract_json(reply: str) -> dict | None:
    start = reply.find("{")
    end = reply.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_mutants(
    reply: str, *, file: str, start_line: int, end_line: int, original_src: str
) -> list[Mutant]:
    parsed = _extract_json(reply)
    if parsed is None:
        return []

    mutants: list[Mutant] = []
    for entry in parsed.get("mutants", []):
        if not isinstance(entry, dict):
            continue
        mutated = entry.get("mutated_src")
        if not isinstance(mutated, str) or not mutated:
            continue
        mutants.append(
            Mutant(
                file=file,
                start_line=start_line,
                end_line=end_line,
                operator=str(entry.get("operator", "semantic")),
                original_src=original_src,
                mutated_src=mutated,
                rationale=str(entry.get("rationale", "")),
                source="llm",
            )
        )
    return mutants


async def propose(
    client, *, file: str, source: str, start_line: int, end_line: int
) -> list[Mutant]:
    reply = await client.complete(
        build_prompt(file, source, start_line, end_line),
        model=EXECUTION_MODEL,
        max_tokens=2048,
    )
    return parse_mutants(
        reply,
        file=file,
        start_line=start_line,
        end_line=end_line,
        original_src=source,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_llm_mutants.py -q`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/llm/mutants.py tests/test_llm_mutants.py
git commit -m "feat: propose semantic mutants with Nemotron on the execution tier"
```

---

### Task 8: The generation orchestrator

Everything converges here: filter the files, collect deterministic candidates,
gate them, and rank within a budget. The budget is not decoration — the
measured concurrency cap is 24, and a run that generates 200 mutants would
queue for ten rounds and stop feeling live.

**Files:**
- Create: `src/chesterton/mutation/generate.py`
- Test: `tests/test_mutation_generate.py`

**Interfaces:**
- Consumes: `Hunk` (Phase 1), `is_mutable_source` (Task 2), `Mutant`/`MutantGate` (Task 3), `find_candidates`/`apply_candidate` (Tasks 4–5).
- Produces: `MUTANT_BUDGET: int`; `OPERATOR_WEIGHT: dict[str, int]`; `generate(hunks: Sequence[Hunk], sources: Mapping[str, str], *, budget: int = MUTANT_BUDGET) -> tuple[list[Mutant], dict[str, int]]`.

- [ ] **Step 1: Write the failing test**

`tests/test_mutation_generate.py`:

```python
from chesterton.models import Hunk
from chesterton.mutation.generate import MUTANT_BUDGET, generate

GUARDED = '''\
@rate_limit(10)
def charge(amount):
    if not amount:
        raise ValueError("required")
    return amount > 100
'''


def test_mutants_are_generated_for_a_python_hunk():
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED})
    assert mutants
    assert all(m.file == "pay.py" for m in mutants)


def test_non_python_files_are_skipped_entirely():
    mutants, rejected = generate([Hunk("README.md", 1, 2)], {"README.md": "# hi\n"})
    assert mutants == []
    assert rejected["not_mutable_source"] == 1


def test_a_hunk_with_no_source_available_is_skipped():
    mutants, rejected = generate([Hunk("gone.py", 1, 2)], {})
    assert mutants == []
    assert rejected["no_source"] == 1


def test_every_generated_mutant_passed_the_gate():
    # The gate rejects unparseable output, so anything returned must compile.
    import ast

    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED})
    for mutant in mutants:
        ast.parse(mutant.mutated_src)


def test_the_budget_is_respected():
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED}, budget=2)
    assert len(mutants) == 2


def test_guard_deletion_outranks_a_boundary_shift():
    # The spec's headline operator is the quiet removal of a guard. Under a
    # tight budget that must survive and the cheaper mutations must not.
    mutants, _ = generate([Hunk("pay.py", 1, 5)], {"pay.py": GUARDED}, budget=1)
    assert mutants[0].operator in {"delete_guard", "strip_decorator"}


def test_the_default_budget_fits_the_measured_concurrency_cap():
    # 24 concurrent operations was measured safe. A budget far above it queues.
    assert MUTANT_BUDGET <= 24
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mutation_generate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chesterton.mutation.generate'`

- [ ] **Step 3: Write the orchestrator**

`src/chesterton/mutation/generate.py`:

```python
"""Collect, gate, rank and budget the mutants for one run.

The budget exists because concurrency is capped. 24 simultaneous sandbox
operations was measured safe (72/72 across three rounds); a run that generated
200 mutants would queue for ten rounds and stop feeling live, which costs the
demo more than the extra coverage buys.

Ranking is by operator weight, because under a tight budget the mutations that
survive should be the ones carrying the most signal. Deleting a guard clause is
the spec's headline case — an agent quietly removing a protection — and it
outranks shifting a comparison boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from chesterton.filters import is_mutable_source
from chesterton.models import Hunk
from chesterton.mutation.gate import MutantGate
from chesterton.mutation.model import Mutant
from chesterton.mutation.operators import apply_candidate, find_candidates

#: Matches the measured safe concurrency. One round, no queueing.
MUTANT_BUDGET = 24

#: Higher is kept first when the budget bites.
OPERATOR_WEIGHT = {
    "delete_guard": 100,
    "strip_decorator": 90,
    "remove_cleanup": 85,
    "drop_await": 80,
    "widen_except": 70,
    "invert_condition": 50,
    "off_by_one": 40,
}


def generate(
    hunks: Sequence[Hunk],
    sources: Mapping[str, str],
    *,
    budget: int = MUTANT_BUDGET,
) -> tuple[list[Mutant], dict[str, int]]:
    gate = MutantGate()
    skipped: dict[str, int] = {}
    collected: list[Mutant] = []

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for hunk in hunks:
        if not is_mutable_source(hunk.file):
            skip("not_mutable_source")
            continue

        source = sources.get(hunk.file)
        if source is None:
            skip("no_source")
            continue

        for candidate in find_candidates(source, hunk.lines):
            mutated = apply_candidate(source, candidate)
            mutant = Mutant(
                file=hunk.file,
                start_line=hunk.start_line,
                end_line=hunk.end_line,
                operator=candidate.operator,
                original_src=source,
                mutated_src=mutated,
                rationale=candidate.description,
                source="deterministic",
            )
            if gate.admit(mutant):
                collected.append(mutant)

    collected.sort(key=lambda m: OPERATOR_WEIGHT.get(m.operator, 0), reverse=True)
    return collected[:budget], {**skipped, **gate.rejected}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS — 122 passed

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/mutation/generate.py tests/test_mutation_generate.py
git commit -m "feat: orchestrate mutant generation with gating, ranking and a budget"
```

---

### Task 9: Measure the CrossHair opportunity

Not an implementation — a measurement that decides whether Phase 2b is worth
building. The spec estimates CrossHair lands on 10–30% of changed functions and
sets an acceptance bar: **at least one curated seed must produce a solver-proved
distinguishing input**, because that is the demo's strongest moment and random
search cannot substitute for it on camera.

Build nothing until this number exists.

**Files:**
- Create: `scripts/probe_crosshair.py`
- Modify: `pyproject.toml` (add `crosshair-tool` to the `sandbox` extra)

**Interfaces:**
- Consumes: nothing from this plan; operates on local Python files.
- Produces: a printed hit-rate table. No library code.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, extend the optional `sandbox` extra:

```toml
sandbox = ["contree-sdk", "crosshair-tool>=0.0.110"]
```

Then: `.venv/Scripts/pip install -q -e ".[sandbox]"`

- [ ] **Step 2: Write the probe**

`scripts/probe_crosshair.py`:

```python
"""How often can CrossHair actually find a distinguishing input?

The spec's evidence ladder puts a solver-proved distinguishing input above a
surviving mutant, and §15 sets an acceptance bar: at least one curated seed
must produce one. CrossHair needs type-annotated, deterministic, side-effect-
free functions, and the spec's own estimate is that only 10-30% of changed
functions qualify.

This measures the ceiling before Phase 2b commits to building the tier. It
counts eligibility, not solver success — a function CrossHair cannot even
attempt is a function the tier will never help with.

Usage:
    python scripts/probe_crosshair.py <file-or-dir> [...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Calls that make a function unanalysable by a solver.
_IMPURE_HINTS = {"open", "print", "input", "requests", "urlopen", "random"}


def _eligible(fn: ast.FunctionDef) -> tuple[bool, str]:
    args = [a for a in fn.args.args if a.arg not in {"self", "cls"}]
    if not args:
        return False, "no arguments"
    if any(a.annotation is None for a in args):
        return False, "unannotated arguments"
    if fn.returns is None:
        return False, "no return annotation"

    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _IMPURE_HINTS:
                return False, f"calls {node.func.id}()"
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return False, "mutates outer scope"
    return True, "eligible"


def scan(path: Path) -> list[tuple[str, bool, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            ok, why = _eligible(node)
            out.append((f"{path}:{node.name}", ok, why))
    return out


def main(targets: list[str]) -> int:
    files: list[Path] = []
    for target in targets:
        p = Path(target)
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])

    rows = [row for f in files for row in scan(f)]
    if not rows:
        print("No functions found.")
        return 1

    eligible = [r for r in rows if r[1]]
    print(f"{len(eligible)}/{len(rows)} functions are CrossHair-eligible "
          f"({100 * len(eligible) / len(rows):.0f}%)\n")

    reasons: dict[str, int] = {}
    for _, ok, why in rows:
        if not ok:
            reasons[why] = reasons.get(why, 0) + 1
    print("Why the rest are not:")
    for why, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {why}")

    print("\nEligible functions (CrossHair can at least attempt these):")
    for name, _, _ in eligible[:20]:
        print(f"  {name}")

    print(
        "\nEligibility is the CEILING, not the hit rate — the solver still has "
        "to find a difference within its budget. If eligibility is already "
        "under ~10%, Phase 2b is not worth building and the Hypothesis "
        "fallback should carry tier 1 alone."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["src/chesterton"]))
```

- [ ] **Step 3: Run it against this codebase as a sanity check**

Run: `.venv/Scripts/python scripts/probe_crosshair.py src/chesterton`
Expected: a percentage and a reason breakdown. This codebase is heavily
annotated, so expect a high number — it is a smoke test of the probe, not a
representative sample.

- [ ] **Step 4: Run it against a real seed repository**

Clone one of the confirmed seed repositories and probe its source, not its
tests:

```bash
git clone --depth 1 https://github.com/IAMconsortium/nomenclature /tmp/nomenclature
.venv/Scripts/python scripts/probe_crosshair.py /tmp/nomenclature/nomenclature
```

**That** number decides Phase 2b, not the one from this codebase — Chesterton
is unusually heavily annotated and would flatter the result. Record it in spec
§15 beside the CrossHair risk, with the date and the repository measured.

- [ ] **Step 5: Commit**

```bash
git add scripts/probe_crosshair.py pyproject.toml
git commit -m "feat: measure CrossHair eligibility before committing to the tier"
```

---

## Phase 2 Done When

- `pytest` is green with no network access (122 tests).
- Given hunks and their source, `generate()` returns a gated, ranked, budgeted
  mutant list, and reports what it rejected and why.
- Non-Python and test files never reach the mutation path.
- The CrossHair eligibility number exists for at least one real seed
  repository, recorded in spec §15.

## Follow-on

- **Phase 2b — the distinguishing-input tier.** Planned only if the Task 9
  number justifies it: CrossHair `diffbehavior`, the Hypothesis
  `ghostwriter.equivalent()` fallback, and tier routing across tiers 0/1/1b/2.
- **Phase 3 — execution and reduction.** The seed pipeline (build and tag
  baseline checkpoints, three-times flake detection), semaphore-bounded fan-out
  over the real runner, ddmin over hunks, the budget guard.
- **Phase 4 — triage and review.** Deterministic equivalence pre-filter,
  Nemotron Super classification with abstention, regression-test generation
  with two-way execution verification.
