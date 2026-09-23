"""The triage pass over one run's survivors (spec §9).

Pre-filter, classify, rank, confirm. A headline finding was called an
untested invariant, confidently, on every one of `samples` independent
calls. Anything the model was unsure of, or disagreed with itself about, is
"worth a look": kept, never promoted. "Three confident findings beat eleven
noisy ones."
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace

from chesterton.execute.mutants import MutantResult
from chesterton.triage.classify import Classification, ModelUnavailable, classify_survivor
from chesterton.triage.evidence import Evidence, evidence_for
from chesterton.triage.prefilter import prefilter


@dataclass(frozen=True)
class TriagedSurvivor:
    evidence: Evidence
    classification: Classification
    #: For a confirmed candidate: how many of the samples agreed.
    agreement: int | None = None
    #: The pre-filter's reason, when it dismissed this without a model call.
    prefiltered: str | None = None


@dataclass(frozen=True)
class TriageReport:
    headline: list[TriagedSurvivor]
    worth_a_look: list[TriagedSurvivor]
    dismissed: list[TriagedSurvivor]
    model_calls: int


def _candidate(c: Classification) -> bool:
    return c.label == "untested_invariant" and c.confident


def _rank(t: TriagedSurvivor) -> tuple:
    ev = t.evidence
    return (
        0 if t.classification.category == "safety" else 1,
        -len(ev.tests),
        ev.file, ev.start_line, ev.mutant.content_hash,
    )


def _hunk(t: TriagedSurvivor) -> tuple[str, int, int]:
    return (t.evidence.file, t.evidence.start_line, t.evidence.end_line)


async def triage(
    client,
    results: Sequence[MutantResult],
    pr_title: str,
    *,
    samples: int = 3,
    headline_limit: int = 3,
    concurrency: int = 4,
) -> TriageReport:
    semaphore = asyncio.Semaphore(concurrency)
    calls = 0

    async def classify(ev: Evidence) -> Classification:
        nonlocal calls
        async with semaphore:
            calls += 1
            return await classify_survivor(client, ev)

    dismissed: list[TriagedSurvivor] = []
    pending: list[Evidence] = []
    for result in results:
        if result.verdict != "survived":
            continue
        ev = evidence_for(result, pr_title)
        reason = prefilter(ev)
        if reason is None:
            pending.append(ev)
        else:
            dismissed.append(TriagedSurvivor(
                ev, Classification("equivalent", None, True, f"deterministic pre-filter: {reason}"),
                prefiltered=reason,
            ))

    first = await asyncio.gather(*(classify(ev) for ev in pending))
    if pending and all(c.failure == "unavailable" for c in first):
        # A total model outage (bad key, denied model) must not read as a
        # clean review with "0 headline findings" (spec §9, F3).
        raise ModelUnavailable(
            f"the model was unavailable for all {len(pending)} survivors sent to it"
        )
    triaged = [TriagedSurvivor(ev, c) for ev, c in zip(pending, first)]

    chosen: list[TriagedSurvivor] = []
    for t in sorted((t for t in triaged if _candidate(t.classification)), key=_rank):
        if len(chosen) < headline_limit and _hunk(t) not in {_hunk(c) for c in chosen}:
            chosen.append(t)

    chosen_ids = {id(t) for t in chosen}

    async def confirm(t: TriagedSurvivor) -> TriagedSurvivor:
        more = await asyncio.gather(*(classify(t.evidence) for _ in range(samples - 1)))
        return replace(t, agreement=1 + sum(_candidate(c) for c in more))

    confirmed = await asyncio.gather(*(confirm(t) for t in chosen))
    headline = [t for t in confirmed if t.agreement == samples]
    worth_a_look = [t for t in confirmed if t.agreement != samples]
    for t in triaged:
        if id(t) in chosen_ids:
            continue
        if t.classification.label in ("untested_invariant", "unclassified"):
            worth_a_look.append(t)
        else:
            dismissed.append(t)
    return TriageReport(headline, worth_a_look, dismissed, calls)
