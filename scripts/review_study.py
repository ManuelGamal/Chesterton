"""EXPLORATORY: does review write verified tests on real wrong agent patches?

Not a benchmark and no pre-registered claim. For each UTBoost-wrong
matplotlib-23314 patch in benchmark-v2, it reviews the run, then runs any
verified regression test against the GOLD fix too:

- passes_on_gold: the test defends behaviour the correct fix shares;
- fails_on_gold: the test encoded the agent's behaviour as correct, the
  hazard spec §9 cites (Trail of Bits). Reported, never hidden.

Usage:
    python scripts/review_study.py <benchmark-dir> <gold-seed.json> <out-dir>

Needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID. About 20 Super calls, up to 2
Ultra calls and up to 5 sandbox ops per patch.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
from pathlib import Path

from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.llm.client import NemotronClient
from chesterton.review import review_run
from chesterton.sandbox.contree import ConTreeSandboxRunner
from chesterton.seed.record import SeedRecord

TASK = "matplotlib__matplotlib-23314"


async def gold_check(pool: SandboxPool, gold_seed: SeedRecord, test_path: str, test_src: str) -> str:
    command = (
        f"cd {shlex.quote(gold_seed.workdir)} && {gold_seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {shlex.quote(test_path)}"
    )
    try:
        result = await pool.run(
            gold_seed.checkpoint_id, command,
            files={f"{gold_seed.workdir}/{test_path}": test_src}, timeout=300.0,
        )
    except BudgetExhausted:
        return "error"
    if result.error is not None:
        return "error"
    return {0: "passes_on_gold", 1: "fails_on_gold"}.get(result.exit_code, "error")


def summarise(rows: list[dict]) -> str:
    verified = [r for r in rows if r["verified"]]
    n_errors = sum(1 for r in rows if r.get("error"))
    return "\n".join([
        f"{len(rows)} patches, {sum(r['headline'] > 0 for r in rows)} with a headline finding, "
        f"{len(verified)} verified tests",
        f"  {sum(r['gold'] == 'passes_on_gold' for r in verified)} consistent with the gold fix, "
        f"{sum(r['gold'] == 'fails_on_gold' for r in verified)} encode the agent's behaviour, "
        f"{sum(r['gold'] == 'error' for r in verified)} could not be checked",
        f"  {n_errors} patches could not be studied",
    ])


async def study(bench: Path, gold: SeedRecord, runner, client, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    pairs = json.loads((bench / "pairs.json").read_text(encoding="utf-8"))
    wrong = sorted({p["wrong"] for p in pairs if p["task"] == TASK})
    rows = []
    for patch in wrong:
        try:
            stem = Path(patch).stem
            seed = SeedRecord.from_json((bench / "seeds" / TASK / f"{stem}.json").read_text(encoding="utf-8"))
            report = json.loads((bench / "runs" / TASK / f"{stem}.json").read_text(encoding="utf-8"))
            review = await review_run(seed, report, runner, client)
            (out / f"{stem}.json").write_text(review.to_json(), encoding="utf-8", newline="\n")
            test = review.regression
            verdict = None
            if test is not None and test.verified:
                verdict = await gold_check(SandboxPool(runner, op_budget=1), gold, test.path, test.source)
            row = {"patch": stem, "headline": len(review.triage.headline),
                   "verified": bool(test and test.verified), "gold": verdict, "error": None}
            rows.append(row)
            print(f"  {stem}: {row}")
        except Exception as exc:
            row = {"patch": stem, "headline": 0, "verified": False, "gold": None,
                   "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            print(f"  {stem}: {row}")
    return rows


async def main(bench: Path, gold_path: Path, out: Path) -> int:
    gold = SeedRecord.from_json(gold_path.read_text(encoding="utf-8"))
    runner, client = ConTreeSandboxRunner(), NemotronClient()
    out.mkdir(parents=True, exist_ok=True)
    try:
        rows = await study(bench, gold, runner, client, out)
    finally:
        await runner.aclose()
    (out / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8", newline="\n")
    print("\nEXPLORATORY, not a benchmark:\n" + summarise(rows))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))))
