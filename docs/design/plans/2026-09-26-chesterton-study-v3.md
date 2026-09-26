# Study v3 (Verified Tests at Scale) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the code that runs study v3 exactly as registered in spec §17: reference-fix seeds, the pilot, the main run (with the budget-rule sample) and the registered estimands.

**Architecture:**
- **`src/chesterton/benchmark/verified.py`**: the pure logic. It selects the population, the pilot and the sample, and computes Wilson intervals, per-task means, the task-clustered bootstrap and the report dict. It runs no sandbox and calls no model.
- **`scripts/study_v3.py`**: the resumable driver.
  - It builds a reference-fix seed per task, reviews each patch with the existing `review_run` and checks every verified test on the reference fix with the existing `gold_check`.
  - It writes one row file per patch, so completed reviews are never rerun.
  - It reuses `scripts/benchmark.py` (`fetch_bases`, `PYTHON`, `slug_for`) and `scripts/review_study.py` (`gold_check`), loading both by path the way the tests already load scripts.

**Tech Stack:** Python 3.12, pytest (asyncio mode auto), the project's FakeSandboxRunner and ScriptedClient test doubles.

**Spec:** `docs/design/specs/2026-09-18-chesterton-design.md` §17, the section "Study v3: verified tests at scale", registered in commit `8f95e0e`.

## Global Constraints

- **The registration is binding.** Population, pilot, estimands, sensitivity analyses, retries and the budget rule are exactly as in spec §17 "Study v3". This plan implements them and changes none.
- **Registered constants:**
  - seed `20260926`;
  - `10_000` bootstrap resamples;
  - Wilson intervals at 95% (z = 1.959963984540054);
  - pilot: 2 pairs of `pydata__xarray-4687`, 2 of `sympy__sympy-21847` and 1 of `scikit-learn__scikit-learn-14087`, taken as the first by wrong-patch stem.
- **No re-runs.** A review that completed is never rerun. A row whose `error` is not null is retried on the next invocation, and its `retries` count increases.
- **Leave the review pipeline alone.** No change to `src/chesterton/review.py`, `src/chesterton/triage/` or `src/chesterton/regress/`. The review configuration is the one at the registration commit.
- **Workspace.** Work in the main checkout `C:\Users\manue\projects\chesterton`, on branch `study-v3`. Never commit to `master`. Never push.
- **Commit messages** end with a blank line and then exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No other co-author line.
- **Editing files.** Create and edit files with the Write/Edit tools, never bash heredocs: in this shell, heredocs turn `\\` into `\`. Everything written to disk is UTF-8 with LF line endings.
- **Staging.** `git add` only the files a task names. Data directories are never committed: `benchmark*/`, `agent_patches*/`, `review-study*/`, `review-gold/`, `seeds/`, `runs/`, `logs/`.
- **Tests.** Run them with `.venv/Scripts/python.exe -m pytest -q`, from the repo root. The shell's cwd resets to a dead worktree, so start every command with `cd "C:/Users/manue/projects/chesterton"`.
- **No live calls.** No test calls Nebius or any network. Tests use fakes only.

---

### Task 1: The registered logic (population, pilot, sample, estimands)

**Files:**
- Create: `src/chesterton/benchmark/verified.py`
- Test: `tests/test_benchmark_verified.py`

**Interfaces:**
- Produces:
  - `SEED: int`, `RESAMPLES: int`, `PILOT: dict[str, int]`;
  - `Pair(task: str, wrong: str, control: str)`, a frozen dataclass whose `wrong` and `control` are stems;
  - `population(pairs: list[dict], runs: Path) -> list[Pair]`;
  - `pilot(pop: list[Pair]) -> list[Pair]`;
  - `main_pairs(pop: list[Pair], pilot_pairs: list[Pair]) -> list[Pair]`;
  - `sample(pairs: list[Pair], fraction: float) -> list[Pair]`;
  - `patches(pairs: list[Pair]) -> list[tuple[str, str, str]]`, yielding `(task, stem, arm)` with `arm` either `"wrong"` or `"control"`;
  - `wilson(k: int, n: int) -> tuple[float, float, float] | None`;
  - `yield_counts(rows) -> dict[str, tuple[int, int]]` and `agreement_counts(rows) -> dict[str, tuple[int, int]]`;
  - `per_task_mean(counts) -> float | None`;
  - `cluster_interval(counts, *, resamples=RESAMPLES, seed=SEED) -> tuple[float, float] | None`;
  - `estimate(counts) -> dict`;
  - `report(rows: list[dict]) -> dict`.
- **Row shape**, as the Task 2 driver writes it:

  ```python
  {"task", "patch", "arm", "headline", "verified", "status", "gold", "super_calls",
   "ultra_calls", "ops", "wall_s", "retries", "error"}
  ```

- [ ] **Step 1: Write the failing tests**

`tests/test_benchmark_verified.py`:

```python
"""Study v3's registered logic (spec §17): population, pilot, sample, estimands."""

