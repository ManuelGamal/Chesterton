"""Which files are worth mutating at all.

Two exclusions, for different reasons.

Non-Python files cannot be parsed, so `semantic_hunks` falls back to one hunk
per line and every changed line of a README becomes a confident "no test
defends this" finding. That is fabricated evidence, which is the one thing
this project must not produce.

Test files are excluded because mutating a test and then running that same
test is circular — the file covers itself, the mutant always dies, and the
result carries no information.
"""

from __future__ import annotations

from chesterton.paths import normalise_path

#: Directory names that mark a test tree.
_TEST_DIRS = {"test", "tests"}


def is_mutable_source(path: str) -> bool:
    if not path:
        return False

    normalised = normalise_path(path)
    if not normalised.endswith(".py"):
        return False

    parts = normalised.split("/")
    name = parts[-1]

    # Whole-segment matching, not substring: "latest_release.py" is not a test.
    if any(part in _TEST_DIRS for part in parts[:-1]):
        return False
    if name == "conftest.py":
        return False
    if name.startswith("test_") or name.endswith("_test.py"):
        return False

    return True
