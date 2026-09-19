"""How often can CrossHair actually find a distinguishing input?

The spec's evidence ladder puts a solver-proved distinguishing input above a
surviving mutant, and §15 sets an acceptance bar: at least one curated seed
must produce one. CrossHair needs type-annotated, deterministic, side-effect-
free functions, and the spec's own estimate is that only 10-30% of changed
functions qualify.

This measures the ceiling before Phase 2b commits to building the tier. It
counts eligibility, not solver success — a function CrossHair cannot even
attempt is a function the tier will never help with.

Two kinds of check, of different quality. The annotation checks are exact.
The purity screen is a name heuristic: it catches calls and attribute access
rooted at known-impure modules, pathlib I/O methods and `self.<client>.get()`
style network calls, but impurity behind any other call is invisible. So the
eligible count is an upper bound and the impure count a lower one — an
earlier, narrower screen passed `self.session.get(url)`, `p.read_text()`,
`os.environ[name]` and `time.time()` as pure.

Usage:
    python scripts/probe_crosshair.py <file-or-dir> [...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Calls that make a function unanalysable by a solver.
_IMPURE_HINTS = {"open", "print", "input", "requests", "urlopen", "random"}

#: Modules whose attributes are I/O, process state, the clock or chance.
#: Touching one at all makes a function impure, called or not:
#: `os.environ[name]` reads process state without a call in sight.
_IMPURE_ROOTS = {
    "os",
    "sys",
    "time",
    "random",
    "socket",
    "subprocess",
    "shutil",
    "urllib",
    "requests",
    "httpx",
}

#: Methods that do I/O or read the clock whatever their receiver is called:
#: pathlib's file API, and the datetime constructors that read "now".
_IMPURE_METHODS = {
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "open",
    "exists",
    "is_file",
    "is_dir",
    "iterdir",
    "glob",
    "rglob",
    "mkdir",
    "unlink",
    "rmdir",
    "touch",
    "stat",
    "now",
    "today",
    "utcnow",
}

#: Verbs that mean a network call when sent to a client held on `self`, as
#: in `self.session.get(url)`.
_CLIENT_VERBS = {"get", "post", "put", "patch", "delete", "request", "send"}

#: Functions and coroutines walked by the probe.
_FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


def _call_root_name(func: ast.expr) -> str | None:
    """Resolve the leftmost name of a (possibly dotted) call target.

    ``requests.get(...)`` is an ``ast.Attribute`` whose value chain bottoms
    out at the ``ast.Name`` ``requests`` — nobody calls ``requests(...)``
    directly, so checking only bare names misses almost every real impure
    call. ``a.b.c()`` resolves to ``a``.
    """
    node = func
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def _eligible(fn: _FuncDef) -> tuple[bool, str]:
    if isinstance(fn, ast.AsyncFunctionDef):
        # CrossHair's symbolic execution does not drive coroutines: a
        # coroutine is not merely hard to analyse, it is never attempted.
        return False, "async def"

    all_args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
    args = [a for a in all_args if a.arg not in {"self", "cls"}]
    if not args:
        return False, "no arguments"
    if any(a.annotation is None for a in args):
        return False, "unannotated arguments"
    if fn.returns is None:
        return False, "no return annotation"

    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            reason = _impure_call(node.func)
            if reason:
                return False, reason
        if isinstance(node, ast.Attribute):
            root = _call_root_name(node)
            if root in _IMPURE_ROOTS:
                return False, f"uses {root}"
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return False, "mutates outer scope"
    return True, "eligible"


def _impure_call(func: ast.expr) -> str | None:
    """Why this call target is impure, or None if the heuristic sees nothing.

    Still a heuristic: it matches names, so an impure call behind an arbitrary
    helper is invisible and the function is counted eligible. Every gap here
    OVERSTATES eligibility.
    """
    root = _call_root_name(func)
    if root in _IMPURE_HINTS:
        return f"calls {root}()"
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr in _IMPURE_METHODS:
        return f"calls .{func.attr}()"
    receiver = func.value
    if (
        func.attr in _CLIENT_VERBS
        and isinstance(receiver, ast.Attribute)
        and _call_root_name(receiver) == "self"
    ):
        return f"calls self.<client>.{func.attr}()"
    return None


def scan(path: Path) -> list[tuple[str, bool, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    posix_path = path.as_posix()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ok, why = _eligible(node)
            out.append((f"{posix_path}:{node.name}", ok, why))
    return out


def main(targets: list[str]) -> int:
    files: list[Path] = []
    for target in targets:
        p = Path(target)
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])

    rows = [row for f in files for row in scan(f)]
    if not rows:
        print("No functions found.")
        return 1

    eligible = [r for r in rows if r[1]]
    print(f"{len(eligible)}/{len(rows)} functions are CrossHair-eligible "
          f"({100 * len(eligible) / len(rows):.0f}%)\n")

    reasons: dict[str, int] = {}
    for _, ok, why in rows:
        if not ok:
            reasons[why] = reasons.get(why, 0) + 1
    print("Why the rest are not:")
    for why, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {why}")

    print("\nEligible functions (CrossHair can at least attempt these):")
    for name, _, _ in eligible[:20]:
        print(f"  {name}")

    print(
        "\nEligibility is the CEILING, not the hit rate — the solver still has "
        "to find a difference within its budget. If eligibility is already "
        "under ~10%, Phase 2b is not worth building and the Hypothesis "
        "fallback should carry tier 1 alone."
    )
    print(
        "The purity screen is a name heuristic that OVERSTATES eligibility — "
        "impurity behind any call it cannot name goes unseen — while the "
        "annotation checks are exact. Do not quote the impure count as a fact."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["src/chesterton"]))
