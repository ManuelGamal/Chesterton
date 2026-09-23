"""The streamed coverage export must say exactly what `coverage json` said.

Live 2026-09-22 (benchmark v2): every matplotlib-14623 patch touching
lib/matplotlib/axes/_base.py failed to seed. The baseline passed, and then
`coverage json --show-contexts` was OOM-killed, because nearly all ~580
tests run nearly every line of that file and the reporter builds the whole
line-by-test matrix at once. The streamed export writes one record per
(file, test) instead, and the matrix is assembled on this side.

v1 seeds built with the old export are reused, so the two must agree
exactly. This runs REAL pytest and coverage on a tiny project and compares.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from chesterton.covmap.invert import (
    IMPORT_TIME,
    executable_lines,
    invert_coverage,
    read_streamed_coverage,
)
from chesterton.covmap.stream import EXPORTER_SOURCE

pytest.importorskip("pytest_cov")

MODULE = '''\
LIMIT = 10


def clamp(x):
    if x > LIMIT:
        return LIMIT
    total = (x +
             0)
    return total


def unused():
    return 1
'''
TESTS = '''\
from pkg.mod import clamp


def test_low():
    assert clamp(3) == 3


def test_high():
    assert clamp(30) == 10
'''


# Branch mode stores arcs, not lines, and a repository's own coverage
# config can switch it on, so both modes must agree.
@pytest.fixture(scope="module", params=["lines", "branches"])
def measured(tmp_path_factory, request) -> Path:
    root = tmp_path_factory.mktemp("proj")
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "mod.py").write_text(MODULE)
    (root / "pkg" / "other.py").write_text("X = 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_mod.py").write_text(TESTS)
    (root / "pytest.ini").write_text("[pytest]\n")  # keep this repo's config out
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--cov", "--cov-context=test", "--cov-report=", "tests",
         *(["--cov-branch"] if request.param == "branches" else [])],
        cwd=root, check=True, capture_output=True,
    )
    return root


def old_export(root: Path) -> dict:
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", "--show-contexts",
         "-o", "old.json", "--include=pkg/mod.py"],
        cwd=root, check=True, capture_output=True,
    )
    return json.loads((root / "old.json").read_text())


def new_export(root: Path, *targets: str) -> str:
    script = root / "export_coverage.py"
    script.write_text(EXPORTER_SOURCE)
    done = subprocess.run(
        [sys.executable, str(script), str(root), *targets],
        cwd=root, check=True, capture_output=True, text=True,
    )
    return done.stdout


def test_the_streamed_map_equals_the_json_reports(measured):
    old = old_export(measured)
    covmap, executable = read_streamed_coverage(new_export(measured, "pkg/mod.py"))

    assert covmap == invert_coverage(old)
    assert executable == executable_lines(old)
    # Sanity: the comparison is not vacuous.
    [mod] = covmap
    assert covmap[mod][6] == ["tests/test_mod.py::test_high"]
    assert covmap[mod][1] == [IMPORT_TIME]


def test_only_the_named_sources_are_exported(measured):
    covmap, executable = read_streamed_coverage(new_export(measured, "pkg/mod.py"))

    assert [Path(f).name for f in covmap] == ["mod.py"]
    assert [Path(f).name for f in executable] == ["mod.py"]


def test_a_missing_data_file_fails_loudly(tmp_path):
    script = tmp_path / "export_coverage.py"
    script.write_text(EXPORTER_SOURCE)

    done = subprocess.run(
        [sys.executable, str(script), str(tmp_path), "pkg/mod.py"],
        cwd=tmp_path, capture_output=True, text=True,
    )

    assert done.returncode == 1
    assert "no coverage data" in done.stderr
