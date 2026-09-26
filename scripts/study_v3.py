"""Study v3: verified tests at scale (spec §17, REGISTERED 2026-09-26, commit 8f95e0e).

Usage, from the repo root (needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID):
    python scripts/study_v3.py gold-seeds             # one reference-fix seed per task, once
    python scripts/study_v3.py run pilot              # stage 0: the registered 10 patches
    python scripts/study_v3.py run main [--sample F]  # the 292 main patches, or the budget sample
    python scripts/study_v3.py report pilot|main      # the registered estimands -> report.json

Resumable. A patch whose row has no error is never reviewed again (spec §17,
Retries); a row with an infrastructure error is retried on the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from chesterton.benchmark import verified as v
from chesterton.execute.pool import SandboxPool
from chesterton.review import review_run
from chesterton.seed.build import build_seed
from chesterton.seed.record import SeedRecord

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark-v2"


def _load(name: str):
    """Reuse another script's helpers, loaded by path like the tests load scripts."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bench = _load("benchmark")
_review_study = _load("review_study")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


async def build_gold_seeds(runner, tasks, out: Path, *, fetch_bases=None, build=build_seed) -> dict[str, str]:
    """One reference-fix seed per task, built as benchmark.seed_for builds v2's seeds."""
    fetch = fetch_bases or _bench.fetch_bases
    bases, unknown = await fetch(sorted(set(tasks)))
    status = {task: "unknown task" for task in unknown}
    for task in sorted(bases):
        path = out / f"{task}.json"
        if path.exists():
            status[task] = "exists"
            continue
        base = bases[task]
        try:
            seed = await build(
                runner, base.pr, slug=_bench.slug_for(task, "gold.diff"), image_ref=base.image,
                python=_bench.PYTHON, test_paths=base.test_paths, install_pytest=True,
            )
        except Exception as exc:  # one task failing must not end the build
            status[task] = f"failed: {type(exc).__name__}: {exc}"[:300]
            _write(out / f"{task}.error.txt", status[task] + "\n")
            continue
        _write(path, seed.to_json())
        status[task] = "built"
    return status


def stage_patches(bench: Path, stage: str, *, fraction: float | None = None) -> list[tuple[str, str, str]]:
    """The registered patches for a stage; main's budget sample is fixed once, on first use."""
    pairs = json.loads((bench / "pairs.json").read_text(encoding="utf-8"))
    pop = v.population(pairs, bench / "runs")
    pilot = v.pilot(pop)
    if stage == "pilot":
        return v.patches(pilot)
    main = v.main_pairs(pop, pilot)
    lock = bench / "study-v3" / "main" / "sample.json"
    if lock.exists():
        saved = json.loads(lock.read_text(encoding="utf-8"))
        if fraction is not None and fraction != saved["fraction"]:
            raise SystemExit(f"the main sample is already fixed at fraction {saved['fraction']} ({lock})")
        chosen = {(p["task"], p["wrong"]) for p in saved["pairs"]}
        return v.patches([p for p in main if (p.task, p.wrong) in chosen])
    if fraction is None:
        return v.patches(main)
    picked = v.sample(main, fraction)
    _write(lock, json.dumps({"fraction": fraction, "seed": v.SEED,
                             "pairs": [{"task": p.task, "wrong": p.wrong, "control": p.control} for p in picked]},
                            indent=1) + "\n")
    return v.patches(picked)


def _fields_from_review(review: dict) -> tuple[dict, str | None, str | None]:
    """The row's fields but for `gold`, straight from a parsed review.json.

    `review_run` already ran (spec §17, a completed review is never rerun);
    `ReviewReport.to_json()` already computed `regression.verified`, so it is
    read here, never recomputed. Returns the fields plus the verified test's
    path and source, for the caller to gold-check.
    """
    triage = review["triage"]
    regression = review.get("regression")
    verified, status, attempts, path, source = False, None, 0, None, None
    if regression is not None:
        verified = regression["verified"]
        verification = regression.get("verification")
        status = verification["status"] if verification else regression.get("note")
        attempts = regression["attempts"]
        path, source = regression["path"], regression["source"]
    fields = {
        "headline": len(triage["headline"]), "verified": verified, "status": status,
        "super_calls": triage["model_calls"], "ultra_calls": attempts,
        "ops": review["ops_used"], "wall_s": round(review["wall_s"], 3),
    }
    return fields, path, source


async def _row_from_review(review: dict, runner, gold: SeedRecord | None) -> dict:
    """The row's fields, including the gold check, from a parsed review.json."""
    fields, path, source = _fields_from_review(review)
    outcome = None
    if fields["verified"]:
        if gold is None:
            outcome = "error"
        else:
            outcome = await _review_study.gold_check(SandboxPool(runner, op_budget=1), gold, path, source)
            fields["ops"] += 1
    fields["gold"] = outcome
    return fields


