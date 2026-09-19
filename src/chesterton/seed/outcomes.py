"""Per-test outcomes from pytest's `-rA` short summary, and which tests are
safe to select.

A test is SELECTABLE only if it passed in every baseline run. Two other kinds
are excluded, for different reasons:

- flaky: its outcome differed between runs, or it was not collected every
  time. A mutant "killed" by a flaky test may have been killed by chance,
  which is a fabricated kill.
- failing: it never passed (failed, errored, xfailed). It fails with or
  without the mutant, so it would report every mutant as killed.

The ids are pytest node ids. That is what `-rA` prints and what pytest-cov
records as a coverage context, so the two join without translation. JUnit XML
was rejected: its dotted classnames do not round-trip to node ids for test
classes or parametrised tests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

PASSED = "PASSED"

#: "PASSED tests/t.py::test_x" or "FAILED tests/t.py::test_y - Error: ...".
#: SKIPPED lines have a different shape ("SKIPPED [1] file:line: reason") and
#: are deliberately not matched: a skipped test defends nothing.
_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS)\s+(\S+)")


def parse_outcomes(report: str) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for line in report.splitlines():
        match = _LINE.match(line)
        if match is None:
            continue
        status, node = match.groups()
        # One test can be reported twice (a pass in call, then an error in
        # teardown). Any non-pass is sticky.
        if outcomes.get(node, PASSED) == PASSED:
            outcomes[node] = status
    return outcomes


@dataclass(frozen=True)
class Selectability:
    selectable: frozenset[str]
    flaky: frozenset[str]
    failing: frozenset[str]


def classify_runs(runs: Sequence[Mapping[str, str]]) -> Selectability:
    if not runs:
        raise ValueError("classify_runs needs at least one run")

    every: set[str] = set()
    for run in runs:
        every.update(run)

    selectable: set[str] = set()
    flaky: set[str] = set()
    failing: set[str] = set()
    for node in every:
        seen = [run.get(node) for run in runs]
        if all(status == PASSED for status in seen):
            selectable.add(node)
        elif None in seen or PASSED in seen:
            flaky.add(node)
        else:
            failing.add(node)

    return Selectability(frozenset(selectable), frozenset(flaky), frozenset(failing))
