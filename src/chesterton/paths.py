"""One path spelling, everywhere.

coverage.py records native separators; GitHub diffs always use forward
slashes. If the two ever meet unnormalised, every lookup misses and every
hunk looks uncovered — silently, with green tests. Normalise at the boundary.
"""

from __future__ import annotations


def normalise_path(path: str) -> str:
    # removeprefix, not lstrip: lstrip strips CHARACTERS, so lstrip("./")
    # would turn ".hidden/x.py" into "hidden/x.py".
    return path.replace("\\", "/").removeprefix("./")
