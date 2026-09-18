from chesterton.mutation.operators import apply_candidate, find_candidates

GUARD = '''\
def get_user(user_id):
    if not user_id:
        raise ValueError("required")
    return _db.fetch(user_id)
'''

ASYNC = '''\
async def save(record):
    await _db.write(record)
    return True
'''

NARROW = '''\
def load(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return None
'''

CLEANUP = '''\
def write(path, data):
    fh = open(path, "w")
    try:
        fh.write(data)
    finally:
        fh.close()
'''


def pick(source: str, lines: list[int], operator: str):
    return next(c for c in find_candidates(source, lines) if c.operator == operator)


def test_a_guard_clause_offers_deletion():
    assert apply_candidate(GUARD, pick(GUARD, [2], "delete_guard")) != GUARD


def test_deleting_a_guard_removes_the_whole_clause_not_half_of_it():
    # Half a guard is invalid Python. The gate would reject it, so this
    # operator would silently produce nothing.
    mutated = apply_candidate(GUARD, pick(GUARD, [2], "delete_guard"))
    assert "if not user_id" not in mutated
    assert "raise ValueError" not in mutated
    assert "return _db.fetch(user_id)" in mutated


def test_a_non_guard_if_is_not_offered_for_deletion():
    # Only if-blocks whose body is purely a raise or return are guards. Deleting
    # an if that does real work is a different, much noisier mutation.
    source = "def f(x):\n    if x:\n        y = compute(x)\n        log(y)\n    return 1\n"
    assert all(c.operator != "delete_guard" for c in find_candidates(source, [2]))


def test_an_await_offers_a_drop():
    mutated = apply_candidate(ASYNC, pick(ASYNC, [2], "drop_await"))
    assert "await " not in mutated
    assert "_db.write(record)" in mutated


def test_a_narrow_except_offers_widening():
    mutated = apply_candidate(NARROW, pick(NARROW, [4], "widen_except"))
    assert "except FileNotFoundError" not in mutated
    assert "except:" in mutated or "except Exception" in mutated


def test_a_bare_except_is_not_offered_for_widening():
    source = "def f():\n    try:\n        g()\n    except:\n        pass\n"
    assert all(c.operator != "widen_except" for c in find_candidates(source, [4]))


def test_a_finally_block_offers_cleanup_removal():
    # The `finally:` line is line 5 of CLEANUP.
    mutated = apply_candidate(CLEANUP, pick(CLEANUP, [5], "remove_cleanup"))
    assert "fh.close()" not in mutated
    assert "finally:" in mutated


def test_cleanup_removal_empties_the_block_rather_than_deleting_it():
    # Deleting the clause outright would leave a try with no handler, which is
    # invalid Python — the gate would reject every such mutant and this
    # operator would silently produce nothing.
    import ast

    ast.parse(apply_candidate(CLEANUP, pick(CLEANUP, [5], "remove_cleanup")))
