"""Study v3: verified tests at scale (spec §17, REGISTERED 2026-09-26, commit 8f95e0e).

Needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID for gold-seeds and run. The runbook,
in this order (spec §17, Amendments 1 and 2), from the repo root:

    1. python scripts/study_v3.py gold-seeds
         One reference-fix seed per task. Check each printed selectable/failing
         count against the median of that task's v2 seeds: a gap is image drift.
    2. python scripts/study_v3.py run pilot
         The registered 10 patches. Then `report pilot` prints its cost first.
    3. Read the billing (Nebius Token Factory plus sandboxes), c = spend / 10, then
       python scripts/study_v3.py budget --usd B --cost-per-patch C
         Prints f = min(1, B / (292 x c)), rounded down to 0.05, and each task's k.
    4. If f < 1, record B, c and f in spec §17 as Amendment 4, before any main run.
    5. python scripts/study_v3.py run main [--sample f]
         `--sample f --dry-run` prints each task's k and writes nothing.
    6. python scripts/study_v3.py report main

Always run with:
    PYTHONIOENCODING=utf-8 python scripts/study_v3.py ... 2>&1 | tee logs/study-v3-<stage>.log

`run` refuses to start until every task has a reference-fix seed, or a
recorded build failure accepted with --accept-missing-gold. It is resumable. A
row with no error is never reviewed again. An infrastructure failure (a raised
API, sandbox, model-unavailable or timeout error, or a completed review that
Amendment 2 flags) is retried on the next run; a flagged review's file is kept
as <stem>.review.<n>.json, and after 3 retries the last review stands. Any
other exception is recorded as `other:` and retried only with --retry-other.
A stage stops after 5 consecutive errors, and the command then exits non-zero.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import median

import openai

from chesterton.benchmark import verified as v
from chesterton.execute.pool import BudgetExhausted, SandboxPool
from chesterton.review import review_run
from chesterton.sandbox.protocol import SandboxReadError
from chesterton.seed.build import build_seed
from chesterton.seed.record import SeedRecord
from chesterton.triage.classify import ModelUnavailable

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark-v2"

#: Spec §17: the registration commit, and the review pipeline it fixed.
REGISTRATION = "8f95e0e"
PIPELINE = ("src/chesterton/review.py", "src/chesterton/triage", "src/chesterton/regress")

#: Amendment 2, item 1: after this many retries a flagged review stands.
MAX_INFRA_RETRIES = 3
#: Amendment 2, item 1: a stage stops after this many consecutive errors.
MAX_CONSECUTIVE_ERRORS = 5
#: Amendment 2, item 2: a gold error keeps this much of its output.
GOLD_TAIL = 2000


def _load(name: str):
    """Reuse another script's helpers, loaded by path like the tests load scripts."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bench = _load("benchmark")


class GoldSandboxError(RuntimeError):
    """The gold check's sandbox operation failed. Retried; never an outcome (Amendment 2, item 2)."""


def _sandbox_errors() -> tuple[type[BaseException], ...]:
    # A sandbox operation failure comes back as RunResult.error, never raised
    # (sandbox/protocol.py); the gold check raises GoldSandboxError for it. The
    # SDK's own ContreeError is caught inside ConTreeSandboxRunner.run, but is
    # listed in case one escapes (e.g. from `images.use`).
    errors: tuple[type[BaseException], ...] = (SandboxReadError, GoldSandboxError)
    try:
        from contree_sdk.sdk.exceptions import ContreeError
    except ImportError:
        return errors
    return errors + (ContreeError,)


#: Amendment 2, item 1: the known infrastructure types, retried automatically.
INFRASTRUCTURE = (openai.OpenAIError, ModelUnavailable, *_sandbox_errors(),
                  TimeoutError, asyncio.TimeoutError, BudgetExhausted)


