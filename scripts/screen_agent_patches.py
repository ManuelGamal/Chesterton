"""Which resolved agent patches does UTBoost's augmented test show to be wrong?

Reads what scripts/collect_agent_patches.py wrote, then for each distinct
patch runs ONE disposable sandbox op from the task's SWE-bench image:

  1. apply the agent's source changes;
  2. apply SWE-bench's ORIGINAL test_patch and run its FAIL_TO_PASS tests.
     These should pass, because SWE-bench marked the patch resolved. A
     failure here means this sandbox does not reproduce "resolved", and the
     patch is set aside, not counted either way;
  3. swap in UTBoost's AUGMENTED test_patch and run its FAIL_TO_PASS tests.

Passing 2 and failing 3 is the target: an agent patch that passed SWE-bench's
tests and is wrong. These are the seeds Chesterton is meant to catch.

Only FAIL_TO_PASS is run, not PASS_TO_PASS, to keep each op small. A patch
that breaks only a PASS_TO_PASS test is under-counted here, so the "wrong"
set is a lower bound.

Usage:
    python scripts/screen_agent_patches.py <patch-dir> <instance-id> [...]

Needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID. Costs one sandbox op per distinct
patch, run at most 24 at a time.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import sys
from collections import Counter
from pathlib import Path

import httpx

from chesterton.execute.pool import SandboxPool
from chesterton.filters import is_mutable_source
from chesterton.github.swebench import fetch_swebench_rows, image_for
from chesterton.sandbox.contree import ConTreeSandboxRunner

PYTHON = "/opt/miniconda3/envs/testbed/bin/python"
UTBOOST = ("Bertsekas/SWE-Bench_Verified_UTBoost", "Bertsekas/SWE-Bench_Lite_UTBoost")
TIMEOUT_S = 600.0

AGENT, ORIGINAL, AUGMENTED = (
    "/chesterton/agent.diff",
    "/chesterton/original_tests.diff",
    "/chesterton/augmented_tests.diff",
)

_MARK = re.compile(r"^CHESTERTON_(\w+)=(\S+)$", re.M)


def _ids(field) -> list[str]:
    return json.loads(field) if isinstance(field, str) else list(field)


#: `diff --git a/x b/x`, and the quoted form git uses when a path has
#: non-ASCII or special characters: `diff --git "a/tem\303\244ge.png" "b/..."`.
#: Live 2026-09-20, sphinx-7440 carried one and a bare split crashed.
_HEADER = re.compile(r'^diff --git ("?)a/(?P<a>.+?)\1 ("?)b/(?P<b>.+?)\3$')


def _files(diff: str) -> list[str]:
    files = []
    for line in diff.splitlines():
        match = _HEADER.match(line)
        if match:
            files.append(match.group("b"))
    return files


def selector(tests: list[str], test_files: list[str]) -> str:
    """pytest arguments selecting a FAIL_TO_PASS list.

    Most SWE-bench tasks list pytest node ids. sympy lists bare function
    names (`test_idiff`), since its own runner is bin/test. Its tests run
    under pytest all the same, so bare names are selected with `-k` inside
    the task's test files. `-k` matches substrings and may select a few
    extra tests; for a screen that is harmless, since extra tests only need
    to keep passing.
    """
    q = shlex.quote
    if all("::" in t for t in tests):
        return " ".join(map(q, tests))
    return " ".join(map(q, test_files)) + " -k " + q(" or ".join(dict.fromkeys(tests)))


def screen_script(
    original_f2p: list[str],
    augmented_f2p: list[str],
    original_files: list[str] = (),
    augmented_files: list[str] = (),
) -> str:
    q = shlex.quote
    py = q(PYTHON)
    apply = "git apply --whitespace=nowarn"
    # The agent patch applies the way SWE-bench's harness applies it: git
    # apply, else GNU patch with fuzz. Live 2026-09-19, 10 xarray patches
    # needed the fallback. Both tools' messages are kept (2>&1), since the
    # first screen threw git's error away and left only "apply failed".
    fuzzy = "patch --batch --fuzz=5 -p1 --no-backup-if-mismatch -i"
    return "\n".join([
        "cd /testbed",
        f"{{ {apply} {AGENT} || {fuzzy} {AGENT}; }} 2>&1 || "
        "{ echo CHESTERTON_APPLY=agent; exit 0; }",
        f"{apply} {ORIGINAL} || {{ echo CHESTERTON_APPLY=original; exit 0; }}",
        f"{py} -m pytest -q -p no:cacheprovider {selector(original_f2p, list(original_files))} "
        "> /tmp/original.txt 2>&1; echo CHESTERTON_ORIGINAL=$?",
        # UTBoost's test patch is written against different starting points
        # per task: for some it replaces the original tests (apply from base,
        # so revert first), for others it extends them (apply on top). Live
        # 2026-09-20, assuming the first excluded every seaborn, requests and
        # pylint-5859 patch, each with ORIGINAL=0. Try on top, then reverted.
        f"{apply} {AUGMENTED} 2>&1 || {{ {apply} -R {ORIGINAL} 2>&1 && "
        f"{apply} {AUGMENTED} 2>&1; }} || {{ echo CHESTERTON_APPLY=augmented; exit 0; }}",
        f"{py} -m pytest -q -p no:cacheprovider {selector(augmented_f2p, list(augmented_files))} "
        "> /tmp/augmented.txt 2>&1; echo CHESTERTON_AUGMENTED=$?",
        "echo '--- augmented tail'; tail -n 15 /tmp/augmented.txt",
    ])


def classify(error: str | None, stdout: str) -> str:
    if error is not None:
        return "sandbox_error"
    marks = dict(_MARK.findall(stdout))
    if "APPLY" in marks:
        return f"apply_failed:{marks['APPLY']}"
    original, augmented = marks.get("ORIGINAL"), marks.get("AUGMENTED")
    if original != "0":
        return "fails_original"  # sandbox does not reproduce "resolved"
    if augmented == "0":
        return "passes_augmented"
    if augmented == "1":
        return "WRONG"  # passed SWE-bench's tests, fails UTBoost's
    return f"error:augmented_exit_{augmented}"


async def screen(pool, iid: str, patch_dir: Path, original: dict, augmented: dict) -> dict:
    base = await pool.runner.use_image(image_for(iid))
    script = screen_script(
        _ids(original["FAIL_TO_PASS"]),
        _ids(augmented["FAIL_TO_PASS"]),
        _files(original["test_patch"]),
        _files(augmented["test_patch"]),
    )
    summary = json.loads((patch_dir / iid / "summary.json").read_text(encoding="utf-8"))

    async def one(entry: dict) -> dict:
        text = (patch_dir / iid / entry["patch"]).read_text(encoding="utf-8")
        if not any(is_mutable_source(f) for f in _files(text)):
            return {**entry, "verdict": "no_source_change"}
        result = await pool.run(base, script, files={
            AGENT: text, ORIGINAL: original["test_patch"], AUGMENTED: augmented["test_patch"],
        }, timeout=TIMEOUT_S)
        return {**entry, "verdict": classify(result.error, result.stdout),
                "tail": (result.stdout or "")[-1500:], "error": result.error}

    return {"instance": iid, "patches": await asyncio.gather(*(one(e) for e in summary))}


async def main(patch_dir: Path, instance_ids: list[str]) -> int:
    # One scan per dataset family, not two per task: scanning per task drew
    # HTTP 429 from the dataset API.
    async with httpx.AsyncClient(timeout=60) as http:
        originals = await fetch_swebench_rows(instance_ids, client=http)
        augmenteds = await fetch_swebench_rows(instance_ids, client=http, datasets=UTBOOST)

    runner = ConTreeSandboxRunner()
    total = sum(
        len(json.loads((patch_dir / iid / "summary.json").read_text(encoding="utf-8")))
        for iid in instance_ids
        if (patch_dir / iid / "summary.json").exists()
    )
    pool = SandboxPool(runner, op_budget=total)
    try:
        for iid in instance_ids:
            if (patch_dir / iid / "screen.json").exists():
                # Screening costs one sandbox op per patch; never pay twice.
                # Delete the file to re-screen a task.
                print(f"\n{iid}: already screened, skipped")
                continue
            if iid not in originals or iid not in augmenteds:
                print(f"\n{iid}: not in both datasets, skipped")
                continue
            report = await screen(pool, iid, patch_dir, originals[iid], augmenteds[iid])
            (patch_dir / iid / "screen.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            counts = Counter(p["verdict"] for p in report["patches"])
            print(f"\n{iid}: {dict(counts)}")
            for p in report["patches"]:
                if p["verdict"] == "WRONG":
                    print(f"  WRONG  {p['patch']}  passed SWE-bench for {len(p['submissions'])} "
                          f"submission(s), e.g. {p['submissions'][0]}")
    finally:
        await runner.aclose()
    print(f"\n{pool.ops_used} sandbox ops")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]), sys.argv[2:])))
