"""Three confident findings beat eleven noisy ones (spec §9)."""

import openai
import pytest

from chesterton.triage.classify import ModelUnavailable
from chesterton.triage.select import triage

from conftest import HEAD_PAY, NO_GUARD, ScriptedClient, a_survivor, finding_reply

GUARD = a_survivor(NO_GUARD, rationale="M-GUARD")
GUARD_2 = a_survivor(
    HEAD_PAY.replace('raise ValueError("required")', "pass"), rationale="M-PASS"
)
RETURN = a_survivor(
    HEAD_PAY.replace("    return amount\n", "    return 0\n"), start=4, end=4,
    rationale="M-RETURN", tests=("tests/t.py::a", "tests/t.py::b", "tests/t.py::c"),
)
FINDING, FUNCTIONAL = finding_reply(), finding_reply(category="functional")
EQUIVALENT = finding_reply(label="equivalent", category=None)
UNSURE = finding_reply(confident=False)


async def test_a_finding_confirmed_three_times_is_a_headline():
    client = ScriptedClient(by_marker={"M-GUARD": [FINDING] * 3, "M-RETURN": EQUIVALENT})

    report = await triage(client, [GUARD, RETURN], "t")

    [top] = report.headline
    assert top.evidence.rationale == "M-GUARD" and top.agreement == 3
    assert [d.evidence.rationale for d in report.dismissed] == ["M-RETURN"]
    assert report.worth_a_look == []
    assert report.model_calls == 4  # two survivors, then two confirmations


async def test_a_finding_that_wavers_on_resampling_is_only_worth_a_look():
    client = ScriptedClient(by_marker={"M-GUARD": [FINDING, FINDING, EQUIVALENT]})

    report = await triage(client, [GUARD], "t")

    assert report.headline == []
    [look] = report.worth_a_look
    assert look.agreement == 2


async def test_an_unsure_finding_is_worth_a_look_and_never_resampled():
    client = ScriptedClient(by_marker={"M-GUARD": UNSURE})

    report = await triage(client, [GUARD], "t")

    assert report.headline == [] and len(report.worth_a_look) == 1
    assert report.model_calls == 1


async def test_one_headline_per_hunk():
    client = ScriptedClient(by_marker={"M-PASS": [FUNCTIONAL] * 3, "M-GUARD": [FINDING] * 3})

    report = await triage(client, [GUARD, GUARD_2], "t")

    assert [h.evidence.rationale for h in report.headline] == ["M-GUARD"]  # safety first
    assert [w.evidence.rationale for w in report.worth_a_look] == ["M-PASS"]


async def test_safety_outranks_functional_and_the_limit_holds():
    client = ScriptedClient(by_marker={"M-GUARD": [FINDING] * 3, "M-RETURN": [FUNCTIONAL] * 3})

    report = await triage(client, [RETURN, GUARD], "t", headline_limit=1)

    assert [h.evidence.rationale for h in report.headline] == ["M-GUARD"]
    assert [w.evidence.rationale for w in report.worth_a_look] == ["M-RETURN"]


async def test_killed_results_are_ignored_and_logging_is_dismissed_for_free():
    logged = "import logging\nlog = logging.getLogger(__name__)\nlog.info('a')\n"
    quiet = a_survivor(logged.replace("'a'", "'b'"), start=3, end=3, original=logged)
    killed = a_survivor(NO_GUARD, verdict="killed")
    client = ScriptedClient(FINDING)

    report = await triage(client, [quiet, killed], "t")

    assert client.calls == []
    [dropped] = report.dismissed
    assert dropped.prefiltered == "logging_only"
    assert report.headline == [] and report.worth_a_look == []


# F3: a total model outage (bad key, denied model) must not read as a clean
# review with "0 headline findings". Live 2026-09-23: every classification
# silently abstained and the CLI exited 0.
async def test_every_survivor_unavailable_raises_instead_of_a_silent_clean_review():
    client = ScriptedClient(raises=openai.OpenAIError("down"))

    with pytest.raises(ModelUnavailable, match="2"):
        await triage(client, [GUARD, RETURN], "t")


async def test_a_mix_of_unavailable_and_a_real_answer_does_not_raise():
    class MixedClient:
        async def complete(self, prompt, *, model, max_tokens=2048, thinking=False):
            if "M-GUARD" in prompt:
                raise openai.OpenAIError("down")
            return FINDING

    report = await triage(MixedClient(), [GUARD, RETURN], "t")

    # GUARD abstained (unavailable) every time, so it never becomes a
    # headline, but the run as a whole did not raise.
    assert [h.evidence.rationale for h in report.headline] == ["M-RETURN"]


async def test_no_survivors_sent_to_the_model_never_raises():
    client = ScriptedClient(raises=openai.OpenAIError("down"))
    logged = "import logging\nlog = logging.getLogger(__name__)\nlog.info('a')\n"
    quiet = a_survivor(logged.replace("'a'", "'b'"), start=3, end=3, original=logged)

    report = await triage(client, [quiet], "t")

    assert client.calls == []
    assert report.dismissed and report.dismissed[0].prefiltered == "logging_only"


async def test_identical_survivors_are_each_accounted_for():
    twin_a = a_survivor(NO_GUARD, rationale="M-GUARD")
    twin_b = a_survivor(NO_GUARD, rationale="M-GUARD")
    client = ScriptedClient(by_marker={"M-GUARD": [FINDING] * 4})

    report = await triage(client, [twin_a, twin_b], "t")

    assert len(report.headline) + len(report.worth_a_look) + len(report.dismissed) == 2
    assert len(report.headline) == 1
    assert len(report.worth_a_look) == 1
