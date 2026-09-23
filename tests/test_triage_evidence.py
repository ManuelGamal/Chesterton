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
