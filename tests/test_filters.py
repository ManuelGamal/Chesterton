import pytest

from chesterton.filters import is_mutable_source


@pytest.mark.parametrize(
    "path",
    [
        "widgets/users.py",
        "src/pkg/core.py",
        "a.py",
    ],
)
def test_python_sources_are_mutable(path):
    assert is_mutable_source(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "pyproject.toml",
        "poetry.lock",
        "widgets/data.json",
        "Makefile",
        "",
    ],
)
def test_non_python_files_are_not_mutable(path):
    # A prose hunk would otherwise reach semantic_hunks, fall back to per-line
    # hunks on a SyntaxError, and produce confident findings about a README.
    assert is_mutable_source(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_users.py",
        "widgets/tests/test_core.py",
        "test/test_thing.py",
        "widgets/users_test.py",
        "conftest.py",
        "widgets/conftest.py",
    ],
)
def test_test_files_are_not_mutable(path):
    # Mutating a test and then running that same test is circular: the file
    # covers itself, so the mutant always dies and the finding means nothing.
    assert is_mutable_source(path) is False


def test_a_source_file_merely_containing_test_in_its_name_is_mutable():
    # "latest" and "contest" are not tests. Substring matching would be wrong.
    assert is_mutable_source("widgets/latest_release.py") is True
    assert is_mutable_source("widgets/contest.py") is True


@pytest.mark.parametrize(
    "path",
    [
        "latest/x.py",
        "contests/rank.py",
        "src/protest/a.py",
        "latest_release/notes.py",
        "widgets/latest_release.py",
    ],
)
def test_a_directory_merely_containing_test_in_its_name_is_mutable(path):
    # The directory rule matches whole segments. The filename cases above are
    # governed by separate prefix/suffix checks, so they cannot catch a
    # substring match creeping into the directory rule.
    assert is_mutable_source(path) is True


@pytest.mark.parametrize(
    "path", ["a/b/tests/c/d.py", "Tests/helpers.py", "src/TEST/util.py"]
)
def test_a_test_directory_at_any_depth_and_any_case_is_not_mutable(path):
    assert is_mutable_source(path) is False


def test_windows_separators_are_handled():
    assert is_mutable_source("widgets\\tests\\test_x.py") is False
    assert is_mutable_source("widgets\\users.py") is True
