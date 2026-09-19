"""Build a seed: the tagged baseline checkpoint every run forks from.

One persisted operation (ruling P3-4) applies the PR diff, installs
pytest-cov, and runs the suite three times. The first run is under coverage
contexts, single-threaded because contexts are unreliable under xdist
(spec §7). The results are read back as FILES (ruling P3-3): stdout is
truncated at 64 KiB, and a real coverage-contexts report is larger than that.

The three runs are what make a kill mean something. A test is selectable only
if it passed all three; flaky and always-failing tests would turn chance or
pre-existing failure into fabricated kills.
"""

from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone

from chesterton.covmap.invert import invert_coverage
from chesterton.diffing.parse import changed_lines
from chesterton.filters import is_mutable_source
from chesterton.models import PullRequest
from chesterton.paths import normalise_path
from chesterton.seed.outcomes import classify_runs, parse_outcomes
from chesterton.seed.record import SeedRecord, is_valid_slug, seed_tag

#: Where SWE-rebench images check the repository out (probe_images.py).
DEFAULT_WORKDIR = "/testbed"
DEFAULT_TEST_COMMAND = "python -m pytest"

#: Outside the repository, so nothing here can leak into a test run.
ARTIFACT_DIR = "/chesterton"
DIFF_PATH = f"{ARTIFACT_DIR}/pr.diff"
COVERAGE_PATH = f"{ARTIFACT_DIR}/coverage.json"
RUN_LOGS = (
    f"{ARTIFACT_DIR}/run1.txt",
    f"{ARTIFACT_DIR}/run2.txt",
    f"{ARTIFACT_DIR}/run3.txt",
)

#: Build time only. It is never on a judge's clock.
SEED_TIMEOUT_S = 1800.0

#: -rA prints one node-id line per test; the rest keeps runs deterministic
#: and leaves no cache behind in the checkpoint.
_PYTEST_FLAGS = "-q -rA -p no:randomly -p no:cacheprovider"


class SeedBuildError(RuntimeError):
    """The seed could not be built; the message says which stage failed."""


def _stage(name: str) -> str:
    # On stderr, so under `set -e` the last stage announced is the one that
    # failed. The first live build failed with no way to tell which it was.
    return f"echo 'chesterton: {name}' >&2"


def build_script(workdir: str, test_command: str) -> str:
    q = shlex.quote
    return "\n".join(
        [
            "set -e",
            f"mkdir -p {ARTIFACT_DIR}",
            f"cd {q(workdir)}",
            _stage("applying the PR diff"),
            f"git apply --whitespace=nowarn {DIFF_PATH}",
            _stage("installing pytest-cov"),
            # The env var silences pip's root-user warning, which otherwise
            # fills stderr. It is not the --root-user-action flag, because
            # older pip rejects that flag and would fail the build.
            "PIP_ROOT_USER_ACTION=ignore python -m pip install -q pytest-cov",
            _stage("baseline run 1 of 3, under coverage"),
            # `|| true` on every test run: a failing test is data here, not a
            # build failure. classify_runs sorts the outcomes out.
            f"{test_command} {_PYTEST_FLAGS} --cov --cov-context=test "
            f"--cov-report= > {RUN_LOGS[0]} 2>&1 || true",
            _stage("exporting coverage"),
            # Empty coverage means run 1 never got going, and the reason is in
            # its own output, so surface that rather than coverage's bare
            # "No data to report".
            f"python -m coverage json --show-contexts -o {COVERAGE_PATH} || "
            f"{{ echo 'chesterton: coverage recorded no data; the end of run 1 "
            f"follows' >&2; tail -n 40 {RUN_LOGS[0]} >&2; exit 1; }}",
            _stage("baseline runs 2 and 3"),
            f"{test_command} {_PYTEST_FLAGS} > {RUN_LOGS[1]} 2>&1 || true",
            f"{test_command} {_PYTEST_FLAGS} > {RUN_LOGS[2]} 2>&1 || true",
        ]
    )


def relative_to_workdir(path: str, workdir: str) -> str:
    prefix = normalise_path(workdir).rstrip("/") + "/"
    return normalise_path(path).removeprefix(prefix)


def _tail(text: str, lines: int = 20) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


async def build_seed(
    runner,
    pr: PullRequest,
    *,
    slug: str,
    image_ref: str,
    workdir: str = DEFAULT_WORKDIR,
    test_command: str = DEFAULT_TEST_COMMAND,
    timeout: float = SEED_TIMEOUT_S,
) -> SeedRecord:
    if not is_valid_slug(slug):
        raise ValueError(
            f"invalid slug {slug!r}: use lowercase letters, digits and hyphens"
        )

    base = await runner.use_image(image_ref)
    tag = seed_tag(slug)
    result = await runner.run(
        base,
        build_script(workdir, test_command),
        files={DIFF_PATH: pr.diff},
        disposable=False,
        tag=tag,
        timeout=timeout,
    )

    if result.error is not None:
        raise SeedBuildError(f"the seed build operation failed: {result.error}")
    if result.exit_code != 0:
        # Both streams: the stage markers are on stderr, but a tool's own
        # reason can be on stdout, and `stderr or stdout` hid it live.
        output = "\n".join(s for s in (result.stderr, result.stdout) if s)
        raise SeedBuildError(
            f"the seed build script exited {result.exit_code}; the last "
            "'chesterton:' stage below is the one that failed.\n" + _tail(output, 50)
        )
    checkpoint = result.checkpoint_id
    if checkpoint is None:
        raise SeedBuildError("the persisted build returned no checkpoint id")

    runs = [
        parse_outcomes((await runner.read_file(checkpoint, log)).decode("utf-8", "replace"))
        for log in RUN_LOGS
    ]
    selection = classify_runs(runs)
    if not selection.selectable:
        raise SeedBuildError(
            "no test passed in all three baseline runs, so nothing can be "
            "selected and every mutant would be uncovered"
        )

    report = json.loads((await runner.read_file(checkpoint, COVERAGE_PATH)).decode("utf-8"))
    coverage = {
        relative_to_workdir(path, workdir): lines
        for path, lines in invert_coverage(report).items()
    }

    sources: dict[str, str] = {}
    for file in sorted(changed_lines(pr.diff)):
        if is_mutable_source(file):
            raw = await runner.read_file(checkpoint, f"{workdir}/{file}")
            sources[file] = raw.decode("utf-8")

    return SeedRecord(
        slug=slug,
        pr=pr,
        image_ref=image_ref,
        workdir=workdir,
        test_command=test_command,
        checkpoint_id=checkpoint,
        checkpoint_tag=tag,
        coverage=coverage,
        selectable=selection.selectable,
        flaky=selection.flaky,
        failing=selection.failing,
        sources=sources,
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
