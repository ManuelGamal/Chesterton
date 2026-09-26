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


def bench(tmp_path, demo_seed, *, gold=True, pairs=1):
    b = tmp_path / "benchmark-v2"
    for sub in ("seeds", "runs"):
        (b / sub / TASK).mkdir(parents=True)
    report = {"results": [asdict(a_survivor(NO_GUARD))]}
    stems = [s for i in range(1, pairs + 1) for s in (f"w{i}", f"c{i}")]
    for stem in stems:
        (b / "seeds" / TASK / f"{stem}.json").write_text(demo_seed.to_json(), encoding="utf-8")
        (b / "runs" / TASK / f"{stem}.json").write_text(json.dumps(report), encoding="utf-8")
    (b / "pairs.json").write_text(json.dumps(
        [{"task": TASK, "wrong": f"w{i}.diff", "control": f"c{i}.diff"} for i in range(1, pairs + 1)]),
        encoding="utf-8")
    if gold:
        (b / "gold-seeds").mkdir()
        (b / "gold-seeds" / f"{TASK}.json").write_text(replace(demo_seed, checkpoint_id=GOLD).to_json(),
                                                        encoding="utf-8")
    return b


#: The reference-fix seed's checkpoint, so a handler can tell a gold check from a review's runs.
GOLD = "ckpt-gold"


def scripted_runner(*, review=None, gold=None):
    """runner(), but a review run or a gold check can be scripted (a RunResult, or an exception to raise)."""
    base = runner()._handler

    def handler(checkpoint, shell, files):
        special = gold if checkpoint == GOLD else review
        if isinstance(special, BaseException):
            raise special
        return special if special is not None else base(checkpoint, shell, files)
    return FakeSandboxRunner(handler=handler, artifacts={"/testbed/tests/test_pay.py": "def test_charge():\n    pass\n"})


STUB = {"commit": "abc1234", "dirty": False, "pipeline_unchanged_since_registration": True,
        "models": {}, "python": "3.13.0"}


def add_main_task(b, other="psf__requests-863"):
    """One pair in a second task, so main is not empty (the pilot takes TASK's first pair)."""
    for sub in ("seeds", "runs"):
        (b / sub / other).mkdir(parents=True, exist_ok=True)
    for stem in ("w9", "c9"):
        (b / "runs" / other / f"{stem}.json").write_text("{}", encoding="utf-8")
    pairs = json.loads((b / "pairs.json").read_text(encoding="utf-8"))
    pairs.append({"task": other, "wrong": "w9.diff", "control": "c9.diff"})
    (b / "pairs.json").write_text(json.dumps(pairs), encoding="utf-8")
    return other


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


async def test_a_crash_after_review_json_but_before_row_json_is_resumed_without_a_second_review(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    first = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())
    assert (out / TASK / "w1.review.json").exists()
    (out / TASK / "w1.row.json").unlink()  # simulate the crash: review.json survives, row.json does not

    client = ScriptedClient(raises=openai.OpenAIError("must not be called"))
    resumed = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), client)

    assert client.calls == []
    original = next(r for r in first if r["patch"] == "w1")
    rebuilt = next(r for r in resumed if r["patch"] == "w1")
    assert rebuilt["error"] is None and rebuilt["verified"] is True and rebuilt["gold"] == "passes_on_gold"
    assert (rebuilt["headline"], rebuilt["super_calls"], rebuilt["ultra_calls"]) == \
           (original["headline"], original["super_calls"], original["ultra_calls"])


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
                                 study.stage_patches(b, "pilot"), runner(), good_client(), require_gold=False)

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


async def test_a_successful_build_removes_a_stale_error_file(tmp_path, demo_seed):
    out = tmp_path / "gold-seeds"
    out.mkdir()
    (out / "ok__task-3.error.txt").write_text("failed: RuntimeError: image pull failed\n", encoding="utf-8")
    base = SimpleNamespace(pr=demo_seed.pr, image="docker://img", test_paths=("tests/t.py",))

    async def fake_bases(tasks):
        return {t: base for t in tasks}, []

    async def fake_build(runner, pr, **kw):
        return replace(demo_seed, slug=kw["slug"])

    status = await study.build_gold_seeds(None, ["ok__task-3"], out, fetch_bases=fake_bases, build=fake_build)

    assert status == {"ok__task-3": "built"}
    assert not (out / "ok__task-3.error.txt").exists()


