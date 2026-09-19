"""Everything a run needs from build time, in one serialisable record.

A seed is built once, ahead of the demo, and never on a judge's clock:
prebuilt image pulls alone measured 88-225 s (spec §15). The record carries
the tagged checkpoint to fork from, the coverage map, which tests are safe
to select, and the post-patch text of every changed source file. A run needs
nothing else, and needs no GitHub call.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from chesterton.models import CoverageMap, PullRequest

#: Lowercase letters, digits and hyphens: safe inside a checkpoint tag.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG.match(slug))


def seed_tag(slug: str) -> str:
    return f"chesterton:seed-{slug}"


@dataclass(frozen=True)
class SeedRecord:
    slug: str
    pr: PullRequest
    image_ref: str
    workdir: str
    test_command: str
    checkpoint_id: str
    checkpoint_tag: str
    coverage: CoverageMap
    selectable: frozenset[str]
    flaky: frozenset[str]
    failing: frozenset[str]
    sources: dict[str, str]
    built_at: str
    #: The test files the baseline, mutant fan-out and ddmin probes are scoped
    #: to. Empty means the whole suite. SWE-bench likewise runs only the files
    #: a task touches; the whole of sympy three times over would take hours.
    test_paths: tuple[str, ...] = ()

    def to_json(self) -> str:
        payload = asdict(self)
        for name in ("selectable", "flaky", "failing"):
            payload[name] = sorted(payload[name])
        # JSON object keys are strings; line numbers are restored on load.
        payload["coverage"] = {
            file: {str(line): tests for line, tests in lines.items()}
            for file, lines in self.coverage.items()
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> SeedRecord:
        payload = json.loads(text)
        payload["pr"] = PullRequest(**payload["pr"])
        for name in ("selectable", "flaky", "failing"):
            payload[name] = frozenset(payload[name])
        payload["coverage"] = {
            file: {int(line): tests for line, tests in lines.items()}
            for file, lines in payload["coverage"].items()
        }
        # Records written before scoping existed carry no test_paths.
        payload["test_paths"] = tuple(payload.get("test_paths", ()))
        return cls(**payload)
