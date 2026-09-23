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


def _changed_span(before: list[str], after: list[str]) -> tuple[int, int, int]:
    """The 1-based first differing line, and each list's last differing line.

    Some operators edit past their own recorded hunk (`remove_cleanup` empties
    a whole `finally` body; `delete_guard` removes a whole guard block), so
    start_line/end_line alone cannot be trusted to bound the change. This
    finds the real extent from the common prefix and suffix of the two
    module's line lists, the way `difflib` itself would.
    """
    n = min(len(before), len(after))
    prefix = 0
    while prefix < n and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    limit = n - prefix
    while suffix < limit and before[len(before) - 1 - suffix] == after[len(after) - 1 - suffix]:
        suffix += 1
    return prefix + 1, len(before) - suffix, len(after) - suffix


def evidence_for(result: MutantResult, pr_title: str, context: int = CONTEXT_LINES) -> Evidence:
    mutant = result.mutant
    before, after = _lines(mutant.original_src), _lines(mutant.mutated_src)
    # The mutation can add or remove lines; the after-side hunk end moves with it.
    shift = len(after) - len(before)

    change_first, change_last_before, change_last_after = _changed_span(before, after)
    # The display window covers the union of the real change and the hunk
    # the operator recorded, plus context, so a change that reaches past its
    # own hunk is never cut off.
    union_first = min(change_first, mutant.start_line)
    union_last_before = max(change_last_before, mutant.end_line)
    union_last_after = max(change_last_after, mutant.end_line + shift)

    first = max(1, union_first - context)
    last_before = min(len(before), union_last_before + context)
    last_after = min(len(after), union_last_after + context)

    window_before = before[first - 1 : last_before]
    window_after = after[first - 1 : last_after]
    diff = "\n".join(
        line
        for line in difflib.unified_diff(
            window_before, window_after,
            fromfile=f"a/{mutant.file}", tofile=f"b/{mutant.file}", lineterm="",
        )
        # The @@ header is numbered relative to the window, not the file;
        # dropping it avoids showing a misleading line number.
        if not line.startswith("@@")
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
