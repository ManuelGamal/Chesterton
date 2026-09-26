"""Study v3, verified tests at scale (spec §17, registered 2026-09-26).

Pure logic: which patches the study reviews, and the registered estimands.
Nothing here opens a sandbox or calls a model; scripts/study_v3.py does.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from statistics import median

#: Registered: the seed for the budget sample and the cluster bootstrap.
SEED = 20260926
#: Registered: cluster-bootstrap resamples.
RESAMPLES = 10_000
#: Two-sided 95%.
Z = 1.959963984540054
#: Registered pilot: the first N pairs, by wrong-patch stem, of these tasks.
PILOT = {"pydata__xarray-4687": 2, "sympy__sympy-21847": 2, "scikit-learn__scikit-learn-14087": 1}


@dataclass(frozen=True)
class Pair:
    task: str
    wrong: str
    control: str


def population(pairs: list[dict], runs: Path) -> list[Pair]:
    """The pairs v2 analysed: those whose wrong and control run files both exist."""
    out = []
    for p in pairs:
        if not p.get("wrong") or not p.get("control"):
            # match_controls leaves control null when no size-matched
            # control patch is left for a wrong patch; it has no control run
            # file, so it is excluded here rather than raising.
            continue
        wrong, control = Path(p["wrong"]).stem, Path(p["control"]).stem
        if all((runs / p["task"] / f"{stem}.json").exists() for stem in (wrong, control)):
            out.append(Pair(p["task"], wrong, control))
    return out


def pilot(pop: list[Pair]) -> list[Pair]:
    chosen: list[Pair] = []
    for task, n in PILOT.items():
        chosen += sorted((p for p in pop if p.task == task), key=lambda p: p.wrong)[:n]
    return chosen


def main_pairs(pop: list[Pair], pilot_pairs: list[Pair]) -> list[Pair]:
    excluded = set(pilot_pairs)
    return [p for p in pop if p not in excluded]


def _k(fraction: float, n: int) -> int:
    """Amendment 1: k = max(1, round(fraction x n)), Python's round (halves to even)."""
    return max(1, round(fraction * n))


def sample(pairs: list[Pair], fraction: float) -> list[Pair]:
    """The budget rule: the same fraction of every task's pairs (at least one), seeded."""
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    out: list[Pair] = []
    for task in sorted({p.task for p in pairs}):
        mine = sorted((p for p in pairs if p.task == task), key=lambda p: p.wrong)
        out += random.Random(f"{SEED}:{task}").sample(mine, _k(fraction, len(mine)))
    return out


def sample_sizes(pairs: list[Pair], fraction: float) -> dict[str, tuple[int, int]]:
    """Per task: (k the sample would draw, n main pairs). Draws nothing."""
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    counts = Counter(p.task for p in pairs)
    return {task: (_k(fraction, n), n) for task, n in sorted(counts.items())}


#: Amendment 2, item 3: the registered main study's patch count.
MAIN_PATCHES = 292


def budget_fraction(usd: float, cost_per_patch: float, patches: int = MAIN_PATCHES) -> float:
    """Amendment 2, item 3: f = min(1, B / (292 x c)), rounded down to a multiple of 0.05.

    Computed in decimal from the numbers as typed, so 14.6 / (292 x 0.1) is
    exactly 0.5 and is not rounded down to 0.45 by binary float error.
    """
    if cost_per_patch <= 0 or usd < 0:
        raise ValueError(f"need a budget >= 0 and a cost per patch > 0, got {usd} and {cost_per_patch}")
    raw = Decimal(str(usd)) / (patches * Decimal(str(cost_per_patch)))
    steps = (raw * 20).to_integral_value(rounding=ROUND_FLOOR)
    return float(min(Decimal(1), steps / 20))


def patches(pairs: list[Pair]) -> list[tuple[str, str, str]]:
    return [x for p in pairs for x in ((p.task, p.wrong, "wrong"), (p.task, p.control, "control"))]


def wilson(k: int, n: int) -> tuple[float, float, float] | None:
    """(rate, low, high): the Wilson score interval at 95%."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def yield_counts(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Per task: (patches with a verified test, patches). Every patch counts."""
    counts: dict[str, list[int]] = {}
    for r in rows:
        c = counts.setdefault(r["task"], [0, 0])
        c[0] += bool(r["verified"])
        c[1] += 1
    return {t: (k, n) for t, (k, n) in counts.items()}


