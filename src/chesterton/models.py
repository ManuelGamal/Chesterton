"""Shared value types. Frozen dataclasses — nothing here mutates."""

from __future__ import annotations

from dataclasses import dataclass

# file path (forward slashes) -> line number -> test ids executing that line
CoverageMap = dict[str, dict[int, list[str]]]


@dataclass(frozen=True)
class PullRequest:
    owner: str
    repo: str
    number: int
    title: str
    base_sha: str
    head_sha: str
    merge_base_sha: str
    clone_url: str
    diff: str


@dataclass(frozen=True)
class Hunk:
    """A contiguous group of changed lines, in post-patch coordinates."""

    file: str
    start_line: int
    end_line: int

    @property
    def lines(self) -> list[int]:
        return list(range(self.start_line, self.end_line + 1))
