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
