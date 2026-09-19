from chesterton.mutation.operators import apply_candidate, find_candidates

DECORATED = '''\
@rate_limit(10)
def charge(amount):
    if amount > 100:
        raise ValueError("too much")
    return amount
'''


def ops_on(source: str, lines: list[int]) -> set[str]:
    return {c.operator for c in find_candidates(source, lines)}


def test_a_decorator_line_offers_a_strip():
    assert "strip_decorator" in ops_on(DECORATED, [1])


def test_stripping_a_decorator_removes_exactly_that_line():
    candidate = next(
        c for c in find_candidates(DECORATED, [1]) if c.operator == "strip_decorator"
    )
    mutated = apply_candidate(DECORATED, candidate)
    assert "@rate_limit" not in mutated
    assert "def charge(amount):" in mutated
    assert "raise ValueError" in mutated


def test_a_condition_offers_an_inversion():
    assert "invert_condition" in ops_on(DECORATED, [3])


def test_inverting_a_condition_negates_the_test():
    candidate = next(
        c for c in find_candidates(DECORATED, [3]) if c.operator == "invert_condition"
    )
    mutated = apply_candidate(DECORATED, candidate)
    assert "if not (amount > 100)" in mutated


def test_a_comparison_offers_an_off_by_one():
    assert "off_by_one" in ops_on(DECORATED, [3])


def test_off_by_one_widens_the_boundary():
    candidate = next(
        c for c in find_candidates(DECORATED, [3]) if c.operator == "off_by_one"
    )
    mutated = apply_candidate(DECORATED, candidate)
    assert "amount >= 100" in mutated


def test_candidates_outside_the_changed_lines_are_ignored():
    # Only the PR's own changes are mutated; the rest of the file is not ours
    # to touch.
    assert find_candidates(DECORATED, [5]) == []


def test_unparseable_source_yields_no_candidates():
    assert find_candidates("def broken(:\n", [1]) == []


def test_every_candidate_carries_a_human_readable_description():
    for candidate in find_candidates(DECORATED, [1, 3]):
        assert candidate.description
        assert candidate.line > 0


CHAINED = "def f(a, b, c):\n    if a < b < c:\n        return 1\n"
TWIN = "def f(a, b, c, d):\n    if a > b and c > d:\n        return 1\n"


def test_a_chained_comparison_offers_one_candidate_per_comparator():
    cands = [c for c in find_candidates(CHAINED, [2]) if c.operator == "off_by_one"]
    assert len(cands) == 2


def test_applying_one_chained_candidate_shifts_exactly_one_boundary():
    # Flipping both operators at once is the super-mutant this design exists
    # to prevent: a surviving super-mutant says nothing about which change
    # the tests missed.
    cands = [c for c in find_candidates(CHAINED, [2]) if c.operator == "off_by_one"]
    results = {apply_candidate(CHAINED, c).splitlines()[1].strip() for c in cands}
    assert results == {"if a <= b < c:", "if a < b <= c:"}


def test_two_comparisons_on_one_line_are_separately_addressable():
    # Each candidate must mutate the comparison its description names.
    # Otherwise a surviving mutant is attributed to untouched code.
    cands = [c for c in find_candidates(TWIN, [2]) if c.operator == "off_by_one"]
    assert len(cands) == 2
    results = {apply_candidate(TWIN, c).splitlines()[1].strip() for c in cands}
    assert results == {"if a >= b and c > d:", "if a > b and c >= d:"}
