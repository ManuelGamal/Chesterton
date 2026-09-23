"""One survivor, one judgement from the reasoning tier (spec §9)."""

import openai

from chesterton.llm.client import REASONING_MODEL, TruncatedResponse
from chesterton.triage.classify import (
    build_triage_prompt,
    classify_survivor,
    parse_classification,
)
from chesterton.triage.evidence import evidence_for

from conftest import NO_GUARD, T_CHARGE, ScriptedClient, a_survivor, finding_reply

EV = evidence_for(a_survivor(NO_GUARD, rationale="drop the guard"), "Require an amount")


def test_the_prompt_carries_the_code_the_mutant_and_the_tests_that_passed():
    prompt = build_triage_prompt(EV)

    assert "Classify the mutant" in prompt
    assert "Require an amount" in prompt
    assert '-        raise ValueError("required")' in prompt
    assert T_CHARGE in prompt
    assert "drop the guard" in prompt
    # The invariant instructions come first, so prompt caching can reuse them.
    assert prompt.index("Classify the mutant") < prompt.index("Require an amount")


def test_a_long_test_list_is_cut_with_a_count():
    many = tuple(f"tests/t.py::test_{i}" for i in range(50))
    prompt = build_triage_prompt(evidence_for(a_survivor(NO_GUARD, tests=many), "t"))

    assert "tests/t.py::test_19" in prompt and "tests/t.py::test_20" not in prompt
    assert "and 30 more" in prompt


def test_a_well_formed_reply_is_read_exactly():
    c = parse_classification(finding_reply(explanation="nothing checks the guard"))

    assert (c.label, c.category, c.confident) == ("untested_invariant", "safety", True)
    assert c.explanation == "nothing checks the guard"


def test_only_a_finding_carries_a_category():
    c = parse_classification(finding_reply(label="equivalent", category="safety"))

    assert c.label == "equivalent" and c.category is None


def test_confidence_must_be_a_real_true():
    assert parse_classification(finding_reply(confident="yes")).confident is False


def test_an_unknown_label_or_prose_abstains():
    assert parse_classification(finding_reply(label="bug")).label == "unclassified"
    assert parse_classification("I think it is fine").label == "unclassified"


async def test_the_call_uses_the_reasoning_tier_with_thinking_on():
    client = ScriptedClient(finding_reply())

    c = await classify_survivor(client, EV)

    assert c.label == "untested_invariant"
    [call] = client.calls
    assert call["model"] == REASONING_MODEL and call["thinking"] is True
    assert call["max_tokens"] >= 8192


async def test_a_truncated_or_failed_call_abstains_instead_of_raising():
    truncated = await classify_survivor(ScriptedClient(raises=TruncatedResponse("x")), EV)
    down = await classify_survivor(ScriptedClient(raises=openai.OpenAIError("down")), EV)

    assert truncated.label == down.label == "unclassified"
    assert truncated.confident is False and "tokens" in truncated.explanation
    assert "unavailable" in down.explanation


# F3: a total model outage (bad key, denied model) must not look like a clean
# review. `failure` distinguishes "the model was never really consulted" from
# a real, if unsure, answer.
def test_a_real_answer_carries_no_failure():
    assert parse_classification(finding_reply()).failure is None
    # Valid JSON with an unknown label is a real (if useless) answer, not a
    # failure: the model responded, it just did not fit the schema's labels.
    unknown_label = parse_classification(finding_reply(label="bug"))
    assert unknown_label.label == "unclassified" and unknown_label.failure is None


def test_an_unparseable_reply_is_a_malformed_failure():
    assert parse_classification("not json at all").failure == "malformed"


async def test_a_truncated_or_unavailable_call_carries_its_failure():
    truncated = await classify_survivor(ScriptedClient(raises=TruncatedResponse("x")), EV)
    down = await classify_survivor(ScriptedClient(raises=openai.OpenAIError("down")), EV)

    assert truncated.failure == "truncated"
    assert down.failure == "unavailable"


# M2: a confident untested_invariant with no explanation is not trustworthy
# enough to show a human; abstain instead, but this is a real answer, not an
# outage, so failure stays None.
def test_a_confident_finding_with_no_explanation_abstains():
    c = parse_classification(finding_reply(explanation=""))

    assert c.label == "unclassified" and c.failure is None
    assert "explanation" in c.explanation

    blank = parse_classification(finding_reply(explanation="   "))
    assert blank.label == "unclassified" and blank.failure is None


def test_an_unconfident_finding_with_no_explanation_is_still_just_unsure():
    c = parse_classification(finding_reply(confident=False, explanation=""))

    assert c.label == "untested_invariant" and c.confident is False
    assert c.failure is None
