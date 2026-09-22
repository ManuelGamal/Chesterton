"""The screening script is a script, not library code, so it is loaded by path.

Live 2026-09-22: 12 of the 22 UTBoost tasks screened to nothing usable.
- 8 read "apply_failed:augmented", with git saying "corrupt patch at line
  33". UTBoost's test patches end without a final newline, so git rejects
  the last line.
- 5 sympy tasks read "fails_original" for every patch, although SWE-bench
  resolved them all: "No module named pytest". SWE-bench runs sympy with
  its own bin/test, so the image never had pytest.
"""

import importlib.util
import json
from pathlib import Path

from chesterton.execute.pool import SandboxPool
from chesterton.sandbox.fake import FakeSandboxRunner

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "screen_agent_patches.py"
_spec = importlib.util.spec_from_file_location("screen_agent_patches", _SCRIPT)
screening = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(screening)

AGENT_PATCH = (
    "diff --git a/pkg/a.py b/pkg/a.py\n"
    "--- a/pkg/a.py\n"
    "+++ b/pkg/a.py\n"
    "@@ -1 +1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
)
# As UTBoost ships it: the last line has no newline.
UNTERMINATED = (
    "diff --git a/tests/test_a.py b/tests/test_a.py\n"
    "--- a/tests/test_a.py\n"
    "+++ b/tests/test_a.py\n"
    "@@ -1 +1,2 @@\n"
    " import pkg\n"
    "+assert pkg.x == 2"
)


async def test_every_patch_reaches_the_sandbox_with_a_final_newline(tmp_path):
    task = tmp_path / "task-1"
    task.mkdir()
    (task / "summary.json").write_text(json.dumps([{"patch": "p.diff"}]), encoding="utf-8")
    (task / "p.diff").write_text(AGENT_PATCH.rstrip("\n"), encoding="utf-8")
    rows = {"FAIL_TO_PASS": ["tests/test_a.py::test_x"], "test_patch": UNTERMINATED}
    runner = FakeSandboxRunner()

    await screening.screen(SandboxPool(runner), "task-1", tmp_path, rows, rows)

    [written] = runner.files_written
    assert all(text.endswith("\n") for text in written.values())


def a_script() -> str:
    return screening.screen_script(["tests/test_a.py::test_x"], ["tests/test_a.py::test_y"])


def test_utboosts_patch_falls_back_to_fuzzy_patch_as_the_agents_does():
    script = a_script()

    fuzzy = f"patch --batch --fuzz=5 -p1 --no-backup-if-mismatch -i {screening.AUGMENTED}"
    assert fuzzy in script
    # Checked dry first: a half-applied test patch would screen garbage.
    assert f"patch --dry-run --batch --fuzz=5 -p1 -i {screening.AUGMENTED}" in script


def test_pytest_is_installed_before_the_first_test_run_when_the_image_lacks_it():
    lines = a_script().splitlines()

    install = next(i for i, line in enumerate(lines) if "pip install -q pytest" in line)
    first_run = next(i for i, line in enumerate(lines) if "-m pytest" in line)
    assert install < first_run
    # Only when missing: the install sits behind a failed import.
    check, _, fallback = lines[install].partition(" || ")
    assert "-c 'import pytest'" in check and "pip install" in fallback
