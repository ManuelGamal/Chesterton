import json
from pathlib import Path

from chesterton.covmap.invert import (
    COVERAGE_CAPTURE_COMMANDS,
    invert_coverage,
    load_coverage,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = json.loads((FIXTURES / "coverage.json").read_text())


def test_maps_a_line_to_the_tests_that_execute_it():
    covmap = invert_coverage(REPORT)
    assert covmap["widgets/users.py"][2] == [
        "tests/test_users.py::test_get_user",
        "tests/test_users.py::test_rejects_blank",
    ]


def test_strips_the_phase_suffix_from_context_names():
    covmap = invert_coverage(REPORT)
    assert all(
        "|" not in test
        for tests in covmap["widgets/users.py"].values()
        for test in tests
    )


def test_drops_the_empty_context_which_means_no_test():
    assert invert_coverage(REPORT)["widgets/users.py"].get(8, []) == []


def test_line_numbers_are_integers_not_strings():
    covmap = invert_coverage(REPORT)
    assert all(isinstance(line, int) for line in covmap["widgets/users.py"])


def test_windows_paths_are_normalised_to_forward_slashes():
    # coverage.py emits native separators; GitHub diffs never do. Without
    # this, every lookup misses and every hunk looks uncovered.
    covmap = invert_coverage(REPORT)
    assert "widgets/billing.py" in covmap
    assert "widgets\\billing.py" not in covmap
    assert covmap["widgets/billing.py"][4] == ["tests/test_billing.py::test_charge"]


def test_load_coverage_reads_from_disk():
    covmap = load_coverage(FIXTURES / "coverage.json")
    assert covmap["widgets/users.py"][9] == ["tests/test_users.py::test_list_users"]


def test_the_documented_capture_command_uses_the_real_pytest_cov_flag():
    # --cov-context=test_function is coverage.py's dynamic_context setting,
    # not a pytest-cov flag value. Using it errors the baseline capture.
    assert "--cov-context=test" in COVERAGE_CAPTURE_COMMANDS[0]
    assert "test_function" not in COVERAGE_CAPTURE_COMMANDS[0]
