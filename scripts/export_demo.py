"""Write the demo's replay bundles (docs/superpowers/specs/2026-09-24-chesterton-demo-ui-design.md §4-5).

Usage (from the repo root):
    python scripts/export_demo.py

Reads recorded artifacts only. A story whose seed, run or review is missing
is skipped and reported, never faked. Story 3 needs its review first:
    python -m chesterton review seeds/matplotlib-23314.json runs/matplotlib-23314.json --out review-gold/matplotlib-23314.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from chesterton.demo.export import build_bundle
from chesterton.seed.record import SeedRecord

TASK = "matplotlib__matplotlib-23314"
SCREEN = f"agent_patches_v2/{TASK}/screen.json"

STORIES = [
    {"id": "hero", "tab": "Wrong patch, caught", "utboost": "wrong",
     "title": "An agent's fix passed SWE-bench. Here is what its tests let through.",
     "seed": f"benchmark-v2/seeds/{TASK}/6d83e35469d2.json",
     "run": f"benchmark-v2/runs/{TASK}/6d83e35469d2.json",
     "review": "review-study-2/6d83e35469d2.json",
     "gold": ("review-study-2/summary.json", "6d83e35469d2"),
     "submission": (SCREEN, "6d83e35469d2")},
    {"id": "limit", "tab": "The honest limit", "utboost": "wrong",
     "title": "A verified test can still encode the agent's bug.",
     "seed": f"benchmark-v2/seeds/{TASK}/92beef201cfd.json",
     "run": f"benchmark-v2/runs/{TASK}/92beef201cfd.json",
     "review": "review-study-2/92beef201cfd.json",
     "gold": ("review-study-2/summary.json", "92beef201cfd"),
     "submission": (SCREEN, "92beef201cfd")},
    {"id": "gold", "tab": "The correct fix", "utboost": "correct",
     "title": "The reference fix: well defended, and a quiet review.",
     "seed": "seeds/matplotlib-23314.json",
     "run": "runs/matplotlib-23314.json",
     "review": "review-gold/matplotlib-23314.json",
     "gold": None,
     "submission": "The SWE-bench reference fix"},
]


def submission_for(screen_path: Path, stem: str) -> str:
    screen = json.loads(screen_path.read_text(encoding="utf-8"))
    for entry in screen["patches"]:
        if entry["patch"] == f"{stem}.diff":
            return entry["submissions"][0]
    raise KeyError(f"{stem}.diff not in {screen_path}")


def _gold(root: Path, spec) -> str | None:
    if spec is None:
        return None
    summary_path, stem = spec
    rows = json.loads((root / summary_path).read_text(encoding="utf-8"))
    return next((r["gold"] for r in rows if r["patch"] == stem), None)


def _submission(root: Path, spec) -> str:
    if isinstance(spec, str):
        return spec
    screen_path, stem = spec
    return submission_for(root / screen_path, stem)


def export(root: Path, out: Path, commit: str, *, stories=STORIES) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    exported = []
    for story in stories:
        paths = [root / story[k] for k in ("seed", "run", "review")]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            print(f"  skipped {story['id']}: missing {', '.join(missing)}")
            continue
        seed = SeedRecord.from_json(paths[0].read_text(encoding="utf-8"))
        run, review = (json.loads(p.read_text(encoding="utf-8")) for p in paths[1:])
        bundle = build_bundle(
            story=story, seed=seed, run=run, review=review,
            gold=_gold(root, story["gold"]), submission=_submission(root, story["submission"]),
            commit=commit,
        )
        (out / f"{story['id']}.json").write_text(
            json.dumps(bundle, indent=1) + "\n", encoding="utf-8", newline="\n")
        exported.append(story["id"])
        print(f"  exported {story['id']}: {len(bundle['mutants'])} mutants, "
              f"{len(bundle['triage']['headline'])} headline")
    index = {"stories": [{"id": s["id"], "tab": s["tab"]} for s in stories if s["id"] in exported]}
    (out / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8", newline="\n")
    return exported


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                            capture_output=True, text=True, check=True).stdout.strip()
    exported = export(root, root / "web" / "public" / "stories", commit)
    return 0 if exported else 1


if __name__ == "__main__":
    sys.exit(main())
