import pytest

from chesterton.seed.outcomes import classify_runs, parse_outcomes

SUMMARY = "=========================== short test summary info ===========================\n"

REPORT = """\
============================= test session starts =============================
collected 3 items

tests/test_pay.py .F.                                                     [100%]

=========================== short test summary info ===========================
PASSED tests/test_pay.py::test_charge
PASSED tests/test_pay.py::test_refund[zero]
FAILED tests/test_pay.py::test_broken - AssertionError: expected 3
SKIPPED [1] tests/test_pay.py:40: needs a network
1 failed, 2 passed, 1 skipped in 0.12s
"""


def test_summary_lines_become_node_id_outcomes():
    assert parse_outcomes(REPORT) == {
        "tests/test_pay.py::test_charge": "PASSED",
        "tests/test_pay.py::test_refund[zero]": "PASSED",
        "tests/test_pay.py::test_broken": "FAILED",
    }


def test_captured_log_lines_are_not_mistaken_for_test_outcomes():
    # Measured live 2026-09-19 on nomenclature-284: -rA prints captured log
    # output, and "ERROR    <logger>:<file>:<line>" matched the summary
    # pattern, filing five log lines as "failing tests".
    report = """\
==================================== PASSES ====================================
------------------------------ Captured log call -------------------------------
ERROR    nomenclature.core:core.py:74 The validation failed.
=========================== short test summary info ============================
PASSED tests/test_core.py::test_region_processing
1 passed in 0.50s
"""
    assert parse_outcomes(report) == {"tests/test_core.py::test_region_processing": "PASSED"}


def test_a_report_with_no_summary_section_yields_nothing():
    # No summary means pytest never got as far as reporting; guessing from
    # the rest of the output is how log lines became outcomes.
    assert parse_outcomes("ERROR    app:app.py:3 boom\n") == {}


def test_a_teardown_error_after_a_pass_is_not_a_pass():
    # -rA reports both phases for one test; any non-pass must win.
    report = SUMMARY + "PASSED tests/t.py::test_x\nERROR tests/t.py::test_x - RuntimeError\n"
    assert parse_outcomes(report) == {"tests/t.py::test_x": "ERROR"}


def test_a_non_pass_is_not_overwritten_by_a_later_pass():
    report = SUMMARY + "ERROR tests/t.py::test_x - boom\nPASSED tests/t.py::test_x\n"
    assert parse_outcomes(report) == {"tests/t.py::test_x": "ERROR"}


def test_only_tests_passing_every_run_are_selectable():
    stable = {"t::a": "PASSED", "t::b": "PASSED", "t::c": "FAILED"}
    wobbly = {"t::a": "PASSED", "t::b": "FAILED", "t::c": "FAILED"}

    result = classify_runs([stable, wobbly, stable])

    assert result.selectable == {"t::a"}
    assert result.flaky == {"t::b"}
    assert result.failing == {"t::c"}


def test_a_test_missing_from_one_run_is_flaky():
    # Not collected every time is a disagreement between runs.
    result = classify_runs([{"t::a": "PASSED"}, {}, {"t::a": "PASSED"}])

    assert result.flaky == {"t::a"}
    assert result.selectable == frozenset()


def test_an_expected_failure_is_never_selectable():
    result = classify_runs([{"t::x": "XFAIL"}] * 3)

    assert result.failing == {"t::x"}
    assert result.selectable == frozenset()


def test_classifying_no_runs_is_refused():
    with pytest.raises(ValueError):
        classify_runs([])
