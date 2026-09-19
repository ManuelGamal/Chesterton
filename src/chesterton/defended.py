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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from chesterton.covmap.invert import IMPORT_TIME
from chesterton.filters import is_mutable_source
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
            # An import-time line IS executed, so it is not uncovered. But
            # import time is not a test anyone can run, so it is not offered
            # for selection.
            tests.update(t for t in covering if t != IMPORT_TIME)
        else:
            uncovered.append(line)

    return HunkDefence(hunk=hunk, tests=sorted(tests), uncovered_lines=uncovered)


def defended_hunks(
    hunks: Sequence[Hunk], covmap: CoverageMap
) -> list[HunkDefence]:
    return [_defence(hunk, covmap) for hunk in hunks]


def covering_tests(hunk: Hunk, covmap: CoverageMap) -> list[str]:
    """The tests one mutant of this hunk must run. Never a cross-hunk union."""
    return _defence(hunk, covmap).tests


def uncovered_findings(
    hunks: Sequence[Hunk],
    covmap: CoverageMap,
    changed: Mapping[str, Sequence[int]],
) -> list[tuple[str, int]]:
    """Tier-0 findings: (file, line) for every CHANGED line no test executes.

    Hunks are deliberately wider than the lines the PR touched — semantic
    grouping expands to whole statements so mutation operators have something
    meaningful to work on. Findings must not inherit that width: a
    continuation line the author never touched, which coverage.py cannot even
    record, is not evidence of anything. Intersect with the changed set.

    Only mutable sources can carry a finding. A README or a lockfile has no
    coverage to find, so every changed line of it would read as "no test
    defends this" — fabricated evidence. A test file is not code the suite
    defends; it is the suite.
    """
    changed_by_file = {file: set(lines) for file, lines in changed.items()}
    sources = [hunk for hunk in hunks if is_mutable_source(hunk.file)]
    return [
        (defence.hunk.file, line)
        for defence in defended_hunks(sources, covmap)
        for line in defence.uncovered_lines
        if line in changed_by_file.get(defence.hunk.file, set())
    ]
