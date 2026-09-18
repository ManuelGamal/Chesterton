from pathlib import Path

from chesterton.diffing.parse import changed_lines

FIXTURES = Path(__file__).parent / "fixtures"
DIFF = (FIXTURES / "pr.diff").read_text()


def test_reports_added_lines_in_post_patch_coordinates():
    # Hunk header @@ -30,3 +29,4 @@ resumes the new file at line 29, so the
    # context line is 29 and the added line is 30.
    assert changed_lines(DIFF)["widgets/users.py"] == [30]


def test_ignores_context_and_removed_lines():
    result = changed_lines(DIFF)["widgets/users.py"]
    assert 10 not in result
    assert 11 not in result


def test_handles_a_diff_with_no_added_lines():
    pure_deletion = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,2 +1,1 @@\n"
        " keep\n"
        "-drop\n"
    )
    assert changed_lines(pure_deletion) == {"x.py": []}


def test_a_deleted_file_contributes_no_added_lines():
    deleted = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-one\n"
        "-two\n"
    )
    assert changed_lines(deleted) == {}


def test_a_deleted_file_does_not_pollute_the_next_file():
    combined = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-one\n"
        "diff --git a/kept.py b/kept.py\n"
        "--- a/kept.py\n"
        "+++ b/kept.py\n"
        "@@ -1,1 +1,2 @@\n"
        " keep\n"
        "+added\n"
    )
    result = changed_lines(combined)
    assert result == {"kept.py": [2]}


def test_no_newline_marker_does_not_shift_later_lines():
    with_marker = (
        "diff --git a/y.py b/y.py\n"
        "--- a/y.py\n"
        "+++ b/y.py\n"
        "@@ -1,2 +1,3 @@\n"
        " first\n"
        "-old\n"
        "\\ No newline at end of file\n"
        "+new\n"
        "+last\n"
    )
    assert changed_lines(with_marker)["y.py"] == [2, 3]


def test_a_new_file_reports_all_its_lines():
    added_file = (
        "diff --git a/fresh.py b/fresh.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/fresh.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+alpha\n"
        "+beta\n"
    )
    assert changed_lines(added_file)["fresh.py"] == [1, 2]
