"""Live smoke test: does the sandbox path work at all?

Deliberately separate from `spike_fanout.py`. This answers "does any of this
function" — the spike answers "is it fast enough". Keeping them apart means a
failure tells you which question you are looking at.

Usage:
    python scripts/smoke_sandbox.py [image-ref]

Defaults to `ubuntu:latest`. Needs NEBIUS_API_KEY. Costs a handful of trivial
sandbox operations.

Every check is independent and prints PASS or FAIL with the real error. The
summary at the end says what each failure would mean for the design, because
"it broke" is not actionable at 2am.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from chesterton.sandbox.contree import ConTreeSandboxRunner

INFERENCE_HOST = "api.tokenfactory.nebius.com"

#: Written by one run, read back by its forks. If this survives, checkpointing
#: — the mechanic the whole project rests on — genuinely works.
SENTINEL = "/tmp/chesterton-sentinel"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


async def main(image_ref: str) -> int:
    if not os.environ.get("NEBIUS_API_KEY"):
        sys.exit("NEBIUS_API_KEY is not set.")

    runner = ConTreeSandboxRunner(os.environ["NEBIUS_API_KEY"])
    started = time.perf_counter()

    # 1. Resolve an image. Proves auth, base URL, and the client construction
    #    this adapter was rewritten to get right.
    print(f"\n1. Resolving {image_ref!r} ...")
    try:
        base = await runner.use_image(image_ref)
        record("image resolves", bool(base), f"checkpoint {base}")
    except Exception as exc:
        record("image resolves", False, f"{type(exc).__name__}: {exc}")
        return summarise()

    # 2. Run one trivial command.
    print("\n2. Running a trivial command ...")
    try:
        r = await runner.run(base, "echo hello-from-sandbox")
        record(
            "command executes",
            r.exit_code == 0 and "hello-from-sandbox" in r.stdout,
            f"exit={r.exit_code} stdout={r.stdout.strip()!r}",
        )
        record(
            "disposable run yields no checkpoint",
            r.checkpoint_id is None,
            f"checkpoint_id={r.checkpoint_id!r}",
        )
    except Exception as exc:
        record("command executes", False, f"{type(exc).__name__}: {exc}")
        return summarise()

    # 3. Persist a checkpoint, tagged. Untagged images can be garbage-collected
    #    and judging is six weeks after submission, so tagging must work.
    print("\n3. Creating a tagged checkpoint ...")
    try:
        built = await runner.run(
            base,
            f"echo persisted > {SENTINEL}",
            disposable=False,
            tag="chesterton:smoke",
        )
        ok = built.checkpoint_id is not None and built.checkpoint_id != base
        record("checkpoint persists with a new id", ok, f"id={built.checkpoint_id}")
    except Exception as exc:
        record("checkpoint persists", False, f"{type(exc).__name__}: {exc}")
        return summarise()

    if built.checkpoint_id is None:
        return summarise()

    # 4. Fork it twice, concurrently. This is the project's core mechanic in
    #    miniature: does forked state actually carry the parent's filesystem?
    print("\n4. Forking that checkpoint twice, concurrently ...")
    try:
        forks = await asyncio.gather(
            runner.run(built.checkpoint_id, f"cat {SENTINEL}"),
            runner.run(built.checkpoint_id, f"cat {SENTINEL}"),
        )
        both_ok = all(f.exit_code == 0 and "persisted" in f.stdout for f in forks)
        record(
            "forks inherit the parent filesystem",
            both_ok,
            f"exits={[f.exit_code for f in forks]}",
        )
    except Exception as exc:
        record("forks inherit parent filesystem", False, f"{type(exc).__name__}: {exc}")

    # 5. Network egress from inside a sandbox to the inference API. This is
    #    undocumented and an open community question. If it fails, any design
    #    that calls a model from inside a sandbox is dead and inference has to
    #    happen on the orchestrator instead.
    print(f"\n5. Probing egress to {INFERENCE_HOST} from inside a sandbox ...")
    try:
        dns = await runner.run(base, f"getent hosts {INFERENCE_HOST} || echo NO_DNS")
        record(
            "DNS resolves inside the sandbox",
            "NO_DNS" not in dns.stdout,
            dns.stdout.strip()[:80] or "(empty)",
        )

        tcp = await runner.run(
            base,
            "bash -c 'timeout 8 bash -c \"exec 3<>/dev/tcp/"
            f"{INFERENCE_HOST}/443\" && echo EGRESS_OK || echo EGRESS_BLOCKED'",
        )
        record(
            "TCP:443 egress permitted",
            "EGRESS_OK" in tcp.stdout,
            tcp.stdout.strip()[:80] or "(empty)",
        )
    except Exception as exc:
        record("egress probe", False, f"{type(exc).__name__}: {exc}")

    print(f"\nTotal wall clock: {time.perf_counter() - started:.1f}s")
    await runner.aclose()
    return summarise()


def summarise() -> int:
    failed = [(n, d) for n, ok, d in results if not ok]
    print("\n" + "=" * 62)
    if not failed:
        print("ALL CHECKS PASSED — the sandbox path works end to end.")
        print("Next: scripts/spike_fanout.py, which answers whether it is FAST enough.")
        return 0

    print(f"{len(failed)} CHECK(S) FAILED\n")
    meanings = {
        "image resolves": (
            "Auth, base URL, or client construction is wrong. Nothing else can "
            "work until this does. Check the key and the /sandboxes base URL."
        ),
        "command executes": (
            "The SDK connects but cannot run anything. Compare against the "
            "surface pinned in tests/test_sandbox_contree.py."
        ),
        "checkpoint persists with a new id": (
            "disposable=False is not producing a reusable checkpoint. The entire "
            "fan-out design depends on this; stop and re-read the SDK docs."
        ),
        "forks inherit the parent filesystem": (
            "Forked sandboxes do not carry parent state. This invalidates the "
            "checkpoint-and-fork architecture in spec section 4 — escalate before "
            "building anything else."
        ),
        "TCP:443 egress permitted": (
            "Sandboxes cannot reach the inference API. Not fatal: keep all model "
            "calls on the orchestrator and use sandboxes purely for execution. "
            "Record the finding in spec section 15."
        ),
        "DNS resolves inside the sandbox": (
            "No name resolution inside sandboxes — same consequence as blocked "
            "egress. Keep inference on the orchestrator."
        ),
    }
    for name, detail in failed:
        print(f"  {name}: {detail}")
        note = meanings.get(name)
        if note:
            print(f"      -> {note}\n")
    return 1


if __name__ == "__main__":
    ref = sys.argv[1] if len(sys.argv) > 1 else "ubuntu:latest"
    raise SystemExit(asyncio.run(main(ref)))
