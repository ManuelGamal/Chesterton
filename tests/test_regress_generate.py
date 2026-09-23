"""One regression test, written for the top finding (spec §9)."""

import ast

import openai

from chesterton.llm.client import SYNTHESIS_MODEL, TruncatedResponse
from chesterton.regress.context import covering_test_source
from chesterton.regress.generate import (
    build_regression_prompt,
    generate_regression_test,
    parse_test_module,
    private_names,
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


# M3: some replies fence with ```py instead of ```python.
def test_a_py_fence_is_accepted_too():
    py_fenced = GOOD.replace("```python", "```py")

    assert parse_test_module(py_fenced).startswith("import pytest")


async def test_generation_uses_the_synthesis_tier():
    client = ScriptedClient(GOOD)

    generation = await generate_regression_test(client, EV, "e", "CTX", "p.py")

    assert "def test_zero_is_refused" in generation.source
    assert generation.failure is None
    [call] = client.calls
    assert call["model"] == SYNTHESIS_MODEL and call["thinking"] is True


# F3: the caller needs the real reason generation produced nothing, so a
# truncated reply is never described as "no parseable test module".
async def test_a_truncated_generation_carries_its_failure():
    client = ScriptedClient(raises=TruncatedResponse("x"))

    generation = await generate_regression_test(client, EV, "e", "CTX", "p.py")

    assert generation.source is None and generation.failure == "truncated"


async def test_an_unavailable_model_carries_its_failure():
    client = ScriptedClient(raises=openai.OpenAIError("down"))

    generation = await generate_regression_test(client, EV, "e", "CTX", "p.py")

    assert generation.source is None and generation.failure == "unavailable"


async def test_an_unparseable_reply_carries_its_failure():
    client = ScriptedClient("not a test module at all")

    generation = await generate_regression_test(client, EV, "e", "CTX", "p.py")

    assert generation.source is None and generation.failure == "unparseable"


# --- a test pinned to internals encodes the patch, not its behaviour --------
# Live 2026-09-23 (review study, matplotlib-23314): of 10 verified tests, the
# 5 that FAILED on the gold fix all read private attributes the agent had
# invented (ax._axis3don, ax._axis_map, a fake zaxis); the 5 that passed on
# gold asserted only ax.get_visible(). The prompt already said "public API".


PRIVATE = '''
from mpl_toolkits.mplot3d import axes3d, _helper


class TestState:
    def setup_method(self):
        self._fig = None

    def test_x(self):
        ax = make()
        ax.set_visible(False)
        assert ax._axis3don is False
        for axis in ax._axis_map.values():
            assert axis.__class__ is not None
'''


def test_private_attributes_and_imports_are_named():
    assert private_names(PRIVATE) == ["_axis3don", "_axis_map", "_helper"]


def test_public_api_self_state_and_dunders_are_allowed():
    public = "def test_x():\n    ax = make()\n    assert ax.get_visible() is False\n    assert ax.__class__\n"

    assert private_names(public) == []


def test_the_prompt_forbids_private_attributes():
    prompt = build_regression_prompt(EV, "e", "CTX", "p.py")

    assert "private" in prompt and "underscore" in prompt


async def test_a_test_reading_private_attributes_is_rejected_before_any_sandbox_op():
    reply = "```python\ndef test_x():\n    ax = make()\n    assert ax._axis3don is False\n```"

    generation = await generate_regression_test(ScriptedClient(reply), EV, "e", "CTX", "p.py")

    assert generation.source is None
    assert generation.failure == "private_api"
    assert generation.private == ("_axis3don",)
