"""Study v3, verified tests at scale (spec §17, registered 2026-09-26).

Pure logic: which patches the study reviews, and the registered estimands.
Nothing here opens a sandbox or calls a model; scripts/study_v3.py does.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass
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


def sample(pairs: list[Pair], fraction: float) -> list[Pair]:
    """The budget rule: the same fraction of every task's pairs (at least one), seeded."""
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    out: list[Pair] = []
    for task in sorted({p.task for p in pairs}):
        mine = sorted((p for p in pairs if p.task == task), key=lambda p: p.wrong)
        k = max(1, round(fraction * len(mine)))
        out += random.Random(f"{SEED}:{task}").sample(mine, k)
    return out


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
    if r["error"]:
        return "error"
    if r["headline"] == 0:
        return "no headline"
    return f"not verified: {r['status']}"


def report(rows: list[dict]) -> dict:
    """Everything spec §17 registers for v3, as plain JSON."""
    def cost(key: str) -> dict:
        values = [r[key] for r in rows]
        return {"median": float(median(values)) if values else None, "total": sum(values)}

    by_task = {}
    for task in sorted({r["task"] for r in rows}):
        mine = [r for r in rows if r["task"] == task]
        y, a = yield_counts(mine).get(task, (0, 0)), agreement_counts(mine).get(task, (0, 0))
        by_task[task] = {"yield": list(y), "agreement": list(a)}
    return {
        "patches": len(rows),
        "yield": estimate(yield_counts(rows)),
        "agreement": estimate(agreement_counts(rows)),
        "gold_errors": sum(1 for r in rows if r["verified"] and r["gold"] == "error"),
        "by_arm": {
            arm: {"yield": estimate(yield_counts(mine)), "agreement": estimate(agreement_counts(mine))}
            for arm in ("wrong", "control")
            if (mine := [r for r in rows if r["arm"] == arm])
        },
        "by_task": by_task,
        "headline_counts": {str(h): c for h, c in sorted(Counter(r["headline"] for r in rows).items(), reverse=True)},
        "no_test_reasons": dict(Counter(_reason(r) for r in rows if not r["verified"])),
        "retries": sum(r["retries"] for r in rows),
        "retried": [{"task": r["task"], "patch": r["patch"], "retries": r["retries"]} for r in rows if r["retries"] > 0],
        "errors": [{"task": r["task"], "patch": r["patch"], "error": r["error"]} for r in rows if r["error"]],
        "cost": {key: cost(key) for key in ("super_calls", "ultra_calls", "ops", "wall_s")},
    }
