"""Delta debugging over a set, with sandbox forks as the oracle (spec §8).

This is Zeller's ddmin, reading "the property holds" where the textbook
reads "the test fails". It returns a 1-minimal subset that still holds:
removing any single element makes it stop holding.

There are two departures from the textbook, both for the platform:

- Every candidate at one granularity is probed CONCURRENTLY (ruling P3-7).
  Forks are cheap and independent, and wall clock is what a live demo
  spends. The choice among candidates is still the first in a fixed order,
  so the result is the one sequential ddmin would reach, at the price of
  extra probes.
- Probes are cached by subset. ddmin revisits subsets, and every probe is a
  sandbox op against a finite budget.

UNRESOLVED (the probe errored, or pytest exited with something other than a
pass or a fail) counts as "does not hold". That preserves the invariant that
the current set always holds, and the invariant is what makes a search cut
short by the budget still sound (ruling P3-8). The set in hand is an upper
bound on what is needed. The result says it was cut short rather than
claiming to be minimal.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from chesterton.execute.pool import BudgetExhausted

T = TypeVar("T")


class Outcome(Enum):
    HOLDS = "holds"
    FAILS = "fails"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class DdminResult(Generic[T]):
    minimal: frozenset[T]
    probes: int
    exhausted: bool


def _split(items: list[T], n: int) -> list[list[T]]:
    size, extra = divmod(len(items), n)
    chunks, start = [], 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        chunks.append(items[start:end])
        start = end
    return [chunk for chunk in chunks if chunk]


async def ddmin(
    elements: Sequence[T],
    probe: Callable[[frozenset[T]], Awaitable[Outcome]],
    *,
    check_empty: bool = True,
) -> DdminResult[T]:
    cache: dict[frozenset[T], Outcome] = {}
    exhausted = False

    async def holding(candidates: list[frozenset[T]]) -> list[bool]:
        nonlocal exhausted
        todo = [c for c in dict.fromkeys(candidates) if c not in cache]
        outcomes = await asyncio.gather(
            *(probe(c) for c in todo), return_exceptions=True
        )
        for candidate, outcome in zip(todo, outcomes):
            if isinstance(outcome, BudgetExhausted):
                exhausted = True
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                cache[candidate] = outcome
        return [cache.get(c) is Outcome.HOLDS for c in candidates]

    current = list(elements)

    if check_empty and current:
        [empty_holds] = await holding([frozenset()])
        if empty_holds:
            return DdminResult(frozenset(), len(cache), exhausted)
        if exhausted:
            return DdminResult(frozenset(current), len(cache), True)

    n = 2
    while len(current) >= 2:
        subsets = [frozenset(chunk) for chunk in _split(current, n)]

        results = await holding(subsets)
        if exhausted:
            break
        hit = next((i for i, ok in enumerate(results) if ok), None)
        if hit is not None:
            current = [e for e in current if e in subsets[hit]]
            n = 2
            continue

        complements = [frozenset(e for e in current if e not in s) for s in subsets]
        results = await holding(complements)
        if exhausted:
            break
        hit = next((i for i, ok in enumerate(results) if ok), None)
        if hit is not None:
            current = [e for e in current if e in complements[hit]]
            n = max(n - 1, 2)
            continue

        if n >= len(current):
            break
        n = min(2 * n, len(current))

    return DdminResult(frozenset(current), len(cache), exhausted)
