"""Go/no-go measurement: forking one checkpoint 24 ways and running tests.

Usage:
    python scripts/spike_fanout.py <image-ref> "<test-command>" [rounds]

Example:
    python scripts/spike_fanout.py docker://<swe-rebench-image> "pytest -q -x" 3

Reports wall clock, per-fork distribution, failure count, and round-to-round
variance. Phase 2's tier design depends on all four.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time

from chesterton.sandbox.contree import ConTreeSandboxRunner

FANOUT = 24
TARGET_SECONDS = 20.0


async def one_fork(runner, checkpoint_id: str, test_cmd: str) -> tuple[float, bool]:
    start = time.perf_counter()
    try:
        result = await runner.run(checkpoint_id, test_cmd, disposable=True)
        ok = result.exit_code in (0, 1)  # 1 == tests ran and failed; still a run
    except Exception as exc:  # an errored op is never a result
        print(f"  fork errored: {type(exc).__name__}: {exc}")
        return time.perf_counter() - start, False
    return time.perf_counter() - start, ok


async def one_round(runner, checkpoint_id: str, test_cmd: str) -> dict:
    sem = asyncio.Semaphore(FANOUT)

    async def guarded() -> tuple[float, bool]:
        async with sem:
            return await one_fork(runner, checkpoint_id, test_cmd)

    start = time.perf_counter()
    outcomes = await asyncio.gather(*(guarded() for _ in range(FANOUT)))
    wall = time.perf_counter() - start

    timings = [t for t, _ in outcomes]
    failures = sum(1 for _, ok in outcomes if not ok)
    return {
        "wall": wall,
        "median": statistics.median(timings),
        "p_slowest": max(timings),
        "failures": failures,
    }


async def main(image_ref: str, test_cmd: str, rounds: int) -> None:
    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        sys.exit("NEBIUS_API_KEY is not set — the spike needs a real key.")

    runner = ConTreeSandboxRunner(api_key)

    print(f"Resolving {image_ref} ...")
    t0 = time.perf_counter()
    base = await runner.use_image(image_ref)
    print(f"  resolved in {time.perf_counter() - t0:.1f}s")

    print("Building and TAGGING the baseline checkpoint ...")
    t0 = time.perf_counter()
    prepped = await runner.run(
        base, test_cmd, disposable=False, tag="chesterton:spike-base"
    )
    build = time.perf_counter() - t0
    if prepped.checkpoint_id is None:
        sys.exit("Non-disposable run returned no checkpoint id — adapter bug.")
    print(f"  built in {build:.1f}s -> {prepped.checkpoint_id}")
    print("  (tagged: untagged checkpoints may be garbage-collected)")

    results = []
    for i in range(rounds):
        print(f"\nRound {i + 1}/{rounds}: forking {FANOUT} ways, running tests ...")
        r = await one_round(runner, prepped.checkpoint_id, test_cmd)
        results.append(r)
        print(
            f"  wall {r['wall']:.1f}s | median fork {r['median']:.2f}s | "
            f"slowest {r['p_slowest']:.2f}s | failed {r['failures']}/{FANOUT}"
        )

    walls = [r["wall"] for r in results]
    worst = max(walls)
    spread = max(walls) - min(walls)
    total_failures = sum(r["failures"] for r in results)

    print("\n=== SPIKE RESULT ===")
    print(f"  baseline build     : {build:.1f}s (one-time, cached)")
    print(f"  worst-case wall    : {worst:.1f}s over {rounds} round(s)")
    print(f"  round-to-round spread: {spread:.1f}s")
    print(f"  failed forks       : {total_failures}/{FANOUT * rounds}")
    print(f"\n  VERDICT: {'GO' if worst < TARGET_SECONDS else 'REDESIGN — see spec section 15'}")
    print("  Record all four numbers in spec section 15.")

    await runner.aclose()


if __name__ == "__main__":
    cmd = sys.argv[2] if len(sys.argv) > 2 else "pytest -q"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    asyncio.run(main(sys.argv[1], cmd, n))