def test_a_gold_seeds_counts_are_shown_beside_the_median_of_its_v2_seeds(tmp_path, demo_seed):
    gold, seeds = tmp_path / "gold-seeds", tmp_path / "seeds" / TASK
    gold.mkdir()
    seeds.mkdir(parents=True)
    (gold / f"{TASK}.json").write_text(replace(demo_seed, failing=frozenset({"t::a"})).to_json(), encoding="utf-8")
    for i, n in enumerate((1, 3, 5)):
        many = frozenset(f"t::s{j}" for j in range(n))
        (seeds / f"w{i}.json").write_text(replace(demo_seed, selectable=many).to_json(), encoding="utf-8")

    line = study.seed_counts(gold, tmp_path / "seeds", TASK)

    assert line == "selectable 1, failing 1 (v2 median over 3 seeds: selectable 3, failing 0)"


async def test_the_report_is_written_from_the_row_files(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())

    r = study.write_report(out, todo, provenance=STUB)

    assert r["patches"] == 2 and r["yield"]["k"] == 2 and r["agreement"]["k"] == 2
    assert r["missing"] == [] and r["provenance"] == STUB and r["sample"] is None
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["patches"] == 2


# --- Amendment 2: infrastructure failures (B) -------------------------------------------------


def a_review(*, failure=None, note=None, status="verified"):
    """A parsed review.json, in the shape ReviewReport.to_json() writes."""
    classification = {"label": "untested_invariant", "category": "safety", "confident": True,
                      "explanation": "x", "failure": None}
    triage = {"headline": [{"evidence": {}, "classification": classification, "agreement": 3, "prefiltered": None}],
              "worth_a_look": [{"evidence": {}, "classification": {**classification, "label": "unclassified",
                                                                      "failure": failure}}],
              "dismissed": [], "model_calls": 4}
    verification = {"status": status, "detail": "d", "patch_tail": "", "mutant_tail": ""} if status else None
    regression = {"path": "t.py", "source": "s", "verification": verification, "attempts": 1, "note": note,
                  "verified": status == "verified"}
    return {"slug": "demo", "triage": triage, "regression": regression, "ops_used": 2, "wall_s": 1.0}


def test_an_infrastructure_failure_is_read_from_the_serialized_review():
    assert study.infra_failure(a_review()) is None
    assert "unavailable" in study.infra_failure(a_review(failure="unavailable"))
    assert study.infra_failure(a_review(failure="truncated")) is None
    assert study.infra_failure(a_review(status=None, note="regression stage failed: RuntimeError: x")) \
        == "regression stage failed: RuntimeError: x"
    assert study.infra_failure(a_review(status=None, note="no regression test generated: unavailable")) \
        == "no regression test generated: unavailable"
    assert study.infra_failure(a_review(status=None, note="no regression test generated: private_api (_x)")) is None
    assert "verification status is error" in study.infra_failure(a_review(status="error"))
    assert study.infra_failure(a_review(status="fails_on_patch")) is None


async def test_a_review_whose_regression_stage_failed_is_an_error_its_file_kept_and_it_is_retried(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")

    failed = await study.run_stage(b, out, b / "gold-seeds", todo,
                                   scripted_runner(review=RuntimeError("sandbox gone")), good_client())

    assert all(r["error"] == "infrastructure: regression stage failed: RuntimeError: sandbox gone" for r in failed)
    assert not (out / TASK / "w1.review.json").exists()
    kept = json.loads((out / TASK / "w1.review.1.json").read_text(encoding="utf-8"))
    assert kept["regression"]["note"].startswith("regression stage failed")

    retried = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())

    for r in retried:
        assert r["error"] is None and r["verified"] and r["retries"] == 1
        assert r["history"] == ["infrastructure: regression stage failed: RuntimeError: sandbox gone"]
    assert (out / TASK / "w1.review.json").exists() and (out / TASK / "w1.review.1.json").exists()
    assert study.write_report(out, todo, provenance=STUB)["retried"][0]["history"] == retried[0]["history"]


