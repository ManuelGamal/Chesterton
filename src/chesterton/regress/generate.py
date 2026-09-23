"""Ask Nemotron Ultra for the test the suite is missing (spec §9).

One call for the top finding, on the synthesis tier. The reply is a whole
test module. Nothing here trusts it: `verify` runs it before anyone sees
it, and a test that does not pass on the pull request and fail on the
mutant is never rendered.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from chesterton.llm.client import SYNTHESIS_MODEL, TruncatedResponse
from chesterton.triage.evidence import Evidence

REGRESSION_FILE = "test_chesterton_regression.py"
#: Thinking plus a whole test module.
MAX_TOKENS = 16384

_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class Generation:
    """One attempt at writing the regression test.

    `failure` names the real reason `source` is None ("truncated",
    "unavailable" or "unparseable"), so a repair prompt or a report note
    never calls a truncated reply "no parseable test module" (spec §9, F3).
    """

    source: str | None
    failure: str | None = None


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
) -> Generation:
    import openai

    prompt = build_regression_prompt(ev, explanation, test_context, path, feedback)
    try:
        reply = await client.complete(
            prompt, model=SYNTHESIS_MODEL, max_tokens=MAX_TOKENS, thinking=True
        )
    except TruncatedResponse:
        return Generation(None, "truncated")
    except openai.OpenAIError:
        return Generation(None, "unavailable")
    source = parse_test_module(reply)
    return Generation(source, None if source is not None else "unparseable")