def _say(text: str) -> None:
    """Print a line, never crashing on the console's encoding."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"), flush=True)


def _write(path: Path, text: str) -> None:
    """Atomic: a crash mid-write leaves the old file, never half of the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read_json(path: Path):
    """A parsed JSON file, or None when it is missing or corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):  # JSONDecodeError is a ValueError
        return None


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
        (out / f"{task}.error.txt").unlink(missing_ok=True)  # a stale failure no longer holds
        status[task] = "built"
    return status


def seed_counts(gold_dir: Path, seeds_dir: Path, task: str) -> str:
    """A reference-fix seed's test counts beside its task's v2 seeds', so image drift shows."""
    gold = json.loads((gold_dir / f"{task}.json").read_text(encoding="utf-8"))
    v2 = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((seeds_dir / task).glob("*.json"))]
    line = f"selectable {len(gold['selectable'])}, failing {len(gold['failing'])}"
    if not v2:
        return line + " (no v2 seeds to compare)"
    sel = median(len(s["selectable"]) for s in v2)
    fail = median(len(s["failing"]) for s in v2)
    return line + f" (v2 median over {len(v2)} seeds: selectable {sel:g}, failing {fail:g})"


def _main_pairs(bench: Path) -> list[v.Pair]:
    pairs = json.loads((bench / "pairs.json").read_text(encoding="utf-8"))
    pop = v.population(pairs, bench / "runs")
    return v.main_pairs(pop, v.pilot(pop))


def stage_patches(bench: Path, stage: str, *, fraction: float | None = None) -> list[tuple[str, str, str]]:
    """The registered patches for a stage; main's budget sample is fixed once, on first use."""
    pairs = json.loads((bench / "pairs.json").read_text(encoding="utf-8"))
    pop = v.population(pairs, bench / "runs")
    pilot = v.pilot(pop)
    if stage == "pilot":
        return v.patches(pilot)
    main = v.main_pairs(pop, pilot)
    out = bench / "study-v3" / "main"
    lock = out / "sample.json"
    if lock.exists():
        saved = json.loads(lock.read_text(encoding="utf-8"))
        if fraction is not None and fraction != saved["fraction"]:
            raise SystemExit(f"the main sample is already fixed at fraction {saved['fraction']} ({lock})")
        chosen = {(p["task"], p["wrong"]) for p in saved["pairs"]}
        return v.patches([p for p in main if (p.task, p.wrong) in chosen])
    if fraction is None:
        return v.patches(main)
    started = sorted(p for pattern in ("*/*.row.json", "*/*.review*.json") for p in out.glob(pattern))
    if started:
        # Amendment 2, item 4: a sample drawn after seeing any main review
        # could be chosen to suit it.
        raise SystemExit(f"no sample is drawn once any main review exists (Amendment 2, item 4): "
                         f"{len(started)} main row/review files, e.g. {started[0]}")
    picked = v.sample(main, fraction)
    _write(lock, json.dumps({"fraction": fraction, "seed": v.SEED,
                             "pairs": [{"task": p.task, "wrong": p.wrong, "control": p.control} for p in picked]},
                            indent=1) + "\n")
    return v.patches(picked)


def infra_failure(review: dict) -> str | None:
    """Why a completed review is an infrastructure failure (Amendment 2, item 1), or None.

    Reads review.json as ReviewReport.to_json() writes it: every recorded
    classification is at triage.{headline,worth_a_look,dismissed}[].
    classification.failure (triage/classify.py); regression.note carries a
    stage exception or the last generation failure (review.py); and
    regression.verification.status is verify.py's Status.
    """
    triage = review.get("triage") or {}
    for group in ("headline", "worth_a_look", "dismissed"):
        for item in triage.get(group) or []:
            if (item.get("classification") or {}).get("failure") == "unavailable":
                return f"triage classification unavailable ({group})"
    regression = review.get("regression")
    if regression is None:
        return None
    note = regression.get("note") or ""
    if note.startswith("regression stage failed") or ": unavailable" in note:
        return note[:300]
    verification = regression.get("verification")
    if verification and verification.get("status") == "error":
        return f"verification status is error: {verification.get('detail', '')}"[:300]
    return None


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
        "review_wall_s": round(review["wall_s"], 3),
    }
    return fields, path, source