async def test_after_three_infrastructure_retries_the_last_review_stands(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    for _ in range(3):
        rows = await study.run_stage(b, out, b / "gold-seeds", todo,
                                     scripted_runner(review=RuntimeError("down")), good_client())
        assert all(r["error"] for r in rows)

    stands = await study.run_stage(b, out, b / "gold-seeds", todo,
                                   scripted_runner(review=RuntimeError("down")), good_client())

    for r in stands:
        assert r["error"] is None and r["retries"] == 3 and r["infra_capped"] is True
        assert r["infra_reason"] == "regression stage failed: RuntimeError: down" and not r["verified"]
    assert [p.name for p in sorted((out / TASK).glob("w1.review*.json"))] == \
           ["w1.review.1.json", "w1.review.2.json", "w1.review.3.json", "w1.review.json"]
    again = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())
    assert again == stands
    assert study.write_report(out, todo, provenance=STUB)["no_test_reasons"] == {"infrastructure (capped)": 2}


async def test_an_unknown_exception_is_recorded_as_other_and_not_retried_without_retry_other(
        tmp_path, demo_seed, monkeypatch):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    real = study.review_run

    async def broken(*args, **kw):
        raise ValueError("a bug, not an outage")
    monkeypatch.setattr(study, "review_run", broken)

    rows = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())

    assert all(r["error"] == "other: ValueError: a bug, not an outage" and r["retry_other"] is False for r in rows)
    monkeypatch.setattr(study, "review_run", real)
    client = good_client()
    skipped = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), client)
    assert skipped == rows and client.calls == []
    retried = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client(), retry_other=True)
    assert all(r["error"] is None and r["retries"] == 1 for r in retried)


async def test_five_consecutive_errors_stop_the_stage(tmp_path, demo_seed, capsys):
    b = bench(tmp_path, demo_seed, pairs=3)
    todo = [(TASK, s, arm) for i in (1, 2, 3) for s, arm in ((f"w{i}", "wrong"), (f"c{i}", "control"))]
    out = b / "study-v3" / "pilot"

    rows = await study.run_stage(b, out, b / "gold-seeds", todo, runner(),
                                 ScriptedClient(raises=openai.OpenAIError("outage")))

    assert len(rows) == 5 and all(r["error"].startswith("infrastructure: ModelUnavailable") for r in rows)
    assert not (out / TASK / "c3.row.json").exists()
    assert "5 consecutive errors" in capsys.readouterr().out


# --- Amendment 2: gold checks (C) --------------------------------------------------------------


