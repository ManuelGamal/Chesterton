import pytest

from chesterton.diffing.semantic import semantic_hunks

SOURCE = '''\
def get_user(user_id):
    if not user_id:
        raise ValueError("required")
    return _db.fetch(user_id)


def list_users(limit):
    rows = _db.fetch_all()
    return rows[:limit]
'''

BIG_TRY = "def f():\n    try:\n" + "".join(
    f"        step_{i}()\n" for i in range(60)
) + "    except ValueError:\n        handle()\n"

DECORATED = '''\
@rate_limit(10)
def charge(amount):
    return _gateway.charge(amount)
'''


def test_a_changed_line_expands_to_its_guard_clause():
    # Line 3 is the raise inside the if on line 2; the guard spans 2-3.
    hunks = semantic_hunks(SOURCE, "users.py", [3])
    assert len(hunks) == 1
    assert (hunks[0].start_line, hunks[0].end_line) == (2, 3)


def test_adjacent_lines_in_one_guard_produce_one_hunk():
    hunks = semantic_hunks(SOURCE, "users.py", [2, 3])
    assert len(hunks) == 1
    assert (hunks[0].start_line, hunks[0].end_line) == (2, 3)


def test_lines_in_different_functions_produce_separate_hunks():
    hunks = semantic_hunks(SOURCE, "users.py", [4, 8])
    assert len(hunks) == 2
    assert {h.start_line for h in hunks} == {4, 8}


def test_a_line_inside_a_large_try_does_not_swallow_the_block():
    # step_29() is at line 32; the enclosing try is far over the cap.
    hunks = semantic_hunks(BIG_TRY, "big.py", [32])
    assert len(hunks) == 1
    assert hunks[0].end_line - hunks[0].start_line + 1 <= 3


def test_an_except_header_maps_to_the_handler_not_the_whole_try():
    except_line = BIG_TRY.splitlines().index("    except ValueError:") + 1
    hunks = semantic_hunks(BIG_TRY, "big.py", [except_line])
    assert hunks[0].start_line == except_line


def test_a_decorator_line_yields_a_single_line_hunk():
    # Stripping @rate_limit means deleting exactly that line.
    hunks = semantic_hunks(DECORATED, "pay.py", [1])
    assert (hunks[0].start_line, hunks[0].end_line) == (1, 1)


def test_unparseable_source_falls_back_to_one_hunk_per_line():
    hunks = semantic_hunks("def broken(:\nx = (\n", "x.py", [1, 2])
    assert len(hunks) == 2
    assert (hunks[0].start_line, hunks[0].end_line) == (1, 1)
    assert (hunks[1].start_line, hunks[1].end_line) == (2, 2)


def test_a_line_outside_any_statement_still_yields_a_hunk():
    hunks = semantic_hunks(SOURCE, "users.py", [5])
    assert (hunks[0].start_line, hunks[0].end_line) == (5, 5)


def test_the_hunk_path_is_normalised_to_forward_slashes():
    # Every other boundary normalises; if this one does not, hunks never
    # match a coverage map and covered lines are reported as undefended.
    hunks = semantic_hunks(SOURCE, "widgets\\users.py", [4])
    assert hunks[0].file == "widgets/users.py"


def test_a_line_number_below_one_is_rejected():
    with pytest.raises(ValueError, match="outside"):
        semantic_hunks(SOURCE, "users.py", [0])


def test_a_line_past_the_end_of_the_source_is_rejected():
    # The visible symptom of a coordinate mismatch: source from one tree, line
    # numbers from another. Returning a confident hunk over unrelated content
    # is the failure mode this project exists to eliminate, so it must raise.
    with pytest.raises(ValueError, match="different trees"):
        semantic_hunks(SOURCE, "users.py", [500])


def test_valid_coordinates_at_the_file_boundary_are_accepted():
    # Off-by-one in the guard would be worse than no guard: it would reject
    # the last line of every file.
    last = len(SOURCE.splitlines())
    assert semantic_hunks(SOURCE, "users.py", [last])[0].end_line == last
