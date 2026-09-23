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
