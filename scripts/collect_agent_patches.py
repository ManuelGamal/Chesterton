"""Collect the agent patches that SWE-bench marked RESOLVED for given tasks.

Why: a SWE-bench gold patch is a poor seed, because its test_patch was written
for it (spec §15, 2026-09-19). The thesis target is the AGENT patch that
passed those tests. UTBoost (ACL'25) found 345 such patches that were wrong,
but did not publish which. They can be rebuilt from here: take the resolved
patches that differ from the gold patch, then check each against UTBoost's
augmented test.

Sources:
  - SWE-bench/experiments on GitHub: evaluation/<split>/<submission>/results/
    results.json, whose "resolved" list says which instances passed.
  - s3://swe-bench-submissions/<split>/<submission>/logs/<id>/patch.diff: the
    patch itself, read over public HTTPS.

The experiments repository states no license, so the patches are written to a
git-ignored directory and never committed. Uses 2 GitHub API calls (the
submission listings); everything else is raw or S3 and does not count
against the API rate limit.

Usage:
    python scripts/collect_agent_patches.py <out-dir> <instance-id> [...]
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx

from chesterton.github.swebench import fetch_swebench_rows, task_from_row

LISTING = "https://api.github.com/repos/SWE-bench/experiments/contents/evaluation/{split}"
RESULTS = "https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/{split}/{sub}/results/results.json"
PATCH = "https://swe-bench-submissions.s3.amazonaws.com/{split}/{sub}/logs/{iid}/patch.diff"
SPLITS = ("lite", "verified")


def _normalised(diff: str) -> str:
    """Identity for grouping: the edits, ignoring index hashes and whitespace."""
    lines = []
    for line in diff.splitlines():
        if line.startswith(("index ", "diff --git")):
            continue
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            lines.append(line.rstrip())
    return "\n".join(lines)


def _source_only(diff: str, test_paths: set[str]) -> str:
    """Drop edits to the task's test files, as SWE-bench's harness does."""
    kept, keep = [], True
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1].strip()
            keep = path not in test_paths
        if keep:
            kept.append(line)
    return "".join(kept)


async def main(out_dir: Path, instance_ids: list[str]) -> int:
    semaphore = asyncio.Semaphore(16)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        # One scan for every instance: scanning per instance drew HTTP 429.
        rows = await fetch_swebench_rows(instance_ids, client=http)
        missing = [iid for iid in instance_ids if iid not in rows]
        if missing:
            print(f"not in SWE-bench Verified or Lite, skipped: {', '.join(missing)}")
        tasks = {iid: task_from_row(rows[iid]) for iid in instance_ids if iid in rows}

        submissions: list[tuple[str, str]] = []
        for split in SPLITS:
            r = await http.get(LISTING.format(split=split),
                               headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            submissions += [(split, e["name"]) for e in r.json() if e["type"] == "dir"]
        print(f"{len(submissions)} submissions across {', '.join(SPLITS)}")

        async def resolved(split: str, sub: str) -> tuple[str, str, set[str]]:
            async with semaphore:
                r = await http.get(RESULTS.format(split=split, sub=sub))
            if r.status_code != 200:
                return split, sub, set()
            return split, sub, set(r.json().get("resolved", []))

        results = await asyncio.gather(*(resolved(s, n) for s, n in submissions))

        async def patch(split: str, sub: str, iid: str) -> tuple[str, str, str | None]:
            async with semaphore:
                r = await http.get(PATCH.format(split=split, sub=sub, iid=iid))
            return split, sub, r.text if r.status_code == 200 and r.text.strip() else None

        for iid, task in tasks.items():
            wanted = [(s, n) for s, n, ok in results if iid in ok]
            fetched = await asyncio.gather(*(patch(s, n, iid) for s, n in wanted))
            gold = _normalised(_source_only(task.pr.diff, set(task.test_paths)))

            groups: dict[str, list[str]] = defaultdict(list)
            texts: dict[str, str] = {}
            missing = []
            for split, sub, text in fetched:
                if text is None:
                    missing.append(f"{split}/{sub}")
                    continue
                source = _source_only(text, set(task.test_paths))
                key = hashlib.sha256(_normalised(source).encode()).hexdigest()[:12]
                groups[key].append(f"{split}/{sub}")
                texts[key] = source

            target = out_dir / iid
            target.mkdir(parents=True, exist_ok=True)
            summary = []
            for key, subs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                is_gold = _normalised(texts[key]) == gold
                (target / f"{key}.diff").write_text(texts[key], encoding="utf-8", newline="\n")
                summary.append({"patch": f"{key}.diff", "same_as_gold": is_gold,
                                "submissions": subs})
            (target / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

            print(f"\n{iid}: resolved by {len(wanted)} submissions, "
                  f"{len(missing)} without a retrievable patch")
            print(f"  {len(groups)} distinct source patches:")
            for entry in summary:
                tag = "gold-equivalent" if entry["same_as_gold"] else "DIFFERS from gold"
                print(f"    {entry['patch']}  x{len(entry['submissions']):3d}  {tag}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]), sys.argv[2:])))
