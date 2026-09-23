"""The demo's replay bundle: a reshaping of recorded artifacts, nothing new."""

import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from chesterton.demo.export import CONCURRENCY, build_bundle, schedule
from chesterton.review import review_run
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult

from conftest import DEMO_DIFF, HEAD_PAY, NO_GUARD, ScriptedClient, a_survivor, finding_reply

GOLDEN = Path(__file__).parent / "fixtures" / "demo_example_bundle.json"
STORY = {"id": "hero", "tab": "Wrong patch, caught", "title": "Demo story", "utboost": "wrong"}
GOOD = "```python\nimport pytest\nfrom pay import charge\n\n\ndef test_zero():\n    with pytest.raises(ValueError):\n        charge(0)\n```"
# The conftest diff has no `diff --git` headers; real PR diffs do, and the
# exporter splits files on them.
HEADED_DIFF = DEMO_DIFF.replace(
    "--- a/pay.py", "diff --git a/pay.py b/pay.py\n--- a/pay.py").replace(
    "--- a/README.md", "diff --git a/README.md b/README.md\n--- a/README.md")


def headed(seed):
    return replace(seed, pr=replace(seed.pr, diff=HEADED_DIFF))


def results():
    survived = a_survivor(NO_GUARD, rationale="drop the guard")
    killed = a_survivor(HEAD_PAY.replace("return amount", "return 0"), start=4, end=4, verdict="killed")
    uncovered = a_survivor(HEAD_PAY.replace("return amount", "return 1"), start=4, end=4,
                           verdict="uncovered", tests=())
    return [survived, killed, uncovered]


def run_report():
    rows = []
    for i, r in enumerate(results()):
        row = asdict(r)
        row["duration_s"] = None if r.verdict == "uncovered" else 2.0 + i
        rows.append(row)
    return {
        "slug": "demo", "wall_s": 42.0, "tier0": [["pay.py", 3]], "hunks": 2, "results": rows,
        "counts": {"killed": 1, "survived": 1, "uncovered": 1, "error": 0},
        "model": {"calls": 5, "retried": 0, "failures": {}},
        "surface": {"hunks": ["pay.py#0"], "needed": [], "undefended": ["pay.py#0"], "probes": 3,
                    "exhausted": False, "skipped": {}, "note": None},
        "ops_used": 6, "op_budget": 160,
    }


async def a_review(seed):
    report = {"results": [asdict(results()[0])]}

    def handler(checkpoint, shell, files):
        return RunResult("", "", 1 if "/testbed/pay.py" in files else 0, None)

    runner = FakeSandboxRunner(handler=handler, artifacts={
        "/testbed/tests/test_pay.py": "def test_charge():\n    pass\n"})
    client = ScriptedClient(by_marker={"Classify the mutant": [finding_reply()] * 3,
                                       "Write one pytest regression test": [GOOD]})
    review = await review_run(seed, report, runner, client)
    return json.loads(review.to_json())


async def a_bundle(demo_seed):
    seed = headed(demo_seed)
    return build_bundle(story=STORY, seed=seed, run=run_report(), review=await a_review(seed),
                        gold="passes_on_gold", submission="an agent", commit="test000")


async def test_the_bundle_carries_no_whole_modules(demo_seed):
    text = json.dumps(await a_bundle(demo_seed))

    assert "original_src" not in text and "mutated_src" not in text
    assert json.dumps(HEAD_PAY)[1:-1] not in text  # windows are numbered, never the raw module


async def test_only_changed_mutable_sources_are_in_the_patch(demo_seed):
    bundle = await a_bundle(demo_seed)

    assert "pay.py" in bundle["patch"]["diff"]
    assert "README.md" not in bundle["patch"]["diff"]
    assert bundle["patch"]["dropped_files"] == ["README.md"]


async def test_every_mutant_keeps_its_recorded_verdict_and_lane(demo_seed):
    bundle = await a_bundle(demo_seed)

    assert [m["verdict"] for m in bundle["mutants"]] == ["survived", "killed", "uncovered"]
    lanes = {lane["id"]: lane for lane in bundle["lanes"]}
    assert all(m["lane"] in lanes for m in bundle["mutants"])
    assert [(l["start_line"], l["end_line"]) for l in bundle["lanes"]] == [(2, 3), (4, 4)]
    assert "raise" in bundle["mutants"][0]["before"] and "raise" not in bundle["mutants"][0]["after"]


async def test_findings_regression_and_counters_are_carried_over(demo_seed):
    bundle = await a_bundle(demo_seed)

    [headline] = bundle["triage"]["headline"]
    assert headline["id"] == "h0" and headline["label"] == "untested_invariant"
    assert headline["agreement"] == 3 and headline["tests"]
    reg = bundle["regression"]
    assert reg["finding_id"] == "h0" and reg["verified"] is True and reg["gold"] == "passes_on_gold"
    assert "def test_zero" in reg["source"]
    assert bundle["counters"] == {"sandbox_ops": 8, "lightning_calls": 5, "super_calls": 3,
                                  "ultra_calls": 1, "run_wall_s": 42.0}
    assert bundle["ddmin"] == {"undefended": [{"file": "pay.py", "start_line": 1, "end_line": 4}],
                               "probes": 3}
    assert bundle["tier0"] == [{"file": "pay.py", "line": 3}]


async def test_the_timeline_adds_up(demo_seed):
    tl = (await a_bundle(demo_seed))["timeline"]

    assert tl["total_s"] == pytest.approx(
        tl["generate_s"] + tl["mutants_end_s"] + tl["ddmin_s"] + tl["triage_s"] + tl["regression_s"])


def test_the_schedule_never_runs_more_than_24_at_once():
    many = [a_survivor(NO_GUARD) for _ in range(60)]
    slots = schedule(many, durations=[1.0 + (i % 7) for i in range(60)])

    events = sorted([(s, 1) for s, d in slots] + [(s + d, -1) for s, d in slots],
                    key=lambda e: (e[0], e[1]))
    running, peak = 0, 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    assert peak <= CONCURRENCY


def test_an_uncovered_or_unmeasured_mutant_takes_no_time():
    [slot] = schedule([a_survivor(NO_GUARD, verdict="uncovered")], durations=[None])

    assert slot == (0.0, 0.0)


async def test_the_example_bundle_matches_the_golden_file(demo_seed):
    bundle = await a_bundle(demo_seed)
    if os.environ.get("CHESTERTON_UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8", newline="\n")

    assert bundle == json.loads(GOLDEN.read_text(encoding="utf-8"))
