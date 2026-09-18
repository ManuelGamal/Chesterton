from chesterton.defended import (
    defended_hunks,
    tests_for_hunk,
    uncovered_findings,
)
from chesterton.models import Hunk

COVMAP = {
    "users.py": {
        2: ["tests/test_users.py::test_get_user"],
        3: ["tests/test_users.py::test_get_user", "tests/test_users.py::test_blank"],
        8: [],
    }
}


def test_collects_the_union_of_tests_covering_a_hunk():
    result = defended_hunks([Hunk("users.py", 2, 3)], COVMAP)
    assert result[0].tests == [
        "tests/test_users.py::test_blank",
        "tests/test_users.py::test_get_user",
    ]


def test_reports_lines_no_test_executes():
    result = defended_hunks([Hunk("users.py", 8, 8)], COVMAP)
    assert result[0].uncovered_lines == [8]
    assert result[0].fully_uncovered is True


def test_a_line_absent_from_the_map_counts_as_uncovered():
    result = defended_hunks([Hunk("users.py", 99, 99)], COVMAP)
    assert result[0].uncovered_lines == [99]


def test_a_hunk_in_an_unknown_file_is_entirely_uncovered():
    result = defended_hunks([Hunk("ghost.py", 1, 2)], COVMAP)
    assert result[0].uncovered_lines == [1, 2]
    assert result[0].tests == []


def test_a_partly_covered_hunk_is_not_fully_uncovered():
    result = defended_hunks([Hunk("users.py", 2, 8)], COVMAP)
    assert result[0].fully_uncovered is False
    assert result[0].uncovered_lines == [4, 5, 6, 7, 8]


def test_tier_zero_findings_are_reported_per_line_not_per_hunk():
    # A partly covered hunk still contains undefended lines, and each one is
    # a finding. Rolling them into one boolean hides most of them.
    findings = uncovered_findings([Hunk("users.py", 2, 8)], COVMAP)
    assert findings == [
        ("users.py", 4),
        ("users.py", 5),
        ("users.py", 6),
        ("users.py", 7),
        ("users.py", 8),
    ]


def test_tests_are_selected_per_hunk_not_unioned_across_hunks():
    # Each mutant targets ONE hunk and must run only that hunk's tests.
    assert tests_for_hunk(Hunk("users.py", 2, 2), COVMAP) == [
        "tests/test_users.py::test_get_user"
    ]
    assert tests_for_hunk(Hunk("users.py", 3, 3), COVMAP) == [
        "tests/test_users.py::test_blank",
        "tests/test_users.py::test_get_user",
    ]


def test_an_empty_hunk_list_yields_no_defences_and_no_findings():
    assert defended_hunks([], COVMAP) == []
    assert uncovered_findings([], COVMAP) == []


def test_an_empty_coverage_map_makes_everything_uncovered():
    result = defended_hunks([Hunk("users.py", 1, 2)], {})
    assert result[0].uncovered_lines == [1, 2]
    assert result[0].fully_uncovered is True
