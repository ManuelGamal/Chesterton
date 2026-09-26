"""The study v3 driver, end to end on fakes: no network, no sandbox, no model."""

import importlib.util
import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from conftest import NO_GUARD, ScriptedClient, a_survivor, finding_reply

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "study_v3.py"
_spec = importlib.util.spec_from_file_location("study_v3", _SCRIPT)
study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)

TASK = "pydata__xarray-4687"
GOOD = "```python\nimport pytest\nfrom pay import charge\n\n\ndef test_zero():\n    with pytest.raises(ValueError):\n        charge(0)\n```"


def runner():
    # The PR passes its tests; the mutant (which rewrites pay.py) fails them; the gold seed passes.
    def handler(checkpoint, shell, files):
        return RunResult("", "", 1 if "/testbed/pay.py" in files else 0, None)
    return FakeSandboxRunner(handler=handler, artifacts={"/testbed/tests/test_pay.py": "def test_charge():\n    pass\n"})


def good_client():
    return ScriptedClient(by_marker={"Classify the mutant": finding_reply(), "Write one pytest regression test": GOOD})


def bench(tmp_path, demo_seed, *, gold=True):
    b = tmp_path / "benchmark-v2"
    for sub in ("seeds", "runs"):
        (b / sub / TASK).mkdir(parents=True)
    report = {"results": [asdict(a_survivor(NO_GUARD))]}
    for stem in ("w1", "c1"):
        (b / "seeds" / TASK / f"{stem}.json").write_text(demo_seed.to_json(), encoding="utf-8")
        (b / "runs" / TASK / f"{stem}.json").write_text(json.dumps(report), encoding="utf-8")
    (b / "pairs.json").write_text(json.dumps([{"task": TASK, "wrong": "w1.diff", "control": "c1.diff"}]), encoding="utf-8")
    if gold:
        (b / "gold-seeds").mkdir()
        (b / "gold-seeds" / f"{TASK}.json").write_text(demo_seed.to_json(), encoding="utf-8")
    return b


async def test_a_stage_reviews_each_patch_and_checks_its_test_on_the_correct_fix(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    todo = study.stage_patches(b, "pilot")

    rows = await study.run_stage(b, b / "study-v3" / "pilot", b / "gold-seeds", todo, runner(), good_client())

    assert [(r["patch"], r["arm"]) for r in rows] == [("w1", "wrong"), ("c1", "control")]
    for r in rows:
        assert r["error"] is None and r["verified"] is True and r["gold"] == "passes_on_gold"
        assert r["super_calls"] >= 3 and r["ultra_calls"] >= 1 and r["retries"] == 0
    assert (b / "study-v3" / "pilot" / TASK / "w1.review.json").exists()


async def test_a_completed_review_is_never_rerun(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    first = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())

    again = await study.run_stage(b, out, b / "gold-seeds", todo, runner(),
                                  ScriptedClient(raises=openai.OpenAIError("must not be called")))

    assert again == first


async def test_an_errored_review_is_retried_and_counted(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    failed = await study.run_stage(b, out, b / "gold-seeds", todo, runner(),
                                   ScriptedClient(raises=openai.OpenAIError("outage")))
    assert all(r["error"] for r in failed)

    retried = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())

    assert all(r["error"] is None and r["retries"] == 1 for r in retried)


async def test_a_task_without_a_reference_fix_seed_reports_its_gold_checks_as_errors(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed, gold=False)

    rows = await study.run_stage(b, b / "study-v3" / "pilot", b / "gold-seeds",
                                 study.stage_patches(b, "pilot"), runner(), good_client())

    assert all(r["verified"] and r["gold"] == "error" for r in rows)


def test_the_main_sample_is_fixed_once_and_a_different_fraction_is_refused(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    # One pair in the pilot task: the pilot takes it, so main is empty; add a second task for main.
    other = "psf__requests-863"
    for sub in ("seeds", "runs"):
        (b / sub / other).mkdir(parents=True)
    for stem in ("w9", "c9"):
        (b / "runs" / other / f"{stem}.json").write_text("{}", encoding="utf-8")
    pairs = json.loads((b / "pairs.json").read_text(encoding="utf-8"))
    pairs.append({"task": other, "wrong": "w9.diff", "control": "c9.diff"})
    (b / "pairs.json").write_text(json.dumps(pairs), encoding="utf-8")

    assert study.stage_patches(b, "pilot") == [(TASK, "w1", "wrong"), (TASK, "c1", "control")]
    assert study.stage_patches(b, "main", fraction=0.5) == [(other, "w9", "wrong"), (other, "c9", "control")]
    assert json.loads((b / "study-v3" / "main" / "sample.json").read_text(encoding="utf-8"))["fraction"] == 0.5
    assert study.stage_patches(b, "main") == [(other, "w9", "wrong"), (other, "c9", "control")]
    with pytest.raises(SystemExit, match="sample"):
        study.stage_patches(b, "main", fraction=0.25)


async def test_reference_fix_seeds_are_built_once_and_failures_recorded(tmp_path, demo_seed):
    out = tmp_path / "gold-seeds"
    out.mkdir()
    (out / "done__task-1.json").write_text("{}", encoding="utf-8")
    base = SimpleNamespace(pr=demo_seed.pr, image="docker://img", test_paths=("tests/t.py",))

    async def fake_bases(tasks):
        return {t: base for t in tasks if t != "gone__task-9"}, ["gone__task-9"]

    async def fake_build(runner, pr, **kw):
        if "broken" in kw["slug"]:  # slug_for gives "bm-broken-task-2-gold"
            raise RuntimeError("image pull failed")
        return replace(demo_seed, slug=kw["slug"])

    status = await study.build_gold_seeds(
        None, ["done__task-1", "broken__task-2", "ok__task-3", "gone__task-9"], out,
        fetch_bases=fake_bases, build=fake_build)

    assert status == {"done__task-1": "exists", "broken__task-2": "failed: RuntimeError: image pull failed",
                      "ok__task-3": "built", "gone__task-9": "unknown task"}
    assert (out / "ok__task-3.json").exists() and (out / "broken__task-2.error.txt").exists()


async def test_the_report_is_written_from_the_row_files(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out = b / "study-v3" / "pilot"
    await study.run_stage(b, out, b / "gold-seeds", study.stage_patches(b, "pilot"), runner(), good_client())

    r = study.write_report(out)

    assert r["patches"] == 2 and r["yield"]["k"] == 2 and r["agreement"]["k"] == 2
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["patches"] == 2
