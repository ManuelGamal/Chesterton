"""Which interpreter in an image can actually run the repository's tests?

The first live seed build (nomenclature-284, 2026-09-19) applied the PR and
installed pytest-cov cleanly, then failed with "ModuleNotFoundError: No module
named 'pandas'" loading the repository's own conftest. The PR does not touch
that conftest or any dependency. Yet the fan-out spike had run pytest in the
same image with every fork exiting 0 or 1, so pandas imported there.

Two explanations fit, and this answers both in ONE disposable sandbox op:

  1. The dependencies live in an environment (conda, venv) that the plain
     `python` on PATH is not. Every candidate interpreter is listed with
     whether it can import the modules named on the command line.
  2. `pip install pytest-cov` itself changes what `python` resolves to, or
     breaks the environment. The same import check runs before and after it.

It also runs a collect-only pytest from the repository, as the seed build
would, and prints its exit code.

Usage:
    python scripts/probe_interpreter.py <image-ref> [module ...]

    python scripts/probe_interpreter.py \\
        docker://swerebench/sweb.eval.x86_64.iamconsortium_1776_nomenclature-284 \\
        pandas nomenclature

Needs NEBIUS_API_KEY and NEBIUS_PROJECT_ID. Costs one disposable sandbox op.
"""

from __future__ import annotations

import asyncio
import shlex
import sys

from chesterton.sandbox.contree import ConTreeSandboxRunner

REPO_PATH = "/testbed"

#: Where SWE-bench-family images tend to keep their environments. Globs that
#: match nothing are dropped by `ls -d ... 2>/dev/null`.
CANDIDATE_GLOBS = (
    "/opt/*/envs/*/bin/python",
    "/opt/*/bin/python",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
    "/root/.venv/bin/python",
    f"{REPO_PATH}/.venv/bin/python",
)


def probe_script(modules: list[str]) -> str:
    imports = ", ".join(["pytest", *modules])
    check = shlex.quote(f"import sys, {imports}; print(sys.executable)")
    globs = " ".join(CANDIDATE_GLOBS)
    return "\n".join(
        [
            "echo '== shell'",
            'echo "whoami=$(whoami) default pwd=$(pwd)"',
            # From the repository, as the seed build runs, so the repo's own
            # package imports the way its tests would import it.
            f"cd {REPO_PATH}",
            'echo "PATH=$PATH"',
            "echo \"python on PATH: $(command -v python) | python3: $(command -v python3)\"",
            "echo '== candidate interpreters (import check BEFORE pip install)'",
            f"for p in $(command -v python) $(ls -d {globs} 2>/dev/null); do",
            f'  printf "%s -> " "$p"; "$p" -c {check} 2>&1 | tail -n 1',
            "done",
            "echo '== environment activation hints'",
            "tail -n 5 /root/.bashrc 2>/dev/null",
            "ls /etc/profile.d 2>/dev/null",
            "echo '== collect-only pytest from the repository, plain python'",
            "python -m pytest -q --co > /tmp/chesterton-co.txt 2>&1; "
            'echo "collect exit=$?"',
            "tail -n 4 /tmp/chesterton-co.txt",
            "echo '== pip install pytest-cov, then the same import check'",
            "PIP_ROOT_USER_ACTION=ignore python -m pip install -q pytest-cov 2>&1 | tail -n 3",
            "echo \"python on PATH now: $(command -v python)\"",
            f"python -c {check} 2>&1 | tail -n 1",
        ]
    )


async def main(image_ref: str, modules: list[str]) -> int:
    runner = ConTreeSandboxRunner()
    try:
        base = await runner.use_image(image_ref)
        result = await runner.run(base, probe_script(modules), timeout=600)
    finally:
        await runner.aclose()

    # An errored operation is not a result; say so rather than print nothing.
    if result.error is not None:
        print(f"probe operation failed: {result.error}")
        return 1
    print(result.stdout)
    if result.stderr.strip():
        print("--- stderr ---")
        print(result.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2:])))
