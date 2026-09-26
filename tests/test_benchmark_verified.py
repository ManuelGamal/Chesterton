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
             {"task": "t1", "wrong": "w2.diff", "control": "c2.diff"},
             # match_controls leaves this null when no control is left; it
             # has no control run file, so it is excluded, not an error.
             {"task": "t1", "wrong": "w3.diff", "control": None}]

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
    retried = row("a", verified=True, gold="passes_on_gold")
    retried["retries"] = 1
    rows = [retried,
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
    assert r["no_test_reasons"] == {"no headline": 1, "not verified: fails_on_patch": 1, "error: infrastructure": 1}
    assert r["headline_counts"] == {"1": 2, "0": 2}
    assert r["cost"]["super_calls"] == {"median": 3.0, "total": 9}
    assert r["cost_rows"] == 3
    assert r["retried"] == [{"task": "a", "patch": "p", "retries": 1, "history": []}]
    assert r["errors"] == [{"task": "b", "patch": "p", "error": "SandboxError: gone"}]
    json.dumps(r)  # the report is plain JSON


def test_a_gold_error_is_listed_classified_and_counted_in_the_agreement_bound():
    bad = row("a", verified=True, gold="error")
    bad |= {"patch": "w2", "gold_exit": 2, "gold_tail": "E   ModuleNotFoundError: No module named 'x'"}
    rows = [row("a", verified=True, gold="passes_on_gold"), bad, row("b", verified=True, gold="fails_on_gold")]

    r = v.report(rows)

    assert r["gold_errors"] == 1
    assert r["gold_errors_list"] == [{"task": "a", "patch": "w2", "exit": 2, "kind": "collection"}]
    assert (r["agreement"]["k"], r["agreement"]["n"]) == (1, 2)
    assert (r["agreement_bound"]["k"], r["agreement_bound"]["n"]) == (1, 3)


def test_a_gold_error_from_a_missing_seed_is_other_whatever_its_build_failure_says():
    no_seed = row("a", verified=True, gold="error")
    no_seed |= {"gold_exit": None, "gold_tail": "no reference-fix seed: failed: SeedBuildError: ImportError: pip"}

    assert v.report([no_seed])["gold_errors_list"] == [{"task": "a", "patch": "p", "exit": None, "kind": "other"}]


def test_a_gold_error_is_a_collection_error_only_when_its_tail_says_so():
    assert v.gold_error_kind("ImportError while importing test module") == "collection"
    assert v.gold_error_kind("!!! Interrupted: 1 error during collection !!!") == "collection"
    assert v.gold_error_kind("!!! Interrupted: 2 errors during collection !!!") == "collection"
    assert v.gold_error_kind("_____ ERROR collecting tests/test_x.py _____") == "collection"
    assert v.gold_error_kind("Segmentation fault") == "other"
    assert v.gold_error_kind(None) == "other"


def test_the_no_test_reasons_are_fixed_categories():
    capped = row("a", headline=1, status="error")
    capped |= {"infra_capped": True, "infra_reason": "verification status is error"}
    rows = [row("a", headline=0), row("a", status="no regression test generated: private_api (_x, _y)"),
            row("a", status="fails_on_patch"), capped,
            row("b", headline=0, error="other: ValueError: slug"),
            row("b", headline=0, error="infrastructure: OpenAIError: outage")]

    r = v.report(rows)

    assert r["no_test_reasons"] == {
        "no headline": 1, "not verified: private_api": 1, "not verified: fails_on_patch": 1,
        "infrastructure (capped)": 1, "error: other": 1, "error: infrastructure": 1,
    }
    assert r["infra_capped"] == [{"task": "a", "patch": "p", "reason": "verification status is error"}]
    assert v.normalise_status("no covering test to place a new test beside") == "no covering test"
    assert v.normalise_status("regression stage failed: SandboxReadError: gone") == "regression stage failed"
    assert v.normalise_status(None) == "none"


def test_the_report_states_what_is_missing_the_sample_and_its_provenance():
    stub = {"commit": "abc1234", "dirty": False, "pipeline_unchanged_since_registration": True,
            "models": {"reasoning": "m1"}, "python": "3.13.0"}
    sample = {"fraction": 0.5, "seed": v.SEED, "pairs_per_task": {"a": 1}}

    r = v.report([row("a")], missing=[{"task": "a", "patch": "c1"}], sample=sample, provenance=stub)

    assert (r["expected"], r["present"]) == (2, 1)
    assert r["missing"] == [{"task": "a", "patch": "c1"}]
    assert r["sample"] == sample
    assert r["provenance"] == stub
    assert v.report([row("a")])["sample"] is None


def test_the_sensitivity_without_matplotlib_23314_leaves_that_task_out():
    rows = [row("matplotlib__matplotlib-23314", verified=True, gold="fails_on_gold"),
            row("matplotlib__matplotlib-23314", verified=True, gold="fails_on_gold"),
            row("a", verified=True, gold="passes_on_gold"), row("a")]

    r = v.report(rows)

    assert (r["yield"]["k"], r["yield"]["n"]) == (3, 4)
    s = r["without_matplotlib_23314"]
    assert (s["yield"]["k"], s["yield"]["n"]) == (1, 2)
    assert (s["agreement"]["k"], s["agreement"]["n"]) == (1, 1)


def test_the_budget_fraction_is_rounded_down_to_a_multiple_of_five_hundredths():
    assert v.budget_fraction(20, 0.1) == 0.65  # 20 / 29.2 = 0.6849
    assert v.budget_fraction(1000, 0.1) == 1.0
    assert v.budget_fraction(29.2, 0.1) == 1.0
    assert v.budget_fraction(14.6, 0.1) == 0.5  # exactly 0.5, not 0.45 by float error
    assert v.budget_fraction(0.01, 0.1) == 0.0
    with pytest.raises(ValueError):
        v.budget_fraction(10, 0)


def test_the_sample_sizes_are_the_k_the_sample_draws():
    pop = pop_of({"a": 10, "b": 4, "c": 1})

    sizes = v.sample_sizes(pop, 0.5)

    assert sizes == {"a": (5, 10), "b": (2, 4), "c": (1, 1)}
    assert sum(k for k, _ in sizes.values()) == len(v.sample(pop, 0.5))
