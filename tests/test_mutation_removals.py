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
    # Only if-blocks that exist to bail out are guards. Deleting an if that
    # does real work is a different, much noisier mutation.
    source = "def f(x):\n    if x:\n        y = compute(x)\n        log(y)\n    return 1\n"
    assert all(c.operator != "delete_guard" for c in find_candidates(source, [2]))


# The shape of nomenclature PR #284's own guard, measured live 2026-09-19. The
# old rule demanded a body of nothing but raise/return, so the headline
# operator never fired on the headline case.
LOGGED_GUARD = '''\
def apply(self, res):
    if not_defined := self.codes.validate(res.region):
        log_error("region", not_defined)
        raise ValueError("The validation failed.")
    return res
'''


def test_a_guard_that_logs_before_raising_offers_deletion():
    assert any(c.operator == "delete_guard" for c in find_candidates(LOGGED_GUARD, [2]))


def test_deleting_a_logged_guard_removes_the_log_and_the_raise_together():
    mutated = apply_candidate(LOGGED_GUARD, pick(LOGGED_GUARD, [2], "delete_guard"))
    assert "if not_defined" not in mutated
    assert "log_error" not in mutated
    assert "raise ValueError" not in mutated
    assert "return res" in mutated


def test_a_block_that_only_logs_is_not_a_guard():
    # A guard must bail out; logging alone changes nothing about control flow.
    source = "def f(x):\n    if x:\n        log(x)\n    return 1\n"
    assert all(c.operator != "delete_guard" for c in find_candidates(source, [2]))


def test_a_block_that_logs_after_raising_is_not_a_guard_shape_we_accept():
    # The exit must come LAST: statements after a raise are dead code, and a
    # body with dead code is not the bail-out shape this operator targets.
    source = "def f(x):\n    if x:\n        raise ValueError\n        log(x)\n    return 1\n"
    assert all(c.operator != "delete_guard" for c in find_candidates(source, [2]))


def test_an_assignment_before_the_raise_is_deliberately_not_accepted():
    # Pins the boundary that was approved: bare calls (logging, reporting)
    # before the exit, nothing else. Widening further is a separate decision.
    source = "def f(x):\n    if x:\n        msg = describe(x)\n        raise ValueError(msg)\n    return 1\n"
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


TWO_HANDLERS = '''\
def load(key):
    try:
        return cache[key]
    except ValueError:
        return None
    except KeyError:
        return default
'''


def test_widening_a_non_last_handler_yields_except_exception_not_bare():
    # Ruling P22: a bare `except:` is only legal as a try's LAST handler.
    # Widening an earlier one to bare would make LibCST refuse to render the
    # tree at all ("must be the last one"), aborting the whole run.
    candidate = pick(TWO_HANDLERS, [4], "widen_except")
    mutated = apply_candidate(TWO_HANDLERS, candidate)
    assert "except Exception:\n        return None\n" in mutated
    assert "except ValueError" not in mutated
    assert "except KeyError:\n        return default\n" in mutated  # untouched


def test_widening_the_last_handler_still_yields_bare_except():
    candidate = pick(TWO_HANDLERS, [6], "widen_except")
    mutated = apply_candidate(TWO_HANDLERS, candidate)
    assert "except ValueError:\n        return None\n" in mutated  # untouched
    assert "except:\n        return default\n" in mutated
    assert "except KeyError" not in mutated


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
