from chesterton.reduce.patch import patch_hunks, probe_files, revert

BASE = "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"
HEAD = "a = 1\nc = 3\nd = 4\ne = 50"

DIFF = (
    "--- a/m.py\n"
    "+++ b/m.py\n"
    "@@ -1,2 +1,1 @@\n"
    " a = 1\n"
    "-b = 2\n"
    "@@ -5 +4 @@\n"
    "-e = 5\n"
    "+e = 50\n"
    "\\ No newline at end of file\n"
    "--- /dev/null\n"
    "+++ b/new.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+x = 1\n"
    "+y = 2\n"
    "--- a/gone.py\n"
    "+++ b/gone.py\n"
    "@@ -1,2 +0,0 @@\n"
    "-p = 1\n"
    "-q = 2\n"
    "--- a/tests/test_m.py\n"
    "+++ b/tests/test_m.py\n"
    "@@ -1 +1 @@\n"
    "-assert True\n"
    "+assert 1\n"
    "--- a/README.md\n"
    "+++ b/README.md\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


def test_only_source_hunks_are_kept_and_the_rest_are_counted():
    hunks, skipped = patch_hunks(DIFF)

    assert [h.label for h in hunks] == ["m.py#0", "m.py#1", "new.py#0"]
    assert skipped == {"removed_file": 1, "not_mutable_source": 2}


def test_reverting_every_hunk_of_a_file_restores_the_base_exactly():
    hunks, _ = patch_hunks(DIFF)
    m_hunks = [h for h in hunks if h.file == "m.py"]

    assert revert(HEAD, m_hunks) == BASE


def test_reverting_one_hunk_leaves_the_other_applied():
    hunks, _ = patch_hunks(DIFF)
    first = next(h for h in hunks if h.label == "m.py#0")

    assert revert(HEAD, [first]) == "a = 1\nb = 2\nc = 3\nd = 4\ne = 50"


def test_a_pure_deletion_is_reinserted_after_its_anchor_line():
    # @@ -3 +2,0 @@ : the deletion sits AFTER head line 2.
    diff = "--- a/m.py\n+++ b/m.py\n@@ -3 +2,0 @@\n-c = 3\n"
    [hunk], _ = patch_hunks(diff)

    assert revert("a = 1\nb = 2\nd = 4\n", [hunk]) == "a = 1\nb = 2\nc = 3\nd = 4\n"


def test_reverting_an_added_file_empties_it():
    hunks, _ = patch_hunks(DIFF)
    added = next(h for h in hunks if h.file == "new.py")

    assert revert("x = 1\ny = 2\n", [added]) == ""


def test_a_base_line_without_a_trailing_newline_is_restored_without_one():
    # The marker follows the REMOVED line, so the base had no final newline.
    diff = (
        "--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n"
        "-x = 1\n\\ No newline at end of file\n+x = 2\n"
    )
    [hunk], _ = patch_hunks(diff)

    assert revert("x = 2\n", [hunk]) == "x = 1"


def test_probe_files_writes_only_files_with_a_reverted_hunk():
    hunks, _ = patch_hunks(DIFF)
    sources = {"m.py": HEAD, "new.py": "x = 1\ny = 2\n"}
    keep = frozenset(h for h in hunks if h.file == "new.py")

    files = probe_files(sources, "/testbed", hunks, keep)

    assert files == {"/testbed/m.py": BASE}


def test_keeping_every_hunk_writes_nothing():
    hunks, _ = patch_hunks(DIFF)
    sources = {"m.py": HEAD, "new.py": "x = 1\ny = 2\n"}

    assert probe_files(sources, "/testbed", hunks, frozenset(hunks)) == {}
