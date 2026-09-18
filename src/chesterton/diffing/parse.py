"""Unified-diff parsing, delegated to unidiff (MIT).

Chesterton mutates the PATCH, so every line number here is a post-patch
(new file) coordinate. A hand-rolled parser was tried and rejected: it
recorded phantom added lines for deleted files and drifted by one line on
`\\ No newline at end of file`. Both corrupt line numbers with no visible
failure, and the spec treats that as the catastrophic case.

Deleted and binary files contribute nothing — there is no post-patch line
to mutate.
"""

from __future__ import annotations

from unidiff import PatchSet

from chesterton.paths import normalise_path


def changed_lines(diff: str) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}

    for patched_file in PatchSet(diff):
        if patched_file.is_binary_file or patched_file.is_removed_file:
            continue

        lines = [
            line.target_line_no
            for hunk in patched_file
            for line in hunk
            if line.is_added and line.target_line_no is not None
        ]
        result[normalise_path(patched_file.path)] = lines

    return result
