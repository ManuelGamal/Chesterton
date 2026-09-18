"""Turn a coverage contexts report into {file: {line: [test ids]}}.

The capture is two commands, run single-threaded inside the baseline
checkpoint. Dynamic contexts are unreliable under pytest-xdist.

Note the flag: pytest-cov takes `--cov-context=test`. `test_function` is
coverage.py's own `dynamic_context` setting value and is not valid here.

The empty-string context means "executed outside any test", which for our
purposes is the same as undefended.
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


def _clean(context: str) -> str | None:
    """'tests/t.py::test_x|run' -> 'tests/t.py::test_x'; '' -> None."""
    name = context.split("|", 1)[0]
    return name or None


def invert_coverage(report: dict) -> CoverageMap:
    covmap: CoverageMap = {}
    for path, file_report in report.get("files", {}).items():
        lines: dict[int, list[str]] = {}
        for line_str, contexts in file_report.get("contexts", {}).items():
            cleaned = [name for name in (_clean(c) for c in contexts) if name]
            lines[int(line_str)] = sorted(set(cleaned))
        covmap[normalise_path(path)] = lines
    return covmap


def load_coverage(path: Path) -> CoverageMap:
    return invert_coverage(json.loads(Path(path).read_text()))