async def test_a_gold_run_that_exits_2_on_an_import_error_is_a_collection_error_in_the_bound(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    gold = RunResult("E   ImportError: cannot import name 'charge'\n", "", 2, None)

    rows = await study.run_stage(b, out, b / "gold-seeds", todo, scripted_runner(gold=gold), good_client())

    for r in rows:
        assert r["error"] is None and r["gold"] == "error" and r["gold_exit"] == 2
        assert "ImportError" in r["gold_tail"]
        assert r["wall_s"] == pytest.approx(r["review_wall_s"] + r["gold_s"], abs=2e-3)
    rep = study.write_report(out, todo, provenance=STUB)
    assert rep["gold_errors_list"] == [{"task": TASK, "patch": "w1", "exit": 2, "kind": "collection"},
                                       {"task": TASK, "patch": "c1", "exit": 2, "kind": "collection"}]
    assert rep["agreement"]["n"] == 0 and (rep["agreement_bound"]["k"], rep["agreement_bound"]["n"]) == (0, 2)


async def test_the_gold_tail_keeps_the_last_2000_characters(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    gold = RunResult("x" * 5000 + "END", "", 1, None)

    rows = await study.run_stage(b, out, b / "gold-seeds", todo, scripted_runner(gold=gold), good_client())

    assert rows[0]["gold"] == "fails_on_gold" and len(rows[0]["gold_tail"]) == 2000
    assert rows[0]["gold_tail"].endswith("END")


async def test_a_gold_check_whose_sandbox_operation_failed_is_retried_from_the_same_review(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    gold = RunResult("", "", None, None, error="OperationTimedOutError: 300 s")

    failed = await study.run_stage(b, out, b / "gold-seeds", todo, scripted_runner(gold=gold), good_client())

    assert all(r["error"].startswith("infrastructure: GoldSandboxError") and r["gold"] is None for r in failed)
    assert (out / TASK / "w1.review.json").exists()  # the review is kept, never redone
    client = ScriptedClient(raises=openai.OpenAIError("must not be called"))
    retried = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), client)
    assert client.calls == []
    assert all(r["error"] is None and r["gold"] == "passes_on_gold" and r["retries"] == 1 for r in retried)


async def test_the_gold_check_runs_exactly_review_studys_command(demo_seed):
    spec = importlib.util.spec_from_file_location("review_study", _SCRIPT.with_name("review_study.py"))
    review_study = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review_study)
    ours, theirs = runner(), runner()

    assert await study.gold_check(study.SandboxPool(ours, op_budget=1), demo_seed, "tests/t_r.py", "src") == \
           ("passes_on_gold", 0, "")
    assert await review_study.gold_check(study.SandboxPool(theirs, op_budget=1), demo_seed, "tests/t_r.py", "src") \
           == "passes_on_gold"
    assert ours.calls == theirs.calls and ours.files_written == theirs.files_written
    assert ours.options == theirs.options
    assert "-p no:randomly -p no:cacheprovider" in ours.calls[0][1]


async def test_run_refuses_to_start_while_a_task_has_no_reference_fix_seed(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed, gold=False)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")

    with pytest.raises(SystemExit, match=TASK):
        await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())
    assert not out.exists()

    (b / "gold-seeds").mkdir()
    (b / "gold-seeds" / f"{TASK}.error.txt").write_text("failed: SeedBuildError: pip\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=TASK):
        await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())
    rows = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client(), accept_missing_gold=True)
    assert all(r["gold"] == "error" and "SeedBuildError" in r["gold_tail"] for r in rows)


# --- Amendment 2: the report reads the registered list (D) ---------------------------------------


async def test_a_report_on_a_partial_stage_lists_what_is_missing(tmp_path, demo_seed, monkeypatch, capsys):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    await study.run_stage(b, out, b / "gold-seeds", todo[:1], runner(), good_client())
    (out / TASK / "stray.row.json").write_text(json.dumps({"task": TASK, "patch": "stray"}), encoding="utf-8")

    r = study.write_report(out, todo, provenance=STUB)

    assert (r["expected"], r["present"], r["patches"]) == (2, 1, 1)
    assert r["missing"] == [{"task": TASK, "patch": "c1"}]
    monkeypatch.setattr(study, "BENCH", b)
    monkeypatch.setattr(study, "provenance", lambda: STUB)
    capsys.readouterr()
    assert await study._main(["report", "pilot"]) == 0
    assert capsys.readouterr().out.startswith("INCOMPLETE: 1 of 2 rows")


