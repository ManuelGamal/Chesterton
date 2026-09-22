"""The benchmark driver is a script, not library code, so it is loaded by path.

Live 2026-09-22 (benchmark v1): the rate's denominator counted every line of
an agent's scratch script, because a file with no coverage record fell back
to "all changed lines". One control scored 650 changed lines against a real
17, which drowned its rate.
"""

import importlib.util
from dataclasses import replace
from pathlib import Path

from chesterton.github.swebench import task_from_row

from test_github_swebench import ROW, TESTS
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


# --- the dataset is read once, and no seed can end the study ---------------
# Live 2026-09-22 (v2 seeding): seed_for downloaded the SWE-bench dataset
# once PER SEED, outside its try. At 231 builds the dataset API answered
# HTTP 429, the exception escaped, and the whole study stopped.

async def test_every_task_is_fetched_in_one_scan():
    calls = []

    async def fetch_rows(ids, **_):
        calls.append(sorted(ids))
        return {ROW["instance_id"]: ROW}

    bases, missing = await benchmark.fetch_bases(
        ["pydata__xarray-7393", "pydata__xarray-7393", "psf__requests-1"], fetch_rows=fetch_rows
    )

    assert calls == [["psf__requests-1", "pydata__xarray-7393"]]
    assert bases["pydata__xarray-7393"].instance_id == "pydata__xarray-7393"
    assert missing == ["psf__requests-1"]


async def test_a_seed_that_fails_before_its_build_is_recorded_not_raised(tmp_path):
    task = "pydata__xarray-7393"
    (tmp_path / task).mkdir()
    # Only test files: with_patch refuses it, before any sandbox op.
    (tmp_path / task / "only-tests.diff").write_text(TESTS, encoding="utf-8")
    out = tmp_path / "out"

    path = await benchmark.seed_for(
        None, tmp_path, out, task, "only-tests.diff", base=task_from_row(ROW)
    )

    assert path is None
    assert (out / "seeds" / task / "only-tests.error.txt").exists()
