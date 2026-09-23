"""A run's survivors in, a triaged review and at most one verified test out."""

import json
from dataclasses import asdict

from chesterton.review import review_run
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import NO_GUARD, ScriptedClient, a_survivor, finding_reply

TEST_PAY = "from pay import charge\n\n\ndef test_charge():\n    assert charge(3) == 3\n"
GOOD = "```python\nimport pytest\nfrom pay import charge\n\n\ndef test_zero():\n    with pytest.raises(ValueError):\n        charge(0)\n```"
BAD = "```python\ndef test_bad():\n    assert 'BAD' == 'bad'\n```"

REPORT = {"results": [asdict(a_survivor(NO_GUARD, rationale="M-GUARD"))]}
TRIAGE, WRITE = "Classify the mutant", "Write one pytest regression test"


def sandbox():
    """The good test passes on the PR and fails on the mutant; BAD fails everywhere."""
    def handler(checkpoint, shell, files):
        test = files.get("/testbed/tests/test_chesterton_regression.py", "")
        if "BAD" in test:
            return RunResult("E  AssertionError", "", 1, None)
        return RunResult("", "", 1 if "/testbed/pay.py" in files else 0, None)
    return FakeSandboxRunner(handler=handler, artifacts={"/testbed/tests/test_pay.py": TEST_PAY})


async def test_the_top_finding_gets_a_test_verified_on_the_first_try(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [GOOD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert len(review.triage.headline) == 1
    test = review.regression
    assert test.verified and test.attempts == 1
    assert test.path == "tests/test_chesterton_regression.py"
    assert review.ops_used == 2
    [write] = [c for c in client.calls if WRITE in c["prompt"]]
    assert "def test_charge" in write["prompt"]  # the covering test, read from the checkpoint


async def test_a_failed_attempt_is_repaired_once_with_its_output(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [BAD, GOOD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression.verified and review.regression.attempts == 2
    second = [c for c in client.calls if WRITE in c["prompt"]][1]
    assert "fails_on_patch" in second["prompt"] and "AssertionError" in second["prompt"]
    assert review.ops_used == 4


async def test_a_test_that_never_verifies_is_kept_but_not_verified(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [BAD, BAD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression.verified is False
    assert review.regression.verification.status == "fails_on_patch"


async def test_no_headline_means_no_test_and_no_sandbox_op(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: finding_reply(confident=False)})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression is None and review.ops_used == 0
    assert not any(WRITE in c["prompt"] for c in client.calls)


async def test_the_json_carries_windows_and_the_test_but_never_whole_modules(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [GOOD]})
    review = await review_run(demo_seed, REPORT, sandbox(), client)
    payload = json.loads(review.to_json())

    assert "original_src" not in review.to_json()
    assert payload["regression"]["verified"] is True
    assert "def test_zero" in payload["regression"]["source"]
    assert payload["triage"]["headline"][0]["evidence"]["file"] == "pay.py"