def test_the_report_carries_the_sample_block(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    other = add_main_task(b)
    todo = study.stage_patches(b, "main", fraction=0.5)

    r = study.write_report(b / "study-v3" / "main", todo, provenance=STUB)

    assert r["sample"] == {"fraction": 0.5, "seed": 20260926, "pairs_per_task": {other: 1}}
    assert r["missing"] == [{"task": other, "patch": "w9"}, {"task": other, "patch": "c9"}]


def test_the_provenance_block_names_the_commit_the_pipeline_and_the_models():
    p = study.provenance()

    assert set(p) == {"commit", "dirty", "pipeline_unchanged_since_registration", "models", "python"}
    assert p["commit"] and isinstance(p["dirty"], bool)
    assert p["pipeline_unchanged_since_registration"] is True
    assert p["models"]["reasoning"] == "nvidia/nemotron-3-super-120b-a12b"


async def test_the_pilot_report_prints_its_cost_before_its_estimands(tmp_path, demo_seed, monkeypatch, capsys):
    b = bench(tmp_path, demo_seed)
    todo = study.stage_patches(b, "pilot")
    await study.run_stage(b, b / "study-v3" / "pilot", b / "gold-seeds", todo, runner(), good_client())
    monkeypatch.setattr(study, "BENCH", b)
    monkeypatch.setattr(study, "provenance", lambda: STUB)
    capsys.readouterr()

    assert await study._main(["report", "pilot"]) == 0

    text = capsys.readouterr().out
    assert text.startswith("pilot (reported separately, not part of the main estimate)")
    assert text.index("cost") < text.index("yield")


# --- Amendment 2: the sample and the budget (E) --------------------------------------------------


def test_a_sample_is_refused_once_a_main_row_exists(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    other = add_main_task(b)
    (b / "study-v3" / "main" / other).mkdir(parents=True)
    (b / "study-v3" / "main" / other / "w9.row.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="review"):
        study.stage_patches(b, "main", fraction=0.5)
    assert not (b / "study-v3" / "main" / "sample.json").exists()


async def test_the_budget_command_prints_f_and_each_tasks_k_and_writes_nothing(tmp_path, demo_seed, monkeypatch, capsys):
    b = bench(tmp_path, demo_seed)
    other = add_main_task(b)
    monkeypatch.setattr(study, "BENCH", b)

    assert await study._main(["budget", "--usd", "20", "--cost-per-patch", "0.1"]) == 0

    text = capsys.readouterr().out
    assert "f = 0.65" in text and f"{other}: k = 1 of 1" in text
    assert not (b / "study-v3").exists()


async def test_a_dry_run_prints_each_tasks_k_and_writes_no_lock(tmp_path, demo_seed, monkeypatch, capsys):
    b = bench(tmp_path, demo_seed)
    other = add_main_task(b)
    monkeypatch.setattr(study, "BENCH", b)

    assert await study._main(["run", "main", "--sample", "0.5", "--dry-run"]) == 0

    assert f"{other}: k = 1 of 1" in capsys.readouterr().out
    assert not (b / "study-v3").exists()


# --- Amendment 2: robustness (F) ---------------------------------------------------------------------


def test_a_write_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "r.json"
    study._write(path, "old")

    def crash(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(study.os, "replace", crash)

    with pytest.raises(OSError):
        study._write(path, "new")
    assert path.read_text(encoding="utf-8") == "old"


async def test_a_corrupt_row_json_resumes_from_review_json(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())
    (out / TASK / "w1.row.json").write_text('{"task": "pydata', encoding="utf-8")  # a crash mid-write

    client = ScriptedClient(raises=openai.OpenAIError("must not be called"))
    resumed = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), client)

    assert client.calls == []
    assert resumed[0]["error"] is None and resumed[0]["verified"] and resumed[0]["gold"] == "passes_on_gold"


async def test_a_corrupt_review_json_is_set_aside_and_the_review_redone(tmp_path, demo_seed):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")
    (out / TASK).mkdir(parents=True)
    (out / TASK / "w1.review.json").write_text('{"slug": "de', encoding="utf-8")

    rows = await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())

    assert rows[0]["error"] is None and rows[0]["verified"]
    assert rows[0]["retries"] == 1 and rows[0]["history"] == ["corrupt review.json"]
    assert (out / TASK / "w1.review.corrupt.json").read_text(encoding="utf-8") == '{"slug": "de'
    assert rows[1]["retries"] == 0


async def test_a_stage_prints_progress_and_a_summary(tmp_path, demo_seed, capsys):
    b = bench(tmp_path, demo_seed)
    out, todo = b / "study-v3" / "pilot", study.stage_patches(b, "pilot")

    await study.run_stage(b, out, b / "gold-seeds", todo, runner(), good_client())

    text = capsys.readouterr().out
    assert "[1/2]" in text and "[2/2]" in text and "errors 0" in text
    assert "done 2, errors 0, retried 0, skipped 0" in text


def test_printing_never_crashes_on_encoding(monkeypatch):
    import io
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(study.sys, "stdout", stream)

    study._say("verified → ✓ 中")

    stream.flush()
    assert stream.buffer.getvalue().startswith(b"verified ")
