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
import json
import sys
from pathlib import Path

from chesterton.execute.pool import RUN_OP_BUDGET
from chesterton.run import RunRefused, RunReport, run_seed
from chesterton.seed.build import DEFAULT_PYTHON, SeedBuildError, build_seed
from chesterton.seed.record import SeedRecord


async def _fetch_from_github(url: str):
    import httpx

    from chesterton.github.pr import fetch_pull_request, parse_pr_url

    owner, repo, number = parse_pr_url(url)
    async with httpx.AsyncClient(timeout=30) as http:
        return await fetch_pull_request(owner, repo, number, client=http)


async def _fetch_swebench(instance_id: str):
    import httpx

    from chesterton.github.swebench import fetch_swebench_task

    async with httpx.AsyncClient(timeout=60) as http:
        return await fetch_swebench_task(instance_id, client=http)


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
    source = seed.add_mutually_exclusive_group(required=True)
    source.add_argument("--pr", help="GitHub pull request URL")
    source.add_argument(
        "--swebench",
        metavar="INSTANCE_ID",
        help="a SWE-bench task, e.g. pydata__xarray-7393: its gold patch plus "
        "its original test_patch, its image and its test files by default",
    )
    seed.add_argument(
        "--patch",
        type=Path,
        metavar="FILE",
        help="with --swebench: review this patch (e.g. an agent's) instead of "
        "the gold patch; the task's original tests stay the oracle",
    )
    seed.add_argument(
        "--image",
        help="image ref, e.g. docker://...; required with --pr, defaults to "
        "SWE-bench's own image with --swebench",
    )
    seed.add_argument("--slug", required=True, help="lowercase letters, digits, hyphens")
    seed.add_argument(
        "--python",
        default=DEFAULT_PYTHON,
        help="interpreter the repository's tests run under; in SWE-rebench "
        "images this is /opt/conda/envs/testbed/bin/python, not the `python` "
        "on PATH (find it with scripts/probe_interpreter.py)",
    )
    seed.add_argument(
        "--tests",
        nargs="+",
        default=[],
        metavar="PATH",
        help="scope the baseline and every run to these test files; the "
        "whole suite if omitted",
    )
    seed.add_argument("--out", required=True, type=Path)

    run = commands.add_parser("run", help="run Chesterton against a seed")
    run.add_argument("seed", type=Path, help="a seed record written by `seed`")
    run.add_argument("--out", required=True, type=Path)
    run.add_argument("--no-llm", action="store_true", help="deterministic mutants only")
    run.add_argument("--no-reduce", action="store_true", help="skip ddmin")
    run.add_argument("--op-budget", type=int, default=RUN_OP_BUDGET)

    review = commands.add_parser(
        "review", help="triage a run's survivors and write a verified regression test"
    )
    review.add_argument("seed", type=Path, help="a seed record written by `seed`")
    review.add_argument("run", type=Path, help="a run report written by `run`")
    review.add_argument("--out", required=True, type=Path)
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


async def _seed(args, runner_factory, fetch, fetch_swebench) -> int:
    if args.swebench:
        from chesterton.github.swebench import SWEBenchError, with_patch

        try:
            task = await fetch_swebench(args.swebench)
        except SWEBenchError as exc:
            print(f"could not fetch {args.swebench}: {exc}", file=sys.stderr)
            return 1
        if args.patch:
            try:
                task = with_patch(
                    task, args.patch.read_text(encoding="utf-8"), label=args.patch.stem
                )
            except (OSError, ValueError) as exc:
                print(f"cannot review {args.patch}: {exc}", file=sys.stderr)
                return 1
        pr = task.pr
        image = args.image or task.image
        # SWE-bench's own scope unless overridden: the test_patch's files.
        scope = args.tests or list(task.test_paths)
    else:
        pr, image, scope = await fetch(args.pr), args.image, args.tests

    runner = runner_factory()
    try:
        seed = await build_seed(
            runner, pr, slug=args.slug, image_ref=image,
            python=args.python, test_paths=scope,
        )
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
    print(f"  scope: {', '.join(seed.test_paths) or 'the whole suite'}")
    return 0


async def _run(args, runner_factory, client_factory) -> int:
    if not args.seed.is_file():
        # A failed seed build writes nothing; say so instead of a traceback.
        print(
            f"no seed at {args.seed}; build it first with `chesterton seed`",
            file=sys.stderr,
        )
        return 1
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


def _summarise_review(review) -> str:
    t = review.triage
    lines = [
        f"{review.slug}: {len(t.headline)} headline, {len(t.worth_a_look)} worth a look, "
        f"{len(t.dismissed)} dismissed; {t.model_calls} triage calls, "
        f"{review.ops_used} sandbox ops, {review.wall_s:.1f}s",
    ]
    for f in t.headline:
        ev, c = f.evidence, f.classification
        lines.append(f"  {ev.file}:{ev.start_line}-{ev.end_line} [{c.category}] {c.explanation}")
    test = review.regression
    if test is not None and test.verified:
        lines.append(f"  regression test {test.path}: verified (passes on the PR, fails on the mutant)")
        lines.append(test.source.rstrip())
    elif test is not None:
        why = test.verification.status if test.verification else (test.note or "no test written")
        lines.append(f"  no verified regression test ({why})")
    return "\n".join(lines)


async def _review(args, runner_factory, client_factory) -> int:
    from chesterton.review import review_run
    from chesterton.triage.classify import ModelUnavailable

    for path, what in ((args.seed, "seed"), (args.run, "run report")):
        if not path.is_file():
            print(f"no {what} at {path}", file=sys.stderr)
            return 1
    seed = SeedRecord.from_json(args.seed.read_text(encoding="utf-8"))
    report = json.loads(args.run.read_text(encoding="utf-8"))
    runner = runner_factory()
    try:
        review = await review_run(seed, report, runner, client_factory())
    except ValueError as exc:
        # The seed and the run report do not belong together (F5).
        print(str(exc), file=sys.stderr)
        return 1
    except ModelUnavailable as exc:
        # A total model outage must not look like a clean "0 findings"
        # review (F3): nothing is written, and the exit code says so.
        print(f"{exc} (check NEBIUS_API_KEY and model access)", file=sys.stderr)
        return 2
    finally:
        await runner.aclose()
    _write(args.out, review.to_json())
    print(_summarise_review(review))
    return 0


def main(
    argv=None, *, runner_factory=None, client_factory=None, fetch=None,
    fetch_swebench=None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runner_factory = runner_factory or _default_runner
    if args.command == "seed":
        if args.pr and not args.image:
            parser.error("--image is required with --pr")
        if args.patch and not args.swebench:
            parser.error("--patch needs --swebench: only a SWE-bench task has "
                         "separate original tests to keep as the oracle")
        return asyncio.run(
            _seed(
                args, runner_factory,
                fetch or _fetch_from_github,
                fetch_swebench or _fetch_swebench,
            )
        )
    if args.command == "review":
        return asyncio.run(_review(args, runner_factory, client_factory or _default_client))
    return asyncio.run(_run(args, runner_factory, client_factory or _default_client))


if __name__ == "__main__":
    raise SystemExit(main())
