"""The pre-registered benchmark analysis (spec §17, registered 2026-09-20).

This module was written and committed BEFORE any benchmark run, so the
metric cannot be fitted to the data. The protocol it implements is in spec
§17, "Pre-registered protocol"; changing it after a run starts is a new
study and must say so.

The question: across agent patches that passed SWE-bench's tests, does
Chesterton flag the ones UTBoost proved wrong more often than matched ones
UTBoost's tests accept?

- A patch is FLAGGED when its run has at least one surviving mutant or
  tier-0 finding. Provable no-ops are already rejected by the gate, before
  they run.
- Its RATE is (survivors + tier-0 findings) per changed executable line. Agent
  patches add code, so raw counts partly measure volume; the rate does not.
- Each wrong patch is paired with a control from the SAME task, matched on
  size (changed source lines), nearest first, without replacement, with ties
  broken by name.
- H1, the primary hypothesis: wrong patches are flagged more often. One-sided
  exact McNemar test on the discordant pairs, alpha 0.05.
- H2, secondary: the wrong patch's rate is higher within a pair. One-sided
  exact sign test, ties dropped, alpha 0.05.

Both are reported whatever they show.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import comb
from typing import Literal

from unidiff import PatchSet

from chesterton.filters import is_mutable_source
from chesterton.paths import normalise_path

Group = Literal["wrong", "control"]


@dataclass(frozen=True)
class PatchOutcome:
    task: str
    patch: str
    group: Group
    #: Changed EXECUTABLE lines in source files; the rate's denominator.
    changed_lines: int
    mutants_run: int
    survivors: int
    tier0: int

    @property
    def flagged(self) -> bool:
        return self.survivors > 0 or self.tier0 > 0

    @property
    def rate(self) -> float:
        if self.changed_lines <= 0:
            return 0.0
        return (self.survivors + self.tier0) / self.changed_lines


def outcome_from_report(
    report: dict, *, task: str, patch: str, group: Group, changed_lines: int
) -> PatchOutcome:
    counts = report["counts"]
    return PatchOutcome(
        task=task,
        patch=patch,
        group=group,
        changed_lines=changed_lines,
        mutants_run=counts["killed"] + counts["survived"],
        survivors=counts["survived"],
        tier0=len(report["tier0"]),
    )


def binomial_tail(k: int, n: int) -> float:
    """P(X >= k) for X ~ Binomial(n, 1/2): the exact one-sided p-value."""
    return sum(comb(n, i) for i in range(k, n + 1)) / 2**n


@dataclass(frozen=True)
class Result:
    pairs: int
    wrong_flag_rate: float
    control_flag_rate: float
    #: Pairs where only the wrong patch was flagged, and only the control.
    discordant_wrong: int
    discordant_control: int
    mcnemar_p: float
    rate_wins: int
    rate_losses: int
    rate_ties: int
    sign_p: float


def analyse(pairs: Sequence[tuple[PatchOutcome, PatchOutcome]]) -> Result:
    for wrong, control in pairs:
        if (wrong.group, control.group) != ("wrong", "control"):
            raise ValueError("each pair must be (wrong, control)")
        if wrong.task != control.task:
            raise ValueError("a pair must come from the same task")

    n = len(pairs)
    only_wrong = sum(w.flagged and not c.flagged for w, c in pairs)
    only_control = sum(c.flagged and not w.flagged for w, c in pairs)
    wins = sum(w.rate > c.rate for w, c in pairs)
    losses = sum(w.rate < c.rate for w, c in pairs)

    discordant = only_wrong + only_control
    decided = wins + losses
    return Result(
        pairs=n,
        wrong_flag_rate=sum(w.flagged for w, _ in pairs) / n if n else 0.0,
        control_flag_rate=sum(c.flagged for _, c in pairs) / n if n else 0.0,
        discordant_wrong=only_wrong,
        discordant_control=only_control,
        mcnemar_p=binomial_tail(only_wrong, discordant) if discordant else 1.0,
        rate_wins=wins,
        rate_losses=losses,
        rate_ties=n - decided,
        sign_p=binomial_tail(wins, decided) if decided else 1.0,
    )


def patch_size(diff: str) -> int:
    """Changed (added plus removed) lines in mutable source files."""
    size = 0
    for patched in PatchSet(diff):
        if not is_mutable_source(normalise_path(patched.path)):
            continue
        size += sum(1 for hunk in patched for line in hunk if line.is_added or line.is_removed)
    return size


def match_controls(
    wrong: Sequence[tuple[str, int]], controls: Sequence[tuple[str, int]]
) -> list[tuple[str, str | None]]:
    """Pair each wrong patch with the nearest-sized unused control.

    Deterministic: wrong patches are taken in name order, and ties in
    distance are broken by the control's name. None when no control is left.
    """
    available = sorted(controls)
    pairs: list[tuple[str, str | None]] = []
    for name, size in sorted(wrong):
        if not available:
            pairs.append((name, None))
            continue
        best = min(available, key=lambda c: (abs(c[1] - size), c[0]))
        available.remove(best)
        pairs.append((name, best[0]))
    return pairs