async def gold_check(pool: SandboxPool, gold_seed: SeedRecord, test_path: str, test_src: str
                     ) -> tuple[str, int | None, str]:
    """review_study.gold_check's command, with its exit code and output tail.

    A failed sandbox operation raises GoldSandboxError, and BudgetExhausted
    propagates: both are infrastructure, retried, never an outcome
    (Amendment 2, item 2). Exit 0 is passes_on_gold, 1 fails_on_gold, and any
    other exit of a completed run is error.
    """
    command = (
        f"cd {shlex.quote(gold_seed.workdir)} && {gold_seed.test_command} "
        f"-q -p no:randomly -p no:cacheprovider {shlex.quote(test_path)}"
    )
    result = await pool.run(
        gold_seed.checkpoint_id, command,
        files={f"{gold_seed.workdir}/{test_path}": test_src}, timeout=300.0,
    )
    if result.error is not None:
        raise GoldSandboxError(result.error)
    tail = "\n".join(s for s in (result.stdout, result.stderr) if s)[-GOLD_TAIL:]
    outcome = {0: "passes_on_gold", 1: "fails_on_gold"}.get(result.exit_code, "error")
    return outcome, result.exit_code, tail


async def _row_from_review(review: dict, runner, gold: SeedRecord | None, no_gold: str, *,
                           gold_capped: str | None = None) -> tuple[dict, str | None]:
    """The row's fields, including the gold check, from a parsed review.json.

    Returns the fields and, when the gold check's sandbox operation failed,
    that failure. The review's fields are kept either way: a failed gold
    operation never erases a verified test (Amendment 3, item 2). With
    `gold_capped` (the last op error, once the gold check has failed on its
    first attempt and 3 retries), no gold check runs and the outcome is error.
    """
    fields, path, source = _fields_from_review(review)
    outcome, code, tail, gold_s, failure = None, None, None, 0.0, None
    if fields["verified"]:
        if gold_capped is not None:
            outcome, tail = "error", gold_capped[-GOLD_TAIL:]
            fields["gold_capped"] = True
        elif gold is None:
            outcome, tail = "error", no_gold[-GOLD_TAIL:]
        else:
            started = time.perf_counter()
            try:
                outcome, code, tail = await gold_check(SandboxPool(runner, op_budget=1), gold, path, source)
            except GoldSandboxError as exc:
                failure = str(exc)[:300]
            gold_s = round(time.perf_counter() - started, 3)
            fields["ops"] += 1  # the op was issued, whether or not it succeeded
    # Amendment 2: the patch's wall time includes its gold check.
    fields |= {"gold": outcome, "gold_exit": code, "gold_tail": tail, "gold_s": gold_s,
               "wall_s": round(fields["review_wall_s"] + gold_s, 3)}
    return fields, failure


async def review_patch(bench: Path, task: str, stem: str, runner, client, out: Path) -> dict:
    """Run one review, write its review.json, and return it parsed."""
    seed = SeedRecord.from_json((bench / "seeds" / task / f"{stem}.json").read_text(encoding="utf-8"))
    report = json.loads((bench / "runs" / task / f"{stem}.json").read_text(encoding="utf-8"))
    review = await review_run(seed, report, runner, client)
    text = review.to_json()
    _write(out / f"{stem}.review.json", text)
    return json.loads(text)


def _archived(task_dir: Path, stem: str) -> int:
    """Reviews set aside for this patch: flagged ones (<stem>.review.<n>.json) and corrupt ones."""
    prefix = f"{stem}.review."
    count = 0
    for p in task_dir.glob(f"{stem}.review.*.json"):
        middle = p.name[len(prefix):-len(".json")]
        count += middle.isdigit() or middle == "corrupt" or middle.startswith("corrupt.")
    return count


