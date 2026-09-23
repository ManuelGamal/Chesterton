"""The exploratory study script is loaded by path, like the other scripts."""

import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import openai

from chesterton.execute.pool import SandboxPool
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from conftest import NO_GUARD, ScriptedClient, a_survivor

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
        {"patch": "a", "headline": 1, "verified": True, "gold": "passes_on_gold", "error": None},
        {"patch": "b", "headline": 1, "verified": True, "gold": "fails_on_gold", "error": None},
        {"patch": "c", "headline": 0, "verified": False, "gold": None, "error": None},
        {"patch": "d", "headline": 0, "verified": False, "gold": None, "error": "boom"},
    ]

    text = study.summarise(rows)

    assert "4 patches" in text and "2 with a headline finding" in text
    assert "2 verified tests" in text
    assert "1 consistent with the gold fix" in text and "1 encode the agent's behaviour" in text
    assert "1 patches could not be studied" in text


async def test_one_broken_patch_does_not_end_the_study(tmp_path, demo_seed):
    # Build a bench directory with two patches, but only provide files for the first
    bench = tmp_path / "bench"
    bench.mkdir()
    seeds_dir = bench / "seeds" / study.TASK
    runs_dir = bench / "runs" / study.TASK
    seeds_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)

    # Write pairs.json with two patches
    pairs = [
        {"task": study.TASK, "wrong": "aaa.diff", "control": "c1.diff"},
        {"task": study.TASK, "wrong": "bbb.diff", "control": "c2.diff"},
    ]
    (bench / "pairs.json").write_text(
        __import__("json").dumps(pairs), encoding="utf-8", newline="\n"
    )

    # Write only aaa's files
    (seeds_dir / "aaa.json").write_text(demo_seed.to_json(), encoding="utf-8", newline="\n")
    (runs_dir / "aaa.json").write_text(
        __import__("json").dumps({"results": []}), encoding="utf-8", newline="\n"
    )

    # Leave bbb's files missing

    out = tmp_path / "out"
    rows = await study.study(bench, demo_seed, FakeSandboxRunner(), ScriptedClient(), out)

    assert len(rows) == 2
    assert rows[0]["patch"] == "aaa"
    assert rows[0]["error"] is None
    assert rows[0]["headline"] == 0
    assert rows[1]["patch"] == "bbb"
    assert "FileNotFoundError" in rows[1]["error"]
    assert (out / "aaa.json").exists()


# F3: study.py needs no special code for a total model outage; review_run's
# ModelUnavailable is just another exception the existing `except Exception`
# turns into an error row instead of ending the whole study.
async def test_a_total_model_outage_is_recorded_as_an_error_row(tmp_path, demo_seed):
    bench = tmp_path / "bench"
    bench.mkdir()
    seeds_dir = bench / "seeds" / study.TASK
    runs_dir = bench / "runs" / study.TASK
    seeds_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)

    pairs = [{"task": study.TASK, "wrong": "outage.diff", "control": "c.diff"}]
    (bench / "pairs.json").write_text(json.dumps(pairs), encoding="utf-8", newline="\n")

    (seeds_dir / "outage.json").write_text(demo_seed.to_json(), encoding="utf-8", newline="\n")
    report = {"results": [asdict(a_survivor(NO_GUARD))]}
    (runs_dir / "outage.json").write_text(json.dumps(report), encoding="utf-8", newline="\n")

    out = tmp_path / "out"
    client = ScriptedClient(raises=openai.OpenAIError("access denied"))
    rows = await study.study(bench, demo_seed, FakeSandboxRunner(), client, out)

    assert len(rows) == 1
    assert rows[0]["patch"] == "outage"
    assert "ModelUnavailable" in rows[0]["error"]
    assert not (out / "outage.json").exists()