import json

import pytest

from chesterton.benchmark import verified as v


def write_runs(root, task, stems):
    d = root / task
    d.mkdir(parents=True, exist_ok=True)
    for s in stems:
        (d / f"{s}.json").write_text("{}", encoding="utf-8")


def test_the_population_is_the_pairs_whose_two_runs_exist(tmp_path):
    write_runs(tmp_path, "t1", ["w1", "c1", "w2"])
    pairs = [{"task": "t1", "wrong": "w1.diff", "control": "c1.diff"},
             {"task": "t1", "wrong": "w2.diff", "control": "c2.diff"}]

    assert v.population(pairs, tmp_path) == [v.Pair("t1", "w1", "c1")]


def pop_of(counts):
    return [v.Pair(task, f"w{i:02d}", f"c{i:02d}") for task, n in counts.items() for i in range(n)]


def test_the_pilot_is_the_registered_five_pairs_by_wrong_stem():
    pop = pop_of({"pydata__xarray-4687": 12, "sympy__sympy-21847": 16,
                  "scikit-learn__scikit-learn-14087": 5, "sympy__sympy-22714": 32})

    chosen = v.pilot(pop)

    assert [(p.task, p.wrong) for p in chosen] == [
        ("pydata__xarray-4687", "w00"), ("pydata__xarray-4687", "w01"),
        ("sympy__sympy-21847", "w00"), ("sympy__sympy-21847", "w01"),
        ("scikit-learn__scikit-learn-14087", "w00"),
    ]
    assert len(v.main_pairs(pop, chosen)) == len(pop) - 5
    assert not set(v.main_pairs(pop, chosen)) & set(chosen)


def test_the_budget_sample_takes_the_same_fraction_of_every_task_and_is_seeded():
    pop = pop_of({"a": 10, "b": 4, "c": 1})

    first = v.sample(pop, 0.5)

    assert sorted(p.task for p in first) == ["a"] * 5 + ["b"] * 2 + ["c"]
    assert v.sample(pop, 0.5) == first
    with pytest.raises(ValueError):
        v.sample(pop, 0)


def test_each_pair_gives_its_wrong_and_its_control_patch():
    assert v.patches([v.Pair("t", "w", "c")]) == [("t", "w", "wrong"), ("t", "c", "control")]


def test_the_wilson_interval_matches_a_hand_computed_value():
    p, lo, hi = v.wilson(9, 13)

    assert p == pytest.approx(9 / 13)
    assert lo == pytest.approx(0.4237, abs=1e-3)
    assert hi == pytest.approx(0.8732, abs=1e-3)
    assert v.wilson(0, 0) is None
    assert v.wilson(0, 5)[1] == pytest.approx(0.0, abs=1e-12)


def row(task, arm="wrong", *, verified=False, gold=None, headline=1, status=None, error=None):
    return {"task": task, "patch": "p", "arm": arm, "headline": headline, "verified": verified,
            "status": status, "gold": gold, "super_calls": 3, "ultra_calls": 1 if verified else 0,
            "ops": 2, "wall_s": 10.0, "retries": 0, "error": error}


def test_yield_counts_every_patch_and_agreement_only_checked_verified_tests():
    rows = [row("a", verified=True, gold="passes_on_gold"), row("a", verified=True, gold="error"),
            row("a", error="boom", headline=0), row("b", verified=True, gold="fails_on_gold")]

    assert v.yield_counts(rows) == {"a": (2, 3), "b": (1, 1)}
    assert v.agreement_counts(rows) == {"a": (1, 1), "b": (0, 1)}


def test_the_per_task_mean_weights_tasks_equally():
    assert v.per_task_mean({"a": (1, 1), "b": (0, 3), "c": (0, 0)}) == pytest.approx(0.5)
    assert v.per_task_mean({"a": (0, 0)}) is None


