import json
from dataclasses import replace

import openai
import pytest

from chesterton.covmap.invert import IMPORT_TIME
from chesterton.run import RunRefused, restrict_coverage, run_seed
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import T_CHARGE, T_FLAKY


def guard_matters_to_mutants_but_not_to_the_suite(checkpoint, shell, files):
    """Mutant runs name a test id and die unless the guard's raise survives.
    Surface probes deselect tests, and the suite passes either way, so the
    guard is undefended."""
    if "--deselect" in shell:
        return RunResult("", "", 0, None)
    written = files.get("/testbed/pay.py", "")
    return RunResult("", "", 1 if "raise ValueError" in written else 0, None)


class _Client:
    def __init__(self, reply=None, raises=None):
        self.reply, self.raises, self.calls = reply, raises, 0

    async def complete(self, prompt, *, model, max_tokens=2048, thinking=False):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.reply


async def test_a_deterministic_run_reports_verdicts_tier0_and_the_surface(demo_seed):
    runner = FakeSandboxRunner(handler=guard_matters_to_mutants_but_not_to_the_suite)

    report = await run_seed(demo_seed, runner)

    assert report.hunks == 1
    assert report.generated == len(report.results) > 0
    assert report.counts.survived >= 1  # deleting the guard goes unnoticed
    assert report.model is None
    # Line 3 is executed only by a flaky test, so it is undefended (P3-6).
    assert ("pay.py", 3) in report.tier0
    assert report.surface.undefended == ("pay.py#0",)
    assert report.ops_used <= report.op_budget


async def test_a_run_that_cannot_afford_its_mutants_refuses_before_any_op(demo_seed):
    runner = FakeSandboxRunner()

    with pytest.raises(RunRefused, match="refusing to start"):
        await run_seed(demo_seed, runner, op_budget=0)

    assert runner.calls == []


async def test_the_refusal_counts_import_time_mutants_that_will_cost_an_op(demo_seed):
    # Every line of the guard hunk runs only at import, so every mutant runs
    # the whole suite. Counting only coverage-selected mutants would let this
    # run start with a budget it cannot pay.
    seed = replace(
        demo_seed,
        coverage={"pay.py": {line: [IMPORT_TIME] for line in (1, 2, 3, 4)}},
    )
    runner = FakeSandboxRunner()

    with pytest.raises(RunRefused, match="refusing to start"):
        await run_seed(seed, runner, op_budget=0)

    assert runner.calls == []


async def test_malformed_model_replies_are_retried_once_then_counted(demo_seed):
    client = _Client(reply="not json at all")

    report = await run_seed(demo_seed, FakeSandboxRunner(), client=client, reduce=False)

    assert client.calls == 2  # one hunk, one retry
    assert report.model.calls == 2
    assert report.model.retried == 1
    assert report.model.failures == {"malformed": 1}
    assert report.generated > 0  # deterministic mutants still ran


async def test_an_unavailable_model_falls_back_to_deterministic_mutants(demo_seed):
    client = _Client(raises=openai.OpenAIError("down"))

    report = await run_seed(demo_seed, FakeSandboxRunner(), client=client, reduce=False)

    assert report.model.failures == {"unavailable": 1}
    assert report.generated > 0


async def test_a_well_formed_proposal_reaches_the_sandbox(demo_seed):
    reply = json.dumps({"mutants": [{
        "mutated_src": "    if amount is None:\n        raise ValueError(\"required\")\n",
        "rationale": "only None is rejected now",
    }]})

    report = await run_seed(
        demo_seed, FakeSandboxRunner(), client=_Client(reply=reply), reduce=False
    )

    assert any(r.mutant.source == "llm" for r in report.results)
    assert report.model.failures == {}


async def test_tier0_skips_changed_lines_that_cannot_execute(demo_seed):
    # Pretend line 3 (the flaky-only `raise`) had no bytecode: it must then
    # drop out of tier 0, where it is otherwise a finding (P3-6).
    seed = replace(demo_seed, executable={"pay.py": [1, 2, 4]})

    report = await run_seed(seed, FakeSandboxRunner(), reduce=False)

    assert ("pay.py", 3) not in report.tier0


COMMENTED = (
    "def charge(amount):\n"
    "    # Reject a zero amount\n"
    "    if not amount:\n"
    '        raise ValueError("required")\n'
    "    return amount\n"
)
COMMENTED_DIFF = (
    "--- a/pay.py\n"
    "+++ b/pay.py\n"
    "@@ -1,2 +1,5 @@\n"
    " def charge(amount):\n"
    "+    # Reject a zero amount\n"
    "+    if not amount:\n"
    '+        raise ValueError("required")\n'
    "     return amount\n"
)


async def test_no_hunk_is_built_from_a_line_that_cannot_execute(demo_seed):
    # Live, Agentless on matplotlib-23314 (2026-09-19): a changed comment line
    # became its own hunk, and the model "mutated" `# Call the base class`
    # into invented calls, costing model calls and reporting meaningless
    # uncovered rows.
    seed = replace(
        demo_seed,
        pr=replace(demo_seed.pr, diff=COMMENTED_DIFF),
        sources={"pay.py": COMMENTED},
        coverage={"pay.py": {1: [T_CHARGE], 3: [T_CHARGE], 4: [T_CHARGE], 5: [T_CHARGE]}},
        executable={"pay.py": [1, 3, 4, 5]},  # line 2 is the comment
    )

    report = await run_seed(seed, FakeSandboxRunner(), reduce=False)

    assert report.hunks == 1  # the guard; no hunk for the comment alone
    assert all(r.mutant.start_line >= 3 for r in report.results)


def test_coverage_is_restricted_to_selectable_tests():
    coverage = {"pay.py": {2: [T_CHARGE, T_FLAKY], 3: [T_FLAKY]}}

    assert restrict_coverage(coverage, {T_CHARGE}) == {"pay.py": {2: [T_CHARGE], 3: []}}


def test_restriction_keeps_the_import_time_marker():
    # Import time is not a test that can be flaky; dropping it here would
    # bring the false tier-0 finding back through the restriction.
    coverage = {"region.py": {29: [IMPORT_TIME]}}

    assert restrict_coverage(coverage, {T_CHARGE}) == {"region.py": {29: [IMPORT_TIME]}}


async def test_the_report_serialises_and_never_says_equivalent(demo_seed):
    runner = FakeSandboxRunner(handler=guard_matters_to_mutants_but_not_to_the_suite)

    report = await run_seed(demo_seed, runner)
    text = report.to_json()
    payload = json.loads(text)

    assert payload["counts"]["survived"] == report.counts.survived
    assert payload["score"] == report.counts.score
    assert "equivalent" not in text.lower()
