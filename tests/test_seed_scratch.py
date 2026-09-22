"""Which files a patch created that no baseline run ever executed.

Live 2026-09-22 (benchmark v1): 23 of 78 agent patches carried scratch
scripts such as reproduce_issue.py and debug_where2.py. No test imports
them, so tier 0 reported every line as "no test executes this line", and
their hunks used up the whole mutant budget of 8 runs. A patch is only
exempt when both hold: it CREATED the file, and coverage never saw it run.
"""

from dataclasses import replace

from chesterton.run import run_seed
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import DEMO_DIFF

SCRATCH_DIFF = DEMO_DIFF + (
    "diff --git a/reproduce_issue.py b/reproduce_issue.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/reproduce_issue.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+from pay import charge\n"
    "+print(charge(0))\n"
)
SCRATCH_SRC = "from pay import charge\nprint(charge(0))\n"


def with_scratch(seed, executable):
    return replace(
        seed,
        pr=replace(seed.pr, diff=SCRATCH_DIFF),
        sources={**seed.sources, "reproduce_issue.py": SCRATCH_SRC},
        executable=executable,
    )


def test_a_created_file_no_run_executed_is_unexercised(demo_seed):
    seed = with_scratch(demo_seed, {"pay.py": [1, 2, 3, 4]})

    assert seed.unexercised_new_files() == frozenset({"reproduce_issue.py"})


def test_a_created_file_the_tests_import_is_kept(demo_seed):
    # A new helper module the fix really uses gets imported, so coverage
    # records it; it is part of the program under test.
    seed = with_scratch(demo_seed, {"pay.py": [1, 2, 3, 4], "reproduce_issue.py": [1, 2]})

    assert seed.unexercised_new_files() == frozenset()


def test_an_edited_file_is_never_exempt_even_when_nothing_ran_it(demo_seed):
    # pay.py is edited, not created: an unexecuted edit is a real finding.
    seed = replace(demo_seed, executable={"other.py": [1]})

    assert seed.unexercised_new_files() == frozenset()


def test_a_seed_without_executable_data_exempts_nothing(demo_seed):
    # Seeds built before executable lines were recorded carry {}: with no
    # data, every created file would look unexecuted, so none is exempt.
    seed = with_scratch(demo_seed, {})

    assert seed.unexercised_new_files() == frozenset()


def test_only_source_files_are_listed_since_tests_and_docs_are_never_mutated(demo_seed):
    diff = SCRATCH_DIFF + (
        "diff --git a/test_fix.py b/test_fix.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/test_fix.py\n"
        "@@ -0,0 +1 @@\n"
        "+assert True\n"
    )
    seed = with_scratch(demo_seed, {"pay.py": [1, 2, 3, 4]})
    seed = replace(seed, pr=replace(seed.pr, diff=diff))

    assert seed.unexercised_new_files() == frozenset({"reproduce_issue.py"})


# --- the run leaves them out, and says so -------------------------------


def suite_passes(checkpoint, shell, files):
    return RunResult("", "", 0, None)


async def test_a_run_reports_no_tier0_or_mutant_in_an_unexercised_new_file(demo_seed):
    seed = with_scratch(demo_seed, {"pay.py": [1, 2, 3, 4]})

    report = await run_seed(seed, FakeSandboxRunner(handler=suite_passes), reduce=False)

    assert [f for f, _ in report.tier0 if f == "reproduce_issue.py"] == []
    assert all(r.mutant.file == "pay.py" for r in report.results)
    assert ("pay.py", 3) in report.tier0  # the real finding is untouched
    assert report.excluded_files == ["reproduce_issue.py"]


async def test_ddmin_does_not_count_an_unexercised_new_file_as_undefended(demo_seed):
    seed = with_scratch(demo_seed, {"pay.py": [1, 2, 3, 4]})

    report = await run_seed(seed, FakeSandboxRunner(handler=suite_passes))

    assert report.surface.hunks == ("pay.py#0",)
    assert report.surface.skipped.get("unexercised_new_file") == 1