def test_the_cluster_interval_is_seeded_and_collapses_when_every_task_agrees():
    same = {"a": (1, 2), "b": (2, 4), "c": (3, 6)}
    assert v.cluster_interval(same, resamples=500) == (0.5, 0.5)
    mixed = {"a": (1, 1), "b": (0, 1), "c": (1, 2)}
    assert v.cluster_interval(mixed, resamples=500) == v.cluster_interval(mixed, resamples=500)
    assert v.cluster_interval({"a": (0, 0)}, resamples=50) is None


def test_the_report_carries_both_estimands_arms_reasons_and_cost():
    rows = [row("a", verified=True, gold="passes_on_gold"),
            row("a", "control", headline=0),
            row("b", verified=False, status="fails_on_patch"),
            row("b", "control", error="SandboxError: gone", headline=0)]

    r = v.report(rows)

    assert r["patches"] == 4
    assert r["yield"]["k"] == 1 and r["yield"]["n"] == 4
    assert r["agreement"]["k"] == 1 and r["agreement"]["n"] == 1
    assert r["gold_errors"] == 0
    assert r["by_arm"]["wrong"]["yield"]["n"] == 2
    assert r["by_task"]["a"]["yield"] == [1, 2]
    assert r["no_test_reasons"] == {"no headline": 1, "not verified: fails_on_patch": 1, "error": 1}
    assert r["headline_counts"] == {"1": 2, "0": 2}
    assert r["cost"]["super_calls"] == {"median": 3.0, "total": 12}
    json.dumps(r)  # the report is plain JSON
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd "C:/Users/manue/projects/chesterton" && .venv/Scripts/python.exe -m pytest -q tests/test_benchmark_verified.py`

Expected: fails with `ImportError: cannot import name 'verified'`.

- [ ] **Step 3: Implement**

`src/chesterton/benchmark/verified.py`:

```python
"""Study v3, verified tests at scale (spec §17, registered 2026-09-26).

Pure logic: which patches the study reviews, and the registered estimands.
Nothing here opens a sandbox or calls a model; scripts/study_v3.py does.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import median

#: Registered: the seed for the budget sample and the cluster bootstrap.
SEED = 20260926
#: Registered: cluster-bootstrap resamples.
RESAMPLES = 10_000
#: Two-sided 95%.
Z = 1.959963984540054
#: Registered pilot: the first N pairs, by wrong-patch stem, of these tasks.
PILOT = {"pydata__xarray-4687": 2, "sympy__sympy-21847": 2, "scikit-learn__scikit-learn-14087": 1}


@dataclass(frozen=True)
class Pair:
    task: str
    wrong: str
    control: str


def population(pairs: list[dict], runs: Path) -> list[Pair]:
    """The pairs v2 analysed: those whose wrong and control run files both exist."""
    out = []
    for p in pairs:
        wrong, control = Path(p["wrong"]).stem, Path(p["control"]).stem
        if all((runs / p["task"] / f"{stem}.json").exists() for stem in (wrong, control)):
            out.append(Pair(p["task"], wrong, control))
    return out


def pilot(pop: list[Pair]) -> list[Pair]:
    chosen: list[Pair] = []
    for task, n in PILOT.items():
        chosen += sorted((p for p in pop if p.task == task), key=lambda p: p.wrong)[:n]
    return chosen


def main_pairs(pop: list[Pair], pilot_pairs: list[Pair]) -> list[Pair]:
    excluded = set(pilot_pairs)
    return [p for p in pop if p not in excluded]


def sample(pairs: list[Pair], fraction: float) -> list[Pair]:
    """The budget rule: the same fraction of every task's pairs (at least one), seeded."""
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    out: list[Pair] = []
    for task in sorted({p.task for p in pairs}):
        mine = sorted((p for p in pairs if p.task == task), key=lambda p: p.wrong)
        k = max(1, round(fraction * len(mine)))
        out += random.Random(f"{SEED}:{task}").sample(mine, k)
    return out


def patches(pairs: list[Pair]) -> list[tuple[str, str, str]]:
    return [x for p in pairs for x in ((p.task, p.wrong, "wrong"), (p.task, p.control, "control"))]