def _set_aside(review_path: Path, task_dir: Path, stem: str, label: str | None = None) -> Path:
    """Move review.json to the next free <stem>.review.<n>.json (or .review.corrupt.json)."""
    if label is not None and not (task_dir / f"{stem}.review.{label}.json").exists():
        target = task_dir / f"{stem}.review.{label}.json"
    else:
        prefix = f"{label}." if label else ""
        n = 1
        while (task_dir / f"{stem}.review.{prefix}{n}.json").exists():
            n += 1
        target = task_dir / f"{stem}.review.{prefix}{n}.json"
    os.replace(review_path, target)
    return target


EMPTY = {"headline": 0, "verified": False, "status": None, "gold": None, "gold_exit": None, "gold_tail": None,
         "super_calls": 0, "ultra_calls": 0, "ops": 0, "wall_s": 0.0, "review_wall_s": 0.0, "gold_s": 0.0}


def _gold_seeds(gold_dir: Path, tasks, *, require_gold: bool, accept_missing_gold: bool):
    """Each task's reference-fix seed, or None with why; refuses a stage that lacks one."""
    if require_gold:
        missing = [t for t in tasks if not (gold_dir / f"{t}.json").exists()
                   and not (accept_missing_gold and (gold_dir / f"{t}.error.txt").exists())]
        if missing:
            raise SystemExit(
                f"refusing to start: no reference-fix seed for {', '.join(missing)} in {gold_dir}. "
                "Run gold-seeds; a recorded build failure (<task>.error.txt) is accepted only with "
                "--accept-missing-gold (Amendment 2, item 2)."
            )
    seeds, why = {}, {}
    for t in tasks:
        path, err = gold_dir / f"{t}.json", gold_dir / f"{t}.error.txt"
        seeds[t] = SeedRecord.from_json(path.read_text(encoding="utf-8")) if path.exists() else None
        why[t] = "no reference-fix seed" + (f": {err.read_text(encoding='utf-8').strip()}" if err.exists() else "")
    return seeds, why


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


class StageRows(list):
    """A stage's rows, plus whether the stage stopped after MAX_CONSECUTIVE_ERRORS errors.

    `stopped` is set even when the stop fell on the stage's last row, where
    the row count alone cannot show it.
    """

    def __init__(self, rows=(), *, stopped: bool = False) -> None:
        super().__init__(rows)
        self.stopped = stopped


#: The error prefix of a gold check whose sandbox operation failed (Amendment 3, item 2).
GOLD_INFRA = "infrastructure: gold check: "


def _commit() -> str | None:
    """The short SHA of HEAD, recorded on every new row (Amendment 3, item 5)."""
    result = _git("rev-parse", "--short", "HEAD")
    return result.stdout.strip() or None if result.returncode == 0 else None


def _raise_capped(prior: dict | None, review_path: Path) -> bool:
    """Amendment 3, item 1: a review that raised on its first attempt and 3 retries stands.

    A raised review's row error is "infrastructure: <Type>: <msg>" and leaves
    no review.json. A flagged review's error shares the prefix, but it never
    reaches MAX_INFRA_RETRIES as an error row (at the cap it stands, with
    error None), and a gold-check error keeps its review.json.
    """
    return (prior is not None and prior["retries"] >= MAX_INFRA_RETRIES
            and (prior["error"] or "").startswith("infrastructure: ")
            and not prior["error"].startswith(GOLD_INFRA) and not review_path.exists())


