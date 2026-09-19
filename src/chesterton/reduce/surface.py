"""The minimal set of hunks the tests need, and so the undefended rest.

Ruling P3-1: a probe applies only a subset S of the PR's source hunks,
reverting the others to their pre-patch text, and runs the selectable
suite. The property is "the suite passes". ddmin finds a 1-minimal S for
which it holds: the hunks the tests NEED. Every other hunk is undefended,
a change the suite would not notice if it were undone.

"Of 11 hunks, these 2 are the entire undefended surface" (spec §8).

The suite is the whole suite minus flaky and always-failing tests, which
are deselected by node id. The full PR holds by construction, since every
selectable test passed at head three times, so the search starts there.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from chesterton.execute.pool import SandboxPool
from chesterton.reduce.ddmin import Outcome, ddmin
from chesterton.reduce.patch import patch_hunks, probe_files
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.record import SeedRecord

#: A probe runs the whole selectable suite, not a coverage selection.
SUITE_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class SurfaceResult:
    hunks: tuple[str, ...]
    needed: tuple[str, ...]
    undefended: tuple[str, ...]
    probes: int
    exhausted: bool
    skipped: dict[str, int]
    note: str | None = None


def suite_command(seed: SeedRecord) -> str:
    deselect = " ".join(
        f"--deselect {shlex.quote(test)}" for test in sorted(seed.flaky | seed.failing)
    )
    return (
        f"cd {shlex.quote(seed.workdir)} && {seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {deselect}"
    ).rstrip()


def _outcome(result: RunResult) -> Outcome:
    if result.error is not None:
        return Outcome.UNRESOLVED
    if result.exit_code == 0:
        return Outcome.HOLDS
    if result.exit_code == 1:
        return Outcome.FAILS
    return Outcome.UNRESOLVED


async def undefended_surface(pool: SandboxPool, seed: SeedRecord) -> SurfaceResult:
    hunks, skipped = patch_hunks(seed.pr.diff)
    labels = tuple(hunk.label for hunk in hunks)
    if not hunks:
        return SurfaceResult(
            labels, (), (), 0, False, skipped, note="no source hunks to reduce"
        )

    command = suite_command(seed)

    async def probe(keep: frozenset) -> Outcome:
        files = probe_files(seed.sources, seed.workdir, hunks, keep)
        result = await pool.run(
            seed.checkpoint_id, command, files=files, timeout=SUITE_TIMEOUT_S
        )
        return _outcome(result)

    found = await ddmin(hunks, probe)
    return SurfaceResult(
        hunks=labels,
        needed=tuple(h.label for h in hunks if h in found.minimal),
        undefended=tuple(h.label for h in hunks if h not in found.minimal),
        probes=found.probes,
        exhausted=found.exhausted,
        skipped=skipped,
    )
