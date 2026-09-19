"""Do the prebuilt SWE-rebench images pull, and are they usable as seeds?

This is the last unverified claim in the spec. The plan's whole scoping
decision — curated seeds, no arbitrary repositories — rests on Nebius having
published ~7,500 prebuilt images, a claim that came from a HuggingFace
discussion thread rather than formal docs.

"Does it pull" is only half the question. An image that resolves but has no
repository checked out, or no interpreter, is useless to us. So each candidate
is checked three ways.

Image names come from the `docker_image` field of the SWE-rebench dataset:
    https://huggingface.co/datasets/nebius/SWE-rebench
    namespace `swerebench/`, format sweb.eval.x86_64.<owner>_<pr>_<repo>-<n>

Usage:
    python scripts/probe_images.py [image-ref ...]

Needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID. Pulls can be slow and large — the
first one is the expensive one, so be patient before concluding it hangs.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from chesterton.sandbox.contree import ConTreeSandboxRunner

#: A spread of real entries from the dataset's test split. Small, unglamorous
#: libraries on purpose — a seed PR wants a fast deterministic suite, not a
#: famous name with a thirty-minute test run.
CANDIDATES = [
    "swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64",
    "swerebench/sweb.eval.x86_64.iamconsortium_1776_nomenclature-284",
    "swerebench/sweb.eval.x86_64.humancompatibleai_1776_overcooked_ai-104",
    "swerebench/sweb.eval.x86_64.12rambau_1776_sepal_ui-411",
]

#: SWE-bench-family images conventionally check the repository out here.
REPO_PATH = "/testbed"


async def probe(runner: ConTreeSandboxRunner, ref: str) -> dict:
    out: dict = {"ref": ref, "pulled": False, "repo": False, "python": None}

    started = time.perf_counter()
    try:
        checkpoint = await runner.use_image(f"docker://{ref}")
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["seconds"] = time.perf_counter() - started
        return out

    out["pulled"] = True
    out["checkpoint"] = checkpoint
    out["seconds"] = time.perf_counter() - started

    # A pulled image with no repository in it is not a seed.
    try:
        ls = await runner.run(checkpoint, f"ls {REPO_PATH} 2>/dev/null | head -5")
    except Exception as exc:
        out["repo_error"] = f"{type(exc).__name__}: {exc}"
    else:
        # An errored OPERATION (timeout, cancellation, service failure) comes
        # back as `.error`, not a raised exception. Left unchecked, `repo`
        # stays False — indistinguishable from a genuine empty repository,
        # which is a fabricated "no repo" finding on an image we never
        # actually inspected.
        if ls.error is not None:
            out["repo_error"] = ls.error
        else:
            out["repo"] = ls.exit_code == 0 and bool(ls.stdout.strip())
            out["repo_sample"] = ls.stdout.strip().replace("\n", ", ")[:70]

    # And one with no interpreter cannot run a test suite.
    try:
        py = await runner.run(checkpoint, "python --version 2>&1 || python3 --version 2>&1")
    except Exception as exc:
        out["python_error"] = f"{type(exc).__name__}: {exc}"
    else:
        if py.error is not None:
            out["python_error"] = py.error
        else:
            out["python"] = py.stdout.strip()[:40] or None

    return out


async def main(refs: list[str]) -> int:
    missing = [
        n for n in ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID") if not os.environ.get(n)
    ]
    if missing:
        sys.exit(f"Not set: {', '.join(missing)}. Both are required for Sandboxes.")

    runner = ConTreeSandboxRunner()
    results = []

    print(f"Probing {len(refs)} candidate image(s). The first pull is the slow one.\n")
    for i, ref in enumerate(refs, 1):
        short = ref.split(".")[-1]
        print(f"{i}/{len(refs)}  {short} ...", flush=True)
        r = await probe(runner, ref)
        results.append(r)

        if not r["pulled"]:
            print(f"     FAIL  ({r['seconds']:.1f}s) {r.get('error', '')}\n")
            continue

        print(f"     pulled in {r['seconds']:.1f}s -> {r['checkpoint']}")
        if r.get("repo_error"):
            repo_status = f"ERROR — {r['repo_error']}"
        elif r["repo"]:
            repo_status = "yes — " + r.get("repo_sample", "")
        else:
            repo_status = "EMPTY"
        print(f"     {REPO_PATH}: {repo_status}")
        if r.get("python_error"):
            python_status = f"ERROR — {r['python_error']}"
        else:
            python_status = r["python"] or "NOT FOUND"
        print(f"     python: {python_status}\n")

    await runner.aclose()

    usable = [r for r in results if r["pulled"] and r["repo"] and r["python"]]
    print("=" * 62)
    print(f"{len(usable)}/{len(results)} candidate(s) usable as seeds.\n")

    if usable:
        fastest = min(usable, key=lambda r: r["seconds"])
        print("Usable:")
        for r in usable:
            print(f"  {r['ref']}  ({r['seconds']:.1f}s)")
        print(f"\nNext: re-run the fan-out spike against a real suite, e.g.\n")
        print(f'  python scripts/spike_fanout.py docker://{fastest["ref"]} "python -m pytest -q -x" 3')
        print(
            "\nThe earlier spike used a synthetic sleep. Real suites contend for "
            "CPU and I/O, so the number will be worse — that is the point of "
            "measuring it."
        )
        return 0

    print(
        "No usable image. If every candidate failed to pull, the ~7,500 prebuilt\n"
        "images claim does not hold as documented, and the curated-seed scoping\n"
        "decision in the plan needs revisiting — building environments per repo\n"
        "is the problem SWE-bench spent years on, so that is a scope change, not\n"
        "an afternoon of work."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:] or CANDIDATES)))