async def review_patch(bench: Path, task: str, stem: str, runner, client, gold: SeedRecord | None, out: Path) -> dict:
    seed = SeedRecord.from_json((bench / "seeds" / task / f"{stem}.json").read_text(encoding="utf-8"))
    report = json.loads((bench / "runs" / task / f"{stem}.json").read_text(encoding="utf-8"))
    review = await review_run(seed, report, runner, client)
    text = review.to_json()
    _write(out / f"{stem}.review.json", text)
    return await _row_from_review(json.loads(text), runner, gold)


EMPTY = {"headline": 0, "verified": False, "status": None, "gold": None,
         "super_calls": 0, "ultra_calls": 0, "ops": 0, "wall_s": 0.0}


async def run_stage(bench: Path, out: Path, gold_dir: Path, todo, runner, client) -> list[dict]:
    golds: dict[str, SeedRecord | None] = {}
    rows = []
    for task, stem, arm in todo:
        task_dir = out / task
        row_path = task_dir / f"{stem}.row.json"
        review_path = task_dir / f"{stem}.review.json"
        prior = json.loads(row_path.read_text(encoding="utf-8")) if row_path.exists() else None
        if prior is not None and prior["error"] is None:
            rows.append(prior)
            continue
        if task not in golds:
            path = gold_dir / f"{task}.json"
            golds[task] = SeedRecord.from_json(path.read_text(encoding="utf-8")) if path.exists() else None
        row = {"task": task, "patch": stem, "arm": arm, "retries": prior["retries"] + 1 if prior else 0}
        try:
            if review_path.exists():
                # A review that completed is never rerun (spec §17): a crash
                # between writing review.json and row.json must resume from
                # the review already on disk, not pay for another one.
                review = json.loads(review_path.read_text(encoding="utf-8"))
                row |= await _row_from_review(review, runner, golds[task])
            else:
                row |= await review_patch(bench, task, stem, runner, client, golds[task], task_dir)
            row["error"] = None
        except Exception as exc:  # recorded and retried later, never fatal to the stage
            row |= EMPTY | {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        _write(row_path, json.dumps(row, indent=1) + "\n")
        rows.append(row)
        print(f"  {task}/{stem} ({arm}): verified={row['verified']} gold={row['gold']} error={row['error']}")
    return rows


def write_report(out: Path) -> dict:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*/*.row.json"))]
    report = v.report(rows)
    _write(out / "report.json", json.dumps(report, indent=1) + "\n")
    return report


def _line(name: str, e: dict) -> str:
    if e["rate"] is None:
        return f"{name}: no data"
    lo, hi = e["wilson"]
    ci = e["cluster_interval"]
    clustered = f", task-clustered [{ci[0]:.0%}, {ci[1]:.0%}]" if ci else ""
    return (f"{name}: {e['k']}/{e['n']} = {e['rate']:.0%} (Wilson 95% [{lo:.0%}, {hi:.0%}]{clustered}; "
            f"mean of {e['tasks']} task rates {e['per_task_mean']:.0%})")


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gold-seeds")
    run = sub.add_parser("run")
    run.add_argument("stage", choices=["pilot", "main"])
    run.add_argument("--sample", type=float, default=None, help="budget rule: fraction of main pairs")
    rep = sub.add_parser("report")
    rep.add_argument("stage", choices=["pilot", "main"])
    args = parser.parse_args(argv)

    if args.cmd == "report":
        r = write_report(BENCH / "study-v3" / args.stage)
        print(f"{r['patches']} patches\n" + _line("yield", r["yield"]) + "\n" + _line("agreement", r["agreement"]))
        return 0

    from chesterton.llm.client import NemotronClient
    from chesterton.sandbox.contree import ConTreeSandboxRunner

    runner = ConTreeSandboxRunner()
    try:
        if args.cmd == "gold-seeds":
            pairs = json.loads((BENCH / "pairs.json").read_text(encoding="utf-8"))
            tasks = sorted({p.task for p in v.population(pairs, BENCH / "runs")})
            for task, state in (await build_gold_seeds(runner, tasks, BENCH / "gold-seeds")).items():
                print(f"  {task}: {state}")
            return 0
        if args.sample is not None and args.stage != "main":
            parser.error("--sample applies to the main stage only")
        todo = stage_patches(BENCH, args.stage, fraction=args.sample)
        print(f"{args.stage}: {len(todo)} patches")
        await run_stage(BENCH, BENCH / "study-v3" / args.stage, BENCH / "gold-seeds", todo, runner, NemotronClient())
        return 0
    finally:
        await runner.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