async def run_stage(bench: Path, out: Path, gold_dir: Path, todo, runner, client, *,
                    require_gold: bool = True, accept_missing_gold: bool = False,
                    retry_other: bool = False, retry_capped: bool = False) -> StageRows:
    """Review each patch in `todo` that has no finished row, and gold-check its verified test.

    Returns the rows so far, with `stopped` set when the stage stopped after
    MAX_CONSECUTIVE_ERRORS consecutive errors. `retry_capped` retries rows
    that Amendment 3's caps would leave standing (a review that keeps
    raising, a gold check that keeps failing).
    """
    tasks = sorted({task for task, _, _ in todo})
    golds, no_gold = _gold_seeds(gold_dir, tasks, require_gold=require_gold,
                                 accept_missing_gold=accept_missing_gold)
    started, n = time.perf_counter(), len(todo)
    commit = _commit()
    rows = StageRows()
    tally = Counter()
    consecutive = 0
    for i, (task, stem, arm) in enumerate(todo, 1):
        task_dir = out / task
        row_path = task_dir / f"{stem}.row.json"
        review_path = task_dir / f"{stem}.review.json"
        # A corrupt row.json (a crash mid-write) is no prior row: resume from review.json.
        prior = _read_json(row_path)
        if prior is not None and prior["error"] is None:
            rows.append(prior)
            tally["before"] += 1
            continue
        if prior is not None and prior.get("retry_other") is False and not retry_other:
            rows.append(prior)
            tally["skipped"] += 1
            _say(f"[{i}/{n}] {task}/{stem} ({arm}): skipped, {prior['error']} (retry with --retry-other)")
            continue
        if not retry_capped and _raise_capped(prior, review_path):
            rows.append(prior)  # it stands as an error: listed, and no test in the yield
            tally["skipped"] += 1
            _say(f"[{i}/{n}] {task}/{stem} ({arm}): stands after {prior['retries']} retries, "
                 f"{prior['error']} (retry with --retry-capped)")
            continue
        # Amendment 3, item 2: a gold check that failed on its first attempt
        # and 3 retries is not run again; its last op error is its tail.
        gold_capped = None
        if (not retry_capped and prior is not None and prior["retries"] >= MAX_INFRA_RETRIES
                and (prior["error"] or "").startswith(GOLD_INFRA)):
            gold_capped = prior["error"][len(GOLD_INFRA):]

        review = None
        history = list(prior.get("history") or []) + [prior["error"]] if prior else []
        if review_path.exists():
            review = _read_json(review_path)
            if review is None:
                _set_aside(review_path, task_dir, stem, "corrupt")
                history.append("corrupt review.json")
        if gold_capped is not None:
            retries = prior["retries"]  # no new attempt is made
        else:
            # Never fewer than the reviews already set aside, so a crash between
            # setting one aside and writing its row cannot lose a retry.
            retries = max(prior["retries"] + 1 if prior else 0, _archived(task_dir, stem))
        row = {"task": task, "patch": stem, "arm": arm, "retries": retries, "history": history, "commit": commit}
        try:
            if review is None:
                review = await review_patch(bench, task, stem, runner, client, task_dir)
            reason = infra_failure(review)
            if reason is not None and retries < MAX_INFRA_RETRIES:
                _set_aside(review_path, task_dir, stem)
                row |= EMPTY | {"error": f"infrastructure: {reason}"}
            else:
                # A completed review is never rerun (spec §17): a crash between
                # review.json and row.json resumes from the review on disk.
                fields, gold_failure = await _row_from_review(review, runner, golds[task], no_gold[task],
                                                              gold_capped=gold_capped)
                row |= fields
                # A failed gold operation keeps the review's fields: the test stays verified.
                row["error"] = f"{GOLD_INFRA}{gold_failure}" if gold_failure is not None else None
                if reason is not None:  # Amendment 2: after 3 retries the last review stands
                    row |= {"infra_capped": True, "infra_reason": reason}
        except INFRASTRUCTURE as exc:  # recorded and retried on the next run
            row |= EMPTY | {"error": f"infrastructure: {type(exc).__name__}: {str(exc)[:300]}"}
        except Exception as exc:  # not a known infrastructure type: never retried blindly
            row |= EMPTY | {"error": f"other: {type(exc).__name__}: {str(exc)[:300]}", "retry_other": False}
        _write(row_path, json.dumps(row, indent=1) + "\n")
        rows.append(row)
        tally["errors" if row["error"] else "done"] += 1
        tally["retried"] += row["retries"] > 0
        consecutive = consecutive + 1 if row["error"] else 0
        _say(f"[{i}/{n}] {task}/{stem} ({arm}): verified={row['verified']} gold={row['gold']} "
             f"error={row['error']} | errors {tally['errors']} | {time.perf_counter() - started:.0f}s")
        if consecutive >= MAX_CONSECUTIVE_ERRORS:
            _say(f"stopping the stage: {consecutive} consecutive errors (Amendment 2, item 1); "
                 f"the last was {row['error']}")
            rows.stopped = True
            break
    _say(f"stage summary: done {tally['done'] + tally['before']}, errors {tally['errors']}, "
         f"retried {tally['retried']}, skipped {tally['skipped']}, wall {time.perf_counter() - started:.0f}s "
         f"({tally['before']} were done before this run)")
    return rows


