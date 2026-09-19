"""python -m chesterton seed | run

  seed  Build time. Fetch a PR, build its tagged baseline checkpoint and
        write the seed record. Slow (image pulls measured 88-225 s), and
        never on a judge's clock.
  run   Run time. Load a seed record and run tier 0, mutation and ddmin
        against it under one op budget, then write the report.

The factories exist so tests can inject fakes. The real runner and client
read NEBIUS_API_KEY and NEBIUS_PROJECT_ID from the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from chesterton.execute.pool import RUN_OP_BUDGET
from chesterton.run import RunRefused, RunReport, run_seed
from chesterton.seed.build import SeedBuildError, build_seed
from chesterton.seed.record import SeedRecord


async def _fetch_from_github(url: str):
    import httpx

    from chesterton.github.pr import fetch_pull_request, parse_pr_url

    owner, repo, number = parse_pr_url(url)
    async with httpx.AsyncClient(timeout=30) as http:
        return await fetch_pull_request(owner, repo, number, client=http)


def _default_runner():
    from chesterton.sandbox.contree import ConTreeSandboxRunner

    return ConTreeSandboxRunner()


def _default_client():
    from chesterton.llm.client import NemotronClient

    return NemotronClient()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chesterton")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="build a seed checkpoint for a PR")
    seed.add_argument("--pr", required=True, help="GitHub pull request URL")
    seed.add_argument("--image", required=True, help="image ref, e.g. docker://...")
    seed.add_argument("--slug", required=True, help="lowercase letters, digits, hyphens")
    seed.add_argument("--out", required=True, type=Path)

    run = commands.add_parser("run", help="run Chesterton against a seed")
    run.add_argument("seed", type=Path, help="a seed record written by `seed`")
    run.add_argument("--out", required=True, type=Path)
    run.add_argument("--no-llm", action="store_true", help="deterministic mutants only")
    run.add_argument("--no-reduce", action="store_true", help="skip ddmin")
    run.add_argument("--op-budget", type=int, default=RUN_OP_BUDGET)
    return parser


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _summarise(report: RunReport) -> str:
    c = report.counts
    score = "n/a" if c.score is None else f"{c.score:.0%}"
    lines = [
        f"{report.slug}: {report.hunks} hunks, {report.generated} mutants, "
        f"{report.ops_used}/{report.op_budget} sandbox ops, {report.wall_s:.1f}s",
        f"  tier 0: {len(report.tier0)} changed lines no selectable test executes",
        f"  mutants: {c.killed} killed, {c.survived} survived "
        f"(no selected test failed), {c.uncovered} uncovered, {c.error} error; "
        f"score {score} (errors and uncovered excluded)",
    ]
    if report.model is not None:
        failures = ", ".join(f"{k} {v}" for k, v in sorted(report.model.failures.items()))
        lines.append(
            f"  model: {report.model.calls} calls, {report.model.retried} retried, "
            f"failures: {failures or 'none'}"
        )
    surface = report.surface
    if surface is None:
        lines.append("  undefended surface: not computed")
    elif surface.note:
        lines.append(f"  undefended surface: {surface.note}")
    else:
        bound = " (budget ran out: at least these)" if surface.exhausted else ""
        lines.append(
            f"  undefended surface: of {len(surface.hunks)} hunks, "
            f"{len(surface.undefended)} are undefended{bound}: "
            f"{', '.join(surface.undefended) or 'none'} ({surface.probes} probes)"
        )
    return "\n".join(lines)


async def _seed(args, runner_factory, fetch) -> int:
    pr = await fetch(args.pr)
    runner = runner_factory()
    try:
        seed = await build_seed(runner, pr, slug=args.slug, image_ref=args.image)
    except SeedBuildError as exc:
        print(f"seed build failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await runner.aclose()
    _write(args.out, seed.to_json())
    print(
        f"seed {seed.slug}: checkpoint {seed.checkpoint_id} tagged "
        f"{seed.checkpoint_tag}; {len(seed.selectable)} selectable, "
        f"{len(seed.flaky)} flaky, {len(seed.failing)} failing tests -> {args.out}"
    )
    return 0


async def _run(args, runner_factory, client_factory) -> int:
    seed = SeedRecord.from_json(args.seed.read_text(encoding="utf-8"))
    runner = runner_factory()
    client = None if args.no_llm else client_factory()
    try:
        report = await run_seed(
            seed, runner, client=client,
            op_budget=args.op_budget, reduce=not args.no_reduce,
        )
    except RunRefused as exc:
        print(f"run refused: {exc}", file=sys.stderr)
        return 2
    finally:
        await runner.aclose()
    _write(args.out, report.to_json())
    print(_summarise(report))
    return 0


def main(argv=None, *, runner_factory=None, client_factory=None, fetch=None) -> int:
    args = build_parser().parse_args(argv)
    runner_factory = runner_factory or _default_runner
    if args.command == "seed":
        return asyncio.run(_seed(args, runner_factory, fetch or _fetch_from_github))
    return asyncio.run(_run(args, runner_factory, client_factory or _default_client))


if __name__ == "__main__":
    raise SystemExit(main())
