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

import re

from unidiff import PatchSet

from chesterton.paths import normalise_path

#: `diff --git a/x b/x`, and the quoted form git uses for non-ASCII or
#: special characters: `diff --git "a/testim\303\244ge.png" "b/..."`.
_HEADER = re.compile(r'^diff --git ("?)a/(?P<a>.+?)\1 ("?)b/(?P<b>.+?)\3$')


def _decode(path: str) -> str:
    """Undo git's C-style quoting of a path, e.g. `testim\\303\\244ge.png`."""
    if "\\" not in path:
        return normalise_path(path)
    try:
        raw = path.encode("ascii").decode("unicode_escape").encode("latin-1")
        return normalise_path(raw.decode("utf-8"))
    except (UnicodeDecodeError, UnicodeEncodeError):
        return normalise_path(path)


def split_by_file(diff: str) -> list[tuple[str, str]]:
    """(path, section) per file, tolerating diffs unidiff will not parse.

    Agent patches from SWE-bench submissions are sometimes truncated — a hunk
    header promising more lines than the body carries — and `unidiff` raises
    on those (live 2026-09-20). They still apply under `patch --fuzz`, and
    SWE-bench's own harness counted them, so reading them by header is the
    honest thing to do. The sections concatenate back to the input exactly.
    """
    sections: list[tuple[str, str]] = []
    lines: list[str] = []
    path: str | None = None
    for line in diff.splitlines(keepends=True):
        match = _HEADER.match(line.rstrip("\n"))
        if match:
            if path is not None:
                sections.append((path, "".join(lines)))
            path, lines = _decode(match.group("b")), []
        if path is not None:
            lines.append(line)
    if path is not None:
        sections.append((path, "".join(lines)))
    return sections


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
