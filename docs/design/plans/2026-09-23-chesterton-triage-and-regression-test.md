# Triage and Verified Regression Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a finished run's surviving mutants into (a) a short, triaged list of findings a reviewer should act on and (b) one regression test for the top finding, shown only when execution proves it passes on the pull request's code and fails on the mutant.

**Architecture:** A new `chesterton review SEED RUN` command reads a seed and a run report that already exist, so runs and the benchmark stay untouched. Triage builds compact evidence for each survivor, drops obvious equivalents with a deterministic pre-filter, classifies the rest with Nemotron Super, and confirms the top candidates by sampling them three times. The top headline finding gets a test written by Nemotron Ultra. That test is verified in two sandbox forks of the seed checkpoint, with one repair attempt fed by the failure.

**Tech Stack:** Python 3.12+, pytest with pytest-asyncio (auto mode), the existing `NemotronClient`, `SandboxPool` and `FakeSandboxRunner`, and `ast`/`difflib` from the standard library. No new dependencies.

**Spec:** `docs/design/specs/2026-09-18-chesterton-design.md`: §9 (triage and review synthesis) is the design; §10 (model routing) and §14 (failure modes) constrain it. §17's v2 result is why this matters now: "flagged at all" does not separate wrong patches from accepted ones, so the value has to come from *which* survivor matters and *what test catches it*.

## Global Constraints

- Model ids come from the constants in `src/chesterton/llm/client.py` (`REASONING_MODEL`, `SYNTHESIS_MODEL`). Never retype them: "Casing differs between all three".
- A reply cut off by `max_tokens` raises `TruncatedResponse` inside the client and is never parsed (§10). Every model call here catches it and turns it into an honest non-answer.
- Triage uses Super **with thinking on** (§9). Test generation uses Ultra with thinking on. Size `max_tokens` for thinking plus answer: 8192 for Super, 16384 for Ultra.
- Abstention is required (§9): an unsure or unparseable classification goes to "worth a look", never to the headline. The headline shows at most three findings, each confirmed 3 of 3 times.
- A regression test is never rendered unless it verified both ways: pytest exit 0 on the pull request's code and exit 1 on the mutant (§9). Any other exit code proves nothing.
- A sandbox operation that failed (`RunResult.error` set) or hit the op budget is an `error`, never a verdict (§14).
- Everything written to disk is UTF-8 with `newline="\n"`.
- Tests run offline: `FakeSandboxRunner` for sandboxes, a scripted fake for the model. Run the suite with `.venv/Scripts/python.exe -m pytest -q`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `src/chesterton/triage/__init__.py` | package marker |
| `src/chesterton/triage/evidence.py` | `Evidence` for one survivor; rebuilding `MutantResult`s from a run report's JSON |
| `src/chesterton/triage/prefilter.py` | the deterministic pre-filter (logging-only mutations) |
| `src/chesterton/triage/classify.py` | the Super prompt, strict reply parsing, one classification call |
| `src/chesterton/triage/select.py` | the whole triage pass: pre-filter, classify, rank, confirm, sort into headline / worth a look / dismissed |
| `src/chesterton/regress/__init__.py` | package marker |
| `src/chesterton/regress/context.py` | the covering test's source, cut down to imports plus the one test |
| `src/chesterton/regress/generate.py` | where the new test goes, the Ultra prompt, parsing the reply into a test module |
| `src/chesterton/regress/verify.py` | two sandbox forks: must pass on the PR's code, must fail on the mutant |
| `src/chesterton/review.py` | orchestration: triage, then generate → verify → one repair; `ReviewReport` JSON |
| `src/chesterton/__main__.py` | new `review` subcommand |
| `src/chesterton/llm/mutants.py` | `_extract_json` becomes public `extract_json`, reused by triage |
| `scripts/review_study.py` | exploratory measurement on matplotlib-23314's wrong patches |
| `tests/conftest.py` | shared helpers: `a_survivor`, `ScriptedClient`, `finding_reply` |

---

### Task 1: Evidence for one survivor

**Files:**
- Create: `src/chesterton/triage/__init__.py` (empty)
- Create: `src/chesterton/triage/evidence.py`
- Modify: `tests/conftest.py` (append `a_survivor`)
- Test: `tests/test_triage_evidence.py`

**Interfaces:**
- Consumes: `MutantResult` and `Mutant` (`chesterton.execute.mutants`, `chesterton.mutation.model`).
- Produces:
  - `Evidence(file, start_line, end_line, operator, rationale, original, mutated, diff, tests: tuple[str, ...], pr_title, mutant: Mutant)`. `original`/`mutated` are line-numbered windows; `diff` is a unified diff of the raw windows.
  - `evidence_for(result: MutantResult, pr_title: str, context: int = CONTEXT_LINES) -> Evidence`
  - `results_from_report(report: dict) -> list[MutantResult]`
  - conftest: `a_survivor(mutated_src, *, start=2, end=3, rationale="", tests=(T_CHARGE,), original=HEAD_PAY, file="pay.py", verdict="survived") -> MutantResult`

- [ ] **Step 1: Add the shared test helper**

Append to `tests/conftest.py`:

```python
from chesterton.execute.mutants import MutantResult  # noqa: E402
from chesterton.mutation.model import Mutant  # noqa: E402

#: The demo module with its guard deleted: lines 2-3 are gone.
NO_GUARD = "def charge(amount):\n    return amount\n"


def a_survivor(
    mutated_src: str,
    *,
    start: int = 2,
    end: int = 3,
    rationale: str = "",
    tests: tuple[str, ...] = (T_CHARGE,),
    original: str = HEAD_PAY,
    file: str = "pay.py",
    verdict: str = "survived",
) -> MutantResult:
    mutant = Mutant(
        file=file, start_line=start, end_line=end, operator="semantic",
        original_src=original, mutated_src=mutated_src, rationale=rationale,
        source="llm",
    )
    return MutantResult(mutant, verdict, tests)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_triage_evidence.py`:

```python
"""What triage sees about one surviving mutant."""

import json

from chesterton.run import run_seed
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from chesterton.triage.evidence import evidence_for, results_from_report

from conftest import NO_GUARD, T_CHARGE, a_survivor


def test_evidence_shows_the_numbered_code_before_and_after():
    ev = evidence_for(a_survivor(NO_GUARD, rationale="drop the guard"), "Require an amount")

    assert "    2 |     if not amount:" in ev.original
    assert "raise" not in ev.mutated
    assert "    2 |     return amount" in ev.mutated
    assert '-        raise ValueError("required")' in ev.diff
    assert ev.tests == (T_CHARGE,)
    assert (ev.file, ev.start_line, ev.end_line) == ("pay.py", 2, 3)
    assert ev.rationale == "drop the guard"
    assert ev.pr_title == "Require an amount"


def test_the_window_is_the_hunk_plus_context_not_the_module():
    module = "".join(f"x{i} = {i}\n" for i in range(1, 101))
    mutated = module.replace("x50 = 50\n", "x50 = 0\n")
    result = a_survivor(mutated, start=50, end=50, original=module)

    ev = evidence_for(result, "t", context=3)

    assert "   47 | x47 = 47" in ev.original and "   53 | x53 = 53" in ev.original
    assert "x46" not in ev.original and "x54" not in ev.original
    assert "   50 | x50 = 0" in ev.mutated


async def test_results_rebuild_exactly_from_a_run_report(demo_seed):
    def survive(checkpoint, shell, files):
        return RunResult("", "", 0, None)

    report = await run_seed(demo_seed, FakeSandboxRunner(handler=survive), reduce=False)

    rebuilt = results_from_report(json.loads(report.to_json()))

    assert rebuilt == report.results
    assert any(r.verdict == "survived" for r in rebuilt)
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_evidence.py`
Expected: collection error, `ModuleNotFoundError: No module named 'chesterton.triage'`.

- [ ] **Step 4: Implement**

`src/chesterton/triage/evidence.py`:

```python
"""What triage sees about one surviving mutant.

The prompt gets the hunk and a little context, never the whole module: a
matplotlib module runs to thousands of lines, and the reasoning tier is
priced and rate-limited per token (spec §10). The evidence a static reviewer
cannot have is `tests`: the tests that executed this code, ran against the
mutant, and all passed (spec §9).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from chesterton.execute.mutants import MutantResult
from chesterton.mutation.model import Mutant

#: Lines of unchanged code shown either side of the hunk.
CONTEXT_LINES = 6


@dataclass(frozen=True)
class Evidence:
    file: str
    start_line: int
    end_line: int
    operator: str
    rationale: str
    #: The pull request's code around the hunk, line-numbered.
    original: str
    #: The same window after the mutation, line-numbered.
    mutated: str
    #: A unified diff between the two raw windows.
    diff: str
    tests: tuple[str, ...]
    pr_title: str
    #: The whole mutant, for verification. Never shown to a model.
    mutant: Mutant = field(repr=False)


def _lines(source: str) -> list[str]:
    """Physical lines, split on "\\n" only, as the rest of the pipeline counts."""
    parts = source.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _numbered(lines: list[str], first: int) -> str:
    return "\n".join(f"{first + i:>5} | {line}" for i, line in enumerate(lines))


def evidence_for(result: MutantResult, pr_title: str, context: int = CONTEXT_LINES) -> Evidence:
    mutant = result.mutant
    before, after = _lines(mutant.original_src), _lines(mutant.mutated_src)
    first = max(1, mutant.start_line - context)
    last = min(len(before), mutant.end_line + context)
    # The mutation can add or remove lines; the window's end moves with it.
    shift = len(after) - len(before)
    window_before = before[first - 1 : last]
    window_after = after[first - 1 : max(first - 1, last + shift)]
    diff = "\n".join(
        difflib.unified_diff(
            window_before, window_after,
            fromfile=f"a/{mutant.file}", tofile=f"b/{mutant.file}", lineterm="",
        )
    )
    return Evidence(
        file=mutant.file,
        start_line=mutant.start_line,
        end_line=mutant.end_line,
        operator=mutant.operator,
        rationale=mutant.rationale,
        original=_numbered(window_before, first),
        mutated=_numbered(window_after, first),
        diff=diff,
        tests=tuple(result.tests),
        pr_title=pr_title,
        mutant=mutant,
    )


def results_from_report(report: dict) -> list[MutantResult]:
    """The mutant results of a run report written by `chesterton run`."""
    return [
        MutantResult(
            mutant=Mutant(**entry["mutant"]),
            verdict=entry["verdict"],
            tests=tuple(entry["tests"]),
            duration_s=entry.get("duration_s"),
            detail=entry.get("detail"),
            stdout_tail=entry.get("stdout_tail", ""),
        )
        for entry in report["results"]
    ]
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_evidence.py`
Expected: 3 passed. Then run the full suite: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/triage tests/test_triage_evidence.py tests/conftest.py
git commit -m "feat: gather compact evidence for each surviving mutant"
```

---

### Task 2: Deterministic pre-filter

**Files:**
- Create: `src/chesterton/triage/prefilter.py`
- Test: `tests/test_triage_prefilter.py`

**Interfaces:**
- Consumes: `Evidence`, `evidence_for` (Task 1).
- Produces: `LOGGING_ONLY = "logging_only"`; `prefilter(ev: Evidence) -> str | None` (the reason it is an obvious equivalent, or None).

- [ ] **Step 1: Write the failing tests**

`tests/test_triage_prefilter.py`:

```python
"""Obvious equivalents are dropped before any model call (spec §9)."""

from chesterton.triage.evidence import evidence_for
from chesterton.triage.prefilter import LOGGING_ONLY, prefilter

from conftest import NO_GUARD, a_survivor

LOGGED = (
    "import logging\n"
    "log = logging.getLogger(__name__)\n"
    "\n"
    "def charge(amount):\n"
    '    log.debug("charging %s", amount)\n'
    "    return amount\n"
)


def ev(result):
    return evidence_for(result, "t")


def test_a_mutation_inside_a_logging_call_is_dropped():
    mutated = LOGGED.replace('log.debug("charging %s", amount)', 'log.debug("charging")')

    assert prefilter(ev(a_survivor(mutated, start=5, end=5, original=LOGGED))) == LOGGING_ONLY


def test_print_and_warnings_count_as_logging():
    printed = LOGGED.replace('log.debug("charging %s", amount)', 'print("charging", amount)')
    quiet = printed.replace('print("charging", amount)', 'print("charging")')

    assert prefilter(ev(a_survivor(quiet, start=5, end=5, original=printed))) == LOGGING_ONLY


def test_a_deleted_guard_is_kept_for_the_model():
    assert prefilter(ev(a_survivor(NO_GUARD))) is None


def test_a_change_that_also_touches_real_code_is_kept():
    mutated = LOGGED.replace(
        '    log.debug("charging %s", amount)\n    return amount\n',
        '    log.debug("charging")\n    return 0\n',
    )

    assert prefilter(ev(a_survivor(mutated, start=5, end=6, original=LOGGED))) is None
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_prefilter.py`
Expected: `ModuleNotFoundError: No module named 'chesterton.triage.prefilter'`.

- [ ] **Step 3: Implement**

`src/chesterton/triage/prefilter.py`:

```python
"""Survivors that are obvious equivalents, dropped before any model call.

Spec §9's first stage. Only rules that are right by construction belong
here: a survivor dropped here is never shown to anyone, so a wrong rule
would hide a real finding. Anything uncertain goes to the model instead.

One rule so far: every line the mutation changed is a logging, print or
warnings call. What those emit is output, not behaviour the program acts on.
"""

from __future__ import annotations

import re

from chesterton.triage.evidence import Evidence

LOGGING_ONLY = "logging_only"

#: `log.debug(...)`, `self.logger.warning(...)`, `logging.info(...)`,
#: `print(...)`, `warnings.warn(...)`: one whole call on one line.
_LOGGING = re.compile(
    r"^\s*(?:(?:self|cls)\.)?(?:_?log(?:ger)?|logging|LOG|LOGGER)\.\w+\(.*\)\s*$"
    r"|^\s*print\(.*\)\s*$"
    r"|^\s*warnings\.warn\(.*\)\s*$"
)


