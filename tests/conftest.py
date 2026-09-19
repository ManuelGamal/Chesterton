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
