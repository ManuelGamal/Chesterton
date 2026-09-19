"""Turn a coverage contexts report into {file: {line: [test ids]}}.

The capture is two commands, run single-threaded inside the baseline
checkpoint. Dynamic contexts are unreliable under pytest-xdist.

Note the flag: pytest-cov takes `--cov-context=test`. `test_function` is
coverage.py's own `dynamic_context` setting value and is not valid here.

The empty-string context means "executed outside any test": at import,
while pytest collects. It is recorded as IMPORT_TIME, not dropped. Phase 1
dropped it as "undefended", and live on nomenclature-284 (2026-09-19) that
made a changed `from nomenclature.validation import log_error` a tier-0
finding, "no test executes this line", on a line every run executes. Import
time is execution, so tier 0 must not report it; it is never a test id that
can be selected either, and consumers filter it out of test selection.
"""

from __future__ import annotations

import json
from pathlib import Path

from chesterton.models import CoverageMap
from chesterton.paths import normalise_path

COVERAGE_CAPTURE_COMMANDS = (
    "pytest --cov --cov-context=test -p no:randomly",
    "coverage json --show-contexts -o coverage.json",
)


#: Stands in for the empty context: executed at import, outside any test.
#: Angle brackets cannot appear in a pytest node id, so it never collides.
IMPORT_TIME = "<import>"


def _clean(context: str) -> str:
    """'tests/t.py::test_x|run' -> 'tests/t.py::test_x'; '' -> IMPORT_TIME."""
    name = context.split("|", 1)[0]
    return name or IMPORT_TIME


def invert_coverage(report: dict) -> CoverageMap:
    covmap: CoverageMap = {}
    for path, file_report in report.get("files", {}).items():
        lines: dict[int, list[str]] = {}
        for line_str, contexts in file_report.get("contexts", {}).items():
            lines[int(line_str)] = sorted({_clean(c) for c in contexts})
        covmap[normalise_path(path)] = lines
    return covmap


def executable_lines(report: dict) -> dict[str, list[int]]:
    """Per file, every line coverage.py treats as a statement.

    That is executed_lines plus missing_lines. Any other line (a closing
    bracket, a blank, a comment) has no bytecode, so coverage can never
    record it as run. Live on xarray-7393 (2026-09-19), a changed closing `)`
    was reported as a tier-0 finding for exactly that reason.
    """
    return {
        normalise_path(path): sorted(
            set(file_report.get("executed_lines", []))
            | set(file_report.get("missing_lines", []))
        )
        for path, file_report in report.get("files", {}).items()
    }


def load_coverage(path: Path) -> CoverageMap:
    return invert_coverage(json.loads(Path(path).read_text()))