def _changed(diff: str) -> list[str]:
    return [
        line[1:]
        for line in diff.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def prefilter(ev: Evidence) -> str | None:
    changed = [line for line in _changed(ev.diff) if line.strip()]
    if changed and all(_LOGGING.match(line) for line in changed):
        return LOGGING_ONLY
    return None
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_prefilter.py`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/triage/prefilter.py tests/test_triage_prefilter.py
git commit -m "feat: drop survivors that only change a logging call"
```

---

### Task 3: Classify one survivor with Nemotron Super

**Files:**
- Modify: `src/chesterton/llm/mutants.py` (rename `_extract_json` → `extract_json`, both occurrences)
- Create: `src/chesterton/triage/classify.py`
- Modify: `tests/conftest.py` (append `ScriptedClient`, `finding_reply`)
- Test: `tests/test_triage_classify.py`

**Interfaces:**
- Consumes: `Evidence` (Task 1); `REASONING_MODEL`, `TruncatedResponse` (`chesterton.llm.client`); `extract_json` (`chesterton.llm.mutants`).
- Produces:
  - `Classification(label: Label, category: "safety" | "functional" | None, confident: bool, explanation: str)`, where `Label = Literal["equivalent", "dead_code", "untested_invariant", "unclassified"]`.
  - `build_triage_prompt(ev: Evidence) -> str` (contains the marker text `Classify the mutant`).
  - `parse_classification(reply: str) -> Classification`
  - `async classify_survivor(client, ev: Evidence) -> Classification`
  - conftest: `ScriptedClient(reply=None, *, raises=None, by_marker=None)` with `.calls` (a list of dicts with prompt, model, max_tokens and thinking). `by_marker` maps a substring of the prompt to one reply, or to a list consumed front first. Also `finding_reply(label="untested_invariant", category="safety", confident=True, explanation="the guard is never exercised") -> str`.

- [ ] **Step 1: Make the JSON helper public**

In `src/chesterton/llm/mutants.py`, rename the function `_extract_json` to `extract_json` and update its single call site in `parse_mutants`. Run `.venv/Scripts/python.exe -m pytest -q`: all pass, since no test imports the old name (checked: `grep -rn _extract_json src tests` shows only mutants.py).

- [ ] **Step 2: Add the shared fakes**

Append to `tests/conftest.py`:

```python
import json as _json  # noqa: E402


class ScriptedClient:
    """A NemotronClient stand-in: answers by prompt content, records every call."""

    def __init__(self, reply=None, *, raises=None, by_marker=None):
        self.reply, self.raises = reply, raises
        self.by_marker = dict(by_marker or {})
        self.calls: list[dict] = []

    async def complete(self, prompt, *, model, max_tokens=2048, thinking=False):
        self.calls.append(
            {"prompt": prompt, "model": model, "max_tokens": max_tokens, "thinking": thinking}
        )
        if self.raises is not None:
            raise self.raises
        for marker, replies in self.by_marker.items():
            if marker in prompt:
                return replies.pop(0) if isinstance(replies, list) else replies
        return self.reply


def finding_reply(
    label="untested_invariant", category="safety", confident=True,
    explanation="the guard is never exercised",
) -> str:
    return _json.dumps(
        {"label": label, "category": category, "confident": confident,
         "explanation": explanation}
    )
```

- [ ] **Step 3: Write the failing tests**

`tests/test_triage_classify.py`:

```python
"""One survivor, one judgement from the reasoning tier (spec §9)."""

import openai

from chesterton.llm.client import REASONING_MODEL, TruncatedResponse
from chesterton.triage.classify import (
    build_triage_prompt,
    classify_survivor,
    parse_classification,
)
from chesterton.triage.evidence import evidence_for

from conftest import NO_GUARD, T_CHARGE, ScriptedClient, a_survivor, finding_reply

EV = evidence_for(a_survivor(NO_GUARD, rationale="drop the guard"), "Require an amount")


def test_the_prompt_carries_the_code_the_mutant_and_the_tests_that_passed():
    prompt = build_triage_prompt(EV)

    assert "Classify the mutant" in prompt
    assert "Require an amount" in prompt
    assert '-        raise ValueError("required")' in prompt
    assert T_CHARGE in prompt
    assert "drop the guard" in prompt
    # The invariant instructions come first, so prompt caching can reuse them.
    assert prompt.index("Classify the mutant") < prompt.index("Require an amount")


def test_a_long_test_list_is_cut_with_a_count():
    many = tuple(f"tests/t.py::test_{i}" for i in range(50))
    prompt = build_triage_prompt(evidence_for(a_survivor(NO_GUARD, tests=many), "t"))

    assert "tests/t.py::test_19" in prompt and "tests/t.py::test_20" not in prompt
    assert "and 30 more" in prompt


def test_a_well_formed_reply_is_read_exactly():
    c = parse_classification(finding_reply(explanation="nothing checks the guard"))

    assert (c.label, c.category, c.confident) == ("untested_invariant", "safety", True)
    assert c.explanation == "nothing checks the guard"


def test_only_a_finding_carries_a_category():
    c = parse_classification(finding_reply(label="equivalent", category="safety"))

    assert c.label == "equivalent" and c.category is None


def test_confidence_must_be_a_real_true():
    assert parse_classification(finding_reply(confident="yes")).confident is False


def test_an_unknown_label_or_prose_abstains():
    assert parse_classification(finding_reply(label="bug")).label == "unclassified"
    assert parse_classification("I think it is fine").label == "unclassified"


async def test_the_call_uses_the_reasoning_tier_with_thinking_on():
    client = ScriptedClient(finding_reply())

    c = await classify_survivor(client, EV)

    assert c.label == "untested_invariant"
    [call] = client.calls
    assert call["model"] == REASONING_MODEL and call["thinking"] is True
    assert call["max_tokens"] >= 8192


async def test_a_truncated_or_failed_call_abstains_instead_of_raising():
    truncated = await classify_survivor(ScriptedClient(raises=TruncatedResponse("x")), EV)
    down = await classify_survivor(ScriptedClient(raises=openai.OpenAIError("down")), EV)

    assert truncated.label == down.label == "unclassified"
    assert truncated.confident is False and "tokens" in truncated.explanation
    assert "unavailable" in down.explanation
```

- [ ] **Step 4: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_classify.py`
Expected: `ModuleNotFoundError: No module named 'chesterton.triage.classify'`.

- [ ] **Step 5: Implement**

`src/chesterton/triage/classify.py`:

```python
"""One surviving mutant, one judgement from Nemotron Super.

Spec §9's second stage. The labels are the spec's: `equivalent` (a false
positive), `dead_code` (honest, low value) and `untested_invariant` (the
finding), with `safety` or `functional` inside the last. `unclassified` is
this module's own: the model was unsure, unreachable, truncated or
unreadable. It is an abstention, and abstentions are never headlines.

Thinking stays ON (spec §9): this is a judgement call, and §10 measured
that a complete reply's content is clean. A truncated one raises in the
client and is never parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from chesterton.llm.client import REASONING_MODEL, TruncatedResponse
from chesterton.llm.mutants import extract_json
from chesterton.triage.evidence import Evidence

Label = Literal["equivalent", "dead_code", "untested_invariant", "unclassified"]
Category = Literal["safety", "functional"]

_LABELS = ("equivalent", "dead_code", "untested_invariant")
_CATEGORIES = ("safety", "functional")

#: Thinking plus a short JSON answer.
MAX_TOKENS = 8192
#: Test ids shown in the prompt; the rest are counted.
MAX_TESTS_SHOWN = 20


@dataclass(frozen=True)
class Classification:
    label: Label
    category: Category | None
    confident: bool
    explanation: str


def _abstain(why: str) -> Classification:
    return Classification("unclassified", None, False, why)


_PROMPT = """\
You review one result of mutation testing on a pull request. A mutant is a \
small deliberate edit to code the pull request changed. The tests that \
execute this code were run against the mutant and ALL PASSED, so the test \
suite cannot tell the mutant from the pull request's code.

Classify the mutant:
- "equivalent": it behaves identically to the original for every input the \
program can reach; no test could ever tell them apart.
- "dead_code": it can change behaviour only on a path the program never \
takes, or its effect is never observable.
- "untested_invariant": it changes observable behaviour and the tests do \
not check it. This is the finding a reviewer needs.
For "untested_invariant", category is "safety" when the change weakens a \
protection (an auth or permission check, a bounds or None check, input \
validation, resource cleanup, a rate limit, error handling) and \
"functional" otherwise. For the other labels, category is null.
Set "confident" to false whenever you are unsure. An unsure answer is kept \
for a human to look at and is never shown as a finding.

Reply with JSON only:
{{"label": "...", "category": "safety" | "functional" | null, \
"confident": true | false, "explanation": "one or two sentences a reviewer can check"}}

Pull request: {title}
File: {file}, lines {start}-{end}
Mutation operator: {operator}
The mutation's stated intent: {rationale}

The pull request's code:
{original}

The mutant:
{mutated}

Diff:
{diff}

Tests that executed this code and passed against the mutant ({count}):
{tests}
"""


def _tests(tests: tuple[str, ...]) -> str:
    if not tests:
        return "(none by name: the code runs at import time, and the whole suite passed)"
    shown = "\n".join(tests[:MAX_TESTS_SHOWN])
    rest = len(tests) - MAX_TESTS_SHOWN
    return shown + (f"\n... and {rest} more" if rest > 0 else "")


def build_triage_prompt(ev: Evidence) -> str:
    return _PROMPT.format(
        title=ev.pr_title, file=ev.file, start=ev.start_line, end=ev.end_line,
        operator=ev.operator, rationale=ev.rationale or "(none given)",
        original=ev.original, mutated=ev.mutated, diff=ev.diff,
        count=len(ev.tests), tests=_tests(ev.tests),
    )


def parse_classification(reply: str) -> Classification:
    parsed = extract_json(reply)
    if parsed is None:
        return _abstain("the model's reply was not the JSON asked for")
    label = parsed.get("label")
    if label not in _LABELS:
        return _abstain(f"the model gave no known label ({label!r})")
    category = parsed.get("category") if label == "untested_invariant" else None
    if label == "untested_invariant" and category not in _CATEGORIES:
        return _abstain("the model called it a finding without a valid category")
    explanation = parsed.get("explanation")
    return Classification(
        label=label,
        category=category,
        confident=parsed.get("confident") is True,
        explanation=explanation if isinstance(explanation, str) else "",
    )


async def classify_survivor(client, ev: Evidence) -> Classification:
    import openai

    try:
        reply = await client.complete(
            build_triage_prompt(ev), model=REASONING_MODEL,
            max_tokens=MAX_TOKENS, thinking=True,
        )
    except TruncatedResponse:
        return _abstain("the model ran out of tokens before answering")
    except openai.OpenAIError as exc:
        return _abstain(f"the model was unavailable ({type(exc).__name__})")
    return parse_classification(reply)
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_classify.py`
Expected: 8 passed. Then the full suite: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/chesterton/llm/mutants.py src/chesterton/triage/classify.py tests/test_triage_classify.py tests/conftest.py
git commit -m "feat: classify a surviving mutant with Nemotron Super, abstaining when unsure"
```

---

### Task 4: The triage pass: rank, confirm, sort

**Files:**
- Create: `src/chesterton/triage/select.py`
- Test: `tests/test_triage_select.py`

**Interfaces:**
- Consumes: `evidence_for` (Task 1), `prefilter` (Task 2), `classify_survivor` and `Classification` (Task 3), `MutantResult`.
- Produces:
  - `TriagedSurvivor(evidence: Evidence, classification: Classification, agreement: int | None = None, prefiltered: str | None = None)`
  - `TriageReport(headline: list[TriagedSurvivor], worth_a_look: list[TriagedSurvivor], dismissed: list[TriagedSurvivor], model_calls: int)`
  - `async triage(client, results: Sequence[MutantResult], pr_title: str, *, samples: int = 3, headline_limit: int = 3, concurrency: int = 4) -> TriageReport`

Rules, from spec §9:
- Only `survived` results are triaged.
- The pre-filter dismisses without a model call.
- A **candidate** is `untested_invariant` and `confident`. Candidates rank safety first, then by more tests that ran and still passed, then by file, line and content hash, so the order is deterministic. At most one candidate per hunk (file, start, end) and at most `headline_limit` are confirmed.
- **Confirmation:** `samples - 1` more classifications. The candidate is a headline only when all `samples` say candidate; otherwise it goes to worth a look, with its `agreement` count.
- Everything else labelled `untested_invariant` or `unclassified` goes to worth a look. `equivalent` and `dead_code` are dismissed.

- [ ] **Step 1: Write the failing tests**

`tests/test_triage_select.py`:

```python
"""Three confident findings beat eleven noisy ones (spec §9)."""

from chesterton.triage.select import triage

from conftest import HEAD_PAY, NO_GUARD, ScriptedClient, a_survivor, finding_reply

GUARD = a_survivor(NO_GUARD, rationale="M-GUARD")
GUARD_2 = a_survivor(
    HEAD_PAY.replace('raise ValueError("required")', "pass"), rationale="M-PASS"
)
RETURN = a_survivor(
    HEAD_PAY.replace("    return amount\n", "    return 0\n"), start=4, end=4,
    rationale="M-RETURN", tests=("tests/t.py::a", "tests/t.py::b", "tests/t.py::c"),
)
FINDING, FUNCTIONAL = finding_reply(), finding_reply(category="functional")
EQUIVALENT = finding_reply(label="equivalent", category=None)
UNSURE = finding_reply(confident=False)


async def test_a_finding_confirmed_three_times_is_a_headline():
    client = ScriptedClient(by_marker={"M-GUARD": [FINDING] * 3, "M-RETURN": EQUIVALENT})

    report = await triage(client, [GUARD, RETURN], "t")

    [top] = report.headline
    assert top.evidence.rationale == "M-GUARD" and top.agreement == 3
    assert [d.evidence.rationale for d in report.dismissed] == ["M-RETURN"]
    assert report.worth_a_look == []
    assert report.model_calls == 4  # two survivors, then two confirmations


async def test_a_finding_that_wavers_on_resampling_is_only_worth_a_look():
    client = ScriptedClient(by_marker={"M-GUARD": [FINDING, FINDING, EQUIVALENT]})

    report = await triage(client, [GUARD], "t")

    assert report.headline == []
    [look] = report.worth_a_look
    assert look.agreement == 2


async def test_an_unsure_finding_is_worth_a_look_and_never_resampled():
    client = ScriptedClient(by_marker={"M-GUARD": UNSURE})

    report = await triage(client, [GUARD], "t")

    assert report.headline == [] and len(report.worth_a_look) == 1
    assert report.model_calls == 1


async def test_one_headline_per_hunk():
    client = ScriptedClient(by_marker={"M-PASS": [FUNCTIONAL] * 3, "M-GUARD": [FINDING] * 3})

    report = await triage(client, [GUARD, GUARD_2], "t")

    assert [h.evidence.rationale for h in report.headline] == ["M-GUARD"]  # safety first
    assert [w.evidence.rationale for w in report.worth_a_look] == ["M-PASS"]


async def test_safety_outranks_functional_and_the_limit_holds():
    client = ScriptedClient(by_marker={"M-GUARD": [FINDING] * 3, "M-RETURN": [FUNCTIONAL] * 3})

    report = await triage(client, [RETURN, GUARD], "t", headline_limit=1)

    assert [h.evidence.rationale for h in report.headline] == ["M-GUARD"]
    assert [w.evidence.rationale for w in report.worth_a_look] == ["M-RETURN"]


async def test_killed_results_are_ignored_and_logging_is_dismissed_for_free():
    logged = "import logging\nlog = logging.getLogger(__name__)\nlog.info('a')\n"
    quiet = a_survivor(logged.replace("'a'", "'b'"), start=3, end=3, original=logged)
    killed = a_survivor(NO_GUARD, verdict="killed")
    client = ScriptedClient(FINDING)

    report = await triage(client, [quiet, killed], "t")

    assert client.calls == []
    [dropped] = report.dismissed
    assert dropped.prefiltered == "logging_only"
    assert report.headline == [] and report.worth_a_look == []
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_select.py`
Expected: `ModuleNotFoundError: No module named 'chesterton.triage.select'`.

- [ ] **Step 3: Implement**

`src/chesterton/triage/select.py`:

```python
"""The triage pass over one run's survivors (spec §9).

Pre-filter, classify, rank, confirm. A headline finding was called an
untested invariant, confidently, on every one of `samples` independent
calls. Anything the model was unsure of, or disagreed with itself about, is
"worth a look": kept, never promoted. "Three confident findings beat eleven
noisy ones."
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace

from chesterton.execute.mutants import MutantResult
from chesterton.triage.classify import Classification, classify_survivor
from chesterton.triage.evidence import Evidence, evidence_for
from chesterton.triage.prefilter import prefilter


@dataclass(frozen=True)
class TriagedSurvivor:
    evidence: Evidence
    classification: Classification
    #: For a confirmed candidate: how many of the samples agreed.
    agreement: int | None = None
    #: The pre-filter's reason, when it dismissed this without a model call.
    prefiltered: str | None = None


@dataclass(frozen=True)
class TriageReport:
    headline: list[TriagedSurvivor]
    worth_a_look: list[TriagedSurvivor]
    dismissed: list[TriagedSurvivor]
    model_calls: int


def _candidate(c: Classification) -> bool:
    return c.label == "untested_invariant" and c.confident


def _rank(t: TriagedSurvivor) -> tuple:
    ev = t.evidence
    return (
        0 if t.classification.category == "safety" else 1,
        -len(ev.tests),
        ev.file, ev.start_line, ev.mutant.content_hash,
    )


def _hunk(t: TriagedSurvivor) -> tuple[str, int, int]:
    return (t.evidence.file, t.evidence.start_line, t.evidence.end_line)


async def triage(
    client,
    results: Sequence[MutantResult],
    pr_title: str,
    *,
    samples: int = 3,
    headline_limit: int = 3,
    concurrency: int = 4,
) -> TriageReport:
    semaphore = asyncio.Semaphore(concurrency)
    calls = 0

    async def classify(ev: Evidence) -> Classification:
        nonlocal calls
        async with semaphore:
            calls += 1
            return await classify_survivor(client, ev)

    dismissed: list[TriagedSurvivor] = []
    pending: list[Evidence] = []
    for result in results:
        if result.verdict != "survived":
            continue
        ev = evidence_for(result, pr_title)
        reason = prefilter(ev)
        if reason is None:
            pending.append(ev)
        else:
            dismissed.append(TriagedSurvivor(
                ev, Classification("equivalent", None, True, f"deterministic pre-filter: {reason}"),
                prefiltered=reason,
            ))

    first = await asyncio.gather(*(classify(ev) for ev in pending))
    triaged = [TriagedSurvivor(ev, c) for ev, c in zip(pending, first)]

    chosen: list[TriagedSurvivor] = []
    for t in sorted((t for t in triaged if _candidate(t.classification)), key=_rank):
        if len(chosen) < headline_limit and _hunk(t) not in {_hunk(c) for c in chosen}:
            chosen.append(t)

    async def confirm(t: TriagedSurvivor) -> TriagedSurvivor:
        more = await asyncio.gather(*(classify(t.evidence) for _ in range(samples - 1)))
        return replace(t, agreement=1 + sum(_candidate(c) for c in more))

    confirmed = await asyncio.gather(*(confirm(t) for t in chosen))
    headline = [t for t in confirmed if t.agreement == samples]
    worth_a_look = [t for t in confirmed if t.agreement != samples]
    for t in triaged:
        if t in chosen:
            continue
        if t.classification.label in ("untested_invariant", "unclassified"):
            worth_a_look.append(t)
        else:
            dismissed.append(t)
    return TriageReport(headline, worth_a_look, dismissed, calls)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_triage_select.py`
Expected: 6 passed. Then the full suite.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/triage/select.py tests/test_triage_select.py
git commit -m "feat: triage survivors into confirmed headlines, worth a look, and dismissed"
```

---

### Task 5: Write a regression test with Nemotron Ultra

**Files:**
- Create: `src/chesterton/regress/__init__.py` (empty)
- Create: `src/chesterton/regress/context.py`
- Create: `src/chesterton/regress/generate.py`
- Test: `tests/test_regress_generate.py`

**Interfaces:**
- Consumes: `Evidence` (Task 1); `SYNTHESIS_MODEL`, `TruncatedResponse`.
- Produces:
  - `covering_test_source(module_src: str, test_id: str) -> str`: the test module's imports plus the one test (with its decorators). It falls back to the first 60 lines if the module does not parse or the test is not found.
  - `REGRESSION_FILE = "test_chesterton_regression.py"`; `regression_test_path(test_id: str) -> str`
  - `build_regression_prompt(ev, explanation, test_context, path, feedback=None) -> str` (contains the marker `Write one pytest regression test`)
  - `parse_test_module(reply: str) -> str | None`
  - `async generate_regression_test(client, ev, explanation, test_context, path, feedback=None) -> str | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_regress_generate.py`:

```python
"""One regression test, written for the top finding (spec §9)."""

from chesterton.llm.client import SYNTHESIS_MODEL, TruncatedResponse
from chesterton.regress.context import covering_test_source
from chesterton.regress.generate import (
    build_regression_prompt,
    generate_regression_test,
    parse_test_module,
    regression_test_path,
)
from chesterton.triage.evidence import evidence_for

from conftest import NO_GUARD, ScriptedClient, a_survivor

TEST_MODULE = '''\
import pytest
from pay import charge


def helper():
    return 1


class TestCharge:
    def test_positive(self):
        assert charge(3) == 3


@pytest.mark.parametrize("fmt", ["png"])
def test_rendered(fmt):
    assert charge(1) == 1
'''

GOOD = "```python\nimport pytest\nfrom pay import charge\n\n\ndef test_zero_is_refused():\n    with pytest.raises(ValueError):\n        charge(0)\n```"

EV = evidence_for(a_survivor(NO_GUARD), "Require an amount")


def test_the_new_file_sits_beside_the_covering_test():
    assert regression_test_path("lib/mpl_toolkits/tests/test_mplot3d.py::test_x[png]") == (
        "lib/mpl_toolkits/tests/test_chesterton_regression.py"
    )
    assert regression_test_path("test_pay.py::test_charge") == "test_chesterton_regression.py"


def test_the_context_is_the_imports_and_the_one_test():
    context = covering_test_source(TEST_MODULE, "tests/test_pay.py::test_rendered[png]")

    assert "from pay import charge" in context
    assert '@pytest.mark.parametrize("fmt", ["png"])' in context
    assert "def test_rendered(fmt):" in context
    assert "def helper" not in context and "test_positive" not in context


def test_a_method_is_found_inside_its_class():
    context = covering_test_source(TEST_MODULE, "tests/test_pay.py::TestCharge::test_positive")

    assert "def test_positive(self):" in context and "test_rendered" not in context


def test_an_unparseable_module_falls_back_to_its_head():
    assert covering_test_source("def broken(:\n", "t.py::x").startswith("def broken(")


def test_the_prompt_carries_everything_the_test_needs():
    prompt = build_regression_prompt(EV, "nothing checks the guard", "CTX", "tests/test_x.py")

    assert "Write one pytest regression test" in prompt
    for part in ("Require an amount", "nothing checks the guard", "CTX", "tests/test_x.py",
                 "    2 |     if not amount:", "    2 |     return amount"):
        assert part in prompt
    assert "previous attempt" not in prompt


def test_feedback_from_a_failed_attempt_is_passed_on():
    prompt = build_regression_prompt(EV, "e", "CTX", "p.py", feedback="fails_on_patch: boom")

    assert "previous attempt" in prompt and "fails_on_patch: boom" in prompt


def test_a_fenced_module_with_a_test_is_accepted():
    assert parse_test_module(GOOD).startswith("import pytest")


def test_a_bare_module_is_accepted_too():
    assert parse_test_module("def test_x():\n    assert True\n") is not None


def test_a_reply_without_a_test_or_that_does_not_parse_is_refused():
    assert parse_test_module("```python\ndef helper():\n    pass\n```") is None
    assert parse_test_module("```python\ndef test_x(:\n```") is None


async def test_generation_uses_the_synthesis_tier():
    client = ScriptedClient(GOOD)

    source = await generate_regression_test(client, EV, "e", "CTX", "p.py")

    assert "def test_zero_is_refused" in source
    [call] = client.calls
    assert call["model"] == SYNTHESIS_MODEL and call["thinking"] is True


async def test_a_truncated_generation_yields_nothing():
    client = ScriptedClient(raises=TruncatedResponse("x"))

    assert await generate_regression_test(client, EV, "e", "CTX", "p.py") is None
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_regress_generate.py`
Expected: `ModuleNotFoundError: No module named 'chesterton.regress'`.

- [ ] **Step 3: Implement the context extractor**

`src/chesterton/regress/context.py`:

```python
"""The one existing test the model should imitate, not the whole file.

A covering test shows the model how this repository builds the objects the
code needs, and which fixtures and imports exist. The whole test file can be
thousands of lines (matplotlib's test_axes.py), so only its imports and the
test itself are sent.
"""

from __future__ import annotations

import ast

FALLBACK_LINES = 60


def _target(test_id: str) -> tuple[str | None, str]:
    parts = test_id.split("::")[1:]
    name = parts[-1].split("[", 1)[0] if parts else ""
    owner = parts[0] if len(parts) > 1 else None
    return owner, name


def _segment(lines: list[str], node: ast.AST) -> str:
    first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return "\n".join(lines[first - 1 : node.end_lineno])


def covering_test_source(module_src: str, test_id: str) -> str:
    lines = module_src.split("\n")
    try:
        tree = ast.parse(module_src)
    except SyntaxError:
        return "\n".join(lines[:FALLBACK_LINES])
    owner, name = _target(test_id)
    imports = [
        _segment(lines, node) for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    scope = tree.body
    if owner is not None:
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner]
        scope = classes[0].body if classes else []
    found = [
        _segment(lines, node) for node in scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if not found:
        return "\n".join(lines[:FALLBACK_LINES])
    return "\n".join(imports) + "\n\n\n" + found[0]
```

- [ ] **Step 4: Implement generation**

`src/chesterton/regress/generate.py`:

```python
"""Ask Nemotron Ultra for the test the suite is missing (spec §9).

One call for the top finding, on the synthesis tier. The reply is a whole
test module. Nothing here trusts it: `verify` runs it before anyone sees
it, and a test that does not pass on the pull request and fail on the
mutant is never rendered.
"""

from __future__ import annotations

import ast
import re

from chesterton.llm.client import SYNTHESIS_MODEL, TruncatedResponse
from chesterton.triage.evidence import Evidence

REGRESSION_FILE = "test_chesterton_regression.py"
#: Thinking plus a whole test module.
MAX_TOKENS = 16384

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def regression_test_path(test_id: str) -> str:
    """Beside the covering test, so its conftest fixtures apply."""
    test_file = test_id.split("::", 1)[0]
    directory = test_file.rsplit("/", 1)[0] if "/" in test_file else ""
    return f"{directory}/{REGRESSION_FILE}" if directory else REGRESSION_FILE


_PROMPT = """\
Write one pytest regression test for a pull request.

The test suite runs the code below, yet a small change to it, the mutant, \
goes unnoticed: every existing test still passes. Write a test module that \
PASSES on the pull request's code and FAILS on the mutant, by checking the \
behaviour the mutant breaks.
- It is a new file, {path}, beside the existing test shown below, so it can \
use the same imports and fixtures.
- Test observable behaviour through the code's public API. Do not read \
source text, compare code, or look for the mutant.
- Deterministic: no network, no sleeping, no unseeded randomness.
- Only syntax that Python 3.7 accepts.
Reply with the complete module in one ```python block and nothing else.

Pull request: {title}
File: {file}, lines {start}-{end}

The pull request's code:
{original}

The mutant:
{mutated}

Why this matters: {explanation}

An existing test that executes this code:
```python
{context}
```
{feedback}"""

_FEEDBACK = """
A previous attempt failed verification. What happened:
{feedback}
Write a corrected module."""


def build_regression_prompt(
    ev: Evidence, explanation: str, test_context: str, path: str,
    feedback: str | None = None,
) -> str:
    return _PROMPT.format(
        path=path, title=ev.pr_title, file=ev.file, start=ev.start_line,
        end=ev.end_line, original=ev.original, mutated=ev.mutated,
        explanation=explanation or "(none given)", context=test_context,
        feedback=_FEEDBACK.format(feedback=feedback) if feedback else "",
    )


def _defines_a_test(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            return True
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            if any(
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
                for n in node.body
            ):
                return True
    return False


def parse_test_module(reply: str) -> str | None:
    match = _FENCE.search(reply)
    source = (match.group(1) if match else reply).strip() + "\n"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return source if _defines_a_test(tree) else None


async def generate_regression_test(
    client, ev: Evidence, explanation: str, test_context: str, path: str,
    feedback: str | None = None,
) -> str | None:
    import openai

    prompt = build_regression_prompt(ev, explanation, test_context, path, feedback)
    try:
        reply = await client.complete(
            prompt, model=SYNTHESIS_MODEL, max_tokens=MAX_TOKENS, thinking=True
        )
    except (TruncatedResponse, openai.OpenAIError):
        return None
    return parse_test_module(reply)
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_regress_generate.py`
Expected: 12 passed.

- [ ] **Step 6: Commit**

```bash
git add src/chesterton/regress tests/test_regress_generate.py
git commit -m "feat: ask Nemotron Ultra for a regression test beside the covering test"
```

---

### Task 6: Verify the test by execution, both ways

**Files:**
- Create: `src/chesterton/regress/verify.py`
- Test: `tests/test_regress_verify.py`

**Interfaces:**
- Consumes: `SandboxPool`, `BudgetExhausted` (`chesterton.execute.pool`); `SeedRecord`; `Mutant`; `RunResult`.
- Produces:
  - `Verification(status, detail, patch_tail="", mutant_tail="")`, where `status` is one of `"verified"`, `"fails_on_patch"`, `"passes_on_mutant"`, `"invalid_on_mutant"` or `"error"`; plus `.feedback() -> str` for a repair prompt.
  - `async verify_regression_test(pool, seed, mutant, test_path: str, test_src: str) -> Verification`

- [ ] **Step 1: Write the failing tests**

`tests/test_regress_verify.py`:

```python
"""Only a test that passes on the PR and fails on the mutant is shown (spec §9)."""

from chesterton.execute.pool import SandboxPool
from chesterton.regress.verify import verify_regression_test
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import NO_GUARD, a_survivor

MUTANT = a_survivor(NO_GUARD).mutant
PATH = "tests/test_chesterton_regression.py"
SRC = "def test_x():\n    assert True\n"


def runner(on_patch, on_mutant):
    def handler(checkpoint, shell, files):
        mutated = "/testbed/pay.py" in files
        code = on_mutant if mutated else on_patch
        if isinstance(code, str):
            return RunResult("", "", None, None, error=code)
        return RunResult(f"exit {code}", "", code, None)
    return FakeSandboxRunner(handler=handler)


async def verify(seed, r, budget=2):
    pool = SandboxPool(r, op_budget=budget)
    return await verify_regression_test(pool, seed, MUTANT, PATH, SRC), pool


async def test_passing_on_the_pr_and_failing_on_the_mutant_is_verified(demo_seed):
    r = runner(on_patch=0, on_mutant=1)

    v, pool = await verify(demo_seed, r)

    assert v.status == "verified" and pool.ops_used == 2
    assert all(PATH in shell for _, shell in r.calls)
    for files in r.files_written:
        assert files["/testbed/" + PATH] == SRC


async def test_a_test_that_fails_on_the_pr_is_refused(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=1, on_mutant=1))

    assert v.status == "fails_on_patch" and "exit 1" in v.patch_tail


async def test_a_test_the_mutant_also_passes_catches_nothing(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant=0))

    assert v.status == "passes_on_mutant"


async def test_a_mutant_run_that_errors_proves_nothing(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant=2))

    assert v.status == "invalid_on_mutant" and "2" in v.detail


async def test_a_failed_sandbox_operation_is_an_error_not_a_verdict(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant="OperationTimedOutError"))

    assert v.status == "error" and "OperationTimedOutError" in v.detail


async def test_an_exhausted_budget_is_an_error(demo_seed):
    v, _ = await verify(demo_seed, runner(on_patch=0, on_mutant=1), budget=1)

    assert v.status == "error" and "budget" in v.detail


def test_feedback_names_the_status_and_the_relevant_output():
    from chesterton.regress.verify import Verification

    v = Verification("fails_on_patch", "pytest exited 1", patch_tail="E  AssertionError")

    assert "fails_on_patch" in v.feedback() and "AssertionError" in v.feedback()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_regress_verify.py`
Expected: `ModuleNotFoundError: No module named 'chesterton.regress.verify'`.

- [ ] **Step 3: Implement**

`src/chesterton/regress/verify.py`:

```python
"""Run a generated test twice, in two forks of the seed checkpoint.

On the pull request's code it must PASS (pytest exit 0). With the mutant
written over its file it must FAIL (exit 1: tests failed). Anything else
proves nothing, and an unverified test is never rendered (spec §9). This is
the answer to "an uncritical agent may encode a bug as correct behaviour":
execution, not a disclaimer.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from typing import Literal

from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.mutation.model import Mutant
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.record import SeedRecord

Status = Literal["verified", "fails_on_patch", "passes_on_mutant", "invalid_on_mutant", "error"]

VERIFY_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class Verification:
    status: Status
    detail: str
    patch_tail: str = ""
    mutant_tail: str = ""

    def feedback(self) -> str:
        tail = self.patch_tail if self.status == "fails_on_patch" else self.mutant_tail
        return f"{self.status}: {self.detail}\nThe run's output ended:\n{tail}"


def _tail(result: RunResult | None, lines: int = 30) -> str:
    if result is None:
        return ""
    text = "\n".join(s for s in (result.stdout, result.stderr) if s)
    return "\n".join(text.strip().splitlines()[-lines:])


async def _run(pool, seed, command, files) -> RunResult | str:
    try:
        return await pool.run(seed.checkpoint_id, command, files=files, timeout=VERIFY_TIMEOUT_S)
    except BudgetExhausted as exc:
        return str(exc)


async def verify_regression_test(
    pool: SandboxPool, seed: SeedRecord, mutant: Mutant, test_path: str, test_src: str
) -> Verification:
    command = (
        f"cd {shlex.quote(seed.workdir)} && {seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {shlex.quote(test_path)}"
    )
    test_file = {f"{seed.workdir}/{test_path}": test_src}
    on_patch, on_mutant = await asyncio.gather(
        _run(pool, seed, command, test_file),
        _run(pool, seed, command, {**test_file, f"{seed.workdir}/{mutant.file}": mutant.mutated_src}),
    )
    for name, result in (("pull request", on_patch), ("mutant", on_mutant)):
        if isinstance(result, str):
            return Verification("error", f"the {name} run was not made: {result}")
        if result.error is not None:
            return Verification("error", f"the {name} run failed: {result.error}")
    tails = {"patch_tail": _tail(on_patch), "mutant_tail": _tail(on_mutant)}
    if on_patch.exit_code != 0:
        return Verification(
            "fails_on_patch",
            f"pytest exited {on_patch.exit_code} on the pull request's code; it must pass there",
            **tails,
        )
    if on_mutant.exit_code == 0:
        return Verification("passes_on_mutant", "the mutant passes it too, so it catches nothing", **tails)
    if on_mutant.exit_code != 1:
        return Verification(
            "invalid_on_mutant",
            f"pytest exited {on_mutant.exit_code} on the mutant; only a test failure (1) counts",
            **tails,
        )
    return Verification("verified", "passes on the pull request, fails on the mutant", **tails)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_regress_verify.py`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/regress/verify.py tests/test_regress_verify.py
git commit -m "feat: verify a regression test passes on the PR and fails on the mutant"
```

---

### Task 7: Orchestrate a review, with one repair

**Files:**
- Create: `src/chesterton/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `results_from_report` (Task 1), `triage` and `TriageReport` (Task 4), `covering_test_source`, `regression_test_path` and `generate_regression_test` (Task 5), `verify_regression_test` and `Verification` (Task 6), `SandboxPool`, `SeedRecord`.
- Produces:
  - `RegressionTest(path: str, source: str | None, verification: Verification | None, attempts: int, note: str | None = None)` with `.verified -> bool`.
  - `ReviewReport(slug, triage: TriageReport, regression: RegressionTest | None, ops_used, wall_s)` with `.to_json() -> str`, which never includes whole-module sources.
  - `REVIEW_OP_BUDGET = 4`; `MAX_ATTEMPTS = 2`
  - `async review_run(seed: SeedRecord, report: dict, runner, client, *, op_budget=REVIEW_OP_BUDGET) -> ReviewReport`

- [ ] **Step 1: Write the failing tests**

`tests/test_review.py`:

```python
"""A run's survivors in, a triaged review and at most one verified test out."""

import json
from dataclasses import asdict

from chesterton.review import review_run
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import NO_GUARD, ScriptedClient, a_survivor, finding_reply

TEST_PAY = "from pay import charge\n\n\ndef test_charge():\n    assert charge(3) == 3\n"
GOOD = "```python\nimport pytest\nfrom pay import charge\n\n\ndef test_zero():\n    with pytest.raises(ValueError):\n        charge(0)\n```"
BAD = "```python\ndef test_bad():\n    assert 'BAD' == 'bad'\n```"

REPORT = {"results": [asdict(a_survivor(NO_GUARD, rationale="M-GUARD"))]}
TRIAGE, WRITE = "Classify the mutant", "Write one pytest regression test"


def sandbox():
    """The good test passes on the PR and fails on the mutant; BAD fails everywhere."""
    def handler(checkpoint, shell, files):
        test = files.get("/testbed/tests/test_chesterton_regression.py", "")
        if "BAD" in test:
            return RunResult("E  AssertionError", "", 1, None)
        return RunResult("", "", 1 if "/testbed/pay.py" in files else 0, None)
    return FakeSandboxRunner(handler=handler, artifacts={"/testbed/tests/test_pay.py": TEST_PAY})


async def test_the_top_finding_gets_a_test_verified_on_the_first_try(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [GOOD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert len(review.triage.headline) == 1
    test = review.regression
    assert test.verified and test.attempts == 1
    assert test.path == "tests/test_chesterton_regression.py"
    assert review.ops_used == 2
    [write] = [c for c in client.calls if WRITE in c["prompt"]]
    assert "def test_charge" in write["prompt"]  # the covering test, read from the checkpoint


async def test_a_failed_attempt_is_repaired_once_with_its_output(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [BAD, GOOD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression.verified and review.regression.attempts == 2
    second = [c for c in client.calls if WRITE in c["prompt"]][1]
    assert "fails_on_patch" in second["prompt"] and "AssertionError" in second["prompt"]
    assert review.ops_used == 4


async def test_a_test_that_never_verifies_is_kept_but_not_verified(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [BAD, BAD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression.verified is False
    assert review.regression.verification.status == "fails_on_patch"


async def test_no_headline_means_no_test_and_no_sandbox_op(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: finding_reply(confident=False)})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression is None and review.ops_used == 0
    assert not any(WRITE in c["prompt"] for c in client.calls)


async def test_the_json_carries_windows_and_the_test_but_never_whole_modules(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [GOOD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)
    payload = json.loads(review.to_json())

    assert "original_src" not in review.to_json()
    assert payload["regression"]["verified"] is True
    assert "def test_zero" in payload["regression"]["source"]
    assert payload["triage"]["headline"][0]["evidence"]["file"] == "pay.py"
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_review.py`
Expected: `ModuleNotFoundError: No module named 'chesterton.review'`.

- [ ] **Step 3: Implement**

`src/chesterton/review.py`:

```python
"""Review one finished run: triage its survivors, then write one test.

Reads a seed and a run report that already exist, so runs, and the
benchmark built on them, never change. The top headline finding gets a
regression test from the synthesis tier. It is verified in two forks, and
if it fails, it is repaired once with what went wrong. Four sandbox ops at
most. A test that never verified is kept in the report for inspection and
marked unverified; it is never rendered as a finding's answer (spec §9).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from chesterton.execute.pool import SandboxPool
from chesterton.regress.context import covering_test_source
from chesterton.regress.generate import generate_regression_test, regression_test_path
from chesterton.regress.verify import Verification, verify_regression_test
from chesterton.sandbox.protocol import SandboxReadError
from chesterton.seed.record import SeedRecord
from chesterton.triage.evidence import results_from_report
from chesterton.triage.select import TriagedSurvivor, TriageReport, triage

REVIEW_OP_BUDGET = 4
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class RegressionTest:
    path: str
    source: str | None
    verification: Verification | None
    attempts: int
    note: str | None = None

    @property
    def verified(self) -> bool:
        return self.verification is not None and self.verification.status == "verified"


@dataclass(frozen=True)
class ReviewReport:
    slug: str
    triage: TriageReport
    #: For the first headline finding, when there is one.
    regression: RegressionTest | None
    ops_used: int
    wall_s: float

    def to_json(self) -> str:
        payload = _without_modules(asdict(self))
        if self.regression is not None:
            payload["regression"]["verified"] = self.regression.verified
        return json.dumps(payload, indent=2)


def _without_modules(value):
    """Drop each Evidence's whole Mutant: two full modules per survivor."""
    if isinstance(value, dict):
        return {k: _without_modules(v) for k, v in value.items() if k != "mutant"}
    if isinstance(value, list):
        return [_without_modules(v) for v in value]
    return value


async def _regression_for(
    finding: TriagedSurvivor, seed: SeedRecord, runner, pool: SandboxPool, client
) -> RegressionTest:
    ev = finding.evidence
    if not ev.tests:
        return RegressionTest("", None, None, 0, note="no covering test to place a new test beside")
    test_id = ev.tests[0]
    path = regression_test_path(test_id)
    try:
        raw = await runner.read_file(seed.checkpoint_id, f"{seed.workdir}/{test_id.split('::', 1)[0]}")
        context = covering_test_source(raw.decode("utf-8", "replace"), test_id)
    except SandboxReadError:
        context = "(the covering test could not be read)"

    source, verification, feedback = None, None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        source = await generate_regression_test(
            client, ev, finding.classification.explanation, context, path, feedback
        )
        if source is None:
            feedback = "the reply held no parseable test module with a test function"
            continue
        verification = await verify_regression_test(pool, seed, ev.mutant, path, source)
        if verification.status in ("verified", "error"):
            return RegressionTest(path, source, verification, attempt)
        feedback = verification.feedback()
    return RegressionTest(path, source, verification, MAX_ATTEMPTS)


async def review_run(
    seed: SeedRecord, report: dict, runner, client, *, op_budget: int = REVIEW_OP_BUDGET
) -> ReviewReport:
    started = time.perf_counter()
    triaged = await triage(client, results_from_report(report), seed.pr.title)
    pool = SandboxPool(runner, op_budget=op_budget)
    regression = None
    if triaged.headline:
        regression = await _regression_for(triaged.headline[0], seed, runner, pool, client)
    return ReviewReport(
        seed.slug, triaged, regression, pool.ops_used, round(time.perf_counter() - started, 3)
    )
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_review.py`
Expected: 5 passed. Then the full suite.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/review.py tests/test_review.py
git commit -m "feat: review a run: triage, then one test, verified and repaired once"
```

---

### Task 8: The `chesterton review` command

**Files:**
- Modify: `src/chesterton/__main__.py` (parser, `_review`, `_summarise_review`, dispatch in `main`)
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `review_run`, `ReviewReport` (Task 7).
- Produces: `chesterton review SEED RUN --out OUT`. It exits 0 on success and 1 when either input file is missing, and prints a verified test's source only when it verified.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
from dataclasses import asdict  # noqa: E402

from conftest import NO_GUARD, ScriptedClient, a_survivor, finding_reply  # noqa: E402

GOOD_TEST = "```python\nimport pytest\nfrom pay import charge\n\n\ndef test_zero():\n    with pytest.raises(ValueError):\n        charge(0)\n```"


def review_files(tmp_path, demo_seed):
    seed = tmp_path / "seed.json"
    seed.write_text(demo_seed.to_json(), encoding="utf-8")
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"results": [asdict(a_survivor(NO_GUARD))]}), encoding="utf-8")
    return seed, run


def a_reviewing_runner():
    def handler(checkpoint, shell, files):
        return RunResult("", "", 1 if "/testbed/pay.py" in files else 0, None)
    return FakeSandboxRunner(handler=handler, artifacts={"/testbed/tests/test_pay.py": "def test_charge():\n    pass\n"})


def test_review_writes_a_report_and_shows_the_verified_test(tmp_path, demo_seed, capsys):
    seed, run = review_files(tmp_path, demo_seed)
    out = tmp_path / "review.json"
    client = ScriptedClient(by_marker={"Classify the mutant": [finding_reply()] * 3,
                                       "Write one pytest regression test": [GOOD_TEST]})

    code = main(["review", str(seed), str(run), "--out", str(out)],
                runner_factory=a_reviewing_runner, client_factory=lambda: client)

    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["regression"]["verified"] is True
    printed = capsys.readouterr().out
    assert "1 headline" in printed and "pay.py:2-3" in printed
    assert "verified" in printed and "def test_zero" in printed


def test_review_never_prints_an_unverified_test(tmp_path, demo_seed, capsys):
    seed, run = review_files(tmp_path, demo_seed)
    client = ScriptedClient(by_marker={"Classify the mutant": [finding_reply()] * 3,
                                       "Write one pytest regression test": [GOOD_TEST, GOOD_TEST]})

    def passes_everywhere():
        return FakeSandboxRunner(handler=lambda c, s, f: RunResult("", "", 0, None),
                                 artifacts={"/testbed/tests/test_pay.py": "def test_charge():\n    pass\n"})

    code = main(["review", str(seed), str(run), "--out", str(tmp_path / "r.json")],
                runner_factory=passes_everywhere, client_factory=lambda: client)

    assert code == 0
    printed = capsys.readouterr().out
    assert "def test_zero" not in printed and "no verified regression test" in printed


def test_review_without_its_inputs_says_so(tmp_path, capsys):
    code = main(["review", str(tmp_path / "no-seed.json"), str(tmp_path / "no-run.json"),
                 "--out", str(tmp_path / "r.json")])

    assert code == 1
    assert "no seed" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_cli.py`
Expected: the three new tests fail with argparse `invalid choice: 'review'` (SystemExit 2).

- [ ] **Step 3: Implement**

In `src/chesterton/__main__.py`:

1. In `build_parser`, after the `run` subparser and before `return parser`:

```python
    review = commands.add_parser(
        "review", help="triage a run's survivors and write a verified regression test"
    )
    review.add_argument("seed", type=Path, help="a seed record written by `seed`")
    review.add_argument("run", type=Path, help="a run report written by `run`")
    review.add_argument("--out", required=True, type=Path)
```

2. Add below `_run`:

```python
def _summarise_review(review) -> str:
    t = review.triage
    lines = [
        f"{review.slug}: {len(t.headline)} headline, {len(t.worth_a_look)} worth a look, "
        f"{len(t.dismissed)} dismissed; {t.model_calls} triage calls, "
        f"{review.ops_used} sandbox ops, {review.wall_s:.1f}s",
    ]
    for f in t.headline:
        ev, c = f.evidence, f.classification
        lines.append(f"  {ev.file}:{ev.start_line}-{ev.end_line} [{c.category}] {c.explanation}")
    test = review.regression
    if test is not None and test.verified:
        lines.append(f"  regression test {test.path}: verified (passes on the PR, fails on the mutant)")
        lines.append(test.source.rstrip())
    elif test is not None:
        why = test.verification.status if test.verification else (test.note or "no test written")
        lines.append(f"  no verified regression test ({why})")
    return "\n".join(lines)


async def _review(args, runner_factory, client_factory) -> int:
    from chesterton.review import review_run

    for path, what in ((args.seed, "seed"), (args.run, "run report")):
        if not path.is_file():
            print(f"no {what} at {path}", file=sys.stderr)
            return 1
    seed = SeedRecord.from_json(args.seed.read_text(encoding="utf-8"))
    report = json.loads(args.run.read_text(encoding="utf-8"))
    runner = runner_factory()
    try:
        review = await review_run(seed, report, runner, client_factory())
    finally:
        await runner.aclose()
    _write(args.out, review.to_json())
    print(_summarise_review(review))
    return 0
```

Add `import json` at the top of the module if it is not already imported.

3. In `main`, replace the final line with:

```python
    if args.command == "review":
        return asyncio.run(_review(args, runner_factory, client_factory or _default_client))
    return asyncio.run(_run(args, runner_factory, client_factory or _default_client))
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_cli.py`
Expected: all pass, including the 3 new tests. Then the full suite.

- [ ] **Step 5: Commit**

```bash
git add src/chesterton/__main__.py tests/test_cli.py
git commit -m "feat: add chesterton review, printing a regression test only once verified"
```

---

### Task 9: Exploratory measurement on matplotlib-23314

This is not a benchmark and makes no pre-registered claim. It answers two questions before the pitch leans on the feature. Does review produce verified tests on real wrong agent patches? And do those tests encode the agent's behaviour, or the correct one? A verified test that *fails on the gold fix* has encoded the agent's bug as correct: exactly the Trail of Bits hazard §9 cites. It is reported, never hidden.

**Files:**
- Create: `scripts/review_study.py`
- Test: `tests/test_review_study.py`
- Modify: `docs/design/specs/2026-09-18-chesterton-design.md` (§9: what was built; results go in after the live run)

**Interfaces:**
- Consumes: `review_run` (Task 7); `SeedRecord`; `ConTreeSandboxRunner`; `NemotronClient`; `SandboxPool`.
- Produces: `async gold_check(pool, gold_seed, test_path, test_src) -> "passes_on_gold" | "fails_on_gold" | "error"`; `summarise(rows: list[dict]) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_review_study.py`:

```python
"""The exploratory study script is loaded by path, like the other scripts."""

import importlib.util
from pathlib import Path

from chesterton.execute.pool import SandboxPool
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_study.py"
_spec = importlib.util.spec_from_file_location("review_study", _SCRIPT)
study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)


def pool(code=0, error=None):
    runner = FakeSandboxRunner(handler=lambda c, s, f: RunResult("", "", code, None, error=error))
    return SandboxPool(runner, op_budget=1), runner


async def test_a_test_that_passes_on_the_gold_fix_is_consistent_with_it(demo_seed):
    p, runner = pool(0)

    assert await study.gold_check(p, demo_seed, "tests/t.py", "def test_x(): pass\n") == "passes_on_gold"
    [files] = runner.files_written
    assert files == {"/testbed/tests/t.py": "def test_x(): pass\n"}


async def test_a_test_that_fails_on_the_gold_fix_encoded_the_agents_behaviour(demo_seed):
    p, _ = pool(1)

    assert await study.gold_check(p, demo_seed, "tests/t.py", "x") == "fails_on_gold"


async def test_anything_else_on_gold_is_an_error(demo_seed):
    assert await study.gold_check(pool(2)[0], demo_seed, "t.py", "x") == "error"
    assert await study.gold_check(pool(error="boom")[0], demo_seed, "t.py", "x") == "error"


def test_the_summary_counts_each_outcome():
    rows = [
        {"patch": "a", "headline": 1, "verified": True, "gold": "passes_on_gold"},
        {"patch": "b", "headline": 1, "verified": True, "gold": "fails_on_gold"},
        {"patch": "c", "headline": 0, "verified": False, "gold": None},
    ]

    text = study.summarise(rows)

    assert "3 patches" in text and "2 with a headline finding" in text
    assert "2 verified tests" in text
    assert "1 consistent with the gold fix" in text and "1 encode the agent's behaviour" in text
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_review_study.py`
Expected: `FileNotFoundError` for `scripts/review_study.py`.

- [ ] **Step 3: Implement**

`scripts/review_study.py`:

```python
"""EXPLORATORY: does review write verified tests on real wrong agent patches?

Not a benchmark and no pre-registered claim. For each UTBoost-wrong
matplotlib-23314 patch in benchmark-v2, it reviews the run, then runs any
verified regression test against the GOLD fix too:

- passes_on_gold: the test defends behaviour the correct fix shares;
- fails_on_gold: the test encoded the agent's behaviour as correct, the
  hazard spec §9 cites (Trail of Bits). Reported, never hidden.

Usage:
    python scripts/review_study.py <benchmark-dir> <gold-seed.json> <out-dir>

Needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID. About 20 Super calls, up to 2
Ultra calls and up to 5 sandbox ops per patch.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
from pathlib import Path

from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.llm.client import NemotronClient
from chesterton.review import review_run
from chesterton.sandbox.contree import ConTreeSandboxRunner
from chesterton.seed.record import SeedRecord

TASK = "matplotlib__matplotlib-23314"


async def gold_check(pool: SandboxPool, gold_seed: SeedRecord, test_path: str, test_src: str) -> str:
    command = (
        f"cd {shlex.quote(gold_seed.workdir)} && {gold_seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {shlex.quote(test_path)}"
    )
    try:
        result = await pool.run(
            gold_seed.checkpoint_id, command,
            files={f"{gold_seed.workdir}/{test_path}": test_src}, timeout=300.0,
        )
    except BudgetExhausted:
        return "error"
    if result.error is not None:
        return "error"
    return {0: "passes_on_gold", 1: "fails_on_gold"}.get(result.exit_code, "error")


def summarise(rows: list[dict]) -> str:
    verified = [r for r in rows if r["verified"]]
    return "\n".join([
        f"{len(rows)} patches, {sum(r['headline'] > 0 for r in rows)} with a headline finding, "
        f"{len(verified)} verified tests",
        f"  {sum(r['gold'] == 'passes_on_gold' for r in verified)} consistent with the gold fix, "
        f"{sum(r['gold'] == 'fails_on_gold' for r in verified)} encode the agent's behaviour, "
        f"{sum(r['gold'] == 'error' for r in verified)} could not be checked",
    ])


async def main(bench: Path, gold_path: Path, out: Path) -> int:
    pairs = json.loads((bench / "pairs.json").read_text(encoding="utf-8"))
    wrong = sorted({p["wrong"] for p in pairs if p["task"] == TASK})
    gold = SeedRecord.from_json(gold_path.read_text(encoding="utf-8"))
    runner, client = ConTreeSandboxRunner(), NemotronClient()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for patch in wrong:
            stem = Path(patch).stem
            seed = SeedRecord.from_json((bench / "seeds" / TASK / f"{stem}.json").read_text(encoding="utf-8"))
            report = json.loads((bench / "runs" / TASK / f"{stem}.json").read_text(encoding="utf-8"))
            review = await review_run(seed, report, runner, client)
            (out / f"{stem}.json").write_text(review.to_json(), encoding="utf-8", newline="\n")
            test = review.regression
            verdict = None
            if test is not None and test.verified:
                verdict = await gold_check(SandboxPool(runner, op_budget=1), gold, test.path, test.source)
            rows.append({"patch": stem, "headline": len(review.triage.headline),
                         "verified": bool(test and test.verified), "gold": verdict})
            print(f"  {stem}: {rows[-1]}")
    finally:
        await runner.aclose()
    (out / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8", newline="\n")
    print("\nEXPLORATORY, not a benchmark:\n" + summarise(rows))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))))
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_review_study.py`
Expected: 4 passed. Then the full suite.

- [ ] **Step 5: Record what was built in the spec**

In `docs/design/specs/2026-09-18-chesterton-design.md`, at the end of §9 (just before `## 10. Model routing`), add:

```markdown
### As built — 2026-09-23

`chesterton review SEED RUN` reads an existing run, so runs and the benchmark
never change. Decisions the section above left open:

- **Pre-filter:** one rule, right by construction: every changed line is a
  one-line logging, print or warnings call. Anything uncertain goes to the model.
- **Headline:** confident `untested_invariant`, ranked safety first, then by
  how many tests ran it and still passed; at most one per hunk and three per
  run; each confirmed 3 of 3 times, or it is only "worth a look".
- **Regression test:** for the first headline only, written by Ultra beside
  the covering test (`test_chesterton_regression.py`), verified in two forks
  (exit 0 on the PR, exit 1 on the mutant; any other code proves nothing),
  repaired once with the failing output. At most 4 sandbox ops per review.
- **Measured before it is pitched:** `scripts/review_study.py` runs it on
  matplotlib-23314's 13 wrong agent patches and checks each verified test
  against the gold fix. A test that fails on gold encoded the agent's bug and
  is reported as such. Exploratory, not a benchmark.
```

- [ ] **Step 6: Commit**

```bash
git add scripts/review_study.py tests/test_review_study.py docs/design/specs/2026-09-18-chesterton-design.md
git commit -m "feat: explore review on matplotlib-23314's wrong patches, checked against gold"
```

- [ ] **Step 7: Run it live (the human runs this, in the prepared terminal)**

```powershell
python scripts/review_study.py benchmark-v2 seeds/matplotlib-23314.json review-study
```

Paste the summary back. It decides how strongly the pitch can lean on "the test your agent forgot". If `seeds/matplotlib-23314.json`'s checkpoint has been garbage-collected, every gold check reads `error`. Rebuild that seed with `chesterton seed --swebench matplotlib__matplotlib-23314 --slug matplotlib-23314 --python /opt/miniconda3/envs/testbed/bin/python --out seeds/matplotlib-23314.json` and re-run.
