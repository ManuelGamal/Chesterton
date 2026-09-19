import asyncio

from chesterton.execute.pool import BudgetExhausted
from chesterton.reduce.ddmin import Outcome, ddmin


def needs(required, *, unresolved_if=frozenset(), log=None, delay=0.0, stats=None):
    """A monotone predicate: holds iff every element of `required` is kept."""

    async def probe(subset):
        if log is not None:
            log.append(subset)
        if stats is not None:
            stats["now"] += 1
            stats["peak"] = max(stats["peak"], stats["now"])
        await asyncio.sleep(delay)
        if stats is not None:
            stats["now"] -= 1
        if subset & unresolved_if:
            return Outcome.UNRESOLVED
        return Outcome.HOLDS if required <= subset else Outcome.FAILS

    return probe


async def test_a_known_minimal_subset_is_found():
    result = await ddmin(range(10), needs({2, 5}))

    assert result.minimal == {2, 5}
    assert result.exhausted is False


async def test_a_single_needed_element_is_found():
    assert (await ddmin(range(8), needs({6}))).minimal == {6}


async def test_when_everything_is_needed_everything_is_returned():
    assert (await ddmin(range(5), needs(set(range(5))))).minimal == set(range(5))


async def test_when_nothing_is_needed_one_probe_says_so():
    # Ruling P3-1: the whole PR reverted and the suite still passes means
    # the entire PR is undefended, at the cost of exactly one probe.
    result = await ddmin(range(10), needs(set()))

    assert result.minimal == frozenset()
    assert result.probes == 1


async def test_an_unresolved_probe_never_counts_as_holding():
    # Any subset containing 2 errors, and 2 sorts BEFORE the needed 7, so at
    # every split the first candidate in order is an unresolved one. If
    # UNRESOLVED counted as holding, ddmin would take it and end on {2}.
    # (With the order reversed this test passed even with that bug.)
    result = await ddmin(range(10), needs({7}, unresolved_if=frozenset({2})))

    assert result.minimal == {7}


async def test_no_subset_is_probed_twice():
    log = []
    await ddmin(range(12), needs({3, 9}, log=log))

    assert len(log) == len(set(log))


async def test_probes_at_one_granularity_run_concurrently():
    stats = {"now": 0, "peak": 0}
    await ddmin(range(8), needs({1, 6}, delay=0.01, stats=stats))

    assert stats["peak"] > 1


async def test_a_spent_budget_returns_a_sound_upper_bound_marked_exhausted():
    calls = {"n": 0}
    inner = needs({2, 5})

    async def budgeted(subset):
        calls["n"] += 1
        if calls["n"] > 3:
            raise BudgetExhausted("spent")
        return await inner(subset)

    result = await ddmin(range(10), budgeted)

    assert result.exhausted is True
    # Cut short, the set in hand still holds: it contains all that is needed.
    assert {2, 5} <= result.minimal


async def test_the_result_is_deterministic():
    first = await ddmin(range(16), needs({0, 7, 15}))
    second = await ddmin(range(16), needs({0, 7, 15}))

    assert first == second


async def test_no_elements_means_no_probes():
    result = await ddmin([], needs(set()))

    assert result.minimal == frozenset()
    assert result.probes == 0