def wilson(k: int, n: int) -> tuple[float, float, float] | None:
    """(rate, low, high): the Wilson score interval at 95%."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def yield_counts(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Per task: (patches with a verified test, patches). Every patch counts."""
    counts: dict[str, list[int]] = {}
    for r in rows:
        c = counts.setdefault(r["task"], [0, 0])
        c[0] += bool(r["verified"])
        c[1] += 1
    return {t: (k, n) for t, (k, n) in counts.items()}


def agreement_counts(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Per task: (verified tests passing on the correct fix, verified tests checked on it)."""
    counts: dict[str, list[int]] = {}
    for r in rows:
        if not r["verified"] or r["gold"] not in ("passes_on_gold", "fails_on_gold"):
            continue
        c = counts.setdefault(r["task"], [0, 0])
        c[0] += r["gold"] == "passes_on_gold"
        c[1] += 1
    return {t: (k, n) for t, (k, n) in counts.items()}


def per_task_mean(counts: dict[str, tuple[int, int]]) -> float | None:
    rates = [k / n for k, n in counts.values() if n > 0]
    return sum(rates) / len(rates) if rates else None


def cluster_interval(
    counts: dict[str, tuple[int, int]], *, resamples: int = RESAMPLES, seed: int = SEED
) -> tuple[float, float] | None:
    """A 95% percentile interval for the pooled rate, resampling tasks with replacement."""
    tasks = sorted(t for t, (_, n) in counts.items() if n > 0)
    if not tasks:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        pick = [rng.choice(tasks) for _ in tasks]
        k = sum(counts[t][0] for t in pick)
        n = sum(counts[t][1] for t in pick)
        stats.append(k / n)
    stats.sort()
    last = len(stats) - 1
    return stats[round(0.025 * last)], stats[round(0.975 * last)]


def estimate(counts: dict[str, tuple[int, int]]) -> dict:
    k = sum(k for k, _ in counts.values())
    n = sum(n for _, n in counts.values())
    w = wilson(k, n)
    return {
        "k": k, "n": n,
        "rate": w[0] if w else None,
        "wilson": [w[1], w[2]] if w else None,
        "per_task_mean": per_task_mean(counts),
        "cluster_interval": list(ci) if (ci := cluster_interval(counts)) else None,
        "tasks": sum(1 for _, n in counts.values() if n > 0),
    }


def _reason(r: dict) -> str:
    if r["error"]:
        return "error"
    if r["headline"] == 0:
        return "no headline"
    return f"not verified: {r['status']}"


def report(rows: list[dict]) -> dict:
    """Everything spec §17 registers for v3, as plain JSON."""
    def cost(key: str) -> dict:
        values = [r[key] for r in rows]
        return {"median": float(median(values)) if values else None, "total": sum(values)}

    by_task = {}
    for task in sorted({r["task"] for r in rows}):
        mine = [r for r in rows if r["task"] == task]
        y, a = yield_counts(mine).get(task, (0, 0)), agreement_counts(mine).get(task, (0, 0))
        by_task[task] = {"yield": list(y), "agreement": list(a)}
    return {
        "patches": len(rows),
        "yield": estimate(yield_counts(rows)),
        "agreement": estimate(agreement_counts(rows)),
        "gold_errors": sum(1 for r in rows if r["verified"] and r["gold"] == "error"),
        "by_arm": {
            arm: {"yield": estimate(yield_counts(mine)), "agreement": estimate(agreement_counts(mine))}
            for arm in ("wrong", "control")
            if (mine := [r for r in rows if r["arm"] == arm])
        },
        "by_task": by_task,
        "headline_counts": {str(h): c for h, c in sorted(Counter(r["headline"] for r in rows).items(), reverse=True)},
        "no_test_reasons": dict(Counter(_reason(r) for r in rows if not r["verified"])),
        "retries": sum(r["retries"] for r in rows),
        "cost": {key: cost(key) for key in ("super_calls", "ultra_calls", "ops", "wall_s")},
    }
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd "C:/Users/manue/projects/chesterton" && .venv/Scripts/python.exe -m pytest -q tests/test_benchmark_verified.py`

Expected: all 9 pass.

If `test_the_report_carries_both_estimands_arms_reasons_and_cost` fails only on the order of the keys in `headline_counts` or `no_test_reasons`, dict equality ignores order, so the failure lies elsewhere: look at the counts.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add src/chesterton/benchmark/verified.py tests/test_benchmark_verified.py
git commit -m "feat: study v3's registered logic: population, pilot, sample and estimands" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The resumable driver

**Files:**
- Create: `scripts/study_v3.py`
- Test: `tests/test_study_v3_script.py`

**Interfaces:**
- **Consumes:**
  - everything in Task 1;
  - `review_run(seed, report, runner, client)` from `chesterton.review`, which returns a `ReviewReport` with `.triage.headline`, `.triage.model_calls`, `.regression` (with `.verified`, `.path`, `.source`, `.verification.status`, `.attempts` and `.note`), `.ops_used`, `.wall_s` and `.to_json()`;
  - `gold_check(pool, gold_seed, test_path, test_src)` from `scripts/review_study.py`;
  - `fetch_bases`, `PYTHON` and `slug_for` from `scripts/benchmark.py`;
  - `build_seed` from `chesterton.seed.build`.
- **Produces** a CLI:
  - `study_v3.py gold-seeds`;
  - `study_v3.py run pilot|main [--sample F]`;
  - `study_v3.py report pilot|main`.
- **Outputs:**
  - `benchmark-v2/gold-seeds/<task>.json`, plus `<task>.error.txt` when a build fails;
  - `benchmark-v2/study-v3/<stage>/<task>/<stem>.row.json` and `<stem>.review.json`;
  - `benchmark-v2/study-v3/main/sample.json`, only when sampled;
  - `benchmark-v2/study-v3/<stage>/report.json`.

- [ ] **Step 1: Write the failing tests**

`tests/test_study_v3_script.py`:

```python
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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd "C:/Users/manue/projects/chesterton" && .venv/Scripts/python.exe -m pytest -q tests/test_study_v3_script.py`

Expected: fails, because `scripts/study_v3.py` does not exist.

- [ ] **Step 3: Implement**

`scripts/study_v3.py`:

```python
"""Study v3: verified tests at scale (spec §17, REGISTERED 2026-09-26, commit 8f95e0e).

Usage, from the repo root (needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID):
    python scripts/study_v3.py gold-seeds             # one reference-fix seed per task, once
    python scripts/study_v3.py run pilot              # stage 0: the registered 10 patches
    python scripts/study_v3.py run main [--sample F]  # the 292 main patches, or the budget sample
    python scripts/study_v3.py report pilot|main      # the registered estimands -> report.json

Resumable. A patch whose row has no error is never reviewed again (spec §17,
Retries); a row with an infrastructure error is retried on the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from chesterton.benchmark import verified as v
from chesterton.execute.pool import SandboxPool
from chesterton.review import review_run
from chesterton.seed.build import build_seed
from chesterton.seed.record import SeedRecord

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark-v2"


def _load(name: str):
    """Reuse another script's helpers, loaded by path like the tests load scripts."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bench = _load("benchmark")
_review_study = _load("review_study")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


async def build_gold_seeds(runner, tasks, out: Path, *, fetch_bases=None, build=build_seed) -> dict[str, str]:
    """One reference-fix seed per task, built as benchmark.seed_for builds v2's seeds."""
    fetch = fetch_bases or _bench.fetch_bases
    bases, unknown = await fetch(sorted(set(tasks)))
    status = {task: "unknown task" for task in unknown}
    for task in sorted(bases):
        path = out / f"{task}.json"
        if path.exists():
            status[task] = "exists"
            continue
        base = bases[task]
        try:
            seed = await build(
                runner, base.pr, slug=_bench.slug_for(task, "gold.diff"), image_ref=base.image,
                python=_bench.PYTHON, test_paths=base.test_paths, install_pytest=True,
            )
        except Exception as exc:  # one task failing must not end the build
            status[task] = f"failed: {type(exc).__name__}: {exc}"[:300]
            _write(out / f"{task}.error.txt", status[task] + "\n")
            continue
        _write(path, seed.to_json())
        status[task] = "built"
    return status


def stage_patches(bench: Path, stage: str, *, fraction: float | None = None) -> list[tuple[str, str, str]]:
    """The registered patches for a stage; main's budget sample is fixed once, on first use."""
    pairs = json.loads((bench / "pairs.json").read_text(encoding="utf-8"))
    pop = v.population(pairs, bench / "runs")
    pilot = v.pilot(pop)
    if stage == "pilot":
        return v.patches(pilot)
    main = v.main_pairs(pop, pilot)
    lock = bench / "study-v3" / "main" / "sample.json"
    if lock.exists():
        saved = json.loads(lock.read_text(encoding="utf-8"))
        if fraction is not None and fraction != saved["fraction"]:
            raise SystemExit(f"the main sample is already fixed at fraction {saved['fraction']} ({lock})")
        chosen = {(p["task"], p["wrong"]) for p in saved["pairs"]}
        return v.patches([p for p in main if (p.task, p.wrong) in chosen])
    if fraction is None:
        return v.patches(main)
    picked = v.sample(main, fraction)
    _write(lock, json.dumps({"fraction": fraction, "seed": v.SEED,
                             "pairs": [{"task": p.task, "wrong": p.wrong, "control": p.control} for p in picked]},
                            indent=1) + "\n")
    return v.patches(picked)


async def review_patch(bench: Path, task: str, stem: str, runner, client, gold: SeedRecord | None, out: Path) -> dict:
    seed = SeedRecord.from_json((bench / "seeds" / task / f"{stem}.json").read_text(encoding="utf-8"))
    report = json.loads((bench / "runs" / task / f"{stem}.json").read_text(encoding="utf-8"))
    review = await review_run(seed, report, runner, client)
    _write(out / f"{stem}.review.json", review.to_json())
    test = review.regression
    verified = bool(test and test.verified)
    outcome, gold_ops = None, 0
    if verified:
        if gold is None:
            outcome = "error"
        else:
            outcome = await _review_study.gold_check(SandboxPool(runner, op_budget=1), gold, test.path, test.source)
            gold_ops = 1
    status = None
    if test is not None:
        status = test.verification.status if test.verification else test.note
    return {
        "headline": len(review.triage.headline), "verified": verified, "status": status, "gold": outcome,
        "super_calls": review.triage.model_calls, "ultra_calls": test.attempts if test else 0,
        "ops": review.ops_used + gold_ops, "wall_s": round(review.wall_s, 3),
    }


EMPTY = {"headline": 0, "verified": False, "status": None, "gold": None,
         "super_calls": 0, "ultra_calls": 0, "ops": 0, "wall_s": 0.0}


async def run_stage(bench: Path, out: Path, gold_dir: Path, todo, runner, client) -> list[dict]:
    golds: dict[str, SeedRecord | None] = {}
    rows = []
    for task, stem, arm in todo:
        row_path = out / task / f"{stem}.row.json"
        prior = json.loads(row_path.read_text(encoding="utf-8")) if row_path.exists() else None
        if prior is not None and prior["error"] is None:
            rows.append(prior)
            continue
        if task not in golds:
            path = gold_dir / f"{task}.json"
            golds[task] = SeedRecord.from_json(path.read_text(encoding="utf-8")) if path.exists() else None
        row = {"task": task, "patch": stem, "arm": arm, "retries": prior["retries"] + 1 if prior else 0}
        try:
            row |= await review_patch(bench, task, stem, runner, client, golds[task], out / task)
            row["error"] = None
        except Exception as exc:  # recorded and retried later, never fatal to the stage
            row |= EMPTY | {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        _write(row_path, json.dumps(row, indent=1) + "\n")
        rows.append(row)
        print(f"  {task}/{stem} ({arm}): verified={row['verified']} gold={row['gold']} error={row['error']}")
    return rows


def write_report(out: Path) -> dict:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*/*.row.json"))]
    report = v.report(rows)
    _write(out / "report.json", json.dumps(report, indent=1) + "\n")
    return report


def _line(name: str, e: dict) -> str:
    if e["rate"] is None:
        return f"{name}: no data"
    lo, hi = e["wilson"]
    ci = e["cluster_interval"]
    clustered = f", task-clustered [{ci[0]:.0%}, {ci[1]:.0%}]" if ci else ""
    return (f"{name}: {e['k']}/{e['n']} = {e['rate']:.0%} (Wilson 95% [{lo:.0%}, {hi:.0%}]{clustered}; "
            f"mean of {e['tasks']} task rates {e['per_task_mean']:.0%})")


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gold-seeds")
    run = sub.add_parser("run")
    run.add_argument("stage", choices=["pilot", "main"])
    run.add_argument("--sample", type=float, default=None, help="budget rule: fraction of main pairs")
    rep = sub.add_parser("report")
    rep.add_argument("stage", choices=["pilot", "main"])
    args = parser.parse_args(argv)

    if args.cmd == "report":
        r = write_report(BENCH / "study-v3" / args.stage)
        print(f"{r['patches']} patches\n" + _line("yield", r["yield"]) + "\n" + _line("agreement", r["agreement"]))
        return 0

    from chesterton.llm.client import NemotronClient
    from chesterton.sandbox.contree import ConTreeSandboxRunner

    runner = ConTreeSandboxRunner()
    try:
        if args.cmd == "gold-seeds":
            pairs = json.loads((BENCH / "pairs.json").read_text(encoding="utf-8"))
            tasks = sorted({p.task for p in v.population(pairs, BENCH / "runs")})
            for task, state in (await build_gold_seeds(runner, tasks, BENCH / "gold-seeds")).items():
                print(f"  {task}: {state}")
            return 0
        if args.sample is not None and args.stage != "main":
            parser.error("--sample applies to the main stage only")
        todo = stage_patches(BENCH, args.stage, fraction=args.sample)
        print(f"{args.stage}: {len(todo)} patches")
        await run_stage(BENCH, BENCH / "study-v3" / args.stage, BENCH / "gold-seeds", todo, runner, NemotronClient())
        return 0
    finally:
        await runner.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd "C:/Users/manue/projects/chesterton" && .venv/Scripts/python.exe -m pytest -q tests/test_study_v3_script.py tests/test_benchmark_verified.py`

Expected: all pass.

The fixture's review must produce a verified test, so that the tests' assertions hold. The `runner()` handler makes the PR pass and the mutant fail, the same way `tests/test_demo_export.py::a_review` does. If `verified` comes out False, read `tests/test_demo_export.py` lines 56-67 and match its handler and artifacts. Don't weaken the assertions.

Then run the whole suite: `.venv/Scripts/python.exe -m pytest -q`. Every test must pass, and only the pre-existing live tests may skip.

- [ ] **Step 5: Check the registered population on the real data (read-only, no network)**

Run:

```bash
cd "C:/Users/manue/projects/chesterton" && .venv/Scripts/python.exe -c "
import importlib.util, pathlib
s = importlib.util.spec_from_file_location('s', 'scripts/study_v3.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
b = pathlib.Path('benchmark-v2')
print('pilot', len(m.stage_patches(b, 'pilot')), 'main', len(m.stage_patches(b, 'main')))"
```

Expected: `pilot 10 main 292`.

If the output differs, stop and report the numbers: the registration says 10 and 292.

This step writes nothing, because `stage_patches` without `--sample` never creates the lock.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/manue/projects/chesterton" && git add scripts/study_v3.py tests/test_study_v3_script.py
git commit -m "feat: the resumable study v3 driver: reference-fix seeds, pilot, main and report" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the plan (human, in your own terminal)

Always run the driver like this, so the log survives and printing never fails on the console's encoding:

```
PYTHONIOENCODING=utf-8 python scripts/study_v3.py … 2>&1 | tee logs/study-v3-<stage>.log
```

In this order (spec §17, Amendment 2):

1. **Gold seeds.** Run `gold-seeds`. It builds 16 seeds at about 2 minutes each. Check each printed `selectable` and `failing` count against the median of that task's v2 seeds, printed beside it: a large gap is image drift. Re-run it to retry a failed build. `run` refuses to start while a task has no seed, unless its recorded failure is accepted with `--accept-missing-gold`.
2. **Pilot.** Run `run pilot`, then `report pilot`, which prints the cost first and the estimands after it.
3. **Budget.** Read the billing (Nebius Token Factory plus sandboxes) and set c = the pilot's spend / 10. State a budget B, then run `budget --usd B --cost-per-patch C`. It prints f and each task's k, and writes nothing. The pilot's estimands are not consulted.
4. **Amendment 3.** If f < 1, record B, c and f in spec §17 as Amendment 3, before any main run. `run main --sample f --dry-run` prints the same k without writing the lock.
5. **Main.** Run `run main`, adding `--sample f` if f < 1. Re-invoke it to retry infrastructure failures. It exits non-zero if it stopped after 5 consecutive errors. Rows with an `other:` error are retried only with `--retry-other`.
6. **Report.** Run `report main`. It prints `INCOMPLETE: k of N rows` first if any registered row is missing.
7. **Record the result.** Write it into spec §17 under "Study v3 result, as registered", and into the README, whatever it is.
