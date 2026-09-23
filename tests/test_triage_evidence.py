"""What triage sees about one surviving mutant."""

import json

from chesterton.run import run_seed
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from chesterton.triage.evidence import evidence_for, results_from_report

from conftest import NO_GUARD, T_CHARGE, a_survivor


def test_evidence_shows_the_numbered_code_before_and_after():
    ev = evidence_for(a_survivor(NO_GUARD, rationale="drop the guard"), "Require an amount")

    assert "    2 |     if not amount:" in ev.original
    assert "raise" not in ev.mutated
    assert "    2 |     return amount" in ev.mutated
    assert '-        raise ValueError("required")' in ev.diff
    assert ev.tests == (T_CHARGE,)
    assert (ev.file, ev.start_line, ev.end_line) == ("pay.py", 2, 3)
    assert ev.rationale == "drop the guard"
    assert ev.pr_title == "Require an amount"


def test_the_window_is_the_hunk_plus_context_not_the_module():
    module = "".join(f"x{i} = {i}\n" for i in range(1, 101))
    mutated = module.replace("x50 = 50\n", "x50 = 0\n")
    result = a_survivor(mutated, start=50, end=50, original=module)

    ev = evidence_for(result, "t", context=3)

    assert "   47 | x47 = 47" in ev.original and "   53 | x53 = 53" in ev.original
    assert "x46" not in ev.original and "x54" not in ev.original
    assert "   50 | x50 = 0" in ev.mutated


async def test_results_rebuild_exactly_from_a_run_report(demo_seed):
    def survive(checkpoint, shell, files):
        return RunResult("", "", 0, None)

    report = await run_seed(demo_seed, FakeSandboxRunner(handler=survive), reduce=False)

    rebuilt = results_from_report(json.loads(report.to_json()))

    assert rebuilt == report.results
    assert any(r.verdict == "survived" for r in rebuilt)


# F1: an operator can edit past its own recorded hunk (`remove_cleanup` empties
# a whole `finally` body; `delete_guard` removes a whole guard block). Live
# 2026-09-23: the window was built from start_line..end_line +/- context, so
# the display cut off before the real end of the change, and the pre-filter
# (which read that same window) called a resource-cleanup survivor
# "logging_only" without ever seeing the removed `conn.close()`.
CLEANUP_BEFORE = (
    "def process():\n"
    "    try:\n"
    "        do_work()\n"
    "    finally:\n"
    '        log.info("step 1")\n'
    '        log.info("step 2")\n'
    '        log.info("step 3")\n'
    '        log.info("step 4")\n'
    '        log.info("step 5")\n'
    '        log.info("step 6")\n'
    "        conn.close()\n"
)
CLEANUP_AFTER = (
    "def process():\n"
    "    try:\n"
    "        do_work()\n"
    "    finally:\n"
    "        pass\n"
)


def test_a_mutation_that_edits_past_its_hunk_is_shown_in_full():
    # The operator only recorded line 5 (the first log call) as its hunk, but
    # its edit reaches through line 11 (conn.close()).
    result = a_survivor(CLEANUP_AFTER, start=5, end=5, original=CLEANUP_BEFORE)

    ev = evidence_for(result, "t", context=3)

    assert "conn.close()" in ev.original
    assert "conn.close()" not in ev.mutated
    assert "-        conn.close()" in ev.diff


def test_a_hunk_at_the_first_line_clamps_instead_of_going_negative():
    module = "".join(f"x{i} = {i}\n" for i in range(1, 11))
    mutated = module.replace("x1 = 1\n", "x1 = 0\n")
    result = a_survivor(mutated, start=1, end=1, original=module)

    ev = evidence_for(result, "t", context=3)

    assert "    1 | x1 = 0" in ev.mutated
    assert "x-1" not in ev.mutated and "x0" not in ev.mutated


def test_a_hunk_at_the_last_line_clamps_at_the_bottom():
    module = "".join(f"x{i} = {i}\n" for i in range(1, 11))
    mutated = module.replace("x10 = 10\n", "x10 = 0\n")
    result = a_survivor(mutated, start=10, end=10, original=module)

    ev = evidence_for(result, "t", context=3)

    assert "   10 | x10 = 0" in ev.mutated
    assert ev.original.strip().splitlines()[-1] == "   10 | x10 = 10"


def test_context_larger_than_the_file_clamps_both_edges():
    module = "".join(f"x{i} = {i}\n" for i in range(1, 6))
    mutated = module.replace("x3 = 3\n", "x3 = 0\n")
    result = a_survivor(mutated, start=3, end=3, original=module)

    ev = evidence_for(result, "t", context=100)

    assert ev.original.splitlines()[0] == "    1 | x1 = 1"
    assert ev.mutated.splitlines()[-1] == "    5 | x5 = 5"
