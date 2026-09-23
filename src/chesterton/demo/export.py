"""Turn recorded artifacts into one replay bundle per demo story (demo spec §5).

A reshaping only: nothing here runs a test, calls a model or opens a
sandbox. Every verdict, duration and finding in a bundle was recorded by a
real run. Whole modules never enter a bundle; the UI gets windows.
"""

from __future__ import annotations

from chesterton.diffing.parse import split_by_file
from chesterton.execute.mutants import MutantResult
from chesterton.filters import is_mutable_source
from chesterton.reduce.patch import patch_hunks
from chesterton.seed.record import SeedRecord
from chesterton.triage.evidence import evidence_for, results_from_report

#: The real run's sandbox concurrency (execute.pool).
CONCURRENCY = 24
#: Display lengths, in recorded seconds, for phases the run does not time
#: per step. The UI says only mutant durations are as measured.
GENERATE_S = 16.0
DDMIN_S = 16.0
TRIAGE_S = 16.0
REGRESSION_S = 16.0
#: Lines of context in each mutant's before/after window.
WINDOW = 2


def schedule(results: list[MutantResult], durations: list[float | None]) -> list[tuple[float, float]]:
    """(start_s, duration_s) per result: greedy onto CONCURRENCY slots, in order.

    An uncovered mutant cost no sandbox op, and an unmeasured one has no
    duration: both take no time and land at 0.
    """
    slots = [0.0] * CONCURRENCY
    placed: list[tuple[float, float]] = []
    for result, duration in zip(results, durations):
        if result.verdict == "uncovered" or not duration:
            placed.append((0.0, 0.0))
            continue
        i = min(range(CONCURRENCY), key=lambda k: slots[k])
        start = slots[i]
        slots[i] = start + duration
        placed.append((round(start, 3), round(duration, 3)))
    return placed


def _patch(seed: SeedRecord) -> tuple[str, list[str]]:
    exempt = seed.unexercised_new_files()
    kept, dropped = [], []
    for path, section in split_by_file(seed.pr.diff):
        if is_mutable_source(path) and path not in exempt:
            kept.append(section)
        else:
            dropped.append(path)
    return "".join(kept), dropped


def _finding(prefix: str, index: int, item: dict) -> dict:
    ev, c = item["evidence"], item["classification"]
    return {
        "id": f"{prefix}{index}", "file": ev["file"], "start_line": ev["start_line"],
        "end_line": ev["end_line"], "operator": ev["operator"], "rationale": ev["rationale"],
        "original": ev["original"], "mutated": ev["mutated"], "diff": ev["diff"],
        "tests": list(ev["tests"]), "label": c["label"], "category": c["category"],
        "confident": c["confident"], "explanation": c["explanation"],
        "agreement": item.get("agreement"),
    }


def _regression(review: dict, headline: list[dict], gold: str | None) -> dict | None:
    reg = review.get("regression")
    if reg is None:
        return None
    # Review writes its test for the first headline finding that has tests.
    target = next((f for f in headline if f["tests"]), headline[0] if headline else None)
    verification = reg.get("verification") or {}
    return {
        "finding_id": target["id"] if target else None,
        "path": reg["path"], "source": reg["source"],
        "status": verification.get("status"), "detail": verification.get("detail"),
        "patch_tail": verification.get("patch_tail", ""),
        "mutant_tail": verification.get("mutant_tail", ""),
        "attempts": reg["attempts"], "note": reg.get("note"),
        "verified": bool(reg.get("verified")),
        "gold": gold if reg.get("verified") else None,
    }


def build_bundle(
    *, story: dict, seed: SeedRecord, run: dict, review: dict, gold: str | None,
    submission: str, commit: str,
) -> dict:
    diff, dropped = _patch(seed)
    results = results_from_report(run)
    placed = schedule(results, [row.get("duration_s") for row in run["results"]])

    lanes: dict[tuple[str, int, int], str] = {}
    mutants = []
    for i, (result, (start, duration)) in enumerate(zip(results, placed)):
        m = result.mutant
        lane = lanes.setdefault((m.file, m.start_line, m.end_line), f"L{len(lanes)}")
        ev = evidence_for(result, seed.pr.title, context=WINDOW)
        mutants.append({
            "id": f"m{i}", "lane": lane, "file": m.file, "start_line": m.start_line,
            "end_line": m.end_line, "operator": m.operator, "verdict": result.verdict,
            "tests": len(result.tests), "start_s": start, "duration_s": duration,
            "before": ev.original, "after": ev.mutated,
        })

    by_label = {h.label: h for h in patch_hunks(seed.pr.diff)[0]}
    surface = run.get("surface") or {}
    undefended = []
    for label in surface.get("undefended", []):
        h = by_label.get(label)
        if h is not None:
            undefended.append({"file": h.file, "start_line": h.target_start,
                               "end_line": h.target_start + max(h.target_length, 1) - 1})

    triage = review["triage"]
    headline = [_finding("h", i, x) for i, x in enumerate(triage["headline"])]
    mutants_end = max((m["start_s"] + m["duration_s"] for m in mutants), default=0.0)
    regression = _regression(review, headline, gold)
    return {
        "meta": {
            "id": story["id"], "tab": story["tab"], "title": story["title"],
            "pr_title": seed.pr.title, "repo": f"{seed.pr.owner}/{seed.pr.repo}",
            "task": seed.slug, "submission": submission, "utboost": story["utboost"],
            "chesterton_commit": commit, "recorded": seed.built_at,
        },
        "patch": {"diff": diff, "dropped_files": dropped},
        "lanes": [{"id": lane, "file": f, "start_line": s, "end_line": e}
                  for (f, s, e), lane in lanes.items()],
        "mutants": mutants,
        "tier0": [{"file": f, "line": line} for f, line in run.get("tier0", [])],
        "ddmin": {"undefended": undefended, "probes": surface.get("probes", 0)},
        "triage": {
            "headline": headline,
            "worth_a_look": [_finding("w", i, x) for i, x in enumerate(triage["worth_a_look"])],
            "dismissed": [_finding("d", i, x) for i, x in enumerate(triage["dismissed"])],
            "model_calls": triage["model_calls"],
        },
        "regression": regression,
        "counters": {
            "sandbox_ops": run.get("ops_used", 0) + review.get("ops_used", 0),
            "lightning_calls": (run.get("model") or {}).get("calls", 0),
            "super_calls": triage["model_calls"],
            "ultra_calls": regression["attempts"] if regression else 0,
            "run_wall_s": run.get("wall_s", 0.0),
        },
        "timeline": {
            "generate_s": GENERATE_S, "mutants_end_s": round(mutants_end, 3),
            "ddmin_s": DDMIN_S, "triage_s": TRIAGE_S, "regression_s": REGRESSION_S,
            "total_s": round(GENERATE_S + mutants_end + DDMIN_S + TRIAGE_S + REGRESSION_S, 3),
        },
    }
