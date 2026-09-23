"""Fixtures shared across the Phase 3 test modules.

The demo seed is small enough to reason about by hand. It is a PR that adds
a guard to `charge`, plus a README line. The guard's `raise` is executed only
by a flaky test, which makes it a real tier-0 finding once coverage is
restricted to selectable tests (ruling P3-6).
"""

from __future__ import annotations

import pytest

from chesterton.models import PullRequest
from chesterton.seed.record import SeedRecord

DEMO_DIFF = (
    "--- a/pay.py\n"
    "+++ b/pay.py\n"
    "@@ -1,2 +1,4 @@\n"
    " def charge(amount):\n"
    "+    if not amount:\n"
    '+        raise ValueError("required")\n'
    "     return amount\n"
    "--- a/README.md\n"
    "+++ b/README.md\n"
    "@@ -1 +1,2 @@\n"
    " # Pay\n"
    "+Charges must be non-zero.\n"
)

HEAD_PAY = (
    "def charge(amount):\n"
    "    if not amount:\n"
    '        raise ValueError("required")\n'
    "    return amount\n"
)

T_CHARGE = "tests/test_pay.py::test_charge"
T_FLAKY = "tests/test_pay.py::test_flaky"


@pytest.fixture
def demo_seed() -> SeedRecord:
    pr = PullRequest(
        owner="acme",
        repo="pay",
        number=1,
        title="Require a non-zero amount",
        base_sha="b" * 40,
        head_sha="h" * 40,
        merge_base_sha="b" * 40,
        clone_url="https://github.com/acme/pay.git",
        diff=DEMO_DIFF,
    )
    return SeedRecord(
        slug="demo",
        pr=pr,
        image_ref="docker://example/pay",
        workdir="/testbed",
        test_command="python -m pytest",
        checkpoint_id="ckpt-seed",
        checkpoint_tag="chesterton:seed-demo",
        coverage={"pay.py": {1: [T_CHARGE], 2: [T_CHARGE], 3: [T_FLAKY], 4: [T_CHARGE]}},
        selectable=frozenset({T_CHARGE}),
        flaky=frozenset({T_FLAKY}),
        failing=frozenset(),
        sources={"pay.py": HEAD_PAY},
        built_at="2026-09-19T00:00:00+00:00",
    )


from chesterton.execute.mutants import MutantResult  # noqa: E402
from chesterton.mutation.model import Mutant  # noqa: E402

#: The demo module with its guard deleted: lines 2-3 are gone.
NO_GUARD = "def charge(amount):\n    return amount\n"


def a_survivor(
    mutated_src: str,
    *,
    start: int = 2,
    end: int = 3,
    rationale: str = "",
    tests: tuple[str, ...] = (T_CHARGE,),
    original: str = HEAD_PAY,
    file: str = "pay.py",
    verdict: str = "survived",
) -> MutantResult:
    mutant = Mutant(
        file=file, start_line=start, end_line=end, operator="semantic",
        original_src=original, mutated_src=mutated_src, rationale=rationale,
        source="llm",
    )
    return MutantResult(mutant, verdict, tests)


import json as _json  # noqa: E402


class ScriptedClient:
    """A NemotronClient stand-in: answers by prompt content, records every call."""

    def __init__(self, reply=None, *, raises=None, by_marker=None):
        self.reply, self.raises = reply, raises
        self.by_marker = dict(by_marker or {})
        self.calls: list[dict] = []

    async def complete(self, prompt, *, model, max_tokens=2048, thinking=False):
        self.calls.append(
            {"prompt": prompt, "model": model, "max_tokens": max_tokens, "thinking": thinking}
        )
        if self.raises is not None:
            raise self.raises
        for marker, replies in self.by_marker.items():
            if marker in prompt:
                return replies.pop(0) if isinstance(replies, list) else replies
        return self.reply


def finding_reply(
    label="untested_invariant", category="safety", confident=True,
    explanation="the guard is never exercised",
) -> str:
    return _json.dumps(
        {"label": label, "category": category, "confident": confident,
         "explanation": explanation}
    )
