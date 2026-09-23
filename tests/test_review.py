"""A run's survivors in, a triaged review and at most one verified test out."""

import json
from dataclasses import asdict

import openai
import pytest

from chesterton.llm.client import TruncatedResponse
from chesterton.review import review_run
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import HEAD_PAY, NO_GUARD, T_CHARGE, ScriptedClient, a_survivor, finding_reply

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


# F3: the repair feedback and the final note must name the real reason
# generation produced nothing, never a generic "no parseable test module".
class TruncatingOnceClient(ScriptedClient):
    """The first WRITE call is truncated; the second gets a good reply."""

    def __init__(self):
        super().__init__(by_marker={TRIAGE: [finding_reply()] * 3})
        self._writes = 0

    async def complete(self, prompt, *, model, max_tokens=2048, thinking=False):
        if WRITE in prompt:
            self._writes += 1
            self.calls.append({"prompt": prompt, "model": model,
                                "max_tokens": max_tokens, "thinking": thinking})
            if self._writes == 1:
                raise TruncatedResponse("out of tokens")
            return GOOD
        return await super().complete(prompt, model=model, max_tokens=max_tokens,
                                       thinking=thinking)


async def test_a_truncated_generation_says_so_in_the_repair_feedback(demo_seed):
    client = TruncatingOnceClient()

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression.verified and review.regression.attempts == 2
    [write_two] = [c for c in client.calls if WRITE in c["prompt"]][1:]
    assert "ran out of tokens" in write_two["prompt"]
    assert "no parseable test module" not in write_two["prompt"]


async def test_a_generation_that_never_produces_source_notes_the_last_failure(demo_seed):
    class AlwaysUnavailableForWrites(ScriptedClient):
        def __init__(self):
            super().__init__(by_marker={TRIAGE: [finding_reply()] * 3})

        async def complete(self, prompt, *, model, max_tokens=2048, thinking=False):
            if WRITE in prompt:
                self.calls.append({"prompt": prompt, "model": model,
                                    "max_tokens": max_tokens, "thinking": thinking})
                raise openai.OpenAIError("down")
            return await super().complete(prompt, model=model, max_tokens=max_tokens,
                                           thinking=thinking)

    review = await review_run(demo_seed, REPORT, sandbox(), AlwaysUnavailableForWrites())

    assert review.regression.source is None
    assert review.regression.verification is None
    assert "unavailable" in review.regression.note


# F4: a sandbox that cannot even be read from must not lose the triage that
# already ran, or bury the review under a traceback.
class BrokenReadRunner(FakeSandboxRunner):
    async def read_file(self, checkpoint_id, path):
        raise RuntimeError("NEBIUS_PROJECT_ID is not set")


async def test_a_broken_sandbox_read_keeps_the_triage_and_notes_the_failure(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3})
    runner = BrokenReadRunner(handler=lambda c, s, f: RunResult("", "", 0, None))

    review = await review_run(demo_seed, REPORT, runner, client)

    assert len(review.triage.headline) == 1
    assert review.regression is not None and review.regression.verified is False
    assert "RuntimeError" in review.regression.note


# F5: nothing checked that the seed and the run report belong together.
async def test_a_run_report_for_a_different_slug_is_refused(demo_seed):
    mismatched = {**REPORT, "slug": "someone-elses-slug"}

    with pytest.raises(ValueError, match="someone-elses-slug"):
        await review_run(demo_seed, mismatched, sandbox(), ScriptedClient())


async def test_a_run_report_with_a_matching_slug_is_accepted(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [GOOD]})
    matching = {**REPORT, "slug": demo_seed.slug}

    review = await review_run(demo_seed, matching, sandbox(), client)

    assert review.regression.verified


async def test_a_run_report_with_no_slug_at_all_is_accepted(demo_seed):
    # Older reports never carried a slug; nothing to check against.
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.slug == demo_seed.slug


# M1: the regression test targets the first headline that HAS covering
# tests, not blindly headline[0]. Safety always ranks first regardless of
# test count, so a safety finding with no covering test must not block a
# functional finding that has one.
SAFETY_NO_TESTS = a_survivor(NO_GUARD, rationale="M-SAFETY", tests=())
FUNCTIONAL_WITH_TESTS = a_survivor(
    HEAD_PAY.replace("    return amount\n", "    return 0\n"), start=4, end=4,
    rationale="M-FUNC", tests=(T_CHARGE,),
)
TWO_HEADLINE_REPORT = {
    "results": [asdict(SAFETY_NO_TESTS), asdict(FUNCTIONAL_WITH_TESTS)]
}


async def test_a_safety_headline_with_no_tests_is_skipped_for_one_that_has_them(demo_seed):
    client = ScriptedClient(by_marker={
        "M-SAFETY": [finding_reply(category="safety")] * 3,
        "M-FUNC": [finding_reply(category="functional")] * 3,
        WRITE: [GOOD],
    })

    review = await review_run(demo_seed, TWO_HEADLINE_REPORT, sandbox(), client)

    assert [h.evidence.rationale for h in review.triage.headline] == ["M-SAFETY", "M-FUNC"]
    assert review.regression is not None
    assert review.regression.note != "no covering test to place a new test beside"
    assert review.regression.verified


async def test_the_no_covering_test_note_is_kept_when_no_headline_has_tests(demo_seed):
    no_tests_either = a_survivor(
        HEAD_PAY.replace("    return amount\n", "    return 0\n"), start=4, end=4,
        rationale="M-FUNC2", tests=(),
    )
    report = {"results": [asdict(SAFETY_NO_TESTS), asdict(no_tests_either)]}
    client = ScriptedClient(by_marker={
        "M-SAFETY": [finding_reply(category="safety")] * 3,
        "M-FUNC2": [finding_reply(category="functional")] * 3,
    })

    review = await review_run(demo_seed, report, sandbox(), client)

    assert review.regression.note == "no covering test to place a new test beside"


# --- a test pinned to internals is repaired, not verified ------------------
# Live 2026-09-23 (review study): the verified tests that failed on the gold
# fix all read private attributes. Rejected statically, they cost no op.

PRIVATE_TEST = "```python\nfrom pay import charge\n\n\ndef test_zero():\n    assert charge._validated is True\n```"


async def test_a_private_api_test_is_repaired_without_spending_sandbox_ops(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [PRIVATE_TEST, GOOD]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression.verified and review.regression.attempts == 2
    assert review.ops_used == 2  # only the second attempt was run
    second = [c for c in client.calls if WRITE in c["prompt"]][1]
    assert "_validated" in second["prompt"] and "public API" in second["prompt"]


async def test_two_private_api_tests_leave_a_note_naming_the_attributes(demo_seed):
    client = ScriptedClient(by_marker={TRIAGE: [finding_reply()] * 3, WRITE: [PRIVATE_TEST, PRIVATE_TEST]})

    review = await review_run(demo_seed, REPORT, sandbox(), client)

    assert review.regression.verified is False and review.ops_used == 0
    assert "private_api" in review.regression.note and "_validated" in review.regression.note
