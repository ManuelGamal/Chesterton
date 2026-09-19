"""The PR's hunks as units ddmin can keep or revert.

A ddmin probe applies a subset of the PR by reverting every other source
hunk to its pre-patch text. Reverting is exact splicing on the HEAD text,
bottom-up so earlier edits cannot shift later line numbers. Every
coordinate comes from unidiff, whose conventions were measured rather than
assumed:

- A zero-length target (`@@ -3 +2,0 @@`) reports target_start=2, and the
  deletion sits AFTER that line, so it is re-inserted at index 2, not 1.
- An added file reports target 1,n with no source lines; reverting it
  empties the file.
- `\\ No newline at end of file` arrives as its own line after the line it
  qualifies, and that line's .value still ends in "\\n". Following a context
  or removed line, it means the BASE had no final newline, so the newline
  is stripped from the recorded source text.

Only mutable source files take part. Test files are the oracle, so reverting
them would be circular. Removed and binary files have no head text to
splice into.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from unidiff import PatchSet

from chesterton.filters import is_mutable_source
from chesterton.paths import normalise_path

_NO_NEWLINE = "\\"


@dataclass(frozen=True)
class PatchHunk:
    file: str
    index: int
    target_start: int
    target_length: int
    #: The pre-patch text of this hunk's span, one entry per line, with ends.
    source_lines: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.file}#{self.index}"


def _source_lines(hunk) -> tuple[str, ...]:
    lines: list[str] = []
    previous = None
    for line in hunk:
        if line.line_type == _NO_NEWLINE:
            if previous is not None and (previous.is_context or previous.is_removed) and lines:
                lines[-1] = lines[-1].removesuffix("\n")
        elif line.is_context or line.is_removed:
            lines.append(line.value)
        previous = line
    return tuple(lines)


def patch_hunks(diff: str) -> tuple[list[PatchHunk], dict[str, int]]:
    hunks: list[PatchHunk] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for patched in PatchSet(diff):
        path = normalise_path(patched.path)
        if patched.is_binary_file:
            skip("binary")
            continue
        if patched.is_removed_file:
            skip("removed_file")
            continue
        if not is_mutable_source(path):
            skip("not_mutable_source")
            continue
        for index, hunk in enumerate(patched):
            hunks.append(
                PatchHunk(
                    file=path,
                    index=index,
                    target_start=hunk.target_start,
                    target_length=hunk.target_length,
                    source_lines=_source_lines(hunk),
                )
            )
    return hunks, skipped


def revert(head_text: str, hunks: Iterable[PatchHunk]) -> str:
    lines = head_text.splitlines(keepends=True)
    for hunk in sorted(hunks, key=lambda h: h.target_start, reverse=True):
        start = hunk.target_start if hunk.target_length == 0 else hunk.target_start - 1
        lines[start : start + hunk.target_length] = list(hunk.source_lines)
    return "".join(lines)


def probe_files(
    sources: Mapping[str, str],
    workdir: str,
    hunks: Sequence[PatchHunk],
    keep: frozenset[PatchHunk],
) -> dict[str, str]:
    """The files a probe must write so that only `keep` stays applied.

    A file whose hunks are all kept is not written: the checkpoint already
    holds its head text.
    """
    reverted: dict[str, list[PatchHunk]] = defaultdict(list)
    for hunk in hunks:
        if hunk not in keep:
            reverted[hunk.file].append(hunk)
    return {
        f"{workdir.rstrip('/')}/{file}": revert(sources[file], file_hunks)
        for file, file_hunks in reverted.items()
    }
