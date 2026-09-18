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


def covering_tests(hunk: Hunk, covmap: CoverageMap) -> list[str]:
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
