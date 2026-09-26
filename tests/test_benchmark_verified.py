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
