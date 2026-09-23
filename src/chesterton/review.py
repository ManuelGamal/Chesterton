"""Review one finished run: triage its survivors, then write one test.

Reads a seed and a run report that already exist, so runs, and the
benchmark built on them, never change. The top headline finding gets a
regression test from the synthesis tier. It is verified in two forks, and
if it fails, it is repaired once with what went wrong. Four sandbox ops at
most. A test that never verified is kept in the report for inspection and
marked unverified; it is never rendered as a finding's answer (spec §9).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from chesterton.execute.pool import SandboxPool
from chesterton.regress.context import covering_test_source
from chesterton.regress.generate import generate_regression_test, regression_test_path
from chesterton.regress.verify import Verification, verify_regression_test
from chesterton.sandbox.protocol import SandboxReadError
from chesterton.seed.record import SeedRecord
from chesterton.triage.evidence import results_from_report
from chesterton.triage.select import TriagedSurvivor, TriageReport, triage

REVIEW_OP_BUDGET = 4
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class RegressionTest:
    path: str
    source: str | None
    verification: Verification | None
    attempts: int
    note: str | None = None

    @property
    def verified(self) -> bool:
        return self.verification is not None and self.verification.status == "verified"


@dataclass(frozen=True)
class ReviewReport:
    slug: str
    triage: TriageReport
    #: For the first headline finding, when there is one.
    regression: RegressionTest | None
    ops_used: int
    wall_s: float

    def to_json(self) -> str:
        payload = _without_modules(asdict(self))
        if self.regression is not None:
            payload["regression"]["verified"] = self.regression.verified
        return json.dumps(payload, indent=2)


def _without_modules(value):
    """Drop each Evidence's whole Mutant: two full modules per survivor."""
    if isinstance(value, dict):
        return {k: _without_modules(v) for k, v in value.items() if k != "mutant"}
    if isinstance(value, list):
        return [_without_modules(v) for v in value]
    return value


async def _regression_for(
    finding: TriagedSurvivor, seed: SeedRecord, runner, pool: SandboxPool, client
) -> RegressionTest:
    ev = finding.evidence
    if not ev.tests:
        return RegressionTest("", None, None, 0, note="no covering test to place a new test beside")
    test_id = ev.tests[0]
    path = regression_test_path(test_id)
    try:
        raw = await runner.read_file(seed.checkpoint_id, f"{seed.workdir}/{test_id.split('::', 1)[0]}")
        context = covering_test_source(raw.decode("utf-8", "replace"), test_id)
    except SandboxReadError:
        context = "(the covering test could not be read)"

    source, verification, feedback = None, None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        source = await generate_regression_test(
            client, ev, finding.classification.explanation, context, path, feedback
        )
        if source is None:
            feedback = "the reply held no parseable test module with a test function"
            continue
        verification = await verify_regression_test(pool, seed, ev.mutant, path, source)
        if verification.status in ("verified", "error"):
            return RegressionTest(path, source, verification, attempt)
        feedback = verification.feedback()
    return RegressionTest(path, source, verification, MAX_ATTEMPTS)


async def review_run(
    seed: SeedRecord, report: dict, runner, client, *, op_budget: int = REVIEW_OP_BUDGET
) -> ReviewReport:
    started = time.perf_counter()
    triaged = await triage(client, results_from_report(report), seed.pr.title)
    pool = SandboxPool(runner, op_budget=op_budget)
    regression = None
    if triaged.headline:
        regression = await _regression_for(triaged.headline[0], seed, runner, pool, client)
    return ReviewReport(
        seed.slug, triaged, regression, pool.ops_used, round(time.perf_counter() - started, 3)
    )
