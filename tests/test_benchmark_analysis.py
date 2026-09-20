import pytest

from chesterton.benchmark.analysis import (
    PatchOutcome,
    analyse,
    binomial_tail,
    match_controls,
    outcome_from_report,
    patch_size,
)


def an_outcome(group, *, task="t", patch="p", changed=10, survivors=0, tier0=0, run=5):
    return PatchOutcome(task=task, patch=patch, group=group, changed_lines=changed,
                        mutants_run=run, survivors=survivors, tier0=tier0)


def test_a_patch_is_flagged_by_any_survivor_or_tier0_finding():
    assert an_outcome("wrong", survivors=1).flagged
    assert an_outcome("wrong", tier0=1).flagged
    assert not an_outcome("wrong").flagged


def test_the_rate_normalises_findings_by_changed_executable_lines():
    # Agent patches add code, so raw survivor counts partly measure volume.
    assert an_outcome("wrong", changed=20, survivors=3, tier0=1).rate == 0.2
    assert an_outcome("wrong", changed=0).rate == 0.0


def test_an_outcome_is_read_from_a_run_report():
    report = {"counts": {"killed": 4, "survived": 3, "uncovered": 2, "error": 1},
              "tier0": [["a.py", 3]]}
    outcome = outcome_from_report(report, task="t", patch="p", group="wrong", changed_lines=9)

    assert (outcome.mutants_run, outcome.survivors, outcome.tier0) == (7, 3, 1)


def test_the_binomial_tail_matches_a_hand_computed_value():
    # P(X >= 8 | n = 9, p = 1/2) = (C(9,8) + C(9,9)) / 2^9 = 10/512
    assert binomial_tail(8, 9) == pytest.approx(10 / 512)
    assert binomial_tail(0, 5) == 1.0


def test_mcnemar_counts_only_discordant_pairs():
    pairs = (
        [(an_outcome("wrong", survivors=1), an_outcome("control"))] * 8
        + [(an_outcome("wrong"), an_outcome("control", survivors=1))] * 1
        + [(an_outcome("wrong", survivors=1), an_outcome("control", survivors=1))] * 5
    )

    result = analyse(pairs)

    assert (result.discordant_wrong, result.discordant_control) == (8, 1)
    assert result.mcnemar_p == pytest.approx(10 / 512)
    assert result.wrong_flag_rate == pytest.approx(13 / 14)
    assert result.control_flag_rate == pytest.approx(6 / 14)


def test_the_sign_test_compares_rates_within_each_pair_and_drops_ties():
    pairs = [
        (an_outcome("wrong", survivors=5), an_outcome("control", survivors=1)),
        (an_outcome("wrong", survivors=5), an_outcome("control", survivors=1)),
        (an_outcome("wrong", survivors=1), an_outcome("control", survivors=1)),  # tie
    ]

    result = analyse(pairs)

    assert (result.rate_wins, result.rate_losses, result.rate_ties) == (2, 0, 1)
    assert result.sign_p == pytest.approx(0.25)


def test_no_discordant_pairs_gives_no_evidence_either_way():
    result = analyse([(an_outcome("wrong"), an_outcome("control"))])
    assert result.mcnemar_p == 1.0
    assert result.sign_p == 1.0


def test_a_pair_must_be_wrong_then_control_from_the_same_task():
    with pytest.raises(ValueError, match="wrong, control"):
        analyse([(an_outcome("control"), an_outcome("wrong"))])
    with pytest.raises(ValueError, match="same task"):
        analyse([(an_outcome("wrong", task="a"), an_outcome("control", task="b"))])


def test_patch_size_counts_changed_source_lines_only():
    diff = (
        "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n"
        "@@ -1,2 +1,3 @@\n x = 1\n-y = 2\n+y = 3\n+z = 4\n"
        "diff --git a/tests/test_a.py b/tests/test_a.py\n--- a/tests/test_a.py\n"
        "+++ b/tests/test_a.py\n@@ -1 +1,2 @@\n import a\n+assert a\n"
    )
    assert patch_size(diff) == 3  # one removed and two added in pkg/a.py


def test_patch_size_reads_a_truncated_diff_unidiff_refuses():
    # Live 2026-09-20: agent patches from SWE-bench submissions can promise
    # more lines in a hunk header than the body carries. They still apply
    # under `patch --fuzz`, and SWE-bench counted them, so the benchmark
    # must read them rather than crash on them.
    truncated = (
        "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n"
        "@@ -1,7 +1,10 @@\n def f():\n-    return 1\n+    return 2\n"
        "diff --git a/tests/test_a.py b/tests/test_a.py\n--- a/tests/test_a.py\n"
        "+++ b/tests/test_a.py\n@@ -1 +1,2 @@\n import pkg\n+assert pkg\n"
    )

    assert patch_size(truncated) == 2  # one removed, one added, in pkg/a.py only


def test_controls_are_matched_on_size_without_replacement_and_deterministically():
    wrong = [("w1", 10), ("w2", 30)]
    controls = [("c1", 9), ("c2", 11), ("c3", 31), ("c4", 100)]

    pairs = match_controls(wrong, controls)

    # w1 takes the nearest (c1 and c2 tie at distance 1; name breaks the tie).
    assert pairs == [("w1", "c1"), ("w2", "c3")]


def test_a_wrong_patch_with_no_control_left_is_reported_unmatched():
    assert match_controls([("w1", 5), ("w2", 6)], [("c1", 5)]) == [("w1", "c1"), ("w2", None)]
