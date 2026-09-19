import json

import openai
import pytest

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


def test_coverage_is_restricted_to_selectable_tests():
    coverage = {"pay.py": {2: [T_CHARGE, T_FLAKY], 3: [T_FLAKY]}}

    assert restrict_coverage(coverage, {T_CHARGE}) == {"pay.py": {2: [T_CHARGE], 3: []}}


async def test_the_report_serialises_and_never_says_equivalent(demo_seed):
    runner = FakeSandboxRunner(handler=guard_matters_to_mutants_but_not_to_the_suite)

    report = await run_seed(demo_seed, runner)
    text = report.to_json()
    payload = json.loads(text)

    assert payload["counts"]["survived"] == report.counts.survived
    assert payload["score"] == report.counts.score
    assert "equivalent" not in text.lower()
