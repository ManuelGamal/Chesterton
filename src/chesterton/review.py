"""Review one finished run: triage its survivors, then write one test.

Reads a seed and a run report that already exist, so runs, and the
benchmark built on them, never change. `review_run` first checks the two
belong together: a run report carries its own `slug`, and a mismatch against
the seed's is refused rather than reviewed (F5). The first headline finding
that has a covering test gets a regression test from the synthesis tier
(M1: a safety finding with no covering test must not block a functional one
that has one). It is verified in two forks, and if it fails, it is repaired
once with what went wrong. Four sandbox ops at most. A test that never
verified is kept in the report for inspection and marked unverified; it is
never rendered as a finding's answer (spec §9). If the regression stage
itself cannot run (e.g. the sandbox runner cannot even be read from), the
triage that already happened is still returned, with the failure named in
the regression's note (F4).
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

#: The real reason generation produced no source, for repair feedback and
#: the final note (spec §9, F3): truncation is never described as "no
#: parseable test module".
_GENERATION_FEEDBACK = {
    "truncated": "the model ran out of tokens before finishing the test module",
    "unavailable": "the model was unavailable",
    "unparseable": "the reply held no parseable test module with a test function",
}


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

    source, verification, feedback, failure = None, None, None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        generation = await generate_regression_test(
            client, ev, finding.classification.explanation, context, path, feedback
        )
        source, failure = generation.source, generation.failure
        if source is None:
            feedback = _GENERATION_FEEDBACK.get(failure, failure or "no test source")
            continue
        verification = await verify_regression_test(pool, seed, ev.mutant, path, source)
        if verification.status in ("verified", "error"):
            return RegressionTest(path, source, verification, attempt)
        feedback = verification.feedback()
    note = f"no regression test generated: {failure}" if source is None else None
    return RegressionTest(path, source, verification, MAX_ATTEMPTS, note=note)


async def review_run(
    seed: SeedRecord, report: dict, runner, client, *, op_budget: int = REVIEW_OP_BUDGET
) -> ReviewReport:
    report_slug = report.get("slug")
    if report_slug is not None and report_slug != seed.slug:
        raise ValueError(
            f"the run report is for slug {report_slug!r} but the seed is {seed.slug!r}: "
            "they do not belong together"
        )
    started = time.perf_counter()
    triaged = await triage(client, results_from_report(report), seed.pr.title)
    pool = SandboxPool(runner, op_budget=op_budget)
    regression = None
    if triaged.headline:
        # M1: a headline with no covering test cannot get a test placed
        # beside it; try the next headline that has one before giving up.
        finding = next((f for f in triaged.headline if f.evidence.tests), triaged.headline[0])
        try:
            regression = await _regression_for(finding, seed, runner, pool, client)
        except Exception as exc:
            # The triage already ran (spec §9); a sandbox that cannot even
            # be read from (e.g. ConTreeSandboxRunner with no
            # NEBIUS_PROJECT_ID) must not throw the whole review away (F4).
            regression = RegressionTest(
                "", None, None, 0,
                note=f"regression stage failed: {type(exc).__name__}: {exc}",
            )
    return ReviewReport(
        seed.slug, triaged, regression, pool.ops_used, round(time.perf_counter() - started, 3)
    )
