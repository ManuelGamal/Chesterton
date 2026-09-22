"""The benchmark driver is a script, not library code, so it is loaded by path.

Live 2026-09-22 (benchmark v1): the rate's denominator counted every line of
an agent's scratch script, because a file with no coverage record fell back
to "all changed lines". One control scored 650 changed lines against a real
17, which drowned its rate.
"""

import importlib.util
from dataclasses import replace
from pathlib import Path

from test_seed_scratch import with_scratch

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py"
_spec = importlib.util.spec_from_file_location("benchmark_script", _SCRIPT)
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)


def test_the_denominator_counts_executable_changed_lines(demo_seed):
    # pay.py gains lines 2 and 3; both can execute.
    seed = replace(demo_seed, executable={"pay.py": [1, 2, 3, 4]})

    assert benchmark.changed_executable_lines(seed) == 2


def test_an_unexercised_new_file_adds_nothing_to_the_denominator(demo_seed):
    seed = with_scratch(demo_seed, {"pay.py": [1, 2, 3, 4]})

    assert benchmark.changed_executable_lines(seed) == 2


# --- a failed seed build leaves its reason behind ---------------------------
# Live 2026-09-22: every matplotlib-14623 patch touching axes/_base.py failed
# to seed (21 of 21), and the reason went only to stdout. Nothing on disk
# could say whether it was memory, a patch that would not apply, or a timeout.


def test_a_failed_build_writes_its_full_reason_next_to_the_seeds(tmp_path):
    error = RuntimeError("the seed build script exited 1\n" + "x" * 5000)

    path = benchmark.record_seed_failure(tmp_path, "task-1", "abc123.diff", error)

    assert path == tmp_path / "seeds" / "task-1" / "abc123.error.txt"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("RuntimeError: the seed build script exited 1")
    assert text.endswith("x" * 5000)  # untruncated, unlike the console line


def test_a_later_successful_build_clears_the_old_reason(tmp_path):
    benchmark.record_seed_failure(tmp_path, "task-1", "abc123.diff", RuntimeError("boom"))

    benchmark.clear_seed_failure(tmp_path, "task-1", "abc123.diff")

    assert not (tmp_path / "seeds" / "task-1" / "abc123.error.txt").exists()
