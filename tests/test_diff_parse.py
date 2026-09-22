from pathlib import Path

from chesterton.diffing.parse import changed_lines

FIXTURES = Path(__file__).parent / "fixtures"
DIFF = (FIXTURES / "pr.diff").read_text()


def test_reports_added_lines_in_post_patch_coordinates():
    # Hunk header @@ -30,2 +29,3 @@ resumes the new file at line 29, so the
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


# --- tolerant splitting -----------------------------------------------------
# Live 2026-09-20: agent patches from SWE-bench submissions can be truncated
# (a hunk header promising more lines than the body carries) or use git's
# quoted form for non-ASCII paths. unidiff raises on the first and mis-splits
# the second, which crashed both the benchmark and patch review.

TRUNCATED = (
    "diff --git a/pkg/a.py b/pkg/a.py\n"
    "--- a/pkg/a.py\n"
    "+++ b/pkg/a.py\n"
    "@@ -1,7 +1,10 @@\n"
    " def f():\n"
    "-    return 1\n"
    "+    return 2\n"
    # Raw: git writes the octal escapes literally, and a plain Python string
    # would turn \303\244 into two characters before the parser ever saw it.
    r'diff --git "a/doc/testim\303\244ge.png" "b/doc/testim\303\244ge.png"' + "\n"
    "--- a/doc/x.png\n"
    "+++ b/doc/x.png\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
    "diff --git a/tests/test_a.py b/tests/test_a.py\n"
    "--- a/tests/test_a.py\n"
    "+++ b/tests/test_a.py\n"
    "@@ -1 +1,2 @@\n"
    " import pkg\n"
    "+assert pkg\n"
)


def test_a_truncated_diff_still_splits_into_its_files():
    from chesterton.diffing.parse import split_by_file

    sections = split_by_file(TRUNCATED)

    assert [path for path, _ in sections] == [
        "pkg/a.py",  # noqa: the next entry is git's quoted, UTF-8 encoded path
        "doc/testimäge.png",
        "tests/test_a.py",
    ]


def test_each_section_keeps_its_own_text_verbatim():
    from chesterton.diffing.parse import split_by_file

    sections = dict(split_by_file(TRUNCATED))

    assert sections["pkg/a.py"].startswith("diff --git a/pkg/a.py")
    assert sections["pkg/a.py"].endswith("+    return 2\n")
    assert "".join(text for _, text in split_by_file(TRUNCATED)) == TRUNCATED


def test_a_diff_with_no_headers_yields_nothing():
    from chesterton.diffing.parse import split_by_file

    assert split_by_file("not a diff at all\n") == []


# --- files a patch creates --------------------------------------------------
# Live 2026-09-22: agent patches carry scratch scripts (reproduce_issue.py,
# debug_where2.py) that no test imports. Telling them apart starts with
# knowing which files the patch created rather than edited.

SCRATCH = (
    "diff --git a/pkg/a.py b/pkg/a.py\n"
    "--- a/pkg/a.py\n"
    "+++ b/pkg/a.py\n"
    "@@ -1 +1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
    "diff --git a/reproduce_issue.py b/reproduce_issue.py\n"
    "new file mode 100644\n"
    "index 0000000..e69de29\n"
    "--- /dev/null\n"
    "+++ b/reproduce_issue.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+import pkg\n"
    "+print(pkg.x)\n"
)


def test_a_created_file_is_reported_and_an_edited_one_is_not():
    from chesterton.diffing.parse import added_files

    assert added_files(SCRATCH) == {"reproduce_issue.py"}


def test_a_created_file_is_found_even_in_a_truncated_diff():
    from chesterton.diffing.parse import added_files

    # The hunk promises 5 lines and carries 2, which unidiff refuses.
    truncated = SCRATCH.replace("+1,2 @@", "+1,5 @@")

    assert added_files(truncated) == {"reproduce_issue.py"}


def test_a_diff_that_creates_nothing_reports_nothing():
    from chesterton.diffing.parse import added_files

    assert added_files(TRUNCATED) == set()