def agreement_counts(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Per task: (verified tests passing on the correct fix, verified tests checked on it)."""
    counts: dict[str, list[int]] = {}
    for r in rows:
        if not r["verified"] or r["gold"] not in ("passes_on_gold", "fails_on_gold"):
            continue
        c = counts.setdefault(r["task"], [0, 0])
        c[0] += r["gold"] == "passes_on_gold"
        c[1] += 1
    return {t: (k, n) for t, (k, n) in counts.items()}


def agreement_bound_counts(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Amendment 2, item 2: agreement with every gold `error` counted as `fails_on_gold`."""
    counts: dict[str, list[int]] = {}
    for r in rows:
        if not r["verified"] or r["gold"] not in ("passes_on_gold", "fails_on_gold", "error"):
            continue
        c = counts.setdefault(r["task"], [0, 0])
        c[0] += r["gold"] == "passes_on_gold"
        c[1] += 1
    return {t: (k, n) for t, (k, n) in counts.items()}


_COLLECTION = re.compile(r"ImportError|ModuleNotFoundError|ERROR collecting|errors? during collection")


def gold_error_kind(tail: str | None) -> str:
    """Amendment 2, item 2: a gold `error` is a collection/import error, or other."""
    return "collection" if tail and _COLLECTION.search(tail) else "other"


def normalise_status(status: str | None) -> str:
    """A no-test status reduced to its value: the fixed key, never free text.

    `status` is the verification status, or the regression's note when no
    test reached verification (review.py): "no regression test generated:
    <failure>", "no covering test to place a new test beside", or
    "regression stage failed: <Type>: <message>".
    """
    if not status:
        return "none"
    if status.startswith("no regression test generated:"):
        value = status.split(":", 1)[1].strip()
        return value.split(" ", 1)[0] or "none"
    if status.startswith("no covering test"):
        return "no covering test"
    if status.startswith("regression stage failed"):
        return "regression stage failed"
    return status.split(":", 1)[0].strip()


def per_task_mean(counts: dict[str, tuple[int, int]]) -> float | None:
    rates = [k / n for k, n in counts.values() if n > 0]
    return sum(rates) / len(rates) if rates else None


def cluster_interval(
    counts: dict[str, tuple[int, int]], *, resamples: int = RESAMPLES, seed: int = SEED
) -> tuple[float, float] | None:
    """A 95% percentile interval for the pooled rate, resampling tasks with replacement."""
    tasks = sorted(t for t, (_, n) in counts.items() if n > 0)
    if not tasks:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        pick = [rng.choice(tasks) for _ in tasks]
        k = sum(counts[t][0] for t in pick)
        n = sum(counts[t][1] for t in pick)
        stats.append(k / n)
    stats.sort()
    last = len(stats) - 1
    return stats[round(0.025 * last)], stats[round(0.975 * last)]


def estimate(counts: dict[str, tuple[int, int]]) -> dict:
    k = sum(k for k, _ in counts.values())
    n = sum(n for _, n in counts.values())
    w = wilson(k, n)
    return {
        "k": k, "n": n,
        "rate": w[0] if w else None,
        "wilson": [w[1], w[2]] if w else None,
        "per_task_mean": per_task_mean(counts),
        "cluster_interval": list(ci) if (ci := cluster_interval(counts)) else None,
        "tasks": sum(1 for _, n in counts.values() if n > 0),
    }


def _reason(r: dict) -> str:
    """Amendment 2: the fixed categories of why a patch got no verified test."""
    if r["error"]:
        return "error: other" if r["error"].startswith("other:") else "error: infrastructure"
    if r.get("infra_capped"):
        return "infrastructure (capped)"
    if r["headline"] == 0:
        return "no headline"
    return f"not verified: {normalise_status(r['status'])}"


#: Amendment 2, item 7: sensitivity (c) leaves this task out.
SENSITIVITY_C_TASK = "matplotlib__matplotlib-23314"


def report(
    rows: list[dict],
    *,
    missing: list[dict] | None = None,
    sample: dict | None = None,
    provenance: dict | None = None,
) -> dict:
    """Everything spec §17 registers for v3, as plain JSON.

    `rows` are the stage's rows that exist; `missing` names the registered
    patches that have none. `sample` and `provenance` come from the driver,
    so this module stays pure.
    """
    missing = list(missing or [])
    # Amendment 2: cost medians leave out error rows, whose zeros are no cost.
    costed = [r for r in rows if not r["error"]]

    def cost(key: str) -> dict:
        values = [r[key] for r in costed]
        return {"median": float(median(values)) if values else None, "total": sum(values)}

    by_task = {}
    for task in sorted({r["task"] for r in rows}):
        mine = [r for r in rows if r["task"] == task]
        y, a = yield_counts(mine).get(task, (0, 0)), agreement_counts(mine).get(task, (0, 0))
        by_task[task] = {"yield": list(y), "agreement": list(a)}
    without_c = [r for r in rows if r["task"] != SENSITIVITY_C_TASK]
    gold_errors = [r for r in rows if r["verified"] and r["gold"] == "error"]
    return {
        "expected": len(rows) + len(missing),
        "present": len(rows),
        "missing": missing,
        "sample": sample,
        "provenance": provenance,
        "patches": len(rows),
        "yield": estimate(yield_counts(rows)),
        "agreement": estimate(agreement_counts(rows)),
        "agreement_bound": estimate(agreement_bound_counts(rows)),
        "without_matplotlib_23314": {
            "yield": estimate(yield_counts(without_c)),
            "agreement": estimate(agreement_counts(without_c)),
        },
        "gold_errors": len(gold_errors),
        "gold_errors_list": [
            {"task": r["task"], "patch": r["patch"], "exit": r.get("gold_exit"),
             "kind": gold_error_kind(r.get("gold_tail"))}
            for r in gold_errors
        ],
        "by_arm": {
            arm: {"yield": estimate(yield_counts(mine)), "agreement": estimate(agreement_counts(mine))}
            for arm in ("wrong", "control")
            if (mine := [r for r in rows if r["arm"] == arm])
        },
        "by_task": by_task,
        "headline_counts": {str(h): c for h, c in sorted(Counter(r["headline"] for r in rows).items(), reverse=True)},
        "no_test_reasons": dict(Counter(_reason(r) for r in rows if not r["verified"])),
        "retries": sum(r["retries"] for r in rows),
        "retried": [{"task": r["task"], "patch": r["patch"], "retries": r["retries"],
                     "history": list(r.get("history") or [])} for r in rows if r["retries"] > 0],
        "errors": [{"task": r["task"], "patch": r["patch"], "error": r["error"]} for r in rows if r["error"]],
        "infra_capped": [{"task": r["task"], "patch": r["patch"], "reason": r.get("infra_reason")}
                         for r in rows if r.get("infra_capped")],
        "cost": {key: cost(key) for key in ("super_calls", "ultra_calls", "ops", "wall_s")},
        "cost_rows": len(costed),
    }