def provenance() -> dict:
    """Amendment 2, item 8, and Amendment 3, item 5: where a report came from."""
    from chesterton.llm import client as llm

    commit = _git("rev-parse", "--short", "HEAD")
    status = _git("status", "--porcelain", "--", "src/", "scripts/")
    diff = _git("diff", "--quiet", REGISTRATION, "--", *PIPELINE)
    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        "pipeline_unchanged_since_registration": {0: True, 1: False}.get(diff.returncode),
        "models": {"execution": llm.EXECUTION_MODEL, "reasoning": llm.REASONING_MODEL,
                   "synthesis": llm.SYNTHESIS_MODEL},
        "python": platform.python_version(),
    }


def write_report(out: Path, todo, *, provenance: dict | None = None) -> dict:
    """The report on exactly the registered rows for `todo`, naming any that are missing."""
    rows, missing = [], []
    for task, stem, _ in todo:
        row = _read_json(out / task / f"{stem}.row.json")
        if row is None:
            missing.append({"task": task, "patch": stem})
        else:
            rows.append(row)
    sample = None
    saved = _read_json(out / "sample.json")
    if saved is not None:
        sample = {"fraction": saved["fraction"], "seed": saved["seed"],
                  "pairs_per_task": dict(sorted(Counter(p["task"] for p in saved["pairs"]).items()))}
    if provenance is None:
        # The module-level provenance(), which the parameter shadows here.
        provenance = globals()["provenance"]()
    report = v.report(rows, missing=missing, sample=sample, provenance=provenance)
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


def _cost_lines(r: dict) -> list[str]:
    lines = [f"cost, over {r['cost_rows']} rows without an error:"]
    for key, c in r["cost"].items():
        med = "n/a" if c["median"] is None else f"{c['median']:g}"
        lines.append(f"  {key}: median {med}, total {c['total']:g}")
    return lines


def _estimand_lines(r: dict) -> list[str]:
    lines = [f"{r['patches']} patches", _line("yield", r["yield"]), _line("agreement", r["agreement"]),
             _line("agreement, every gold error counted as fails_on_gold", r["agreement_bound"]),
             f"gold errors: {r['gold_errors']}"]
    s = r["without_matplotlib_23314"]
    lines += [_line("yield without matplotlib-23314", s["yield"]),
              _line("agreement without matplotlib-23314", s["agreement"])]
    return lines


def _print_sizes(sizes: dict[str, tuple[int, int]]) -> None:
    for task, (k, n) in sizes.items():
        _say(f"  {task}: k = {k} of {n}")
    _say(f"  total: {sum(k for k, _ in sizes.values())} of {sum(n for _, n in sizes.values())} pairs")


