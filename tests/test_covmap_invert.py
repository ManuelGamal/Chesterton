import json
from pathlib import Path

from chesterton.covmap.invert import (
    COVERAGE_CAPTURE_COMMANDS,
    IMPORT_TIME,
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


def test_the_empty_context_is_recorded_as_import_time_not_dropped():
    # Reverses a Phase 1 ruling on live evidence (2026-09-19). The empty
    # context is code that ran outside any test, i.e. at import during
    # collection. Dropping it made nomenclature-284's changed
    # `from nomenclature.validation import log_error` a tier-0 finding:
    # "no test executes this line", on a line every test run executes.
    assert invert_coverage(REPORT)["widgets/users.py"][8] == [IMPORT_TIME]


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
