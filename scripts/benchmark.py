"""Run the pre-registered benchmark (spec §17) over screened agent patches.

Three phases, all resumable: anything already written is skipped, so an
interrupted study continues where it stopped.

  1. PAIR   wrong patches with same-task controls matched on size, and write
            pairs.json. Written once and then reused, so the pairing cannot
            drift between runs.
  2. SEED   build one seed per patch (each is one long sandbox op, six at a
            time).
  3. RUN    run Chesterton once per seed, sequentially, because each run is
            already internally parallel up to the semaphore's 24.

Then the analysis in chesterton/benchmark/analysis.py, which was committed
before any of this ran.

Usage:
    python scripts/benchmark.py <patch-dir> <out-dir> <instance-id> [...]

Needs NEBIUS_API_KEY, NEBIUS_PROJECT_ID and a Token Factory key for the
model proposals.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

from chesterton.benchmark.analysis import (
    analyse,
    match_controls,
    outcome_from_report,
    patch_size,
)
from chesterton.diffing.parse import changed_lines
from chesterton.filters import is_mutable_source
from chesterton.github.swebench import fetch_swebench_task, with_patch
from chesterton.llm.client import NemotronClient
from chesterton.run import run_seed
from chesterton.sandbox.contree import ConTreeSandboxRunner
from chesterton.seed.build import build_seed
from chesterton.seed.record import SeedRecord

PYTHON = "/opt/miniconda3/envs/testbed/bin/python"
BUILD_CONCURRENCY = 6


def slug_for(task: str, patch: str) -> str:
    return f"bm-{task.replace('__', '-').lower()}-{Path(patch).stem}"


def changed_executable_lines(seed: SeedRecord) -> int:
    """The rate's denominator: changed lines that can actually run.

    A scratch script the patch created and nothing ran is left out, as the
    run leaves it out of tier 0 and mutation (benchmark v2).
    """
    exempt = seed.unexercised_new_files()
    total = 0
    for file, lines in changed_lines(seed.pr.diff).items():
        if not is_mutable_source(file) or file in exempt:
            continue
        runnable = seed.executable.get(file)
        total += len(lines) if runnable is None else len(set(lines) & set(runnable))
    return total


def pair_patches(patch_dir: Path, task: str) -> list[dict]:
    screen = json.loads((patch_dir / task / "screen.json").read_text(encoding="utf-8"))

    def sized(verdict: str) -> list[tuple[str, int]]:
        return [
            (p["patch"], patch_size((patch_dir / task / p["patch"]).read_text(encoding="utf-8")))
            for p in screen["patches"]
            if p["verdict"] == verdict
        ]

    wrong, controls = sized("WRONG"), sized("passes_augmented")
    return [
        {"task": task, "wrong": w, "control": c}
        for w, c in match_controls(wrong, controls)
    ]


def _failure_path(out: Path, task: str, patch: str) -> Path:
    return out / "seeds" / task / f"{Path(patch).stem}.error.txt"


def record_seed_failure(out: Path, task: str, patch: str, exc: BaseException) -> Path:
    """Keep the whole reason on disk; the console line is cut at 200 chars.

    v1 lost why every matplotlib-14623 patch touching axes/_base.py failed.
    """
    path = _failure_path(out, task, patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8", newline="\n")
    return path


def clear_seed_failure(out: Path, task: str, patch: str) -> None:
    _failure_path(out, task, patch).unlink(missing_ok=True)


async def seed_for(runner, patch_dir: Path, out: Path, task: str, patch: str) -> Path | None:
    path = out / "seeds" / task / f"{Path(patch).stem}.json"
    if path.exists():
        return path
    async with httpx.AsyncClient(timeout=60) as http:
        base = await fetch_swebench_task(task, client=http)
    reviewed = with_patch(
        base, (patch_dir / task / patch).read_text(encoding="utf-8"), label=Path(patch).stem
    )
    try:
        seed = await build_seed(
            runner, reviewed.pr, slug=slug_for(task, patch), image_ref=reviewed.image,
            python=PYTHON, test_paths=reviewed.test_paths,
            # PYTHON is the testbed interpreter for every SWE-bench image, so a
            # missing pytest is sympy's bin/test setup, not a wrong interpreter.
            install_pytest=True,
        )
    except Exception as exc:  # one seed failing must not end the study
        where = record_seed_failure(out, task, patch, exc)
        print(f"  seed FAILED {task}/{patch}: {type(exc).__name__}: {str(exc)[:200]} "
              f"(full reason in {where})")
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(seed.to_json(), encoding="utf-8", newline="\n")
    clear_seed_failure(out, task, patch)
    print(f"  seeded {task}/{patch}: {len(seed.selectable)} selectable tests")
    return path


async def run_for(runner, client, out: Path, task: str, patch: str) -> dict | None:
    report_path = out / "runs" / task / f"{Path(patch).stem}.json"
    seed_path = out / "seeds" / task / f"{Path(patch).stem}.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    if not seed_path.exists():
        return None
    seed = SeedRecord.from_json(seed_path.read_text(encoding="utf-8"))
    try:
        report = await run_seed(seed, runner, client=client)
    except Exception as exc:
        print(f"  run FAILED {task}/{patch}: {type(exc).__name__}: {str(exc)[:200]}")
        return None
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
    counts = report.counts
    print(f"  ran {task}/{patch}: {counts.killed} killed, {counts.survived} survived, "
          f"{len(report.tier0)} tier-0, {report.wall_s:.0f}s")
    return json.loads(report.to_json())


async def main(patch_dir: Path, out: Path, tasks: list[str]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    pairs_path = out / "pairs.json"
    if pairs_path.exists():
        pairs = json.loads(pairs_path.read_text(encoding="utf-8"))
        print(f"reusing the pairing in {pairs_path}")
    else:
        pairs = [pair for task in tasks for pair in pair_patches(patch_dir, task)]
        pairs_path.write_text(json.dumps(pairs, indent=2), encoding="utf-8")
    matched = [p for p in pairs if p["control"]]
    print(f"{len(pairs)} wrong patches, {len(matched)} matched with a control")

    runner = ConTreeSandboxRunner()
    client = NemotronClient()
    try:
        print("\nseeding")
        semaphore = asyncio.Semaphore(BUILD_CONCURRENCY)

        async def build(task: str, patch: str):
            async with semaphore:
                return await seed_for(runner, patch_dir, out, task, patch)

        await asyncio.gather(*(
            build(p["task"], patch)
            for p in matched for patch in (p["wrong"], p["control"])
        ))

        print("\nrunning")
        outcomes = []
        for pair in matched:
            reports = [
                await run_for(runner, client, out, pair["task"], pair[group])
                for group in ("wrong", "control")
            ]
            if any(r is None for r in reports):
                continue
            seeds = [
                SeedRecord.from_json(
                    (out / "seeds" / pair["task"] / f"{Path(pair[g]).stem}.json")
                    .read_text(encoding="utf-8")
                )
                for g in ("wrong", "control")
            ]
            outcomes.append(tuple(
                outcome_from_report(report, task=pair["task"], patch=pair[group], group=group,
                                    changed_lines=changed_executable_lines(seed))
                for report, seed, group in zip(reports, seeds, ("wrong", "control"))
            ))
    finally:
        await runner.aclose()

    result = analyse(outcomes)
    (out / "summary.json").write_text(
        json.dumps({"pairs_analysed": result.pairs, **result.__dict__}, indent=2), encoding="utf-8"
    )
    print(f"\n=== pre-registered result over {result.pairs} pairs ===")
    print(f"  flagged: wrong {result.wrong_flag_rate:.0%}, control {result.control_flag_rate:.0%}")
    print(f"  H1 exact McNemar: {result.discordant_wrong} wrong-only vs "
          f"{result.discordant_control} control-only discordant pairs, p = {result.mcnemar_p:.4f}")
    print(f"  H2 exact sign test on rates: {result.rate_wins} wins, {result.rate_losses} losses, "
          f"{result.rate_ties} ties, p = {result.sign_p:.4f}")
    print(f"  (alpha 0.05, one-sided, as registered in spec §17)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])))
