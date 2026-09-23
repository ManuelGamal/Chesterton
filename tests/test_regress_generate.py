"""One regression test, written for the top finding (spec §9)."""

import ast

from chesterton.llm.client import SYNTHESIS_MODEL, TruncatedResponse
from chesterton.regress.context import covering_test_source
from chesterton.regress.generate import (
    build_regression_prompt,
    generate_regression_test,
    parse_test_module,
    regression_test_path,
)
from chesterton.triage.evidence import evidence_for

from conftest import NO_GUARD, ScriptedClient, a_survivor

TEST_MODULE = '''\
import pytest
from pay import charge


def helper():
    return 1


class TestCharge:
    def test_positive(self):
        assert charge(3) == 3


@pytest.mark.parametrize("fmt", ["png"])
def test_rendered(fmt):
    assert charge(1) == 1
'''

GOOD = "```python\nimport pytest\nfrom pay import charge\n\n\ndef test_zero_is_refused():\n    with pytest.raises(ValueError):\n        charge(0)\n```"

EV = evidence_for(a_survivor(NO_GUARD), "Require an amount")


def test_the_new_file_sits_beside_the_covering_test():
    assert regression_test_path("lib/mpl_toolkits/tests/test_mplot3d.py::test_x[png]") == (
        "lib/mpl_toolkits/tests/test_chesterton_regression.py"
    )
    assert regression_test_path("test_pay.py::test_charge") == "test_chesterton_regression.py"


def test_the_context_is_the_imports_and_the_one_test():
    context = covering_test_source(TEST_MODULE, "tests/test_pay.py::test_rendered[png]")

    assert "from pay import charge" in context
    assert '@pytest.mark.parametrize("fmt", ["png"])' in context
    assert "def test_rendered(fmt):" in context
    assert "def helper" not in context and "test_positive" not in context


def test_a_method_is_found_inside_its_class():
    context = covering_test_source(TEST_MODULE, "tests/test_pay.py::TestCharge::test_positive")

    assert "def test_positive(self):" in context and "test_rendered" not in context
    assert "class TestCharge:" in context
    assert ast.parse(context) is not None


def test_an_unparseable_module_falls_back_to_its_head():
    assert covering_test_source("def broken(:\n", "t.py::x").startswith("def broken(")


def test_the_prompt_carries_everything_the_test_needs():
    prompt = build_regression_prompt(EV, "nothing checks the guard", "CTX", "tests/test_x.py")

    assert "Write one pytest regression test" in prompt
    for part in ("Require an amount", "nothing checks the guard", "CTX", "tests/test_x.py",
                 "    2 |     if not amount:", "    2 |     return amount"):
        assert part in prompt
    assert "previous attempt" not in prompt


def test_feedback_from_a_failed_attempt_is_passed_on():
    prompt = build_regression_prompt(EV, "e", "CTX", "p.py", feedback="fails_on_patch: boom")

    assert "previous attempt" in prompt and "fails_on_patch: boom" in prompt


def test_a_fenced_module_with_a_test_is_accepted():
    assert parse_test_module(GOOD).startswith("import pytest")


def test_a_bare_module_is_accepted_too():
    assert parse_test_module("def test_x():\n    assert True\n") is not None


def test_a_reply_without_a_test_or_that_does_not_parse_is_refused():
    assert parse_test_module("```python\ndef helper():\n    pass\n```") is None
    assert parse_test_module("```python\ndef test_x(:\n```") is None


async def test_generation_uses_the_synthesis_tier():
    client = ScriptedClient(GOOD)

    source = await generate_regression_test(client, EV, "e", "CTX", "p.py")

    assert "def test_zero_is_refused" in source
    [call] = client.calls
    assert call["model"] == SYNTHESIS_MODEL and call["thinking"] is True


async def test_a_truncated_generation_yields_nothing():
    client = ScriptedClient(raises=TruncatedResponse("x"))

    assert await generate_regression_test(client, EV, "e", "CTX", "p.py") is None