async def _main(argv: list[str]) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):  # a stream that cannot be reconfigured; _say still guards
            pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gold-seeds")
    run = sub.add_parser("run")
    run.add_argument("stage", choices=["pilot", "main"])
    run.add_argument("--sample", type=float, default=None, help="budget rule: fraction of main pairs")
    run.add_argument("--dry-run", action="store_true", help="with --sample: print each task's k, write nothing")
    run.add_argument("--accept-missing-gold", action="store_true",
                     help="start although a task has only a recorded seed-build failure")
    run.add_argument("--retry-other", action="store_true", help="also retry rows that failed with an unknown error")
    run.add_argument("--retry-capped", action="store_true",
                     help="also retry a review that kept raising, or a gold check that kept failing, past the cap")
    rep = sub.add_parser("report")
    rep.add_argument("stage", choices=["pilot", "main"])
    bud = sub.add_parser("budget")
    bud.add_argument("--usd", type=float, required=True, help="the owner's budget B, in US dollars")
    bud.add_argument("--cost-per-patch", type=float, required=True, help="c: the pilot's billed spend / 10")
    args = parser.parse_args(argv)

    if args.cmd == "report":
        r = write_report(BENCH / "study-v3" / args.stage, stage_patches(BENCH, args.stage))
        if r["missing"]:
            _say(f"INCOMPLETE: {r['present']} of {r['expected']} rows")
        if args.stage == "pilot":
            _say("pilot (reported separately, not part of the main estimate)")
            lines = _cost_lines(r) + _estimand_lines(r)
        else:
            if r["sample"] is not None:
                _say(f"a stratified sample: fraction {r['sample']['fraction']}, seed {r['sample']['seed']}")
            lines = _estimand_lines(r) + _cost_lines(r)
        for line in lines:
            _say(line)
        return 0

    if args.cmd == "budget":
        f = v.budget_fraction(args.usd, args.cost_per_patch)
        _say(f"f = min(1, {args.usd:g} / ({v.MAIN_PATCHES} x {args.cost_per_patch:g})), "
             f"rounded down to 0.05: f = {f:.2f}")
        if f >= 1:
            _say("f = 1: no sample; run main in full")
            return 0
        if f <= 0:
            _say("f = 0: the budget is below the smallest sample; no sample can be drawn")
            return 1
        _print_sizes(v.sample_sizes(_main_pairs(BENCH), f))
        _say("record B, c and f as Amendment 4 before any main run; nothing was written")
        return 0

    if args.sample is not None and args.stage != "main":
        parser.error("--sample applies to the main stage only")
    if args.dry_run:
        if args.sample is None:
            parser.error("--dry-run applies with --sample only")
        _say(f"dry run, fraction {args.sample}: nothing is written")
        _print_sizes(v.sample_sizes(_main_pairs(BENCH), args.sample))
        return 0

    from chesterton.llm.client import NemotronClient
    from chesterton.sandbox.contree import ConTreeSandboxRunner

    runner = ConTreeSandboxRunner()
    try:
        if args.cmd == "gold-seeds":
            pairs = json.loads((BENCH / "pairs.json").read_text(encoding="utf-8"))
            tasks = sorted({p.task for p in v.population(pairs, BENCH / "runs")})
            gold_dir = BENCH / "gold-seeds"
            for task, state in (await build_gold_seeds(runner, tasks, gold_dir)).items():
                counts = f" | {seed_counts(gold_dir, BENCH / 'seeds', task)}" if state in ("built", "exists") else ""
                _say(f"  {task}: {state}{counts}")
            return 0
        todo = stage_patches(BENCH, args.stage, fraction=args.sample)
        _say(f"{args.stage}: {len(todo)} patches")
        rows = await run_stage(BENCH, BENCH / "study-v3" / args.stage, BENCH / "gold-seeds", todo, runner,
                               NemotronClient(), accept_missing_gold=args.accept_missing_gold,
                               retry_other=args.retry_other, retry_capped=args.retry_capped)
        # Stopped by the circuit breaker, even if the stop fell on the last row.
        return 3 if rows.stopped else 0
    finally:
        await runner.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
