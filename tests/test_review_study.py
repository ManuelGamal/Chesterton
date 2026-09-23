"""The exploratory study script is loaded by path, like the other scripts."""

import importlib.util
from pathlib import Path

from chesterton.execute.pool import SandboxPool
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_study.py"
_spec = importlib.util.spec_from_file_location("review_study", _SCRIPT)
study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)


def pool(code=0, error=None):
    runner = FakeSandboxRunner(handler=lambda c, s, f: RunResult("", "", code, None, error=error))
    return SandboxPool(runner, op_budget=1), runner


async def test_a_test_that_passes_on_the_gold_fix_is_consistent_with_it(demo_seed):
    p, runner = pool(0)

    assert await study.gold_check(p, demo_seed, "tests/t.py", "def test_x(): pass\n") == "passes_on_gold"
    [files] = runner.files_written
    assert files == {"/testbed/tests/t.py": "def test_x(): pass\n"}


async def test_a_test_that_fails_on_the_gold_fix_encoded_the_agents_behaviour(demo_seed):
    p, _ = pool(1)

    assert await study.gold_check(p, demo_seed, "tests/t.py", "x") == "fails_on_gold"


async def test_anything_else_on_gold_is_an_error(demo_seed):
    assert await study.gold_check(pool(2)[0], demo_seed, "t.py", "x") == "error"
    assert await study.gold_check(pool(error="boom")[0], demo_seed, "t.py", "x") == "error"


def test_the_summary_counts_each_outcome():
    rows = [
        {"patch": "a", "headline": 1, "verified": True, "gold": "passes_on_gold"},
        {"patch": "b", "headline": 1, "verified": True, "gold": "fails_on_gold"},
        {"patch": "c", "headline": 0, "verified": False, "gold": None},
    ]

    text = study.summarise(rows)

    assert "3 patches" in text and "2 with a headline finding" in text
    assert "2 verified tests" in text
    assert "1 consistent with the gold fix" in text and "1 encode the agent's behaviour" in text
