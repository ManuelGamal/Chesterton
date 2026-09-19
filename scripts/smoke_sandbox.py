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

results: list[tuple[str, bool, str, bool]] = []


def record(name: str, ok: bool, detail: str = "", *, errored: bool = False) -> bool:
    """`errored` marks a sandbox OPERATION failure (timeout, cancellation, a
    service error, or a bug in this script), as opposed to a check that ran
    to completion and came back false. The two must never share a diagnosis:
    an errored run proves nothing about the design question the check asks,
    and summarise() must not claim otherwise (see ruling on R2).
    """
    results.append((name, ok, detail, errored))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


async def main(image_ref: str) -> int:
    missing = [
        name
        for name in ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID")
        if not os.environ.get(name)
    ]
    if missing:
        sys.exit(
            f"Not set: {', '.join(missing)}.\n"
            "Sandboxes needs BOTH — it authorises on a Project header as well "
            "as a bearer token, and a request missing the project is rejected "
            "as ForbiddenError, which looks like a permissions problem but is "
            "not. Both values are at "
            "https://tokenfactory.nebius.com/project/api-keys"
        )

    runner = ConTreeSandboxRunner()  # credentials resolve from the environment
    started = time.perf_counter()

    # 1. Resolve an image. Proves auth, base URL, and the client construction
    #    this adapter was rewritten to get right.
    print(f"\n1. Resolving {image_ref!r} ...")
    try:
        base = await runner.use_image(image_ref)
        # bool(base) is not enough: an unresolved lazy handle stringifies to
        # "None", which is truthy. Demand something that looks like a real id.
        looks_real = bool(base) and base not in {"None", "none"} and len(base) > 8
        record("image resolves", looks_real, f"checkpoint {base!r}")
        if not looks_real:
            return summarise()
    except Exception as exc:
        record("image resolves", False, f"{type(exc).__name__}: {exc}")
        return summarise()

    # 2. Run one trivial command.
    print("\n2. Running a trivial command ...")
    try:
        r = await runner.run(base, "echo hello-from-sandbox")
    except Exception as exc:
        record("command executes", False, f"{type(exc).__name__}: {exc}", errored=True)
        return summarise()
    # An errored OPERATION (timeout, cancellation, service failure) comes back
    # as `.error` rather than a raised exception now — check it before
    # exit_code or stdout, which are meaningless (exit_code is always None) on
    # error. Read as a PASS or misdiagnosed as some other failure, this is
    # exactly the false-positive class this project keeps tripping on.
    if r.error is not None:
        record("command executes", False, r.error, errored=True)
        return summarise()
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
    except Exception as exc:
        record(
            "checkpoint persists with a new id",
            False,
            f"{type(exc).__name__}: {exc}",
            errored=True,
        )
        return summarise()
    if built.error is not None:
        record("checkpoint persists with a new id", False, built.error, errored=True)
        return summarise()
    ok = built.checkpoint_id is not None and built.checkpoint_id != base
    record("checkpoint persists with a new id", ok, f"id={built.checkpoint_id}")

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
    except Exception as exc:
        record(
            "forks inherit the parent filesystem",
            False,
            f"{type(exc).__name__}: {exc}",
            errored=True,
        )
    else:
        errors = [f.error for f in forks if f.error is not None]
        if errors:
            record(
                "forks inherit the parent filesystem",
                False,
                "; ".join(errors),
                errored=True,
            )
        else:
            both_ok = all(f.exit_code == 0 and "persisted" in f.stdout for f in forks)
            record(
                "forks inherit the parent filesystem",
                both_ok,
                f"exits={[f.exit_code for f in forks]}",
            )

    # 5. Network egress from inside a sandbox to the inference API. This is
    #    undocumented and an open community question. If it fails, any design
    #    that calls a model from inside a sandbox is dead and inference has to
    #    happen on the orchestrator instead.
    print(f"\n5. Probing egress to {INFERENCE_HOST} from inside a sandbox ...")
    try:
        dns = await runner.run(base, f"getent hosts {INFERENCE_HOST} || echo NO_DNS")
    except Exception as exc:
        record(
            "DNS resolves inside the sandbox",
            False,
            f"{type(exc).__name__}: {exc}",
            errored=True,
        )
    else:
        if dns.error is not None:
            record("DNS resolves inside the sandbox", False, dns.error, errored=True)
        else:
            record(
                "DNS resolves inside the sandbox",
                "NO_DNS" not in dns.stdout,
                dns.stdout.strip()[:80] or "(empty)",
            )

    try:
        tcp = await runner.run(
            base,
            "bash -c 'timeout 8 bash -c \"exec 3<>/dev/tcp/"
            f"{INFERENCE_HOST}/443\" && echo EGRESS_OK || echo EGRESS_BLOCKED'",
        )
    except Exception as exc:
        record(
            "TCP:443 egress permitted",
            False,
            f"{type(exc).__name__}: {exc}",
            errored=True,
        )
    else:
        if tcp.error is not None:
            record("TCP:443 egress permitted", False, tcp.error, errored=True)
        else:
            record(
                "TCP:443 egress permitted",
                "EGRESS_OK" in tcp.stdout,
                tcp.stdout.strip()[:80] or "(empty)",
            )

    print(f"\nTotal wall clock: {time.perf_counter() - started:.1f}s")
    await runner.aclose()
    return summarise()


#: ForbiddenError is an authorisation problem, not a design finding about
#: whatever step happened to hit it, so it fires on the error text regardless
#: of which check surfaced it (ruling on R2).
#:
#: Measured, not assumed: the first live ForbiddenError on this project was
#: diagnosed as a missing beta entitlement, and that was wrong — the project
#: header was carrying the wrong value. Check the cheap cause before writing to
#: support.
_FORBIDDEN_HINT = (
    "The error names ForbiddenError: the key authenticates but this request "
    "is not authorised. Sandboxes authorises on a Project header as well as "
    "the bearer token, so check NEBIUS_PROJECT_ID FIRST — it must be the "
    "project the key belongs to (both are at "
    "https://tokenfactory.nebius.com/project/api-keys). Only if that is "
    "right is this an entitlement problem, which needs access requested via "
    "the Token Factory console or contree@nebius.com."
)

#: Shown for a FAIL that came from an errored sandbox OPERATION (or an
#: unexpected bug in this script) rather than a check that ran to completion.
#: Such a failure proves nothing about the design question the check asks —
#: pairing it with that check's normal diagnosis is exactly the
#: "misdiagnosed as some other failure" defect this project keeps tripping on.
_ERRORED_HINT = (
    "This was a sandbox OPERATION failure (timeout, cancellation, a service "
    "error, or a bug in this script), not a completed check. It does not by "
    "itself confirm this check's usual design conclusion — see the error "
    "text above, and rule out an infrastructure problem before treating this "
    "as a finding."
)


def summarise() -> int:
    failed = [(n, d, errored) for n, ok, d, errored in results if not ok]
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
            "The SDK connects but cannot run anything."
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
    for name, detail, errored in failed:
        print(f"  {name}: {detail}")
        if "ForbiddenError" in detail:
            print(f"      -> {_FORBIDDEN_HINT}\n")
        elif errored:
            print(f"      -> {_ERRORED_HINT}\n")
        else:
            note = meanings.get(name)
            if note:
                print(f"      -> {note}\n")
    return 1


if __name__ == "__main__":
    ref = sys.argv[1] if len(sys.argv) > 1 else "ubuntu:latest"
    raise SystemExit(asyncio.run(main(ref)))
