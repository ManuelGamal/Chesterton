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

COORDINATE CONTRACT. `source` must be the post-patch file content at head, and
`lines` must be post-patch coordinates as emitted by `changed_lines`. Passing
source from one tree with line numbers from another does not fail loudly — it
expands to spans over unrelated content and reports them with full confidence.
The bounds check below turns the detectable half of that mistake into an error.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence

from chesterton.models import Hunk
from chesterton.paths import normalise_path

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


def _check_coordinates(source: str, lines: Sequence[int]) -> None:
    """Reject line numbers that cannot belong to this source.

    A line outside the file is the visible symptom of a coordinate-system
    mismatch — most often `source` taken from the base tree while `lines` are
    post-patch. Unguarded, that degrades silently into confident hunks over
    unrelated content, which is the exact failure mode this project exists to
    eliminate. Only the detectable half is caught here: a mismatch that happens
    to land in range still passes, so the contract in the module docstring
    remains the real defence.
    """
    total = len(source.splitlines())
    outside = [n for n in lines if n < 1 or n > total]
    if outside:
        raise ValueError(
            f"line numbers {outside} fall outside a {total}-line source; "
            "source and lines are probably from different trees"
        )


def semantic_hunks(source: str, path: str, lines: Sequence[int]) -> list[Hunk]:
    _check_coordinates(source, lines)
    path = normalise_path(path)
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
